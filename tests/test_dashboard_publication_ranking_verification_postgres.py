"""Batched verification aggregation keeps the previous POI/store semantics."""
from datetime import timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, literal, or_, select, text, union_all
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications.ranking_build import _unique_poi_stores, _verification_by_store
from apps.api.dy_api.models import Base, RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord
from apps.api.dy_api.ranking_snapshots import utc
from apps.worker.ranking_preview_fixture import AT, CUTOFF


@pytest.fixture(params=["sqlite", "postgres"])
def source(request, db_session):
    if request.param == "sqlite":
        yield db_session
        return
    raw = os.getenv("DYDATA_PUBLICATION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set DYDATA_PUBLICATION_TEST_DATABASE_URL to a disposable local PostgreSQL test database")
    url = make_url(raw)
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert "test" in (url.database or "").lower()
    schema = "ranking_verify_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_unique_poi_mapping_preserves_duplicate_and_ambiguous_semantics():
    assert _unique_poi_stores([
        ("duplicate", "A"), ("duplicate", "A"), ("ambiguous", "A"), ("ambiguous", "B"),
        ("second", "A"), ("null-only", None), ("nonnull", None), ("nonnull", "B"), (None, "A"),
    ]) == {"duplicate": "A", "second": "A", "nonnull": "B"}


def test_batch_verification_matches_previous_sql_aggregate(source):
    mappings = [("early", "A"), ("late", "A"), ("other", "B"),
        ("duplicate", "A"), ("duplicate", "A"), ("ambiguous", "A"), ("ambiguous", "B")]
    cases = [
        ("multi", "early", "success", AT + timedelta(hours=1), None),
        ("multi", "late", "1", AT + timedelta(hours=3), None),
        ("multi", "late", "verified", AT + timedelta(hours=2), None),
        ("multi", "other", "已核销", AT + timedelta(hours=4), None),
        ("duplicate", "duplicate", "success", AT, None),
        ("ambiguous", "ambiguous", "success", AT, None),
        ("missing", "unknown", "success", AT, None),
        ("cancel-at", "early", "success", AT, CUTOFF),
        ("cancel-before", "early", "success", AT, CUTOFF - timedelta(seconds=1)),
        ("cancel-after", "early", "success", AT, CUTOFF + timedelta(seconds=1)),
        ("future", "early", "success", CUTOFF + timedelta(seconds=1), None),
        ("at-cutoff", "early", "success", CUTOFF, None),
        ("failed", "early", "failed", AT, None),
        ("no-time", "early", "success", None, None),
        ("unrequested", "early", "success", AT, None),
    ]
    orders = {case[0] for case in cases} | {"no-verification"}
    source.add_all([RawDouyinOrder(order_id=order, sale_time=AT) for order in orders])
    source.flush()
    source.add_all([RawDouyinOrderCoupon(coupon_id=str(index), order_id=case[0]) for index, case in enumerate(cases)])
    source.flush()
    source.add_all([RawDouyinVerifyRecord(verify_id=str(index), coupon_id=str(index), poi_id=poi,
        verify_status=status, verify_time=at, cancel_time=cancel)
        for index, (_, poi, status, at, cancel) in enumerate(cases)])
    source.commit()
    requested = orders - {"unrequested"}
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(source.bind, "before_cursor_execute", capture)
    try:
        actual = _verification_by_store(source, requested, _unique_poi_stores(mappings), CUTOFF)
    finally:
        event.remove(source.bind, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert "dim_store_poi_mappings" not in statements[0]
    assert "GROUP BY raw_douyin_order_coupons.order_id, raw_douyin_verify_records.poi_id" in statements[0]

    # The former SQL rule is an independent oracle, including duplicate and
    # ambiguous mapping rows that current schema constraints normally prevent.
    mapping_rows = union_all(*[select(literal(poi).label("poi_id"), literal(store).label("store_id"))
        for poi, store in mappings]).subquery()
    unique_pois = select(mapping_rows.c.poi_id, func.min(mapping_rows.c.store_id).label("store_id")).group_by(
        mapping_rows.c.poi_id).having(func.count(func.distinct(mapping_rows.c.store_id)) == 1).subquery()
    old = source.execute(select(RawDouyinOrderCoupon.order_id, unique_pois.c.store_id,
        func.max(RawDouyinVerifyRecord.verify_time)).join(RawDouyinVerifyRecord,
        RawDouyinVerifyRecord.coupon_id == RawDouyinOrderCoupon.coupon_id).join(unique_pois,
        unique_pois.c.poi_id == RawDouyinVerifyRecord.poi_id).where(
        RawDouyinOrderCoupon.order_id.in_(requested),
        RawDouyinVerifyRecord.verify_status.in_(("1", "success", "verified", "已核销")),
        RawDouyinVerifyRecord.verify_time <= CUTOFF,
        or_(RawDouyinVerifyRecord.cancel_time.is_(None), RawDouyinVerifyRecord.cancel_time > CUTOFF)
    ).group_by(RawDouyinOrderCoupon.order_id, unique_pois.c.store_id))
    assert actual == {(order, store): utc(at) for order, store, at in old}
    assert actual == {("multi", "A"): AT + timedelta(hours=3), ("multi", "B"): AT + timedelta(hours=4),
        ("duplicate", "A"): AT, ("cancel-after", "A"): AT, ("at-cutoff", "A"): CUTOFF}
