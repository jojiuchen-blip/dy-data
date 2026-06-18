from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import get_data_store, generated_at
from dy_api.schemas import (
    CommissionRulesSummaryData,
    MonthlySettlementData,
    OrderDetailsData,
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
        content=store.order_details_export_csv(filters),
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
