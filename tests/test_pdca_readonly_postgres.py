"""Opt-in tests against a disposable loopback-only PDCA database, never production."""
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from dy_api import pdca_readonly_access as access
from dy_api.auth import create_session_token
from apps.api.dy_api.models import RawDouyinOrder, DimSkuProductRule


@pytest.fixture
def isolated_engine(monkeypatch):
    port = os.environ.get('PDCA_READONLY_TEST_PORT')
    if not port:
        pytest.skip('Disposable PDCA PostgreSQL port not supplied')
    assert port.isdigit() and 1024 <= int(port) <= 65535
    # No arbitrary database URL is accepted, preventing accidental production use.
    engine = create_engine(f'postgresql+psycopg://postgres@127.0.0.1:{port}/pdca_readonly_test',
                           pool_size=1, max_overflow=0, connect_args={'connect_timeout': 5})
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT current_database()')) == 'pdca_readonly_test'
        connection.execute(text('CREATE TEMP TABLE pdca_readonly_probe (value INTEGER)'))
    monkeypatch.setattr(access, 'get_engine', lambda: engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_postgres_enforces_readonly_and_timeout_then_restores_pool(isolated_engine):
    iterator = access.get_pdca_readonly_session()
    session = next(iterator)
    assert session.scalar(text('SHOW transaction_read_only')) == 'on'
    assert session.scalar(text('SHOW statement_timeout')) == '8s'
    assert session.scalar(text('SHOW lock_timeout')) == '1s'
    # PostgreSQL allows writes to TEMP tables even in READ ONLY; use permanent
    # DDL to verify database enforcement without creating a business table.
    with pytest.raises(DBAPIError) as caught:
        session.execute(text('CREATE TABLE pdca_forbidden_write (value INTEGER)'))
    assert caught.value.orig.sqlstate == '25006'
    iterator.close()
    with isolated_engine.connect() as connection:
        assert connection.scalar(text('SHOW transaction_read_only')) == 'off'
        assert connection.scalar(text("SELECT to_regclass('public.pdca_forbidden_write')")) is None
        assert connection.scalar(text('SHOW statement_timeout')) == '0'


def test_postgres_normal_read_does_not_leave_open_readonly_transaction(isolated_engine):
    iterator = access.get_pdca_readonly_session()
    session = next(iterator)
    assert session.scalar(text('SELECT 42')) == 42
    iterator.close()
    with isolated_engine.connect() as connection:
        assert connection.scalar(text('SHOW transaction_read_only')) == 'off'


def test_real_app_creation_cohort_on_postgres(isolated_engine, monkeypatch):
    from dy_api.main import create_app
    monkeypatch.setenv('DY_API_TEST_MODE', '1')
    monkeypatch.setenv('DY_SUPER_ADMIN_USERNAME', 'pg-test-admin')
    monkeypatch.setenv('DY_TEST_ADMIN_PASSWORD', 'synthetic-password')
    RawDouyinOrder.__table__.create(isolated_engine, checkfirst=True)
    DimSkuProductRule.__table__.create(isolated_engine, checkfirst=True)
    with Session(isolated_engine) as session:
        session.add(DimSkuProductRule(sku_id='PG-SKU', product_id='PG-PRODUCT', product_scope='精诚养车'))
        session.add(RawDouyinOrder(order_id='90000000000000000001', sku_id='PG-SKU',
                                   create_order_time=datetime(2026, 7, 31, 16, tzinfo=timezone.utc),
                                   paid_amount_cent=15999,
                                   raw_payload={'receipt_amount': 16000, 'discount_amount': 800,
                                                'discounts': [{'platform_discount_amount': 800}],
                                                'secret': 'must-not-export'}))
        session.commit()
    with TestClient(create_app()) as client:
        client.cookies.set('dy_session', create_session_token('pg-test-admin', role='highest_admin'))
        response = client.get('/api/v1/admin/pdca-source-evidence', params={
            'dataset': 'orders', 'periodStart': '2026-08-01', 'periodEnd': '2026-08-01',
            'observedThrough': '2026-09-01T00:00:00+08:00'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['rows'][0]['order_id'] == '90000000000000000001'
    row = response.json()['data']['rows'][0]
    assert row['paid_amount_cent'] == 15999
    assert row['source_receipt_amount_cent'] == 16000
    assert row['source_platform_discount_amount_cent'] == 800
    assert row['order_receipt_candidate_cent'] == 16800
    assert 'must-not-export' not in response.text
    assert response.json()['meta']['amount_semantics_verified'] is False
    assert response.json()['meta']['collection_complete_through'] is None


def test_postgres_json_boolean_and_unknown_receipts_remain_unknown(isolated_engine):
    from datetime import date
    from dy_api.pdca_source_evidence import read_pdca_page

    RawDouyinOrder.__table__.create(isolated_engine, checkfirst=True)
    DimSkuProductRule.__table__.create(isolated_engine, checkfirst=True)
    payloads = [
        {'receipt_amount': True, 'discount_amount': 0, 'discounts': []},
        {'receipt_amount': 16800, 'discount_amount': False},
        {'receipt_amount': 16800, 'discount_amount': 100,
         'discounts': [{'platform_discount_amount': True}]},
        {'receipt_amount': 168.5, 'discount_amount': 0, 'discounts': []},
        {},
    ]
    with Session(isolated_engine) as session:
        session.add(DimSkuProductRule(sku_id='PG-UNKNOWN', product_scope='精诚养车'))
        for index, payload in enumerate(payloads):
            session.add(RawDouyinOrder(order_id=f'PG-UNKNOWN-{index}', sku_id='PG-UNKNOWN',
                                      create_order_time=datetime(2026, 8, 2, tzinfo=timezone.utc),
                                      paid_amount_cent=16800, raw_payload=payload))
        session.commit()
    iterator = access.get_pdca_readonly_session()
    session = next(iterator)
    try:
        result = read_pdca_page(session, dataset='orders', period_start=date(2026, 8, 2),
                                period_end=date(2026, 8, 2),
                                observed_through=datetime(2026, 9, 1, tzinfo=timezone.utc))
        rows = result.model_dump(mode='json')['data']['rows']
        assert len(rows) == len(payloads)
        assert all(row['order_receipt_candidate_cent'] is None for row in rows)
        assert all(row['paid_amount_cent'] == 16800 for row in rows)
    finally:
        iterator.close()
