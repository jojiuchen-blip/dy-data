from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from dy_api.routes._data import get_data_store, generated_at
from dy_api.schemas import (
    ClueAssignmentRoundData,
    ClueFilterMetadata,
    ClueOverviewMetrics,
    ClueOrderDetailData,
    dump_model,
)


router = APIRouter()


def _require_available_store(store):
    if not store.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    return store


@router.get("/clues/filters")
def clue_filters(store=Depends(get_data_store)):
    store = _require_available_store(store)
    data = ClueFilterMetadata(**store.clue_filters())
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clues/overview")
def clue_overview(
    assigned_store_id: str | None = None,
    assigned_date_start: str | None = None,
    assigned_date_end: str | None = None,
    lead_status: str | None = None,
    round_status: str | None = None,
    product_type: str | None = None,
    city: str | None = None,
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = ClueOverviewMetrics(
        **store.clue_overview(
            {
                "assigned_store_id": assigned_store_id,
                "assigned_date_start": assigned_date_start,
                "assigned_date_end": assigned_date_end,
                "lead_status": lead_status,
                "round_status": round_status,
                "product_type": product_type,
                "city": city,
            }
        )
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clues/assignment-rounds")
def clue_assignment_rounds(
    assigned_store_id: str | None = None,
    assigned_date_start: str | None = None,
    assigned_date_end: str | None = None,
    lead_status: str | None = None,
    round_status: str | None = None,
    product_type: str | None = None,
    city: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = ClueAssignmentRoundData(
        **store.clue_assignment_rounds(
            {
                "assigned_store_id": assigned_store_id,
                "assigned_date_start": assigned_date_start,
                "assigned_date_end": assigned_date_end,
                "lead_status": lead_status,
                "round_status": round_status,
                "product_type": product_type,
                "city": city,
                "q": q,
                "page": page,
                "page_size": page_size,
            }
        )
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clues/orders/{order_id}")
def clue_order_detail(order_id: str, store=Depends(get_data_store)):
    store = _require_available_store(store)
    payload = store.clue_order_detail(order_id)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clue order not found",
        )
    data = ClueOrderDetailData(**payload)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }
