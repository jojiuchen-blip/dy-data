from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from dy_api.routes._data import get_data_store, generated_at
from dy_api.schemas import (
    MonthlySettlementData,
    OrderDetailsData,
    StoreRankingData,
    dump_model,
)


router = APIRouter()


STORE_RANKING_DEFINITIONS = [
    {
        "key": "sales_order_count",
        "label": "Sales orders",
        "description": "Distinct order count by sale ownership store.",
    },
    {
        "key": "effective_commission_income_cent",
        "label": "Estimated receivable commission",
        "description": "Estimated commission for this store's sales verified by other stores.",
    },
]

MONTHLY_SETTLEMENT_DEFINITIONS = [
    {
        "key": "estimated_receivable_commission_cent",
        "label": "Estimated receivable commission",
        "description": "Estimated commission from this store's sales verified by other stores.",
    },
    {
        "key": "commissionable_total_cent",
        "label": "Commissionable total",
        "description": "Eligible paid amount for cross-store commission in the verify month.",
    },
    {
        "key": "estimated_payable_commission_cent",
        "label": "Estimated payable commission",
        "description": "Estimated commission payable for other stores' sales verified here.",
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
    store=Depends(get_data_store),
):
    data = StoreRankingData(
        month=month,
        product_type=product_type,
        limit=limit,
        rows=store.store_ranking(month=month, product_type=product_type, limit=limit),
    )
    return {
        "data": dump_model(data),
        "definitions": STORE_RANKING_DEFINITIONS,
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/stores/{store_id}/monthly-settlement")
def monthly_settlement(
    store_id: str,
    month: str,
    product_type: str = "all",
    store=Depends(get_data_store),
):
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
