"""Highest-admin, aggregate-only settlement audit endpoint for DYDATA-102."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from dy_api.pdca_readonly_access import get_pdca_readonly_session, require_pdca_super_admin
from dy_api.settlement_audit_readonly import (
    SettlementMonthAudit,
    parse_audit_months,
    read_settlement_month_audit,
)

router = APIRouter()


@router.get(
    '/settlement-month-audit',
    response_model=SettlementMonthAudit,
    summary='Read fixed aggregate settlement audit for 2026-09 and 2026-10',
)
def settlement_month_audit(
    response: Response,
    months: str = Query(
        default='2026-09,2026-10',
        max_length=64,
        description='Fixed audit window; only 2026-09 and 2026-10 are accepted.',
    ),
    _username: str = Depends(require_pdca_super_admin),
    session: Session = Depends(get_pdca_readonly_session),
) -> SettlementMonthAudit:
    """Return layer counts and amounts only, inside a read-only transaction."""

    response.headers['Cache-Control'] = 'no-store'
    try:
        selected = parse_audit_months(months)
    except ValueError as error:
        raise HTTPException(status_code=422, detail='Invalid audit months') from error
    try:
        return read_settlement_month_audit(session, months=selected)
    except DBAPIError as error:
        raise HTTPException(status_code=503, detail='Source query unavailable') from error
