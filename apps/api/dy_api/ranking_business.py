"""Bounded, refreshable business snapshots derived from existing engine data."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.ranking_configuration import DATA_START, RANKING_WRITE_LOCK
from apps.api.dy_api.ranking_schema_v1 import eligibility, runs
from apps.api.dy_api.ranking_snapshots import METRIC_VERSION, calculate_snapshot, utc


def ensure_business_snapshot(
    session: Session, *, period_start: datetime, period_end: datetime,
    now: datetime | None = None, max_period_rows: int = 50000,
) -> str:
    """Return a recent business run or atomically calculate a bounded new run.

    Caller owns commit/rollback. Freshness is five minutes, so subsequently
    repaired raw records and late follows are reflected on the next refresh.
    Source business tables are never updated here. Synthetic batches cannot
    satisfy this cache, even when period and metric version are identical.
    """
    start, end, cutoff = map(utc, (period_start, period_end, now or datetime.now(timezone.utc)))
    tomorrow = (cutoff.astimezone(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    if start < DATA_START or start >= end or end > tomorrow or end - start > timedelta(days=366):
        raise ValueError("请选择2026-09-01至今天之间的有效日期范围，单次不超过366天")
    if not 1 <= max_period_rows <= 50000:
        raise ValueError("invalid snapshot row budget")

    def recent():
        return session.scalar(select(runs.c.run_id).where(
            runs.c.period_start == start, runs.c.period_end == end,
            runs.c.data_mode == "business", runs.c.status == "success",
            runs.c.metric_version == METRIC_VERSION,
            runs.c.observed_through >= cutoff - timedelta(minutes=5),
            runs.c.observed_through <= cutoff,
        ).order_by(runs.c.observed_through.desc()).limit(1))

    cached = recent()
    if cached:
        return cached
    with session.begin_nested():
        if session.bind.dialect.name == "postgresql":
            locked = session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"),
                                    {"key": RANKING_WRITE_LOCK})
            if not locked:
                raise ValueError("指标数据正在更新，请稍后刷新")
        cached = recent()
        if cached:
            return cached
        if session.bind.dialect.name == "postgresql":
            # Bound SQL execution as well as Python hydration. Restore the
            # original connection setting after success; savepoint rollback
            # restores it on failure.
            original_timeout = session.scalar(text("SHOW statement_timeout"))
            session.execute(text("SELECT set_config('statement_timeout', '20000', true)"))
        version = session.scalar(select(eligibility.c.eligibility_version).where(
            eligibility.c.product_scope == "精诚养车", eligibility.c.effective_from <= start,
        ).order_by(eligibility.c.effective_from.desc()).limit(1))
        if not version:
            raise ValueError("所选日期缺少精诚养车适用门店名单，请先由管理员导入")
        run_id = "business-" + uuid4().hex
        calculate_snapshot(session, run_id=run_id, period_start=start, period_end=end,
            observed_through=cutoff, roster_at=start, eligibility_version=version,
            data_mode="business", max_period_rows=max_period_rows)
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SELECT set_config('statement_timeout', :value, true)"),
                            {"value": original_timeout})
    return run_id
