from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from scripts.ops import certify_legacy_projection_root as maintenance


def _factory(db_session: Session):
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)


def _arguments(*, max_manifest_rows: int) -> list[str]:
    return [
        "--batch-size",
        "2",
        "--max-manifest-rows",
        str(max_manifest_rows),
        "--max-estimated-write-bytes",
        "100000",
        "--max-estimated-wal-bytes",
        "200000",
        "--observed-disk-headroom-bytes",
        "1000000",
        "--min-disk-headroom-bytes",
        "0",
    ]


def test_maintenance_command_publishes_then_reports_idempotent_root(
    db_session: Session, monkeypatch, capsys
) -> None:
    factory = _factory(db_session)
    monkeypatch.setattr(maintenance, "get_session_factory", lambda: factory)

    first_exit = maintenance.main(_arguments(max_manifest_rows=10))
    first = json.loads(capsys.readouterr().out)
    second_exit = maintenance.main(_arguments(max_manifest_rows=10))
    second = json.loads(capsys.readouterr().out)

    assert first_exit == 0
    assert first["protocol"] == "dydata-legacy-root-maintenance-v1"
    assert first["status"] == "published"
    assert first["published"] is True
    assert second_exit == 0
    assert second["status"] == "already_published"
    assert second["published"] is False
    assert second["generation_id"] == first["generation_id"]
    with factory() as check:
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert pointer is not None and pointer.generation_id == first["generation_id"]
        assert check.scalar(
            select(func.count()).select_from(SettlementProjectionGeneration)
        ) == 1


def test_maintenance_command_resource_guard_writes_no_projection_metadata(
    db_session: Session, monkeypatch, capsys
) -> None:
    factory = _factory(db_session)
    monkeypatch.setattr(maintenance, "get_session_factory", lambda: factory)
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="maintenance-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="maintenance-run",
        )
    )
    db_session.commit()

    exit_code = maintenance.main(_arguments(max_manifest_rows=0))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["status"] == "resource_guard"
    assert payload["failure_code"] == "manifest_rows_exceed_limit"
    with factory() as check:
        assert check.scalar(
            select(func.count()).select_from(SettlementProjectionGeneration)
        ) == 0
        assert check.scalar(
            select(func.count()).select_from(SettlementProjectionActive)
        ) == 0
