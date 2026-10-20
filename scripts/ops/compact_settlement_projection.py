"""Ops entrypoint for the claimable settlement compaction runner.

Queues (idempotently), claims and runs one settlement compaction job against
the active settlement head, then publishes the verified compact head through
``publish_settlement_compaction``.  Run only during an authorized low-write
maintenance window; the command never writes fee, statement, confirmation or
invoice rows and never mutates the active pointer outside the audited
publisher.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.dy_api.db import get_session_factory  # noqa: E402
from apps.api.dy_api.models import SettlementProjectionActive  # noqa: E402
from apps.ops_agent.resources import ResourceAction  # noqa: E402
from apps.worker.legacy_projection_bootstrap import ResourceGateConfig  # noqa: E402
from apps.worker.resource_monitor import (  # noqa: E402
    current_resource_decision,
    start_resource_monitor,
)
from apps.worker.settlement_compaction import (  # noqa: E402
    DEFAULT_SETTLEMENT_COMPACTION_LEASE,
    claim_settlement_compaction_job,
    enqueue_settlement_compaction_job,
    run_settlement_compaction_job,
)

PROTOCOL = "dydata-settlement-compaction-ops-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compact and publish the active settlement lineage under a durable "
            "job claim. Requires an authorized maintenance window."
        )
    )
    parser.add_argument("--batch-size", required=True, type=int)
    parser.add_argument("--max-manifest-rows", required=True, type=int)
    parser.add_argument("--max-estimated-write-bytes", required=True, type=int)
    parser.add_argument("--max-estimated-wal-bytes", required=True, type=int)
    parser.add_argument("--observed-disk-headroom-bytes", required=True, type=int)
    parser.add_argument("--min-disk-headroom-bytes", required=True, type=int)
    parser.add_argument("--lease-minutes", type=int, default=30)
    parser.add_argument(
        "--admission-wait-seconds",
        type=int,
        default=90,
        help=(
            "Bounded wait for a real healthy resource observation before "
            "claiming; never bypasses the guard."
        ),
    )
    parser.add_argument(
        "--base-generation-id",
        default=None,
        help=(
            "Optional explicit base; defaults to the current active settlement "
            "pointer inside the enqueue transaction."
        ),
    )
    return parser


def _emit(payload: dict[str, object], *, error: bool = False) -> int:
    stream = sys.stderr if error else sys.stdout
    print(json.dumps(payload, sort_keys=True), file=stream)
    return 1 if error else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        return _emit(
            {"protocol": PROTOCOL, "status": "error", "error_type": "database_not_configured"},
            error=True,
        )
    limits = ResourceGateConfig(
        max_manifest_rows=args.max_manifest_rows,
        max_estimated_write_bytes=args.max_estimated_write_bytes,
        max_estimated_wal_bytes=args.max_estimated_wal_bytes,
        observed_disk_headroom_bytes=args.observed_disk_headroom_bytes,
        min_disk_headroom_bytes=args.min_disk_headroom_bytes,
    )
    # Real resource admission: start the existing ResourceMonitor flow (a no-op
    # when WORKER_RESOURCE_GUARD_ENABLED is off) and keep it alive for the whole
    # run.  The monitor boots in its protected state, so the bounded wait below
    # exists to observe a genuine healthy sample / recovery dwell before the
    # claim — the decision itself always comes from the monitor, never from a
    # hand-constructed ALLOW, and the guard is never disabled here.
    monitor = start_resource_monitor(factory)
    try:
        if args.base_generation_id is not None:
            base = args.base_generation_id
        else:
            with factory() as session:
                active = session.get(SettlementProjectionActive, "settlement")
                if active is None or active.generation_id is None:
                    return _emit(
                        {
                            "protocol": PROTOCOL,
                            "status": "error",
                            "error_type": "active_pointer_missing",
                        },
                        error=True,
                    )
                base = active.generation_id
        job_id = enqueue_settlement_compaction_job(
            factory,
            base_generation_id=base,
            batch_size=args.batch_size,
            resource_limits=limits,
        )
        if monitor is not None:
            deadline = time.monotonic() + args.admission_wait_seconds
            while True:
                decision = current_resource_decision()
                if decision.action == ResourceAction.ALLOW:
                    break
                if time.monotonic() >= deadline:
                    return _emit(
                        {
                            "protocol": PROTOCOL,
                            "status": "not_claimed",
                            "job_id": job_id,
                            "reason": (
                                "resource guard did not observe a healthy "
                                "sample within the bounded wait"
                            ),
                            "resource_action": getattr(
                                decision.action, "value", str(decision.action)
                            ),
                            "resource_reasons": list(decision.reasons),
                        }
                    )
                time.sleep(1)
        # Claim exactly this job: a shared-heavy-slot refusal returns None and
        # leaves the queued row untouched — never a claimed-but-unexecuted job.
        # resource_decision=None resolves the real current_resource_decision()
        # inside the claim (STOP when the guard is on but the monitor is
        # missing or stale), so admission is never bypassed.
        claimed = claim_settlement_compaction_job(
            factory,
            lease_duration=timedelta(minutes=args.lease_minutes),
            job_id=job_id,
        )
        if claimed is None:
            return _emit(
                {
                    "protocol": PROTOCOL,
                    "status": "not_claimed",
                    "job_id": job_id,
                    "reason": (
                        "job not claimable: another heavy job holds the slot, "
                        "rate-limit cooldown is active, resource admission "
                        "refused, or the job is running"
                    ),
                }
            )
        claimed_job_id, claim_id = claimed
        if claimed_job_id != job_id:
            return _emit(
                {
                    "protocol": PROTOCOL,
                    "status": "error",
                    "error_type": "claim_mismatch",
                    "job_id": job_id,
                    "claimed_job_id": claimed_job_id,
                },
                error=True,
            )
        result = run_settlement_compaction_job(
            job_id=job_id,
            factory=factory,
            claim_id=claim_id,
            lease_duration=timedelta(minutes=args.lease_minutes),
        )
        return _emit({"protocol": PROTOCOL, "job_id": job_id, **result})
    except Exception as exc:
        return _emit(
            {
                "protocol": PROTOCOL,
                "status": "error",
                "error_type": type(exc).__name__,
                "detail": str(exc)[:500],
            },
            error=True,
        )
    finally:
        if monitor is not None:
            monitor.stop()


if __name__ == "__main__":  # pragma: no cover - manual ops entrypoint
    raise SystemExit(main())
