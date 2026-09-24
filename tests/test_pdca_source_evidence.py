"""Independent PDCA route contract, tested with isolated synthetic records."""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from apps.api.dy_api.models import DimSkuProductRule, DimStorePoiMapping, RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord, RawDouyinRefundRecord
from dy_api import pdca_readonly_access
from dy_api.auth import create_session_token
from dy_api.routes import pdca_sources

PARAMS = {'dataset': 'orders', 'periodStart': '2026-08-01', 'periodEnd': '2026-08-07',
          'observedThrough': '2026-09-01T00:00:00+08:00'}


@pytest.mark.parametrize('receipt,discounts,total_discount,expected', [
    (16000, [{'platform_discount_amount': 800}], 800, 16800),
    ('16000', [{'platform_discount_amount': '300'}, {'platform_discount_amount': 500}], 800, 16800),
    (0, [], 0, 0),
    (16800, None, 0, 16800),
    (None, [], 0, None),
    (True, [], 0, None),
    (168.5, [], 0, None),
    (-1, [], 0, None),
    (16800, None, None, None),
    (16800, None, False, None),
    (16800, [], 100, None),
    (16800, [{'platform_discount_amount': 200}], 100, None),
    (16800, [{'platform_discount_amount': None}], 100, None),
    (16800, [{'platform_discount_amount': True}], 100, None),
    (16800, [{'platform_discount_amount': -1}], 100, None),
])
def test_receipt_evidence_never_substitutes_user_payment(
        client, db_session, receipt, discounts, total_discount, expected):
    order = db_session.query(RawDouyinOrder).filter_by(order_id='A').one()
    order.raw_payload = {'receipt_amount': receipt, 'discounts': discounts,
                         'discount_amount': total_discount, 'pay_amount': 99999,
                         'secret': 'must-not-be-returned'}
    db_session.commit()
    response = client.get('/api/v1/admin/pdca-source-evidence', params=PARAMS)
    assert response.status_code == 200
    row = response.json()['data']['rows'][0]
    assert row.get('order_receipt_candidate_cent', 'missing') == expected
    assert response.json()['meta']['amount_semantics_verified'] is False
    assert row['paid_amount_cent'] == 16800  # Existing field stays unchanged.
    assert 'must-not-be-returned' not in response.text


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setenv('DY_API_TEST_MODE', '1')
    monkeypatch.setenv('DY_SUPER_ADMIN_USERNAME', 'synthetic-admin')
    monkeypatch.setenv('DY_TEST_ADMIN_PASSWORD', 'synthetic-password')
    monkeypatch.setattr(pdca_readonly_access, 'get_engine', lambda: db_session.get_bind())
    db_session.add(DimSkuProductRule(sku_id='SKU', product_id='PRODUCT', product_scope='精诚养车', product_type='保养'))
    for identity, created in [('A', datetime(2026, 7, 31, 16)), ('B', datetime(2026, 8, 3)),
                              ('OLD', datetime(2026, 7, 1)), ('END', datetime(2026, 8, 7, 16))]:
        db_session.add(RawDouyinOrder(order_id=identity, sku_id='SKU', create_order_time=created,
                                      sale_time=datetime(2026, 8, 3), paid_amount_cent=16800,
                                      product_name='synthetic-product', raw_payload={'secret': 'never-export'}))
    db_session.flush()
    db_session.add(RawDouyinOrderCoupon(coupon_id='C', order_id='A'))
    db_session.add(RawDouyinVerifyRecord(verify_id='V', coupon_id='C', sku_id='SKU',
                                        verify_status='success', verify_time=datetime(2026, 8, 5),
                                        cancel_time=datetime(2026, 8, 6)))
    db_session.commit()
    app = FastAPI()
    app.include_router(pdca_sources.router, prefix='/api/v1/admin')
    with TestClient(app) as client:
        client.cookies.set('dy_session', create_session_token('synthetic-admin', role='highest_admin'))
        yield client


def test_order_cohort_retains_no_coupon_and_excludes_sale_only_old_orders(client):
    response = client.get('/api/v1/admin/pdca-source-evidence', params=PARAMS)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [row['order_id'] for row in payload['data']['rows']] == ['A', 'B']
    assert payload['data']['rows'][0]['paid_amount_cent'] == 16800
    assert payload['meta']['collection_complete_through'] is None
    assert payload['meta']['consistent_snapshot'] is False
    assert payload['meta']['refund_reason_available'] is False
    assert 'never-export' not in response.text


def test_page_cursor_bound_to_dataset_and_window(client):
    params = {**PARAMS, 'pageSize': 1}
    first = client.get('/api/v1/admin/pdca-source-evidence', params=params).json()['data']
    assert first['has_more'] is True
    second = client.get('/api/v1/admin/pdca-source-evidence', params={**params, 'cursor': first['next_cursor']}).json()['data']
    assert second['rows'][0]['order_id'] == 'B'
    assert second['has_more'] is False
    assert client.get('/api/v1/admin/pdca-source-evidence', params={**params, 'dataset': 'coupons', 'cursor': first['next_cursor']}).status_code == 422


@pytest.mark.parametrize('dataset', ['orders', 'coupons', 'verifications', 'refunds', 'sku_rules', 'poi_mappings'])
def test_dataset_serialization_and_zero_write_sql(client, db_session, dataset):
    statements = []
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement)
    event.listen(db_session.get_bind(), 'before_cursor_execute', capture)
    try:
        response = client.get('/api/v1/admin/pdca-source-evidence', params={**PARAMS, 'dataset': dataset})
        assert response.status_code == 200, response.text
        assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER')) for s in statements)
        if dataset == 'verifications':
            assert response.json()['data']['rows'][0]['cancel_time'] is not None
    finally:
        event.remove(db_session.get_bind(), 'before_cursor_execute', capture)


@pytest.mark.parametrize('change', [{'dataset': 'users'}, {'pageSize': 501}, {'cursor': 'bad'},
                                    {'periodEnd': '2026-08-08'}, {'observedThrough': '2026-09-01'}])
def test_bad_query_rejected(client, change):
    assert client.get('/api/v1/admin/pdca-source-evidence', params={**PARAMS, **change}).status_code == 422


def test_anonymous_denied(client):
    client.cookies.clear()
    assert client.get('/api/v1/admin/pdca-source-evidence', params=PARAMS).status_code == 401


def test_database_connection_failure_is_safe_503(client, db_session, monkeypatch):
    def fail():
        raise OperationalError('SELECT secret_sql', {}, RuntimeError('synthetic-secret'))
    monkeypatch.setattr(db_session.get_bind(), 'connect', fail)
    with TestClient(client.app, raise_server_exceptions=False) as failing:
        failing.cookies.update(client.cookies)
        response = failing.get('/api/v1/admin/pdca-source-evidence', params=PARAMS)
    assert response.status_code == 503
    assert 'synthetic-secret' not in response.text and 'secret_sql' not in response.text


def test_real_app_route_is_readonly_and_mounted(client, db_session):
    from dy_api.main import create_app
    statements = []
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement)
    event.listen(db_session.get_bind(), 'before_cursor_execute', capture)
    try:
        with TestClient(create_app()) as integrated:
            integrated.cookies.update(client.cookies)
            response = integrated.get('/api/v1/admin/pdca-source-evidence', params=PARAMS)
        assert response.status_code == 200, response.text
        assert [row['order_id'] for row in response.json()['data']['rows']] == ['A', 'B']
        assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for s in statements)
    finally:
        event.remove(db_session.get_bind(), 'before_cursor_execute', capture)


def test_refund_evidence_keeps_integer_cents_without_private_payload(client, db_session):
    db_session.add(RawDouyinRefundRecord(source_record_key='refund-source', order_id='A',
                                        refund_id='90000000000000000001', raw_refund_status='source-status',
                                        refund_amount_cent=12345, payload_hash='synthetic-hash',
                                        raw_payload={'reason': 'not-approved', 'phone': 'private-test-value'}))
    db_session.commit()
    response = client.get('/api/v1/admin/pdca-source-evidence', params={**PARAMS, 'dataset': 'refunds'})
    assert response.status_code == 200
    row = response.json()['data']['rows'][0]
    assert row['refund_amount_cent'] == 12345
    assert row['refund_id'] == '90000000000000000001'
    assert row['raw_refund_status'] == 'source-status'
    assert 'not-approved' not in response.text and 'private-test-value' not in response.text


def test_reverification_keeps_both_events_and_explicit_poi_mapping(client, db_session):
    db_session.add(RawDouyinVerifyRecord(verify_id='V2', coupon_id='C', sku_id='SKU',
                                        verify_status='success', verify_time=datetime(2026, 8, 7), poi_id='POI'))
    db_session.add(DimStorePoiMapping(store_id='STORE', poi_id='POI'))
    db_session.commit()
    response = client.get('/api/v1/admin/pdca-source-evidence', params={**PARAMS, 'dataset': 'verifications'})
    events = response.json()['data']['rows']
    assert [item['verify_id'] for item in events] == ['V', 'V2']
    assert events[0]['cancel_time'] is not None and events[1]['cancel_time'] is None
    response = client.get('/api/v1/admin/pdca-source-evidence', params={**PARAMS, 'dataset': 'poi_mappings'})
    assert response.json()['data']['rows'][0]['store_id'] == 'STORE'
    assert response.json()['data']['rows'][0]['poi_id'] == 'POI'
