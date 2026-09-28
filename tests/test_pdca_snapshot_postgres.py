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


def test_postgres_quality_union_large_bindings_and_repeatable_view(isolated_engine, monkeypatch):
    from dy_api import pdca_snapshot_projection as projection
    DataQualityIssue.__table__.create(isolated_engine, checkfirst=True)
    with Session(isolated_engine) as session:
        session.add(DataQualityIssue(issue_id='QUALITY-ORDER',issue_type='synthetic',message='synthetic',order_id='QO-0'))
        session.add(DataQualityIssue(issue_id='QUALITY-BATCH',issue_type='synthetic',message='synthetic',source_run_id='QR-0'))
        session.commit()
    writer=create_engine(isolated_engine.url)
    original=projection._rows
    first=True
    def concurrent_rows(session, statement):
        nonlocal first
        result=original(session,statement)
        if first:
            first=False
            with writer.begin() as connection:
                connection.execute(DataQualityIssue.__table__.insert().values(issue_id='QUALITY-LATE',issue_type='synthetic',message='synthetic',coupon_id='QC-0'))
        return result
    monkeypatch.setattr(projection,'_rows',concurrent_rows)
    try:
        with snapshot_session() as session:
            rows=projection._quality_rows(session,
                {'QO-'+str(i) for i in range(12768)}, {'QC-'+str(i) for i in range(20000)},
                {'QR-'+str(i) for i in range(32768)},'related_batches')
            assert [r['issue_id'] for r in rows]==['QUALITY-BATCH','QUALITY-ORDER']
        with snapshot_session() as session:
            rows=projection._quality_rows(session,[],['QC-0'],set(),'cohort')
            assert [r['issue_id'] for r in rows]==['QUALITY-LATE']
    finally:
        writer.dispose()


def test_postgres_materialized_coupon_scope_keeps_concurrent_snapshot(isolated_engine, monkeypatch):
    from datetime import date
    import json
    from dy_api import pdca_snapshot_projection as projection

    tables = [model.__table__ for model in (DimStore, DimSkuProductRule, DimStorePoiMapping,
        RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord, RawDouyinRefundRecord,
        DouyinRefundEvent, DataQualityIssue, JobRun, JobStageRun)]
    Base.metadata.create_all(isolated_engine, tables=tables)
    when = datetime(2026, 9, 22, tzinfo=timezone.utc)
    with Session(isolated_engine) as session:
        session.add(RawDouyinOrder(order_id='COUPON-SNAPSHOT-A', sku_id='COUPON-SCOPE', create_order_time=when))
        session.flush()
        session.add(RawDouyinOrderCoupon(coupon_id='COUPON-SNAPSHOT-C', order_id='COUPON-SNAPSHOT-A', coupon_status='before'))
        session.commit()
    writer = create_engine(isolated_engine.url)
    original = projection._rows
    calls = 0

    def write_after_complete_orders(session, statement):
        nonlocal calls
        result = original(session, statement)
        calls += 1
        if calls == 2:
            assert [row['order_id'] for row in result] == ['COUPON-SNAPSHOT-A']
            with Session(writer) as other:
                other.query(RawDouyinOrderCoupon).filter_by(coupon_id='COUPON-SNAPSHOT-C').update({'coupon_status': 'after'})
                other.add(RawDouyinOrder(order_id='COUPON-SNAPSHOT-B', sku_id='COUPON-SCOPE', create_order_time=when))
                other.flush()
                other.add_all([
                    RawDouyinOrderCoupon(coupon_id='COUPON-SNAPSHOT-LATE-A', order_id='COUPON-SNAPSHOT-A'),
                    RawDouyinOrderCoupon(coupon_id='COUPON-SNAPSHOT-LATE-B', order_id='COUPON-SNAPSHOT-B'),
                ])
                other.commit()
        return result

    monkeypatch.setattr(projection, '_rows', write_after_complete_orders)
    start, end, cutoff = projection.validate_window(date(2026, 9, 22), date(2026, 9, 22),
        datetime(2026, 9, 23, tzinfo=timezone.utc))
    try:
        with snapshot_session() as session:
            first, _, _ = projection.project_snapshot(session, start, end, cutoff, ['COUPON-SCOPE'], 'cohort')
        rows = [json.loads(row) for row in first['coupons']]
        assert [(row['coupon_id'], row['coupon_status']) for row in rows] == [('COUPON-SNAPSHOT-C', 'before')]
        monkeypatch.setattr(projection, '_rows', original)
        with snapshot_session() as session:
            second, _, _ = projection.project_snapshot(session, start, end, cutoff, ['COUPON-SCOPE'], 'cohort')
        rows = [json.loads(row) for row in second['coupons']]
        assert [row['coupon_id'] for row in rows] == ['COUPON-SNAPSHOT-C', 'COUPON-SNAPSHOT-LATE-A', 'COUPON-SNAPSHOT-LATE-B']
        assert rows[0]['coupon_status'] == 'after'
    finally:
        writer.dispose()


def test_postgres_coupon_query_accepts_maximum_materialized_order_bindings(isolated_engine, monkeypatch):
    """Exercise the actual project_snapshot coupon query at its order row cap."""
    from datetime import date
    from dy_api import pdca_snapshot_projection as projection

    Base.metadata.create_all(isolated_engine, tables=[RawDouyinOrder.__table__, RawDouyinOrderCoupon.__table__])
    when = datetime(2026, 9, 22, tzinfo=timezone.utc)
    orders = [{'order_id': f'BOUND-COUPON-{i:05}', 'sku_id': 'BOUND-COUPON-SKU',
               'create_order_time': when, 'raw_payload': {}} for i in range(projection.MAX_DATASET_ROWS)]
    with isolated_engine.begin() as connection:
        connection.execute(RawDouyinOrder.__table__.insert(), orders)
    with Session(isolated_engine) as session:
        session.add_all([
            RawDouyinOrderCoupon(coupon_id='BOUND-COUPON-Z', order_id=orders[0]['order_id']),
            RawDouyinOrderCoupon(coupon_id='BOUND-COUPON-A', order_id=orders[-1]['order_id']),
        ])
        session.commit()
    original = projection._rows
    calls = 0

    class CouponChecked(Exception):
        pass

    def check_coupon_stage(session, statement):
        nonlocal calls
        calls += 1
        if calls == 1:
            return []  # Rules unrelated to the large binding contract.
        if calls == 3:
            assert 'raw_douyin_orders' not in str(statement)
            assert [row['coupon_id'] for row in original(session, statement)] == ['BOUND-COUPON-A', 'BOUND-COUPON-Z']
            raise CouponChecked()
        return original(session, statement)

    monkeypatch.setattr(projection, '_rows', check_coupon_stage)
    start, end, cutoff = projection.validate_window(date(2026, 9, 22), date(2026, 9, 22),
        datetime(2026, 9, 23, tzinfo=timezone.utc))
    with snapshot_session() as session, pytest.raises(CouponChecked):
        projection.project_snapshot(session, start, end, cutoff, ['BOUND-COUPON-SKU'], 'cohort')
