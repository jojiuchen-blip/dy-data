"""Highest-administrator-only observation endpoint; no production sync side effects."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dy_api.auth import get_current_super_admin
from dy_api.ranking_source_evidence import read_source_page
from dy_api.routes._data import get_session_dependency

router = APIRouter()


@router.get("/ranking-source-evidence")
def ranking_source_evidence(
    dataset: str,
    period_start: date = Query(alias="periodStart"),
    period_end: date = Query(alias="periodEnd"),
    observed_through: datetime = Query(alias="observedThrough"),
    page_size: int = Query(default=500, ge=1, le=500, alias="pageSize"),
    cursor: str | None = Query(default=None, max_length=2048),
    _username: str = Depends(get_current_super_admin),
    session=Depends(get_session_dependency),
):
    if session is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET LOCAL statement_timeout = '8s'"))
            session.execute(text("SET LOCAL lock_timeout = '1s'"))
        return read_source_page(session, dataset=dataset, period_start=period_start,
            period_end=period_end, observed_through=observed_through, page_size=page_size, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DBAPIError as exc:
        # Never expose SQL, connection details or source values in public errors.
        raise HTTPException(status_code=503, detail="Source query unavailable; retry with a smaller range") from exc
