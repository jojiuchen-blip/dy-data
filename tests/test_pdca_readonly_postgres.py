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
                                   paid_amount_cent=16800))
        session.commit()
    with TestClient(create_app()) as client:
        client.cookies.set('dy_session', create_session_token('pg-test-admin', role='highest_admin'))
        response = client.get('/api/v1/admin/pdca-source-evidence', params={
            'dataset': 'orders', 'periodStart': '2026-08-01', 'periodEnd': '2026-08-01',
            'observedThrough': '2026-09-01T00:00:00+08:00'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['rows'][0]['order_id'] == '90000000000000000001'
    assert response.json()['data']['rows'][0]['paid_amount_cent'] == 16800
    assert response.json()['meta']['collection_complete_through'] is None
