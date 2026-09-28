"""Independent, highest-admin, read-only PDCA evidence endpoint."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from dy_api.pdca_readonly_access import get_pdca_readonly_session, require_pdca_super_admin
from dy_api.pdca_source_evidence import read_pdca_page
from dy_api.pdca_source_schema import EvidencePage
from dy_api import pdca_snapshot_store
from dy_api.pdca_snapshot_projection import (
    SnapshotLimitError, SnapshotSourceError, project_snapshot, snapshot_session, validate_window,
)
from dy_api.pdca_snapshot_schema import SnapshotManifest, SnapshotPage

router = APIRouter()


def require_pdca_snapshot_admin(request: Request) -> str:
    """Reuse authorization, releasing its connection before snapshot acquisition."""
    iterator = get_pdca_readonly_session()
    try:
        session = next(iterator)
        return require_pdca_super_admin(request, session)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail='Source authentication unavailable') from None
    finally:
        iterator.close()


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


@router.get('/pdca-source-snapshots', response_model=SnapshotManifest)
def pdca_snapshot_manifest(
    response: Response,
    period_start: date = Query(alias='periodStart'),
    period_end: date = Query(alias='periodEnd'),
    observed_through: datetime = Query(alias='observedThrough'),
    sku_ids: list[str] | None = Query(default=None, alias='skuIds', max_length=100),
    username: str = Depends(require_pdca_snapshot_admin),
) -> SnapshotManifest:
    """Read a bounded cohort atomically; freeze only approved evidence in RAM."""
    response.headers['Cache-Control'] = 'no-store'
    try:
        start, end, cutoff = validate_window(period_start, period_end, observed_through)
        if sku_ids is not None and (not 1 <= len(sku_ids) <= 100 or
                                   any(not value or len(value) > 128 for value in sku_ids)):
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=422, detail='Invalid snapshot query') from None
    if not pdca_snapshot_store.BUILD_SLOT.acquire(blocking=False):
        raise HTTPException(status_code=429, detail='Snapshot capacity busy', headers={'Retry-After': '10'})
    try:
        pdca_snapshot_store.STORE.check_capacity()
        as_of = datetime.now(timezone.utc)
        with snapshot_session() as session:
            datasets, selected_skus, rule_version = project_snapshot(session, start, end, cutoff, sku_ids)
        return pdca_snapshot_store.STORE.freeze(username, datasets, start=start, end=end, cutoff=cutoff,
            sku_ids=selected_skus, explicit_scope=sku_ids is not None, rule_version=rule_version, as_of=as_of)
    except (ValueError, TypeError):
        raise HTTPException(status_code=503, detail='Source snapshot invalid') from None
    except SnapshotLimitError:
        raise HTTPException(status_code=413, detail='Snapshot limit exceeded; narrow date or SKU scope') from None
    except pdca_snapshot_store.SnapshotBusyError:
        raise HTTPException(status_code=429, detail='Snapshot capacity busy', headers={'Retry-After': '600'}) from None
    except (SQLAlchemyError, SnapshotSourceError):
        raise HTTPException(status_code=503, detail='Source snapshot unavailable') from None
    finally:
        pdca_snapshot_store.BUILD_SLOT.release()


@router.get('/pdca-source-snapshots/{snapshot_id}', response_model=SnapshotPage)
def pdca_snapshot_page(
    snapshot_id: str,
    dataset: str,
    response: Response,
    page_size: int = Query(default=500, ge=1, le=500, alias='pageSize'),
    cursor: str | None = Query(default=None, max_length=2048),
    username: str = Depends(require_pdca_snapshot_admin),
) -> SnapshotPage:
    """Revalidate authorization every page; never silently recreate an expired snapshot."""
    response.headers['Cache-Control'] = 'no-store'
    try:
        return pdca_snapshot_store.STORE.page(username, snapshot_id, dataset, page_size, cursor)
    except pdca_snapshot_store.SnapshotGoneError:
        raise HTTPException(status_code=410, detail='Snapshot expired or unavailable; start a new complete read') from None
    except ValueError:
        raise HTTPException(status_code=422, detail='Invalid snapshot page') from None
