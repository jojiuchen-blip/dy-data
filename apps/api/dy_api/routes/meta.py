from __future__ import annotations

from fastapi import APIRouter, Depends

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import get_data_store, generated_at
from dy_api.schemas import FilterMetadata, dump_model


router = APIRouter()


@router.get("/meta/filters")
def filters(
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    scope_store_ids = None if current_user.has_global_data_access else current_user.store_ids
    data = FilterMetadata(
        stores=store.list_stores(scope_store_ids=scope_store_ids),
        product_types=store.list_product_types(),
        sale_months=store.list_sale_months(),
        verify_months=store.list_verify_months(),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }
