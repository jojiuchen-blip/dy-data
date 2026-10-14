"""Bounded, refreshable business snapshots derived from existing engine data."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.ranking_configuration import DATA_START, RANKING_WRITE_LOCK
from apps.api.dy_api.ranking_schema_v1 import eligibility, runs
from apps.api.dy_api.ranking_snapshots import metric_version, calculate_snapshot, utc
from apps.api.dy_api.ranking_lifecycle import (
    ensure_lifecycle_schema,
    _next_refresh_at,
    register_snapshot,
    reusable_business_snapshot,
    source_fingerprint,
)


def ensure_business_snapshot(
    session: Session, *, period_start: datetime, period_end: datetime,
    now: datetime | None = None, max_period_rows: int = 50000, product_scope: str = "jingcheng",
) -> str:
    """Return a recent business run or atomically calculate a bounded new run.

    Caller owns commit/rollback. The UI may request a refresh every five
    minutes, but an unchanged source reuses the same immutable run across
    that boundary; a source counter change or a time-driven metric boundary
    causes a new run.
    Source business tables are never updated here. Synthetic batches cannot
    satisfy this cache, even when period and metric version are identical.
    """
    version_key = metric_version(product_scope)
    start, end, cutoff = map(utc, (period_start, period_end, now or datetime.now(timezone.utc)))
    tomorrow = (cutoff.astimezone(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    if start < DATA_START or start >= end or end > tomorrow or end - start > timedelta(days=366):
        raise ValueError("请选择2026-09-01至今天之间的有效日期范围，单次不超过366天")
    if not 1 <= max_period_rows <= 50000:
        raise ValueError("invalid snapshot row budget")

    ensure_lifecycle_schema(session)
    source_token = source_fingerprint(session)
    cached = reusable_business_snapshot(
        session,
        period_start=start,
        period_end=end,
        metric_version=version_key,
        source_token=source_token,
        now=cutoff,
    )
    if cached:
        return cached
    # Lifecycle bootstrap runs on the Session's connection before this
    # savepoint is opened. Keeping one nested transaction for SQLite as well
    # preserves atomic publication when calculation or source validation
    # fails; callers can roll back the outer transaction safely.
    with session.begin_nested():
        if session.bind.dialect.name == "postgresql":
            locked = session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"),
                                    {"key": RANKING_WRITE_LOCK})
            if not locked:
                raise ValueError("指标数据正在更新，请稍后刷新")
        source_token = source_fingerprint(session)
        cached = reusable_business_snapshot(
            session,
            period_start=start,
            period_end=end,
            metric_version=version_key,
            source_token=source_token,
            now=cutoff,
        )
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
            data_mode="business", max_period_rows=max_period_rows, product_scope=product_scope)
        # A source writer may commit while the calculation is hydrating its
        # rows.  Never publish a mixed batch: the caller retries from a clean
        # transaction after this savepoint rolls back.
        if source_fingerprint(session) != source_token:
            raise ValueError("榜单计算期间源数据发生变化，请稍后刷新")
        register_snapshot(
            session,
            run_id=run_id,
            source_token=source_token,
            next_refresh_at=_next_refresh_at(
                session,
                run_id,
                period_start=start,
                period_end=end,
                cutoff=cutoff,
            ),
            now=cutoff,
        )
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SELECT set_config('statement_timeout', :value, true)"),
                            {"value": original_timeout})
    return run_id
