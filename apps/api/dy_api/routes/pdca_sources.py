"""Independent, highest-admin, read-only PDCA evidence endpoint."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from dy_api.pdca_readonly_access import get_pdca_readonly_session, require_pdca_super_admin
from dy_api.pdca_source_evidence import read_pdca_page
from dy_api.pdca_source_schema import EvidencePage

router = APIRouter()


@router.get('/pdca-source-evidence', response_model=EvidencePage, summary='Read bounded PDCA source observations')
def pdca_source_evidence(
    dataset: str,
    period_start: date = Query(alias='periodStart'),
    period_end: date = Query(alias='periodEnd'),
    observed_through: datetime = Query(alias='observedThrough'),
    page_size: int = Query(default=500, ge=1, le=500, alias='pageSize'),
    cursor: str | None = Query(default=None, max_length=2048),
    _username: str = Depends(require_pdca_super_admin),
    session: Session = Depends(get_pdca_readonly_session),
) -> EvidencePage:
    """Return existing facts only; never seed permissions, refresh or collect."""
    try:
        return read_pdca_page(session, dataset=dataset, period_start=period_start,
                              period_end=period_end, observed_through=observed_through,
                              page_size=page_size, cursor=cursor)
    except ValueError as error:
        raise HTTPException(status_code=422, detail='Invalid evidence query') from error
    except DBAPIError as error:
        raise HTTPException(status_code=503, detail='Source query unavailable') from error
