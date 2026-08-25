from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy.orm import Session

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.clue_allocation import (
    materialize_clue_master_leads,
    refresh_due_store_score_snapshots,
)
from apps.worker.clue_center import rebuild_clue_center
from apps.worker.clue_follow_up_state import process_due_transitions
from apps.worker.pipeline import build_douyin_client_from_env
from apps.worker.settlement import rebuild_settlement


MATERIALIZATION_STAGES = (
    "clue_master_rebuild",
    "clue_center_rebuild",
    "settlement",
    "clue_master_refresh",
    "clue_center_refresh",
    "clue_follow_up_due",
    "store_score_snapshot",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one materialization stage and exit.")
    parser.add_argument("--job-id", required=True, help="Parent materialization job id.")
    parser.add_argument("--stage", required=True, choices=MATERIALIZATION_STAGES)
    return parser.parse_args(argv)


def run_materialization_stage(
    session: Session,
    *,
    stage: str,
    source_run_id: str,
) -> Any:
    if stage in {"clue_master_rebuild", "clue_master_refresh"}:
        return materialize_clue_master_leads(session)
    if stage in {"clue_center_rebuild", "clue_center_refresh"}:
        client = build_douyin_client_from_env()
        resolver = getattr(client, "decrypt_cipher_texts", None)
        return rebuild_clue_center(
            session,
            phone_plain_resolver=resolver if callable(resolver) else None,
        )
    if stage == "settlement":
        return rebuild_settlement(session, source_run_id=source_run_id)
    if stage == "clue_follow_up_due":
        return process_due_transitions(session)
    if stage == "store_score_snapshot":
        return refresh_due_store_score_snapshots(session)
    raise ValueError(f"Unsupported materialization stage: {stage}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before materialization.")

    with session_scope(factory) as session:
        result = run_materialization_stage(
            session,
            stage=args.stage,
            source_run_id=args.job_id,
        )
    payload = _json_payload(result)
    print(
        json.dumps(
            {"job_id": args.job_id, "stage": args.stage, "result": payload},
            ensure_ascii=True,
            default=str,
            separators=(",", ":"),
        ),
        flush=True,
    )
    if isinstance(payload, dict) and payload.get("skipped"):
        return 75
    return 0


def _json_payload(result: Any) -> Any:
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
