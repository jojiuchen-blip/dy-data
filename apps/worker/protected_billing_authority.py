"""Read protected bills from immutable entries without repairing fee pointers."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

from sqlalchemy import and_, case, func, literal, or_, select, tuple_
from sqlalchemy.orm import Session, aliased

from apps.api.dy_api.models import (
    InvoiceRecord, PromotionInvoiceAllocation, SettlementDispute, SettlementCarryforwardSource,
    SettlementFeeAdjustment, SettlementFeeResult,
    SettlementStatement, SettlementStatementConfirmation, SettlementStatementEntry,
    SettlementStatementLine,
)

SNAPSHOT_FIELDS = (
    "order_status", "coupon_status", "product_name", "sku_id", "sku_name",
    "sale_channel", "sale_store_id", "sale_store", "verify_store_id", "verify_store",
    "sale_time", "verify_time", "received_amount_cent", "fee_rate", "refund_at", "adjustment_type",
)


class ProtectedBillingAuthorityError(ValueError):
    """A frozen bill or an event basis cannot safely define publication authority."""


def protected_statement_condition(statement=SettlementStatement) -> Any:
    """Use the complete existing generator predicate, including either direction."""
    return or_(
        statement.statement_status.in_((3, 4)), statement.confirmed_at.is_not(None),
        statement.locked_at.is_not(None),
        select(SettlementStatementConfirmation.id).where(
            SettlementStatementConfirmation.statement_id == statement.statement_id,
        ).exists(),
        select(SettlementDispute.id).where(
            SettlementDispute.store_id == statement.store_id,
            SettlementDispute.statement_month == statement.statement_month,
            or_(SettlementDispute.status.in_((1, 2, 3, 4)), SettlementDispute.result_statement_id.is_not(None)),
        ).exists(),
        select(PromotionInvoiceAllocation.id).where(
            PromotionInvoiceAllocation.store_id == statement.store_id,
            PromotionInvoiceAllocation.statement_month == statement.statement_month,
        ).exists(),
        select(InvoiceRecord.id).where(
            InvoiceRecord.store_id == statement.store_id,
            InvoiceRecord.statement_month == statement.statement_month,
        ).exists(),
    )


def is_protected_statement(session: Session, statement: SettlementStatement) -> bool:
    """Evaluate the same predicate for a known bill, without changing its state."""
    return session.scalar(select(SettlementStatement.id).where(
        SettlementStatement.statement_id == statement.statement_id,
        protected_statement_condition(),
    ).limit(1)) is not None


def lock_current_bills(session: Session, slots: set[tuple[str, str]]) -> None:
    """After slot locks, serialize with confirmation and invoice writers on bills."""
    if slots:
        list(session.scalars(select(SettlementStatement).where(
            SettlementStatement.is_current.is_(True),
            tuple_(SettlementStatement.store_id, SettlementStatement.statement_month).in_(sorted(slots)),
        ).order_by(SettlementStatement.store_id, SettlementStatement.statement_month, SettlementStatement.statement_id)
            .with_for_update().execution_options(populate_existing=True)))


def protected_entries_relation(*, statements=None):
    """Include every entry of every protected current bill, not a repair cohort."""
    entry = SettlementStatementEntry
    statement = SettlementStatement if statements is None else statements.c
    query = select(
        entry.statement_entry_id, entry.statement_id, entry.statement_line_id,
        entry.source_type, entry.source_record_id, entry.original_fee_result_id,
        entry.coupon_id, entry.order_id, entry.fee_direction, entry.original_business_month,
        entry.statement_posting_month, entry.product_scope, entry.product_type,
        entry.base_amount_cent, entry.fee_amount_cent, entry.rule_version,
        *(getattr(entry, f"{field}_snapshot") for field in SNAPSHOT_FIELDS),
        statement.store_id.label("authority_store_id"),
        statement.statement_month.label("authority_month"),
    ).join(SettlementStatement if statements is None else statements,
           statement.statement_id == entry.statement_id)
    if statements is None:
        query = query.where(SettlementStatement.is_current.is_(True), protected_statement_condition())
    return query.subquery("protected_billing_entries")


def protected_slot_condition(store_id, month, *, statements=None):
    """Whether a destination slot must use its entire current bill snapshot."""
    if statements is not None:
        return select(statements.c.statement_id).where(
            statements.c.store_id == store_id, statements.c.statement_month == month,
        ).exists()
    statement = aliased(SettlementStatement)
    return select(statement.id).where(
        statement.is_current.is_(True), statement.store_id == store_id,
        statement.statement_month == month, protected_statement_condition(statement),
    ).exists()


def frozen_primary_chain_condition(result=SettlementFeeResult, *, entries=None):
    """Suppress primary results on the same chain even after a store/month move."""
    entries = protected_entries_relation() if entries is None else entries
    return select(entries.c.statement_entry_id).where(
        entries.c.source_type == 1, entries.c.coupon_id == result.coupon_id,
        entries.c.fee_direction == result.fee_direction,
    ).exists()


def frozen_authority_rows(months: tuple[str, ...], *, entries=None):
    """Match the sparse relation schema using frozen core amounts and dimensions."""
    entry = protected_entries_relation() if entries is None else entries
    original = aliased(SettlementFeeResult)
    return select(
        case((entry.c.source_type == 1, literal("result")), else_=literal("adjustment")).label("source_kind"),
        entry.c.source_record_id.label("source_id"), entry.c.authority_month.label("month"),
        entry.c.authority_store_id.label("store_id"),
        func.coalesce(func.nullif(entry.c.product_scope, ""), "all").label("source_product_scope"),
        func.coalesce(func.nullif(entry.c.product_type, ""), "all").label("source_product_type"),
        entry.c.fee_direction, entry.c.order_id,
        case((entry.c.source_type == 1, original.source_amount_cent), else_=literal(0)).label("source_amount_cent"),
        entry.c.base_amount_cent, entry.c.fee_amount_cent,
        entry.c.statement_entry_id.label("frozen_entry_id"), literal(None).label("basis_entry_id"),
        entry.c.fee_rate_snapshot.label("source_fee_rate"), entry.c.rule_version.label("source_rule_version"),
    ).outerjoin(original, original.fee_result_id == entry.c.original_fee_result_id).where(entry.c.authority_month.in_(months))


def statement_source_from_entry(session: Session, entry: SettlementStatementEntry, store_id: str):
    """Preserve unknown snapshots; never reconstruct display fields from live data."""
    from apps.worker.settlement import StatementSource

    source_amount = 0
    if entry.source_type == 1:
        original = session.scalar(select(SettlementFeeResult).where(
            SettlementFeeResult.fee_result_id == entry.original_fee_result_id,
        ))
        if original is None or not _same_frozen_primary(entry, original):
            raise ProtectedBillingAuthorityError("frozen primary receipt has no exact immutable basis")
        source_amount = original.source_amount_cent
    else:
        event = session.scalar(select(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.adjustment_id == entry.source_record_id,
        ))
        basis = session.scalar(select(SettlementFeeResult).where(
            SettlementFeeResult.fee_result_id == entry.original_fee_result_id,
        ))
        if (event is None or basis is None
                or (event.original_fee_result_id, event.coupon_id, event.order_id, event.fee_direction,
                    event.original_business_month, event.adjustment_posting_month, event.adjustment_base_cent,
                    event.adjustment_fee_cent, event.rule_version)
                != (entry.original_fee_result_id, entry.coupon_id, entry.order_id, entry.fee_direction,
                    entry.original_business_month, entry.statement_posting_month, entry.base_amount_cent,
                    entry.fee_amount_cent, entry.rule_version)
                or (basis.coupon_id, basis.order_id, basis.fee_direction, basis.original_business_month)
                != (entry.coupon_id, entry.order_id, entry.fee_direction, entry.original_business_month)):
            raise ProtectedBillingAuthorityError("frozen adjustment has no exact immutable event and anchor")
    return StatementSource(
        source_type=entry.source_type, source_record_id=entry.source_record_id,
        original_fee_result_id=entry.original_fee_result_id, coupon_id=entry.coupon_id,
        order_id=entry.order_id, fee_direction=entry.fee_direction,
        original_business_month=entry.original_business_month,
        posting_month=entry.statement_posting_month, store_id=store_id,
        product_scope=entry.product_scope, product_type=entry.product_type,
        base_amount_cent=entry.base_amount_cent, fee_amount_cent=entry.fee_amount_cent,
        source_amount_cent=source_amount, rule_version=entry.rule_version,
        **{field: getattr(entry, f"{field}_snapshot") for field in SNAPSHOT_FIELDS},
    )


def adjustment_source_from_entry(session: Session, adjustment: SettlementFeeAdjustment, entry: SettlementStatementEntry, store_id: str):
    """A later event on an exact frozen basis inherits that basis's display snapshot."""
    source = statement_source_from_entry(session, entry, store_id)
    return replace(
        source, source_type=2, source_record_id=adjustment.adjustment_id,
        original_fee_result_id=adjustment.original_fee_result_id,
        original_business_month=adjustment.original_business_month,
        posting_month=adjustment.adjustment_posting_month,
        base_amount_cent=adjustment.adjustment_base_cent,
        fee_amount_cent=adjustment.adjustment_fee_cent, source_amount_cent=0,
        rule_version=adjustment.rule_version,
        refund_at=None if adjustment.adjustment_type == 4 else adjustment.occurred_at,
        adjustment_type=adjustment.adjustment_type,
    )


def _same_frozen_primary(entry: SettlementStatementEntry, original: SettlementFeeResult) -> bool:
    return (
        entry.source_type == 1 and entry.source_record_id == original.fee_result_id
        and entry.original_fee_result_id == original.fee_result_id
        and entry.coupon_id == original.coupon_id and entry.order_id == original.order_id
        and entry.fee_direction == original.fee_direction
        and entry.original_business_month == original.original_business_month
        and entry.base_amount_cent == original.fee_base_cent
        and entry.fee_amount_cent == original.fee_amount_cent
        and entry.rule_version == original.rule_version
    )


def validate_protected_authority(session: Session, months: tuple[str, ...]) -> None:
    """Fail closed on incomplete bills and ambiguous event bases before aggregation."""
    from apps.worker.settlement import (
        _active_adjustment_condition, _as_utc, _effective_adjustment_totals, _has_verify_cancellation,
    )

    bills = list(session.scalars(select(SettlementStatement).where(
        SettlementStatement.is_current.is_(True), SettlementStatement.statement_month.in_(months),
        protected_statement_condition(),
    )))
    seen_sources = set()
    for bill in bills:
        entries = list(session.scalars(select(SettlementStatementEntry).where(SettlementStatementEntry.statement_id == bill.statement_id)))
        totals = defaultdict(lambda: [0, 0])
        line_totals = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
        for entry in entries:
            identity = (entry.source_type, entry.source_record_id)
            if entry.source_type not in (1, 2) or entry.fee_direction not in (1, 2) or identity in seen_sources:
                raise ProtectedBillingAuthorityError("protected source identity is invalid or duplicated")
            seen_sources.add(identity)
            if entry.statement_posting_month != bill.statement_month:
                raise ProtectedBillingAuthorityError("protected entry posting month differs from its bill")
            totals[entry.fee_direction][entry.source_type - 1] += entry.fee_amount_cent
            amounts = line_totals[(entry.fee_direction, entry.product_scope, entry.product_type)]
            index = entry.source_type - 1
            amounts[index] += 1
            amounts[2 + index] += entry.base_amount_cent
            amounts[4 + index] += entry.fee_amount_cent
            # source_amount is an economic field, never the received display snapshot.
            statement_source_from_entry(session, entry, bill.store_id)
        for direction, prefix in ((1, "promotion"), (2, "management")):
            expected = [getattr(bill, f"{prefix}_original_fee_cent"), getattr(bill, f"{prefix}_adjustment_fee_cent")]
            if totals[direction] != expected or sum(expected) != getattr(bill, f"{prefix}_net_fee_cent"):
                raise ProtectedBillingAuthorityError("protected bill entries do not match immutable header")
        lines = session.scalars(select(SettlementStatementLine).where(SettlementStatementLine.statement_id == bill.statement_id))
        actual_lines = {}
        line_keys = {}
        for line in lines:
            key = (line.fee_direction, line.product_scope, line.product_type)
            if key in actual_lines:
                raise ProtectedBillingAuthorityError("protected immutable line group is duplicated")
            actual_lines[key] = [line.original_entry_count, line.adjustment_entry_count,
                                 line.original_base_cent, line.adjustment_base_cent,
                                 line.original_fee_cent, line.adjustment_fee_cent]
            line_keys[line.statement_line_id] = key
            if line.net_base_cent != line.original_base_cent + line.adjustment_base_cent or line.net_fee_cent != line.original_fee_cent + line.adjustment_fee_cent:
                raise ProtectedBillingAuthorityError("protected line net amounts conflict")
        if dict(line_totals) != actual_lines:
            raise ProtectedBillingAuthorityError("protected bill entries do not match immutable lines")
        if any(line_keys.get(entry.statement_line_id) != (entry.fee_direction, entry.product_scope, entry.product_type) for entry in entries):
            raise ProtectedBillingAuthorityError("protected entry is not linked to its immutable line")
    frozen = protected_entries_relation()
    original = SettlementFeeResult
    adjustment = SettlementFeeAdjustment
    store_id = case((adjustment.fee_direction == 1, original.sale_store_id), else_=original.verify_store_id)
    pairs = session.execute(select(adjustment, original, SettlementStatementEntry).join(
        original, original.fee_result_id == adjustment.original_fee_result_id,
    ).join(frozen, and_(frozen.c.source_type == 1, frozen.c.coupon_id == original.coupon_id,
                        frozen.c.fee_direction == original.fee_direction)).join(
        SettlementStatementEntry, SettlementStatementEntry.statement_entry_id == frozen.c.statement_entry_id,
    ).where(adjustment.adjustment_posting_month.in_(months), _active_adjustment_condition(),
            ~protected_slot_condition(store_id, adjustment.adjustment_posting_month)))
    for event, basis, entry in pairs:
        if (event.coupon_id, event.order_id, event.fee_direction) != (entry.coupon_id, entry.order_id, entry.fee_direction) or event.original_business_month != basis.original_business_month:
            raise ProtectedBillingAuthorityError("adjustment identity conflicts with frozen basis")
        if basis.fee_result_id == entry.original_fee_result_id:
            if not _same_frozen_primary(entry, basis):
                raise ProtectedBillingAuthorityError("adjustment exact immutable basis conflicts with frozen entry")
            continue
        anchor = session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == entry.original_fee_result_id))
        restoration = session.scalar(select(SettlementFeeAdjustment.id).where(
            SettlementFeeAdjustment.original_fee_result_id == basis.fee_result_id,
            SettlementFeeAdjustment.adjustment_type == 4,
            SettlementFeeAdjustment.adjustment_base_cent == basis.fee_base_cent,
            SettlementFeeAdjustment.adjustment_fee_cent == basis.fee_amount_cent,
        ).limit(1)) or session.scalar(select(SettlementCarryforwardSource.id).where(
            SettlementCarryforwardSource.original_fee_result_id == basis.fee_result_id,
            SettlementCarryforwardSource.source_event_key == f"reverification:{basis.fee_result_id}",
            SettlementCarryforwardSource.adjustment_type == 4,
            SettlementCarryforwardSource.verify_id == basis.qualifying_verify_id,
            SettlementCarryforwardSource.adjustment_base_cent == basis.fee_base_cent,
            SettlementCarryforwardSource.adjustment_fee_cent == basis.fee_amount_cent,
        ).limit(1))
        if not (basis.reverification_anchor_id == entry.original_fee_result_id and basis.result_status == 2 and basis.qualifying_verify_id
                and basis.qualifying_verify_time is not None and anchor is not None
                and anchor.qualifying_verify_id and anchor.qualifying_verify_time is not None
                and (basis.qualifying_verify_id != anchor.qualifying_verify_id
                     or _as_utc(basis.qualifying_verify_time) != _as_utc(anchor.qualifying_verify_time))
                and restoration and _has_verify_cancellation(session, anchor)
                and anchor.fee_amount_cent + _effective_adjustment_totals(session, original_fee_result_id=anchor.fee_result_id)[1] == 0):
            raise ProtectedBillingAuthorityError("adjustment uses an unapproved replacement of a frozen fee basis")
