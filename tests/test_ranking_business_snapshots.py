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
