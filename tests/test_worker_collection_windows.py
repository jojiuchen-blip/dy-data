from __future__ import annotations

from datetime import datetime

from apps.worker.collectors.types import CollectionStats, CollectionWindow, PhaseStats
from apps.worker.collectors.windows import resolve_collection_window


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_default_collection_window_starts_from_2026_january():
    window = resolve_collection_window(
        now=dt("2026-06-12T10:00:00+08:00"),
        env={},
    )

    assert window.start.isoformat() == "2026-01-01T00:00:00+08:00"
    assert window.end.isoformat() == "2026-06-12T10:00:00+08:00"
    assert window.timezone_name == "Asia/Shanghai"


def test_collection_window_uses_overlap_for_incremental_runs():
    window = resolve_collection_window(
        now=dt("2026-06-12T10:00:00+08:00"),
        overlap_days=7,
        env={},
    )

    assert window.start.isoformat() == "2026-06-05T00:00:00+08:00"
    assert window.end.isoformat() == "2026-06-12T10:00:00+08:00"


def test_collection_stats_exposes_job_run_counts():
    window = CollectionWindow(
        start=dt("2026-01-01T00:00:00+08:00"),
        end=dt("2026-01-02T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )
    stats = CollectionStats(run_id="collect-test", source_window=window)
    stats.add_phase(PhaseStats(name="orders", fetched=3, upserted=2, skipped=1))
    stats.add_phase(PhaseStats(name="verify_records", fetched=2, upserted=1, failed=1))

    assert stats.success_count == 3
    assert stats.failed_count == 1
    assert stats.as_metadata()["phases"]["orders"]["upserted"] == 2
