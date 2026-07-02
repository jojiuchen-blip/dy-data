from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import get_data_store, generated_at, with_utf8_bom
from dy_api.schemas import (
    ClueAssignmentRoundData,
    ClueFilterMetadata,
    ClueFollowUpRequest,
    ClueFollowUpResponseData,
    ClueOverviewMetrics,
    ClueOrderDetailData,
    CluePhoneRevealData,
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


def _scope_store_ids(current_user: AuthContext) -> tuple[str, ...] | None:
    return None if current_user.has_global_data_access else current_user.store_ids


def _operation_actor(current_user: AuthContext) -> dict:
    return {
        "role": current_user.role,
        "store_ids": current_user.store_ids,
        "user_id": current_user.user_id,
        "username": current_user.username,
    }


@router.get("/clues/filters")
def clue_filters(
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = ClueFilterMetadata(**store.clue_filters(_scope_store_ids(current_user)))
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
    store_display_status: str | None = None,
    round_status: str | None = None,
    product_type: str | None = None,
    province: str | None = None,
    city: str | None = None,
    verification_status: str | None = None,
    current_user: AuthContext = Depends(get_current_user),
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
                "store_display_status": store_display_status,
                "round_status": round_status,
                "product_type": product_type,
                "province": province,
                "city": city,
                "verification_status": verification_status,
                "scope_store_ids": _scope_store_ids(current_user),
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
    store_display_status: str | None = None,
    round_status: str | None = None,
    product_type: str | None = None,
    province: str | None = None,
    city: str | None = None,
    verification_status: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: AuthContext = Depends(get_current_user),
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
                "store_display_status": store_display_status,
                "round_status": round_status,
                "product_type": product_type,
                "province": province,
                "city": city,
                "verification_status": verification_status,
                "q": q,
                "page": page,
                "page_size": page_size,
                "scope_store_ids": _scope_store_ids(current_user),
            }
        )
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clues/orders/{order_id}")
def clue_order_detail(
    order_id: str,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    payload = store.clue_order_detail(order_id, _scope_store_ids(current_user))
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


@router.get("/clues/assignment-rounds/export")
def clue_assignment_rounds_export(
    assigned_store_id: str | None = None,
    assigned_date_start: str | None = None,
    assigned_date_end: str | None = None,
    lead_status: str | None = None,
    store_display_status: str | None = None,
    round_status: str | None = None,
    product_type: str | None = None,
    province: str | None = None,
    city: str | None = None,
    verification_status: str | None = None,
    q: str | None = None,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    filters = {
        "assigned_store_id": assigned_store_id,
        "assigned_date_start": assigned_date_start,
        "assigned_date_end": assigned_date_end,
        "lead_status": lead_status,
        "store_display_status": store_display_status,
        "round_status": round_status,
        "product_type": product_type,
        "province": province,
        "city": city,
        "verification_status": verification_status,
        "q": q,
        "scope_store_ids": _scope_store_ids(current_user),
    }
    generated = generated_at().isoformat()
    filename = quote(f"clue-assignment-rounds-{generated[:10]}.csv")
    return Response(
        content=with_utf8_bom(store.clue_assignment_rounds_export_csv(filters)),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Export-Generated-At": generated,
            "X-Export-Filters": store.export_filter_header(filters),
        },
    )


@router.post("/clues/orders/{order_id}/follow-up")
def clue_order_follow_up(
    order_id: str,
    payload: ClueFollowUpRequest,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    result_status, record = store.save_clue_follow_up(
        order_id,
        dump_model(payload),
        _operation_actor(current_user),
    )
    if result_status == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current clue round is not writable",
        )
    if result_status == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clue order not found",
        )
    if result_status == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Current clue round is not active",
        )
    data = ClueFollowUpResponseData(**(record or {}))
    store.session.commit()
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.delete("/clues/follow-up-records/{follow_up_record_id}")
def delete_clue_follow_up_record(
    follow_up_record_id: str,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    store = _require_available_store(store)
    result_status, record = store.delete_clue_follow_up_record(follow_up_record_id)
    if result_status == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Follow-up record not found",
        )
    data = ClueFollowUpResponseData(**(record or {}))
    store.session.commit()
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clues/orders/{order_id}/phone")
def clue_order_phone(
    order_id: str,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    payload = store.clue_order_phone(order_id, _operation_actor(current_user))
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clue phone not found",
        )
    data = CluePhoneRevealData(**payload)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }
