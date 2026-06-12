from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from dy_api.auth import get_current_admin
from dy_api.routes._data import get_data_store, generated_at


router = APIRouter()


@router.get("/jobs/recent")
def recent_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    return {
        "data": {"rows": store.recent_jobs(limit)},
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }
