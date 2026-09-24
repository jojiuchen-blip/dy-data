from datetime import timedelta

import pytest
from sqlalchemy import select, func

from apps.api.dy_api.ranking_schema_v1 import metadata, runs
from apps.api.dy_api.ranking_snapshots import calculate_snapshot
from apps.worker.ranking_preview_fixture import seed_preview, START, END, CUTOFF, ELIGIBILITY_VERSION


@pytest.fixture
def business_db(db_session):
    metadata.create_all(db_session.bind)
    seed_preview(db_session)
    db_session.commit()
    return db_session


def ensure(session, **overrides):
    from apps.api.dy_api.ranking_business import ensure_business_snapshot
    return ensure_business_snapshot(session, **dict(period_start=START, period_end=END,
        now=CUTOFF, **overrides))


def test_business_snapshot_never_reuses_synthetic_batch(business_db):
    calculate_snapshot(business_db, run_id="synthetic", period_start=START, period_end=END,
        observed_through=CUTOFF, roster_at=START, eligibility_version=ELIGIBILITY_VERSION)
    business_db.commit()
    run_id = ensure(business_db)
    assert run_id != "synthetic"
    assert business_db.scalar(select(runs.c.data_mode).where(runs.c.run_id == run_id)) == "business"


def test_recent_business_batch_is_reused_then_refreshed(business_db):
    first = ensure(business_db)
    from apps.api.dy_api.ranking_business import ensure_business_snapshot
    assert ensure_business_snapshot(business_db, period_start=START, period_end=END,
        now=CUTOFF + timedelta(minutes=2)) == first
    refreshed = ensure_business_snapshot(business_db, period_start=START, period_end=END,
        now=CUTOFF + timedelta(minutes=6))
    assert refreshed != first
    assert business_db.scalar(select(func.count()).select_from(runs)) == 2


@pytest.mark.parametrize("start,end", [(START-timedelta(days=1),END),(END,START), (START,CUTOFF+timedelta(days=2))])
def test_business_rejects_out_of_scope_period_before_writes(business_db, start, end):
    from apps.api.dy_api.ranking_business import ensure_business_snapshot
    with pytest.raises(ValueError):
        ensure_business_snapshot(business_db, period_start=start, period_end=end, now=CUTOFF)
    assert business_db.scalar(select(func.count()).select_from(runs)) == 0


def test_business_row_budget_fails_without_partial_batch(business_db):
    with pytest.raises(ValueError, match="数据量"):
        ensure(business_db, max_period_rows=2)
    assert business_db.scalar(select(func.count()).select_from(runs)) == 0


def test_product_scopes_partition_counts_and_isolate_cache(business_db):
    from apps.api.dy_api.models import RawDouyinOrder, ClueAssignmentRound
    from apps.api.dy_api.ranking_snapshots import read_snapshot_report
    original = business_db.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "O1"))
    for suffix, sku in [("other", "UNKNOWN"), ("null", None)]:
        business_db.add(RawDouyinOrder(order_id=suffix, sku_id=sku,
            sale_time=original.sale_time, owner_account_id=original.owner_account_id))
        business_db.add(ClueAssignmentRound(assignment_round_id=suffix,
            order_id=suffix, lead_key=suffix, assigned_store_id="A",
            assigned_at=original.sale_time, execution_mode="formal", round_status="active"))
    business_db.commit()
    reports = {}
    ids = {}
    for scope in ["jingcheng", "byd", "all"]:
        ids[scope] = ensure(business_db, product_scope=scope)
        assert ensure(business_db, product_scope=scope) == ids[scope]
        reports[scope] = read_snapshot_report(business_db, period_start=START,
            period_end=END, product_scope=scope, data_mode="business")
        assert reports[scope]["snapshot_id"] == ids[scope]
        assert reports[scope]["product_scope"] == scope
    assert len(set(ids.values())) == 3
    assert reports["byd"]["totals"]["order_count"] >= 2
    assert reports["byd"]["totals"]["follow_denominator"] >= 2
    for key in ["order_count", "follow_numerator", "follow_denominator",
                "follow_any_numerator", "verification_numerator", "verification_denominator"]:
        assert reports["all"]["totals"][key] == sum(reports[s]["totals"][key] for s in ["jingcheng", "byd"])
    with pytest.raises(ValueError):
        read_snapshot_report(business_db, period_start=START, period_end=END,
            run_id=ids["all"], product_scope="jingcheng")
