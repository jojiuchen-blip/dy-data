"""Retention outcomes for immutable ranking batches, independent of formulas."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.ranking_schema_v1 import metadata, runs, samples
from apps.api.dy_api.ranking_lifecycle import (
    archive_snapshot, cleanup_snapshots, record_snapshot_access, register_snapshot,
)
from apps.api.dy_api.ranking_lifecycle_schema import snapshot_lifecycle

NOW = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
START = NOW - timedelta(days=10)
END = NOW - timedelta(days=1)


@pytest.fixture
def store(db_session):
    metadata.create_all(db_session.bind)
    return db_session


def add_run(session, run_id, *, age_hours=10, version="scope-a", sidecar=True):
    created = NOW - timedelta(hours=age_hours)
    session.execute(runs.insert().values(
        run_id=run_id, period_start=START, period_end=END,
        observed_through=created, roster_at=START, eligibility_version="test",
        metric_version=version, data_mode="business", status="success",
        quality_json={}, created_at=created,
    ))
    session.execute(samples.insert().values(
        run_id=run_id, metric_key="order_count", sample_key=run_id,
        numerator=1, denominator=1, status="included", evidence_json={},
    ))
    if sidecar:
        register_snapshot(session, run_id=run_id, source_token="test-source", now=created)


def ids(session):
    return set(session.scalars(select(runs.c.run_id)))


def test_retention_preserves_two_per_key_and_pins_with_complete_batch_delete(store):
    for key in ("scope-a", "scope-b"):
        for index in range(4):
            add_run(store, f"{key}-{index}", version=key, age_hours=10-index)
    archive_snapshot(store, "scope-a-0", reason="confirmed baseline", now=NOW)
    store.commit()
    preview = cleanup_snapshots(store, now=NOW)
    assert preview["deleted"] == 0
    assert {item["run_id"] for item in preview["planned"]} == {"scope-a-1", "scope-b-0", "scope-b-1"}
    assert len(ids(store)) == 8
    result = cleanup_snapshots(store, now=NOW, dry_run=False)
    store.commit()
    assert result["deleted"] == 3
    expected = {"scope-a-0", "scope-a-2", "scope-a-3", "scope-b-2", "scope-b-3"}
    assert ids(store) == expected
    assert set(store.scalars(select(samples.c.run_id))) == expected
    assert set(store.scalars(select(snapshot_lifecycle.c.run_id))) == expected


def test_new_versions_have_one_hour_grace_and_apply_is_bounded(store):
    for index, age in enumerate((10, 9, 8, 0.8, 0.5, 0.2)):
        add_run(store, f"run-{index}", age_hours=age)
    store.commit()
    result = cleanup_snapshots(store, now=NOW, dry_run=False, max_runs=1)
    store.commit()
    assert result["deleted"] == 1
    assert len(ids(store)) == 5
    assert {"run-3", "run-4", "run-5"} <= ids(store)


def test_idle_ranges_expire_but_recent_export_and_explicit_archive_survive(store):
    for name, version in (("idle", "idle-key"), ("downloaded", "download-key"), ("pinned", "pin-key")):
        add_run(store, name, age_hours=31*24, version=version)
    archive_snapshot(store, "pinned", reason="business milestone", now=NOW)
    record_snapshot_access(store, "downloaded", now=NOW)
    store.commit()
    result = cleanup_snapshots(store, now=NOW, dry_run=False)
    store.commit()
    assert result["deleted"] == 1
    assert ids(store) == {"downloaded", "pinned"}


def test_archive_targets_requested_legacy_run_and_access_preserves_pin(store):
    add_run(store, "oldest", age_hours=12, sidecar=False)
    add_run(store, "target", age_hours=11, sidecar=False)
    add_run(store, "newest", age_hours=10, sidecar=False)
    archive_snapshot(store, "target", reason="specific historical cutoff", actor="operator", now=NOW)
    record_snapshot_access(store, "target", now=NOW)
    store.commit()
    row = store.execute(select(snapshot_lifecycle)).mappings().one()
    assert row["run_id"] == "target"
    assert row["pin_reason"] == "specific historical cutoff"
    assert row["pinned_by"] == "operator"
    assert row["source_fingerprint"] is None
    assert store.scalar(select(func.count()).select_from(runs)) == 3


def test_cli_preview_rolls_back_legacy_metadata_and_keeps_facts(store, monkeypatch, capsys):
    from sqlalchemy.orm import sessionmaker
    from scripts import ranking_retention

    for index in range(4):
        add_run(store, f"legacy-{index}", age_hours=10-index, sidecar=False)
    store.commit()
    factory = sessionmaker(bind=store.bind, autoflush=False)
    monkeypatch.setattr(ranking_retention, "get_session_factory", lambda: factory)
    assert ranking_retention.main(["--limit", "1"]) == 0
    assert '"dry_run": true' in capsys.readouterr().out
    assert store.scalar(select(func.count()).select_from(runs)) == 4
    assert store.scalar(select(func.count()).select_from(samples)) == 4
    assert store.scalar(select(func.count()).select_from(snapshot_lifecycle)) == 0
