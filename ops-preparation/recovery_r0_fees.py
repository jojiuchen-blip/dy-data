#!/usr/bin/env python3
"""DYDATA-104 / R0 read-only probe B: fee result / statement / entry aggregates.

STATUS: authored for controller review. NOT uploaded to production and NOT
executed during R0. This is deliberately a *separate* script from probe A so a
heavy reconciliation can never slow down or time out the lightweight head/day-gap
read.

Where it must run
-----------------
Inside the *worker* container (never the API process), from the repository root:

    docker compose -f deploy/compose.yaml --env-file /opt/dy-dashboard/env/production.env \
        exec -T <worker-service> python - < .dsh-recovery-r0-probe-fees-20261021.py --confirm-read-only

Privacy
-------
Only monthly / directional *aggregates* are returned. No store, order, coupon,
account or per-row identifier is selected or printed. The scope-rule query
deliberately selects no `owner_account_id`; it reports only a distinct-account
count. Error text is truncated and redacted, including database URLs
(`postgresql+psycopg://...`) and credentials; no traceback is printed.

Read-only guarantees
--------------------
Same as probe A: libpq `default_transaction_read_only=on`, explicit
`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`,
statement_timeout=3s, lock_timeout=500ms, idle_in_transaction_session_timeout=15s,
connect_timeout=5s, 45s wall clock armed before any database access, explicit
rollback in `finally`, no writes, no temp tables, no job state changes.
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
from datetime import datetime, timezone

WALL_CLOCK_SECONDS = 45
CONNECT_TIMEOUT_SECONDS = 5
MONTHS = ("2026-08", "2026-09")

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


def _q(session, sql, **params):
    from sqlalchemy import text

    return [dict(row) for row in session.execute(text(sql), params).mappings().all()]


def probe(conn) -> dict:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    session = Session(bind=conn, autoflush=False, autocommit=False, future=True)
    out: dict = {
        "probe": "r0-fee-reconciliation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only_enforced": True,
        "settings": {},
        "months": list(MONTHS),
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
        out["settings"][name] = session.execute(text(f"SHOW {name}")).scalar()
    if (
        str(out["settings"].get("default_transaction_read_only")).lower() != "on"
        or str(out["settings"].get("transaction_read_only")).lower() != "on"
    ):
        raise RuntimeError("refusing to continue: session is not read-only")

    # ---- 1. current commission results, by month and direction -----------
    out["current_fee_results"] = _q(
        session,
        """
        SELECT f.original_business_month          AS month,
               CASE f.fee_direction
                    WHEN 1 THEN 'PROMOTION'
                    WHEN 2 THEN 'MANAGEMENT'
                    ELSE 'UNKNOWN'
               END                                AS fee_direction,
               COUNT(*)                           AS result_rows,
               COALESCE(SUM(f.fee_amount_cent), 0)   AS fee_amount_cent,
               COALESCE(SUM(f.fee_base_cent), 0)     AS fee_base_cent,
               COALESCE(SUM(f.source_amount_cent), 0) AS source_amount_cent,
               COALESCE(SUM(f.refunded_amount_cent), 0) AS refunded_amount_cent
          FROM settlement_fee_result f
          JOIN settlement_fee_result_current c
            ON c.fee_result_id = f.fee_result_id
         WHERE f.original_business_month = ANY(:months)
         GROUP BY f.original_business_month, f.fee_direction
         ORDER BY f.original_business_month, f.fee_direction
        """,
        months=list(MONTHS),
    )

    # Total result rows vs current rows: shows superseded revisions per month.
    out["fee_result_revisions"] = _q(
        session,
        """
        SELECT f.original_business_month AS month,
               CASE f.fee_direction
                    WHEN 1 THEN 'PROMOTION'
                    WHEN 2 THEN 'MANAGEMENT'
                    ELSE 'UNKNOWN'
               END AS fee_direction,
               COUNT(*)                  AS all_result_rows,
               COUNT(*) FILTER (WHERE c.fee_result_id IS NOT NULL) AS current_rows
          FROM settlement_fee_result f
          LEFT JOIN settlement_fee_result_current c
            ON c.fee_result_id = f.fee_result_id
         WHERE f.original_business_month = ANY(:months)
          GROUP BY f.original_business_month, f.fee_direction
          ORDER BY f.original_business_month, f.fee_direction
        """,
        months=list(MONTHS),
    )

    # ---- 2. statements, current versions only ----------------------------
    out["current_statements"] = _q(
        session,
        """
        SELECT statement_month   AS month,
               statement_status  AS statement_status,
               COUNT(*)          AS statements,
               COALESCE(SUM(promotion_net_fee_cent), 0)  AS promotion_net_fee_cent,
               COALESCE(SUM(management_net_fee_cent), 0) AS management_net_fee_cent
          FROM settlement_statement
         WHERE statement_month = ANY(:months)
           AND is_current IS TRUE
         GROUP BY statement_month, statement_status
         ORDER BY statement_month, statement_status
        """,
        months=list(MONTHS),
    )
    out["statement_version_counts"] = _q(
        session,
        """
        SELECT statement_month AS month,
               COUNT(*) AS all_versions,
               COUNT(*) FILTER (WHERE is_current IS TRUE) AS current_versions,
               COUNT(*) FILTER (WHERE locked_at IS NOT NULL) AS locked_versions
          FROM settlement_statement
         WHERE statement_month = ANY(:months)
         GROUP BY statement_month
         ORDER BY statement_month
        """,
        months=list(MONTHS),
    )
    out["statement_confirmation_counts"] = _q(
        session,
        """
        SELECT s.statement_month AS month,
               CASE sc.fee_direction
                    WHEN 1 THEN 'PROMOTION'
                    WHEN 2 THEN 'MANAGEMENT'
                    ELSE 'UNKNOWN'
               END AS fee_direction,
               COUNT(*) AS confirmations
          FROM settlement_statement_confirmation sc
          JOIN settlement_statement s ON s.statement_id = sc.statement_id
         WHERE s.statement_month = ANY(:months) AND s.is_current IS TRUE
         GROUP BY s.statement_month, sc.fee_direction
         ORDER BY s.statement_month, sc.fee_direction
        """,
        months=list(MONTHS),
    )

    # ---- 3. billing entries: current parent statements only --------------
    # `settlement_statement_entry` is versioned by its parent statement. Only a
    # current parent contributes to "current totals"; superseded versions are
    # reported separately as history and never summed into the current figure.
    out["current_entries_by_posting_month"] = _q(
        session,
        """
        SELECT e.statement_posting_month AS posting_month,
               CASE e.fee_direction
                    WHEN 1 THEN 'PROMOTION'
                    WHEN 2 THEN 'MANAGEMENT'
                    ELSE 'UNKNOWN'
               END AS fee_direction,
               COUNT(*) AS entries,
               COALESCE(SUM(e.fee_amount_cent), 0) AS fee_amount_cent,
               COALESCE(SUM(e.base_amount_cent), 0) AS base_amount_cent
          FROM settlement_statement_entry e
          JOIN settlement_statement s ON s.statement_id = e.statement_id
         WHERE e.statement_posting_month = ANY(:months)
           AND s.is_current IS TRUE
         GROUP BY e.statement_posting_month, e.fee_direction
         ORDER BY e.statement_posting_month, e.fee_direction
        """,
        months=list(MONTHS),
    )
    out["history_entries_by_posting_month"] = _q(
        session,
        """
        SELECT e.statement_posting_month AS posting_month,
               CASE e.fee_direction
                    WHEN 1 THEN 'PROMOTION'
                    WHEN 2 THEN 'MANAGEMENT'
                    ELSE 'UNKNOWN'
               END AS fee_direction,
               COUNT(*) AS entries,
               COALESCE(SUM(e.fee_amount_cent), 0) AS fee_amount_cent,
               COALESCE(SUM(e.base_amount_cent), 0) AS base_amount_cent
          FROM settlement_statement_entry e
          JOIN settlement_statement s ON s.statement_id = e.statement_id
         WHERE e.statement_posting_month = ANY(:months)
           AND s.is_current IS FALSE
         GROUP BY e.statement_posting_month, e.fee_direction
         ORDER BY e.statement_posting_month, e.fee_direction
        """,
        months=list(MONTHS),
    )
    out["current_entries_by_original_business_month"] = _q(
        session,
        """
        SELECT e.original_business_month AS original_month,
               CASE e.fee_direction
                    WHEN 1 THEN 'PROMOTION'
                    WHEN 2 THEN 'MANAGEMENT'
                    ELSE 'UNKNOWN'
               END AS fee_direction,
               COUNT(*) AS entries,
               COALESCE(SUM(e.fee_amount_cent), 0) AS fee_amount_cent
          FROM settlement_statement_entry e
          JOIN settlement_statement s ON s.statement_id = e.statement_id
         WHERE e.original_business_month = ANY(:months)
           AND s.is_current IS TRUE
         GROUP BY e.original_business_month, e.fee_direction
         ORDER BY e.original_business_month, e.fee_direction
        """,
        months=list(MONTHS),
    )

    # Catch the "posted into a month from elsewhere" shape without row detail,
    # also restricted to current parent statements.
    out["current_entries_cross_month"] = _q(
        session,
        """
        SELECT e.statement_posting_month AS posting_month,
               e.original_business_month AS original_month,
               COUNT(*) AS entries
          FROM settlement_statement_entry e
          JOIN settlement_statement s ON s.statement_id = e.statement_id
         WHERE e.statement_posting_month = ANY(:months)
           AND s.is_current IS TRUE
           AND e.original_business_month <> e.statement_posting_month
         GROUP BY e.statement_posting_month, e.original_business_month
         ORDER BY e.statement_posting_month, e.original_business_month
        """,
        months=list(MONTHS),
    )

    # ---- 4. scope rules, aggregate only (no account identifiers) ---------
    out["scope_rules"] = _q(
        session,
        """
        SELECT effective_month          AS effective_month,
               sale_channel_normalized  AS sale_channel,
               is_active                AS is_active,
               COUNT(*)                 AS rules,
               COUNT(DISTINCT owner_account_id) AS distinct_accounts
          FROM settlement_scope_rule
         WHERE effective_month = ANY(:months)
         GROUP BY effective_month, sale_channel_normalized, is_active
         ORDER BY effective_month, sale_channel_normalized, is_active
        """,
        months=list(MONTHS),
    )
    out["scope_rule_versions"] = _q(
        session,
        """
        SELECT effective_month AS effective_month, COUNT(*) AS all_versions,
               COUNT(*) FILTER (WHERE is_active IS TRUE) AS active_versions
          FROM settlement_scope_rule
         WHERE effective_month = ANY(:months)
         GROUP BY effective_month
         ORDER BY effective_month
        """,
        months=list(MONTHS),
    )

    for key in (
        "current_fee_results",
        "current_statements",
        "current_entries_by_posting_month",
        "scope_rules",
    ):
        if not out[key]:
            out["warnings"].append(f"{key}: no rows for {MONTHS}")

    session.expunge_all()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-read-only",
        action="store_true",
        help="required: acknowledge this probe opens a READ ONLY transaction",
    )
    args = parser.parse_args()
    if not args.confirm_read_only:
        print(
            "refusing to run: pass --confirm-read-only "
            "(this script may only be reviewed/executed by an authorized controller)",
            file=sys.stderr,
        )
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
                payload = probe(conn)
            finally:
                conn.rollback()  # explicit, even on failure
    except _Timeout as exc:
        print(json.dumps({"probe": "r0-fee-reconciliation", "error": str(exc)}))
        return 3
    except Exception as exc:  # report, never leak a traceback
        print(
            json.dumps(
                {
                    "probe": "r0-fee-reconciliation",
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
