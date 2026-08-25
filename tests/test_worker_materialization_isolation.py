from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    ClueMasterLead,
    ClueSourceIdentifierHistory,
    RawDouyinClue,
)
from apps.worker.collectors.types import CollectionWindow
from apps.worker import scheduler


@dataclass
class CompletedProcess:
    returncode: int = 0
    stdout: str = "ok"
    stderr: str = ""


def test_isolated_materialization_runs_each_heavy_stage_in_a_fresh_process() -> None:
    calls: list[tuple[list[str], int]] = []

    def runner(command, *, capture_output, text, timeout, check):
        assert capture_output is True
        assert text is True
        assert check is False
        calls.append((list(command), timeout))
        return CompletedProcess()

    window = CollectionWindow(
        start=scheduler.datetime.fromisoformat("2026-06-01T00:00:00+08:00"),
        end=scheduler.datetime.fromisoformat("2026-06-03T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )

    scheduler.run_isolated_materialization(
        window=window,
        job_id="materialize-1",
        command_runner=runner,
        timeout_seconds=900,
    )

    assert [command[-1] for command, _timeout in calls] == list(
        scheduler.MATERIALIZATION_STAGES
    )
    assert all(command[:3] == [scheduler.sys.executable, "-m", "apps.worker.materialize_once"] for command, _ in calls)
    assert all("materialize-1" in command for command, _ in calls)
    assert {timeout for _command, timeout in calls} == {900}


def test_isolated_materialization_stops_after_a_failed_stage() -> None:
    calls: list[str] = []

    def runner(command, **_kwargs):
        stage = command[-1]
        calls.append(stage)
        if stage == "settlement":
            return CompletedProcess(returncode=137, stderr="Killed")
        return CompletedProcess()

    window = CollectionWindow(
        start=scheduler.datetime.fromisoformat("2026-06-01T00:00:00+08:00"),
        end=scheduler.datetime.fromisoformat("2026-06-03T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )

    with pytest.raises(RuntimeError, match="settlement.*137"):
        scheduler.run_isolated_materialization(
            window=window,
            job_id="materialize-2",
            command_runner=runner,
        )

    assert calls == ["clue_master_rebuild", "clue_center_rebuild", "settlement"]


@pytest.mark.parametrize(
    ("stage", "expected_call"),
    [
        ("clue_master_rebuild", "clue_master"),
        ("clue_center_rebuild", "clue_center"),
        ("settlement", "settlement"),
        ("clue_master_refresh", "clue_master"),
        ("clue_center_refresh", "clue_center"),
        ("clue_follow_up_due", "follow_up"),
        ("store_score_snapshot", "store_score"),
    ],
)
def test_materialize_once_dispatches_exactly_one_stage(
    monkeypatch,
    stage: str,
    expected_call: str,
) -> None:
    from apps.worker import materialize_once

    calls: list[tuple[str, str | None]] = []
    decrypt = lambda values: {value: value for value in values}
    monkeypatch.setattr(
        materialize_once,
        "build_douyin_client_from_env",
        lambda: type("Client", (), {"decrypt_cipher_texts": staticmethod(decrypt)})(),
        raising=False,
    )
    monkeypatch.setattr(
        materialize_once,
        "materialize_clue_master_leads",
        lambda session: calls.append(("clue_master", None)) or {"master_leads": 1},
    )
    monkeypatch.setattr(
        materialize_once,
        "rebuild_clue_center",
        lambda session, *, phone_plain_resolver: (
            calls.append(("clue_center", None))
            or {"eligible_orders": 1, "has_resolver": phone_plain_resolver is decrypt}
        ),
    )
    monkeypatch.setattr(
        materialize_once,
        "rebuild_settlement",
        lambda session, *, source_run_id: calls.append(("settlement", source_run_id))
        or {"detail_count": 1},
    )
    monkeypatch.setattr(
        materialize_once,
        "process_due_transitions",
        lambda session: calls.append(("follow_up", None)) or {"sla_expired": 1},
    )
    monkeypatch.setattr(
        materialize_once,
        "refresh_due_store_score_snapshots",
        lambda session: calls.append(("store_score", None)) or {"snapshots": 1},
    )

    result = materialize_once.run_materialization_stage(
        object(),
        stage=stage,
        source_run_id="materialize-3",
    )

    assert calls == [
        (expected_call, "materialize-3" if expected_call == "settlement" else None)
    ]
    assert result
    if expected_call == "clue_center":
        assert result["has_resolver"] is True


def test_clue_master_stage_materializes_keyset_pages_with_bounded_sessions(
    db_session,
    monkeypatch,
) -> None:
    from apps.worker import materialize_once

    db_session.add_all(
        [
            RawDouyinClue(
                clue_row_key=f"row-{index}",
                clue_id=f"clue-{index}",
                order_id=f"order-{index}",
                order_status="履约中",
                telephone=f"1380000{index:04d}",
                raw_payload={"clue_id": f"clue-{index}"},
            )
            for index in range(5)
        ]
    )
    db_session.commit()
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    monkeypatch.setenv("WORKER_CLUE_MASTER_BATCH_SIZE", "2")
    statements: list[str] = []

    def record_selects(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement.lower())

    event.listen(db_session.get_bind(), "before_cursor_execute", record_selects)
    try:
        result = materialize_once.run_bounded_clue_master_materialization(factory)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record_selects)

    assert result["raw_rows"] == 5
    assert result["batches"] == 3
    assert result["master_leads"] == 5
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 5
    assert (
        db_session.scalar(select(func.count()).select_from(ClueSourceIdentifierHistory))
        == 10
    )
    bounded_tables = ("clue_master_leads", "clue_source_identifier_history")
    for table_name in bounded_tables:
        table_selects = [statement for statement in statements if f"from {table_name}" in statement]
        assert table_selects
        assert all("where" in statement for statement in table_selects), table_selects

    replay = materialize_once.run_bounded_clue_master_materialization(factory)

    assert replay["batches"] == 3
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 5
    assert (
        db_session.scalar(select(func.count()).select_from(ClueSourceIdentifierHistory))
        == 10
    )
