"""Current store-submitted promotion invoices for the finance work queue."""

from collections import defaultdict

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import get_data_store
from dy_api.routes.dashboard import (
    INVOICE_STATUS_NAMES,
    MAX_FINANCE_ORDER_EXPORT_ROWS,
    _billing_session,
    _finance_csv_download,
    _finance_scope_store_ids,
    _normalize_invoice_status,
    _promotion_invoice_beijing_datetime,
    _raise_reporting_error,
    _reporting_success,
    _require_finance_admin,
    _validate_month,
)
from apps.api.dy_api.dashboard_publications.finance import _finance_display_context
from apps.api.dy_api.models import DimStore, PromotionInvoice, PromotionInvoiceAllocation, StoreFinanceProfile


router = APIRouter()
INVOICE_ROUTE = "/admin/finance/promotion-invoices/submitted"


def _submitted_query(request, current_user, *, month, q, invoice_status):
    _require_finance_admin(current_user, request, page_key="FIN01")
    invoice = PromotionInvoice
    allocation = PromotionInvoiceAllocation
    conditions = [invoice.is_current.is_(True), invoice.is_tombstone.is_(False)]
    store_ids = _finance_scope_store_ids(current_user)
    if store_ids is not None:
        conditions.append(invoice.store_id.in_(store_ids))
    if month is not None:
        _validate_month(month, "month", request)
        conditions.append(select(allocation.allocation_id).where(
            allocation.invoice_id == invoice.invoice_id,
            allocation.store_id == invoice.store_id,
            allocation.is_current.is_(True),
            allocation.statement_month == month,
        ).exists())
    status = _normalize_invoice_status(invoice_status, request, fee_direction="PROMOTION")
    if status is not None:
        conditions.append(invoice.invoice_status == status)
    if q and (term := q.strip().lower()):
        current_saps = select(StoreFinanceProfile.store_id).where(
            StoreFinanceProfile.is_current.is_(True), StoreFinanceProfile.is_tombstone.is_(False),
            func.lower(StoreFinanceProfile.sap_code).contains(term, autoescape=True),
        )
        store_names = select(DimStore.store_id).where(func.lower(DimStore.store_name).contains(term, autoescape=True))
        conditions.append(or_(
            invoice.invoice_number.contains(term, autoescape=True),
            func.lower(invoice.store_id).contains(term, autoescape=True),
            invoice.store_id.in_(store_names),
            invoice.store_id.in_(current_saps),
        ))
    return select(invoice).where(*conditions)


def _submitted_items(session, invoices):
    items = []
    for offset in range(0, len(invoices), 500):
        batch = invoices[offset:offset + 500]
        invoice_ids = {invoice.invoice_id for invoice in batch}
        context = _finance_display_context(session, store_ids={invoice.store_id for invoice in batch},
                                           invoice_ids=invoice_ids)
        periods = defaultdict(set)
        settlement_periods = defaultdict(set)
        allocation = PromotionInvoiceAllocation
        for invoice_id, statement_month, settlement_month in session.execute(select(
            allocation.invoice_id, allocation.statement_month, allocation.settlement_batch_month,
        ).join(PromotionInvoice, and_(PromotionInvoice.invoice_id == allocation.invoice_id,
                                    PromotionInvoice.store_id == allocation.store_id)).where(
            allocation.invoice_id.in_(invoice_ids), allocation.is_current.is_(True),
        )):
            periods[invoice_id].add(statement_month)
            settlement_periods[invoice_id].add(settlement_month)
        for invoice in batch:
            items.append({
                "invoice_id": invoice.invoice_id,
                "store_id": invoice.store_id,
                "store_name": context["names"].get(invoice.store_id),
                "effective_sap_code": context["effective_saps"].get(invoice.store_id),
                "invoice_number": invoice.invoice_number,
                "invoice_amount_cent": invoice.invoice_amount_cent,
                "statement_months": sorted(periods[invoice.invoice_id]),
                "settlement_batch_months": sorted(settlement_periods[invoice.invoice_id]),
                "registered_at": _promotion_invoice_beijing_datetime(invoice.registered_at),
                "status": INVOICE_STATUS_NAMES[invoice.invoice_status],
                "rejection_reason": context["rejections"].get(invoice.invoice_id) if invoice.invoice_status == 4 else None,
            })
    return items


@router.get(INVOICE_ROUTE)
def list_submitted_promotion_invoices(
    request: Request,
    month: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    invoice_status: str | None = Query(default=None, alias="invoiceStatus"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    query = _submitted_query(request, current_user, month=month, q=q, invoice_status=invoice_status)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    invoices = list(session.scalars(query.order_by(
        PromotionInvoice.registered_at.desc(), PromotionInvoice.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size)))
    return _reporting_success(request, {
        "list": _submitted_items(session, invoices), "total": total, "page": page, "page_size": page_size,
    })


@router.get(INVOICE_ROUTE + "/export")
def export_submitted_promotion_invoices(
    request: Request,
    month: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    invoice_status: str | None = Query(default=None, alias="invoiceStatus"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    query = _submitted_query(request, current_user, month=month, q=q, invoice_status=invoice_status)
    invoices = list(session.scalars(query.order_by(
        PromotionInvoice.registered_at.desc(), PromotionInvoice.id.desc(),
    ).limit(MAX_FINANCE_ORDER_EXPORT_ROWS + 1)))
    if len(invoices) > MAX_FINANCE_ORDER_EXPORT_ROWS:
        _raise_reporting_error(request, 413, "EXPORT_LIMIT_EXCEEDED",
                               f"命中记录超过 {MAX_FINANCE_ORDER_EXPORT_ROWS} 行，请缩小筛选范围")
    items = _submitted_items(session, invoices)
    for item in items:
        item["statement_months"] = "、".join(item["statement_months"])
        item["settlement_batch_months"] = "、".join(item["settlement_batch_months"])
    fields = {
        "invoice_id": "发票记录ID", "store_id": "门店ID", "store_name": "门店",
        "effective_sap_code": "有效SAP", "invoice_number": "数电专票号码",
        "invoice_amount_cent": "发票金额（元）", "statement_months": "原账期",
        "registered_at": "提交时间", "settlement_batch_months": "结算归属月",
        "status": "发票审核状态", "rejection_reason": "审核原因",
    }
    return _finance_csv_download(request=request, filename_prefix="finance-promotion-submitted-invoices",
                                fieldnames=list(fields), rows=items, header_labels=fields)
