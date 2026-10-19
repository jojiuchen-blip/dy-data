"""Version-pinned filter metadata for analytical pages."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import camelize, generated_at, get_data_store, request_id
from dy_api.routes._publications import attach_publication, publication_read

router = APIRouter()


@router.get("/dashboard/publications/{module}/filters")
def publication_filters(
    module: str,
    request: Request,
    publication_id: str | None = Query(default=None, max_length=64),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    # get_current_user enforces the module's registered page permission.
    if module not in {"sales", "clue-overview", "settlement", "finance", "douyin-ranking"}:
        raise HTTPException(404, detail="分析模块不存在")
    scope = None if current_user.has_global_data_access else current_user.store_ids
    session = getattr(store, "session", None)
    with publication_read(session, module, publication_id) as publication:
        if module == "sales":
            from apps.api.dy_api.dashboard_publications.sales import read_filters
            data = read_filters(session, publication.id, scope_store_ids=scope,
                visible_product_types=store._visible_product_types())
        elif module == "clue-overview":
            from apps.api.dy_api.dashboard_publications.clues import read_filters
            from dy_api.routes.clues import _scope_store_ids, _published_clue_access
            data = read_filters(session, publication.id, scope_store_ids=_scope_store_ids(current_user),
                include_assigned_stores=False, **_published_clue_access(store))
        elif module in {"settlement", "finance"}:
            from apps.api.dy_api.dashboard_publications.finance import read_filters
            data = read_filters(session, publication.id, module=module, scope_store_ids=scope)
        else:
            from apps.api.dy_api.dashboard_publications.ranking import read_filters
            # A03 intentionally exposes the same full organizational scope as
            # the indicator board and its export.
            data = read_filters(session, publication.id)
    payload = {
        "data": data if module == "clue-overview" else camelize(data),
        "meta": {"generatedAt": generated_at(), "source": "postgres", "requestId": request_id(request)},
    }
    return attach_publication(payload, publication)
