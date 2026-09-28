"""Only synthetic records; freeze evidence without changing business state."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from apps.api.dy_api.models import (
    DataQualityIssue, DouyinRefundEvent, JobRun, RawDouyinOrder,
    RawDouyinOrderCoupon, RawDouyinRefundRecord, RawDouyinVerifyRecord,
)
from test_pdca_source_evidence import client, PARAMS

BASE = '/api/v1/admin/pdca-source-snapshots'
QUERY = {key: value for key, value in PARAMS.items() if key != 'dataset'}


@pytest.fixture(autouse=True)
def isolated_snapshot_cache(monkeypatch):
    from dy_api import pdca_snapshot_store
    monkeypatch.setattr(pdca_snapshot_store, 'STORE', pdca_snapshot_store.SnapshotStore())


def snapshot(client, **params):
    response = client.get(BASE, params={**QUERY, **params})
    assert response.status_code == 200, response.text
    return response.json()


def page(client, manifest, dataset, **params):
    return client.get(BASE + '/' + manifest['meta']['snapshot_id'],
                      params={'dataset': dataset, **params})


@pytest.mark.parametrize('sku', ['SKU', 'EMPTY-SKU'])
def test_coupon_query_reuses_complete_order_scope_and_preserves_projection(client, db_session, monkeypatch, sku):
    from sqlalchemy import select
    from dy_api import pdca_snapshot_projection as projection
    from dy_api.pdca_snapshot_schema import SnapshotCoupon

    db_session.add(RawDouyinOrder(order_id='OTHER-SKU', sku_id='OTHER', create_order_time=datetime(2026, 8, 2)))
    db_session.flush()
    for coupon, order, status, refund_at in [
        ('Z', 'A', 'refunded', datetime(2026, 9, 2)),
        ('AA', 'A', 'unknown', None),
        ('OLD-C', 'OLD', 'valid', None),
        ('END-C', 'END', 'valid', None),
        ('OTHER-C', 'OTHER-SKU', 'valid', None),
    ]:
        db_session.add(RawDouyinOrderCoupon(coupon_id=coupon, order_id=order,
            coupon_status=status, coupon_refund_time=refund_at))
    db_session.commit()
    start, end, cutoff = projection.validate_window(
        datetime(2026, 8, 1).date(), datetime(2026, 8, 7).date(),
        datetime.fromisoformat('2026-09-01T00:00:00+08:00'))
    legacy_ids = select(RawDouyinOrder.order_id).where(
        RawDouyinOrder.sku_id.in_([sku]), RawDouyinOrder.create_order_time >= start,
        RawDouyinOrder.create_order_time < end, RawDouyinOrder.create_order_time <= cutoff)
    legacy = projection._rows(db_session, select(*projection._columns(RawDouyinOrderCoupon, SnapshotCoupon))
        .where(RawDouyinOrderCoupon.order_id.in_(legacy_ids)).order_by(RawDouyinOrderCoupon.coupon_id))
    expected = [SnapshotCoupon(**row).model_dump(mode='json') for row in legacy]
    original = projection._rows
    calls = []

    def capture(session, statement):
        calls.append(statement)
        return original(session, statement)

    monkeypatch.setattr(projection, '_rows', capture)
    manifest = snapshot(client, skuIds=sku)
    actual = page(client, manifest, 'coupons').json()['data']['rows']
    assert actual == expected
    assert [row['coupon_id'] for row in actual] == (['AA', 'C', 'Z'] if sku == 'SKU' else [])
    # The performance contract: coupon retrieval must not rerun the order scan.
    coupon_sql = str(calls[2].compile(compile_kwargs={'render_postcompile': True}))
    assert 'raw_douyin_order_coupons' in coupon_sql
    assert 'raw_douyin_orders' not in coupon_sql


def test_materialized_coupon_scope_keeps_row_limit(client, db_session, monkeypatch):
    from dy_api import pdca_snapshot_projection as projection
    monkeypatch.setattr(projection, 'MAX_DATASET_ROWS', 2)
    db_session.add(RawDouyinOrderCoupon(coupon_id='C2', order_id='A'))
    db_session.commit()
    assert len(page(client, snapshot(client), 'coupons').json()['data']['rows']) == 2
    db_session.add(RawDouyinOrderCoupon(coupon_id='C3', order_id='A'))
    db_session.commit()
    response = client.get(BASE, params=QUERY)
    assert response.status_code == 413


@pytest.mark.parametrize('guard', ['cell', 'bytes'])
def test_materialized_coupon_scope_keeps_transfer_guards(client, db_session, monkeypatch, guard):
    from dy_api import pdca_snapshot_projection as projection
    db_session.query(RawDouyinOrderCoupon).filter_by(coupon_id='C').update({'coupon_status': 'X' * 1025})
    db_session.commit()
    original = projection._rows
    count = 0

    def coupon_guard(session, statement):
        nonlocal count
        count += 1
        if count == 3:
            monkeypatch.setattr(projection, 'MAX_CELL_CHARACTERS' if guard == 'cell' else 'MAX_SNAPSHOT_BYTES', 1024)
        return original(session, statement)

    monkeypatch.setattr(projection, '_rows', coupon_guard)
    assert client.get(BASE, params=QUERY).status_code == 413


def test_order_population_and_snapshot_survive_source_updates(client, db_session):
    first = snapshot(client)
    response = page(client, first, 'orders', pageSize=1)
    assert response.status_code == 200
    payload = response.json()
    assert payload['data']['rows'][0]['order_id'] == 'A'
    db_session.query(RawDouyinOrder).filter_by(order_id='B').update({'order_status': 'refunded'})
    db_session.add(RawDouyinOrder(order_id='AA', sku_id='SKU', create_order_time=datetime(2026, 8, 2)))
    db_session.commit()
    second = page(client, first, 'orders', pageSize=1, cursor=payload['data']['next_cursor']).json()
    assert [row['order_id'] for row in second['data']['rows']] == ['B']
    assert second['data']['rows'][0]['order_status'] is None
    assert second['data']['has_more'] is False
    assert page(client, first, 'orders', pageSize=1).json() == payload
    assert first['meta']['consistent_snapshot'] is True
    assert first['meta']['publishable'] is False
    assert first['meta']['collection_complete_through'] is None
    assert snapshot(client)['data']['datasets'][0]['row_count'] == 3


def test_refund_status_partial_unknown_and_late_evidence(client, db_session):
    for identity, status, kind, occurred in [('PART', 2, 1, datetime(2026, 8, 6)),
                                           ('PENDING', 1, 2, datetime(2026, 8, 7)),
                                           ('LATE', 2, 2, datetime(2026, 9, 2))]:
        db_session.add(DouyinRefundEvent(refund_event_id=identity, order_id='A', coupon_id='C',
            refund_status=status, refund_type=kind, refund_amount_cent=500,
            occurred_at=occurred, source_observed_at=datetime(2026, 9, 5)))
    db_session.add(RawDouyinRefundRecord(source_record_key='RAW', refund_id='PART', order_id='A',
        raw_refund_status='50', normalized_refund_status=2, refund_amount_cent=None,
        refund_completed_at=datetime(2026, 8, 6), payload_hash='synthetic',
        raw_payload={'phone': 'PRIVATE-MARKER'}))
    db_session.add(DataQualityIssue(issue_id='DQ', issue_type='refund_missing_amount', order_id='A',
        message='PRIVATE-MARKER', raw_context_json={'secret': 'PRIVATE-MARKER'}))
    db_session.commit()
    manifest = snapshot(client)
    events = {row['refund_event_id']: row for row in page(client, manifest, 'refund_events').json()['data']['rows']}
    assert events['PART']['refund_scope'] == 'partial'
    assert events['PART']['effective_at'] is not None
    assert events['PENDING']['effective_at'] is None
    assert events['LATE']['within_business_cutoff'] is False
    assert events['PART']['source_observed_at'] > events['PART']['effective_at']
    raw = page(client, manifest, 'raw_refunds')
    assert raw.json()['data']['rows'][0]['refund_amount_cent'] is None
    assert 'PRIVATE-MARKER' not in raw.text
    quality = page(client, manifest, 'quality_issues')
    assert quality.json()['data']['rows'][0]['issue_type'] == 'refund_missing_amount'
    assert 'PRIVATE-MARKER' not in quality.text


def test_verification_revoke_reverify_multicoupon_and_cutoff(client, db_session):
    db_session.add(RawDouyinOrderCoupon(coupon_id='C2', order_id='A'))
    db_session.add(RawDouyinVerifyRecord(verify_id='V2', coupon_id='C', verify_status='1',
        verify_time=datetime(2026, 8, 7)))
    db_session.add(RawDouyinVerifyRecord(verify_id='V3', coupon_id='C2', verify_status='1',
        verify_time=datetime(2026, 9, 2)))
    db_session.commit()
    manifest = snapshot(client)
    rows = page(client, manifest, 'verification_events').json()['data']['rows']
    assert len(rows) == 4 and len({row['event_id'] for row in rows}) == 4
    original = next(row for row in rows if row['verify_id'] == 'V' and row['event_type'] == 'verification')
    revoke = next(row for row in rows if row['event_type'] == 'revocation')
    assert revoke['original_event_id'] == original['event_id']
    assert {row['order_id'] for row in rows} == {'A'}
    assert next(row for row in rows if row['verify_id'] == 'V3')['within_business_cutoff'] is False
    assert 'event_history_incomplete' in manifest['meta']['blocking_reasons']


def test_batches_are_evidence_not_completeness(client, db_session):
    db_session.add(JobRun(job_id='J', job_name='date_sync', status='failed',
        window_start=datetime(2026, 8, 1), window_end=datetime(2026, 8, 2),
        failed_count=2, error_message='PRIVATE-MARKER', metadata_json={'secret':'PRIVATE-MARKER'}))
    db_session.commit()
    manifest = snapshot(client)
    result = page(client, manifest, 'collection_batches')
    assert result.json()['data']['rows'][0]['status'] == 'failed'
    assert 'PRIVATE-MARKER' not in result.text
    assert all(item['collection_complete_through'] is None for item in manifest['data']['datasets'])


def test_snapshot_cursor_auth_invalid_inputs_and_zero_writes(client, db_session):
    statements = []
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement)
    event.listen(db_session.get_bind(), 'before_cursor_execute', capture)
    try:
        manifest = snapshot(client)
        first = page(client, manifest, 'orders', pageSize=1).json()
        assert page(client, manifest, 'coupons', cursor=first['data']['next_cursor']).status_code == 422
        assert page(client, manifest, 'users').status_code == 422
        assert page(client, manifest, 'orders', cursor='bad').status_code == 422
        assert client.get(BASE, params={**QUERY, 'periodEnd': '2026-08-08'}).status_code == 422
        assert not any(sql.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER')) for sql in statements)
        client.cookies.clear()
        assert page(client, manifest, 'orders').status_code == 401
    finally:
        event.remove(db_session.get_bind(), 'before_cursor_execute', capture)


def test_real_application_registration(client, db_session):
    from dy_api.main import create_app
    with TestClient(create_app()) as integrated:
        integrated.cookies.update(client.cookies)
        manifest = snapshot(integrated)
        assert page(integrated, manifest, 'orders').status_code == 200


def test_unicode_owner_expiry_capacity_and_limits(client, monkeypatch):
    from dy_api import pdca_snapshot_store as store, pdca_snapshot_projection as projection
    from dy_api.routes import pdca_sources
    client.app.dependency_overrides[pdca_sources.require_pdca_snapshot_admin] = lambda: '中文管理员'
    manifest = snapshot(client)
    assert page(client, manifest, 'orders').status_code == 200
    client.app.dependency_overrides[pdca_sources.require_pdca_snapshot_admin] = lambda: '其他管理员'
    assert page(client, manifest, 'orders').status_code == 410
    client.app.dependency_overrides.clear()
    monkeypatch.setattr(store, 'MAX_SNAPSHOTS', 1)
    assert client.get(BASE, params=QUERY).status_code == 429
    monkeypatch.setattr(store.time, 'monotonic', lambda: 1e20)
    assert page(client, manifest, 'orders').status_code == 410
    monkeypatch.setattr(projection, 'MAX_DATASET_ROWS', 1)
    assert client.get(BASE, params=QUERY).status_code == 413


def test_source_corruption_and_missing_table_are_safe_503(client, db_session):
    from sqlalchemy import text
    # A source value violating the response schema is a source failure, not a bad query.
    db_session.execute(text("UPDATE raw_douyin_orders SET paid_amount_cent='not-money' WHERE order_id='A'"))
    db_session.commit()
    assert client.get(BASE, params=QUERY).status_code == 503
    db_session.execute(text('DROP TABLE douyin_refund_event'))
    db_session.commit()
    result = client.get(BASE, params=QUERY)
    assert result.status_code == 503
    assert 'raw_douyin' not in result.text


def test_snapshot_transaction_enforces_readonly_and_restores_pool(client, db_session):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from dy_api.pdca_snapshot_projection import snapshot_session
    with snapshot_session() as session:
        assert session.scalar(text('SELECT count(*) FROM raw_douyin_orders')) == 4
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE raw_douyin_orders SET product_name='FORBIDDEN'"))
    assert db_session.execute(text('PRAGMA query_only')).scalar() == 0


def test_explicit_sku_scope_keeps_unpaid_refunded_and_unknown_amount(client, db_session):
    db_session.add(RawDouyinOrder(order_id='X', sku_id='NOT-MAPPED', order_status='refunded',
        create_order_time=datetime(2026, 8, 2), pay_time=datetime(2026, 8, 2),
        paid_amount_cent=12345, raw_payload={}))
    db_session.commit()
    manifest = snapshot(client, skuIds=['SKU', 'NOT-MAPPED'])
    rows = page(client, manifest, 'orders').json()['data']['rows']
    assert {row['order_id'] for row in rows} == {'A', 'B', 'X'}
    unknown = next(row for row in rows if row['order_id'] == 'X')
    assert unknown['order_receipt_candidate_cent'] is None
    assert unknown['order_receipt_amount_cent'] is None
    assert unknown['payment_evidence'] == 'paid_by_cutoff'


def test_refund_field_diagnostics_and_unknown_revocation_time(client, db_session):
    db_session.query(RawDouyinVerifyRecord).filter_by(verify_id='V').update(
        {'verify_status': '2', 'cancel_time': None})
    db_session.add(RawDouyinRefundRecord(source_record_key='DIAG', order_id='A', payload_hash='test',
        raw_payload={'refund_amount_cent': None, 'finish_time': 'PRIVATE-MARKER', 'phone': 'PRIVATE-MARKER'}))
    db_session.commit()
    manifest = snapshot(client)
    raw = page(client, manifest, 'raw_refunds')
    row = raw.json()['data']['rows'][0]
    assert row['amount_field_type'] == 'null'
    assert row['completion_fields_present'] == ['finish_time']
    assert 'PRIVATE-MARKER' not in raw.text
    events = page(client, manifest, 'verification_events').json()['data']['rows']
    revoked = next(row for row in events if row['event_type'] == 'revocation')
    assert revoked['effective_at'] is None
    assert revoked['within_business_cutoff'] is None


@pytest.mark.parametrize('status', ['valid', 'fulfilled', 'used', ' VALID '])
def test_existing_success_status_dictionary(client, db_session, status):
    db_session.query(RawDouyinVerifyRecord).filter_by(verify_id='V').update({'verify_status': status})
    db_session.commit()
    rows = page(client, snapshot(client), 'verification_events').json()['data']['rows']
    assert any(row['event_type'] == 'verification' for row in rows)


def test_oversized_projected_source_field_rejected_before_python_materialization(client, db_session, monkeypatch):
    from dy_api import pdca_snapshot_projection as projection
    monkeypatch.setattr(projection, 'MAX_CELL_CHARACTERS', 100, raising=False)
    db_session.query(RawDouyinOrder).filter_by(order_id='A').update({'product_name': 'x' * 101})
    db_session.commit()
    assert client.get(BASE, params=QUERY).status_code == 413


def test_snapshot_does_not_hold_auth_connection_while_opening_snapshot(client, tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from apps.api.dy_api.models import Base as DatabaseBase
    from dy_api import pdca_readonly_access
    engine = create_engine('sqlite:///' + str(tmp_path / 'single-pool.db'),
                           pool_size=1, max_overflow=0, pool_timeout=0.05)
    DatabaseBase.metadata.create_all(engine)
    monkeypatch.setattr(pdca_readonly_access, 'get_engine', lambda: engine)
    try:
        assert client.get(BASE, params=QUERY).status_code == 200
    finally:
        engine.dispose()


def test_snapshot_auth_query_failure_is_safe(client, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from dy_api.routes import pdca_sources
    def fail(*args):
        raise OperationalError('PRIVATE-SQL', {}, RuntimeError('PRIVATE-MARKER'))
    monkeypatch.setattr(pdca_sources, 'require_pdca_super_admin', fail)
    with TestClient(client.app, raise_server_exceptions=False) as safe_client:
        safe_client.cookies.update(client.cookies)
        response = safe_client.get(BASE, params=QUERY)
    assert response.status_code == 503
    assert 'PRIVATE' not in response.text
