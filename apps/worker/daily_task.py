"""Daily child-process entry point and default stage adapters."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import get_session_factory
from apps.api.dy_api.models import JobImpact, JobRun
from apps.worker import pipeline
from apps.worker.clue_allocation import (
    materialize_clue_master_leads,
    run_incremental_clue_materialization,
)
from apps.worker.clue_center import refresh_clue_center_projection
from apps.worker.clue_allocation import refresh_due_store_score_snapshots
from apps.worker.collectors.types import CollectionStats, CollectionWindow, PhaseStats
from apps.worker.daily_windows import parent_required_stages
from apps.worker.settlement import rebuild_settlement
from apps.worker.stage_runner import (
    DailyStageResult,
    is_daily_execution_lease_live,
    run_daily_stages,
)

VERIFICATION_ORDER_BATCH_SIZE = 64
VERIFICATION_IMPACT_BATCH_SIZE = 64
SETTLEMENT_IMPACT_BATCH_SIZE = 64
SETTLEMENT_COUPON_BATCH_SIZE = 64


def execute_daily_task(
    job_id: str,
    *,
    session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
    handlers: Mapping[str, Callable[..., Any]] | None = None,
    client: Any | None = None,
    allow_unfenced_test: bool = False,
) -> DailyStageResult:
    """Execute one planned date job in isolated stage Sessions.

    The production CLI is fail-closed: a child must receive the lease token
    injected by the supervisor.  Unit tests that exercise stage adapters may
    opt into an unfenced run explicitly with ``allow_unfenced_test=True``.
    """

    factory = session_factory or get_session_factory()
    if factory is None:
        raise RuntimeError("Set a worker database URL before running a daily task")
    lease_owner = os.getenv("DY_WORKER_LEASE_OWNER")
    lease_epoch = os.getenv("DY_WORKER_LEASE_EPOCH")
    attempt_id = os.getenv("DY_WORKER_ATTEMPT_ID")
    component_instance_id = os.getenv("DY_WORKER_COMPONENT_ID")
    token_values = (lease_owner, lease_epoch, attempt_id, component_instance_id)
    if not all(token_values):
        if not allow_unfenced_test or any(token_values):
            raise RuntimeError(
                "daily child requires DY_WORKER_LEASE_OWNER, DY_WORKER_LEASE_EPOCH, "
                "DY_WORKER_ATTEMPT_ID, and DY_WORKER_COMPONENT_ID"
            )
    with _session_scope(factory) as metadata_session:
        job = metadata_session.get(JobRun, job_id)
        if job is None:
            raise ValueError(f"Unknown daily job: {job_id}")
        required_stages = _required_stages_for_job(job)
    if handlers is None and job.job_kind == "finalize":
        from apps.worker.finalize import FenceToken, run_finalize_stage
        from apps.worker.task_control import LeaseToken

        if not all(token_values):
            raise RuntimeError("finalize child requires a complete execution fence")
        live_token = LeaseToken(
            job_id=job.job_id,
            attempt_id=str(attempt_id),
            attempt_number=int(job.attempt_count or 0),
            lease_owner=str(lease_owner),
            lease_epoch=int(lease_epoch),
            component_instance_id=str(component_instance_id),
            business_date=job.business_date,
            current_stage="finalize",
        )
        fence_token = FenceToken.from_job(job, live_token)

        def finalize_handler(_session: Session, _job: JobRun):
            return run_finalize_stage(
                factory,
                parent_job_id=str(job.parent_job_id),
                fence_token=fence_token,
            )

        finalize_handler.requires_independent_sessions = True
        active_handlers = {"finalize": finalize_handler}
    else:
        active_handlers = handlers or default_stage_handlers(client=client)
    active_handlers = {
        stage_name: active_handlers[stage_name]
        for stage_name in required_stages
        if stage_name in active_handlers
    }
    return run_daily_stages(
        factory,
        job_id=job_id,
        handlers=active_handlers,
        lease_owner=lease_owner,
        lease_epoch=int(lease_epoch) if lease_epoch else None,
        attempt_id=attempt_id,
        component_instance_id=component_instance_id,
        stage_order=required_stages,
    )


def default_stage_handlers(*, client: Any | None = None) -> dict[str, Callable[..., Any]]:
    """Build adapters for existing collect/materialize/settle business code."""

    active_client = client

    def ensure_client() -> Any:
        nonlocal active_client
        if active_client is None:
            active_client = pipeline.build_douyin_client_from_env()
        return active_client

    def collect(session: Session, job) -> dict[str, Any]:
        source_window = _job_window(job)
        stats = CollectionStats(run_id=job.job_id, source_window=source_window)
        target = _job_target(job)
        selected_targets = {
            "all": {"orders", "refunds", "clues", "verify_records"},
            "orders": {"orders"},
            "refunds": {"refunds"},
            "clues": {"clues"},
            "verify_records": {"verify_records"},
            "shop_pois": {"shop_pois"},
            "aweme_bindings": {"aweme_bindings"},
        }.get(target, set())
        current_client = ensure_client()
        collector_names = (
            "shop_pois",
            "aweme_bindings",
            "orders",
            "refunds",
            "clues",
            "verify_records",
        )
        for collector_name, collector in zip(collector_names, pipeline.default_collectors()):
            if collector_name not in selected_targets:
                continue
            stats.add_phase(collector(session, current_client, source_window, job.job_id))
        return stats.as_metadata()

    def collect_dimensions(session: Session, job) -> dict[str, Any]:
        target = _job_target(job)
        if target == "backend_aweme_export":
            from apps.worker.browser_exports.backend_aweme import run_backend_aweme_export

            return run_backend_aweme_export(
                session,
                source_run_id=job.job_id,
            ).as_metadata()
        source_targets = {
            "all": {"shop_pois", "aweme_bindings"},
            "shop_pois": {"shop_pois"},
            "aweme_bindings": {"aweme_bindings"},
        }.get(target, set())
        current_client = ensure_client()
        source_window = _job_window(job)
        stats = CollectionStats(run_id=job.job_id, source_window=source_window)
        collector_names = (
            "shop_pois",
            "aweme_bindings",
            "orders",
            "refunds",
            "clues",
            "verify_records",
        )
        for collector_name, collector in zip(collector_names, pipeline.default_collectors()):
            if collector_name in source_targets:
                stats.add_phase(collector(session, current_client, source_window, job.job_id))
        return stats.as_metadata()

    def materialize(session: Session, job) -> dict[str, Any]:
        current_client = ensure_client()
        if _incremental_materialization_enabled(job):
            attempt_token = str(os.getenv("DY_WORKER_ATTEMPT_ID") or "").strip()
            if not attempt_token:
                raise RuntimeError(
                    "incremental clue materialization requires DY_WORKER_ATTEMPT_ID"
                )
            resolver = getattr(current_client, "decrypt_cipher_texts", None)
            result = run_incremental_clue_materialization(
                _session_factory_for(session),
                scope=_materialization_scope(job),
                lease_token=attempt_token,
                now=datetime.now(UTC),
                phone_plain_resolver=resolver if callable(resolver) else None,
                page_fence=_daily_page_fence(session, job),
            )
            return {
                "master": result,
                "center": {
                    "mode": "per_page",
                    "eligible_orders": int(result.get("center_orders", 0) or 0),
                },
            }
        master = materialize_clue_master_leads(session)
        resolver = getattr(current_client, "decrypt_cipher_texts", None)
        center = refresh_clue_center_projection(
            session,
            phone_plain_resolver=resolver if callable(resolver) else None,
        )
        return {"master": master, "center": center}

    def settle(session: Session, job) -> dict[str, Any]:
        incremental = _incremental_settlement_enabled(job)
        if incremental:
            from apps.worker.settlement import settle_impacted_coupons

            kernel_summary = settle_impacted_coupons(
                _session_factory_for(session),
                source_run_id=job.job_id,
                page_fence=_daily_page_fence(session, job),
                impact_batch_size=SETTLEMENT_IMPACT_BATCH_SIZE,
                coupon_batch_size=SETTLEMENT_COUPON_BATCH_SIZE,
            )
            if not kernel_summary.get("completed"):
                raise RuntimeError("incremental settlement did not complete")
            settlement_summary = {
                **_normalize_incremental_settlement_summary(kernel_summary),
                "mode": "incremental",
                "completed": True,
            }
        else:
            stats = rebuild_settlement(session, source_run_id=job.job_id)
            settlement_summary = {
                "mode": "legacy",
                "completed": True,
                "detail_count": int(stats.detail_count),
            }

        settlement_output = {
            "detail_count": int(settlement_summary.get("detail_count", 0) or 0),
            "settlement_summary": settlement_summary,
        }
        if _job_target(job) in {"settlement", "backend_aweme_export"}:
            if incremental:
                settlement_output["store_score_snapshot"] = (
                    _deferred_store_score_snapshot_metadata(settlement_summary)
                )
            return settlement_output
        if incremental:
            current_client = ensure_client()
            resolver = getattr(current_client, "decrypt_cipher_texts", None)
            operation_factory = _session_factory_for(session)
            page_fence = _daily_page_fence(session, job)
            verification_delta = _run_verification_projection_delta_batched(
                operation_factory,
                job,
                page_fence=page_fence,
                phone_plain_resolver=resolver if callable(resolver) else None,
            )
            snapshots = _deferred_store_score_snapshot_metadata(settlement_summary)
            return {
                **settlement_output,
                "verification_projection_delta": verification_delta,
                "clue_follow_up_due": {
                    "disabled": True,
                    "reason": "automatic_reallocation_disabled",
                },
                "store_score_snapshot": snapshots,
            }
        master_refresh = materialize_clue_master_leads(session)
        if master_refresh.get("skipped"):
            return {
                **settlement_output,
                "master_refresh": master_refresh,
                "clue_center_refresh": {"skipped": "locked"},
                "clue_follow_up_due": {"skipped": "locked"},
                "store_score_snapshot": {"skipped": "locked"},
            }
        current_client = ensure_client()
        resolver = getattr(current_client, "decrypt_cipher_texts", None)
        center_refresh = refresh_clue_center_projection(
            session,
            phone_plain_resolver=resolver if callable(resolver) else None,
        )
        snapshots = refresh_due_store_score_snapshots(session)
        return {
            **settlement_output,
            "master_refresh": master_refresh,
            "clue_center_refresh": center_refresh,
            "clue_follow_up_due": {
                "disabled": True,
                "reason": "automatic_reallocation_disabled",
            },
            "store_score_snapshot": snapshots,
        }

    # The stage runner releases its stage transaction before this handler when
    # the explicit incremental mode is enabled.  The legacy default remains a
    # single stage transaction for compatibility.
    materialize.requires_independent_sessions = _incremental_materialization_enabled
    settle.requires_independent_sessions = _incremental_settlement_enabled

    return {
        "collect": collect,
        "collect_dimensions": collect_dimensions,
        "materialize": materialize,
        "settle": settle,
    }


def _incremental_materialization_enabled(job: Any) -> bool:
    metadata = getattr(job, "metadata_json", None) or {}
    return bool(
        metadata.get("clue_materialization_mode") == "incremental"
        or metadata.get("incremental_materialization") is True
    )


def _incremental_settlement_enabled(job: Any) -> bool:
    metadata = getattr(job, "metadata_json", None) or {}
    return bool(
        metadata.get("settlement_mode") == "incremental"
        or metadata.get("incremental_settlement") is True
    )


def _materialization_scope(job: Any) -> str:
    metadata = getattr(job, "metadata_json", None) or {}
    value = metadata.get("clue_materialization_scope")
    return str(value or "clue_materialization")


def _session_factory_for(session: Session) -> sessionmaker[Session]:
    return sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def _daily_page_fence(session: Session, job: Any) -> Callable[[Session], bool]:
    lease_owner = os.getenv("DY_WORKER_LEASE_OWNER")
    lease_epoch_raw = os.getenv("DY_WORKER_LEASE_EPOCH")
    attempt_id = os.getenv("DY_WORKER_ATTEMPT_ID")
    component_instance_id = os.getenv("DY_WORKER_COMPONENT_ID")
    lease_epoch = int(lease_epoch_raw) if lease_epoch_raw else None

    def fence(page_session: Session) -> bool:
        return is_daily_execution_lease_live(
            page_session,
            job_id=str(job.job_id),
            lease_owner=lease_owner,
            lease_epoch=lease_epoch,
            attempt_id=attempt_id,
            component_instance_id=component_instance_id,
            lock=True,
        )

    return fence


def _run_independent_operation(
    session_factory: sessionmaker[Session] | Callable[[], Session],
    operation: Callable[[Session], Any],
    *,
    page_fence: Callable[[Session], bool] | None,
    operation_name: str,
) -> Any:
    """Run one post-settlement operation in its own fenced transaction."""

    operation_session = session_factory()
    try:
        operation_session.begin()
        if page_fence is not None and not page_fence(operation_session):
            raise RuntimeError(f"lease fence rejected before {operation_name}")
        result = operation(operation_session)
        if page_fence is not None and not page_fence(operation_session):
            raise RuntimeError(f"lease fence rejected before {operation_name} commit")
        operation_session.commit()
    except BaseException:
        try:
            operation_session.rollback()
        finally:
            operation_session.close()
        raise
    else:
        operation_session.close()
    return result


def _deferred_store_score_snapshot_metadata(
    settlement_summary: Mapping[str, Any],
) -> dict[str, Any]:
    affected_store_ids = sorted(
        {
            str(store_id)
            for store_id in settlement_summary.get("affected_store_ids", []) or []
            if store_id not in (None, "")
        }
    )
    return {
        "deferred": True,
        "consumer": "T3.4.finalize",
        "affected_store_ids": affected_store_ids,
        "rule_closure": (
            "T3.4 computes the published rule-generation and eligible-store "
            "closure after all daily dates succeed"
        ),
    }


def _normalize_incremental_settlement_summary(
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and canonicalize the kernel summary before checkpointing.

    ``completed`` here is the settlement-kernel fact that the frozen impact
    stream was fully consumed.  The stage runner writes its separate
    ``status=success`` only after verification, due transitions, and deferred
    metadata also finish.
    """

    required = {
        "impact_count",
        "coupon_count",
        "detail_count",
        "result_count",
        "adjustment_count",
        "last_impact_id",
        "affected_months",
        "affected_store_ids",
        "completed",
    }
    missing = sorted(name for name in required if name not in summary)
    if missing:
        raise RuntimeError(
            "incremental settlement summary missing fields: " + ", ".join(missing)
        )
    if summary.get("completed") is not True:
        raise RuntimeError("incremental settlement summary is not complete")

    def bounded_count(name: str) -> int:
        try:
            value = int(summary[name])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"incremental settlement summary has invalid {name}"
            ) from exc
        if value < 0:
            raise RuntimeError(f"incremental settlement summary has negative {name}")
        return value

    def canonical_dimensions(name: str) -> list[str]:
        values = summary[name]
        if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set)):
            raise RuntimeError(f"incremental settlement summary has invalid {name}")
        return sorted(
            {
                str(value)
                for value in values
                if value not in (None, "")
            }
        )

    try:
        last_impact_id = int(summary["last_impact_id"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "incremental settlement summary has invalid last_impact_id"
        ) from exc
    if last_impact_id < 0:
        raise RuntimeError("incremental settlement summary has negative last_impact_id")
    return {
        **summary,
        "impact_count": bounded_count("impact_count"),
        "coupon_count": bounded_count("coupon_count"),
        "detail_count": bounded_count("detail_count"),
        "result_count": bounded_count("result_count"),
        "adjustment_count": bounded_count("adjustment_count"),
        "last_impact_id": last_impact_id,
        "affected_months": canonical_dimensions("affected_months"),
        "affected_store_ids": canonical_dimensions("affected_store_ids"),
        "completed": True,
    }


def _run_verification_projection_delta_batched(
    session_factory: sessionmaker[Session] | Callable[[], Session],
    job: Any,
    *,
    page_fence: Callable[[Session], bool] | None,
    phone_plain_resolver: Callable[[list[str]], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Process impact selection and each order write batch in short Sessions.

    ``order_count`` is the sum of page-local de-duplicated order batches.  If
    an order is affected on multiple impact pages, each page contributes one
    processing attempt; no all-day order set is retained in memory.
    """

    impact_cursor = 0
    upper_bound: int | None = None
    totals = {
        "impact_count": 0,
        "order_count": 0,
        "master": {"master_leads": 0, "closed_leads": 0, "headquarters_pool": 0},
        "center": {"eligible_orders": 0, "assignment_rounds": 0},
    }
    while True:
        page = _run_independent_operation(
            session_factory,
            lambda operation_session: _select_verification_projection_page(
                operation_session,
                job,
                impact_cursor=impact_cursor,
                upper_bound=upper_bound,
            ),
            page_fence=page_fence,
            operation_name=f"verification projection delta page {impact_cursor}",
        )
        if upper_bound is None:
            upper_bound = page["upper_bound"]
        totals["impact_count"] += int(page["impact_count"])
        bounded_orders = page["order_ids"]
        for offset in range(0, len(bounded_orders), VERIFICATION_ORDER_BATCH_SIZE):
            order_batch = set(
                bounded_orders[offset : offset + VERIFICATION_ORDER_BATCH_SIZE]
            )
            batch = _run_independent_operation(
                session_factory,
                lambda operation_session, order_batch=order_batch: _run_verification_order_batch(
                    operation_session,
                    order_batch,
                    phone_plain_resolver=phone_plain_resolver,
                ),
                page_fence=page_fence,
                operation_name=(
                    f"verification projection order batch {impact_cursor}:{offset}"
                ),
            )
            totals["order_count"] += int(batch["order_count"])
            for key in totals["master"]:
                totals["master"][key] += int(batch["master"].get(key, 0) or 0)
            for key in totals["center"]:
                totals["center"][key] += int(batch["center"].get(key, 0) or 0)
        impact_cursor = int(page["last_impact_id"])
        if not page["has_more"]:
            break

    if totals["impact_count"] == 0:
        return {
            "mode": "verification_projection_delta",
            "impact_count": 0,
            "order_count": 0,
            "skipped": "no_verification_delta",
        }
    return {
        "mode": "verification_projection_delta",
        **totals,
    }


def _select_verification_projection_page(
    session: Session,
    job: Any,
    *,
    impact_cursor: int,
    upper_bound: int | None,
) -> dict[str, Any]:
    """Select one bounded impact page without retaining write-side ORM state."""

    if upper_bound is None:
        upper_bound = int(
            session.scalar(
                select(func.max(JobImpact.id)).where(
                    JobImpact.source_run_id == str(job.job_id),
                    JobImpact.entity_type == "verify",
                )
            )
            or 0
        )
    if not upper_bound:
        return {
            "upper_bound": upper_bound,
            "impact_count": 0,
            "order_ids": [],
            "last_impact_id": impact_cursor,
            "has_more": False,
        }
    impacts = list(
        session.scalars(
            select(JobImpact)
            .where(
                JobImpact.source_run_id == str(job.job_id),
                JobImpact.entity_type == "verify",
                JobImpact.id > impact_cursor,
                JobImpact.id <= upper_bound,
            )
            .order_by(JobImpact.id)
            .limit(VERIFICATION_IMPACT_BATCH_SIZE)
        )
    )
    if not impacts:
        return {
            "upper_bound": upper_bound,
            "impact_count": 0,
            "order_ids": [],
            "last_impact_id": impact_cursor,
            "has_more": False,
        }
    order_ids: set[str] = set()
    for impact in impacts:
        closure = impact.affected_closure_json or {}
        order_ids.update(
            str(value)
            for value in closure.get("order_ids", []) or []
            if value not in (None, "")
        )
        order_id = (impact.new_values_json or {}).get("order_id")
        if order_id not in (None, ""):
            order_ids.add(str(order_id))
    last_impact_id = int(impacts[-1].id or impact_cursor)
    return {
        "upper_bound": upper_bound,
        "impact_count": len(impacts),
        "order_ids": sorted(order_ids),
        "last_impact_id": last_impact_id,
        "has_more": last_impact_id < upper_bound,
    }


def _run_verification_order_batch(
    session: Session,
    order_ids: set[str],
    *,
    phone_plain_resolver: Callable[[list[str]], dict[str, str]] | None,
) -> dict[str, Any]:
    master_summary = {
        "master_leads": 0,
        "closed_leads": 0,
        "headquarters_pool": 0,
    }
    center_summary = {
        "eligible_orders": 0,
        "assignment_rounds": 0,
    }
    master = materialize_clue_master_leads(
        session,
        now=datetime.now(UTC),
        order_ids=order_ids,
    )
    if master.get("skipped") == "locked":
        raise RuntimeError("clue master materialization lock unavailable")
    for key in master_summary:
        master_summary[key] += int(master.get(key, 0) or 0)
    center = refresh_clue_center_projection(
        session,
        phone_plain_resolver=phone_plain_resolver,
        order_ids=order_ids,
    )
    for key in center_summary:
        center_summary[key] += int(center.get(key, 0) or 0)
    return {
        "order_count": len(order_ids),
        "master": master_summary,
        "center": center_summary,
    }


def _run_verification_projection_page(
    session: Session,
    job: Any,
    *,
    impact_cursor: int,
    upper_bound: int | None,
    phone_plain_resolver: Callable[[list[str]], dict[str, str]] | None,
) -> dict[str, Any]:
    if upper_bound is None:
        upper_bound = int(
            session.scalar(
                select(func.max(JobImpact.id)).where(
                    JobImpact.source_run_id == str(job.job_id),
                    JobImpact.entity_type == "verify",
                )
            )
            or 0
        )
    if not upper_bound:
        return {
            "upper_bound": upper_bound,
            "impact_count": 0,
            "order_count": 0,
            "last_impact_id": impact_cursor,
            "has_more": False,
            "master": {},
            "center": {},
        }

    impacts = list(
        session.scalars(
            select(JobImpact)
            .where(
                JobImpact.source_run_id == str(job.job_id),
                JobImpact.entity_type == "verify",
                JobImpact.id > impact_cursor,
                JobImpact.id <= upper_bound,
            )
            .order_by(JobImpact.id)
            .limit(VERIFICATION_IMPACT_BATCH_SIZE)
        )
    )
    if not impacts:
        return {
            "upper_bound": upper_bound,
            "impact_count": 0,
            "order_count": 0,
            "last_impact_id": impact_cursor,
            "has_more": False,
            "master": {},
            "center": {},
        }

    order_ids: set[str] = set()
    for impact in impacts:
        closure = impact.affected_closure_json or {}
        order_ids.update(
            str(value)
            for value in closure.get("order_ids", []) or []
            if value not in (None, "")
        )
        order_id = (impact.new_values_json or {}).get("order_id")
        if order_id not in (None, ""):
            order_ids.add(str(order_id))

    master_summary = {
        "master_leads": 0,
        "closed_leads": 0,
        "headquarters_pool": 0,
    }
    center_summary = {
        "eligible_orders": 0,
        "assignment_rounds": 0,
    }
    order_count = 0
    bounded_orders = sorted(order_ids)
    for offset in range(0, len(bounded_orders), VERIFICATION_ORDER_BATCH_SIZE):
        order_batch = set(bounded_orders[offset : offset + VERIFICATION_ORDER_BATCH_SIZE])
        order_count += len(order_batch)
        master = materialize_clue_master_leads(
            session,
            now=datetime.now(UTC),
            order_ids=order_batch,
        )
        if master.get("skipped") == "locked":
            raise RuntimeError("clue master materialization lock unavailable")
        for key in master_summary:
            master_summary[key] += int(master.get(key, 0) or 0)
        center = refresh_clue_center_projection(
            session,
            phone_plain_resolver=phone_plain_resolver,
            order_ids=order_batch,
        )
        for key in center_summary:
            center_summary[key] += int(center.get(key, 0) or 0)

    last_impact_id = int(impacts[-1].id or impact_cursor)
    return {
        "upper_bound": upper_bound,
        "impact_count": len(impacts),
        "order_count": order_count,
        "last_impact_id": last_impact_id,
        "has_more": last_impact_id < upper_bound,
        "master": master_summary,
        "center": center_summary,
    }


def _run_verification_projection_delta(
    session: Session,
    job: Any,
    *,
    phone_plain_resolver: Callable[[list[str]], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compatibility adapter using bounded local pages in the supplied Session."""

    impact_cursor = 0
    upper_bound: int | None = None
    totals = {
        "impact_count": 0,
        "order_count": 0,
        "master": {"master_leads": 0, "closed_leads": 0, "headquarters_pool": 0},
        "center": {"eligible_orders": 0, "assignment_rounds": 0},
    }
    while True:
        page = _run_verification_projection_page(
            session,
            job,
            impact_cursor=impact_cursor,
            upper_bound=upper_bound,
            phone_plain_resolver=phone_plain_resolver,
        )
        if upper_bound is None:
            upper_bound = page["upper_bound"]
        totals["impact_count"] += int(page["impact_count"])
        totals["order_count"] += int(page["order_count"])
        for key in totals["master"]:
            totals["master"][key] += int(page["master"].get(key, 0) or 0)
        for key in totals["center"]:
            totals["center"][key] += int(page["center"].get(key, 0) or 0)
        impact_cursor = int(page["last_impact_id"])
        if not page["has_more"]:
            break
    if totals["impact_count"] == 0:
        return {
            "mode": "verification_projection_delta",
            "impact_count": 0,
            "order_count": 0,
            "skipped": "no_verification_delta",
        }
    return {"mode": "verification_projection_delta", **totals}


def _session_scope(factory):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    return scope()


def _job_target(job) -> str:
    target = (getattr(job, "metadata_json", None) or {}).get("target")
    return str(target or "all")


def _required_stages_for_job(job) -> tuple[str, ...]:
    configured = (getattr(job, "metadata_json", None) or {}).get("required_stages")
    if isinstance(configured, list) and configured:
        return tuple(str(stage) for stage in configured)
    if getattr(job, "job_kind", None) == "parent_sync":
        return parent_required_stages(_job_target(job))
    target = _job_target(job)
    if target == "settlement":
        return ("settle",)
    if target == "clue_center":
        return ("materialize",)
    return ("collect", "materialize", "settle")


def _job_window(job) -> CollectionWindow:
    if job.window_start is None or job.window_end is None:
        raise ValueError(f"daily job has no closed Shanghai window: {job.job_id}")
    start = _as_shanghai(job.window_start)
    end = _as_shanghai(job.window_end)
    return CollectionWindow(
        start=start,
        end=end,
        timezone_name="Asia/Shanghai",
    )


def _as_shanghai(value: datetime) -> datetime:
    from zoneinfo import ZoneInfo

    timezone = ZoneInfo("Asia/Shanghai")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one dy-data daily sync child")
    parser.add_argument("--job-id")
    args = parser.parse_args(argv)
    job_id = args.job_id or os.getenv("DY_WORKER_JOB_ID")
    if not job_id:
        parser.error("--job-id or DY_WORKER_JOB_ID is required")
    execute_daily_task(job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
