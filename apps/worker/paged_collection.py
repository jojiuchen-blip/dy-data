"""Resumable, page-bounded collection for the priority daily scheduler.

The legacy collection adapters keep one transaction open while a complete
window is fetched.  That is a poor fit for a scheduler which may have to yield
when one endpoint's daily budget is exhausted: all rows fetched before the
yield would be rolled back together with the cursor.  This module moves the
boundary to one upstream page.  A page's raw upserts and the next cursor are
committed in the same short transaction, and the next invocation starts from
that cursor.

Only the collect stage is owned here.  Materialization and settlement keep
their existing stage contracts and are deliberately not called from this
module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobRun, JobStageRun
from apps.worker.collectors.clues import collect_clues
from apps.worker.collectors.normalizers import data_items, first, text
from apps.worker.collectors.orders import collect_orders
from apps.worker.collectors.refunds import collect_refunds
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.collectors.verify_records import collect_verify_records
from apps.worker.priority_budget import PriorityBudgetPauseError
from apps.worker.douyin_api_quota import DouyinQuotaExceeded as LedgerQuotaExceeded
from src.dy_data.douyin_rate_limits import DouyinQuotaExceeded as GovernorQuotaExceeded


SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
CHECKPOINT_PROTOCOL = "priority-paged-v1"
COLLECT_STAGE = "collect"

DEFAULT_PAGE_SIZES: dict[str, int] = {
    "orders": 100,
    "refunds": 100,
    "clues": 100,
    "verify_records": 20,
}
MAX_PAGED_REQUESTS = 100_000

_TARGET_DOMAINS: dict[str, tuple[str, ...]] = {
    "all": ("orders", "refunds", "clues", "verify_records"),
    "orders": ("orders",),
    "refunds": ("refunds",),
    "clues": ("clues",),
    "verify_records": ("verify_records",),
}


class PagedCollectionError(RuntimeError):
    """The source page or its durable checkpoint is not safe to continue."""


class LeaseFenceLost(PagedCollectionError):
    """The child lost its execution lease before a page could be committed."""


class ConcurrentPageAdvance(PagedCollectionError):
    """Another execution advanced this stage's checkpoint first."""


class PriorityBudgetPause(PriorityBudgetPauseError):
    """Backward-compatible local name for the priority pause exception."""


@dataclass(frozen=True)
class _Page:
    domain: str
    endpoint: str
    requested_cursor: str | None
    requested_page: int | None
    payload: dict[str, Any]
    rows: list[dict[str, Any]]
    next_cursor: str | None
    next_page: int | None
    completed: bool


def collect_priority_pages(
    session_or_factory: Session | sessionmaker[Session] | Callable[[], Session],
    client: Any,
    job: JobRun,
    *,
    page_fence: Callable[[Session], bool] | None = None,
    source_run_id: str | None = None,
    page_sizes: Mapping[str, int] | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Collect one priority child with one API page per DB transaction.

    ``session_or_factory`` may be the stage Session supplied by
    :func:`run_daily_stages` or a factory used by tests/callers.  The stage
    Session itself is never used for page business writes; every page opens a
    fresh Session so an upstream wait does not hold a transaction or row lock.

    The returned mapping is suitable for ``StageHandlerOutput``/the existing
    stage runner checkpoint adapter.  Each page also updates
    ``job_stage_runs.checkpoint_json`` before its business transaction commits.
    """

    factory = _session_factory(session_or_factory)
    target = _job_target(job)
    domains = _TARGET_DOMAINS.get(target)
    if domains is None:
        raise PagedCollectionError(
            f"priority paged collect does not support target={target!r}"
        )
    window = _job_window(job)
    sizes = _page_sizes(page_sizes)
    source_id = str(source_run_id or job.job_id)

    checkpoint = _load_checkpoint(factory, job, target=target, window=window)
    committed_pages = 0
    for domain in domains:
        state = checkpoint["domains"][domain]
        while not bool(state.get("completed")):
            if max_pages is not None and committed_pages >= max_pages:
                # A partial stage must never be reported as success.  The
                # normal production path yields through the quota governor;
                # this explicit bound is useful to callers that want a
                # deterministic cooperative yield in a dry run.
                raise PriorityBudgetPauseError(60)

            _guard_position(state, domain)
            _assert_fence(factory, page_fence)
            try:
                page = _fetch_page(
                    client,
                    domain=domain,
                    state=state,
                    window=window,
                    page_size=sizes[domain],
                )
            except PriorityBudgetPauseError:
                # Preserve the scheduler's typed marker exactly.  Its message
                # intentionally does not contain the global 2119003 code.
                raise
            except BaseException as exc:
                _raise_budget_pause_if_needed(exc)
                raise

            try:
                page_metadata = _commit_page(
                    factory,
                    job=job,
                    expected_checkpoint=checkpoint,
                    expected_state=state,
                    page=page,
                    window=window,
                    source_run_id=source_id,
                    page_fence=page_fence,
                    original_client=client,
                    page_size=sizes[domain],
                )
            except PriorityBudgetPauseError:
                raise
            except BaseException as exc:
                _raise_budget_pause_if_needed(exc)
                raise

            checkpoint = page_metadata["checkpoint"]
            state = checkpoint["domains"][domain]
            committed_pages += 1

    checkpoint["completed"] = all(
        bool(checkpoint["domains"][domain].get("completed")) for domain in domains
    )
    checkpoint["pages_committed"] = sum(
        int(checkpoint["domains"][domain].get("pages_committed", 0) or 0)
        for domain in domains
    )
    return checkpoint


# Names used by callers that prefer an explicit operation verb.
run_paged_collection = collect_priority_pages
collect_paged = collect_priority_pages


def _session_factory(
    session_or_factory: Session | sessionmaker[Session] | Callable[[], Session],
) -> sessionmaker[Session] | Callable[[], Session]:
    if isinstance(session_or_factory, Session):
        return sessionmaker(
            bind=session_or_factory.get_bind(),
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    if callable(session_or_factory):
        return session_or_factory
    raise TypeError("session_or_factory must be a SQLAlchemy Session or factory")


def _page_sizes(overrides: Mapping[str, int] | None) -> dict[str, int]:
    values = dict(DEFAULT_PAGE_SIZES)
    if overrides is None:
        return values
    for domain in values:
        if domain not in overrides:
            continue
        try:
            size = int(overrides[domain])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"page size for {domain} must be an integer") from exc
        if size < 1 or size > 1000:
            raise ValueError(f"page size for {domain} must be between 1 and 1000")
        values[domain] = size
    return values


def _job_target(job: Any) -> str:
    metadata = getattr(job, "metadata_json", None) or {}
    return str(metadata.get("target") or "all")


def _job_window(job: Any) -> CollectionWindow:
    metadata = getattr(job, "metadata_json", None) or {}
    source_window = metadata.get("source_window")
    start = getattr(job, "window_start", None)
    end = getattr(job, "window_end", None)
    if isinstance(source_window, Mapping):
        start = start or source_window.get("start")
        end = end or source_window.get("end")
    parsed_start = _parse_datetime(start, field_name="window_start")
    parsed_end = _parse_datetime(end, field_name="window_end")
    if parsed_end <= parsed_start:
        raise PagedCollectionError("priority collection window_end must be after window_start")
    timezone_name = (
        str(source_window.get("timezone") or "Asia/Shanghai")
        if isinstance(source_window, Mapping)
        else "Asia/Shanghai"
    )
    return CollectionWindow(
        start=parsed_start,
        end=parsed_end,
        timezone_name=timezone_name,
    )


def _parse_datetime(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise PagedCollectionError(f"invalid {field_name}") from exc
    else:
        raise PagedCollectionError(f"{field_name} is required for priority collection")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI_TIMEZONE)
    return parsed


def _window_metadata(window: CollectionWindow) -> dict[str, str]:
    return {
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "timezone": window.timezone_name,
    }


def _load_checkpoint(
    factory: sessionmaker[Session] | Callable[[], Session],
    job: JobRun,
    *,
    target: str,
    window: CollectionWindow,
) -> dict[str, Any]:
    with factory() as session:
        stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == job.job_id,
                JobStageRun.stage_name == COLLECT_STAGE,
            )
        )
        existing = dict(stage.checkpoint_json or {}) if stage is not None else {}
    return _normalize_checkpoint(existing, target=target, window=window)


def _normalize_checkpoint(
    existing: Mapping[str, Any],
    *,
    target: str,
    window: CollectionWindow,
) -> dict[str, Any]:
    expected_window = _window_metadata(window)
    if not existing:
        return _new_checkpoint(target=target, window=window)
    protocol = existing.get("protocol")
    if protocol not in (None, CHECKPOINT_PROTOCOL):
        raise PagedCollectionError(
            f"unsupported priority collect checkpoint protocol: {protocol!r}"
        )
    saved_window = existing.get("window")
    if saved_window is not None and _canonical_json(saved_window) != _canonical_json(
        expected_window
    ):
        raise PagedCollectionError("priority collect checkpoint window does not match job window")
    saved_target = existing.get("target")
    if saved_target not in (None, target):
        raise PagedCollectionError("priority collect checkpoint target does not match job target")
    raw_domains = existing.get("domains")
    if not isinstance(raw_domains, Mapping):
        raise PagedCollectionError("priority collect checkpoint domains are invalid")
    checkpoint = {
        "protocol": CHECKPOINT_PROTOCOL,
        "window": expected_window,
        "target": target,
        "domains": {
            key: dict(value)
            for key, value in raw_domains.items()
            if isinstance(value, Mapping)
        },
        "pages_committed": int(existing.get("pages_committed", 0) or 0),
        "completed": bool(existing.get("completed")),
    }
    for domain in _TARGET_DOMAINS[target]:
        if domain not in checkpoint["domains"]:
            checkpoint["domains"][domain] = _new_domain_state(domain)
        _validate_domain_state(domain, checkpoint["domains"][domain])
    unexpected = set(checkpoint["domains"]) - set(_TARGET_DOMAINS[target])
    if unexpected:
        raise PagedCollectionError(
            "priority collect checkpoint contains unexpected domains: "
            + ", ".join(sorted(unexpected))
        )
    checkpoint["completed"] = all(
        bool(checkpoint["domains"][domain].get("completed"))
        for domain in _TARGET_DOMAINS[target]
    )
    return checkpoint


def _new_checkpoint(*, target: str, window: CollectionWindow) -> dict[str, Any]:
    domains = {domain: _new_domain_state(domain) for domain in _TARGET_DOMAINS[target]}
    return {
        "protocol": CHECKPOINT_PROTOCOL,
        "window": _window_metadata(window),
        "target": target,
        "domains": domains,
        "pages_committed": 0,
        "completed": False,
    }


def _new_domain_state(domain: str) -> dict[str, Any]:
    if domain == "orders":
        return {
            "endpoint": "orders.create_order",
            "phase": "create",
            "cursor": None,
            "completed": False,
            "seen_positions": [],
            "pages_committed": 0,
            "fetched": 0,
            "upserted": 0,
            "skipped": 0,
            "failed": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "rejected": 0,
        }
    if domain == "clues":
        return {
            "endpoint": "clues.query",
            "page": 1,
            "completed": False,
            "seen_positions": [],
            "pages_committed": 0,
            "fetched": 0,
            "upserted": 0,
            "skipped": 0,
            "failed": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "rejected": 0,
        }
    return {
        "endpoint": f"{domain}.query",
        "cursor": None,
        "completed": False,
        "seen_positions": [],
        "pages_committed": 0,
        "fetched": 0,
        "upserted": 0,
        "skipped": 0,
        "failed": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "rejected": 0,
    }


def _validate_domain_state(domain: str, state: Mapping[str, Any]) -> None:
    if domain == "orders":
        phase = state.get("phase", "create")
        if phase not in {"create", "update"}:
            raise PagedCollectionError("orders checkpoint phase is invalid")
        expected_endpoint = f"orders.{phase}_order"
        if state.get("endpoint") not in (None, expected_endpoint):
            raise PagedCollectionError("orders checkpoint endpoint does not match phase")
        if state.get("endpoint") is None:
            state["endpoint"] = expected_endpoint  # type: ignore[index]
    else:
        expected_endpoint = f"{domain}.query"
        if state.get("endpoint") not in (None, expected_endpoint):
            raise PagedCollectionError(
                f"{domain} checkpoint endpoint does not match expected endpoint"
            )
        if state.get("endpoint") is None:
            state["endpoint"] = expected_endpoint  # type: ignore[index]
    if "completed" not in state:
        state["completed"] = False  # type: ignore[index]
    for key in (
        "pages_committed",
        "fetched",
        "upserted",
        "skipped",
        "failed",
        "inserted",
        "updated",
        "unchanged",
        "rejected",
    ):
        try:
            value = int(state.get(key, 0) or 0)
        except (TypeError, ValueError) as exc:
            raise PagedCollectionError(f"{domain} checkpoint count {key} is invalid") from exc
        if value < 0:
            raise PagedCollectionError(f"{domain} checkpoint count {key} is negative")
        state[key] = value  # type: ignore[index]
    positions = state.get("seen_positions", [])
    if not isinstance(positions, list):
        raise PagedCollectionError(f"{domain} checkpoint seen_positions is invalid")
    if len(positions) > MAX_PAGED_REQUESTS:
        raise PagedCollectionError(f"{domain} checkpoint exceeds page cycle guard")
    if len({str(value) for value in positions}) != len(positions):
        raise PagedCollectionError(f"{domain} checkpoint contains a repeated page position")
    state["seen_positions"] = list(positions)  # type: ignore[index]
    if domain == "clues":
        try:
            page = int(state.get("page", 1) or 1)
        except (TypeError, ValueError) as exc:
            raise PagedCollectionError("clues checkpoint page is invalid") from exc
        if page < 1:
            raise PagedCollectionError("clues checkpoint page must be positive")
        state["page"] = page  # type: ignore[index]
    else:
        cursor = state.get("cursor")
        if cursor not in (None, "") and not isinstance(cursor, str):
            state["cursor"] = _cursor_param(cursor)  # type: ignore[index]


def _fetch_page(
    client: Any,
    *,
    domain: str,
    state: Mapping[str, Any],
    window: CollectionWindow,
    page_size: int,
) -> _Page:
    if domain == "orders":
        return _fetch_orders_page(client, state=state, window=window, page_size=page_size)
    if domain == "refunds":
        return _fetch_refunds_page(client, state=state, window=window, page_size=page_size)
    if domain == "clues":
        return _fetch_clues_page(client, state=state, window=window, page_size=page_size)
    if domain == "verify_records":
        return _fetch_verify_page(client, state=state, window=window, page_size=page_size)
    raise PagedCollectionError(f"unsupported priority collection domain: {domain}")


def _fetch_orders_page(
    client: Any,
    *,
    state: Mapping[str, Any],
    window: CollectionWindow,
    page_size: int,
) -> _Page:
    query = getattr(client, "query_orders", None)
    if not callable(query):
        raise PagedCollectionError("priority orders collection requires query_orders")
    phase = str(state.get("phase") or "create")
    cursor = _optional_cursor(state.get("cursor"))
    kwargs: dict[str, Any] = {"page_size": page_size, "cursor": cursor}
    if phase == "update":
        kwargs["time_field"] = "update_order"
    payload = query(window.start, window.end, **kwargs)
    if not isinstance(payload, dict):
        raise PagedCollectionError("orders page must be an object")
    rows = _rows(payload, "orders", "list", "order_list")
    data = _payload_data(payload)
    next_cursor = _order_cursor(data, rows)
    explicit_more = _explicit_bool(_first_in(data, "has_more", "more"))
    if explicit_more is True and not next_cursor:
        raise PagedCollectionError("orders has_more=true without an advancing cursor")
    if next_cursor is not None and next_cursor == cursor:
        raise PagedCollectionError("orders cursor did not advance")
    if explicit_more is False or (explicit_more is None and len(rows) < page_size):
        completed = True
    elif next_cursor is None:
        # The official order iterator stops on a short page, but a full page
        # without a cursor cannot prove that it is the last page.
        raise PagedCollectionError("orders full page is missing its cursor")
    else:
        completed = False
    endpoint = f"orders.{phase}_order"
    return _Page(
        domain="orders",
        endpoint=endpoint,
        requested_cursor=cursor,
        requested_page=None,
        payload=payload,
        rows=rows,
        next_cursor=next_cursor,
        next_page=None,
        completed=completed,
    )


def _fetch_refunds_page(
    client: Any,
    *,
    state: Mapping[str, Any],
    window: CollectionWindow,
    page_size: int,
) -> _Page:
    query = getattr(client, "query_refunds", None)
    if not callable(query):
        raise PagedCollectionError("priority refunds collection requires query_refunds")
    cursor = _optional_cursor(state.get("cursor"))
    payload = query(window.start, window.end, page_size=page_size, cursor=cursor)
    if not isinstance(payload, dict):
        raise PagedCollectionError("refunds page must be an object")
    rows = _rows(
        payload,
        "refunds",
        "after_sales",
        "after_sale_orders",
        "after_sale_order_list",
        "records",
        "list",
    )
    data = _payload_data(payload)
    has_more = _page_has_more(data)
    next_cursor = _generic_cursor(data, rows)
    if has_more is None:
        raise PagedCollectionError("refunds page must include explicit has_more")
    if has_more and not next_cursor:
        raise PagedCollectionError("refunds has_more=true without a cursor")
    if next_cursor is not None and next_cursor == cursor:
        raise PagedCollectionError("refunds cursor did not advance")
    return _Page(
        domain="refunds",
        endpoint="refunds.query",
        requested_cursor=cursor,
        requested_page=None,
        payload=payload,
        rows=rows,
        next_cursor=next_cursor,
        next_page=None,
        completed=not has_more,
    )


def _fetch_clues_page(
    client: Any,
    *,
    state: Mapping[str, Any],
    window: CollectionWindow,
    page_size: int,
) -> _Page:
    query = getattr(client, "query_clues", None)
    if not callable(query):
        raise PagedCollectionError("priority clues collection requires query_clues")
    page_number = int(state.get("page", 1) or 1)
    payload = query(window.start, window.end, page=page_number, page_size=page_size)
    if not isinstance(payload, dict):
        raise PagedCollectionError("clues page must be an object")
    rows = _rows(payload, "clue_data", "clues", "list", "records")
    data = _payload_data(payload)
    has_more = _page_has_more(data)
    total = _integer(_first_in(data, "total", "total_count", "count"))
    if total is None and isinstance(data.get("page"), Mapping):
        total = _integer(data["page"].get("total"))
    if has_more is True:
        completed = False
    elif has_more is False:
        completed = True
    elif total is not None:
        completed = page_number * page_size >= total
    else:
        completed = len(rows) < page_size
    next_page = None if completed else page_number + 1
    return _Page(
        domain="clues",
        endpoint="clues.query",
        requested_cursor=None,
        requested_page=page_number,
        payload=payload,
        rows=rows,
        next_cursor=None,
        next_page=next_page,
        completed=completed,
    )


def _fetch_verify_page(
    client: Any,
    *,
    state: Mapping[str, Any],
    window: CollectionWindow,
    page_size: int,
) -> _Page:
    query = getattr(client, "query_verify_records", None)
    if not callable(query):
        raise PagedCollectionError(
            "priority verification collection requires query_verify_records"
        )
    cursor = _optional_cursor(state.get("cursor"))
    payload = query(
        window.start,
        window.end,
        page_size=page_size,
        cursor=cursor,
    )
    if not isinstance(payload, dict):
        raise PagedCollectionError("verify_records page must be an object")
    rows = _rows(payload, "verify_records", "records", "list")
    data = _payload_data(payload)
    has_more = _page_has_more(data)
    next_cursor = _generic_cursor(data, rows)
    if has_more is True and not next_cursor:
        raise PagedCollectionError("verify_records has_more=true without a cursor")
    if next_cursor is not None and next_cursor == cursor:
        raise PagedCollectionError("verify_records cursor did not advance")
    if has_more is None:
        if len(rows) < page_size:
            completed = True
        elif next_cursor is None:
            raise PagedCollectionError(
                "verify_records full page is missing its cursor"
            )
        else:
            completed = False
    else:
        completed = not has_more
    return _Page(
        domain="verify_records",
        endpoint="verify_records.query",
        requested_cursor=cursor,
        requested_page=None,
        payload=payload,
        rows=rows,
        next_cursor=next_cursor,
        next_page=None,
        completed=completed,
    )


def _commit_page(
    factory: sessionmaker[Session] | Callable[[], Session],
    *,
    job: JobRun,
    expected_checkpoint: Mapping[str, Any],
    expected_state: Mapping[str, Any],
    page: _Page,
    window: CollectionWindow,
    source_run_id: str,
    page_fence: Callable[[Session], bool] | None,
    original_client: Any,
    page_size: int,
) -> dict[str, Any]:
    with factory() as session:
        session.begin()
        try:
            stage_statement = select(JobStageRun).where(
                JobStageRun.job_id == job.job_id,
                JobStageRun.stage_name == COLLECT_STAGE,
            )
            if session.get_bind().dialect.name == "postgresql":
                stage_statement = stage_statement.with_for_update()
            stage = session.scalar(stage_statement)
            if stage is None:
                now = datetime.now(UTC)
                stage = JobStageRun(
                    stage_run_id=f"stage-{job.job_id}-{COLLECT_STAGE}",
                    job_id=job.job_id,
                    stage_name=COLLECT_STAGE,
                    status="pending",
                    checkpoint_json={},
                    lease_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(stage)
                session.flush()

            current = _normalize_checkpoint(
                dict(stage.checkpoint_json or {}),
                target=str(expected_checkpoint.get("target") or _job_target(job)),
                window=window,
            )
            current_state = current["domains"].get(page.domain)
            if not isinstance(current_state, Mapping):
                raise ConcurrentPageAdvance(f"missing checkpoint domain {page.domain}")
            if _state_token(current_state) != _state_token(expected_state):
                raise ConcurrentPageAdvance(
                    f"{page.domain} checkpoint advanced while page was in flight"
                )
            if str(current_state.get("endpoint")) != page.endpoint:
                raise PagedCollectionError(
                    f"{page.domain} checkpoint endpoint changed during page commit"
                )
            if page_fence is not None and not page_fence(session):
                raise LeaseFenceLost("lease fence rejected before page commit")

            phase_stats = _apply_page(
                session,
                page=page,
                window=window,
                source_run_id=source_run_id,
                client_payload=page.payload,
                original_client=original_client,
                page_size=page_size,
            )
            next_state = dict(current_state)
            _accumulate_stats(next_state, phase_stats)
            next_state["pages_committed"] = int(next_state.get("pages_committed", 0) or 0) + 1
            next_state["completed"] = bool(page.completed)
            if page.domain == "orders":
                if page.completed and str(next_state.get("phase")) == "create":
                    # Orders must also scan the update-order stream.  This is
                    # a phase transition in the same cursor checkpoint, so a
                    # restart cannot repeat the completed create stream.
                    next_state["phase"] = "update"
                    next_state["endpoint"] = "orders.update_order"
                    next_state["cursor"] = None
                    next_state["seen_positions"] = []
                    next_state["completed"] = False
                else:
                    next_state["cursor"] = page.next_cursor
            elif page.domain == "clues":
                if page.next_page is not None:
                    next_state["page"] = page.next_page
                next_state["completed"] = bool(page.completed)
            else:
                next_state["cursor"] = page.next_cursor
            positions = list(current_state.get("seen_positions", []))
            position = _page_position(page)
            if position in positions:
                raise PagedCollectionError(
                    f"{page.domain} page position repeated: {position}"
                )
            positions.append(position)
            if len(positions) > MAX_PAGED_REQUESTS:
                raise PagedCollectionError(
                    f"{page.domain} exceeded the page cycle guard"
                )
            next_state["seen_positions"] = positions
            current["domains"][page.domain] = next_state
            current["pages_committed"] = sum(
                int(value.get("pages_committed", 0) or 0)
                for value in current["domains"].values()
                if isinstance(value, Mapping)
            )
            current["completed"] = all(
                bool(value.get("completed"))
                for value in current["domains"].values()
                if isinstance(value, Mapping)
            )
            stage.checkpoint_json = current
            stage.updated_at = datetime.now(UTC)
            if page_fence is not None and not page_fence(session):
                raise LeaseFenceLost("lease fence rejected before page commit")
            session.commit()
            return {"checkpoint": current, "stats": phase_stats.as_metadata()}
        except BaseException:
            session.rollback()
            raise


def _apply_page(
    session: Session,
    *,
    page: _Page,
    window: CollectionWindow,
    source_run_id: str,
    client_payload: dict[str, Any],
    original_client: Any | None,
    page_size: int,
) -> PhaseStats:
    # ``original_client`` is intentionally optional.  The bounded client
    # delegates certificate supplementation only when the caller provides it;
    # all primary page rows are already captured in ``client_payload``.
    bounded = _BoundedPageClient(
        payload=client_payload,
        rows=page.rows,
        original_client=original_client,
        domain=page.domain,
        page_size=page_size,
        order_phase=(
            page.endpoint.removeprefix("orders.").removesuffix("_order")
            if page.domain == "orders"
            else None
        ),
    )
    if page.domain == "orders":
        return collect_orders(session, bounded, window, source_run_id=source_run_id)
    if page.domain == "refunds":
        return collect_refunds(
            session,
            bounded,
            window,
            source_run_id=source_run_id,
            page_size=page_size,
        )
    if page.domain == "clues":
        return collect_clues(
            session,
            bounded,
            window,
            source_run_id=source_run_id,
            page_size=page_size,
        )
    if page.domain == "verify_records":
        return collect_verify_records(
            session,
            bounded,
            window,
            source_run_id=source_run_id,
            page_size=page_size,
        )
    raise PagedCollectionError(f"unsupported page domain {page.domain}")


def _accumulate_stats(state: dict[str, Any], stats: PhaseStats) -> None:
    metadata = stats.as_metadata()
    for key in (
        "fetched",
        "upserted",
        "skipped",
        "failed",
        "inserted",
        "updated",
        "unchanged",
        "rejected",
    ):
        state[key] = int(state.get(key, 0) or 0) + int(metadata.get(key, 0) or 0)


class _BoundedPageClient:
    """Expose one already-fetched page through the legacy collector API."""

    def __init__(
        self,
        *,
        payload: dict[str, Any],
        rows: list[dict[str, Any]],
        original_client: Any | None,
        domain: str,
        page_size: int,
        order_phase: str | None,
    ) -> None:
        self._payload = payload
        self._rows = rows
        self._original_client = original_client
        self._domain = domain
        self._page_size = page_size
        self._order_phase = order_phase

    def iter_orders(self, *_args: Any, **_kwargs: Any):
        if self._domain == "orders" and self._order_phase == "create":
            yield from self._rows

    def iter_order_updates(self, *_args: Any, **_kwargs: Any):
        if self._domain == "orders" and self._order_phase == "update":
            yield from self._rows

    def iter_refunds(self, *_args: Any, **_kwargs: Any):
        if self._domain == "refunds":
            yield from self._rows

    def query_clues(self, *_args: Any, page: int = 1, **_kwargs: Any) -> dict[str, Any]:
        if self._domain != "clues" or page != 1:
            return {"data": {"clue_data": []}}
        # The outer page state records source totals/has_more.  The existing
        # recursive collector must see a bounded, synthetic second page so it
        # does not recursively split or refetch the same upstream page.
        return {"data": {"clue_data": list(self._rows)}}

    def query_verify_records(
        self,
        *_args: Any,
        cursor: Any = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if self._domain != "verify_records" or cursor not in (None, "", "0", 0):
            return {"data": {"verify_records": [], "has_more": False}}
        return self._payload

    def query_certificates(self, *, order_id: str) -> dict[str, Any]:
        query = getattr(self._original_client, "query_certificates", None)
        if callable(query):
            return query(order_id=order_id)
        return {}

    def decrypt_cipher_texts(self, values: list[str]) -> dict[str, str]:
        resolver = getattr(self._original_client, "decrypt_cipher_texts", None)
        return resolver(values) if callable(resolver) else {}


def _assert_fence(
    factory: sessionmaker[Session] | Callable[[], Session],
    page_fence: Callable[[Session], bool] | None,
) -> None:
    if page_fence is None:
        return
    with factory() as session:
        session.begin()
        try:
            if not page_fence(session):
                raise LeaseFenceLost("lease fence rejected before upstream page")
        finally:
            session.rollback()


def _raise_budget_pause_if_needed(exc: BaseException) -> None:
    if isinstance(exc, PriorityBudgetPauseError):
        raise exc
    if isinstance(exc, (GovernorQuotaExceeded, LedgerQuotaExceeded)):
        retry_after = _retry_after_seconds(exc)
        raise PriorityBudgetPauseError(retry_after) from exc
    # The HTTP client surfaces platform 2119003 as DouyinApiError rather than
    # the governor exception.  Keep this narrow so arbitrary business errors
    # containing the number are not silently converted into a retry pause.
    if exc.__class__.__name__ == "DouyinApiError":
        message = str(exc)
        if "2119003" in message or "请求太过频繁" in message:
            raise PriorityBudgetPauseError(_retry_after_seconds(exc)) from exc


def _retry_after_seconds(exc: BaseException) -> int:
    for candidate in (
        getattr(exc, "retry_after_seconds", None),
        getattr(getattr(exc, "reservation", None), "retry_after_seconds", None),
    ):
        try:
            if candidate is not None:
                return max(60, int(candidate))
        except (TypeError, ValueError):
            continue
    return 60


def _payload_data(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else dict(payload)


def _rows(payload: Mapping[str, Any], *keys: str) -> list[dict[str, Any]]:
    return data_items(dict(payload), *keys)


def _first_in(data: Mapping[str, Any], *keys: str) -> Any:
    return first(dict(data), *keys)


def _generic_cursor(data: Mapping[str, Any], rows: list[dict[str, Any]]) -> str | None:
    page_info = data.get("page_info") if isinstance(data.get("page_info"), Mapping) else {}
    for source in (data, page_info):
        for key in ("next_cursor", "cursor", "next_page_token"):
            value = source.get(key)
            cursor = _optional_cursor(value)
            if cursor is not None:
                return cursor
    if rows:
        return _optional_cursor(first(rows[-1], "cursor", "next_cursor"))
    return None


def _order_cursor(data: Mapping[str, Any], rows: list[dict[str, Any]]) -> str | None:
    search_after = data.get("search_after")
    if isinstance(search_after, Mapping):
        value = search_after.get("CursorValue")
        cursor = _optional_cursor(value)
        if cursor is not None:
            return cursor
    return _generic_cursor(data, rows)


def _explicit_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _page_has_more(data: Mapping[str, Any]) -> bool | None:
    value = _explicit_bool(_first_in(data, "has_more", "more"))
    if value is not None:
        return value
    page_info = data.get("page_info")
    if isinstance(page_info, Mapping):
        return _explicit_bool(_first_in(page_info, "has_more", "more"))
    return None


def _integer(value: Any) -> int | None:
    try:
        return None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None


def _cursor_param(value: Any) -> str:
    if value in (None, ""):
        return "0"
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _optional_cursor(value: Any) -> str | None:
    if value in (None, "", 0, "0", -1, "-1"):
        return None
    return _cursor_param(value)


def _state_token(state: Mapping[str, Any]) -> str:
    identity = {
        "endpoint": state.get("endpoint"),
        "phase": state.get("phase"),
        "cursor": state.get("cursor"),
        "page": state.get("page"),
        "completed": state.get("completed"),
        "pages_committed": state.get("pages_committed", 0),
        "seen_positions": state.get("seen_positions", []),
    }
    return _canonical_json(identity)


def _page_position(page: _Page) -> str:
    if page.domain == "clues":
        return f"page:{page.requested_page}"
    return f"{page.endpoint}:cursor:{page.requested_cursor or '__initial__'}"


def _guard_position(state: Mapping[str, Any], domain: str) -> None:
    positions = state.get("seen_positions", [])
    if not isinstance(positions, list):
        raise PagedCollectionError(f"{domain} checkpoint seen_positions is invalid")
    if len(positions) >= MAX_PAGED_REQUESTS:
        raise PagedCollectionError(f"{domain} exceeded the page cycle guard")
    position = (
        f"page:{int(state.get('page', 1) or 1)}"
        if domain == "clues"
        else f"{state.get('endpoint')}:cursor:{state.get('cursor') or '__initial__'}"
    )
    if position in positions:
        raise PagedCollectionError(f"{domain} page position cycle detected: {position}")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "CHECKPOINT_PROTOCOL",
    "ConcurrentPageAdvance",
    "DEFAULT_PAGE_SIZES",
    "LeaseFenceLost",
    "PagedCollectionError",
    "PriorityBudgetPause",
    "collect_paged",
    "collect_priority_pages",
    "run_paged_collection",
]
