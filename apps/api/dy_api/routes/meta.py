from __future__ import annotations

from fastapi import APIRouter, Depends

from dy_api.routes._data import get_data_store, generated_at
from dy_api.schemas import FilterMetadata, dump_model


router = APIRouter()


@router.get("/meta/filters")
def filters(
    store=Depends(get_data_store),
):
    data = FilterMetadata(
        stores=store.list_stores(),
        product_types=store.list_product_types(),
        sale_months=store.list_sale_months(),
        verify_months=store.list_verify_months(),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }
