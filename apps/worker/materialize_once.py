from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import RawDouyinClue, utcnow
from apps.worker.clue_allocation import (
    materialize_clue_master_leads,
    refresh_due_store_score_snapshots,
)
from apps.worker.clue_center import refresh_clue_center_projection
from apps.worker.pipeline import build_douyin_client_from_env
from apps.worker.settlement import rebuild_settlement


MATERIALIZATION_STAGES = (
    "clue_master_rebuild",
    "clue_projection_rebuild",
    "settlement",
    "clue_master_refresh",
    "clue_projection_refresh",
    "store_score_snapshot",
)
DEFAULT_CLUE_MASTER_BATCH_SIZE = 2_000


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
    if stage in {"clue_projection_rebuild", "clue_projection_refresh"}:
        client = build_douyin_client_from_env()
        resolver = getattr(client, "decrypt_cipher_texts", None)
        return refresh_clue_center_projection(
            session,
            phone_plain_resolver=resolver if callable(resolver) else None,
        )
    if stage == "settlement":
        return rebuild_settlement(session, source_run_id=source_run_id)
    if stage == "store_score_snapshot":
        return refresh_due_store_score_snapshots(session)
    raise ValueError(f"Unsupported materialization stage: {stage}")


def run_bounded_clue_master_materialization(factory) -> dict[str, object]:
    batch_size = _configured_clue_master_batch_size()
    started_at = utcnow()
    with session_scope(factory) as session:
        upper_bound = session.scalar(select(func.max(RawDouyinClue.clue_row_key)))
    if not upper_bound:
        return {
            "raw_rows": 0,
            "batches": 0,
            "master_leads": 0,
            "closed_leads": 0,
            "headquarters_pool": 0,
        }

    cursor: str | None = None
    totals = {
        "raw_rows": 0,
        "batches": 0,
        "master_leads": 0,
        "closed_leads": 0,
        "headquarters_pool": 0,
    }
    while True:
        with session_scope(factory) as session:
            statement = (
                select(RawDouyinClue)
                .where(RawDouyinClue.clue_row_key <= upper_bound)
                .order_by(RawDouyinClue.clue_row_key)
                .limit(batch_size)
            )
            if cursor is not None:
                statement = statement.where(RawDouyinClue.clue_row_key > cursor)
            raw_clues = list(session.scalars(statement).all())
            if not raw_clues:
                break
            result = materialize_clue_master_leads(
                session,
                now=started_at,
                raw_clues=raw_clues,
            )
            if result.get("skipped"):
                raise RuntimeError(
                    "clue master page was not materialized: "
                    f"{result['skipped']} after cursor {cursor or '<start>'}"
                )
            cursor = raw_clues[-1].clue_row_key
            totals["raw_rows"] += len(raw_clues)
            totals["batches"] += 1
            for key in ("master_leads", "closed_leads", "headquarters_pool"):
                totals[key] += int(result.get(key, 0))
    return {
        **totals,
        "batch_size": batch_size,
        "upper_bound": upper_bound,
        "last_cursor": cursor,
    }


def _configured_clue_master_batch_size() -> int:
    raw = os.getenv("WORKER_CLUE_MASTER_BATCH_SIZE")
    if raw is None:
        return DEFAULT_CLUE_MASTER_BATCH_SIZE
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("WORKER_CLUE_MASTER_BATCH_SIZE must be an integer") from exc
    if value <= 0:
        raise ValueError("WORKER_CLUE_MASTER_BATCH_SIZE must be positive")
    return min(value, 10_000)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before materialization.")

    if args.stage in {"clue_master_rebuild", "clue_master_refresh"}:
        result = run_bounded_clue_master_materialization(factory)
    else:
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
