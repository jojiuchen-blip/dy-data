from __future__ import annotations

from dataclasses import dataclass

import pytest

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
