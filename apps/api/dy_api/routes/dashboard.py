from __future__ import annotations

import json
from datetime import date, datetime, timezone
from hashlib import sha256
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import (
    ReportingPermissionError,
    ReportingValidationError,
    camelize,
    generated_at,
    get_data_store,
    request_id,
    with_utf8_bom,
)
from dy_api.schemas import (
    CommissionRulesSummaryData,
    OrderDetailsData,
    SalesDashboardData,
    dump_model,
)
from apps.api.dy_api.models import (
    DimStore,
    InvoiceRecord,
    InvoiceStatusEvent,
    PromotionInvoice,
    PromotionInvoiceAllocation,
    SettlementDispute,
    SettlementStatement,
    SettlementStatementConfirmation,
    SettlementStatementEntry,
    SettlementStatementLine,
    utcnow,
)


router = APIRouter()

FORMAL_PERIOD_START_MONTH = "2026-08"
PERIOD_TYPES = {"MONTHLY", "CUMULATIVE"}
METRIC_SCOPES = {"MONTH", "CUMULATIVE"}
FEE_DIRECTIONS = {"PROMOTION", "MANAGEMENT"}
DATA_STATUSES = {"VALID", "ADJUSTED", "BLOCKED", "LOCKED"}
RANKING_SORT_FIELDS = {
    "SALES_AMOUNT",
    "VERIFIED_AMOUNT",
    "PROMOTION_FEE",
    "MANAGEMENT_FEE",
    "NET_SETTLEMENT_REFERENCE",
}
SORT_ORDERS = {"ASC", "DESC"}
CONFIRMATION_DIRECTION_TO_DB = {"PROMOTION": 1, "MANAGEMENT": 2}
CONFIRMATION_DIRECTION_FROM_DB = {value: key for key, value in CONFIRMATION_DIRECTION_TO_DB.items()}
STATEMENT_STATUS_NAMES = {
    1: "GENERATING",
    2: "PENDING_CONFIRMATION",
    3: "CONFIRMED",
    4: "LOCKED",
}
CONFIRMATION_STATUS_NAMES = {1: "CONFIRMED", 2: "REVOKED"}
INVOICE_STATUS_NAMES = {
    1: "PENDING_INVOICE",
    2: "SUBMITTED_PENDING_FACTORY_REVIEW",
    3: "APPROVED_SETTLED",
    4: "REJECTED_REUPLOAD",
}


STORE_RANKING_DEFINITIONS = [
    {
        "key": "salesOrderCount",
        "label": "销售订单数量",
        "description": "当前完整筛选集合中的销售订单数量，不受当前分页影响。",
    },
    {
        "key": "salesAmountCent",
        "label": "销售金额",
        "description": "当前完整筛选集合中的销售金额，单位分。",
    },
    {
        "key": "verifiedOrderCount",
        "label": "核销订单数量",
        "description": "当前完整筛选集合中的核销订单数量。",
    },
    {
        "key": "verifiedAmountCent",
        "label": "核销金额",
        "description": "当前完整筛选集合中的核销金额，单位分。",
    },
    {
        "key": "promotionNetFeeCent",
        "label": "推广服务费净额",
        "description": "推广服务费原始金额加调整金额后的净额，单位分。",
    },
    {
        "key": "managementNetFeeCent",
        "label": "管理服务费净额",
        "description": "管理服务费原始金额加调整金额后的净额，单位分。",
    },
    {
        "key": "netSettlementReferenceCent",
        "label": "结算参考净额",
        "description": "推广服务费净额减管理服务费净额，仅作为经营与结算核对依据。",
    },
]

MONTHLY_SETTLEMENT_DEFINITIONS = [
    {
        "key": "promotionNetFeeCent",
        "label": "应收推广服务费净额",
        "description": "推广服务费原始金额与调整金额合计后的调整后净额。",
    },
    {
        "key": "managementNetFeeCent",
        "label": "应扣管理服务费净额",
        "description": "管理服务费原始金额与调整金额合计后的调整后净额。",
    },
]

SALES_DASHBOARD_DEFINITIONS = [
    {
        "key": "total_sales_order_count",
        "label": "总销售订单量",
        "description": "销售归属门店在所选期间卖出的有效订单数，按订单编号去重，退款订单不计入。",
    },
    {
        "key": "self_verify_order_count",
        "label": "自店核销数",
        "description": "销售归属门店和实际核销门店都是当前门店的订单数，按订单编号去重，退款订单不计入。",
    },
    {
        "key": "self_verify_rate",
        "label": "自店核销率",
        "description": "自店核销数 / 总销售订单量；总销售订单量为 0 时显示 0。",
    },
    {
        "key": "total_verify_order_count",
        "label": "实际核销总数",
        "description": "不管销售归属门店，只要在当前门店于所选期间完成核销即计入，按订单编号去重；一单核销多券也只算一单。",
    },
    {
        "key": "actual_verify_amount_cent",
        "label": "实际核销金额",
        "description": "当前门店产生核销后的实收金额合计，退款订单不计入。",
    },
    {
        "key": "avg_verify_cycle_days",
        "label": "平均核销周期",
        "description": "当前门店已核销订单从销售时间到核销时间的平均天数，按订单编号去重。",
    },
    {
        "key": "cycle_distribution",
        "label": "核销周期分布",
        "description": "按商品类型展示当前门店核销订单从销售时间到核销时间的周期，箱线图展示四分位，散点展示订单样本。",
    },
]


def _filters_from_query(
    *,
    product_scope: str,
    product_type: str,
    sale_store_id: str | None,
    exclude_sale_store_id: str | None,
    sale_month: str | None,
    is_verified: bool | None,
    verify_store_id: str | None,
    exclude_verify_store_id: str | None,
    verify_month: str | None,
    relation_type: str | None,
    is_commissionable: bool | None,
    q: str | None,
    page: int,
    page_size: int,
) -> dict:
    return {
        "product_scope": product_scope,
        "product_type": product_type,
        "sale_store_id": sale_store_id,
        "exclude_sale_store_id": exclude_sale_store_id,
        "sale_month": sale_month,
        "is_verified": is_verified,
        "verify_store_id": verify_store_id,
        "exclude_verify_store_id": exclude_verify_store_id,
        "verify_month": verify_month,
        "relation_type": relation_type,
        "is_commissionable": is_commissionable,
        "q": q,
        "page": page,
        "page_size": page_size,
    }


@router.get("/dashboard/store-ranking")
def store_ranking(
    request: Request,
    period_type: str = Query(default="MONTHLY", alias="periodType"),
    period_key: str = Query(alias="periodKey"),
    product_scope: str = Query(default="all", alias="productScope"),
    product_type: str = Query(default="all", alias="productType"),
    q: str | None = None,
    sort_by: str = Query(default="NET_SETTLEMENT_REFERENCE", alias="sortBy"),
    sort_order: str = Query(default="DESC", alias="sortOrder"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    period_type = period_type.upper()
    sort_by = sort_by.upper()
    sort_order = sort_order.upper()
    _validate_month(period_key, "periodKey", request)
    _validate_enum(period_type, PERIOD_TYPES, "periodType", request)
    _validate_enum(sort_by, RANKING_SORT_FIELDS, "sortBy", request)
    _validate_enum(sort_order, SORT_ORDERS, "sortOrder", request)
    _validate_product_selection(store, product_scope, product_type, request)
    scope_mode = (
        "AUTHORIZED"
        if current_user.has_global_data_access
        else "GLOBAL_TOP_20_EXCEPTION"
    )
    if scope_mode == "GLOBAL_TOP_20_EXCEPTION":
        page = 1
        page_size = min(page_size, 20)
    filters = {
        "period_type": period_type,
        "period_key": period_key,
        "product_scope": product_scope,
        "product_type": product_type,
        "q": (q or "").strip() or None,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "page": page,
        "page_size": page_size,
        "scope_mode": scope_mode,
        "scope_store_ids": (
            None if current_user.has_global_data_access else current_user.store_ids
        ),
    }
    data = _call_reporting_store(request, store.store_ranking_report, filters)
    return _reporting_success(request, data, definitions=STORE_RANKING_DEFINITIONS)


@router.get("/commission-rules/summary")
def commission_rules_summary(
    _current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    data = CommissionRulesSummaryData(**store.commission_rules_summary())
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/store-settlements")
def list_store_settlements(
    request: Request,
    store_id: str = Query(alias="storeId"),
    month: str = Query(),
    metric_scope: str = Query(alias="metricScope"),
    fee_direction: str | None = Query(default=None, alias="feeDirection"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    _require_billing_store_scope(current_user, store_id, request)
    _validate_month(month, "month", request)
    metric_scope = metric_scope.upper()
    _validate_enum(metric_scope, METRIC_SCOPES, "metricScope", request)
    direction = _normalize_billing_direction(fee_direction, request)
    _require_billing_store(session, store_id, request)

    conditions = [
        SettlementStatement.store_id == store_id,
        SettlementStatement.statement_month == month,
        SettlementStatement.is_current.is_(True),
    ]
    total = session.scalar(
        select(func.count()).select_from(SettlementStatement).where(*conditions)
    ) or 0
    statements = list(
        session.scalars(
            select(SettlementStatement)
            .where(*conditions)
            .order_by(SettlementStatement.statement_month.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    data = {
        "list": [
            _statement_list_item(session, statement, direction=direction)
            for statement in statements
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "metric_scope": metric_scope,
        "metrics": _statement_metrics(session, store_id, month, metric_scope),
    }
    return _reporting_success(request, data)


@router.get("/store-settlements/{statement_id}")
def get_store_settlement_detail(
    statement_id: str,
    request: Request,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    statement = _get_billing_statement(session, statement_id, request)
    _require_billing_store_scope(current_user, statement.store_id, request)
    versions = list(
        session.scalars(
            select(SettlementStatement)
            .where(
                SettlementStatement.store_id == statement.store_id,
                SettlementStatement.statement_month == statement.statement_month,
            )
            .order_by(SettlementStatement.version_no.desc())
        )
    )
    lines = list(
        session.scalars(
            select(SettlementStatementLine)
            .where(SettlementStatementLine.statement_id == statement.statement_id)
            .order_by(
                SettlementStatementLine.fee_direction,
                SettlementStatementLine.product_scope,
                SettlementStatementLine.product_type,
            )
        )
    )
    entry_count = session.scalar(
        select(func.count())
        .select_from(SettlementStatementEntry)
        .where(SettlementStatementEntry.statement_id == statement.statement_id)
    ) or 0
    dispute_count = session.scalar(
        select(func.count())
        .select_from(SettlementDispute)
        .where(SettlementDispute.statement_id == statement.statement_id)
    ) or 0
    invoices = list(
        session.scalars(
            select(InvoiceRecord).where(InvoiceRecord.statement_id == statement.statement_id)
        )
    )
    data = {
        **_statement_header_item(session, statement),
        "versions": [_statement_version_item(row) for row in versions],
        "lines": [_statement_line_item(line) for line in lines],
        "source_summary": {"entry_count": entry_count},
        "dispute_summary": {"count": dispute_count},
        "invoice_summary": [
            {
                "invoice_id": invoice.invoice_id,
                "fee_direction": CONFIRMATION_DIRECTION_FROM_DB[invoice.fee_direction],
                "status": INVOICE_STATUS_NAMES[invoice.invoice_status],
                "invoice_amount_cent": invoice.invoice_amount_cent,
            }
            for invoice in invoices
        ],
    }
    return _reporting_success(request, data)


@router.post("/store-settlements/{statement_id}/confirmations")
def confirm_store_settlement(
    statement_id: str,
    payload: dict,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    statement = _get_billing_statement(session, statement_id, request)
    _require_billing_store_scope(current_user, statement.store_id, request)
    parsed = _parse_confirmation_payload(payload, request)
    key_hash = _billing_idempotency_key_hash(idempotency_key, request)
    payload_hash = _canonical_billing_sha256(parsed)
    replay = session.scalar(
        select(SettlementStatementConfirmation).where(
            SettlementStatementConfirmation.idempotency_key_hash == key_hash
        )
    )
    if replay is not None:
        if replay.request_payload_sha256 != payload_hash:
            _raise_reporting_error(
                request,
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency-Key 已用于不同请求",
            )
        return _reporting_success(request, _confirmation_item(replay, statement))

    if not statement.is_current or statement.version_no != parsed["read_version"]:
        _raise_statement_version_conflict(request, statement)
    direction = parsed["fee_direction"]
    expected_amount = (
        statement.promotion_net_fee_cent
        if direction == "PROMOTION"
        else statement.management_net_fee_cent
    )
    if parsed["confirmed_amount_cent"] != expected_amount:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "确认金额必须等于当前账单净额",
            field="confirmedAmountCent",
        )
    existing = session.scalar(
        select(SettlementStatementConfirmation).where(
            SettlementStatementConfirmation.statement_id == statement.statement_id,
            SettlementStatementConfirmation.fee_direction
            == CONFIRMATION_DIRECTION_TO_DB[direction],
        )
    )
    if existing is not None:
        _raise_reporting_error(
            request,
            status.HTTP_409_CONFLICT,
            "CONFIRMATION_ALREADY_RECORDED",
            "该费用方向已确认",
        )
    now = utcnow()
    confirmation = SettlementStatementConfirmation(
        confirmation_id=f"confirmation-{uuid4().hex}",
        statement_id=statement.statement_id,
        fee_direction=CONFIRMATION_DIRECTION_TO_DB[direction],
        confirmation_status=1,
        confirmed_amount_cent=expected_amount,
        confirmed_by=current_user.username,
        confirmed_at=now,
        idempotency_key_hash=key_hash,
        request_payload_sha256=payload_hash,
    )
    session.add(confirmation)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        _raise_reporting_error(
            request,
            status.HTTP_409_CONFLICT,
            "CONFIRMATION_ALREADY_RECORDED",
            "该费用方向已确认或幂等键已被使用",
        )
    return _reporting_success(request, _confirmation_item(confirmation, statement))


@router.get("/promotion-invoices")
def list_promotion_invoices(
    request: Request,
    store_id: str = Query(alias="storeId"),
    month: str = Query(),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    _require_billing_store_scope(current_user, store_id, request)
    _require_billing_store(session, store_id, request)
    _validate_month(month, "month", request)
    conditions = [
        PromotionInvoiceAllocation.store_id == store_id,
        PromotionInvoiceAllocation.statement_month == month,
        PromotionInvoiceAllocation.is_current.is_(True),
        PromotionInvoice.is_current.is_(True),
    ]
    if status_filter is not None:
        normalized_status = status_filter.upper()
        if normalized_status not in set(INVOICE_STATUS_NAMES.values()):
            _validate_enum(normalized_status, set(INVOICE_STATUS_NAMES.values()), "status", request)
        if normalized_status == "PENDING_INVOICE":
            return _reporting_success(request, {"list": [], "total": 0, "page": page, "page_size": page_size})
        conditions.append(PromotionInvoice.invoice_status == _invoice_status_db(normalized_status))
    query = (
        select(PromotionInvoice, PromotionInvoiceAllocation)
        .join(PromotionInvoiceAllocation, PromotionInvoiceAllocation.invoice_id == PromotionInvoice.invoice_id)
        .where(*conditions)
        .order_by(PromotionInvoice.registered_at.desc())
    )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
    return _reporting_success(request, {
        "list": [_promotion_invoice_item(invoice, allocation) for invoice, allocation in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.post("/promotion-invoices")
def register_promotion_invoice(
    payload: dict,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    parsed = _parse_promotion_invoice_payload(payload, request)
    _require_billing_store_scope(current_user, parsed["store_id"], request)
    _require_billing_store(session, parsed["store_id"], request)
    key_hash = _billing_idempotency_key_hash(idempotency_key, request)
    payload_hash = _canonical_billing_sha256(parsed)
    replay = session.scalar(select(PromotionInvoice).where(PromotionInvoice.idempotency_key_hash == key_hash))
    if replay is not None:
        if replay.request_payload_sha256 != payload_hash:
            _raise_reporting_error(request, status.HTTP_409_CONFLICT, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key 已用于不同请求")
        return _reporting_success(request, _promotion_invoice_header_item(session, replay))
    allocations = []
    for item in parsed["allocations"]:
        statement = _get_billing_statement(session, item["statement_id"], request)
        if (not statement.is_current or statement.store_id != parsed["store_id"]
                or statement.statement_month != item["statement_month"]
                or statement.version_no != item["read_version"]):
            _raise_statement_version_conflict(request, statement)
        confirmed = session.scalar(select(SettlementStatementConfirmation).where(
            SettlementStatementConfirmation.statement_id == statement.statement_id,
            SettlementStatementConfirmation.fee_direction == 1,
            SettlementStatementConfirmation.confirmation_status == 1,
        ))
        if confirmed is None or confirmed.confirmed_amount_cent != item["allocated_amount_cent"]:
            _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "每个账期分配金额必须等于当前有效推广费确认金额", field="allocations")
        occupied = session.scalar(select(PromotionInvoiceAllocation).where(
            PromotionInvoiceAllocation.store_id == statement.store_id,
            PromotionInvoiceAllocation.statement_month == statement.statement_month,
            PromotionInvoiceAllocation.is_current.is_(True),
        ))
        if occupied is not None:
            previous_invoice = session.scalar(select(PromotionInvoice).where(
                PromotionInvoice.invoice_id == occupied.invoice_id,
                PromotionInvoice.is_current.is_(True),
            ))
            if previous_invoice is None or previous_invoice.invoice_status != 4:
                _raise_reporting_error(request, status.HTTP_409_CONFLICT, "PROMOTION_INVOICE_PERIOD_OCCUPIED", "账期已存在当前有效推广费发票分配", field="allocations")
        allocations.append((statement, item))
    now = utcnow()
    rejected_invoices = list(session.scalars(select(PromotionInvoice).join(
        PromotionInvoiceAllocation,
        PromotionInvoiceAllocation.invoice_id == PromotionInvoice.invoice_id,
    ).where(
        PromotionInvoiceAllocation.store_id == parsed["store_id"],
        PromotionInvoiceAllocation.statement_month.in_([item["statement_month"] for _, item in allocations]),
        PromotionInvoiceAllocation.is_current.is_(True),
        PromotionInvoice.is_current.is_(True),
        PromotionInvoice.invoice_status == 4,
    )))
    previous_invoice = rejected_invoices[0] if rejected_invoices else None
    if previous_invoice is not None:
        previous_invoice.is_current = False
        for allocation in session.scalars(select(PromotionInvoiceAllocation).where(
            PromotionInvoiceAllocation.invoice_id == previous_invoice.invoice_id,
            PromotionInvoiceAllocation.is_current.is_(True),
        )):
            allocation.is_current = False
    invoice = PromotionInvoice(
        invoice_id=f"promotion-invoice-{uuid4().hex}", store_id=parsed["store_id"],
        version_no=(previous_invoice.version_no + 1) if previous_invoice else 1,
        supersedes_invoice_id=previous_invoice.invoice_id if previous_invoice else None,
        invoice_number=parsed["invoice_number"], invoice_date=parsed["invoice_date"],
        invoice_amount_cent=parsed["invoice_amount_cent"], invoice_status=2,
        registered_by=current_user.username, registered_at=now,
        idempotency_key_hash=key_hash, request_payload_sha256=payload_hash,
    )
    session.add(invoice)
    for statement, item in allocations:
        session.add(PromotionInvoiceAllocation(
            allocation_id=f"promotion-allocation-{uuid4().hex}", invoice_id=invoice.invoice_id,
            store_id=statement.store_id, statement_id=statement.statement_id,
            statement_month=statement.statement_month, allocated_amount_cent=item["allocated_amount_cent"],
        ))
    session.add(InvoiceStatusEvent(
        event_id=f"invoice-event-{uuid4().hex}", invoice_id=invoice.invoice_id,
        event_type=1, from_status=None, to_status=2, operator_id=current_user.username,
        occurred_at=now,
    ))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        _raise_reporting_error(request, status.HTTP_409_CONFLICT, "PROMOTION_INVOICE_CONFLICT", "发票号码或账期分配已存在")
    return _reporting_success(request, _promotion_invoice_header_item(session, invoice))


@router.get("/admin/finance/summary")
def get_admin_finance_summary(
    request: Request,
    month: str = Query(),
    fee_direction: str = Query(alias="feeDirection"),
    metric_scope: str = Query(alias="metricScope"),
    store_id: str | None = Query(default=None, alias="storeId"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    _require_finance_admin(current_user, request)
    _validate_month(month, "month", request)
    direction = _normalize_billing_direction(fee_direction, request)
    normalized_scope = metric_scope.upper()
    _validate_enum(normalized_scope, METRIC_SCOPES, "metricScope", request)
    if store_id is not None:
        _require_billing_store(session, store_id, request)

    return _reporting_success(
        request,
        {
            "month": month,
            "store_id": store_id,
            "fee_direction": direction,
            "metric_scope": normalized_scope,
            "metrics": _finance_summary_metrics(
                session,
                month=month,
                fee_direction=direction,
                metric_scope=normalized_scope,
                store_id=store_id,
            ),
        },
    )


@router.get("/admin/finance/invoices")
def list_admin_finance_invoices(
    request: Request,
    month: str = Query(),
    fee_direction: str = Query(alias="feeDirection"),
    store_id: str | None = Query(default=None, alias="storeId"),
    invoice_status: str | None = Query(default=None, alias="invoiceStatus"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    _require_finance_admin(current_user, request)
    _validate_month(month, "month", request)
    direction = _normalize_billing_direction(fee_direction, request)
    if store_id is not None:
        _require_billing_store(session, store_id, request)
    status_code = _normalize_invoice_status(invoice_status, request)

    if direction == "PROMOTION":
        conditions = [
            PromotionInvoiceAllocation.statement_month == month,
            PromotionInvoiceAllocation.is_current.is_(True),
            PromotionInvoice.is_current.is_(True),
            SettlementStatement.is_current.is_(True),
        ]
        if store_id is not None:
            conditions.append(PromotionInvoiceAllocation.store_id == store_id)
        if status_code is not None:
            conditions.append(PromotionInvoice.invoice_status == status_code)
        query = (
            select(PromotionInvoice, PromotionInvoiceAllocation)
            .join(
                PromotionInvoiceAllocation,
                PromotionInvoiceAllocation.invoice_id == PromotionInvoice.invoice_id,
            )
            .join(
                SettlementStatement,
                SettlementStatement.statement_id == PromotionInvoiceAllocation.statement_id,
            )
            .where(*conditions)
            .order_by(PromotionInvoice.registered_at.desc(), PromotionInvoice.invoice_id)
        )
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = session.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
        items = [_promotion_invoice_item(invoice, allocation) for invoice, allocation in rows]
    else:
        conditions = [
            InvoiceRecord.statement_month == month,
            InvoiceRecord.fee_direction == CONFIRMATION_DIRECTION_TO_DB[direction],
            InvoiceRecord.is_current.is_(True),
            SettlementStatement.is_current.is_(True),
        ]
        if store_id is not None:
            conditions.append(InvoiceRecord.store_id == store_id)
        if status_code is not None:
            conditions.append(InvoiceRecord.invoice_status == status_code)
        query = (
            select(InvoiceRecord)
            .join(
                SettlementStatement,
                SettlementStatement.statement_id == InvoiceRecord.statement_id,
            )
            .where(*conditions)
            .order_by(InvoiceRecord.registered_at.desc(), InvoiceRecord.invoice_id)
        )
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        invoices = list(session.scalars(query.offset((page - 1) * page_size).limit(page_size)))
        items = [_management_invoice_item(invoice) for invoice in invoices]

    return _reporting_success(
        request,
        {"list": items, "total": total, "page": page, "page_size": page_size},
    )


@router.get("/admin/finance/order-details")
def list_admin_finance_order_details(
    request: Request,
    month: str = Query(),
    fee_direction: str = Query(alias="feeDirection"),
    store_id: str | None = Query(default=None, alias="storeId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    _require_finance_admin(current_user, request)
    _validate_month(month, "month", request)
    direction = _normalize_billing_direction(fee_direction, request)
    if store_id is not None:
        _require_billing_store(session, store_id, request)
    conditions = [
        SettlementStatement.statement_month == month,
        SettlementStatement.is_current.is_(True),
        SettlementStatementEntry.fee_direction == CONFIRMATION_DIRECTION_TO_DB[direction],
    ]
    if store_id is not None:
        conditions.append(SettlementStatement.store_id == store_id)
    query = (
        select(SettlementStatementEntry, SettlementStatement)
        .join(
            SettlementStatement,
            SettlementStatement.statement_id == SettlementStatementEntry.statement_id,
        )
        .where(*conditions)
        .order_by(SettlementStatementEntry.order_id, SettlementStatementEntry.statement_entry_id)
    )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
    return _reporting_success(
        request,
        {
            "list": [
                _finance_order_detail_item(entry, statement, direction)
                for entry, statement in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get("/admin/finance/stores")
def list_admin_finance_stores(
    request: Request,
    month: str = Query(),
    fee_direction: str = Query(alias="feeDirection"),
    metric_scope: str = Query(alias="metricScope"),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    session = _billing_session(store, request)
    _require_finance_admin(current_user, request)
    _validate_month(month, "month", request)
    direction = _normalize_billing_direction(fee_direction, request)
    normalized_scope = metric_scope.upper()
    _validate_enum(normalized_scope, METRIC_SCOPES, "metricScope", request)
    conditions = _finance_statement_conditions(
        month=month, metric_scope=normalized_scope, store_id=None
    )
    normalized_query = (q or "").strip()
    if normalized_query:
        conditions.append(
            (SettlementStatement.store_id.contains(normalized_query))
            | (DimStore.store_name.contains(normalized_query))
        )
    store_ids_query = (
        select(SettlementStatement.store_id)
        .join(DimStore, DimStore.store_id == SettlementStatement.store_id)
        .where(*conditions)
        .distinct()
        .order_by(SettlementStatement.store_id)
    )
    total = session.scalar(select(func.count()).select_from(store_ids_query.subquery())) or 0
    store_ids = list(
        session.scalars(store_ids_query.offset((page - 1) * page_size).limit(page_size))
    )
    stores = {
        store_row.store_id: store_row
        for store_row in session.scalars(select(DimStore).where(DimStore.store_id.in_(store_ids)))
    }
    items = []
    for current_store_id in store_ids:
        store_row = stores[current_store_id]
        metrics = _finance_summary_metrics(
            session,
            month=month,
            fee_direction=direction,
            metric_scope=normalized_scope,
            store_id=current_store_id,
        )
        items.append(
            {
                "store_id": store_row.store_id,
                "store_name": store_row.store_name,
                "sap_code": None,
                "updated_at": store_row.updated_at,
                **metrics,
            }
        )
    return _reporting_success(
        request,
        {"list": items, "total": total, "page": page, "page_size": page_size},
    )


@router.get("/stores/{store_id}/monthly-settlement")
def monthly_settlement(
    request: Request,
    store_id: str,
    month: str,
    product_scope: str = Query(default="all", alias="productScope"),
    product_type: str = Query(default="all", alias="productType"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    _require_store_scope(current_user, store_id)
    _validate_month(month, "month", request)
    _validate_product_selection(store, product_scope, product_type, request)
    _validate_monthly_context(store, store_id, month, request)
    data = _call_reporting_store(
        request,
        store.monthly_settlement_report,
        {
            "store_id": store_id,
            "month": month,
            "product_scope": product_scope,
            "product_type": product_type,
        },
    )
    return _reporting_success(
        request, data, definitions=MONTHLY_SETTLEMENT_DEFINITIONS
    )


@router.get("/order-fee-details")
def order_fee_details(
    request: Request,
    statement_id: str | None = Query(default=None, alias="statementId"),
    statement_line_id: str | None = Query(default=None, alias="statementLineId"),
    store_id: str | None = Query(default=None, alias="storeId"),
    month: str | None = None,
    sale_month: str | None = Query(default=None, alias="saleMonth"),
    verify_month: str | None = Query(default=None, alias="verifyMonth"),
    fee_direction: str = Query(alias="feeDirection"),
    product_scope: str = Query(default="all", alias="productScope"),
    product_type: str = Query(default="all", alias="productType"),
    fee_rates: list[str] | None = Query(default=None, alias="feeRates"),
    rule_versions: list[str] | None = Query(default=None, alias="ruleVersions"),
    data_status: str | None = Query(default=None, alias="dataStatus"),
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    filters = _order_fee_filters(
        request=request,
        store=store,
        current_user=current_user,
        statement_id=statement_id,
        statement_line_id=statement_line_id,
        store_id=store_id,
        month=month,
        sale_month=sale_month,
        verify_month=verify_month,
        fee_direction=fee_direction,
        product_scope=product_scope,
        product_type=product_type,
        fee_rates=fee_rates,
        rule_versions=rule_versions,
        data_status=data_status,
        q=q,
        page=page,
        page_size=page_size,
    )
    data = _call_reporting_store(request, store.order_fee_details, filters)
    return _reporting_success(request, data)


@router.get("/order-fee-details/export")
def order_fee_details_export(
    request: Request,
    statement_id: str | None = Query(default=None, alias="statementId"),
    statement_line_id: str | None = Query(default=None, alias="statementLineId"),
    store_id: str | None = Query(default=None, alias="storeId"),
    month: str | None = None,
    sale_month: str | None = Query(default=None, alias="saleMonth"),
    verify_month: str | None = Query(default=None, alias="verifyMonth"),
    fee_direction: str = Query(alias="feeDirection"),
    product_scope: str = Query(default="all", alias="productScope"),
    product_type: str = Query(default="all", alias="productType"),
    fee_rates: list[str] | None = Query(default=None, alias="feeRates"),
    rule_versions: list[str] | None = Query(default=None, alias="ruleVersions"),
    data_status: str | None = Query(default=None, alias="dataStatus"),
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    filters = _order_fee_filters(
        request=request,
        store=store,
        current_user=current_user,
        statement_id=statement_id,
        statement_line_id=statement_line_id,
        store_id=store_id,
        month=month,
        sale_month=sale_month,
        verify_month=verify_month,
        fee_direction=fee_direction,
        product_scope=product_scope,
        product_type=product_type,
        fee_rates=fee_rates,
        rule_versions=rule_versions,
        data_status=data_status,
        q=q,
        page=page,
        page_size=page_size,
    )
    csv_text = _call_reporting_store(
        request, store.order_fee_details_export_csv, filters
    )
    if not csv_text:
        _raise_reporting_error(
            request,
            status.HTTP_409_CONFLICT,
            "EXPORT_EMPTY",
            "当前筛选无可导出明细",
        )
    generated = generated_at().isoformat()
    filename = quote(f"order-fee-details-{generated[:10]}.csv")
    current_request_id = request_id(request)
    return Response(
        content=with_utf8_bom(csv_text),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Export-Generated-At": generated,
            "X-Export-Filters": store.export_filter_header(filters),
            "X-Request-ID": current_request_id,
        },
    )


@router.get("/dashboard/sales")
def sales_dashboard(
    store_id: str | None = None,
    month: str = "all",
    product_scope: str = "all",
    product_type: str = "all",
    trend_months: list[str] | None = Query(default=None),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    scoped_store_id = _resolve_sales_dashboard_store_id(current_user, store_id)
    data = SalesDashboardData(
        **store.sales_dashboard(
            store_id=scoped_store_id,
            month=month,
            product_scope=product_scope,
            product_type=product_type,
            trend_months=trend_months or [],
        )
    )
    return {
        "data": dump_model(data),
        "definitions": SALES_DASHBOARD_DEFINITIONS,
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/order-details")
def order_details(
    product_scope: str = "all",
    product_type: str = "all",
    sale_store_id: str | None = None,
    exclude_sale_store_id: str | None = None,
    sale_month: str | None = None,
    is_verified: bool | None = None,
    verify_store_id: str | None = None,
    exclude_verify_store_id: str | None = None,
    verify_month: str | None = None,
    relation_type: str | None = None,
    is_commissionable: bool | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    filters = _filters_from_query(
        product_scope=product_scope,
        product_type=product_type,
        sale_store_id=sale_store_id,
        exclude_sale_store_id=exclude_sale_store_id,
        sale_month=sale_month,
        is_verified=is_verified,
        verify_store_id=verify_store_id,
        exclude_verify_store_id=exclude_verify_store_id,
        verify_month=verify_month,
        relation_type=relation_type,
        is_commissionable=is_commissionable,
        q=q,
        page=page,
        page_size=page_size,
    )
    if not current_user.has_global_data_access:
        filters["scope_store_ids"] = current_user.store_ids
    data = OrderDetailsData(**store.order_details(filters))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/order-details/export")
def order_details_export(
    product_scope: str = "all",
    product_type: str = "all",
    sale_store_id: str | None = None,
    exclude_sale_store_id: str | None = None,
    sale_month: str | None = None,
    is_verified: bool | None = None,
    verify_store_id: str | None = None,
    exclude_verify_store_id: str | None = None,
    verify_month: str | None = None,
    relation_type: str | None = None,
    is_commissionable: bool | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    filters = _filters_from_query(
        product_scope=product_scope,
        product_type=product_type,
        sale_store_id=sale_store_id,
        exclude_sale_store_id=exclude_sale_store_id,
        sale_month=sale_month,
        is_verified=is_verified,
        verify_store_id=verify_store_id,
        exclude_verify_store_id=exclude_verify_store_id,
        verify_month=verify_month,
        relation_type=relation_type,
        is_commissionable=is_commissionable,
        q=q,
        page=page,
        page_size=page_size,
    )
    if not current_user.has_global_data_access:
        filters["scope_store_ids"] = current_user.store_ids
    generated = generated_at().isoformat()
    filename = quote(f"order-details-{generated[:10]}.csv")
    return Response(
        content=with_utf8_bom(store.order_details_export_csv(filters)),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Export-Generated-At": generated,
            "X-Export-Filters": store.export_filter_header(filters),
        },
    )


def _reporting_success(
    request: Request, data: dict, *, definitions: list[dict] | None = None
) -> dict:
    payload = {
        "data": camelize(data),
        "meta": {
            "generatedAt": generated_at(),
            "source": "postgres",
            "requestId": request_id(request),
        },
    }
    if definitions:
        payload["definitions"] = [camelize(item) for item in definitions]
    return payload


def _billing_session(store, request: Request):
    session = getattr(store, "session", None)
    if session is None:
        _raise_reporting_error(
            request,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DATABASE_UNAVAILABLE",
            "数据库暂不可用",
        )
    return session


def _require_billing_store_scope(
    current_user: AuthContext, store_id: str, request: Request
) -> None:
    if not current_user.has_global_data_access and store_id not in current_user.store_ids:
        _raise_reporting_error(
            request,
            status.HTTP_403_FORBIDDEN,
            "DATA_SCOPE_FORBIDDEN",
            "门店不在当前账号数据范围内",
            field="storeId",
        )


def _require_billing_store(session, store_id: str, request: Request) -> None:
    if session.get(DimStore, store_id) is None:
        _raise_reporting_error(
            request,
            status.HTTP_404_NOT_FOUND,
            "RESOURCE_NOT_FOUND",
            "门店不存在",
            field="storeId",
        )


def _normalize_billing_direction(value: str | None, request: Request) -> str | None:
    if value is None:
        return None
    direction = value.upper()
    _validate_enum(direction, FEE_DIRECTIONS, "feeDirection", request)
    return direction


def _get_billing_statement(session, statement_id: str, request: Request) -> SettlementStatement:
    statement = session.scalar(
        select(SettlementStatement).where(SettlementStatement.statement_id == statement_id)
    )
    if statement is None:
        _raise_reporting_error(
            request,
            status.HTTP_404_NOT_FOUND,
            "RESOURCE_NOT_FOUND",
            "账单不存在",
            field="statementId",
        )
    return statement


def _statement_list_item(
    session, statement: SettlementStatement, *, direction: str | None
) -> dict:
    item = _statement_header_item(session, statement)
    if direction is not None:
        item["fee_direction"] = direction
    return item


def _statement_metrics(session, store_id: str, month: str, metric_scope: str) -> dict:
    monthly_conditions = [
        SettlementStatement.store_id == store_id,
        SettlementStatement.statement_month == month,
        SettlementStatement.is_current.is_(True),
    ]
    monthly = session.execute(
        select(
            func.coalesce(func.sum(SettlementStatement.promotion_net_fee_cent), 0),
            func.coalesce(func.sum(SettlementStatement.management_net_fee_cent), 0),
        ).where(*monthly_conditions)
    ).one()
    data = {
        "month": {
            "promotion_amount_cent": int(monthly[0]),
            "management_amount_cent": int(monthly[1]),
        }
    }
    if metric_scope == "CUMULATIVE":
        cumulative = session.execute(
            select(
                func.coalesce(func.sum(SettlementStatement.promotion_net_fee_cent), 0),
                func.coalesce(func.sum(SettlementStatement.management_net_fee_cent), 0),
            ).where(
                SettlementStatement.store_id == store_id,
                SettlementStatement.statement_month >= FORMAL_PERIOD_START_MONTH,
                SettlementStatement.statement_month <= month,
                SettlementStatement.is_current.is_(True),
            )
        ).one()
        data["cumulative"] = {
            "promotion_amount_cent": int(cumulative[0]),
            "management_amount_cent": int(cumulative[1]),
        }
    return data


def _require_finance_admin(current_user: AuthContext, request: Request) -> None:
    if not current_user.is_admin:
        _raise_reporting_error(
            request,
            status.HTTP_403_FORBIDDEN,
            "DATA_SCOPE_FORBIDDEN",
            "仅管理员和最高管理员可以查询财务汇总",
        )


def _finance_statement_conditions(
    *, month: str, metric_scope: str, store_id: str | None
) -> list:
    conditions = [SettlementStatement.is_current.is_(True)]
    if metric_scope == "CUMULATIVE":
        conditions.extend(
            [
                SettlementStatement.statement_month >= FORMAL_PERIOD_START_MONTH,
                SettlementStatement.statement_month <= month,
            ]
        )
    else:
        conditions.append(SettlementStatement.statement_month == month)
    if store_id is not None:
        conditions.append(SettlementStatement.store_id == store_id)
    return conditions


def _finance_summary_metrics(
    session,
    *,
    month: str,
    fee_direction: str,
    metric_scope: str,
    store_id: str | None,
) -> dict:
    statement_conditions = _finance_statement_conditions(
        month=month, metric_scope=metric_scope, store_id=store_id
    )
    direction_code = CONFIRMATION_DIRECTION_TO_DB[fee_direction]
    fee_column = (
        SettlementStatement.promotion_net_fee_cent
        if fee_direction == "PROMOTION"
        else SettlementStatement.management_net_fee_cent
    )
    statement_total = session.scalar(
        select(func.coalesce(func.sum(fee_column), 0)).where(*statement_conditions)
    )
    monthly_confirmation_total = _finance_confirmation_total(
        session,
        statement_conditions=_finance_statement_conditions(
            month=month, metric_scope="MONTH", store_id=store_id
        ),
        direction_code=direction_code,
    )
    pending_confirmation_total = (
        monthly_confirmation_total
        if metric_scope == "MONTH"
        else _finance_confirmation_total(
            session,
            statement_conditions=statement_conditions,
            direction_code=direction_code,
        )
    )
    if fee_direction == "PROMOTION":
        issued_total = session.scalar(
            select(func.coalesce(func.sum(PromotionInvoiceAllocation.allocated_amount_cent), 0))
            .join(
                PromotionInvoice,
                PromotionInvoice.invoice_id == PromotionInvoiceAllocation.invoice_id,
            )
            .join(
                SettlementStatement,
                SettlementStatement.statement_id == PromotionInvoiceAllocation.statement_id,
            )
            .where(
                *statement_conditions,
                PromotionInvoiceAllocation.is_current.is_(True),
                PromotionInvoice.is_current.is_(True),
                PromotionInvoice.invoice_status.in_((2, 3)),
            )
        )
        settled_total = session.scalar(
            select(func.coalesce(func.sum(PromotionInvoiceAllocation.allocated_amount_cent), 0))
            .join(
                PromotionInvoice,
                PromotionInvoice.invoice_id == PromotionInvoiceAllocation.invoice_id,
            )
            .join(
                SettlementStatement,
                SettlementStatement.statement_id == PromotionInvoiceAllocation.statement_id,
            )
            .where(
                *statement_conditions,
                PromotionInvoiceAllocation.is_current.is_(True),
                PromotionInvoice.is_current.is_(True),
                PromotionInvoice.invoice_status == 3,
            )
        )
    else:
        issued_total = session.scalar(
            select(func.coalesce(func.sum(InvoiceRecord.invoice_amount_cent), 0))
            .join(
                SettlementStatement,
                SettlementStatement.statement_id == InvoiceRecord.statement_id,
            )
            .where(
                *statement_conditions,
                InvoiceRecord.is_current.is_(True),
                InvoiceRecord.fee_direction == direction_code,
                InvoiceRecord.invoice_status == 3,
            )
        )
        settled_total = session.scalar(
            select(func.coalesce(func.sum(InvoiceRecord.invoice_amount_cent), 0))
            .join(
                SettlementStatement,
                SettlementStatement.statement_id == InvoiceRecord.statement_id,
            )
            .where(
                *statement_conditions,
                InvoiceRecord.is_current.is_(True),
                InvoiceRecord.fee_direction == direction_code,
                InvoiceRecord.invoice_status == 3,
            )
        )

    confirmed_amount = int(monthly_confirmation_total or 0)
    pending_confirmation_amount = int(pending_confirmation_total or 0)
    issued_amount = int(issued_total or 0)
    return {
        "statement_total_cent": int(statement_total or 0),
        "confirmed_amount_cent": confirmed_amount,
        "pending_invoice_amount_cent": max(pending_confirmation_amount - issued_amount, 0),
        "issued_amount_cent": issued_amount,
        "settled_or_deducted_amount_cent": int(settled_total or 0),
    }


def _finance_confirmation_total(session, *, statement_conditions: list, direction_code: int) -> int:
    return int(
        session.scalar(
            select(
                func.coalesce(
                    func.sum(SettlementStatementConfirmation.confirmed_amount_cent), 0
                )
            )
            .join(
                SettlementStatement,
                SettlementStatement.statement_id
                == SettlementStatementConfirmation.statement_id,
            )
            .where(
                *statement_conditions,
                SettlementStatementConfirmation.fee_direction == direction_code,
                SettlementStatementConfirmation.confirmation_status == 1,
            )
        )
        or 0
    )


def _statement_header_item(session, statement: SettlementStatement) -> dict:
    store = session.get(DimStore, statement.store_id)
    confirmations = {
        row.fee_direction: row
        for row in session.scalars(
            select(SettlementStatementConfirmation).where(
                SettlementStatementConfirmation.statement_id == statement.statement_id
            )
        )
    }
    invoices = {
        row.fee_direction: row
        for row in session.scalars(
            select(InvoiceRecord).where(
                InvoiceRecord.statement_id == statement.statement_id,
                InvoiceRecord.is_current.is_(True),
            )
        )
    }
    return {
        "statement_id": statement.statement_id,
        "store_id": statement.store_id,
        "store_name": store.store_name if store is not None else None,
        "month": statement.statement_month,
        "version_no": statement.version_no,
        "is_current": statement.is_current,
        "supersedes_statement_id": statement.supersedes_statement_id,
        "status": STATEMENT_STATUS_NAMES[statement.statement_status],
        "promotion_amount_cent": statement.promotion_net_fee_cent,
        "management_amount_cent": statement.management_net_fee_cent,
        "promotion_confirmation": _confirmation_summary(confirmations.get(1)),
        "management_confirmation": _confirmation_summary(confirmations.get(2)),
        "promotion_invoice_status": _invoice_status(invoices.get(1)),
        "management_invoice_status": _invoice_status(invoices.get(2)),
    }


def _confirmation_summary(
    confirmation: SettlementStatementConfirmation | None,
) -> dict | None:
    if confirmation is None:
        return None
    return {
        "confirmation_id": confirmation.confirmation_id,
        "status": CONFIRMATION_STATUS_NAMES[confirmation.confirmation_status],
        "confirmed_amount_cent": confirmation.confirmed_amount_cent,
        "confirmed_at": confirmation.confirmed_at,
    }


def _invoice_status(invoice: InvoiceRecord | None) -> str:
    return INVOICE_STATUS_NAMES[invoice.invoice_status] if invoice else "PENDING_INVOICE"


def _statement_version_item(statement: SettlementStatement) -> dict:
    return {
        "statement_id": statement.statement_id,
        "version_no": statement.version_no,
        "is_current": statement.is_current,
        "supersedes_statement_id": statement.supersedes_statement_id,
        "status": STATEMENT_STATUS_NAMES[statement.statement_status],
        "created_at": statement.created_at,
    }


def _statement_line_item(line: SettlementStatementLine) -> dict:
    return {
        "statement_line_id": line.statement_line_id,
        "fee_direction": CONFIRMATION_DIRECTION_FROM_DB[line.fee_direction],
        "product_scope": line.product_scope,
        "product_type": line.product_type,
        "original_entry_count": line.original_entry_count,
        "adjustment_entry_count": line.adjustment_entry_count,
        "original_base_cent": line.original_base_cent,
        "adjustment_base_cent": line.adjustment_base_cent,
        "net_base_cent": line.net_base_cent,
        "original_fee_cent": line.original_fee_cent,
        "adjustment_fee_cent": line.adjustment_fee_cent,
        "net_fee_cent": line.net_fee_cent,
    }


def _parse_confirmation_payload(payload: dict, request: Request) -> dict:
    fee_direction = payload.get("feeDirection")
    confirmed_amount = payload.get("confirmedAmountCent")
    read_version = payload.get("readVersion")
    if not isinstance(fee_direction, str):
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "feeDirection 为必填项",
            field="feeDirection",
        )
    direction = _normalize_billing_direction(fee_direction, request)
    if isinstance(confirmed_amount, bool) or not isinstance(confirmed_amount, int):
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "confirmedAmountCent 必须为整数",
            field="confirmedAmountCent",
        )
    if isinstance(read_version, bool) or not isinstance(read_version, int) or read_version < 1:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "readVersion 必须为正整数",
            field="readVersion",
        )
    return {
        "fee_direction": direction,
        "confirmed_amount_cent": confirmed_amount,
        "read_version": read_version,
    }


def _billing_idempotency_key_hash(value: str | None, request: Request) -> str:
    normalized = (value or "").strip()
    if not 16 <= len(normalized) <= 128:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "Idempotency-Key 长度必须为 16～128",
            field="Idempotency-Key",
        )
    return sha256(normalized.encode("utf-8")).hexdigest()


def _canonical_billing_sha256(value: dict) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _confirmation_item(
    confirmation: SettlementStatementConfirmation, statement: SettlementStatement
) -> dict:
    return {
        "confirmation_id": confirmation.confirmation_id,
        "status": CONFIRMATION_STATUS_NAMES[confirmation.confirmation_status],
        "confirmed_amount_cent": confirmation.confirmed_amount_cent,
        "confirmed_at": confirmation.confirmed_at,
        "statement_id": statement.statement_id,
        "version_no": statement.version_no,
        "is_current": statement.is_current,
    }


def _raise_statement_version_conflict(
    request: Request, statement: SettlementStatement
) -> None:
    _raise_reporting_error(
        request,
        status.HTTP_409_CONFLICT,
        "STATEMENT_VERSION_CONFLICT",
        "账单版本已变化或不是当前版本",
        field="readVersion",
    )


def _invoice_status_db(value: str) -> int:
    return next(key for key, status_name in INVOICE_STATUS_NAMES.items() if status_name == value)


def _promotion_invoice_item(
    invoice: PromotionInvoice, allocation: PromotionInvoiceAllocation
) -> dict:
    return {
        **_promotion_invoice_header_item_from_invoice(invoice),
        "statement_id": allocation.statement_id,
        "statement_month": allocation.statement_month,
        "allocated_amount_cent": allocation.allocated_amount_cent,
    }


def _promotion_invoice_header_item(session, invoice: PromotionInvoice) -> dict:
    allocations = list(session.scalars(select(PromotionInvoiceAllocation).where(
        PromotionInvoiceAllocation.invoice_id == invoice.invoice_id,
        PromotionInvoiceAllocation.is_current.is_(True),
    )))
    return {
        **_promotion_invoice_header_item_from_invoice(invoice),
        "allocations": [{
            "statement_id": allocation.statement_id,
            "statement_month": allocation.statement_month,
            "allocated_amount_cent": allocation.allocated_amount_cent,
        } for allocation in allocations],
    }


def _promotion_invoice_header_item_from_invoice(invoice: PromotionInvoice) -> dict:
    return {
        "invoice_id": invoice.invoice_id,
        "store_id": invoice.store_id,
        "version_no": invoice.version_no,
        "is_current": invoice.is_current,
        "supersedes_invoice_id": invoice.supersedes_invoice_id,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "invoice_amount_cent": invoice.invoice_amount_cent,
        "status": INVOICE_STATUS_NAMES[invoice.invoice_status],
        "registered_at": invoice.registered_at,
    }


def _management_invoice_item(invoice: InvoiceRecord) -> dict:
    return {
        "invoice_id": invoice.invoice_id,
        "store_id": invoice.store_id,
        "statement_id": invoice.statement_id,
        "statement_month": invoice.statement_month,
        "fee_direction": CONFIRMATION_DIRECTION_FROM_DB[invoice.fee_direction],
        "version_no": invoice.version_no,
        "is_current": invoice.is_current,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "invoice_amount_cent": invoice.invoice_amount_cent,
        "status": INVOICE_STATUS_NAMES[invoice.invoice_status],
        "registered_at": _finance_datetime(invoice.registered_at),
        "settled_at": (
            _finance_datetime(invoice.registered_at) if invoice.invoice_status == 3 else None
        ),
    }


def _finance_order_detail_item(
    entry: SettlementStatementEntry, statement: SettlementStatement, direction: str
) -> dict:
    return {
        "statement_entry_id": entry.statement_entry_id,
        "statement_id": statement.statement_id,
        "store_id": statement.store_id,
        "statement_month": statement.statement_month,
        "fee_direction": direction,
        "order_id": entry.order_id,
        "coupon_id": entry.coupon_id,
        "original_business_month": entry.original_business_month,
        "statement_posting_month": entry.statement_posting_month,
        "base_amount_cent": entry.base_amount_cent,
        "fee_amount_cent": entry.fee_amount_cent,
    }


def _normalize_invoice_status(value: str | None, request: Request) -> int | None:
    if value is None:
        return None
    normalized = value.upper()
    _validate_enum(normalized, set(INVOICE_STATUS_NAMES.values()), "invoiceStatus", request)
    return _invoice_status_db(normalized)


def _finance_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _parse_promotion_invoice_payload(payload: dict, request: Request) -> dict:
    store_id = payload.get("storeId")
    invoice_number = payload.get("invoiceNumber")
    invoice_date_value = payload.get("invoiceDate")
    invoice_amount = payload.get("invoiceAmountCent")
    rows = payload.get("allocations")
    if not isinstance(store_id, str) or not store_id.strip():
        _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "storeId 为必填项", field="storeId")
    if not isinstance(invoice_number, str) or not invoice_number.isdigit() or len(invoice_number) != 20:
        _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "invoiceNumber 必须为 20 位数字", field="invoiceNumber")
    try:
        parsed_date = date.fromisoformat(invoice_date_value) if isinstance(invoice_date_value, str) else None
    except ValueError:
        parsed_date = None
    if parsed_date is None:
        _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "invoiceDate 必须为 YYYY-MM-DD", field="invoiceDate")
    if isinstance(invoice_amount, bool) or not isinstance(invoice_amount, int) or invoice_amount < 0:
        _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "invoiceAmountCent 必须为非负整数", field="invoiceAmountCent")
    if not isinstance(rows, list) or not rows:
        _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "allocations 至少包含一个完整账期", field="allocations")
    allocations = []
    seen_months = set()
    for item in rows:
        if not isinstance(item, dict):
            _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "allocations 元素必须为对象", field="allocations")
        statement_id, statement_month = item.get("statementId"), item.get("statementMonth")
        allocated, read_version = item.get("allocatedAmountCent"), item.get("readVersion")
        if not isinstance(statement_id, str) or not isinstance(statement_month, str):
            _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "分配必须包含 statementId 和 statementMonth", field="allocations")
        _validate_month(statement_month, "statementMonth", request)
        if statement_month in seen_months:
            _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "同一账期不得拆分多张发票", field="allocations")
        seen_months.add(statement_month)
        if isinstance(allocated, bool) or not isinstance(allocated, int) or allocated < 0 or isinstance(read_version, bool) or not isinstance(read_version, int) or read_version < 1:
            _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "分配金额和 readVersion 不合法", field="allocations")
        allocations.append({"statement_id": statement_id, "statement_month": statement_month, "allocated_amount_cent": allocated, "read_version": read_version})
    if sum(item["allocated_amount_cent"] for item in allocations) != invoice_amount:
        _raise_reporting_error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "分配金额合计必须等于发票金额", field="invoiceAmountCent")
    return {"store_id": store_id.strip(), "invoice_number": invoice_number, "invoice_date": parsed_date, "invoice_amount_cent": invoice_amount, "allocations": allocations}


def _call_reporting_store(request: Request, operation, filters: dict):
    try:
        return operation(filters)
    except ReportingPermissionError as exc:
        _raise_reporting_error(
            request,
            status.HTTP_403_FORBIDDEN,
            "DATA_SCOPE_FORBIDDEN",
            str(exc),
        )
    except ReportingValidationError as exc:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            str(exc),
            field=exc.field,
        )


def _raise_reporting_error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    field: str | None = None,
) -> None:
    errors = [] if field is None else [{"field": field, "reason": message}]
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "errors": errors,
            "requestId": request_id(request),
        },
    )


def _validate_enum(
    value: str, allowed: set[str], field: str, request: Request
) -> None:
    if value not in allowed:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            f"{field} 必须是 {', '.join(sorted(allowed))} 之一",
            field=field,
        )


def _validate_month(value: str, field: str, request: Request) -> None:
    if len(value) != 7 or value[4:5] != "-" or not value[:4].isdigit() or not value[5:].isdigit():
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            f"{field} 必须使用 YYYY-MM 格式",
            field=field,
        )
    month_number = int(value[5:])
    if month_number < 1 or month_number > 12:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            f"{field} 月份必须在 01 到 12 之间",
            field=field,
        )


def _validate_product_selection(
    store, product_scope: str, product_type: str, request: Request
) -> None:
    scope_map = getattr(store, "product_scope_type_map", lambda: {})()
    available_types = set(getattr(store, "list_product_types", lambda: ["all"])())
    if product_scope != "all" and product_scope not in scope_map:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "productScope 不在可用产品范围内",
            field="productScope",
        )
    if product_type == "all":
        return
    allowed_types = (
        available_types if product_scope == "all" else set(scope_map.get(product_scope, []))
    )
    if product_type not in allowed_types:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "productType 不属于所选 productScope",
            field="productType",
        )


def _validate_monthly_context(
    store, store_id: str, month: str, request: Request
) -> None:
    store_exists = getattr(store, "store_exists", lambda _store_id: True)
    if not store_exists(store_id):
        _raise_reporting_error(
            request,
            status.HTTP_404_NOT_FOUND,
            "RESOURCE_NOT_FOUND",
            "门店不存在",
            field="storeId",
        )
    context_exists = getattr(
        store,
        "monthly_settlement_context_exists",
        lambda _store_id, _month: True,
    )
    if not context_exists(store_id, month):
        _raise_reporting_error(
            request,
            status.HTTP_404_NOT_FOUND,
            "RESOURCE_NOT_FOUND",
            "门店账期不存在",
            field="month",
        )


def _order_fee_filters(
    *,
    request: Request,
    store,
    current_user: AuthContext,
    statement_id: str | None,
    statement_line_id: str | None,
    store_id: str | None,
    month: str | None,
    sale_month: str | None,
    verify_month: str | None,
    fee_direction: str,
    product_scope: str,
    product_type: str,
    fee_rates: list[str] | None,
    rule_versions: list[str] | None,
    data_status: str | None,
    q: str | None,
    page: int,
    page_size: int,
) -> dict:
    statement_id = (statement_id or "").strip() or None
    statement_line_id = (statement_line_id or "").strip() or None
    store_id = (store_id or "").strip() or None
    month = (month or "").strip() or None
    if statement_line_id and not statement_id:
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "statementLineId 必须与 statementId 同时提供",
            field="statementLineId",
        )
    if statement_id:
        if not statement_line_id:
            _raise_reporting_error(
                request,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "VALIDATION_FAILED",
                "statementId 存在时 statementLineId 必填",
                field="statementLineId",
            )
        if store_id or month:
            _raise_reporting_error(
                request,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "VALIDATION_FAILED",
                "锁账明细上下文不能与门店月份上下文混用",
                field="storeId" if store_id else "month",
            )
    if store_id:
        _require_store_scope(current_user, store_id)
    if month:
        _validate_month(month, "month", request)
    if store_id and month:
        _validate_monthly_context(store, store_id, month, request)
    if sale_month:
        _validate_month(sale_month, "saleMonth", request)
    if verify_month:
        _validate_month(verify_month, "verifyMonth", request)
    fee_direction = fee_direction.upper()
    _validate_enum(fee_direction, FEE_DIRECTIONS, "feeDirection", request)
    normalized_data_status = data_status.upper() if data_status else None
    if normalized_data_status:
        _validate_enum(normalized_data_status, DATA_STATUSES, "dataStatus", request)
    _validate_product_selection(store, product_scope, product_type, request)
    has_source_context = bool(statement_id and statement_line_id) or bool(
        store_id and month
    )
    return {
        "statement_id": statement_id,
        "statement_line_id": statement_line_id,
        "store_id": store_id,
        "month": month,
        "sale_month": sale_month,
        "verify_month": verify_month,
        "fee_direction": fee_direction,
        "product_scope": product_scope,
        "product_type": product_type,
        "fee_rates": (fee_rates or []) if has_source_context else [],
        "rule_versions": (rule_versions or []) if has_source_context else [],
        "data_status": normalized_data_status,
        "q": (q or "").strip() or None,
        "page": page,
        "page_size": page_size,
        "scope_store_ids": (
            None if current_user.has_global_data_access else current_user.store_ids
        ),
    }


def _require_store_scope(current_user: AuthContext, store_id: str) -> None:
    if current_user.has_global_data_access:
        return
    if store_id not in current_user.store_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Store is outside current account scope",
        )


def _resolve_sales_dashboard_store_id(
    current_user: AuthContext, store_id: str | None
) -> str | None:
    normalized_store_id = (store_id or "").strip()
    if normalized_store_id:
        _require_store_scope(current_user, normalized_store_id)
        return normalized_store_id
    if current_user.has_global_data_access:
        return None
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Store is required for current account scope",
    )
