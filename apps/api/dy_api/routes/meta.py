from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import camelize, generated_at, get_data_store, request_id


router = APIRouter()


@router.get("/meta/filters")
def filters(
    request: Request,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    scope_store_ids = None if current_user.has_global_data_access else current_user.store_ids
    default_product_type = getattr(store, "default_product_type", lambda: "all")()
    list_product_scopes = getattr(store, "list_product_scopes", lambda: ["all"])
    product_scope_type_map = getattr(store, "product_scope_type_map", lambda: {})
    list_statement_months = getattr(
        store, "list_statement_months", store.list_sale_months
    )
    data = {
        "stores": store.list_stores(scope_store_ids=scope_store_ids),
        "product_scopes": list_product_scopes(),
        "product_scope_type_map": product_scope_type_map(),
        "product_types": store.list_product_types(),
        "default_product_type": default_product_type,
        "sale_months": store.list_sale_months(),
        "verify_months": store.list_verify_months(),
        "statement_months": list_statement_months(),
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
