from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

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


router = APIRouter()

FORMAL_PERIOD_START_MONTH = "2026-08"
PERIOD_TYPES = {"MONTHLY", "CUMULATIVE"}
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
    elif not store_id or not month:
        missing_field = "storeId" if not store_id else "month"
        _raise_reporting_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "无 statementId 时 storeId 和 month 均为必填",
            field=missing_field,
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
        "fee_rates": fee_rates or [],
        "rule_versions": rule_versions or [],
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
