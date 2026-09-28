"""Opt-in disposable PostgreSQL checks; inherits loopback/test DB hard guard."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
import pytest

from apps.api.dy_api.models import (
    Base, DataQualityIssue, DimSkuProductRule, DimStore, DimStorePoiMapping,
    DouyinRefundEvent, JobRun, JobStageRun, RawDouyinOrder, RawDouyinOrderCoupon,
    RawDouyinRefundRecord, RawDouyinVerifyRecord,
)
from dy_api.auth import create_session_token
from dy_api.pdca_snapshot_projection import snapshot_session
from test_pdca_readonly_postgres import isolated_engine


def test_postgres_snapshot_repeatable_read_and_database_enforced_readonly(isolated_engine):
    writer = create_engine(isolated_engine.url)
    with writer.begin() as connection:
        connection.execute(text('CREATE TABLE pdca_snapshot_isolation_probe (value INTEGER)'))
        connection.execute(text('INSERT INTO pdca_snapshot_isolation_probe VALUES (1)'))
    try:
        with snapshot_session() as session:
            assert session.scalar(text('SHOW transaction_isolation')) == 'repeatable read'
            assert session.scalar(text('SHOW transaction_read_only')) == 'on'
            assert session.scalar(text('SELECT value FROM pdca_snapshot_isolation_probe')) == 1
            with writer.begin() as connection:
                connection.execute(text('UPDATE pdca_snapshot_isolation_probe SET value=2'))
            assert session.scalar(text('SELECT value FROM pdca_snapshot_isolation_probe')) == 1
            with pytest.raises(DBAPIError) as caught:
                session.execute(text('UPDATE pdca_snapshot_isolation_probe SET value=3'))
            assert caught.value.orig.sqlstate == '25006'
        with isolated_engine.connect() as connection:
            assert connection.scalar(text('SHOW transaction_read_only')) == 'off'
            assert connection.scalar(text('SELECT value FROM pdca_snapshot_isolation_probe')) == 2
    finally:
        with writer.begin() as connection:
            connection.execute(text('DROP TABLE pdca_snapshot_isolation_probe'))
        writer.dispose()


def test_postgres_snapshot_all_projections(isolated_engine, monkeypatch):
    from dy_api.main import create_app
    from dy_api import pdca_snapshot_store
    monkeypatch.setattr(pdca_snapshot_store, 'STORE', pdca_snapshot_store.SnapshotStore())
    monkeypatch.setenv('DY_API_TEST_MODE', '1')
    monkeypatch.setenv('DY_SUPER_ADMIN_USERNAME', 'pg-test-admin')
    monkeypatch.setenv('DY_TEST_ADMIN_PASSWORD', 'synthetic-password')
    tables = [model.__table__ for model in (DimStore, DimSkuProductRule, DimStorePoiMapping,
        RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord, RawDouyinRefundRecord,
        DouyinRefundEvent, DataQualityIssue, JobRun, JobStageRun)]
    Base.metadata.create_all(isolated_engine, tables=tables)
    with Session(isolated_engine) as session:
        session.add(RawDouyinOrder(order_id='SNAP-PG', sku_id='SNAP-SKU',
            create_order_time=datetime(2026, 8, 2, tzinfo=timezone.utc),
            raw_payload={'receipt_amount': 16000, 'discount_amount': 800,
                         'discounts': [{'platform_discount_amount': 800}]}))
        session.add(RawDouyinRefundRecord(source_record_key='SNAP-RAW', order_id='SNAP-PG',
            payload_hash='synthetic', raw_payload={'refund_amount_cent': None, 'finish_time': 'do-not-export'}))
        session.commit()
    with TestClient(create_app()) as client:
        client.cookies.set('dy_session', create_session_token('pg-test-admin', role='highest_admin'))
        base = '/api/v1/admin/pdca-source-snapshots'
        result = client.get(base, params={'periodStart': '2026-08-01', 'periodEnd': '2026-08-07',
            'observedThrough': '2026-09-01T00:00:00+08:00', 'skuIds': 'SNAP-SKU'})
        assert result.status_code == 200, result.text
        manifest = result.json()
        for dataset in manifest['data']['datasets']:
            response = client.get(base + '/' + manifest['meta']['snapshot_id'], params={'dataset': dataset['dataset']})
            assert response.status_code == 200, response.text
            assert 'do-not-export' not in response.text
            if dataset['dataset'] == 'orders':
                assert response.json()['data']['rows'][0]['order_receipt_candidate_cent'] == 16800
            if dataset['dataset'] == 'raw_refunds':
                assert response.json()['data']['rows'][0]['amount_field_type'] == 'null'
