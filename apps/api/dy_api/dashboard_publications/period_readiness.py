"""Background-only collection completeness for formal financial periods."""
from datetime import UTC, date, datetime
import hashlib
import json
from zoneinfo import ZoneInfo

FORMAL_START = "2026-08"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def formal_months(through_month: str) -> tuple[str, ...]:
    """Return the finite formal prefix through a validated request month."""
    end = date.fromisoformat(f"{through_month}-01")
    start = date.fromisoformat(f"{FORMAL_START}-01")
    return tuple(f"{number // 12:04d}-{number % 12 + 1:02d}" for number in range(
        start.year * 12 + start.month - 1, end.year * 12 + end.month))


def capture(session, cutoff: datetime) -> dict:
    """Read the scheduler's owning-generation state; never dispatch or bill.

    Only formal months through the current Shanghai month are inspected. The
    unfinished current month stays unavailable even if future task rows exist.
    A complete month with no fee results is still a valid analytical zero.
    """
    from apps.worker.month_close import month_business_dates
    from apps.worker.priority_scheduler import MAX_PRIORITY_ROWS, _day_state, _priority_rows_for_day

    cutoff = cutoff.replace(tzinfo=UTC) if cutoff.tzinfo is None else cutoff
    local = cutoff.astimezone(SHANGHAI)
    current_month = local.strftime("%Y-%m")
    months = {}
    for month in formal_months(current_month):
        days = month_business_dates(month)
        successes = 0
        revisions = []
        for day in days:
            if day >= local.date():
                continue
            rows = _priority_rows_for_day(session, day)
            # The scheduler query is capped; a saturated page cannot prove
            # that the owning generation and all required domains were read.
            if len(rows) >= MAX_PRIORITY_ROWS:
                continue
            state = _day_state(day, rows)
            finalizers = [row for row in state.rows if row.job_kind == "finalize"]
            if state.state == "success" and len(finalizers) == 1:
                successes += 1
                revisions.append(f"{day.isoformat()}@{finalizers[0].job_id}")
        months[month] = {
            "ready": month < current_month and successes == len(days),
            "success_days": successes, "total_days": len(days),
            "revision": hashlib.sha256(";".join(revisions).encode()).hexdigest()[:16],
        }
    return {"schema_version": 1, "formal_start_month": FORMAL_START, "months": months}


def fingerprint(snapshot: dict) -> str:
    """Hash the same small snapshot frozen by the domain builder."""
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require(snapshot: dict | None, month: str, *, cumulative: bool) -> None:
    """Fail closed from frozen metadata only; never inspect current tasks."""
    from .lifecycle import PublicationError

    if month < FORMAL_START:
        return  # Preserve the existing explicit pre-formal history contract.
    months = snapshot.get("months") if isinstance(snapshot, dict) and snapshot.get("schema_version") == 1 else None
    # Check the requested month before expanding a prefix: future/missing
    # periods cannot trigger an unbounded range in a reader.
    if not isinstance(months, dict) or month not in months:
        required = (month,)
        months = {}
    else:
        required = formal_months(month) if cumulative else (month,)
    if any(
        not isinstance(months.get(key), dict) or months[key].get("ready") is not True
        for key in required
    ):
        raise PublicationError("PUBLICATION_PERIOD_NOT_READY",
            f"{month}账期数据尚未准备完成，请稍后重试；未展示未完成账期的金额。", 503)
