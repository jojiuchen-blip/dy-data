from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.worker.clue_allocation import materialize_clue_master_leads, refresh_due_store_score_snapshots
from apps.worker.clue_center import rebuild_clue_center
from apps.worker.collectors.aweme_bindings import collect_aweme_bindings
from apps.worker.collectors.clues import collect_clues
from apps.worker.collectors.orders import collect_orders
from apps.worker.collectors.types import CollectionStats, CollectionWindow, PhaseStats
from apps.worker.collectors.verify_records import collect_shop_pois, collect_verify_records
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.repositories import finish_job_run, start_job_run
from apps.worker.settlement import rebuild_settlement
from src.dy_data.config import douyin_account_id, douyin_app_id, douyin_app_secret
from src.dy_data.douyin_client import DouyinCredentials, DouyinOpenApiClient


Collector = Callable[[Session, Any, CollectionWindow, str], PhaseStats]
BrowserExportRunner = Callable[[Session, str], PhaseStats | Any]
SettlementRunner = Callable[[Session, str], PhaseStats | Any]
SENSITIVE_ERROR_RE = re.compile(r"(?i)(cookie|token|secret|password|passwd|authorization|credential)")


def build_douyin_client_from_env() -> DouyinOpenApiClient:
    if _truthy(os.getenv("DY_WORKER_FAKE_DOUYIN")):
        return EmptyDouyinClient()  # type: ignore[return-value]

    app_id = douyin_app_id()
    app_secret = douyin_app_secret()
    account_id = douyin_account_id()
    missing = [
        name
        for name, value in (
            ("DOUYIN_APP_ID", app_id),
            ("DOUYIN_APP_SECRET", app_secret),
            ("DOUYIN_ACCOUNT_ID", account_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Set required Douyin collection environment variables: {', '.join(missing)}")
    return DouyinOpenApiClient(DouyinCredentials(app_id=str(app_id), app_secret=str(app_secret), account_id=str(account_id)))


def run_collection_job(
    session: Session,
    *,
    client: Any | None = None,
    window: CollectionWindow | None = None,
    job_id: str | None = None,
    collectors: Sequence[Collector] | None = None,
) -> CollectionStats:
    return _run_job(
        session,
        client=client,
        window=window,
        job_id=job_id,
        collectors=collectors,
        settlement_runner=None,
        job_name="douyin_collection",
    )


def run_collect_and_settle(
    session: Session,
    *,
    client: Any | None = None,
    window: CollectionWindow | None = None,
    job_id: str | None = None,
    include_browser_export: bool | None = None,
    include_materialization: bool = True,
    collectors: Sequence[Collector] | None = None,
    browser_export_runner: BrowserExportRunner | None = None,
    settlement_runner: SettlementRunner | None = None,
) -> CollectionStats:
    return _run_job(
        session,
        client=client,
        window=window,
        job_id=job_id,
        collectors=collectors,
        browser_export_runner=browser_export_runner,
        include_browser_export=include_browser_export,
        include_clue_center_rebuild=include_materialization,
        settlement_runner=(settlement_runner or _run_settlement_phase) if include_materialization else None,
        job_name="collect_and_settle",
    )


def default_collectors() -> list[Collector]:
    return [
        lambda session, client, window, source_run_id: collect_shop_pois(
            session, client, source_run_id=source_run_id
        ),
        lambda session, client, window, source_run_id: collect_aweme_bindings(
            session, client, source_run_id=source_run_id
        ),
        lambda session, client, window, source_run_id: collect_orders(
            session, client, window, source_run_id=source_run_id
        ),
        lambda session, client, window, source_run_id: collect_clues(
            session, client, window, source_run_id=source_run_id
        ),
        lambda session, client, window, source_run_id: collect_verify_records(
            session, client, window, source_run_id=source_run_id
        ),
    ]


def sanitize_error_message(message: str | None) -> str | None:
    if not message:
        return message
    if SENSITIVE_ERROR_RE.search(message):
        return "[redacted sensitive error]"
    return message[:1800]


class EmptyDouyinClient:
    """Offline fake client for Docker smoke tests; production must not enable it."""

    def iter_orders(self, start: Any, end: Any, *, page_size: int = 100):
        return iter(())

    def query_shop_pois(self, *, relation_type: int = 0, cursor: str | int | None = None) -> dict[str, Any]:
        return {"data": {"pois": [], "has_more": False}}

    def query_verify_records(
        self,
        start: Any,
        end: Any,
        *,
        poi_id: str | None = None,
        page_size: int = 20,
        cursor: str | int | None = None,
    ) -> dict[str, Any]:
        return {"data": {"verify_records": [], "has_more": False}}

    def query_craftsman_bind_info(self, *, cursor: str | int | None = None, size: int = 50) -> dict[str, Any]:
        return {"data": {"openapi_merchat_craftsman_info": [], "has_more": False}}

    def query_clues(self, start: Any, end: Any, *, page: int = 1, page_size: int = 100) -> dict[str, Any]:
        return {"data": {"clue_data": []}}

    def decrypt_mask_cipher_texts(self, cipher_texts: list[str]) -> dict[str, str]:
        _ = cipher_texts
        return {}

    def decrypt_cipher_texts(self, cipher_texts: list[str]) -> dict[str, str]:
        _ = cipher_texts
        return {}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _run_job(
    session: Session,
    *,
    client: Any | None,
    window: CollectionWindow | None,
    job_id: str | None,
    collectors: Sequence[Collector] | None,
    browser_export_runner: BrowserExportRunner | None = None,
    include_browser_export: bool | None = None,
    include_clue_center_rebuild: bool = True,
    settlement_runner: SettlementRunner | None,
    job_name: str,
) -> CollectionStats:
    source_window = window or resolve_collection_window()
    source_run_id = job_id or _job_id("collect")
    stats = CollectionStats(run_id=source_run_id, source_window=source_window)
    start_job_run(
        session,
        source_run_id,
        job_name,
        metadata_json=stats.as_metadata(),
    )
    try:
        active_client = client or build_douyin_client_from_env()
        active_collectors = default_collectors() if collectors is None else collectors
        for collector in active_collectors:
            stats.add_phase(collector(session, active_client, source_window, source_run_id))
        if include_clue_center_rebuild:
            stats.add_phase(_run_clue_center_rebuild_phase(session, source_run_id, active_client))
        if _include_browser_export(include_browser_export):
            runner = browser_export_runner or _run_browser_export_phase
            stats.add_phase(_coerce_browser_export_phase(runner(session, source_run_id)))
        if settlement_runner is not None:
            stats.add_phase(_coerce_settlement_phase(settlement_runner(session, source_run_id)))
            if include_clue_center_rebuild:
                stats.add_phase(_run_clue_master_rebuild_phase(session, source_run_id))
                stats.add_phase(_run_store_score_snapshot_phase(session, source_run_id))

        _set_job_metadata(session, source_run_id, stats.as_metadata())
        finish_job_run(
            session,
            source_run_id,
            status="success",
            success_count=stats.success_count,
            failed_count=stats.failed_count,
        )
        return stats
    except Exception as exc:
        _set_job_metadata(session, source_run_id, stats.as_metadata())
        finish_job_run(
            session,
            source_run_id,
            status="failed",
            success_count=stats.success_count,
            failed_count=max(1, stats.failed_count),
            error_message=sanitize_error_message(str(exc)),
        )
        raise


def _run_settlement_phase(session: Session, source_run_id: str) -> PhaseStats:
    result = rebuild_settlement(session, source_run_id=source_run_id)
    return PhaseStats(name="settlement", fetched=0, upserted=result.detail_count)


def _run_clue_center_rebuild_phase(
    session: Session,
    source_run_id: str,
    client: Any | None = None,
) -> PhaseStats:
    _ = source_run_id
    resolver = getattr(client, "decrypt_cipher_texts", None)
    result = rebuild_clue_center(
        session,
        phone_plain_resolver=resolver if callable(resolver) else None,
    )
    return PhaseStats(name="clue_center_rebuild", fetched=0, upserted=int(result.get("eligible_orders", 0) or 0))


def _run_clue_master_rebuild_phase(session: Session, source_run_id: str) -> PhaseStats:
    _ = source_run_id
    result = materialize_clue_master_leads(session)
    return PhaseStats(name="clue_master_rebuild", fetched=0, upserted=int(result.get("master_leads", 0) or 0))


def _run_store_score_snapshot_phase(session: Session, source_run_id: str) -> PhaseStats:
    _ = source_run_id
    result = refresh_due_store_score_snapshots(session)
    return PhaseStats(name="store_score_snapshot", fetched=0, upserted=int(result.get("snapshots", 0) or 0))


def _run_browser_export_phase(session: Session, source_run_id: str) -> PhaseStats:
    from apps.worker.browser_exports.backend_aweme import run_backend_aweme_export

    return run_backend_aweme_export(session, source_run_id=source_run_id)


def _coerce_browser_export_phase(result: PhaseStats | Any) -> PhaseStats:
    if isinstance(result, PhaseStats):
        return result
    return PhaseStats(
        name="backend_aweme_export",
        fetched=int(getattr(result, "fetched", 0) or 0),
        upserted=int(getattr(result, "upserted", 0) or 0),
        skipped=int(getattr(result, "skipped", 0) or 0),
        failed=int(getattr(result, "failed", 0) or 0),
    )


def _coerce_settlement_phase(result: PhaseStats | Any) -> PhaseStats:
    if isinstance(result, PhaseStats):
        return result
    return PhaseStats(name="settlement", fetched=0, upserted=int(getattr(result, "detail_count", 0) or 0))


def _include_browser_export(value: bool | None) -> bool:
    if value is not None:
        return value
    if _truthy(os.getenv("DY_WORKER_FAKE_DOUYIN")):
        return False
    if _truthy(os.getenv("WORKER_SKIP_BROWSER_EXPORT")):
        return False
    return True


def _set_job_metadata(session: Session, job_id: str, metadata: dict[str, Any]) -> None:
    from apps.api.dy_api.models import JobRun

    job = session.get(JobRun, job_id)
    if job is not None:
        job.metadata_json = metadata
        session.flush()


def _job_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{stamp}"
