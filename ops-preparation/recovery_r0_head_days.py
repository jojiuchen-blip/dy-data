#!/usr/bin/env python3
"""DYDATA-104 / R0 read-only probe A: current head, gap days, recovery budgets.

STATUS: authored for controller review. NOT uploaded to production and NOT
executed against the database during R0 (R0 authorizes SSH resource reads only).

Where it must run
-----------------
Inside the *worker* container (never the API process), from the repository root,
so that `apps.*` is importable and `DY_DATABASE_URL`/`DATABASE_URL` is already set
by the container environment:

    docker compose -f deploy/compose.yaml --env-file /opt/dy-dashboard/env/production.env \
        exec -T <worker-service> python - < .dsh-recovery-r0-probe-20261021.py --confirm-read-only

Read-only guarantees (defense in depth, all independent)
-------------------------------------------------------
1. libpq options pin the whole session to `default_transaction_read_only=on`,
   so the server rejects any write even if the code below is wrong.
2. Explicit `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`.
3. `statement_timeout=3s`, `lock_timeout=500ms`,
   `idle_in_transaction_session_timeout=15s`, and `connect_timeout=5s`.
4. Total wall clock cap of 45s via SIGALRM, armed *before* any database access.
5. Explicit `rollback()` in a `finally` block; it never commits.
6. Reads only. It does not call any writer, does not create tables/temp tables,
   does not claim, lease, retry, cancel or mark jobs, and does not touch budgets.

Output
------
One JSON document on stdout. No row-level order/store/account identifiers.
Frozen readiness/filters are read from `dashboard_publication_finance_dimensions`
(the real storage location), not from `stats_json`; only the whitelisted month
fields and `statement_months`/`sale_months` are returned. Stats values are never
returned, only a key count. Error text is truncated and redacted (URLs including
`postgresql+psycopg://`, cookies, tokens, credentials).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import signal
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
WALL_CLOCK_SECONDS = 45
CONNECT_TIMEOUT_SECONDS = 5
TARGET_MONTHS = ("2026-08", "2026-09")
SEP14_FOCUS = date(2026, 9, 14)

# Publication modules that gate the settlement / finance pages (main: sources.py).
TARGET_MODULES = ("settlement", "finance")
# Bounded reads: daily plans normally own three children; a larger set is refused
# instead of silently truncated so a finalizer failure can never be hidden.
MAX_CHILDREN_PER_PARENT = 20
MAX_RECOVERY_ROOTS = 64
# Controller-fixed ordinal-2 RAW service request key for 2026-09-14. The
# controlled CLI path passes this key directly to plan_day_recovery; unlike the
# HTTP API, it does NOT hash the header. The probe only *checks* whether this
# exact raw key was allocated; it never creates a key or a generation.
SEP14_V2_REQUEST_KEY = "dydata102-sep14-recovery-20261016-v2"

_URL_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s\"'<>]+")
_SECRET_RE = re.compile(
    r"(?i)\b(cookie|token|secret|password|passwd|authorization|bearer|session"
    r"|api[_-]?key|sign|sess|access[_-]?key|private[_-]?key)\b\s*[=:]\s*\S+"
)
_EMAIL_RE = re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]+\b")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LONG_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{32,}")


class _Timeout(Exception):
    pass


class _Saturated(RuntimeError):
    """A bounded read hit its cap; the probe refuses to guess."""


def _alarm(_signum, _frame):
    raise _Timeout(f"wall clock {WALL_CLOCK_SECONDS}s exceeded")


def _mask(text: str | None, limit: int = 200) -> str | None:
    """Truncate and redact anything that could carry a secret or identifier."""
    if not text:
        return text
    out = str(text)
    out = _URL_RE.sub("<url>", out)
    out = _EMAIL_RE.sub("<email>", out)
    out = _PHONE_RE.sub("<phone>", out)
    out = _SECRET_RE.sub(r"\1=<redacted>", out)
    out = _LONG_TOKEN_RE.sub("<longtoken>", out)
    out = out.replace("\r", " ").replace("\n", " ").strip()
    return out[:limit] + ("…" if len(out) > limit else "")


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _value(row, name: str):
    """Read a field from either a JobRun object or a SQLAlchemy RowMapping."""
    try:
        return row[name]
    except (KeyError, TypeError):
        return getattr(row, name, None)


def _brief(row) -> dict:
    return {
        "job_id": _value(row, "job_id"),
        "job_name": _value(row, "job_name"),
        "job_kind": _value(row, "job_kind"),
        "status": _value(row, "status"),
        "attempt_count": int(_value(row, "attempt_count") or 0),
        "max_attempts": int(_value(row, "max_attempts") or 0),
        "quota_pause_count": int(_value(row, "quota_pause_count") or 0),
        "lease_expires_at": _iso(_value(row, "lease_expires_at")),
        "cancel_requested_at": _iso(_value(row, "cancel_requested_at")),
        "pause_after_stage_requested_at": _iso(
            _value(row, "pause_after_stage_requested_at")
        ),
        "current_stage": _value(row, "current_stage"),
        "error_code": _value(row, "error_code"),
        "error_summary": _mask(_value(row, "error_summary")),
    }


def _root_identity(row) -> dict:
    metadata = _value(row, "metadata_json") or {}
    return {
        "job_id": _value(row, "job_id"),
        "job_kind": _value(row, "job_kind"),
        "job_name": _value(row, "job_name"),
        "parent_job_id": _value(row, "parent_job_id"),
        "config_version": _value(row, "config_version"),
        "business_date": _iso(_value(row, "business_date")),
        "data_source": _value(row, "data_source"),
        "target": metadata.get("target"),
        "window_start": _iso(_value(row, "window_start")),
        "window_end": _iso(_value(row, "window_end")),
        "status": _value(row, "status"),
        "attempt_count": int(_value(row, "attempt_count") or 0),
        "max_attempts": int(_value(row, "max_attempts") or 0),
        "quota_pause_count": int(_value(row, "quota_pause_count") or 0),
        "lease_expires_at": _iso(_value(row, "lease_expires_at")),
        "lease_is_live": _lease_is_live(_value(row, "lease_expires_at")),
        "cancel_requested_at": _iso(_value(row, "cancel_requested_at")),
        "pause_after_stage_requested_at": _iso(
            _value(row, "pause_after_stage_requested_at")
        ),
        "error_code": _value(row, "error_code"),
        "error_summary": _mask(_value(row, "error_summary")),
        "recovery_root_job_id": metadata.get("recovery_root_job_id"),
        "recovery_ordinal": metadata.get("recovery_ordinal"),
        "recovery_request_key": metadata.get("recovery_request_key"),
    }


def _lease_is_live(value) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > datetime.now(timezone.utc)


def _month_days(month: str) -> tuple[date, ...]:
    """Every calendar date of a YYYY-MM month (mirrors month_close)."""
    start = date.fromisoformat(f"{month}-01")
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return tuple(start + timedelta(days=i) for i in range((nxt - start).days))


def _readiness_view(value) -> dict | None:
    """Only the per-month whitelist needed to explain the 503 gate."""
    if not isinstance(value, dict):
        return None
    months = value.get("months")
    view: dict = {"months": {}}
    if isinstance(months, dict):
        for month, info in months.items():
            if not isinstance(info, dict):
                continue
            view["months"][month] = {
                key: info.get(key)
                for key in ("ready", "success_days", "total_days", "revision")
            }
    return view


def _filters_view(value) -> dict | None:
    """Only the two frozen selector lists permitted by the review."""
    if not isinstance(value, dict):
        return None
    return {
        "statement_months": value.get("statement_months"),
        "sale_months": value.get("sale_months"),
    }


def _open_attempts(session, job_ids) -> dict[str, int]:
    from sqlalchemy import text

    ids = sorted({str(job_id) for job_id in job_ids if job_id})
    if not ids:
        return {}
    params = {f"jid_{index}": job_id for index, job_id in enumerate(ids)}
    placeholders = ", ".join(f":jid_{index}" for index in range(len(ids)))
    rows = session.execute(
        text(
            "SELECT job_id, COUNT(*) AS open_attempts FROM job_attempts "
            "WHERE finished_at IS NULL AND job_id IN (" + placeholders + ") "
            "GROUP BY job_id"
        ),
        params,
    ).all()
    return {row[0]: int(row[1]) for row in rows}


def _children_for_parent(session, parent_job_id: str, cache: dict) -> list[dict]:
    if parent_job_id in cache:
        return cache[parent_job_id]
    from sqlalchemy import text

    rows = session.execute(
        text(
            """
            SELECT job_id, job_name, job_kind, status, attempt_count, max_attempts,
                   quota_pause_count, lease_expires_at,
                   cancel_requested_at, pause_after_stage_requested_at,
                   current_stage, error_code, error_summary
              FROM job_runs
             WHERE parent_job_id = :parent_job_id
             ORDER BY job_id
             LIMIT :limit
            """
        ),
        {"parent_job_id": parent_job_id, "limit": MAX_CHILDREN_PER_PARENT + 1},
    ).mappings().all()
    if len(rows) > MAX_CHILDREN_PER_PARENT:
        raise _Saturated(
            f"parent {parent_job_id} owns more than {MAX_CHILDREN_PER_PARENT} children"
        )
    open_counts = _open_attempts(session, [row["job_id"] for row in rows])
    children = [
        {**_brief(row), "open_attempts": int(open_counts.get(row["job_id"], 0))}
        for row in rows
    ]
    cache[parent_job_id] = children
    return children


def _ledger_view(ledger: list[dict]) -> list[dict]:
    view = []
    for entry in ledger:
        if not isinstance(entry, dict):
            continue
        view.append(
            {
                "ordinal": entry.get("ordinal"),
                "config_version": entry.get("config_version"),
                "parent_job_id": entry.get("parent_job_id"),
                "request_key": entry.get("request_key"),
                "reason": _mask(entry.get("reason"), 120),
                "requested_at": entry.get("requested_at"),
            }
        )
    return view


def _base_roots(session, captured_rows, state):
    """Original base root(s) of one missing day, from rows already captured.

    A recovery generation points at its original root via `recovery_root_job_id`.
    Otherwise the captured base `range_sync` parent(s) are used; only a missing
    root row is fetched by primary key (never an all-row scan).
    """
    from apps.worker.day_recovery import (
        PRIORITY_CONFIG_VERSION,
        RECOVERY_CONFIG_PREFIX,
        RECOVERY_ROOT_KEY,
    )
    from apps.api.dy_api.models import JobRun

    winner = state.parent
    if winner is not None and str(winner.config_version or "").startswith(
        RECOVERY_CONFIG_PREFIX
    ):
        root_id = (winner.metadata_json or {}).get(RECOVERY_ROOT_KEY)
        root = next((row for row in captured_rows if row.job_id == root_id), None)
        if root is None and root_id:
            root = session.get(JobRun, root_id)
        return [root] if root is not None else []

    bases = [
        row
        for row in captured_rows
        if row.job_kind == "range_sync"
        and row.parent_job_id is None
        and row.config_version == PRIORITY_CONFIG_VERSION
        and (row.metadata_json or {}).get("target") == "all"
    ]
    if winner is not None and winner in bases:
        bases.sort(key=lambda row: row.job_id != winner.job_id)
    return bases


def _sep14_v2_check(session, root, ledger: list[dict], raw_key: str) -> dict:
    """Check the fixed ordinal-2 key allocation without allocating anything."""
    from sqlalchemy import text
    from apps.worker.day_recovery import (
        MAX_RECOVERY_GENERATIONS,
        RECOVERY_ORDINAL_KEY,
        RECOVERY_ROOT_KEY,
        plan_window_matches,
        recovery_config_version,
    )

    normalized = (raw_key or "").strip()
    request_key_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    expected_config_version = recovery_config_version(normalized)
    ledger_two = next(
        (
            entry
            for entry in ledger
            if isinstance(entry, dict) and entry.get("ordinal") == 2
        ),
        None,
    )
    rows = session.execute(
        text(
            """
            SELECT job_id, job_kind, status, config_version, parent_job_id,
                   data_source, window_start, window_end, metadata_json
              FROM job_runs
             WHERE job_kind = 'range_sync'
               AND parent_job_id IS NULL
               AND config_version = :config_version
             ORDER BY job_id
             LIMIT 3
            """
        ),
        {"config_version": expected_config_version},
    ).mappings().all()

    checks: dict[str, bool] = {}
    if len(rows) == 1:
        row = rows[0]
        metadata = row["metadata_json"] or {}
        checks = {
            "root_matches": metadata.get(RECOVERY_ROOT_KEY) == root.job_id,
            "ordinal_is_2": metadata.get(RECOVERY_ORDINAL_KEY) == 2,
            "request_key_matches": metadata.get("recovery_request_key")
            == normalized,
            "window_matches": plan_window_matches(row["window_start"], root.window_start)
            and plan_window_matches(row["window_end"], root.window_end),
            "data_source_matches": row["data_source"] == root.data_source,
            "target_all": metadata.get("target") == "all",
        }

    if ledger_two is not None:
        if ledger_two.get("config_version") != expected_config_version:
            state = "already_allocated_with_other_key"
        elif not rows:
            state = "conflict_ledger_without_row"
        elif len(rows) > 1:
            state = "conflict_duplicate_rows"
        elif checks and all(checks.values()) and (
            ledger_two.get("parent_job_id") == rows[0]["job_id"]
            and ledger_two.get("request_key") == normalized
        ):
            state = "allocated_matching_identity"
        else:
            state = "conflict_identity"
    elif rows:
        state = "conflict_row_without_ledger"
    else:
        state = "not_allocated"

    return {
        "state": state,
        "expected_ordinal": 2,
        "expected_config_version": expected_config_version,
        "request_key": normalized,
        "request_key_sha256": request_key_sha256,
        "request_key_length": len(normalized),
        "ledger_ordinal_2": None
        if ledger_two is None
        else {
            "config_version": ledger_two.get("config_version"),
            "parent_job_id": ledger_two.get("parent_job_id"),
            "request_key": ledger_two.get("request_key"),
        },
        "matching_rows": len(rows),
        "identity_checks": checks,
        "budget": {
            "max_generations": MAX_RECOVERY_GENERATIONS,
            "allocated": len(ledger),
            "next_ordinal": len(ledger) + 1,
            "within_budget": len(ledger) < MAX_RECOVERY_GENERATIONS,
        },
        "note": "read-only allocation check; no key or generation is created",
    }


def _root_detail(session, root, captured_rows, missing_days, children_cache, raw_v2_key):
    from apps.worker.day_recovery import (
        MAX_RECOVERY_GENERATIONS,
        RECOVERY_GENERATIONS_KEY,
    )
    from apps.api.dy_api.models import JobRun

    metadata = root.metadata_json or {}
    ledger = metadata.get(RECOVERY_GENERATIONS_KEY)
    ledger = [entry for entry in ledger if isinstance(entry, dict)] if isinstance(ledger, list) else []

    generation_rows = []
    for entry in ledger:
        parent_id = entry.get("parent_job_id")
        row = next((item for item in captured_rows if item.job_id == parent_id), None)
        if row is None and parent_id:
            row = session.get(JobRun, parent_id)
        if row is None:
            generation_rows.append(
                {
                    "ordinal": entry.get("ordinal"),
                    "parent_job_id": parent_id,
                    "row_present": False,
                }
            )
            continue
        generation_rows.append(
            {
                **_root_identity(row),
                "ledger_ordinal": entry.get("ordinal"),
                "ledger_config_version": entry.get("config_version"),
                "ledger_request_key": entry.get("request_key"),
                "children": _children_for_parent(session, row.job_id, children_cache),
            }
        )

    detail = {
        "root_identity": _root_identity(root),
        "missing_days": missing_days,
        "children": _children_for_parent(session, root.job_id, children_cache),
        "open_attempts": _open_attempts(
            session,
            [root.job_id]
            + [
                entry.get("parent_job_id")
                for entry in ledger
                if entry.get("parent_job_id")
            ],
        ),
        "budget": {
            "max_generations": MAX_RECOVERY_GENERATIONS,
            "allocated": len(ledger),
            "remaining": max(0, MAX_RECOVERY_GENERATIONS - len(ledger)),
        },
        "ledger": _ledger_view(ledger),
        "recovery_generations": generation_rows,
    }

    root_day = _job_business_day(root)
    if root_day == SEP14_FOCUS:
        detail["sep14_v2_allocation"] = _sep14_v2_check(
            session, root, ledger, raw_v2_key
        )
    return detail


def _job_business_day(row) -> date | None:
    value = _value(row, "business_date")
    if value is not None:
        return value
    start = _value(row, "window_start")
    if start is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start.astimezone(SHANGHAI).date()


def probe(conn, *, sep14_v2_key: str) -> dict:
    # Imported AFTER the read-only transaction is open: import side effects, if
    # any, still cannot write.
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from apps.worker.priority_scheduler import (
        MAX_PRIORITY_ROWS,
        _day_state,
        _priority_rows_for_day,
    )
    from apps.worker.day_recovery import RECOVERY_ROOT_KEY

    session = Session(bind=conn, autoflush=False, autocommit=False, future=True)
    result: dict = {
        "probe": "r0-head-day-gaps-recovery",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only_enforced": True,
        "settings": {},
        "publications": {},
        "projection_head": {},
        "compaction_jobs_latest": [],
        "heavy_running_jobs": [],
        "day_gaps": {},
        "recovery_budgets": {
            "max_roots": MAX_RECOVERY_ROOTS,
            "max_children_per_parent": MAX_CHILDREN_PER_PARENT,
            "missing_day_roots": [],
            "roots": [],
            "saturated": False,
        },
        "warnings": [],
    }

    for name in (
        "default_transaction_read_only",
        "transaction_isolation",
        "transaction_read_only",
        "statement_timeout",
        "lock_timeout",
        "idle_in_transaction_session_timeout",
        "server_version",
    ):
        result["settings"][name] = session.execute(text(f"SHOW {name}")).scalar()
    if (
        str(result["settings"].get("default_transaction_read_only")).lower() != "on"
        or str(result["settings"].get("transaction_read_only")).lower() != "on"
    ):
        raise RuntimeError("refusing to continue: session is not read-only")

    # ---- 1. current publication head (real dimensions table) --------------
    for module in TARGET_MODULES:
        row = session.execute(
            text(
                """
                SELECT r.id, r.status, r.cutoff, r.data_as_of, r.published_at,
                       r.next_refresh_at, r.stats_json
                  FROM dashboard_publication_heads h
                  JOIN dashboard_publication_runs  r
                    ON r.module = h.module AND r.id = h.publication_id
                 WHERE h.module = :module
                """
            ),
            {"module": module},
        ).mappings().first()
        latest = session.execute(
            text(
                """
                SELECT status FROM dashboard_publication_runs
                 WHERE module = :module
                 ORDER BY created_at DESC, id DESC LIMIT 1
                """
            ),
            {"module": module},
        ).scalar()
        entry: dict = {"head_present": row is not None, "latest_run_status": latest}
        if row is not None:
            stats = row["stats_json"] or {}
            entry.update(
                {
                    "publication_id": row["id"],
                    "run_status": row["status"],
                    "cutoff": _iso(row["cutoff"]),
                    "data_as_of": _iso(row["data_as_of"]),
                    "published_at": _iso(row["published_at"]),
                    "next_refresh_at": _iso(row["next_refresh_at"]),
                    # Stats may contain arbitrary builder detail: expose counts only.
                    "stats_json_counts": {
                        "key_count": len(stats) if isinstance(stats, dict) else 0,
                    },
                }
            )
            dimensions = session.execute(
                text(
                    """
                    SELECT kind, key, value
                      FROM dashboard_publication_finance_dimensions
                     WHERE publication_id = :publication_id
                       AND ((kind = 'period_readiness' AND key = 'v1')
                            OR (kind = 'filters' AND key = 'all'))
                    """
                ),
                {"publication_id": row["id"]},
            ).mappings().all()
            by_key = {(item["kind"], item["key"]): item["value"] for item in dimensions}
            entry["frozen_period_readiness"] = _readiness_view(
                by_key.get(("period_readiness", "v1"))
            )
            entry["frozen_filters"] = _filters_view(by_key.get(("filters", "all")))
            entry["dimension_rows_read"] = {
                "period_readiness": ("period_readiness", "v1") in by_key,
                "filters": ("filters", "all") in by_key,
            }
        else:
            result["warnings"].append(f"{module}: no publication head row")
        result["publications"][module] = entry

    # ---- 2. active settlement projection head, compaction and heavy jobs --
    projection = session.execute(
        text(
            """
            SELECT a.generation_id, g.generation_kind, g.lineage_depth, g.state,
                   g.published_at
              FROM settlement_projection_active a
              JOIN settlement_projection_generation g
                ON g.generation_id = a.generation_id
             WHERE a.projection_name = 'settlement'
            """
        )
    ).mappings().first()
    result["projection_head"] = {
        "present": projection is not None,
        "generation_id": projection["generation_id"] if projection else None,
        "generation_kind": projection["generation_kind"] if projection else None,
        "lineage_depth": projection["lineage_depth"] if projection else None,
        "state": projection["state"] if projection else None,
        "published_at": _iso(projection["published_at"]) if projection else None,
    }

    compaction_rows = session.execute(
        text(
            """
            SELECT job_id, job_name, status, started_at, finished_at,
                   attempt_count, max_attempts, lease_expires_at,
                   cancel_requested_at, pause_after_stage_requested_at,
                   current_stage, error_code, error_summary
              FROM job_runs
             WHERE job_name = 'settlement_compaction'
             ORDER BY started_at DESC, job_id DESC
             LIMIT 3
            """
        )
    ).mappings().all()
    result["compaction_jobs_latest"] = [
        {**_brief(row), "started_at": _iso(row["started_at"]),
         "finished_at": _iso(row["finished_at"])}
        for row in compaction_rows
    ]

    heavy_rows = session.execute(
        text(
            """
            SELECT job_id, job_name, job_kind, current_stage, lease_expires_at,
                   started_at
              FROM job_runs
             WHERE execution_slot = 'heavy_sync' AND status = 'running'
             ORDER BY started_at DESC, job_id
             LIMIT 10
            """
        )
    ).mappings().all()
    result["heavy_running_jobs"] = [
        {
            "job_id": row["job_id"],
            "job_name": row["job_name"],
            "job_kind": row["job_kind"],
            "current_stage": row["current_stage"],
            "lease_expires_at": _iso(row["lease_expires_at"]),
            "started_at": _iso(row["started_at"]),
        }
        for row in heavy_rows
    ]

    # ---- 3. generation-aware day gaps for Aug/Sep 2026 --------------------
    children_cache: dict = {}
    missing_days: list[tuple[str, date, tuple, object]] = []
    for month in TARGET_MONTHS:
        days = _month_days(month)
        ok_days: list[str] = []
        gaps: list[dict] = []
        saturated: list[str] = []
        for day in days:
            rows = _priority_rows_for_day(session, day)
            if len(rows) >= MAX_PRIORITY_ROWS:
                saturated.append(day.isoformat())
                continue
            state = _day_state(day, rows)
            finalizers = [r for r in state.rows if r.job_kind == "finalize"]
            if state.state == "success" and len(finalizers) == 1:
                ok_days.append(day.isoformat())
                continue
            detail = {
                "day": day.isoformat(),
                "winning_state": state.state,
                "winning_parent_job_id": state.parent.job_id if state.parent else None,
                "winning_parent": _brief(state.parent) if state.parent else None,
                # Explicitly separate the owning generation's claimable rows ...
                "owned_claimable_rows": [_brief(row) for row in state.rows],
                # ... from children observed by parent_job_id. A failed winning
                # parent exposes no owned rows, so this is where the finalizer
                # failure becomes visible.
                "observed_children": [],
            }
            if state.parent is not None:
                detail["observed_children"] = _children_for_parent(
                    session, state.parent.job_id, children_cache
                )
            gaps.append(detail)
            missing_days.append((month, day, rows, state))
        result["day_gaps"][month] = {
            "total_days": len(days),
            "success_days": len(ok_days),
            "incomplete_dates": [gap["day"] for gap in gaps],
            "saturated_days": saturated,
            "incomplete_detail": gaps,
        }
        if saturated:
            result["warnings"].append(
                f"{month}: {len(saturated)} day(s) hit MAX_PRIORITY_ROWS="
                f"{MAX_PRIORITY_ROWS}; state not proven"
            )

    # ---- 4. recovery budgets for every missing day (Aug and Sep) ----------
    root_candidates: dict[str, tuple] = {}
    missing_roots: list[dict] = []
    for month, day, rows, state in missing_days:
        try:
            roots = _base_roots(session, rows, state)
        except Exception as exc:  # noqa: BLE001 - report, never leak a traceback
            result["warnings"].append(
                f"{day.isoformat()}: base root lookup failed: {_mask(str(exc), 120)}"
            )
            roots = []
        if not roots:
            result["warnings"].append(
                f"{day.isoformat()}: no original base range root found in captured rows"
            )
        missing_roots.append(
            {
                "month": month,
                "day": day.isoformat(),
                "winning_parent_job_id": state.parent.job_id if state.parent else None,
                "origin_base_root_job_ids": [root.job_id for root in roots],
            }
        )
        for root in roots:
            if root.job_id not in root_candidates:
                root_candidates[root.job_id] = (root, [])
            root_candidates[root.job_id][1].append(day.isoformat())

    if len(root_candidates) > MAX_RECOVERY_ROOTS:
        result["recovery_budgets"]["saturated"] = True
        raise _Saturated(
            f"recovery roots {len(root_candidates)} exceed MAX_RECOVERY_ROOTS="
            f"{MAX_RECOVERY_ROOTS}"
        )

    result["recovery_budgets"]["missing_day_roots"] = missing_roots
    for root_id, (root, root_days) in root_candidates.items():
        result["recovery_budgets"]["roots"].append(
            {
                "root_job_id": root_id,
                **_root_detail(
                    session,
                    root,
                    [
                        row
                        for _month, _day, rows, _state in missing_days
                        for row in rows
                        if row.job_id == root_id
                        or row.parent_job_id == root_id
                        or (row.metadata_json or {}).get(RECOVERY_ROOT_KEY) == root_id
                    ],
                    sorted(set(root_days)),
                    children_cache,
                    sep14_v2_key,
                ),
            }
        )

    session.expunge_all()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-read-only",
        action="store_true",
        help="required: acknowledge this probe opens a READ ONLY transaction",
    )
    parser.add_argument(
        "--sep14-v2-key",
        default=SEP14_V2_REQUEST_KEY,
        help="controller-fixed ordinal-2 Idempotency-Key to check (never allocated)",
    )
    args = parser.parse_args()
    if not args.confirm_read_only:
        print(
            "refusing to run: pass --confirm-read-only "
            "(this script may only be reviewed/executed by an authorized controller)",
            file=sys.stderr,
        )
        return 2
    if not 16 <= len(args.sep14_v2_key.strip()) <= 128:
        print("refusing to run: --sep14-v2-key must be 16..128 characters", file=sys.stderr)
        return 2

    from sqlalchemy import create_engine, text

    from apps.api.dy_api.db import get_database_url, normalize_database_url

    # Arm the wall clock BEFORE the engine/connection is created so DNS, TCP and
    # the initial handshake are all covered.
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(WALL_CLOCK_SECONDS)
    engine = None
    payload: dict
    try:
        url = normalize_database_url(get_database_url(required=True))
        options = (
            "-c default_transaction_read_only=on "
            "-c statement_timeout=3000 "
            "-c lock_timeout=500 "
            "-c idle_in_transaction_session_timeout=15000"
        )
        engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={
                "options": options,
                "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            },
        )
        with engine.connect() as conn:
            try:
                conn.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                payload = probe(conn, sep14_v2_key=args.sep14_v2_key)
            finally:
                conn.rollback()  # explicit, even on failure
    except _Timeout as exc:
        print(json.dumps({"probe": "r0-head-day-gaps-recovery", "error": str(exc)}))
        return 3
    except _Saturated as exc:
        print(
            json.dumps(
                {
                    "probe": "r0-head-day-gaps-recovery",
                    "error": "probe_saturated",
                    "detail": _mask(str(exc), 200),
                }
            )
        )
        return 5
    except Exception as exc:  # report, never leak a traceback
        print(
            json.dumps(
                {
                    "probe": "r0-head-day-gaps-recovery",
                    "error": type(exc).__name__,
                    "detail": _mask(str(exc), 300),
                }
            )
        )
        return 4
    finally:
        signal.alarm(0)
        if engine is not None:
            engine.dispose()

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
