"""Fixed, aggregate-only settlement audit for the 2026-09/2026-10 windows.

This module answers one question only: how many source rows and how much money
exist at each settlement layer, for two fixed business months.  It never
returns identifiers, store names, order numbers or coupon numbers, and it never
writes: callers must run it through the rollback-only read-only transaction in
``pdca_readonly_access``.

Layer semantics mirror the worker so that a divergence is a data finding rather
than a query artefact:

* verify sources follow ``apps.worker.settlement._select_valid_verify_record``:
  the latest non-cancelled valid verify record per coupon, attributed by its
  Asia/Shanghai business month.  The month is derived *after* selection, so a
  coupon whose latest valid verify falls in 2026-10 never counts as 2026-09.
* current commission results are read through ``settlement_fee_result_current``
  (the current pointer), never from historical result versions.
* adjustments keep ordinary rows plus the current carryforward version, and
  require the original basis to still be reachable from the current pointer,
  including the reverification anchor.
* statement entries are read by ``statement_posting_month`` joined to the
  current statement header, so superseded statement versions cannot be counted
  twice.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DataQualityIssue,
    RawDouyinVerifyRecord,
    SettlementCarryforwardApplication,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementStatement,
    SettlementStatementEntry,
)

AUDIT_MONTHS: tuple[str, str] = ("2026-09", "2026-10")
PROMOTION_FEE = 1
MANAGEMENT_FEE = 2
ORIGINAL_ENTRY = 1
ADJUSTMENT_ENTRY = 2

# Source of truth is apps/worker/settlement.py; tests pin the two in sync.
VALID_VERIFY_STATUSES: frozenset[str] = frozenset(
    {"1", "valid", "verified", "success", "fulfilled", "used"}
)
# China has had no DST since 1991, so a fixed +08:00 shift is exact here and
# keeps the SQLite test path equivalent to PostgreSQL's AT TIME ZONE.
SHANGHAI_OFFSET = "+8 hours"
SHANGHAI_ZONE = "Asia/Shanghai"


class VerifySourceRow(BaseModel):
    """Per-coupon eligible verify sources, bucketed by business month."""

    model_config = ConfigDict(extra="forbid")
    business_month: str
    verify_status: str
    source_rows: int
    paid_amount_cent: int


class CurrentFeeResultRow(BaseModel):
    """Current commission results reachable from the current pointer."""

    model_config = ConfigDict(extra="forbid")
    business_month: str
    fee_direction: int
    result_status: int
    result_rows: int
    source_amount_cent: int
    refunded_amount_cent: int
    fee_base_cent: int
    fee_amount_cent: int


class CurrentAdjustmentRow(BaseModel):
    """Effective adjustments, including the current carryforward version."""

    model_config = ConfigDict(extra="forbid")
    posting_month: str
    fee_direction: int
    adjustment_type: int
    adjustment_rows: int
    adjustment_base_cent: int
    adjustment_fee_cent: int
    anchor_matched_rows: int


class CurrentStatementEntryRow(BaseModel):
    """Entries of the current statement header, bucketed by posting month."""

    model_config = ConfigDict(extra="forbid")
    statement_month: str
    posting_month: str
    fee_direction: int
    statement_status: int
    entry_rows: int
    original_entries: int
    adjustment_entries: int
    base_amount_cent: int
    fee_amount_cent: int


class SettlementAuditGuards(BaseModel):
    """Row counts that make the two structural assumptions observable."""

    model_config = ConfigDict(extra="forbid")
    posting_month_mismatch_rows: int
    superseded_statement_entry_rows: int


class SettlementMonthAudit(BaseModel):
    """The complete response: months, counts and money. Never identifiers."""

    model_config = ConfigDict(extra="forbid")
    months: list[str]
    verify_sources: list[VerifySourceRow]
    current_fee_results: list[CurrentFeeResultRow]
    current_adjustments: list[CurrentAdjustmentRow]
    current_statement_entries: list[CurrentStatementEntryRow]
    guards: SettlementAuditGuards


def parse_audit_months(value: str | None) -> tuple[str, ...]:
    """Accept only a non-empty subset of the fixed audit window."""

    if value is None:
        return AUDIT_MONTHS
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part for part in parts):
        raise ValueError("audit months must be a comma-separated list")
    if len(set(parts)) != len(parts):
        raise ValueError("audit months must not repeat")
    if any(part not in AUDIT_MONTHS for part in parts):
        raise ValueError("audit months are fixed to 2026-09 and 2026-10")
    return tuple(month for month in AUDIT_MONTHS if month in set(parts))


def _business_month_expr(session: Session, column: Any) -> Any:
    """Render the Asia/Shanghai business month for the active dialect."""

    if session.get_bind().dialect.name == "postgresql":
        return func.to_char(func.timezone(SHANGHAI_ZONE, column), "YYYY-MM")
    return func.strftime("%Y-%m", column, SHANGHAI_OFFSET)


def _verify_source_rows(
    session: Session, months: tuple[str, ...]
) -> list[VerifySourceRow]:
    """Latest valid, non-cancelled verify record per coupon, then bucket."""

    normalized_status = func.lower(
        func.trim(func.coalesce(RawDouyinVerifyRecord.verify_status, ""))
    )
    ranked = (
        select(
            RawDouyinVerifyRecord.coupon_id.label("coupon_id"),
            RawDouyinVerifyRecord.verify_time.label("verify_time"),
            RawDouyinVerifyRecord.paid_amount_cent.label("paid_amount_cent"),
            normalized_status.label("verify_status"),
            func.row_number()
            .over(
                partition_by=RawDouyinVerifyRecord.coupon_id,
                order_by=(
                    RawDouyinVerifyRecord.verify_time.desc(),
                    RawDouyinVerifyRecord.verify_id.desc(),
                ),
            )
            .label("recency"),
        )
        .where(
            normalized_status.in_(sorted(VALID_VERIFY_STATUSES)),
            RawDouyinVerifyRecord.cancel_time.is_(None),
            RawDouyinVerifyRecord.verify_time.is_not(None),
        )
        .subquery("ranked_verify")
    )
    month = _business_month_expr(session, ranked.c.verify_time)
    rows = session.execute(
        select(
            month.label("business_month"),
            ranked.c.verify_status.label("verify_status"),
            func.count().label("source_rows"),
            func.coalesce(
                func.sum(func.coalesce(ranked.c.paid_amount_cent, 0)), 0
            ).label("paid_amount_cent"),
        )
        .where(ranked.c.recency == 1, month.in_(months))
        .group_by(month, ranked.c.verify_status)
        .order_by(month, ranked.c.verify_status)
    ).all()
    return [
        VerifySourceRow(
            business_month=row.business_month,
            verify_status=row.verify_status,
            source_rows=int(row.source_rows),
            paid_amount_cent=int(row.paid_amount_cent or 0),
        )
        for row in rows
    ]


def _current_fee_result_rows(
    session: Session, months: tuple[str, ...]
) -> list[CurrentFeeResultRow]:
    """Current commission results only, never superseded result versions."""

    rows = session.execute(
        select(
            SettlementFeeResult.original_business_month.label("business_month"),
            SettlementFeeResult.fee_direction.label("fee_direction"),
            SettlementFeeResult.result_status.label("result_status"),
            func.count().label("result_rows"),
            func.coalesce(func.sum(SettlementFeeResult.source_amount_cent), 0).label(
                "source_amount_cent"
            ),
            func.coalesce(func.sum(SettlementFeeResult.refunded_amount_cent), 0).label(
                "refunded_amount_cent"
            ),
            func.coalesce(func.sum(SettlementFeeResult.fee_base_cent), 0).label(
                "fee_base_cent"
            ),
            func.coalesce(func.sum(SettlementFeeResult.fee_amount_cent), 0).label(
                "fee_amount_cent"
            ),
        )
        .join(
            SettlementFeeResultCurrent,
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeResult.fee_result_id,
        )
        .where(SettlementFeeResult.original_business_month.in_(months))
        .group_by(
            SettlementFeeResult.original_business_month,
            SettlementFeeResult.fee_direction,
            SettlementFeeResult.result_status,
        )
        .order_by(
            SettlementFeeResult.original_business_month,
            SettlementFeeResult.fee_direction,
            SettlementFeeResult.result_status,
        )
    ).all()
    return [
        CurrentFeeResultRow(
            business_month=row.business_month,
            fee_direction=int(row.fee_direction),
            result_status=int(row.result_status),
            result_rows=int(row.result_rows),
            source_amount_cent=int(row.source_amount_cent or 0),
            refunded_amount_cent=int(row.refunded_amount_cent or 0),
            fee_base_cent=int(row.fee_base_cent or 0),
            fee_amount_cent=int(row.fee_amount_cent or 0),
        )
        for row in rows
    ]


def _current_adjustment_rows(
    session: Session, months: tuple[str, ...]
) -> list[CurrentAdjustmentRow]:
    """Ordinary adjustments plus the current carryforward version."""

    versioned = (
        select(SettlementCarryforwardApplication.id)
        .where(
            SettlementCarryforwardApplication.target_adjustment_id
            == SettlementFeeAdjustment.adjustment_id
        )
        .exists()
    )
    current_version = (
        select(SettlementCarryforwardApplication.id)
        .where(
            SettlementCarryforwardApplication.target_adjustment_id
            == SettlementFeeAdjustment.adjustment_id,
            SettlementCarryforwardApplication.is_current.is_(True),
        )
        .exists()
    )
    # EXISTS rather than the worker's OR-join: an inner join on
    # (fee_result_id OR reverification_anchor_id) can match two current rows
    # and inflate every amount.  anchor_matched_rows keeps the anchor path
    # visible so any real divergence still shows up.
    current_pointer = (
        select(SettlementFeeResultCurrent.id)
        .where(
            or_(
                SettlementFeeResultCurrent.fee_result_id
                == SettlementFeeResult.fee_result_id,
                SettlementFeeResultCurrent.fee_result_id
                == SettlementFeeResult.reverification_anchor_id,
            )
        )
        .exists()
    )
    anchor_matched = (
        select(SettlementFeeResultCurrent.id)
        .where(
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeResult.reverification_anchor_id
        )
        .exists()
    )
    rows = session.execute(
        select(
            SettlementFeeAdjustment.adjustment_posting_month.label("posting_month"),
            SettlementFeeAdjustment.fee_direction.label("fee_direction"),
            SettlementFeeAdjustment.adjustment_type.label("adjustment_type"),
            func.count().label("adjustment_rows"),
            func.coalesce(
                func.sum(SettlementFeeAdjustment.adjustment_base_cent), 0
            ).label("adjustment_base_cent"),
            func.coalesce(
                func.sum(SettlementFeeAdjustment.adjustment_fee_cent), 0
            ).label("adjustment_fee_cent"),
            func.coalesce(
                func.sum(case((anchor_matched, 1), else_=0)), 0
            ).label("anchor_matched_rows"),
        )
        .select_from(SettlementFeeAdjustment)
        .join(
            SettlementFeeResult,
            SettlementFeeResult.fee_result_id
            == SettlementFeeAdjustment.original_fee_result_id,
        )
        .where(
            SettlementFeeAdjustment.adjustment_posting_month.in_(months),
            or_(~versioned, current_version),
            current_pointer,
        )
        .group_by(
            SettlementFeeAdjustment.adjustment_posting_month,
            SettlementFeeAdjustment.fee_direction,
            SettlementFeeAdjustment.adjustment_type,
        )
        .order_by(
            SettlementFeeAdjustment.adjustment_posting_month,
            SettlementFeeAdjustment.fee_direction,
            SettlementFeeAdjustment.adjustment_type,
        )
    ).all()
    return [
        CurrentAdjustmentRow(
            posting_month=row.posting_month,
            fee_direction=int(row.fee_direction),
            adjustment_type=int(row.adjustment_type),
            adjustment_rows=int(row.adjustment_rows),
            adjustment_base_cent=int(row.adjustment_base_cent or 0),
            adjustment_fee_cent=int(row.adjustment_fee_cent or 0),
            anchor_matched_rows=int(row.anchor_matched_rows or 0),
        )
        for row in rows
    ]


def _current_statement_entry_rows(
    session: Session, months: tuple[str, ...]
) -> list[CurrentStatementEntryRow]:
    """Entries of the current statement header, keyed by posting month."""

    conditions = (
        SettlementStatement.is_current.is_(True),
        SettlementStatementEntry.statement_posting_month.in_(months),
    )
    rows = session.execute(
        select(
            SettlementStatement.statement_month.label("statement_month"),
            SettlementStatementEntry.statement_posting_month.label("posting_month"),
            SettlementStatementEntry.fee_direction.label("fee_direction"),
            SettlementStatement.statement_status.label("statement_status"),
            func.count().label("entry_rows"),
            func.coalesce(
                func.sum(case((SettlementStatementEntry.source_type == ORIGINAL_ENTRY, 1), else_=0)),
                0,
            ).label("original_entries"),
            func.coalesce(
                func.sum(case((SettlementStatementEntry.source_type == ADJUSTMENT_ENTRY, 1), else_=0)),
                0,
            ).label("adjustment_entries"),
            func.coalesce(func.sum(SettlementStatementEntry.base_amount_cent), 0).label(
                "base_amount_cent"
            ),
            func.coalesce(func.sum(SettlementStatementEntry.fee_amount_cent), 0).label(
                "fee_amount_cent"
            ),
        )
        .select_from(SettlementStatementEntry)
        .join(
            SettlementStatement,
            SettlementStatement.statement_id
            == SettlementStatementEntry.statement_id,
        )
        .where(*conditions)
        .group_by(
            SettlementStatement.statement_month,
            SettlementStatementEntry.statement_posting_month,
            SettlementStatementEntry.fee_direction,
            SettlementStatement.statement_status,
        )
        .order_by(
            SettlementStatement.statement_month,
            SettlementStatementEntry.statement_posting_month,
            SettlementStatementEntry.fee_direction,
            SettlementStatement.statement_status,
        )
    ).all()
    return [
        CurrentStatementEntryRow(
            statement_month=row.statement_month,
            posting_month=row.posting_month,
            fee_direction=int(row.fee_direction),
            statement_status=int(row.statement_status),
            entry_rows=int(row.entry_rows),
            original_entries=int(row.original_entries or 0),
            adjustment_entries=int(row.adjustment_entries or 0),
            base_amount_cent=int(row.base_amount_cent or 0),
            fee_amount_cent=int(row.fee_amount_cent or 0),
        )
        for row in rows
    ]


def _audit_guards(session: Session, months: tuple[str, ...]) -> SettlementAuditGuards:
    """Count the two conditions that would make the layers disagree."""

    mismatch = session.scalar(
        select(func.count())
        .select_from(SettlementStatementEntry)
        .join(
            SettlementStatement,
            SettlementStatement.statement_id
            == SettlementStatementEntry.statement_id,
        )
        .where(
            SettlementStatement.is_current.is_(True),
            SettlementStatementEntry.statement_posting_month.in_(months),
            SettlementStatement.statement_month
            != SettlementStatementEntry.statement_posting_month,
        )
    )
    superseded = session.scalar(
        select(func.count())
        .select_from(SettlementStatementEntry)
        .join(
            SettlementStatement,
            SettlementStatement.statement_id
            == SettlementStatementEntry.statement_id,
        )
        .where(
            SettlementStatement.is_current.is_(False),
            SettlementStatementEntry.statement_posting_month.in_(months),
        )
    )
    return SettlementAuditGuards(
        posting_month_mismatch_rows=int(mismatch or 0),
        superseded_statement_entry_rows=int(superseded or 0),
    )


def read_settlement_month_audit(
    session: Session, *, months: tuple[str, ...] = AUDIT_MONTHS
) -> SettlementMonthAudit:
    """Read every layer with counts and amounts only.

    The caller owns the transaction; this function never commits, and it is
    expected to run inside a database-enforced read-only transaction.
    """
    selected = tuple(month for month in AUDIT_MONTHS if month in set(months))
    if not selected:
        raise ValueError("audit months are fixed to 2026-09 and 2026-10")
    return SettlementMonthAudit(
        months=list(selected),
        verify_sources=_verify_source_rows(session, selected),
        current_fee_results=_current_fee_result_rows(session, selected),
        current_adjustments=_current_adjustment_rows(session, selected),
        current_statement_entries=_current_statement_entry_rows(session, selected),
        guards=_audit_guards(session, selected),
    )


class MonthCloseReadinessAlert(BaseModel):
    """Operator alert: a business month could not be closed yet.

    Deliberately narrow: the month, the reason state, severity and the
    operator message only.  Source identifiers stay in the database.
    """

    model_config = ConfigDict(extra="forbid")
    month: str
    state: str
    severity: str
    message: str


class SettlementMonthReadiness(BaseModel):
    """Read-only view of outstanding month-close readiness alerts."""

    model_config = ConfigDict(extra="forbid")
    alerts: list[MonthCloseReadinessAlert]


# Only these reasons may be surfaced, in this fixed wording.  Nothing from the
# database row is echoed back: a quality-issue message or context can contain
# order numbers, phone numbers or store names.
READINESS_STATES: dict[str, str] = {
    "watermark_incomplete": "采集未完整",
    "no_current_results": "无有效佣金结果",
    "locked": "账单已锁账",
}
READINESS_SEVERITY = "warning"
# Strictly the previous complete Shanghai business month: the only month the
# planner ever dispatches, so no other month can be surfaced.
READINESS_WINDOW_MONTHS = 1
_MONTH_KEY_PATTERN = re.compile(r"\d{4}-\d{2}\Z")


def _shift_month(month: str, delta: int) -> str:
    index = int(month[:4]) * 12 + (int(month[5:7]) - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def readiness_month_window(
    now: Any = None, *, months: int = READINESS_WINDOW_MONTHS
) -> tuple[str, ...]:
    """The Shanghai business months an alert may legitimately name.

    With the default window this is exactly the previous complete business
    month — the only month the planner ever dispatches — so an arbitrary or
    historical month can never be surfaced.
    """

    from apps.worker.month_close import previous_business_month

    previous = previous_business_month(now)
    return tuple(_shift_month(previous, -offset) for offset in range(months))


def readiness_message(month: str, state: str) -> str:
    """Fixed operator template; never interpolates stored text."""

    return (
        f"{month} 月结未派发：{READINESS_STATES[state]}；"
        "来源就绪前不会生成账单。"
    )


def read_month_close_readiness(
    session: Session, *, now: Any = None, limit: int = 12
) -> SettlementMonthReadiness:
    """Return outstanding readiness alerts, newest month first.

    Only the four safe fields leave this function.  ``month`` must be a
    ``YYYY-MM`` key inside the recent business-month window, ``state`` must be
    one of the known reasons and both ``message`` and ``severity`` are produced
    here rather than read from the stored row.
    """

    # Local import keeps the API import path free of worker startup cost while
    # still sharing the single source of truth for the issue type.
    from apps.worker.month_close import READINESS_ISSUE_TYPE

    window = set(readiness_month_window(now))
    rows = session.scalars(
        select(DataQualityIssue)
        .where(DataQualityIssue.issue_type == READINESS_ISSUE_TYPE)
        .order_by(DataQualityIssue.issue_id)
        .limit(limit)
    ).all()
    alerts: list[MonthCloseReadinessAlert] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        context = row.raw_context_json
        if not isinstance(context, dict):
            continue
        month = context.get("business_month")
        state = context.get("state")
        if not isinstance(month, str) or not _MONTH_KEY_PATTERN.match(month):
            continue
        if month not in window:
            continue
        if not isinstance(state, str) or state not in READINESS_STATES:
            continue
        if (month, state) in seen:
            continue
        seen.add((month, state))
        alerts.append(
            MonthCloseReadinessAlert(
                month=month,
                state=state,
                severity=READINESS_SEVERITY,
                message=readiness_message(month, state),
            )
        )
    alerts.sort(key=lambda alert: alert.month, reverse=True)
    return SettlementMonthReadiness(alerts=alerts)


__all__ = [
    "MonthCloseReadinessAlert",
    "READINESS_SEVERITY",
    "READINESS_STATES",
    "READINESS_WINDOW_MONTHS",
    "SettlementMonthReadiness",
    "read_month_close_readiness",
    "readiness_message",
    "readiness_month_window",
    "ADJUSTMENT_ENTRY",
    "AUDIT_MONTHS",
    "MANAGEMENT_FEE",
    "ORIGINAL_ENTRY",
    "PROMOTION_FEE",
    "VALID_VERIFY_STATUSES",
    "CurrentAdjustmentRow",
    "CurrentFeeResultRow",
    "CurrentStatementEntryRow",
    "SettlementAuditGuards",
    "SettlementMonthAudit",
    "VerifySourceRow",
    "parse_audit_months",
    "read_settlement_month_audit",
]
