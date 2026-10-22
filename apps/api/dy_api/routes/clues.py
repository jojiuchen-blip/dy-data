from __future__ import annotations

from urllib.parse import quote

from apps.api.dy_api.clue_organization import organization_options, organization_filter_store_ids

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from apps.api.dy_api.models import ClueMasterLead
from apps.api.dy_api.clue_store_filters import (
    ClueExportQueryRequest, ClueQueryRequest, ClueStoreResolveRequest,
    resolve_store_identifiers,
)

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import get_data_store, generated_at, with_utf8_bom
from dy_api.routes._publications import attach_publication, publication_read
from dy_api.schemas import (
    ClueAssignmentRoundData,
    ClueFilterMetadata,
    ClueFollowUpRequest,
    ClueFollowUpResponseData,
    ClueOverviewMetrics,
    ClueOrderDetailData,
    CluePhoneRevealData,
    ClueStoreOptionsData,
    ClueOrganizationOptionsData,
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
    if current_user.has_global_data_access and current_user.is_admin:
        return None
    return current_user.store_ids if current_user.store_scope_mode == "specified" else ()


def _published_clue_access(store) -> dict:
    # These are current access restrictions, deliberately not frozen with the
    # analytical facts: returning a lead to headquarters revokes access now.
    return {
        "visible_product_types": store._visible_product_types(),
        "current_headquarters_order_ids": select(ClueMasterLead.order_id).where(
            ClueMasterLead.lifecycle_status == "active",
            ClueMasterLead.pool_location == "headquarters_pool",
            ClueMasterLead.order_id.is_not(None),
        ),
    }


def _operation_actor(current_user: AuthContext) -> dict:
    return {
        "role": "admin" if current_user.is_highest_admin else current_user.role,
        "store_ids": current_user.store_ids,
        "store_scope_mode": current_user.store_scope_mode,
        "user_id": current_user.user_id,
        "username": current_user.username,
        "auth_type": current_user.auth_type,
        "is_highest_admin": current_user.is_highest_admin,
    }


@router.get("/clues/filters")
def clue_filters(
    include_assigned_stores: bool = True,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = ClueFilterMetadata(
        **store.clue_filters(
            _scope_store_ids(current_user),
            include_assigned_stores=include_assigned_stores,
        )
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clues/filter-options/stores")
def clue_store_filter_options(
    q: str | None = None,
    province: str | None = None,
    city: str | None = None,
    selected_store_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    publication_id: str | None = Query(default=None, max_length=64),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    if publication_id is not None:
        from apps.api.dy_api.dashboard_publications.clues import read_store_options
        with publication_read(store.session, "clue-overview", publication_id) as publication:
            result = read_store_options(store.session, publication.id,
                q=q, province=province, city=city, selected_store_id=selected_store_id,
                limit=limit, scope_store_ids=_scope_store_ids(current_user), **_published_clue_access(store))
        return attach_publication({"data": dump_model(ClueStoreOptionsData(**result)),
            "meta": {"generated_at": generated_at(), "source": "postgres"}}, publication)
    data = ClueStoreOptionsData(
        stores=store.clue_store_options(
            _scope_store_ids(current_user),
            q=q,
            province=province,
            city=city,
            selected_store_id=selected_store_id,
            limit=limit,
        )
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


def _organization_scope(store, user, org_level, org_key):
    try:
        selected = organization_filter_store_ids(store.session, _scope_store_ids(user),
            level=org_level, key=org_key)
        return selected if org_key else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/clues/filter-options/stores/resolve")
def clue_store_resolve(
    payload: ClueStoreResolveRequest,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    """Preview exact authorized account/POI matches without changing data."""
    store = _require_available_store(store)
    try:
        data = resolve_store_identifiers(store.session, payload.raw_input, _scope_store_ids(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "CLUE_STORE_FILTER_LIMIT", "message": str(exc)}) from exc
    return {"data": data, "meta": {"generated_at": generated_at(), "source": "postgres"}}


def _posted_clue_filters(payload, current_user, store):
    filters = payload.filters.model_dump()
    org_level = filters.pop("org_level")
    org_key = filters.pop("org_key")
    filters["scope_store_ids"] = _scope_store_ids(current_user)
    filters["organization_store_ids"] = _organization_scope(store, current_user, org_level, org_key)
    return filters


@router.post("/clues/assignment-rounds")
def clue_assignment_rounds_query(
    payload: ClueQueryRequest,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    """Query the live list with bounded JSON selections and current authorization."""
    store = _require_available_store(store)
    filters = _posted_clue_filters(payload, current_user, store)
    filters.update(page=payload.page, page_size=payload.page_size)
    data = ClueAssignmentRoundData(**store.clue_assignment_rounds(filters, _operation_actor(current_user)))
    return {"data": dump_model(data), "meta": {"generated_at": generated_at(), "source": "postgres"}}


@router.post("/clues/assignment-rounds/export")
def clue_assignment_rounds_export_query(
    payload: ClueExportQueryRequest,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    """Export the identical authorized selection without pagination or URL limits."""
    store = _require_available_store(store)
    return _clue_export_response(_posted_clue_filters(payload, current_user, store), current_user, store)


@router.get("/clues/filter-options/organizations")
def clue_organization_options(
    level: str, q: str = "", selected_key: str = "",
    limit: int = Query(default=50, ge=1, le=100),
    publication_id: str | None = Query(default=None, max_length=64),
    current_user: AuthContext = Depends(get_current_user), store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        if publication_id is not None:
            from apps.api.dy_api.dashboard_publications.clues import read_organization_options
            with publication_read(store.session, "clue-overview", publication_id) as publication:
                options = read_organization_options(store.session, publication.id, _scope_store_ids(current_user),
                    level=level, q=q.strip(), selected_key=selected_key, limit=limit)
            return attach_publication({"data": dump_model(ClueOrganizationOptionsData(options=options)),
                "meta": {"generated_at": generated_at(), "source": "postgres"}}, publication)
        options = organization_options(store.session, _scope_store_ids(current_user),
            level=level, q=q.strip(), selected_key=selected_key, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": dump_model(ClueOrganizationOptionsData(options=options)), "meta": {"generated_at": generated_at(), "source": "postgres"}}


@router.get("/clues/overview")
def clue_overview(
    assigned_store_id: str | None = None,
    assigned_date_start: str | None = None,
    assigned_date_end: str | None = None,
    lead_status: str | None = None,
    store_display_status: str | None = None,
    round_status: str | None = None,
    product_type: str | None = None,
    org_level: str = "all",
    org_key: str = "",
    province: str | None = None,
    city: str | None = None,
    verification_status: str | None = None,
    publication_id: str | None = Query(default=None, max_length=64),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    from apps.api.dy_api.dashboard_publications.clues import read, organization_scope_store_ids
    with publication_read(store.session, "clue-overview", publication_id) as publication:
        try:
            org_scope = organization_scope_store_ids(store.session, publication.id, _scope_store_ids(current_user),
                level=org_level, key=org_key)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        data = ClueOverviewMetrics(**read(store.session, publication.id, {
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
                "organization_store_ids": org_scope,
            }, **_published_clue_access(store)))
    return attach_publication({
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }, publication)


@router.get("/clues/assignment-rounds")
def clue_assignment_rounds(
    assigned_store_id: str | None = None,
    assigned_date_start: str | None = None,
    assigned_date_end: str | None = None,
    lead_status: str | None = None,
    store_display_status: str | None = None,
    round_status: str | None = None,
    product_type: str | None = None,
    org_level: str = "all",
    org_key: str = "",
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
                "organization_store_ids": _organization_scope(store, current_user, org_level, org_key),
            }
            ,
            _operation_actor(current_user),
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
    payload = store.clue_order_detail(
        order_id,
        _scope_store_ids(current_user),
        _operation_actor(current_user),
    )
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
    org_level: str = "all",
    org_key: str = "",
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
        "organization_store_ids": _organization_scope(store, current_user, org_level, org_key),
    }
    return _clue_export_response(filters, current_user, store)


def _clue_export_response(filters, current_user, store):
    generated = generated_at().isoformat()
    filename = quote(f"clue-assignment-rounds-{generated[:10]}.csv")
    return Response(
        content=with_utf8_bom(
            store.clue_assignment_rounds_export_csv(
                filters,
                _operation_actor(current_user),
            )
        ),
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
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    store = _require_available_store(store)
    result_status, record = store.delete_clue_follow_up_record(
        follow_up_record_id,
        _operation_actor(current_user),
    )
    if result_status == "forbidden":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    if result_status == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Follow-up record not found",
        )
    if result_status == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Follow-up record has already been deleted",
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
