"""Current finance states restricted to an immutable published bill universe."""

from types import SimpleNamespace

from sqlalchemy import and_, func, literal, or_, select

from ..models import (
    DimStore, InvoiceRecord, PromotionInvoice, PromotionInvoiceAllocation,
    SettlementStatement, SettlementStatementConfirmation, StoreFinanceProfile,
)
from . import finance as publication


def invoice_query(publication_id, *, month, fee_direction, metric_scope="MONTH",
                  store_id=None, q=None, invoice_status=None, include_history=False,
                  scope_store_ids=None):
    """Filter and paginate live document heads before materializing display rows."""
    frozen = publication.invoices
    conditions = [frozen.c.publication_id == publication_id,
        frozen.c.fee_direction == fee_direction, frozen.c.is_history.is_(False),
        publication._period(frozen.c.month, month, metric_scope),
        *publication._scope(frozen, scope_store_ids)]
    if store_id is not None:
        conditions.append(frozen.c.store_id == store_id)
    base = select(frozen).where(*conditions).subquery("published_finance_rows")
    direction = 1 if fee_direction == "PROMOTION" else 2
    confirmation = SettlementStatementConfirmation
    joined = base.outerjoin(SettlementStatement,
        SettlementStatement.statement_id == base.c.statement_id).outerjoin(confirmation, and_(
            confirmation.statement_id == base.c.statement_id,
            confirmation.fee_direction == direction, confirmation.confirmation_status == 1))
    invoice = PromotionInvoice if direction == 1 else InvoiceRecord
    if direction == 1:
        valid = select(PromotionInvoice.invoice_id).where(
            PromotionInvoice.is_current.is_(True), PromotionInvoice.is_tombstone.is_(False)).correlate(None)
        allocation = PromotionInvoiceAllocation
        joined = joined.outerjoin(allocation, and_(
            allocation.statement_id == base.c.statement_id, allocation.is_current.is_(True),
            allocation.invoice_id.in_(valid))).outerjoin(invoice, invoice.invoice_id == allocation.invoice_id)
        allocation_id = allocation.allocation_id
    else:
        invoice_conditions = [invoice.statement_id == base.c.statement_id,
            invoice.fee_direction == direction, invoice.is_tombstone.is_(False)]
        if not include_history:
            invoice_conditions.append(invoice.is_current.is_(True))
        joined = joined.outerjoin(invoice, and_(*invoice_conditions))
        allocation_id = literal(None)
    query = select(*base.c,
        invoice.invoice_id.label("live_invoice_id"),
        invoice.invoice_status.label("live_status"),
        invoice.invoice_number.label("live_invoice_number"),
        allocation_id.label("live_allocation_id"),
        confirmation.confirmation_id.label("live_confirmation_id"),
        confirmation.confirmed_amount_cent.label("live_confirmed_cent"),
    ).select_from(joined)
    if invoice_status is not None:
        query = query.where(base.c.is_projection.is_(False))
        if direction == 1:
            query = query.where(or_(invoice.invoice_id.is_(None), invoice.invoice_status.in_((1, 4)))
                if invoice_status == 1 else invoice.invoice_status == invoice_status)
        else:
            query = query.where(and_(invoice.invoice_id.is_(None), confirmation.confirmation_id.is_not(None))
                if invoice_status == 1 else invoice.invoice_id.is_not(None))
    if (q or "").strip():
        term = q.strip().lower()
        current_saps = select(StoreFinanceProfile.store_id).where(
            StoreFinanceProfile.is_current.is_(True), StoreFinanceProfile.is_tombstone.is_(False),
            func.lower(func.coalesce(StoreFinanceProfile.sap_code, "")).contains(term))
        current_names = select(DimStore.store_id).where(func.lower(DimStore.store_name).contains(term))
        query = query.where(or_(
            func.lower(base.c.store_id).contains(term),
            func.lower(base.c.item["store_name"].as_string()).contains(term),
            func.lower(func.coalesce(SettlementStatement.sap_code_snapshot, "")).contains(term),
            func.lower(func.coalesce(invoice.invoice_number, "")).contains(term),
            base.c.store_id.in_(current_saps), base.c.store_id.in_(current_names),
        ))
    return query.order_by(base.c.position, invoice.version_no, invoice.invoice_id)


def invoice_items(session, rows, fee_direction):
    """Overlay exact selected document versions without changing frozen fees."""
    items = []
    for offset in range(0, len(rows), 500):
        items.extend(_invoice_items_batch(session, rows[offset:offset + 500], fee_direction))
    return items


def _invoice_items_batch(session, rows, fee_direction):
    """Bound document/profile bind counts and ORM objects for large exports."""
    if not rows:
        return []
    invoice_ids = {row["live_invoice_id"] for row in rows if row["live_invoice_id"]}
    invoice_model = PromotionInvoice if fee_direction == "PROMOTION" else InvoiceRecord
    current_invoices = {row.invoice_id: row for row in session.scalars(
        select(invoice_model).where(invoice_model.invoice_id.in_(invoice_ids)))}
    allocation_ids = {row["live_allocation_id"] for row in rows if row["live_allocation_id"]}
    allocations = {row.allocation_id: row for row in session.scalars(select(PromotionInvoiceAllocation).where(
        PromotionInvoiceAllocation.allocation_id.in_(allocation_ids)))} if allocation_ids else {}
    context = publication._finance_display_context(session,
        store_ids={row["store_id"] for row in rows}, invoice_ids=invoice_ids)
    from ..routes import dashboard as source

    items = []
    direction = 1 if fee_direction == "PROMOTION" else 2
    for row in rows:
        frozen = dict(row["item"])
        if row["is_projection"]:
            frozen["effective_sap_code"] = context["effective_saps"].get(row["store_id"])
            items.append(frozen)
            continue
        statement = SimpleNamespace(statement_id=row["statement_id"], store_id=row["store_id"],
            statement_month=row["month"], store_name_snapshot=frozen.get("store_name"),
            promotion_net_fee_cent=row["amount_cent"], management_net_fee_cent=row["amount_cent"])
        confirmations = {}
        if row["live_confirmation_id"] is not None:
            confirmations[(row["statement_id"], direction)] = SimpleNamespace(
                confirmed_amount_cent=row["live_confirmed_cent"])
        item = publication._formal_invoice_item(source, fee_direction,
            current_invoices.get(row["live_invoice_id"]),
            allocations.get(row["live_allocation_id"]), statement, confirmations, context)
        items.append(publication._json_value(item))
    return items


def summary_metrics(session, publication_id, *, month, fee_direction, metric_scope,
                    store_id=None, q=None, invoice_status=None, scope_store_ids=None):
    """Sum published amounts and current legal states within that exact universe."""
    from ..routes import dashboard as source

    frozen = publication.statements
    direction = 1 if fee_direction == "PROMOTION" else 2
    universe_conditions = [frozen.c.publication_id == publication_id,
        frozen.c.fee_direction == fee_direction, *publication._scope(frozen, scope_store_ids)]
    if store_id is not None:
        universe_conditions.append(frozen.c.store_id == store_id)
    universe = select(frozen).where(*universe_conditions).subquery("published_finance_statements")
    filters = dict(month=month, fee_direction=fee_direction, metric_scope=metric_scope,
        store_id=store_id, q=q, invoice_status=invoice_status, scope_store_ids=scope_store_ids)
    displayed = invoice_query(publication_id, **filters).order_by(None).subquery("live_finance_rows")
    row_filters = bool((q or "").strip()) or invoice_status is not None or scope_store_ids is not None
    selected = [publication._period(universe.c.month, month, metric_scope)]
    matching = select(displayed.c.statement_id).where(displayed.c.statement_id.is_not(None))
    if row_filters:
        selected.append(universe.c.statement_id.in_(matching))
    statement_total = int(session.scalar(select(func.coalesce(func.sum(universe.c.amount_cent), 0)).where(*selected)) or 0)
    statement_total += int(session.scalar(select(func.coalesce(func.sum(displayed.c.amount_cent), 0)).where(
        displayed.c.is_projection.is_(True))) or 0)
    confirmed_conditions = [universe.c.month == month, universe.c.statement_id.in_(
        select(SettlementStatement.statement_id).where(SettlementStatement.is_current.is_(True)))]
    if row_filters:
        confirmed_conditions.append(universe.c.statement_id.in_(matching))
    confirmed = int(session.scalar(select(func.coalesce(func.sum(
        SettlementStatementConfirmation.confirmed_amount_cent), 0)).select_from(universe).join(
            SettlementStatementConfirmation, and_(
                SettlementStatementConfirmation.statement_id == universe.c.statement_id,
                SettlementStatementConfirmation.fee_direction == direction,
                SettlementStatementConfirmation.confirmation_status == 1,
            )).where(*confirmed_conditions)) or 0)
    invoice = PromotionInvoice if direction == 1 else InvoiceRecord
    if direction == 1:
        allocation = PromotionInvoiceAllocation
        issued_query = select(func.coalesce(func.sum(allocation.allocated_amount_cent), 0)).select_from(universe).join(
            allocation, allocation.statement_id == universe.c.statement_id).join(
            invoice, invoice.invoice_id == allocation.invoice_id).where(allocation.is_current.is_(True))
    else:
        issued_query = select(func.coalesce(func.sum(invoice.invoice_amount_cent), 0)).select_from(universe).join(
            invoice, and_(invoice.statement_id == universe.c.statement_id, invoice.fee_direction == direction))
    issued_query = issued_query.where(*selected, invoice.is_current.is_(True), invoice.is_tombstone.is_(False))
    issued = int(session.scalar(issued_query.where(invoice.invoice_status.in_((2, 3)) if direction == 1
        else invoice.invoice_status == 3)) or 0)
    settled = int(session.scalar(issued_query.where(invoice.invoice_status == 3)) or 0)
    # Carry-forward is a legal balance projection over already-issued bills.
    # Never include a bill absent from the selected publication or recalculate fees.
    published_statement_ids = select(universe.c.statement_id)
    matching_ids = set(session.scalars(matching)) if row_filters else None
    if direction == 1:
        _, groups = source._promotion_invoice_carryforward_projection(session, statement_ids=published_statement_ids)
        pending = sum(group["invoiceable_amount_cent"] for group in groups
            if group["closing_month"] is not None
            and (group["closing_month"] == month if metric_scope == "MONTH" else group["closing_month"] <= month)
            and (matching_ids is None or matching_ids.intersection(group["required_statement_ids"])))
    else:
        periods, _ = source._management_invoiceable_projection(session, statement_ids=published_statement_ids, through_month=month)
        pending = sum(period["invoiceable_amount_cent"] for period in periods
            if (period["statement_month"] == month if metric_scope == "MONTH" else period["statement_month"] <= month)
            and (matching_ids is None or period["statement_id"] in matching_ids))
        pending = max(pending, 0)
    return {"month": month, "store_id": store_id, "fee_direction": fee_direction,
        "metric_scope": metric_scope, "metrics": {
            "statement_total_cent": statement_total, "confirmed_amount_cent": confirmed,
            "pending_invoice_amount_cent": pending, "issued_amount_cent": issued,
            "settled_or_deducted_amount_cent": settled,
        }}
