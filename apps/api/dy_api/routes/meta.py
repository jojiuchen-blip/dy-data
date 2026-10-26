from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import camelize, generated_at, get_data_store, request_id


router = APIRouter()


def statement_months_with_previous_business_month(
    months: list[str], *, now: datetime | None = None
) -> list[str]:
    """Available billing months, newest first, always including last month.

    The settlement selector is driven by this list.  Listing only months that
    already hold data hides the period the operator must look at first (the
    previous Shanghai business month), so that month is always present even
    while it is still empty.
    """

    # Local import keeps the API startup path free of worker import cost.
    from apps.worker.month_close import previous_business_month

    merged = {value for value in months if isinstance(value, str) and value}
    merged.add(previous_business_month(now))
    return sorted(merged, reverse=True)


@router.get("/meta/filters")
def filters(
    request: Request,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    scope_store_ids = None if current_user.has_global_data_access else current_user.store_ids
    default_product_type = getattr(store, "default_product_type", lambda: "all")()
    list_statement_months = getattr(
        store, "list_statement_months", store.list_sale_months
    )
    data = {
        "stores": store.list_stores(scope_store_ids=scope_store_ids),
        "product_scopes": ["all"],
        "product_scope_type_map": {},
        "product_types": (
            store.list_product_types() if scope_store_ids is None
            else store.list_product_types(scope_store_ids=scope_store_ids)
        ),
        "default_product_type": default_product_type,
        "sale_months": store.list_sale_months(),
        "verify_months": store.list_verify_months(),
        "statement_months": statement_months_with_previous_business_month(
            list_statement_months()
        ),
        "period_types": ["MONTHLY", "CUMULATIVE"],
        "fee_directions": ["PROMOTION", "MANAGEMENT"],
        "formal_period_start_month": "2026-08",
        "timezone": "Asia/Shanghai",
    }
    return {
        "data": camelize(data),
        "meta": {
            "generatedAt": generated_at(),
            "source": "postgres",
            "requestId": request_id(request),
        },
    }
