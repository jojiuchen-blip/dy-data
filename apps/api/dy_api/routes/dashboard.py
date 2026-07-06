from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import get_data_store, generated_at, with_utf8_bom
from dy_api.schemas import (
    CommissionRulesSummaryData,
    MonthlySettlementData,
    OrderDetailsData,
    SalesDashboardData,
    StoreRankingData,
    dump_model,
)


router = APIRouter()


STORE_RANKING_DEFINITIONS = [
    {
        "key": "sales_order_count",
        "label": "销售订单数量",
        "description": "按订单归属的销售门店统计。顶部数字是当前筛选条件下全国门店的订单合计；表格每行是该门店的订单数，订单是否已核销不影响这个数字。",
    },
    {
        "key": "self_sold_self_verified_count",
        "label": "本店卖本店核销",
        "description": "券由该门店卖出，也在该门店核销。这个数字用来看本店销售后回到本店消费的数量。",
    },
    {
        "key": "self_sold_other_verified_count",
        "label": "本店卖他店核销",
        "description": "券由该门店卖出，但顾客到其他门店核销。通常这类核销会产生该门店预计可收到的分佣。",
    },
    {
        "key": "other_sold_self_verified_count",
        "label": "他店卖本店核销",
        "description": "券由其他门店卖出，但顾客到该门店核销。通常这类核销会产生该门店预计需要分出的分佣。",
    },
    {
        "key": "self_verify_income_cent",
        "label": "核销收入",
        "description": "按实际核销门店统计。顶部数字是当前筛选条件下全国门店的核销收入合计；表格每行是该门店作为核销门店确认的收入。",
    },
    {
        "key": "effective_commission_income_cent",
        "label": "有效分佣收入",
        "description": "销售门店卖出的券在其他门店核销时，销售门店按分佣规则预计可以收到的金额。顶部数字是当前筛选条件下全国门店合计；表格每行是该门店预计可收到的金额。",
    },
]

MONTHLY_SETTLEMENT_DEFINITIONS = [
    {
        "key": "estimated_receivable_commission_cent",
        "label": "预计应收分佣",
        "description": "本店卖出的券在其他门店核销时，本店按分佣规则预计可以收到的金额。这是按当前规则测算的参考额。",
    },
    {
        "key": "estimated_payable_commission_cent",
        "label": "本店预计分出分佣参考额",
        "description": "其他门店卖出的券在本店核销时，本店按分佣规则预计需要分给销售门店的金额。这是按当前规则测算的参考额。",
    },
]

SALES_DASHBOARD_DEFINITIONS = [
    {
        "key": "total_sales_order_count",
        "label": "总销售订单量",
        "description": "销售归属门店在所选期间卖出的有效订单数，按 order_id 去重，剔除 is_refund_excluded=true 的记录。",
    },
    {
        "key": "self_verify_order_count",
        "label": "自店核销数",
        "description": "销售归属门店和实际核销门店都是当前门店的订单数，按 order_id 去重，剔除退款剔除记录。",
    },
    {
        "key": "self_verify_rate",
        "label": "自店核销率",
        "description": "自店核销数 / 总销售订单量；总销售订单量为 0 时显示 0。",
    },
    {
        "key": "total_verify_order_count",
        "label": "实际核销总数",
        "description": "不管销售归属门店，只要在当前门店于所选期间完成核销即计入，按 order_id 去重；一单核销多券也只算一单。",
    },
    {
        "key": "actual_verify_amount_cent",
        "label": "实际核销金额",
        "description": "当前门店产生核销后的实收金额合计，剔除 is_refund_excluded=true 的记录。",
    },
    {
        "key": "avg_verify_cycle_days",
        "label": "平均核销周期",
        "description": "当前门店已核销订单从 sale_time 到 verify_time 的平均天数，按订单去重。",
    },
    {
        "key": "cycle_distribution",
        "label": "核销周期分布",
        "description": "按商品类型展示当前门店核销订单从 sale_time 到 verify_time 的周期，箱线图展示四分位，散点展示订单样本。",
    },
]


def _filters_from_query(
    *,
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
    month: str,
    product_type: str = "all",
    limit: int = Query(default=20, ge=1, le=500),
    _current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    data = StoreRankingData(
        month=month,
        product_type=product_type,
        limit=limit,
        totals=store.store_ranking_totals(month=month, product_type=product_type),
        rows=store.store_ranking(month=month, product_type=product_type, limit=limit),
    )
    return {
        "data": dump_model(data),
        "definitions": STORE_RANKING_DEFINITIONS,
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


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
    store_id: str,
    month: str,
    product_type: str = "all",
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    _require_store_scope(current_user, store_id)
    data = MonthlySettlementData(
        **store.monthly_settlement(
            store_id=store_id, month=month, product_type=product_type
        )
    )
    return {
        "data": dump_model(data),
        "definitions": MONTHLY_SETTLEMENT_DEFINITIONS,
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/dashboard/sales")
def sales_dashboard(
    store_id: str | None = None,
    month: str = "all",
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
