from datetime import timedelta, timezone

import pytest
from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session

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
    params = dict(period_start=START, period_end=END, now=CUTOFF)
    params.update(overrides)
    return ensure_business_snapshot(session, **params)


def test_business_snapshot_never_reuses_synthetic_batch(business_db):
    calculate_snapshot(business_db, run_id="synthetic", period_start=START, period_end=END,
        observed_through=CUTOFF, roster_at=START, eligibility_version=ELIGIBILITY_VERSION)
    business_db.commit()
    run_id = ensure(business_db)
    assert run_id != "synthetic"
    assert business_db.scalar(select(runs.c.data_mode).where(runs.c.run_id == run_id)) == "business"


def test_unchanged_business_batch_is_reused_across_five_minutes(business_db):
    first = ensure(business_db)
    from apps.api.dy_api.ranking_business import ensure_business_snapshot
    assert ensure_business_snapshot(business_db, period_start=START, period_end=END,
        now=CUTOFF + timedelta(minutes=2)) == first
    reused = ensure_business_snapshot(business_db, period_start=START, period_end=END,
        now=CUTOFF + timedelta(minutes=6))
    assert reused == first
    assert business_db.scalar(select(func.count()).select_from(runs)) == 1


def test_source_update_and_delete_invalidate_business_batch(business_db):
    from apps.api.dy_api.models import RawDouyinOrder
    first = ensure(business_db)
    order = business_db.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "O1"))
    order.owner_account_name = "修正后的账号"
    business_db.flush()
    updated = ensure(business_db, now=CUTOFF + timedelta(minutes=1))
    assert updated != first
    business_db.delete(order)
    business_db.flush()
    deleted = ensure(business_db, now=CUTOFF + timedelta(minutes=2))
    assert deleted != updated


@pytest.mark.parametrize("kind", ["sale", "assignment"])
def test_future_row_not_yet_in_samples_expires_cache(business_db, kind):
    from apps.api.dy_api.models import RawDouyinOrder, ClueAssignmentRound
    from apps.api.dy_api.ranking_schema_v1 import samples
    now = END - timedelta(hours=12)
    boundary = now + timedelta(hours=1)
    original = business_db.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "O1"))
    if kind == "sale":
        business_db.add(RawDouyinOrder(
            order_id="future-order", sku_id=original.sku_id, sale_time=boundary,
            owner_account_id=original.owner_account_id,
        ))
        key, metric = "future-order", "order_count"
    else:
        business_db.add(ClueAssignmentRound(
            assignment_round_id="future-round", order_id="O1", lead_key="future-lead",
            assigned_store_id="A", assigned_at=boundary, execution_mode="formal", round_status="active",
        ))
        key, metric = "future-round", "follow_24h"
    business_db.commit()
    first = ensure(business_db, now=now)
    def count(run_id):
        return business_db.scalar(select(func.count()).select_from(samples).where(
            samples.c.run_id == run_id, samples.c.metric_key == metric, samples.c.sample_key == key))
    assert count(first) == 0
    assert ensure(business_db, now=now + timedelta(minutes=30)) == first
    second = ensure(business_db, now=boundary + timedelta(seconds=1))
    assert second != first
    assert count(second) == 1


def test_existing_future_follow_time_expires_cache_without_a_write(business_db):
    from apps.api.dy_api.models import ClueFollowUpRecord
    from apps.api.dy_api.ranking_lifecycle import ensure_lifecycle_schema
    # Initialize local lifecycle DDL before adding source rows. Production
    # reaches this state through migration 0062 before any ranking request.
    ensure_lifecycle_schema(business_db)
    business_db.commit()
    business_db.add(ClueFollowUpRecord(
        follow_up_record_id="FUTURE",
        assignment_round_id="RA1",
        order_id="O1",
        round_no=1,
        assigned_store_id="A",
        follow_result="appointment",
        created_at=CUTOFF + timedelta(hours=1),
    ))
    business_db.flush()
    first = ensure(business_db)
    from apps.api.dy_api.ranking_lifecycle import snapshot_lifecycle
    refresh_at = business_db.scalar(select(snapshot_lifecycle.c.next_refresh_at).where(
        snapshot_lifecycle.c.run_id == first))
    assert refresh_at is not None
    refresh_at = refresh_at.replace(tzinfo=timezone.utc) if refresh_at.tzinfo is None else refresh_at
    assert refresh_at <= CUTOFF + timedelta(hours=1)
    assert ensure(business_db, now=CUTOFF + timedelta(minutes=30)) == first
    assert ensure(business_db, now=CUTOFF + timedelta(hours=2)) != first


def test_future_verification_observation_expires_cache_without_a_write(business_db):
    from apps.api.dy_api.models import ClueAssignmentRound
    from apps.api.dy_api.ranking_lifecycle import snapshot_lifecycle

    round_row = business_db.scalar(
        select(ClueAssignmentRound).where(ClueAssignmentRound.assignment_round_id == "RA1")
    )
    round_row.verified_at = CUTOFF + timedelta(hours=1)
    round_row.updated_at = CUTOFF + timedelta(hours=1)
    business_db.flush()
    first = ensure(business_db)
    refresh_at = business_db.scalar(
        select(snapshot_lifecycle.c.next_refresh_at).where(snapshot_lifecycle.c.run_id == first)
    )
    assert refresh_at is not None
    refresh_at = refresh_at.replace(tzinfo=timezone.utc) if refresh_at.tzinfo is None else refresh_at
    assert refresh_at <= CUTOFF + timedelta(hours=1)
    assert ensure(business_db, now=CUTOFF + timedelta(minutes=30)) == first
    assert ensure(business_db, now=CUTOFF + timedelta(hours=2)) != first


def test_future_terminal_time_in_raw_payload_expires_cache_without_a_write(business_db):
    from apps.api.dy_api.models import RawDouyinOrder
    from apps.api.dy_api.ranking_lifecycle import snapshot_lifecycle

    order = business_db.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "O5"))
    order.order_status = "交易关闭"
    order.raw_payload = {"closed_at": (CUTOFF + timedelta(hours=1)).isoformat()}
    # Source observation is already visible at the requested cutoff; only the
    # business terminal time itself is still in the future.
    order.source_observed_at = CUTOFF
    business_db.flush()
    first = ensure(business_db)
    refresh_at = business_db.scalar(
        select(snapshot_lifecycle.c.next_refresh_at).where(snapshot_lifecycle.c.run_id == first)
    )
    assert refresh_at is not None
    refresh_at = refresh_at.replace(tzinfo=timezone.utc) if refresh_at.tzinfo is None else refresh_at
    assert refresh_at <= CUTOFF + timedelta(hours=1)
    assert ensure(business_db, now=CUTOFF + timedelta(minutes=30)) == first
    assert ensure(business_db, now=CUTOFF + timedelta(hours=2)) != first


def test_successful_export_access_is_durable_and_does_not_copy_facts(business_db):
    from apps.api.dy_api.ranking_lifecycle import record_snapshot_access, snapshot_lifecycle
    from apps.api.dy_api.ranking_schema_v1 import samples, snapshots

    run_id = ensure(business_db)
    fact_counts = {
        "runs": business_db.scalar(select(func.count()).select_from(runs)),
        "samples": business_db.scalar(select(func.count()).select_from(samples)),
        "snapshots": business_db.scalar(select(func.count()).select_from(snapshots)),
    }
    business_db.execute(delete(snapshot_lifecycle).where(snapshot_lifecycle.c.run_id == run_id))
    business_db.commit()
    record_snapshot_access(business_db, run_id, now=CUTOFF + timedelta(hours=2))
    business_db.commit()

    fresh = Session(bind=business_db.get_bind())
    try:
        row = fresh.execute(
            select(snapshot_lifecycle).where(snapshot_lifecycle.c.run_id == run_id)
        ).mappings().one()
        assert row["source_fingerprint"] is None
        assert row["metadata_json"]["access_recorded"] is True
        assert row["last_accessed_at"] is not None
        assert {
            "runs": fresh.scalar(select(func.count()).select_from(runs)),
            "samples": fresh.scalar(select(func.count()).select_from(samples)),
            "snapshots": fresh.scalar(select(func.count()).select_from(snapshots)),
        } == fact_counts
    finally:
        fresh.close()


def test_sqlite_lifecycle_setup_retries_after_rollback(business_db):
    from apps.api.dy_api.models import RawDouyinOrder
    from apps.api.dy_api.ranking_lifecycle import ensure_lifecycle_schema

    ensure_lifecycle_schema(business_db)
    business_db.rollback()
    first = ensure(business_db)
    order = business_db.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "O1"))
    order.owner_account_name = "回滚后重新安装触发器"
    business_db.flush()
    refreshed = ensure(business_db, now=CUTOFF + timedelta(minutes=1))
    assert refreshed != first


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


def test_business_snapshot_rebuilds_previous_follow_metric_version(business_db):
    first = ensure(business_db)
    business_db.execute(runs.update().where(runs.c.run_id == first).values(
        metric_version="douyin-ranking-self-store-v6-period-start-sales-org-clue-followup-v5-common-business-denominator"))
    business_db.commit()
    refreshed = ensure(business_db)
    assert refreshed != first
    assert "ranking-preoct7-manual-follow-v1" in business_db.scalar(
        select(runs.c.metric_version).where(runs.c.run_id == refreshed))
