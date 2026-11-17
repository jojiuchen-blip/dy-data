"""Frozen collection and billing readiness for formal financial periods."""
from datetime import UTC, date, datetime
import hashlib
import json
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

FORMAL_START = "2026-08"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def signed_legacy_statement_condition(statement):
    """Previously confirmed or locked bills retain their existing authority."""
    return or_(statement.statement_status.in_((3, 4)), statement.confirmed_at.is_not(None),
               statement.locked_at.is_not(None))


def formal_months(through_month: str) -> tuple[str, ...]:
    """Return the finite formal prefix through a validated request month."""
    end = date.fromisoformat(f"{through_month}-01")
    start = date.fromisoformat(f"{FORMAL_START}-01")
    return tuple(f"{number // 12:04d}-{number % 12 + 1:02d}" for number in range(
        start.year * 12 + start.month - 1, end.year * 12 + end.month))


def capture(session, cutoff: datetime) -> dict:
    """Read scheduler and close certificates without dispatching or billing."""
    from apps.worker.month_close import month_business_dates
    from apps.worker.priority_scheduler import MAX_PRIORITY_ROWS, _day_state, _priority_rows_for_day
    from apps.worker.account_qualification import FIRST_MONTH
    from src.dy_data.settlement_schedule import monthly_settlement_enabled
    from ..models import SettlementMonthClose, SettlementStatement

    cutoff = cutoff.replace(tzinfo=UTC) if cutoff.tzinfo is None else cutoff
    local = cutoff.astimezone(SHANGHAI)
    current_month = local.strftime("%Y-%m")
    monthly_mode = monthly_settlement_enabled()
    certificates = {}
    frozen_stores = {}
    if monthly_mode:
        certificates = {row.business_month: row for row in session.scalars(select(SettlementMonthClose).where(
            SettlementMonthClose.business_month < current_month))}
        for store_id, month in session.execute(select(SettlementStatement.store_id, SettlementStatement.statement_month).where(
            SettlementStatement.is_current.is_(True),
            or_(SettlementStatement.monthly_close_input_sha256.is_not(None),
                signed_legacy_statement_condition(SettlementStatement)),
            SettlementStatement.statement_month < current_month,
        )):
            frozen_stores.setdefault(month, []).append(store_id)
    months = {}
    for month in formal_months(current_month):
        days = month_business_dates(month)
        revisions = []
        for day in days:
            if day >= local.date():
                continue
            rows = _priority_rows_for_day(session, day)
            # A saturated query cannot prove the owning generation and all domains.
            if len(rows) >= MAX_PRIORITY_ROWS:
                continue
            state = _day_state(day, rows)
            finalizers = [row for row in state.rows if row.job_kind == "finalize"]
            if state.state == "success" and len(finalizers) == 1:
                revisions.append(f"{day.isoformat()}@{finalizers[0].job_id}")
        months[month] = {
            "ready": month < current_month and len(revisions) == len(days),
            "success_days": len(revisions), "total_days": len(days),
            "revision": hashlib.sha256(";".join(revisions).encode()).hexdigest()[:16],
        }
        if monthly_mode and month >= FIRST_MONTH:
            certificate = certificates.get(month)
            published = sorted(frozen_stores.get(month, ()))
            months[month]["monthly_close"] = {
                "status": ("complete" if certificate is not None and certificate.is_complete
                           else "partial" if published else "waiting"),
                "published_store_ids": published,
                "blocked_store_ids": certificate.blocked_store_ids if certificate is not None else [],
                "scope_unresolved": certificate is None or certificate.unscoped_issue_count > 0,
            }
            if published or (certificate is not None and certificate.is_complete):
                # Later upstream retries cannot retract a frozen bill.
                months[month]["ready"] = True
    return {"schema_version": 1, "formal_start_month": FORMAL_START, "months": months}


def fingerprint(snapshot: dict) -> str:
    """Hash the small snapshot frozen by the domain builder."""
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def monthly_close_entry(snapshot: dict | None, month: str | None) -> dict | None:
    from apps.worker.account_qualification import FIRST_MONTH
    from src.dy_data.settlement_schedule import monthly_settlement_enabled

    if not monthly_settlement_enabled() or month is None or month < FIRST_MONTH:
        return None
    periods = (snapshot.get("months") or {}) if isinstance(snapshot, dict) else {}
    return (periods.get(month) or {}).get("monthly_close") or {
        "status": "waiting", "published_store_ids": [], "blocked_store_ids": [], "scope_unresolved": True,
    }


def close_store_amount_ready(entry: dict | None, store_id: str) -> bool:
    return (entry is None or entry["status"] == "complete"
            or store_id in entry["published_store_ids"]
            or (entry["status"] == "partial" and not entry["scope_unresolved"]
                and store_id not in entry["blocked_store_ids"]))


def _status_summary(entry: dict, scope_store_ids: tuple[str, ...] | None) -> dict:
    def count(stores):
        return len(stores) if scope_store_ids is None else len(set(stores).intersection(scope_store_ids))

    return {"status": entry["status"], "published_store_count": count(entry["published_store_ids"]),
            "blocked_store_count": count(entry["blocked_store_ids"]), "scope_unresolved": entry["scope_unresolved"]}


def public_period_snapshot(snapshot: dict | None, scope_store_ids: tuple[str, ...] | None) -> dict | None:
    if not isinstance(snapshot, dict):
        return snapshot
    periods = {}
    for month, facts in (snapshot.get("months") or {}).items():
        entry = monthly_close_entry(snapshot, month)
        periods[month] = {key: value for key, value in facts.items() if key != "monthly_close"}
        if entry is not None:
            periods[month]["monthly_close"] = _status_summary(entry, scope_store_ids)
    return {**snapshot, "months": periods}


def availability(
    snapshot: dict | None, month: str, *, store_id: str | None = None,
    scope_store_ids: tuple[str, ...] | None = None,
) -> dict:
    """Assess the selected month and formal prefix using only frozen evidence."""
    if month < FORMAL_START:
        return {"monthly_ready": True, "cumulative_ready": True, "incomplete_months": []}
    months = snapshot.get("months") if isinstance(snapshot, dict) and snapshot.get("schema_version") == 1 else None
    if not isinstance(months, dict) or month not in months:
        required = (month,)
        months = {}
    else:
        required = formal_months(month)

    def raw_ready(key):
        return isinstance(months.get(key), dict) and months[key].get("ready") is True

    def complete(key):
        entry = monthly_close_entry(snapshot, key)
        return raw_ready(key) and (entry is None or (close_store_amount_ready(entry, store_id) if store_id is not None
                                                    else entry["status"] == "complete"))

    incomplete = [key for key in required if not complete(key)]
    selected = monthly_close_entry(snapshot, month)
    monthly_ready = month not in incomplete
    result = {}
    if selected is not None:
        summary = _status_summary(selected, scope_store_ids)
        if store_id is None and raw_ready(month) and summary["published_store_count"] > 0:
            monthly_ready = True
        result["monthly_close"] = summary
    return {**result, "monthly_ready": monthly_ready, "cumulative_ready": not incomplete, "incomplete_months": incomplete}


def require(snapshot: dict | None, month: str, *, cumulative: bool, store_id: str | None = None,
            scope_store_ids: tuple[str, ...] | None = None) -> dict:
    """Fail closed from frozen metadata only."""
    from .lifecycle import PublicationError

    result = availability(snapshot, month, store_id=store_id, scope_store_ids=scope_store_ids)
    if not result["cumulative_ready" if cumulative else "monthly_ready"]:
        raise PublicationError("PUBLICATION_PERIOD_NOT_READY",
            f"{month}账期数据尚未准备完成，请稍后重试；未展示未完成账期的金额。", 503)
    return result
