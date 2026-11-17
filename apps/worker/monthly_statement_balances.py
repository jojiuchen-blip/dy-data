"""Freeze a store's two independent forward-only settlement balances."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    InvoiceRecord, ManagementCarryforwardApplication, PromotionInvoice,
    PromotionInvoiceAllocation, SettlementStatement, SettlementStatementBalance,
)


class MonthlyBalanceNotReady(ValueError):
    """The prior store period has no settled answer for this balance."""


def previous_month(month: str) -> str:
    return (date.fromisoformat(f"{month}-01") - timedelta(days=1)).strftime("%Y-%m")


def carryforward_store_ids(session: Session, *, month: str) -> set[str]:
    """Include stores that must carry a credit even without new fee entries."""
    return set(session.scalars(
        select(SettlementStatement.store_id)
        .join(SettlementStatementBalance, SettlementStatementBalance.statement_id == SettlementStatement.statement_id)
        .where(
            SettlementStatement.is_current.is_(True),
            SettlementStatement.statement_month == previous_month(month),
            SettlementStatementBalance.closing_balance_cent < 0,
        ).distinct()
    ))


def _require_settled_legacy_credits(session: Session, *, store_id: str, month: str) -> None:
    """Open old-policy credits require reconciliation before starting a zero chain."""
    occupied_promotions = (
        select(PromotionInvoiceAllocation.statement_id)
        .join(PromotionInvoice, PromotionInvoice.invoice_id == PromotionInvoiceAllocation.invoice_id)
        .where(
            PromotionInvoiceAllocation.statement_id == SettlementStatement.statement_id,
            PromotionInvoiceAllocation.is_current.is_(True),
            PromotionInvoice.is_current.is_(True), PromotionInvoice.is_tombstone.is_(False),
            PromotionInvoice.invoice_status.in_((2, 3)),
        ).exists()
    )
    booked_management = (
        select(func.coalesce(func.sum(ManagementCarryforwardApplication.applied_amount_cent), 0))
        .join(InvoiceRecord, InvoiceRecord.invoice_id == ManagementCarryforwardApplication.invoice_id)
        .where(
            ManagementCarryforwardApplication.source_statement_id == SettlementStatement.statement_id,
            ManagementCarryforwardApplication.is_current.is_(True),
            InvoiceRecord.is_current.is_(True), InvoiceRecord.is_tombstone.is_(False),
            InvoiceRecord.invoice_status == 3, InvoiceRecord.invoice_amount_cent > 0,
        ).scalar_subquery()
    )
    pending = session.scalar(select(SettlementStatement.statement_id).where(
        SettlementStatement.store_id == store_id,
        SettlementStatement.statement_month < month,
        SettlementStatement.is_current.is_(True),
        or_(and_(SettlementStatement.promotion_net_fee_cent < 0, ~occupied_promotions),
            SettlementStatement.management_net_fee_cent < -booked_management),
    ).limit(1))
    if pending:
        raise MonthlyBalanceNotReady("legacy_pending_carryforward")


def preceding_statement_for_balance(
    session: Session,
    *,
    store_id: str,
    month: str,
    first_month: str,
    preceding_period_has_no_statement: bool = False,
) -> SettlementStatement | None:
    if month < first_month:
        raise ValueError("monthly balance cannot predate its cutover")
    if month == first_month:
        _require_settled_legacy_credits(session, store_id=store_id, month=month)
        return None
    preceding = session.scalar(
        select(SettlementStatement).where(
            SettlementStatement.store_id == store_id,
            SettlementStatement.statement_month == previous_month(month),
            SettlementStatement.is_current.is_(True),
        )
    )
    if preceding is None:
        if not preceding_period_has_no_statement:
            raise MonthlyBalanceNotReady("preceding_store_period_unresolved")
        _require_settled_legacy_credits(session, store_id=store_id, month=first_month)
    elif any(session.get(SettlementStatementBalance, (preceding.statement_id, direction)) is None
             for direction in (1, 2)):
        raise MonthlyBalanceNotReady("preceding_statement_balance_missing")
    return preceding


def freeze_statement_balances(
    session: Session,
    statement: SettlementStatement,
    *,
    first_month: str,
    preceding_period_has_no_statement: bool = False,
) -> None:
    """Persist balances before publishing a new immutable statement version.

    The caller holds the store/month publication lock and supplies evidence of
    an empty prior slot when applicable. An unresolved slot cannot be treated
    as an opening balance of zero.
    """
    preceding = preceding_statement_for_balance(
        session, store_id=statement.store_id, month=statement.statement_month, first_month=first_month,
        preceding_period_has_no_statement=preceding_period_has_no_statement,
    )
    for direction, period_net in (
        (1, statement.promotion_net_fee_cent),
        (2, statement.management_net_fee_cent),
    ):
        prior = session.get(SettlementStatementBalance, (preceding.statement_id, direction)) if preceding else None
        if preceding is not None and prior is None:
            raise MonthlyBalanceNotReady("preceding_statement_balance_missing")
        opening = prior.closing_balance_cent if prior else 0
        net = period_net + opening
        balance = SettlementStatementBalance(
            statement_id=statement.statement_id, fee_direction=direction,
            previous_statement_id=preceding.statement_id if preceding else None,
            opening_balance_cent=opening, period_net_fee_cent=period_net,
            net_due_cent=net, closing_balance_cent=min(net, 0),
        )
        session.add(balance)
