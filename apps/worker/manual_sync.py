from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import JobRun
from apps.worker.browser_exports.backend_aweme import run_backend_aweme_export
from apps.worker.collectors.aweme_bindings import collect_aweme_bindings
from apps.worker.collectors.orders import collect_orders
from apps.worker.collectors.types import CollectionStats, CollectionWindow, PhaseStats
from apps.worker.collectors.verify_records import collect_shop_pois, collect_verify_records
from apps.worker.pipeline import build_douyin_client_from_env, run_collect_and_settle
from apps.worker.repositories import finish_job_run, start_job_run
from apps.worker.settlement import rebuild_settlement, run_settlement_job


ManualSyncTarget = Literal[
    "all",
    "orders",
    "verify_records",
    "shop_pois",
    "aweme_bindings",
    "backend_aweme_export",
    "settlement",
]

MANUAL_SYNC_TARGETS: tuple[ManualSyncTarget, ...] = (
    "all",
    "orders",
    "verify_records",
    "shop_pois",
    "aweme_bindings",
    "backend_aweme_export",
    "settlement",
)


def run_manual_sync_job(
    *,
    job_id: str,
    target: ManualSyncTarget,
    start: datetime,
    end: datetime,
    factory: sessionmaker | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> None:
    session_factory = factory or get_session_factory()
    if session_factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running manual sync.")

    window = CollectionWindow(start=start, end=end, timezone_name=timezone_name)
    if target == "settlement":
        with session_scope(session_factory) as session:
            run_settlement_job(session, job_id=job_id, source_run_id=job_id)
        return

    with session_scope(session_factory) as session:
        if target == "all":
            run_collect_and_settle(
                session,
                window=window,
                job_id=job_id,
                include_browser_export=False,
            )
            return

        if target == "backend_aweme_export":
            stats = CollectionStats(run_id=job_id, source_window=window)
            start_job_run(
                session,
                job_id,
                "manual_backend_aweme_export",
                metadata_json=stats.as_metadata(),
            )
            try:
                stats.add_phase(run_backend_aweme_export(session, source_run_id=job_id))
                settlement_stats = rebuild_settlement(session, source_run_id=job_id)
                stats.add_phase(PhaseStats(name="settlement", upserted=settlement_stats.detail_count))
                job = session.get(JobRun, job_id)
                if job is not None:
                    job.metadata_json = stats.as_metadata()
                finish_job_run(session, job_id, status="success", success_count=stats.success_count)
            except Exception as exc:
                finish_job_run(session, job_id, status="failed", failed_count=1, error_message=str(exc))
                raise
            return

        client = build_douyin_client_from_env()
        collector = _collector_for_target(target)
        run_collect_and_settle(
            session,
            client=client,
            window=window,
            job_id=job_id,
            collectors=[collector],
            include_browser_export=False,
        )


def _collector_for_target(target: ManualSyncTarget):
    if target == "orders":
        return lambda session, client, window, source_run_id: collect_orders(
            session,
            client,
            window,
            source_run_id=source_run_id,
        )
    if target == "verify_records":
        return lambda session, client, window, source_run_id: collect_verify_records(
            session,
            client,
            window,
            source_run_id=source_run_id,
        )
    if target == "shop_pois":
        return lambda session, client, window, source_run_id: collect_shop_pois(
            session,
            client,
            source_run_id=source_run_id,
        )
    if target == "aweme_bindings":
        return lambda session, client, window, source_run_id: collect_aweme_bindings(
            session,
            client,
            source_run_id=source_run_id,
        )
    raise ValueError(f"Unsupported manual sync target: {target}")
