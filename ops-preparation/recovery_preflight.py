"""DYDATA-102 read-only recovery preflight (fixed target, no writes).

Reads the current control-plane state needed to approve the scoped ordinal-2
recovery of the single fixed original root, and prints one JSON document.  This
script is a *diagnostic*: it never plans, stamps, enqueues, finalizes or writes
anything, and it never opens a writable transaction.

Hard guarantees, in order:

* The database session is opened exclusively through the official read-only
  helper ``dy_api.pdca_readonly_access._open_pdca_readonly_session``.  On
  PostgreSQL that helper issues ``SET TRANSACTION READ ONLY`` plus
  ``SET LOCAL statement_timeout = '8s'`` and ``SET LOCAL lock_timeout = '1s'``;
  this script then asserts ``SHOW transaction_read_only`` is ``on`` and only
  *reports* the retained statement/lock timeouts (it never overrides them).
  The generator is closed (never committed) so the helper's rollback teardown
  runs and the transaction stays read-only end to end.

* Only the fixed original root ``range-sync-10562f3369ac7d31e9801d42d8db1d60``,
  its recorded recovery generations and those generations' children, the
  settlement active-generation head, and 2026-09 month readiness are inspected.

* Every recovery-ledger fact is read through the official ``day_recovery``
  keys/functions (``recovery_generations``, ``recovery_config_version``,
  ``recovery_generation_by_request_key``, ``MAX_RECOVERY_GENERATIONS``), never
  re-derived from guessed metadata keys.

* Output is JSON containing only counts, job status/attempt/max-attempt/
  quota-pause/lease-expiry fields and recovery ordinal/request-key.  It never
  emits raw customer/account/order details, secrets, or database URLs.

Exit codes: 0 = preflight completed (findings are in the JSON, e.g. a missing
root or an already-allocated v2 request is reported, not treated as a crash);
2 = refused guard (database unavailable, unsupported dialect, read-only
transaction assertion failed); 1 = unexpected error (only the exception type is
printed).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

# The worker container ships PYTHONPATH=/app:/app/apps/api, so both ``dy_api.*``
# and ``apps.*`` resolve there.  Insert the same two roots for a local checkout
# so the identical import layout works without a host-specific path; these
# inserts are no-ops when the container's PYTHONPATH is already in effect.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_APPS_API = os.path.join(_REPO_ROOT, "apps", "api")
for _candidate in (_APPS_API, _REPO_ROOT):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from sqlalchemy import func, select, text

from dy_api.pdca_readonly_access import _open_pdca_readonly_session
from dy_api.db import get_engine
from apps.api.dy_api.models import (
    JobRun,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementStatement,
)
from apps.worker.day_recovery import (
    MAX_RECOVERY_GENERATIONS,
    recovery_config_version,
    recovery_generation_by_request_key,
    recovery_generations,
)
from apps.worker.month_close import (
    month_business_dates,
    month_close_preflight,
    published_days_revisions,
)

SCHEMA_VERSION = "dsh-recovery-preflight-v1"
ROOT_JOB_ID = "range-sync-10562f3369ac7d31e9801d42d8db1d60"
TARGET_DATE = date(2026, 9, 14)
BUSINESS_MONTH = "2026-09"
# The fixed ordinal-2 request key the prepared production driver already uses
# (.dsh-production-day-recovery.sh).  ``recovery_generation_by_request_key``
# answers "was this exact v2 request already allocated?" idempotently.
EXPECTED_V2_REQUEST_KEY = "dydata102-sep14-recovery-20261016-v2"


def _emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, indent=2), flush=True)


def _iso(value) -> str | None:
    return None if value is None else value.isoformat()


def _job_fields(row: JobRun) -> dict:
    """Operational fields only; never metadata_json, error text or payloads."""
    return {
        "job_id": row.job_id,
        "job_kind": row.job_kind,
        "status": row.status,
        "attempt_count": int(row.attempt_count or 0),
        "max_attempts": int(row.max_attempts or 0),
        "quota_pause_count": int(row.quota_pause_count or 0),
        "lease_expires_at": _iso(row.lease_expires_at),
        "cancel_requested_at": _iso(row.cancel_requested_at),
        "pause_after_stage_requested_at": _iso(row.pause_after_stage_requested_at),
    }


def _readonly_guard(session) -> dict:
    """Assert the session is really read-only and report the retained timeouts.

    PostgreSQL: ``SET TRANSACTION READ ONLY`` was already issued by the helper,
    so ``SHOW transaction_read_only`` must be ``on``; the helper's ``SET LOCAL``
    statement/lock timeouts are read back unchanged (never overridden).  SQLite
    (local smoke runs only) asserts ``PRAGMA query_only`` is 1.  Anything else
    is refused.
    """
    dialect = session.get_bind().dialect.name
    guard: dict = {"dialect": dialect}
    if dialect == "postgresql":
        transaction_read_only = str(
            session.execute(text("SHOW transaction_read_only")).scalar() or ""
        ).lower()
        statement_timeout = session.execute(text("SHOW statement_timeout")).scalar()
        lock_timeout = session.execute(text("SHOW lock_timeout")).scalar()
        guard["transaction_read_only"] = transaction_read_only
        guard["statement_timeout"] = str(statement_timeout) if statement_timeout is not None else None
        guard["lock_timeout"] = str(lock_timeout) if lock_timeout is not None else None
        if transaction_read_only != "on":
            raise RuntimeError("transaction_read_only_is_off")
        return guard
    if dialect == "sqlite":
        query_only = int(session.execute(text("PRAGMA query_only")).scalar() or 0)
        guard["query_only"] = query_only
        if query_only != 1:
            raise RuntimeError("query_only_is_off")
        return guard
    raise RuntimeError("unsupported_dialect")


def _children_of(session, parent_job_id: str | None) -> list[JobRun]:
    if not parent_job_id:
        return []
    return list(
        session.scalars(
            select(JobRun)
            .where(JobRun.parent_job_id == parent_job_id)
            .order_by(JobRun.job_id)
        )
    )


def _expected_v2_request(session) -> dict:
    recorded = recovery_generation_by_request_key(session, EXPECTED_V2_REQUEST_KEY)
    return {
        "request_key": EXPECTED_V2_REQUEST_KEY,
        "config_version": recovery_config_version(EXPECTED_V2_REQUEST_KEY),
        "allocated": recorded is not None,
        "allocated_parent_job_id": recorded.job_id if recorded is not None else None,
    }


def _active_generation(session) -> dict:
    active = session.get(SettlementProjectionActive, "settlement")
    if active is None or not active.generation_id:
        return {
            "present": False,
            "generation_id": None,
            "generation_kind": None,
            "lineage_depth": None,
            "state": None,
        }
    generation = session.get(SettlementProjectionGeneration, active.generation_id)
    if generation is None:
        return {
            "present": True,
            "generation_id": active.generation_id,
            "generation_kind": None,
            "lineage_depth": None,
            "state": None,
        }
    return {
        "present": True,
        "generation_id": generation.generation_id,
        "generation_kind": generation.generation_kind,
        "lineage_depth": int(generation.lineage_depth)
        if generation.lineage_depth is not None
        else None,
        "state": generation.state,
    }


def _september_readiness(session) -> dict:
    state, watermark = month_close_preflight(session, BUSINESS_MONTH)
    revisions = published_days_revisions(session, BUSINESS_MONTH)
    total = len(month_business_dates(BUSINESS_MONTH))
    return {
        "month_close_state": state,
        "watermark_present": watermark is not None,
        "published_days_count": len(revisions) if revisions is not None else None,
        "published_days_total": total,
        "source_complete": revisions is not None,
    }


def _september_counts(session) -> dict:
    fee_result = (
        session.scalar(
            select(func.count())
            .select_from(SettlementFeeResult)
            .where(SettlementFeeResult.original_business_month == BUSINESS_MONTH)
        )
        or 0
    )
    fee_result_current = (
        session.scalar(
            select(func.count())
            .select_from(SettlementFeeResultCurrent)
            .join(
                SettlementFeeResult,
                SettlementFeeResult.fee_result_id
                == SettlementFeeResultCurrent.fee_result_id,
            )
            .where(SettlementFeeResult.original_business_month == BUSINESS_MONTH)
        )
        or 0
    )
    statement = (
        session.scalar(
            select(func.count())
            .select_from(SettlementStatement)
            .where(SettlementStatement.statement_month == BUSINESS_MONTH)
        )
        or 0
    )
    return {
        "fee_result": int(fee_result),
        "fee_result_current": int(fee_result_current),
        "statement": int(statement),
    }


def _collect(session, guard: dict) -> dict:
    payload = {
        "schema": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "readonly_session": guard,
        "target": {
            "root_job_id": ROOT_JOB_ID,
            "business_date": TARGET_DATE.isoformat(),
            "business_month": BUSINESS_MONTH,
            "expected_v2_request_key": EXPECTED_V2_REQUEST_KEY,
        },
    }

    root = session.get(JobRun, ROOT_JOB_ID)
    payload["root_present"] = root is not None
    payload["root"] = _root_fields(root) if root is not None else None

    entries = recovery_generations(root) if root is not None else []
    generation_rows = []
    for entry in entries:
        ordinal = entry.get("ordinal")
        request_key = entry.get("request_key")
        config_version = entry.get("config_version")
        parent_job_id = entry.get("parent_job_id")
        row = {
            "ordinal": ordinal if isinstance(ordinal, int) else None,
            "request_key": request_key if isinstance(request_key, str) else None,
            "config_version": config_version
            if isinstance(config_version, str)
            else None,
            "parent_job_id": parent_job_id if isinstance(parent_job_id, str) else None,
        }
        parent_row = (
            session.get(JobRun, parent_job_id)
            if isinstance(parent_job_id, str)
            else None
        )
        row["parent"] = _job_fields(parent_row) if parent_row is not None else None
        row["children"] = (
            [_job_fields(child) for child in _children_of(session, parent_job_id)]
            if isinstance(parent_job_id, str)
            else []
        )
        generation_rows.append(row)

    used = len(entries)
    payload["recovery_generations"] = {
        "budget": MAX_RECOVERY_GENERATIONS,
        "used": used,
        "remaining": max(0, MAX_RECOVERY_GENERATIONS - used),
        "entries": generation_rows,
    }
    payload["expected_v2_request"] = _expected_v2_request(session)
    payload["settlement_active_generation"] = _active_generation(session)
    payload["september_readiness"] = _september_readiness(session)
    payload["september_counts"] = _september_counts(session)
    return payload


def _root_fields(root: JobRun) -> dict:
    fields = _job_fields(root)
    fields["config_version"] = root.config_version
    fields["data_source"] = root.data_source
    fields["target"] = (root.metadata_json or {}).get("target")
    fields["window_start"] = _iso(root.window_start)
    fields["window_end"] = _iso(root.window_end)
    return fields


def _self_check() -> int:
    _emit(
        {
            "self_check": "ok",
            "schema": SCHEMA_VERSION,
            "target": {
                "root_job_id": ROOT_JOB_ID,
                "business_date": TARGET_DATE.isoformat(),
                "business_month": BUSINESS_MONTH,
                "expected_v2_request_key": EXPECTED_V2_REQUEST_KEY,
                "expected_v2_config_version": recovery_config_version(
                    EXPECTED_V2_REQUEST_KEY
                ),
            },
            "recovery_budget": MAX_RECOVERY_GENERATIONS,
        }
    )
    return 0


def main() -> int:
    if "--self-check" in sys.argv[1:]:
        return _self_check()

    engine = get_engine()
    if engine is None:
        _emit({"error": {"reason": "database_unavailable"}})
        return 2
    if engine.dialect.name not in {"postgresql", "sqlite"}:
        _emit(
            {
                "error": {
                    "reason": "unsupported_dialect",
                    "dialect": engine.dialect.name,
                }
            }
        )
        return 2

    sessions = _open_pdca_readonly_session()
    try:
        try:
            session = next(sessions)
        except StopIteration:
            _emit({"error": {"reason": "readonly_session_empty"}})
            return 2
        try:
            guard = _readonly_guard(session)
            _emit(_collect(session, guard))
            return 0
        except Exception as exc:  # noqa: BLE001 - type-only, no exception text
            _emit(
                {
                    "error": {
                        "reason": "preflight_failed",
                        "type": type(exc).__name__,
                    }
                }
            )
            return 1
    except Exception as exc:  # noqa: BLE001 - opening the session failed
        _emit(
            {
                "error": {
                    "reason": "readonly_session_unavailable",
                    "type": type(exc).__name__,
                }
            }
        )
        return 2
    finally:
        try:
            sessions.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
