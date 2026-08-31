from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import ast
import gc
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import weakref

from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from apps.api.dy_api.models import (
    Base,
    ClueAllocationRule,
    ClueAllocationRuleVersion,
    SettlementProjectionActive,
    SettlementProjectionCompactionClosure,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementMonthlyOverlay,
    SettlementRankingOverlay,
    StoreScoreSnapshotGeneration,
    SettlementStatement,
    SettlementStatementEntry,
    SettlementStatementLine,
    SettlementOrderDetail,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    AggStoreMonthlySettlement,
    AggStoreRanking,
    DimStore,
    StoreScoreSnapshot,
    StoreScoreSnapshotRun,
)
from apps.worker.legacy_projection_bootstrap import (
    CompactionThresholdConfig,
    ResourceGateConfig,
    certify_legacy_null_root,
    compact_projection_metadata,
)
import apps.worker.legacy_projection_bootstrap as bootstrap
from apps.worker.projection_lineage import resolve_projection_partitions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from dy_api.routes._data import DashboardDataStore  # noqa: E402
from dy_api.routes.admin import list_store_score_snapshots  # noqa: E402


def _factory(db_session: Session):
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)


def _limits(*, rows: int = 10, write: int = 100_000, wal: int = 200_000, headroom: int = 1_000_000):
    return ResourceGateConfig(
        max_manifest_rows=rows,
        max_estimated_write_bytes=write,
        max_estimated_wal_bytes=wal,
        observed_disk_headroom_bytes=headroom,
        min_disk_headroom_bytes=0,
    )


def test_empty_database_publishes_deterministic_null_root(db_session: Session):
    result = certify_legacy_null_root(
        _factory(db_session), batch_size=2, resource_limits=_limits()
    )

    assert result.status == "published"
    assert result.published is True
    assert result.resumed is False
    assert result.batch_count == 0
    assert result.partition_count == 0
    assert result.source_row_count == 0
    assert result.last_key is None
    assert result.manifest_checksum
    assert result.generation_id == "legacy-null-root:" + result.generation_id.split(":", 1)[1]

    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, result.generation_id)
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert generation is not None
        assert generation.state == "published"
        assert generation.generation_kind == "legacy_root"
        assert pointer is not None
        assert pointer.generation_id == result.generation_id
        assert check.scalar(
            select(func.count()).select_from(SettlementProjectionPartitionManifest)
        ) == 0

    retry = certify_legacy_null_root(
        _factory(db_session), batch_size=2, resource_limits=_limits()
    )
    assert retry.status == "already_published"
    assert retry.published is False
    assert retry.resumed is False
    assert retry.generation_id == result.generation_id
    assert retry.manifest_checksum == result.manifest_checksum


def test_protocol_fingerprint_generation_and_empty_checksum_fixtures():
    assert bootstrap._input_fingerprint() == (
        "ae40848a97b0f9c62925ca606d14bb8e5cb5c4f4757c633df43ca89136e6b6bd"
    )
    assert bootstrap._generation_id() == (
        "legacy-null-root:ae40848a97b0f9c62925ca606d14bb8e5cb5c4f4757c633df43ca89136e6b6bd"
    )
    assert bootstrap._empty_manifest_checksum() == (
        "8127841be79e99046981cc9b09fe50076f6a00dad50ad0c426b93d65dfe79e5a"
    )


def test_published_root_idempotency_precedes_post_publication_source_drift(
    db_session: Session,
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="idempotent-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="idempotent-run",
        )
    )
    db_session.commit()
    first = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )
    assert first.status == "published"
    with _factory(db_session)() as before:
        generation_before = before.get(SettlementProjectionGeneration, first.generation_id)
        pointer_before = before.get(SettlementProjectionActive, "settlement")
        manifests_before = [
            (
                row.artifact,
                row.partition_key,
                row.row_count,
                row.amount_total_cent,
                row.status_counts_json,
                row.checksum,
                row.last_key,
            )
            for row in before.scalars(
                select(SettlementProjectionPartitionManifest).order_by(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
            )
        ]
        generation_snapshot = (
            generation_before.state,
            generation_before.manifest_checksum,
            generation_before.checkpoint_json,
            generation_before.last_key,
        )
        pointer_snapshot = (pointer_before.projection_name, pointer_before.generation_id)

    source = db_session.scalar(
        select(AggStoreMonthlySettlement).where(
            AggStoreMonthlySettlement.month == "2026-08"
        )
    )
    assert source is not None
    source.month = "2026-8"
    db_session.commit()

    retry = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )
    assert retry.status == "already_published"
    assert retry.published is False
    assert retry.resumed is False
    assert retry.generation_id == first.generation_id
    assert retry.manifest_checksum == first.manifest_checksum

    with _factory(db_session)() as after:
        generation_after = after.get(SettlementProjectionGeneration, first.generation_id)
        pointer_after = after.get(SettlementProjectionActive, "settlement")
        manifests_after = [
            (
                row.artifact,
                row.partition_key,
                row.row_count,
                row.amount_total_cent,
                row.status_counts_json,
                row.checksum,
                row.last_key,
            )
            for row in after.scalars(
                select(SettlementProjectionPartitionManifest).order_by(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
            )
        ]
        assert (
            generation_after.state,
            generation_after.manifest_checksum,
            generation_after.checkpoint_json,
            generation_after.last_key,
        ) == generation_snapshot
        assert (pointer_after.projection_name, pointer_after.generation_id) == pointer_snapshot
        assert manifests_after == manifests_before


def test_manifest_checksum_canonicalizes_status_json_mapping_and_rejects_malformed():
    base = {
        "artifact": "monthly",
        "partition_key": "2026-08",
        "owner_state": "owned",
        "source_kind": "legacy_root",
        "data_generation_id": None,
        "base_generation_id": None,
        "row_count": 1,
        "amount_total_cent": 0,
        "checksum": "a" * 64,
    }
    mapping = {**base, "status_counts_json": {"1": 1}}
    json_text = {**base, "status_counts_json": '{"1":1}'}
    assert bootstrap._manifest_checksum([mapping]) == bootstrap._manifest_checksum([json_text])
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="status"):
        bootstrap._manifest_checksum([{**base, "status_counts_json": "not-json"}])


def test_score_row_mapping_normalizes_known_sqlite_text_types_without_guessing_strings():
    columns = bootstrap._source_columns(StoreScoreSnapshot)
    native = {
        "snapshot_date": date(2026, 8, 1),
        "window_start": datetime(2026, 8, 1, 0, 0, 0),
        "window_end": datetime(2026, 8, 2, 0, 0, 0),
        "conversion_rate": Decimal("0.400000"),
        "follow_24h_rate": Decimal("0.300000"),
        "conversion_weight": Decimal("0.7000"),
        "follow_24h_weight": Decimal("0.3000"),
        "store_weight": Decimal("1.0000"),
        "composite_score": Decimal("0.400000"),
        "config_json": {"threshold": 0.4, "rule": "legacy"},
        "city_code": "2026-08-01",
    }
    sqlite_text = {
        **native,
        "snapshot_date": "2026-08-01",
        "window_start": "2026-08-01 00:00:00",
        "window_end": "2026-08-02 00:00:00",
        "conversion_rate": 0.4,
        "follow_24h_rate": 0.3,
        "conversion_weight": 0.7,
        "follow_24h_weight": 0.3,
        "store_weight": 1.0,
        "composite_score": 0.4,
        "config_json": '{"threshold":0.4,"rule":"legacy"}',
    }
    native_row = bootstrap._row_mapping(native, columns)
    sqlite_row = bootstrap._row_mapping(sqlite_text, columns)
    assert bootstrap._canonical_json(native_row) == bootstrap._canonical_json(sqlite_row)
    native_partition = bootstrap._PartitionAccumulator.fresh(
        "score", "2026-08-01|4:rule|10:store-cert"
    )
    sqlite_partition = bootstrap._PartitionAccumulator.fresh(
        "score", "2026-08-01|4:rule|10:store-cert"
    )
    native_partition.add(native_row)
    sqlite_partition.add(sqlite_row)
    assert native_partition.digest == sqlite_partition.digest
    assert sqlite_row["city_code"] == "2026-08-01"
    negative_native = bootstrap._row_mapping(
        {**native, "conversion_rate": Decimal("-0.000000")}, columns
    )
    negative_sqlite = bootstrap._row_mapping({**sqlite_text, "conversion_rate": -0.0}, columns)
    assert bootstrap._canonical_json(negative_native) == bootstrap._canonical_json(negative_sqlite)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="JSON"):
        bootstrap._row_mapping({**sqlite_text, "config_json": "[]"}, columns)


@pytest.mark.parametrize("constant", ["NaN", "Infinity"])
def test_r9_json_mapping_rejects_nonstandard_constants(constant: str):
    columns = bootstrap._source_columns(StoreScoreSnapshot)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="JSON"):
        bootstrap._row_mapping(
            {"config_json": f'{{"rule_version_id":"r","x":{constant}}}'}, columns
        )


@pytest.mark.parametrize("constant", ["NaN", "Infinity"])
def test_r9_score_source_nonstandard_json_fails_before_generation_write(
    db_session: Session, monkeypatch, constant: str
):
    raw = {
        "snapshot_id": "r9-score-snapshot",
        "snapshot_run_id": "r9-score-run",
        "store_id": "r9-score-store",
        "snapshot_date": date(2026, 8, 1),
        "run_snapshot_date": date(2026, 8, 1),
        "rule_version_id": "r9-rule",
        "config_json": f'{{"rule_version_id":"r9-rule","x":{constant}}}',
    }

    def source_page(_session, artifact, _batch_size, cursor):
        if artifact == "score" and cursor is None:
            return [raw]
        return []

    monkeypatch.setattr(bootstrap, "_select_source_page", source_page)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="JSON"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 0
        assert check.scalar(select(func.count()).select_from(SettlementProjectionActive)) == 0


def test_keyset_queries_make_nulls_visible_after_a_legal_cursor(db_session: Session):
    statements: list[str] = []

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.upper())

    bootstrap._select_source_page(
        db_session,
        "monthly",
        1,
        {
            "month": "2026-08",
            "store_id": "store-a",
            "product_scope": "all",
            "product_type": "all",
            "projection_run_id": "run-a",
            "id": 1,
        },
    )
    assert statements
    assert "NULLS LAST" in statements[-1]
    assert " IS NULL" in statements[-1]


def test_verify_rejects_non_owned_or_malformed_manifest_before_source_drift(
    db_session: Session, monkeypatch
):
    raw = {
        "id": 1,
        "month": "2026-08",
        "store_id": "store-a",
        "product_scope": "all",
        "product_type": "all",
        "projection_run_id": "run-a",
        "statement_status": 1,
    }
    accumulator = bootstrap._PartitionAccumulator.fresh("monthly", "2026-08")
    accumulator.add(
        bootstrap._row_mapping(raw, bootstrap._source_columns(AggStoreMonthlySettlement)),
        status="1",
    )
    accumulator.last_key = bootstrap._cursor_token("monthly", bootstrap._cursor_from_row("monthly", raw))
    base = {
        "generation_id": bootstrap._generation_id(),
        "artifact": "monthly",
        "partition_key": "2026-08",
        "owner_state": "owned",
        "source_kind": "legacy_root",
        "data_generation_id": None,
        "base_generation_id": None,
        "row_count": 1,
        "amount_total_cent": 0,
        "status_counts_json": {"1": 1},
        "checksum": accumulator.digest,
        "last_key": accumulator.last_key,
    }
    for tamper, expected in (({"owner_state": "tombstone"}, "owner_state"),
                             ({"status_counts_json": "not-json"}, "status")):
        calls = {"count": 0}

        def manifests(*_args, **_kwargs):
            return [{**base, **tamper}]

        def source_page(*_args, **_kwargs):
            calls["count"] += 1
            return [raw] if calls["count"] == 1 else []

        monkeypatch.setattr(bootstrap, "_fetch_all_generation_manifests", manifests)
        monkeypatch.setattr(bootstrap, "_select_source_page", source_page)
        with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match=expected):
            bootstrap._verify_artifact(
                _factory(db_session),
                bootstrap._generation_id(),
                "monthly",
                1,
            )


def test_verify_rejects_canonical_but_stale_manifest_last_key(
    db_session: Session, monkeypatch
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="last-key-store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="last-key-run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="last-key-store-b",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="last-key-run-b",
            ),
        ]
    )
    db_session.commit()
    source_rows = bootstrap._select_source_page(db_session, "monthly", 10, None)
    assert len(source_rows) == 2
    accumulator = bootstrap._PartitionAccumulator.fresh("monthly", "2026-08")
    source_cursors: list[str] = []
    for raw in source_rows:
        accumulator.add(
            bootstrap._row_mapping(raw, bootstrap._source_columns(AggStoreMonthlySettlement)),
            status="1",
        )
        token = bootstrap._cursor_token("monthly", bootstrap._cursor_from_row("monthly", raw))
        source_cursors.append(token)
        accumulator.last_key = token
    manifest = {
        "generation_id": bootstrap._generation_id(),
        "artifact": "monthly",
        "partition_key": "2026-08",
        "owner_state": "owned",
        "source_kind": "legacy_root",
        "data_generation_id": None,
        "base_generation_id": None,
        "row_count": accumulator.row_count,
        "amount_total_cent": accumulator.amount_total_cent,
        "status_counts_json": {"1": 2},
        "checksum": accumulator.digest,
        "last_key": source_cursors[0],
    }
    monkeypatch.setattr(
        bootstrap,
        "_fetch_all_generation_manifests",
        lambda *_args, **_kwargs: [manifest],
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="last_key|drift"):
        bootstrap._verify_artifact(
            _factory(db_session), bootstrap._generation_id(), "monthly", 10
        )


@pytest.mark.parametrize(
    "cursor",
    [
        {"artifact": "monthly"},
        {"partition_key": "2026-08"},
        {"artifact": "monthly", "partition_key": "2026-08", "extra": 1},
        {"artifact": "None", "partition_key": "2026-08"},
        {"artifact": "monthly", "partition_key": ""},
    ],
)
def test_cleanup_checkpoint_requires_exact_nonempty_cursor_shape(cursor):
    resource = (1, 20_480, 40_960, 1_000_000)
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="failed",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=bootstrap._checkpoint(
            phase="cleanup",
            artifact=None,
            cursor=cursor,
            stats=bootstrap._ScanStats(),
            resource=resource,
        ),
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="phase|cleanup"):
        bootstrap._validate_checkpoint(generation, resource)


def test_fetch_manifests_enforces_resource_cap_and_cap_plus_one(db_session: Session):
    resource = (2, 20_480, 40_960, 1_000_000)
    generation_id = bootstrap._generation_id()
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="ready",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
                checkpoint_json=bootstrap._checkpoint(
                    phase="verify",
                    artifact="monthly",
                    cursor=None,
                stats=bootstrap._ScanStats(),
                resource=resource,
            ),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.add_all(
        [
            SettlementProjectionPartitionManifest(
                generation_id=generation_id,
                artifact="monthly",
                partition_key=f"2026-{month:02d}",
                owner_state="owned",
                source_kind="legacy_root",
                row_count=0,
                amount_total_cent=0,
                status_counts_json={},
                checksum="a" * 64,
            )
            for month in (8, 9)
        ]
    )
    db_session.commit()
    page_limits: list[int] = []

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _capture_manifest_page_limit(
        _conn, _cursor, statement, parameters, _context, _executemany
    ):
        if "SELECT GENERATION_ID, ARTIFACT, PARTITION_KEY" in statement.upper():
            if isinstance(parameters, dict):
                page_limits.append(int(parameters["page_limit"]))
            else:
                page_limits.append(int(parameters[-1]))

    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="manifest"):
        bootstrap._fetch_all_generation_manifests(
            _factory(db_session), generation_id, "monthly", max_manifest_rows=1
        )
    assert page_limits and all(limit <= 1 for limit in page_limits)
    page_limits.clear()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="manifest"):
        bootstrap._fetch_all_generation_manifests(
            _factory(db_session), generation_id, "monthly", max_manifest_rows=0
        )
    assert page_limits and all(limit <= 1 for limit in page_limits)
    page_limits.clear()
    rows = bootstrap._fetch_all_generation_manifests(
        _factory(db_session), generation_id, "monthly", max_manifest_rows=2
    )
    assert len(rows) == 2
    assert page_limits and all(limit <= 2 for limit in page_limits)


@pytest.mark.parametrize(
    "tamper",
    ["status", "source_kind", "data_generation_id", "base_generation_id", "last_key"],
)
def test_ready_manifest_tampering_marks_generation_failed_and_keeps_rows(
    db_session: Session, tamper: str
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="ready-corrupt-store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="ready-corrupt-run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="ready-corrupt-store-b",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="ready-corrupt-run-b",
            ),
        ]
    )
    db_session.commit()
    raw_rows = bootstrap._select_source_page(db_session, "monthly", 2, None)
    assert len(raw_rows) == 2
    accumulator = bootstrap._PartitionAccumulator.fresh("monthly", "2026-08")
    source_cursors: list[str] = []
    for raw in raw_rows:
        accumulator.add(
            bootstrap._row_mapping(raw, bootstrap._source_columns(AggStoreMonthlySettlement)),
            status="1",
        )
        token = bootstrap._cursor_token("monthly", bootstrap._cursor_from_row("monthly", raw))
        source_cursors.append(token)
        accumulator.last_key = token
    generation_id = bootstrap._generation_id()
    resource = (1, 20_480, 40_960, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="ready",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="verify",
                artifact=None,
                cursor=None,
                stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=2),
                resource=resource,
            ),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    manifest_values = {
        "owner_state": "owned",
        "source_kind": "legacy_root",
        "data_generation_id": None,
        "base_generation_id": None,
        "row_count": 2,
        "amount_total_cent": 0,
        "status_counts_json": {"1": 2},
        "checksum": accumulator.digest,
        "last_key": accumulator.last_key,
    }
    if tamper == "status":
        manifest_values["status_counts_json"] = "not-json"
    elif tamper in {"source_kind", "data_generation_id"}:
        manifest_values["source_kind"] = "overlay"
        manifest_values["data_generation_id"] = generation_id
    elif tamper == "base_generation_id":
        manifest_values["base_generation_id"] = generation_id
    elif tamper == "last_key":
        manifest_values["last_key"] = source_cursors[0]
    db_session.add(
        SettlementProjectionPartitionManifest(
            generation_id=generation_id,
            artifact="monthly",
            partition_key="2026-08",
            **manifest_values,
        )
    )
    db_session.commit()
    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError,
        match="status|source_kind|generation|last_key|drift",
    ):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, generation_id)
        assert generation is not None and generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None
        manifest = check.get(
            SettlementProjectionPartitionManifest,
            (generation_id, "monthly", "2026-08"),
        )
        assert manifest is not None
        if tamper == "status":
            assert manifest.status_counts_json == "not-json"
        elif tamper == "source_kind":
            assert manifest.source_kind == "overlay"
        elif tamper == "data_generation_id":
            assert manifest.data_generation_id == generation_id
        elif tamper == "base_generation_id":
            assert manifest.base_generation_id == generation_id
        else:
            assert manifest.last_key == source_cursors[0]


def test_malformed_cleanup_checkpoint_fails_closed_without_manifest_deletion(
    db_session: Session,
):
    generation_id = bootstrap._generation_id()
    resource = (0, 16_384, 32_768, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="cleanup",
                artifact=None,
                cursor={"artifact": "monthly", "partition_key": "2026-08", "extra": 1},
                stats=bootstrap._ScanStats(),
                resource=resource,
            ),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.add(
        SettlementProjectionPartitionManifest(
            generation_id=generation_id,
            artifact="monthly",
            partition_key="2026-08",
            owner_state="owned",
            source_kind="legacy_root",
            data_generation_id=None,
            base_generation_id=None,
            row_count=0,
            amount_total_cent=0,
            status_counts_json={},
            checksum=bootstrap._sha256(bootstrap._canonical_json({"rows": []})),
            last_key=None,
        )
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="phase|cleanup"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, generation_id)
        assert generation is not None and generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None
        assert (
            check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest))
            == 1
        )


def test_invalid_batch_fails_closed_before_metadata_write(db_session: Session):
    result = certify_legacy_null_root(
        _factory(db_session), batch_size=0, resource_limits=_limits()
    )

    assert result.status == "resource_guard"
    assert result.published is False
    assert result.generation_id is None
    assert result.manifest_checksum is None
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0
        assert check.scalar(select(func.count()).select_from(SettlementProjectionActive)) == 0


def test_resource_overflow_fails_before_generation_write(db_session: Session):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="store-a",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="run-a",
        )
    )
    db_session.commit()
    result = certify_legacy_null_root(
        _factory(db_session),
        batch_size=1,
        resource_limits=ResourceGateConfig(
            max_manifest_rows=0,
            max_estimated_write_bytes=100_000,
            max_estimated_wal_bytes=200_000,
            observed_disk_headroom_bytes=1_000_000,
            min_disk_headroom_bytes=0,
        ),
    )
    assert result.status == "resource_guard"
    assert result.failure_code == "manifest_rows_exceed_limit"
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0
        assert check.scalar(select(func.count()).select_from(SettlementProjectionActive)) == 0


@pytest.mark.parametrize(
    ("limits", "code"),
    [
        (
            ResourceGateConfig(10, 16383, 100000, 1000000, 0),
            "estimated_write_bytes_exceed_limit",
        ),
        (
            ResourceGateConfig(10, 100000, 32767, 1000000, 0),
            "estimated_wal_bytes_exceed_limit",
        ),
        (
            ResourceGateConfig(10, 100000, 100000, 49151, 0),
            "disk_headroom_insufficient",
        ),
    ],
)
def test_each_resource_budget_is_fail_closed_before_metadata_write(
    db_session: Session, limits: ResourceGateConfig, code: str
):
    result = certify_legacy_null_root(_factory(db_session), resource_limits=limits)
    assert result.status == "resource_guard"
    assert result.failure_code == code
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("month", "2026-8", "YYYY-MM"),
        ("store_id", " store-a", "canonical identity"),
        ("product_scope", " all", "canonical identity"),
        ("product_type", "all ", "canonical identity"),
        ("projection_run_id", " ", "canonical identity"),
    ],
)
def test_invalid_month_identity_fails_before_generation_write(
    db_session: Session, field: str, value: str, match: str
):
    row = AggStoreMonthlySettlement(
        month="2026-08",
        store_id="store-a",
        product_scope="all",
        product_type="all",
        statement_status=1,
        projection_run_id="run-a",
    )
    setattr(row, field, value)
    db_session.add(row)
    db_session.commit()
    with pytest.raises(Exception, match=match):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 0
        assert check.scalar(select(SettlementProjectionActive)) is None


def test_orphan_score_snapshot_fails_before_generation_write(db_session: Session):
    db_session.add(DimStore(store_id="store-orphan", store_name="Orphan"))
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id="orphan-snapshot",
            snapshot_run_id="missing-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            store_id="store-orphan",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    with pytest.raises(Exception, match="orphan"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0


def test_failed_generation_cleanup_reuses_generation_and_removes_only_manifests(
    db_session: Session, monkeypatch
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="run-b",
            ),
        ]
    )
    db_session.commit()
    original_partition = bootstrap._monthly_partition
    injected = {"done": False}
    original_preflight = bootstrap._preflight_source_integrity

    def fail_second_partition(row):
        if (
            injected.get("armed")
            and row.get("month") == "2026-09"
            and not injected["done"]
        ):
            injected["done"] = True
            raise bootstrap.LegacyProjectionBootstrapError(
                "injected durable scan corruption"
            )
        return original_partition(row)

    def arm_after_preflight(factory, batch_size):
        result = original_preflight(factory, batch_size)
        injected["armed"] = True
        return result

    monkeypatch.setattr(bootstrap, "_monthly_partition", fail_second_partition)
    monkeypatch.setattr(bootstrap, "_preflight_source_integrity", arm_after_preflight)
    with pytest.raises(Exception, match="injected durable scan corruption"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=2)
        )
    with _factory(db_session)() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        assert generation is not None
        generation_id = generation.generation_id
        assert generation.state == "failed"
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 1

    monkeypatch.setattr(bootstrap, "_monthly_partition", original_partition)

    result = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=2)
    )
    assert result.status == "published"
    assert result.resumed is True
    assert result.generation_id == generation_id
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 1
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 2


def test_failed_generation_cleanup_refreshes_resource_tuple_and_reuses_generation(
    db_session: Session,
):
    """A retry after source/headroom growth must atomically adopt the new gate tuple."""
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="cleanup-refresh-store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="cleanup-refresh-run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="cleanup-refresh-store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="cleanup-refresh-run-b",
            ),
        ]
    )
    generation_id = bootstrap._generation_id()
    old_resource = (1, 20_480, 40_960, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="failed",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=old_resource[0],
            estimated_write_bytes=old_resource[1],
            estimated_wal_bytes=old_resource[2],
            estimated_disk_headroom_bytes=old_resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="staging",
                artifact="monthly",
                cursor=None,
                stats=bootstrap._ScanStats(),
                resource=old_resource,
            ),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
            failure_code="injected",
            failure_reason="injected",
        )
    )
    db_session.add(
        SettlementProjectionPartitionManifest(
            generation_id=generation_id,
            artifact="monthly",
            partition_key="2026-08",
            owner_state="owned",
            source_kind="legacy_root",
            data_generation_id=None,
            base_generation_id=None,
            row_count=0,
            amount_total_cent=0,
            status_counts_json={},
            checksum=bootstrap._sha256(bootstrap._canonical_json({"rows": []})),
            last_key=None,
        )
    )
    db_session.commit()

    result = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=2)
    )

    assert result.status == "published"
    assert result.generation_id == generation_id
    refreshed_resource = (2, 24_576, 49_152, 1_000_000)
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, generation_id)
        assert generation is not None
        assert generation.state == "published"
        assert (
            generation.estimated_write_rows,
            generation.estimated_write_bytes,
            generation.estimated_wal_bytes,
            generation.estimated_disk_headroom_bytes,
        ) == refreshed_resource
        checkpoint = generation.checkpoint_json
        assert tuple(
            checkpoint[key]
            for key in (
                "estimated_manifest_rows",
                "estimated_write_bytes",
                "estimated_wal_bytes",
                "estimated_disk_headroom_bytes",
            )
        ) == refreshed_resource


def test_staging_ready_transition_adopts_newer_terminal_checkpoint_without_regression():
    """A stale verifier must not overwrite a peer's newer terminal checkpoint."""
    transition = getattr(bootstrap, "_promote_staging_to_ready", None)
    assert transition is not None
    with tempfile.TemporaryDirectory(prefix="legacy-ready-guard-") as temp_dir:
        engine = create_engine(
            f"sqlite+pysqlite:///{Path(temp_dir) / 'ready-guard.sqlite'}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        generation_id = bootstrap._generation_id()
        resource = (2, 24_576, 49_152, 1_000_000)
        checkpoint_a = bootstrap._checkpoint(
            phase="scan",
            artifact=None,
            cursor=None,
            stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
            resource=resource,
        )
        checkpoint_b = bootstrap._checkpoint(
            phase="scan",
            artifact=None,
            cursor=None,
            stats=bootstrap._ScanStats(batch_count=2, partition_count=2, source_row_count=2),
            resource=resource,
        )
        with factory() as setup:
            setup.add(
                SettlementProjectionGeneration(
                    generation_id=generation_id,
                    projection_name="settlement",
                    state="staging",
                    input_fingerprint=bootstrap._input_fingerprint(),
                    lineage_depth=0,
                    estimated_write_rows=resource[0],
                    estimated_write_bytes=resource[1],
                    estimated_wal_bytes=resource[2],
                    estimated_disk_headroom_bytes=resource[3],
                    checkpoint_json=checkpoint_a,
                    last_key="terminal-key-a",
                    source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
                )
            )
            setup.commit()

        barrier = threading.Barrier(2)
        committed = threading.Barrier(2)
        errors: list[BaseException] = []

        def stale_verifier() -> None:
            try:
                with factory() as stale_read:
                    stale = stale_read.get(SettlementProjectionGeneration, generation_id)
                    assert stale is not None
                    assert stale.checkpoint_json == checkpoint_a
                barrier.wait(timeout=5)
                committed.wait(timeout=5)
                transition(factory, generation_id)
            except BaseException as exc:  # pragma: no cover - assertion handoff
                errors.append(exc)

        def peer_advancer() -> None:
            try:
                barrier.wait(timeout=5)
                with factory() as peer:
                    peer.execute(
                        update(SettlementProjectionGeneration)
                        .where(
                            SettlementProjectionGeneration.generation_id == generation_id,
                            SettlementProjectionGeneration.state == "staging",
                        )
                        .values(checkpoint_json=checkpoint_b, last_key="terminal-key-b")
                    )
                    peer.commit()
                committed.wait(timeout=5)
            except BaseException as exc:  # pragma: no cover - assertion handoff
                errors.append(exc)

        verifier = threading.Thread(target=stale_verifier)
        peer = threading.Thread(target=peer_advancer)
        verifier.start()
        peer.start()
        verifier.join(timeout=10)
        peer.join(timeout=10)
        assert not errors
        try:
            with factory() as check:
                generation = check.get(SettlementProjectionGeneration, generation_id)
                assert generation is not None
                assert generation.state == "ready"
                assert generation.last_key == "terminal-key-b"
                assert generation.checkpoint_json["phase"] == "verify"
                assert generation.checkpoint_json["batch_count"] == 2
                assert generation.checkpoint_json["source_row_count"] == 2
                assert generation.checkpoint_json["artifact"] is None
                assert generation.checkpoint_json["cursor"] is None
        finally:
            engine.dispose()


def test_different_published_pointer_is_typed_conflict_without_mutation(db_session: Session):
    db_session.add(
        SettlementProjectionGeneration(
            generation_id="legacy-null-root:other",
            projection_name="settlement",
            state="published",
            input_fingerprint="f" * 64,
            lineage_depth=0,
            estimated_write_rows=0,
            estimated_write_bytes=16384,
            estimated_wal_bytes=32768,
            estimated_disk_headroom_bytes=100000,
            checkpoint_json={"protocol": "other", "operation": "other"},
            source_input_json={},
        )
    )
    db_session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id="legacy-null-root:other"
        )
    )
    db_session.commit()
    with pytest.raises(Exception, match="different generation"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits()
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 1
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert pointer is not None
        assert pointer.generation_id == "legacy-null-root:other"


def test_malformed_checkpoint_is_not_auto_normalized(db_session: Session):
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=0,
            estimated_write_bytes=16384,
            estimated_wal_bytes=32768,
            estimated_disk_headroom_bytes=100000,
            checkpoint_json={"protocol": "wrong", "operation": "legacy-null-root"},
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.commit()
    with pytest.raises(Exception, match="checkpoint"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits()
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None
        assert generation.state == "failed"


def test_empty_root_with_sqlite_foreign_keys_enabled():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, future=True)
    result = certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits())
    assert result.status == "published"
    with factory() as check:
        assert check.get(SettlementProjectionActive, "settlement").generation_id == result.generation_id


def test_keyset_scan_uses_fresh_sessions_and_bounded_pages(db_session: Session):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month=f"2026-{month:02d}",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id=f"run-{month}",
            )
            for month in range(1, 6)
        ]
    )
    db_session.commit()
    base_factory = _factory(db_session)
    sessions: list[Session] = []
    statements: list[str] = []
    parameters: list[object] = []

    def factory():
        session = base_factory()
        sessions.append(session)
        return session

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.upper())
        parameters.append(_parameters)

    result = certify_legacy_null_root(factory, batch_size=2, resource_limits=_limits(rows=5))
    assert result.status == "published"
    assert len(sessions) >= 8
    assert all(not session.in_transaction() for session in sessions)
    assert all(len(session.identity_map) == 0 for session in sessions)
    assert not any(" OFFSET " in statement for statement in statements)
    source_selects = [
        statement
        for statement in statements
        if "AGG_STORE_MONTHLY_SETTLEMENT" in statement
        and "LIMIT" in statement
    ]
    assert source_selects
    assert all("LIMIT" in statement for statement in source_selects)
    source_limits = []
    for index, statement in enumerate(statements):
        if "AGG_STORE_MONTHLY_SETTLEMENT" not in statement or "LIMIT" not in statement:
            continue
        raw_parameters = parameters[index]
        if isinstance(raw_parameters, dict):
            source_limits.append(raw_parameters.get("page_limit"))
        elif isinstance(raw_parameters, (tuple, list)):
            source_limits.append(raw_parameters[-1])
    assert source_limits
    assert all(isinstance(limit, int) and 1 <= limit <= 2 for limit in source_limits)


def test_long_single_partition_has_linear_source_page_queries(db_session: Session):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id=f"long-partition-{index:02d}",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id=f"long-run-{index:02d}",
            )
            for index in range(12)
        ]
    )
    db_session.commit()
    source_sql: list[str] = []

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _capture_source_pages(_conn, _cursor, statement, _parameters, _context, _executemany):
        upper = statement.upper()
        if "FROM AGG_STORE_MONTHLY_SETTLEMENT" in upper and "LIMIT" in upper:
            source_sql.append(upper)

    result = certify_legacy_null_root(
        _factory(db_session), batch_size=2, resource_limits=_limits(rows=1)
    )
    assert result.status == "published"
    assert len(source_sql) <= 24


def test_all_artifact_pages_and_verification_are_keyset_bounded(
    db_session: Session, monkeypatch
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="bound-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="bound-monthly-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="bound-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="bound-monthly-b",
            ),
            AggStoreRanking(
                period_type=1,
                period_key="2026-08",
                month="2026-08",
                store_id="bound-store",
                store_name="Bound Store",
                product_scope="all",
                product_type="all",
                projection_run_id="bound-ranking-a",
                promotion_net_fee_cent=10,
                management_net_fee_cent=4,
                net_settlement_reference_cent=6,
            ),
            AggStoreRanking(
                period_type=2,
                period_key="2026-09",
                month="2026-09",
                store_id="bound-store",
                store_name="Bound Store",
                product_scope="all",
                product_type="all",
                projection_run_id="bound-ranking-b",
                promotion_net_fee_cent=20,
                management_net_fee_cent=5,
                net_settlement_reference_cent=15,
            ),
            StoreScoreSnapshotRun(
                snapshot_run_id="bound-score-a",
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                config_json={"rule_version_id": "bound-rule"},
                computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
            StoreScoreSnapshotRun(
                snapshot_run_id="bound-score-b",
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                config_json={"rule_version_id": "bound-rule"},
                computed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            ),
            StoreScoreSnapshot(
                snapshot_id="bound-score-snapshot-a",
                snapshot_run_id="bound-score-a",
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                store_id="bound-store",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                composite_score=Decimal("0.4"),
                computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
            StoreScoreSnapshot(
                snapshot_id="bound-score-snapshot-b",
                snapshot_run_id="bound-score-b",
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                store_id="bound-store",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                composite_score=Decimal("0.5"),
                computed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()
    base_factory = _factory(db_session)
    sessions: list[Session] = []
    statements: list[str] = []
    parameters: list[object] = []
    pages: list[tuple[str, int]] = []

    def factory():
        session = base_factory()
        sessions.append(session)
        return session

    original_select = bootstrap._select_source_page

    def capture_page(session, artifact, batch_size, cursor):
        page = original_select(session, artifact, batch_size, cursor)
        pages.append((artifact, len(page)))
        return page

    monkeypatch.setattr(bootstrap, "_select_source_page", capture_page)

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.upper())
        parameters.append(_parameters)

    result = certify_legacy_null_root(
        factory, batch_size=1, resource_limits=_limits(rows=6)
    )
    assert result.status == "published"
    assert {artifact for artifact, _size in pages} == {"monthly", "ranking", "score"}
    assert pages
    assert all(size <= 1 for _artifact, size in pages)
    assert all(len(session.identity_map) <= 9 for session in sessions)
    assert all(not session.in_transaction() for session in sessions)
    assert not any(" OFFSET " in statement for statement in statements)

    source_tables = (
        "AGG_STORE_MONTHLY_SETTLEMENT",
        "AGG_STORE_RANKING",
        "STORE_SCORE_SNAPSHOTS AS S",
    )
    source_limited = [
        (statement, parameters[index])
        for index, statement in enumerate(statements)
        if "LIMIT" in statement and any(table in statement for table in source_tables)
    ]
    assert source_limited
    for statement, raw_parameters in source_limited:
        if isinstance(raw_parameters, dict):
            limit = raw_parameters.get("page_limit")
        else:
            limit = raw_parameters[-1]
        assert isinstance(limit, int) and limit <= 1

    manifest_limited = [
        (statement, parameters[index])
        for index, statement in enumerate(statements)
        if "SETTLEMENT_PROJECTION_PARTITION_MANIFEST" in statement
        and "LIMIT" in statement
    ]
    assert manifest_limited
    for _statement, raw_parameters in manifest_limited:
        if isinstance(raw_parameters, dict):
            limit = raw_parameters.get("page_limit")
        else:
            limit = raw_parameters[-1]
        assert isinstance(limit, int) and limit <= 400


def test_failed_generation_cleanup_uses_batch_bounded_keyset_pages(
    db_session: Session, monkeypatch
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="cleanup-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="cleanup-run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="cleanup-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="cleanup-run-b",
            ),
        ]
    )
    db_session.commit()
    original_partition = bootstrap._monthly_partition
    original_preflight = bootstrap._preflight_source_integrity
    injected = {"done": False, "armed": False}

    def fail_second_partition(row):
        if (
            injected["armed"]
            and row.get("month") == "2026-09"
            and not injected["done"]
        ):
            injected["done"] = True
            raise bootstrap.LegacyProjectionBootstrapError(
                "injected durable cleanup seed corruption"
            )
        return original_partition(row)

    def arm_after_preflight(factory, batch_size):
        result = original_preflight(factory, batch_size)
        injected["armed"] = True
        return result

    monkeypatch.setattr(bootstrap, "_monthly_partition", fail_second_partition)
    monkeypatch.setattr(bootstrap, "_preflight_source_integrity", arm_after_preflight)
    factory = _factory(db_session)
    with pytest.raises(Exception, match="injected durable cleanup seed corruption"):
        certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits(rows=2))
    monkeypatch.setattr(bootstrap, "_monthly_partition", original_partition)

    statements: list[str] = []
    parameters: list[object] = []

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _capture_cleanup(_conn, _cursor, statement, _parameters, _context, _executemany):
        upper = statement.upper()
        if "SETTLEMENT_PROJECTION_PARTITION_MANIFEST" in upper and "LIMIT" in upper:
            statements.append(upper)
            parameters.append(_parameters)

    result = certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits(rows=2))
    assert result.status == "published"
    assert statements
    cleanup_queries = [
        (statement, raw_parameters)
        for statement, raw_parameters in zip(statements, parameters)
        if "SELECT ARTIFACT, PARTITION_KEY" in statement
    ]
    fetch_queries = [
        (statement, raw_parameters)
        for statement, raw_parameters in zip(statements, parameters)
        if "SELECT GENERATION_ID, ARTIFACT, PARTITION_KEY" in statement
    ]
    assert cleanup_queries
    assert fetch_queries
    for _statement, raw_parameters in cleanup_queries:
        limit = (
            raw_parameters.get("page_limit")
            if isinstance(raw_parameters, dict)
            else raw_parameters[-1]
        )
        assert isinstance(limit, int) and limit <= 1
    for _statement, raw_parameters in fetch_queries:
        limit = (
            raw_parameters.get("page_limit")
            if isinstance(raw_parameters, dict)
            else raw_parameters[-1]
        )
        assert isinstance(limit, int) and limit <= 400
    assert all(" OFFSET " not in statement for statement in statements)


@pytest.mark.parametrize("iteration", range(10))
def test_concurrent_same_root_certifiers_have_one_winner_and_one_idempotent_loser(
    iteration: int,
):
    with tempfile.TemporaryDirectory(prefix="legacy-root-test-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{directory}/cert.sqlite",
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as seed:
            seed.add_all(
                [
                    AggStoreMonthlySettlement(
                        month=f"2026-{month:02d}",
                        store_id="concurrent-store",
                        product_scope="all",
                        product_type="all",
                        statement_status=1,
                        projection_run_id=f"concurrent-run-{month}",
                    )
                    for month in range(1, 6)
                ]
            )
            seed.commit()

        barrier = threading.Barrier(2)

        def certify():
            barrier.wait(timeout=30)
            return certify_legacy_null_root(
                factory, batch_size=1, resource_limits=_limits(rows=5)
            )

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _item: certify(), (1, 2)))
            statuses = sorted(result.status for result in results)
            assert statuses == ["already_published", "published"]
            assert results[0].generation_id == results[1].generation_id
            with factory() as check:
                assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 1
                assert check.scalar(select(func.count()).select_from(SettlementProjectionActive)) == 1
                pointer = check.get(SettlementProjectionActive, "settlement")
                assert pointer is not None
                assert pointer.generation_id == results[0].generation_id
                manifest_rows = list(
                    check.execute(
                        select(SettlementProjectionPartitionManifest).order_by(
                            SettlementProjectionPartitionManifest.partition_key
                        )
                    ).scalars()
                )
                assert [row.partition_key for row in manifest_rows] == [
                    f"2026-{month:02d}" for month in range(1, 6)
                ]
                assert check.scalar(
                    select(func.count()).select_from(SettlementProjectionGeneration).where(
                        SettlementProjectionGeneration.state != "published"
                    )
                ) == 0
        finally:
            engine.dispose()


def test_certification_records_monthly_ranking_and_score_manifests(db_session: Session):
    db_session.add(DimStore(store_id="store-cert", store_name="Certified Store"))
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="store-cert",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="monthly-run",
            promotion_net_fee_cent=150,
            management_net_fee_cent=50,
        )
    )
    db_session.add(
        AggStoreRanking(
            period_type=1,
            period_key="2026-08",
            month="2026-08",
            store_id="store-cert",
            store_name="Certified Store",
            product_scope="all",
            product_type="all",
            projection_run_id="ranking-run",
            promotion_net_fee_cent=200,
            management_net_fee_cent=80,
            net_settlement_reference_cent=120,
        )
    )
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="score-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            config_json={"rule_version_id": "rule-cert"},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id="score-snapshot",
            snapshot_run_id="score-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            store_id="store-cert",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            conversion_rate=Decimal("0.5"),
            follow_24h_rate=Decimal("0.25"),
            conversion_weight=Decimal("0.7"),
            follow_24h_weight=Decimal("0.3"),
            store_weight=Decimal("1"),
            composite_score=Decimal("0.4"),
            config_json={"rule_version_id": "rule-cert"},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="score-run-b",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            config_json={"rule_version_id": "rule-cert"},
            computed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id="score-snapshot-b",
            snapshot_run_id="score-run-b",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            store_id="store-cert",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            conversion_rate=Decimal("0.6"),
            follow_24h_rate=Decimal("0.3"),
            conversion_weight=Decimal("0.7"),
            follow_24h_weight=Decimal("0.3"),
            store_weight=Decimal("1"),
            composite_score=Decimal("0.5"),
            config_json={"rule_version_id": "rule-cert"},
            computed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    with _factory(db_session)() as check:
        assert check.get(SettlementProjectionActive, "settlement") is None
    source_before = {
        "monthly": db_session.scalar(select(func.count()).select_from(AggStoreMonthlySettlement)),
        "ranking": db_session.scalar(select(func.count()).select_from(AggStoreRanking)),
        "score_run": db_session.scalar(select(func.count()).select_from(StoreScoreSnapshotRun)),
        "score": db_session.scalar(select(func.count()).select_from(StoreScoreSnapshot)),
    }

    result = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=3)
    )

    assert result.status == "published"
    assert result.generation_id == bootstrap._generation_id()
    assert result.published is True
    assert result.resumed is False
    assert result.batch_count == 4
    assert result.partition_count == 3
    assert result.source_row_count == 4
    assert result.last_key == (
        '{"artifact":"score","cursor":{"rule_version_id":"rule-cert",'
        '"snapshot_date":"2026-08-01","snapshot_id":"score-snapshot-b",'
        '"snapshot_run_id":"score-run-b","store_id":"store-cert"}}'
    )
    assert result.manifest_checksum == (
        "eddcb33cbde3660da44b721acf308699b16b58241ab9d1e98fe7b3132be41860"
    )
    assert result.failure_code is None
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, result.generation_id)
        assert generation is not None
        assert generation.estimated_write_rows == 3
        assert generation.estimated_write_bytes == 16384 + (4096 * 3)
        assert generation.estimated_wal_bytes == 2 * generation.estimated_write_bytes
        assert generation.estimated_disk_headroom_bytes == 1_000_000
        manifests = list(
            check.execute(
                select(SettlementProjectionPartitionManifest).order_by(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
            ).scalars()
        )
        assert {(row.artifact, row.partition_key) for row in manifests} == {
            ("monthly", "2026-08"),
            ("ranking", "monthly:2026-08"),
            ("score", "2026-08-01|9:rule-cert|10:store-cert"),
        }
        by_key = {(row.artifact, row.partition_key): row for row in manifests}
        assert by_key[("monthly", "2026-08")].amount_total_cent == 100
        assert by_key[("monthly", "2026-08")].status_counts_json == {"1": 1}
        assert by_key[("ranking", "monthly:2026-08")].amount_total_cent == 120
        assert by_key[("ranking", "monthly:2026-08")].status_counts_json == {}
        assert by_key[("score", "2026-08-01|9:rule-cert|10:store-cert")].amount_total_cent == 0
        assert {
            "monthly": check.scalar(select(func.count()).select_from(AggStoreMonthlySettlement)),
            "ranking": check.scalar(select(func.count()).select_from(AggStoreRanking)),
            "score_run": check.scalar(select(func.count()).select_from(StoreScoreSnapshotRun)),
            "score": check.scalar(select(func.count()).select_from(StoreScoreSnapshot)),
        } == source_before


def test_r6_score_certification_publishes_delimited_unicode_partition(
    db_session: Session,
):
    rule_id = "规则|版本:一"
    store_id = "门店:北|A"
    db_session.add(DimStore(store_id=store_id, store_name="Delimited Unicode Store"))
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="r6-score-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            config_json={"rule_version_id": rule_id},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id="r6-score-snapshot",
            snapshot_run_id="r6-score-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            store_id=store_id,
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            conversion_rate=Decimal("0.5"),
            follow_24h_rate=Decimal("0.25"),
            conversion_weight=Decimal("0.7"),
            follow_24h_weight=Decimal("0.3"),
            store_weight=Decimal("1"),
            composite_score=Decimal("0.4"),
            config_json={"rule_version_id": rule_id},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    expected_partition = bootstrap.canonical_score_partition_key(
        date(2026, 8, 1), rule_id, store_id
    )
    result = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )

    assert result.status == "published"
    assert result.partition_count == 1
    assert result.source_row_count == 1
    with _factory(db_session)() as check:
        manifest = check.scalar(
            select(SettlementProjectionPartitionManifest).where(
                SettlementProjectionPartitionManifest.artifact == "score"
            )
        )
        assert manifest is not None
        assert manifest.partition_key == expected_partition
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert pointer is not None
        assert pointer.generation_id == result.generation_id


def test_failed_batch_commit_resumes_from_durable_checkpoint(db_session: Session):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="run-a",
                promotion_net_fee_cent=10,
                management_net_fee_cent=2,
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=2,
                projection_run_id="run-b",
                promotion_net_fee_cent=20,
                management_net_fee_cent=4,
            ),
        ]
    )
    db_session.commit()

    base_factory = _factory(db_session)
    state = {"commits": 0, "failed": False}

    class FailingSession(Session):
        def commit(self):  # type: ignore[override]
            state["commits"] += 1
            if state["commits"] == 2 and not state["failed"]:
                state["failed"] = True
                raise RuntimeError("injected interruption before batch commit")
            return super().commit()

    failing_factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, future=True, class_=FailingSession
    )
    try:
        certify_legacy_null_root(
            failing_factory, batch_size=1, resource_limits=_limits(rows=2)
        )
    except Exception as exc:
        assert "certification failed" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("injected interruption unexpectedly published")

    with base_factory() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        assert generation is not None
        assert generation.state == "staging"
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 0

    resumed = certify_legacy_null_root(
        base_factory, batch_size=1, resource_limits=_limits(rows=2)
    )
    assert resumed.status == "published"
    assert resumed.resumed is True
    assert resumed.partition_count == 2
    assert resumed.source_row_count == 2


def test_resume_writes_only_after_durable_cursor_and_does_not_repeat_page(
    db_session: Session, monkeypatch
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="run-a",
                promotion_net_fee_cent=10,
                management_net_fee_cent=2,
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=2,
                projection_run_id="run-b",
                promotion_net_fee_cent=20,
                management_net_fee_cent=4,
            ),
        ]
    )
    db_session.commit()
    state = {"commits": 0, "failed": False}

    class FailingSession(Session):
        def commit(self):  # type: ignore[override]
            state["commits"] += 1
            if state["commits"] == 3 and not state["failed"]:
                state["failed"] = True
                raise RuntimeError("injected interruption after first page")
            return super().commit()

    failing_factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, future=True, class_=FailingSession
    )
    try:
        certify_legacy_null_root(
            failing_factory, batch_size=1, resource_limits=_limits(rows=2)
        )
    except Exception:
        pass
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("injected interruption unexpectedly published")

    with _factory(db_session)() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        assert generation is not None
        durable_last_key = generation.last_key
        durable_checkpoint = generation.checkpoint_json
        assert durable_last_key is not None
        assert durable_checkpoint["cursor"] is not None

    captured_payloads: list[dict[str, object]] = []
    original_upsert = bootstrap._upsert_manifests

    def capture_upsert(session, payloads):
        captured_payloads.extend(dict(payload) for payload in payloads)
        return original_upsert(session, payloads)

    monkeypatch.setattr(bootstrap, "_upsert_manifests", capture_upsert)

    retry = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=2)
    )
    assert retry.status == "published"
    assert retry.resumed is True
    assert retry.partition_count == 2
    assert retry.source_row_count == 2
    assert captured_payloads
    assert all(payload["last_key"] != durable_last_key for payload in captured_payloads)
    assert all(str(payload["last_key"]) > durable_last_key for payload in captured_payloads)


def test_page_checkpoint_cas_retries_same_last_key_with_changed_checkpoint(
    db_session: Session, monkeypatch
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="cas-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="cas-run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="cas-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="cas-run-b",
            ),
        ]
    )
    db_session.commit()
    resource = (2, 24_576, 49_152, 1_000_000)
    initial_checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact="monthly",
        cursor=None,
        stats=bootstrap._ScanStats(),
        resource=resource,
    )
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=initial_checkpoint,
            last_key=None,
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.commit()
    attempts = {"count": 0, "injected": False}
    original_upsert = bootstrap._upsert_manifests

    def inject_peer_checkpoint(session, payloads):
        attempts["count"] += 1
        if not attempts["injected"]:
            attempts["injected"] = True
            peer_checkpoint = bootstrap._checkpoint(
                phase="scan",
                artifact="monthly",
                cursor=None,
                stats=bootstrap._ScanStats(),
                resource=resource,
            )
            peer_checkpoint["peer_marker"] = "same-last-key-peer"
            session.execute(
                update(SettlementProjectionGeneration)
                .where(
                    SettlementProjectionGeneration.generation_id
                    == bootstrap._generation_id(),
                    SettlementProjectionGeneration.state == "staging",
                )
                .values(checkpoint_json=peer_checkpoint, last_key=None)
            )
            # Commit the peer's changed checkpoint before the stale page CAS.
            session.commit()
        return original_upsert(session, payloads)

    monkeypatch.setattr(bootstrap, "_upsert_manifests", inject_peer_checkpoint)
    next_checkpoint, _stats = bootstrap._scan_artifact(
        _factory(db_session),
        bootstrap._generation_id(),
        "monthly",
        1,
        initial_checkpoint,
        resource,
    )
    # The first page sees the same durable last_key (NULL) but a different
    # checkpoint JSON, so the checkpoint CAS must reject it and retry once.
    assert attempts["count"] == 3
    assert next_checkpoint["source_row_count"] == 2


def test_stale_scanner_adopts_peer_manifest_checkpoint_after_prefix_interleave(
    monkeypatch,
):
    """A peer page commit must be adopted, not marked as semantic corruption."""

    with tempfile.TemporaryDirectory(prefix="legacy-peer-adopt-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{Path(directory) / 'peer.db'}",
            connect_args={"check_same_thread": False, "timeout": 2.0},
            future=True,
        )
        Base.metadata.create_all(engine)
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as seed:
            seed.add_all(
                [
                    AggStoreMonthlySettlement(
                        month="2026-08",
                        store_id="peer-store",
                        product_scope="all",
                        product_type="all",
                        statement_status=1,
                        projection_run_id="peer-run-a",
                    ),
                    AggStoreMonthlySettlement(
                        month="2026-09",
                        store_id="peer-store",
                        product_scope="all",
                        product_type="all",
                        statement_status=1,
                        projection_run_id="peer-run-b",
                    ),
                ]
            )
            seed.commit()

        resource = (2, 24_576, 49_152, 1_000_000)
        initial_checkpoint = bootstrap._checkpoint(
            phase="scan",
            artifact="monthly",
            cursor=None,
            stats=bootstrap._ScanStats(),
            resource=resource,
        )
        with factory() as seed:
            seed.add(
                SettlementProjectionGeneration(
                    generation_id=bootstrap._generation_id(),
                    projection_name="settlement",
                    state="staging",
                    input_fingerprint=bootstrap._input_fingerprint(),
                    lineage_depth=0,
                    estimated_write_rows=resource[0],
                    estimated_write_bytes=resource[1],
                    estimated_wal_bytes=resource[2],
                    estimated_disk_headroom_bytes=resource[3],
                    checkpoint_json=initial_checkpoint,
                    last_key=None,
                    source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
                )
            )
            seed.commit()

        # Commit page 1 so the stale verifier starts with a real durable
        # cursor/manifest prefix, then crash after that physical commit.
        crash_state = {"armed": True}

        class CrashAfterCommitSession(Session):
            def commit(self):  # type: ignore[override]
                result = super().commit()
                if crash_state["armed"]:
                    crash_state["armed"] = False
                    raise RuntimeError("injected post-page commit crash")
                return result

        crash_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            future=True,
            class_=CrashAfterCommitSession,
        )
        with pytest.raises(RuntimeError, match="post-page commit crash"):
            bootstrap._scan_artifact(
                crash_factory,
                bootstrap._generation_id(),
                "monthly",
                1,
                initial_checkpoint,
                resource,
            )
        with factory() as check:
            first_generation = check.get(
                SettlementProjectionGeneration, bootstrap._generation_id()
            )
            assert first_generation is not None
            first_checkpoint = dict(first_generation.checkpoint_json)
        original_validate = bootstrap._validate_existing_manifests_prefix_once
        state = {"peer_advanced": False}

        def interleave_peer(
            factory_arg,
            generation_id,
            artifact,
            batch_size,
            durable_cursor,
            max_manifest_rows,
        ):
            if not state["peer_advanced"]:
                state["peer_advanced"] = True
                with factory() as peer:
                    peer_generation = peer.get(
                        SettlementProjectionGeneration, generation_id
                    )
                    assert peer_generation is not None
                    peer_checkpoint = dict(peer_generation.checkpoint_json)
                # The peer uses its freshly committed checkpoint and writes the
                # second manifest on its independent backend.
                bootstrap._scan_artifact(
                    factory,
                    generation_id,
                    artifact,
                    batch_size,
                    peer_checkpoint,
                    resource,
                )
                raise bootstrap.LegacyProjectionBootstrapError(
                    "source prefix has no certified manifest"
                )
            return original_validate(
                factory_arg,
                generation_id,
                artifact,
                batch_size,
                durable_cursor,
                max_manifest_rows,
            )

        monkeypatch.setattr(
            bootstrap,
            "_validate_existing_manifests_prefix_once",
            interleave_peer,
        )
        try:
            next_checkpoint, _stats = bootstrap._scan_artifact(
                factory,
                bootstrap._generation_id(),
                "monthly",
                1,
                first_checkpoint,
                resource,
            )
        finally:
            engine.dispose()

        assert state["peer_advanced"] is True
        assert next_checkpoint["artifact"] == "ranking"


def test_source_insert_between_scan_and_verify_fails_closed(db_session: Session, monkeypatch):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="store-a",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="run-a",
            promotion_net_fee_cent=10,
            management_net_fee_cent=2,
        )
    )
    db_session.commit()
    original_finalize = bootstrap._finalize_generation_fenced
    injected = {"done": False}

    def finalize_with_drift(factory, generation_id, resource, batch_size, resumed):
        if not injected["done"]:
            injected["done"] = True
            with _factory(db_session)() as writer:
                writer.add(
                    AggStoreMonthlySettlement(
                        month="2026-09",
                        store_id="store-a",
                        product_scope="all",
                        product_type="all",
                        statement_status=1,
                        projection_run_id="run-b",
                        promotion_net_fee_cent=20,
                        management_net_fee_cent=4,
                    )
                )
                writer.commit()
        return original_finalize(factory, generation_id, resource, batch_size, resumed)

    monkeypatch.setattr(bootstrap, "_finalize_generation_fenced", finalize_with_drift)
    try:
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    except Exception as exc:
        assert "certification failed" not in str(exc)
        assert "manifest" in str(exc) or "drift" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("source drift unexpectedly published")
    with _factory(db_session)() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        assert generation is not None
        assert generation.state == "failed"
        assert check.scalar(select(SettlementProjectionActive)) is None


@pytest.mark.parametrize("batch_size", [-1, 0, 401, True, None, "1", 1.0])
def test_public_batch_guard_matrix_makes_no_session_factory_calls(batch_size):
    calls = {"count": 0}

    def factory():
        calls["count"] += 1
        raise AssertionError("invalid public arguments must not open a session")

    result = certify_legacy_null_root(
        factory, batch_size=batch_size, resource_limits=_limits()
    )

    assert result.status == "resource_guard"
    assert result.failure_code == "invalid_batch_size"
    assert result.published is False
    assert result.generation_id is None
    assert result.resumed is False
    assert result.batch_count == 0
    assert result.partition_count == 0
    assert result.source_row_count == 0
    assert result.last_key is None
    assert result.manifest_checksum is None
    assert calls["count"] == 0


@pytest.mark.parametrize(
    "resource_limits",
    [
        None,
        ResourceGateConfig("10", 100_000, 200_000, 1_000_000, 0),
        ResourceGateConfig(10, 100_000.5, 200_000, 1_000_000, 0),
        ResourceGateConfig(10, True, 200_000, 1_000_000, 0),
        ResourceGateConfig(-1, 100_000, 200_000, 1_000_000, 0),
        ResourceGateConfig(10, 100_000, 200_000, 0, 1),
    ],
)
def test_public_resource_guard_matrix_makes_no_session_factory_calls(
    resource_limits: ResourceGateConfig | None,
):
    calls = {"count": 0}

    def factory():
        calls["count"] += 1
        raise AssertionError("invalid public arguments must not open a session")

    result = certify_legacy_null_root(
        factory, batch_size=1, resource_limits=resource_limits
    )

    assert result.status == "resource_guard"
    assert result.failure_code == "invalid_resource_config"
    assert result.published is False
    assert result.generation_id is None
    assert result.resumed is False
    assert result.batch_count == 0
    assert result.partition_count == 0
    assert result.source_row_count == 0
    assert result.last_key is None
    assert result.manifest_checksum is None
    assert calls["count"] == 0


@pytest.mark.parametrize("conflict_mode", ["cursor", "metadata"])
def test_existing_conflicting_manifest_metadata_fails_without_overwrite(
    db_session: Session, conflict_mode: str
):
    db_session.add_all(
        [
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="store-a",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="run-a",
        ),
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="store-b",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="run-b",
        ),
        ]
    )
    db_session.commit()
    generation_id = bootstrap._generation_id()
    resource = (1, 20_480, 40_960, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="scan",
                artifact="monthly",
                cursor={
                    "month": "2026-08",
                    "store_id": "store-a",
                    "product_scope": "all",
                    "product_type": "all",
                    "projection_run_id": "run-a",
                    "id": 1,
                },
                stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
                resource=resource,
            ),
            last_key=bootstrap._cursor_token(
                "monthly",
                {
                    "month": "2026-08",
                    "store_id": "store-a",
                    "product_scope": "all",
                    "product_type": "all",
                    "projection_run_id": "run-a",
                    "id": 1,
                },
            ),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.add(
        SettlementProjectionPartitionManifest(
            generation_id=generation_id,
            artifact="monthly",
            partition_key="2026-08",
            owner_state="owned",
            source_kind="legacy_root",
            data_generation_id=None,
            base_generation_id=None,
            row_count=1,
            amount_total_cent=999,
            status_counts_json={"9": 1},
            checksum="f" * 64,
            last_key=(
                "conflicting-last-key"
                if conflict_mode == "cursor"
                else bootstrap._cursor_token(
                    "monthly",
                    {
                        "month": "2026-08",
                        "store_id": "store-a",
                        "product_scope": "all",
                        "product_type": "all",
                        "projection_run_id": "run-a",
                        "id": 1,
                    },
                )
            ),
        )
    )
    db_session.commit()

    with pytest.raises(Exception, match="drift|conflict|manifest"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        assert generation is not None
        assert generation.state == "failed"
        assert generation.failure_code == "certification_failed"
        assert generation.failure_reason.startswith("certification_failed:")
        assert len(generation.failure_reason) <= 1000
        manifest = check.scalar(select(SettlementProjectionPartitionManifest))
        assert manifest is not None
        assert manifest.amount_total_cent == 999
        assert manifest.status_counts_json == {"9": 1}
        assert manifest.checksum == "f" * 64
        assert manifest.last_key == (
            "conflicting-last-key"
            if conflict_mode == "cursor"
            else bootstrap._cursor_token(
                "monthly",
                {
                    "month": "2026-08",
                    "store_id": "store-a",
                    "product_scope": "all",
                    "product_type": "all",
                    "projection_run_id": "run-a",
                    "id": 1,
                },
            )
        )
        assert check.scalar(select(SettlementProjectionActive)) is None


def test_zero_row_legacy_manifest_in_durable_prefix_fails_closed_without_overwrite(
    db_session: Session,
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="zero-manifest-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="zero-manifest-run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="zero-manifest-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="zero-manifest-run-b",
            ),
        ]
    )
    db_session.commit()
    raw_rows = bootstrap._select_source_page(db_session, "monthly", 2, None)
    assert len(raw_rows) == 2
    first = raw_rows[0]
    first_cursor = bootstrap._cursor_from_row("monthly", first)
    first_accumulator = bootstrap._PartitionAccumulator.fresh("monthly", "2026-08")
    first_accumulator.add(
        bootstrap._row_mapping(first, bootstrap._source_columns(AggStoreMonthlySettlement)),
        amount=int(first.get("promotion_net_fee_cent") or 0)
        - int(first.get("management_net_fee_cent") or 0),
        status=str(int(first.get("statement_status"))),
    )
    first_accumulator.last_key = bootstrap._cursor_token("monthly", first_cursor)
    generation_id = bootstrap._generation_id()
    resource = (2, 24_576, 49_152, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="scan",
                artifact="monthly",
                cursor=first_cursor,
                stats=bootstrap._ScanStats(
                    batch_count=1, partition_count=1, source_row_count=1
                ),
                resource=resource,
            ),
            last_key=first_accumulator.last_key,
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.add_all(
        [
            SettlementProjectionPartitionManifest(
                generation_id=generation_id,
                artifact="monthly",
                partition_key="2026-08",
                owner_state="owned",
                source_kind="legacy_root",
                data_generation_id=None,
                base_generation_id=None,
                row_count=first_accumulator.row_count,
                amount_total_cent=first_accumulator.amount_total_cent,
                status_counts_json={"1": 1},
                checksum=first_accumulator.digest,
                last_key=first_accumulator.last_key,
            ),
            SettlementProjectionPartitionManifest(
                generation_id=generation_id,
                artifact="monthly",
                partition_key="2026-09",
                owner_state="owned",
                source_kind="legacy_root",
                data_generation_id=None,
                base_generation_id=None,
                row_count=0,
                amount_total_cent=0,
                status_counts_json={},
                checksum=bootstrap._sha256(bootstrap._canonical_json({"rows": []})),
                last_key=None,
            ),
        ]
    )
    db_session.commit()

    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError,
        match="manifest|row_count|empty|zero",
    ):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=2)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, generation_id)
        assert generation is not None
        assert generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None
        corrupt = check.get(
            SettlementProjectionPartitionManifest,
            (generation_id, "monthly", "2026-09"),
        )
        assert corrupt is not None
        assert corrupt.row_count == 0
        assert corrupt.last_key is None


def test_legacy_root_manifest_zero_row_is_typed_corruption():
    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError,
        match="row_count|empty|zero",
    ):
        bootstrap._validate_manifest_row(
            {
                "artifact": "monthly",
                "partition_key": "2026-09",
                "owner_state": "owned",
                "source_kind": "legacy_root",
                "data_generation_id": None,
                "base_generation_id": None,
                "row_count": 0,
                "amount_total_cent": 0,
                "status_counts_json": {},
                "checksum": bootstrap._sha256(bootstrap._canonical_json({"rows": []})),
                "last_key": None,
            },
            "monthly",
        )


@pytest.mark.parametrize("drift", ["insert", "update", "delete"])
def test_source_drift_insert_update_delete_fails_closed(
    db_session: Session, monkeypatch, drift: str
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="run-a",
                promotion_net_fee_cent=10,
                management_net_fee_cent=2,
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="store-a",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="run-b",
                promotion_net_fee_cent=20,
                management_net_fee_cent=4,
            ),
        ]
    )
    db_session.commit()
    original_finalize = bootstrap._finalize_generation_fenced
    injected = {"done": False}

    def finalize_with_drift(factory, generation_id, resource, batch_size, resumed):
        if not injected["done"]:
            injected["done"] = True
            with _factory(db_session)() as writer:
                rows = list(
                    writer.scalars(
                        select(AggStoreMonthlySettlement).order_by(
                            AggStoreMonthlySettlement.month
                        )
                    )
                )
                if drift == "insert":
                    writer.add(
                        AggStoreMonthlySettlement(
                            month="2026-10",
                            store_id="store-a",
                            product_scope="all",
                            product_type="all",
                            statement_status=1,
                            projection_run_id="run-c",
                        )
                    )
                elif drift == "update":
                    rows[0].promotion_net_fee_cent = 999
                else:
                    writer.delete(rows[-1])
                writer.commit()
        return original_finalize(factory, generation_id, resource, batch_size, resumed)

    monkeypatch.setattr(bootstrap, "_finalize_generation_fenced", finalize_with_drift)
    with pytest.raises(Exception, match="manifest|drift"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=2)
        )
    with _factory(db_session)() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        assert generation is not None
        assert generation.state == "failed"
        assert check.scalar(select(SettlementProjectionActive)) is None


@pytest.mark.parametrize(
    "failure_mode", ["before_ready", "during_verify", "before_pointer", "inside_publish"]
)
def test_crash_matrix_never_exposes_partial_root_and_retry_converges(
    db_session: Session, monkeypatch, failure_mode: str
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="crash-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="crash-run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="crash-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="crash-run-b",
            ),
        ]
    )
    db_session.commit()
    injected = {"done": False}
    if failure_mode == "before_ready":
        original_finalize = bootstrap._finalize_generation_fenced

        def fail_before_ready(factory, generation_id, resource, batch_size, resumed):
            if not injected["done"]:
                injected["done"] = True
                raise RuntimeError("injected failure before fenced ready")
            return original_finalize(factory, generation_id, resource, batch_size, resumed)

        monkeypatch.setattr(bootstrap, "_finalize_generation_fenced", fail_before_ready)
    elif failure_mode == "during_verify":
        original_verify = bootstrap._verify_artifact
        injected["verify_active"] = False
        injected["verify_pages"] = 0

        @event.listens_for(db_session.get_bind(), "before_cursor_execute")
        def _fail_inside_verify_after_page(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ):
            if (
                injected["verify_active"]
                and not injected["done"]
                and "AGG_STORE_MONTHLY_SETTLEMENT" in statement.upper()
                and "LIMIT" in statement.upper()
            ):
                if injected["verify_pages"] >= 1:
                    injected["done"] = True
                    raise RuntimeError("injected failure during verify after source page")
                injected["verify_pages"] += 1

        def fail_inside_verify(factory, generation_id, artifact, batch_size):
            if artifact != "monthly":
                return original_verify(factory, generation_id, artifact, batch_size)
            injected["verify_active"] = True
            try:
                return original_verify(factory, generation_id, artifact, batch_size)
            finally:
                injected["verify_active"] = False

        monkeypatch.setattr(bootstrap, "_verify_artifact", fail_inside_verify)
    elif failure_mode == "before_pointer":
        injected["pointer_insert_active"] = False

        @event.listens_for(db_session.get_bind(), "before_cursor_execute")
        def _fail_immediately_before_pointer_insert(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ):
            if (
                injected["pointer_insert_active"]
                and not injected["done"]
                and "INSERT INTO SETTLEMENT_PROJECTION_ACTIVE" in statement.upper()
            ):
                injected["done"] = True
                raise RuntimeError("injected failure immediately before fenced pointer materialization")

        injected["pointer_insert_active"] = True
        event.listen(db_session.get_bind(), "before_cursor_execute", _fail_immediately_before_pointer_insert)
    else:
        injected["pointer_cas"] = False
        bind = db_session.get_bind()

        def _observe_pointer_cas(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ):
            if (
                "UPDATE SETTLEMENT_PROJECTION_ACTIVE SET GENERATION_ID" in statement.upper()
                and not injected["done"]
            ):
                injected["pointer_cas"] = True
                injected["done"] = True
                raise RuntimeError("injected failure after real pointer CAS before coordinator commit")

        event.listen(bind, "after_cursor_execute", _observe_pointer_cas)

    factory = _factory(db_session)
    with pytest.raises(Exception, match="certification failed|injected"):
        certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits(rows=2))
    if failure_mode == "during_verify":
        assert injected["verify_pages"] >= 1
    if failure_mode == "before_pointer":
        assert injected["done"] is True
    with _factory(db_session)() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        assert generation is not None
        assert generation.state in {"staging", "ready"}
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert pointer is None or pointer.generation_id is None
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) <= 2

    retry = certify_legacy_null_root(
        factory, batch_size=1, resource_limits=_limits(rows=2)
    )
    assert retry.status == "published"
    assert retry.published is True
    assert retry.resumed is True
    with _factory(db_session)() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        assert generation is not None
        assert generation.state == "published"
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert pointer is not None
        assert pointer.generation_id == retry.generation_id
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 2


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("period_key", "2026-8", "YYYY-MM"),
        ("store_id", " store-a", "identity"),
        ("product_scope", " all", "identity"),
        ("projection_run_id", " ", "identity"),
    ],
)
def test_invalid_ranking_identity_fails_closed(
    db_session: Session, field: str, value, match: str
):
    row = AggStoreRanking(
        period_type=1,
        period_key="2026-08",
        month="2026-08",
        store_id="store-a",
        store_name="Store A",
        product_scope="all",
        product_type="all",
        projection_run_id="ranking-run",
    )
    setattr(row, field, value)
    db_session.add(row)
    db_session.commit()
    with pytest.raises(Exception, match=match):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 0
        assert check.scalar(select(SettlementProjectionActive)) is None


def test_invalid_ranking_period_type_is_rejected_by_partition_identity_helper():
    with pytest.raises(Exception, match="period_type"):
        bootstrap._ranking_partition(
            {
                "period_type": 3,
                "period_key": "2026-08",
                "month": "2026-08",
                "store_id": "store-a",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": "run-a",
            }
        )


@pytest.mark.parametrize(
    ("helper", "field", "value", "match"),
    [
        ("monthly", "month", "2026-8", "YYYY-MM"),
        ("monthly", "month", "2026-08 ", "YYYY-MM"),
        ("monthly", "store_id", " store-a", "canonical identity"),
        ("monthly", "product_scope", "", "canonical identity"),
        ("monthly", "product_type", "all ", "canonical identity"),
        ("monthly", "projection_run_id", " ", "canonical identity"),
        ("ranking", "period_key", "2026-8", "YYYY-MM"),
        ("ranking", "month", "2026-09", "period_key"),
        ("ranking", "store_id", "store-a ", "canonical identity"),
        ("ranking", "product_scope", " ", "canonical identity"),
        ("ranking", "product_type", "", "canonical identity"),
        ("ranking", "projection_run_id", "run ", "canonical identity"),
        ("score", "snapshot_id", " ", "canonical identity"),
        ("score", "snapshot_run_id", "run ", "canonical identity"),
        ("score", "store_id", " store-a", "canonical identity"),
    ],
)
def test_partition_identity_helpers_reject_noncanonical_values(
    helper: str, field: str, value, match: str
):
    monthly = {
        "month": "2026-08",
        "store_id": "store-a",
        "product_scope": "all",
        "product_type": "all",
        "projection_run_id": "run-a",
        "statement_status": 1,
    }
    ranking = {
        "period_type": 1,
        "period_key": "2026-08",
        "month": "2026-08",
        "store_id": "store-a",
        "product_scope": "all",
        "product_type": "all",
        "projection_run_id": "run-a",
    }
    score = {
        "snapshot_id": "snapshot-a",
        "snapshot_run_id": "run-a",
        "snapshot_date": date(2026, 8, 1),
        "run_snapshot_date": date(2026, 8, 1),
        "store_id": "store-a",
        "rule_version_id": "rule-a",
    }
    row = {"monthly": monthly, "ranking": ranking, "score": score}[helper]
    row[field] = value
    partition_helper = {
        "monthly": bootstrap._monthly_partition,
        "ranking": bootstrap._ranking_partition,
        "score": bootstrap._score_partition,
    }[helper]
    with pytest.raises(Exception, match=match):
        partition_helper(row)


@pytest.mark.parametrize(
    ("field", "value", "match", "expect_generation"),
    [
        ("snapshot_id", " ", "canonical identity", False),
        ("snapshot_run_id", " ", "invalid identity", False),
        ("store_id", " store-a", "canonical identity", False),
    ],
)
def test_invalid_score_identity_fails_before_generation_write(
    db_session: Session, field: str, value, match: str, expect_generation: bool
):
    run = StoreScoreSnapshotRun(
        snapshot_run_id="score-run",
        snapshot_date=date(2026, 8, 1),
        run_mode="scheduled",
        window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
        config_json={"rule_version_id": "rule-a"},
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    row = StoreScoreSnapshot(
        snapshot_id="score-snapshot",
        snapshot_run_id="score-run",
        snapshot_date=date(2026, 8, 1),
        run_mode="scheduled",
        store_id="store-a",
        window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    setattr(row, field, value)
    db_session.add_all([run, row])
    db_session.commit()
    with pytest.raises(Exception, match=match):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation_count = check.scalar(
            select(func.count()).select_from(SettlementProjectionGeneration)
        )
        assert generation_count == (1 if expect_generation else 0)
        if expect_generation:
            generation = check.scalar(select(SettlementProjectionGeneration))
            assert generation is not None
            assert generation.state == "failed"
        assert check.scalar(select(SettlementProjectionActive)) is None


def test_score_run_date_mismatch_fails_before_generation_write(db_session: Session):
    db_session.add_all(
        [
            StoreScoreSnapshotRun(
                snapshot_run_id="score-run",
                snapshot_date=date(2026, 8, 2),
                run_mode="scheduled",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                config_json={"rule_version_id": "rule-a"},
                computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
            StoreScoreSnapshot(
                snapshot_id="score-snapshot",
                snapshot_run_id="score-run",
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                store_id="store-a",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()
    with pytest.raises(Exception, match="date mismatch"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0
        assert check.scalar(select(SettlementProjectionActive)) is None


def _value_snapshot(session: Session, table_names: tuple[str, ...]) -> dict[str, tuple[int, str]]:
    snapshots: dict[str, tuple[int, str]] = {}
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        primary_key_columns = list(table.primary_key.columns)
        rows = session.execute(
            select(table).order_by(*primary_key_columns)
        ).mappings().all()
        payload = [
            {column.name: row[column.name] for column in table.c}
            for row in rows
        ]
        snapshots[table_name] = (
            len(payload),
            sha256(bootstrap._canonical_json(payload)).hexdigest(),
        )
    return snapshots


def _seed_full_authority_fixture(db_session: Session, *, prefix: str) -> dict[str, str]:
    """Seed one meaningful row in every protected authority table.

    The fixture deliberately keeps a published historical base generation
    unpointed; certification must not treat it as the deterministic root or
    mutate any authority row.  Inserts follow the FK/dependency order used by
    the production schema so the same fixture can back reader-parity checks.
    """

    store_id = f"{prefix}-store"
    rule_id = f"{prefix}-rule"
    rule_version_id = f"{prefix}-rule-v1"
    base_generation_id = f"{prefix}-base-generation"
    score_run_id = f"{prefix}-score-run"
    snapshot_id = f"{prefix}-score"
    order_id = f"{prefix}-order"
    coupon_id = f"{prefix}-coupon"
    fee_result_id = f"{prefix}-fee"
    statement_id = f"{prefix}-statement"
    statement_line_id = f"{prefix}-statement-line"
    day = date(2026, 8, 1)
    window_start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 8, 2, tzinfo=timezone.utc)

    db_session.add(
        DimStore(
            store_id=store_id,
            store_name=f"{prefix.title()} Store",
            certified_subject_name=f"{prefix.title()} Subject",
            region="fixture-region",
            is_active=True,
            standard_province="Fixture Province",
            standard_city="Fixture City",
            city_code=f"{prefix}-city",
            longitude=Decimal("120.123456"),
            latitude=Decimal("30.123456"),
            is_douyin_clue_applicable=True,
            participates_in_clue_allocation=True,
            location_source="fixture",
            location_status="verified",
            location_status_note="fixture evidence",
            location_updated_at=window_start,
        )
    )
    db_session.add(
        ClueAllocationRule(
            rule_id=rule_id,
            rule_name=f"{prefix} rule",
            scope_type="global",
            scope_key=f"{prefix}-global",
            created_by="fixture",
        )
    )
    db_session.add(
        ClueAllocationRuleVersion(
            rule_version_id=rule_version_id,
            rule_id=rule_id,
            version_no=1,
            status="published",
            auto_expiry_enabled=True,
            first_follow_up_sla_hours=24,
            protection_days=7,
            conversion_weight=Decimal("0.7000"),
            follow_24h_weight=Decimal("0.3000"),
            lookback_days=30,
            min_samples=1,
            created_by="fixture",
            published_by="fixture",
            published_at=window_start,
        )
    )
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=base_generation_id,
            base_generation_id=None,
            projection_name="settlement",
            state="published",
            input_fingerprint=sha256(f"{prefix}:base".encode()).hexdigest(),
            lineage_depth=0,
            estimated_write_rows=14,
            estimated_write_bytes=1_000_000,
            estimated_wal_bytes=2_000_000,
            estimated_disk_headroom_bytes=10_000_000,
            checkpoint_json={"phase": "fixture", "artifact": None, "cursor": None},
            last_key=None,
            manifest_checksum="b" * 64,
            source_input_json={"fixture": prefix},
            published_at=window_start,
        )
    )
    db_session.commit()

    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id=score_run_id,
            snapshot_date=day,
            run_mode="scheduled",
            scheduled_key=f"{prefix}-scheduled",
            window_start=window_start,
            window_end=window_end,
            candidate_store_count=1,
            snapshot_count=1,
            triggered_by="fixture",
            config_json={"rule_version_id": rule_version_id},
            computed_at=window_end,
        )
    )
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id=snapshot_id,
            snapshot_run_id=score_run_id,
            snapshot_date=day,
            run_mode="scheduled",
            store_id=store_id,
            city_code=f"{prefix}-city",
            window_start=window_start,
            window_end=window_end,
            conversion_numerator=5,
            conversion_denominator=10,
            conversion_rate=Decimal("0.500000"),
            conversion_value_source="fixture",
            follow_24h_numerator=3,
            follow_24h_denominator=10,
            follow_24h_rate=Decimal("0.300000"),
            follow_24h_value_source="fixture",
            conversion_weight=Decimal("0.7000"),
            follow_24h_weight=Decimal("0.3000"),
            store_weight=Decimal("1.0000"),
            composite_score=Decimal("0.440000"),
            config_json={"rule_version_id": rule_version_id},
            computed_at=window_end,
        )
    )
    db_session.commit()

    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id=store_id,
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id=f"{prefix}-monthly-run",
                promotion_net_fee_cent=150,
                management_net_fee_cent=50,
            ),
            AggStoreRanking(
                period_type=1,
                period_key="2026-08",
                month="2026-08",
                store_id=store_id,
                store_name=f"{prefix.title()} Store",
                product_scope="all",
                product_type="all",
                projection_run_id=f"{prefix}-ranking-run",
                promotion_net_fee_cent=150,
                management_net_fee_cent=50,
                net_settlement_reference_cent=100,
            ),
        ]
    )
    db_session.commit()

    db_session.add_all(
        [
            SettlementMonthlyOverlay(
                generation_id=base_generation_id,
                base_generation_id=None,
                month="2026-08",
                store_id=store_id,
                product_scope="all",
                product_type="all",
                partition_key="2026-08",
                statement_status=1,
                projection_run_id=f"{prefix}-monthly-overlay",
                promotion_net_fee_cent=150,
                management_net_fee_cent=50,
                checksum="m" * 64,
            ),
            SettlementRankingOverlay(
                generation_id=base_generation_id,
                base_generation_id=None,
                period_type=1,
                period_key="2026-08",
                store_id=store_id,
                store_name=f"{prefix.title()} Store",
                product_scope="all",
                product_type="all",
                partition_key="monthly:2026-08",
                promotion_net_fee_cent=150,
                management_net_fee_cent=50,
                net_settlement_reference_cent=100,
                projection_run_id=f"{prefix}-ranking-overlay",
                month="2026-08",
                checksum="r" * 64,
            ),
            StoreScoreSnapshotGeneration(
                generation_id=base_generation_id,
                snapshot_run_id=score_run_id,
                store_id=store_id,
                rule_version_id=rule_version_id,
                snapshot_date=day,
                partition_key=bootstrap.canonical_score_partition_key(
                    day, rule_version_id, store_id
                ),
                owner_state="owned",
                checksum="s" * 64,
            ),
        ]
    )
    db_session.commit()

    db_session.add(
        SettlementOrderDetail(
            coupon_id=coupon_id,
            order_id=order_id,
            verify_id=f"{prefix}-verify",
            sku_id=f"{prefix}-sku",
            owner_account_id=f"{prefix}-owner",
            owner_account_name=f"{prefix} owner",
            product_type="all",
            sale_store_id=store_id,
            sale_store_name=f"{prefix.title()} Store",
            sale_time=window_start,
            is_verified=True,
            verify_store_id=store_id,
            verify_store_name=f"{prefix.title()} Store",
            verify_time=window_end,
            relation_type="self_sold",
            is_commissionable=True,
            is_refund_excluded=False,
            paid_amount_cent=100,
            commission_rate=Decimal("0.1000"),
            receivable_commission_cent=10,
            payable_commission_cent=5,
            source_run_id=f"{prefix}-order-run",
            updated_at=window_end,
        )
    )
    db_session.commit()

    db_session.add(
        SettlementFeeResult(
            fee_result_id=fee_result_id,
            coupon_id=coupon_id,
            order_id=order_id,
            fee_direction=1,
            result_version=1,
            original_business_month="2026-08",
            rule_match_date=day,
            sale_store_id=store_id,
            verify_store_id=store_id,
            sku_id=f"{prefix}-sku",
            product_scope="all",
            product_type="all",
            sale_channel_normalized="douyin",
            source_amount_cent=100,
            refunded_amount_cent=0,
            fee_base_cent=100,
            fee_rate=Decimal("0.100000"),
            fee_amount_cent=10,
            rule_version=rule_version_id,
            scope_rule_version=rule_version_id,
            result_status=1,
            calculation_run_id=f"{prefix}-fee-run",
            input_fingerprint=sha256(f"{prefix}:fee".encode()).hexdigest(),
            calculated_at=window_end,
        )
    )
    db_session.commit()

    db_session.add_all(
        [
            SettlementFeeResultCurrent(
                coupon_id=coupon_id,
                fee_direction=1,
                fee_result_id=fee_result_id,
            ),
            SettlementFeeAdjustment(
                adjustment_id=f"{prefix}-adjustment",
                original_fee_result_id=fee_result_id,
                refund_event_id=None,
                coupon_id=coupon_id,
                order_id=order_id,
                fee_direction=1,
                original_business_month="2026-08",
                adjustment_posting_month="2026-08",
                adjustment_type=1,
                adjustment_base_cent=1,
                adjustment_fee_cent=1,
                rule_version=rule_version_id,
                adjustment_reason="fixture adjustment",
                occurred_at=window_end,
                created_by="fixture",
            ),
        ]
    )
    db_session.commit()

    db_session.add(
        SettlementStatement(
            statement_id=statement_id,
            store_id=store_id,
            statement_month="2026-08",
            statement_status=1,
            promotion_original_fee_cent=10,
            promotion_adjustment_fee_cent=2,
            promotion_net_fee_cent=12,
            management_original_fee_cent=8,
            management_adjustment_fee_cent=1,
            management_net_fee_cent=9,
            confirmed_by="fixture",
            lock_version=f"{prefix}-lock",
        )
    )
    db_session.commit()

    db_session.add(
        SettlementStatementLine(
            statement_line_id=statement_line_id,
            statement_id=statement_id,
            fee_direction=1,
            product_scope="all",
            product_type="all",
            original_entry_count=1,
            adjustment_entry_count=0,
            original_base_cent=100,
            adjustment_base_cent=0,
            net_base_cent=100,
            original_fee_cent=10,
            adjustment_fee_cent=0,
            net_fee_cent=10,
        )
    )
    db_session.commit()

    db_session.add(
        SettlementStatementEntry(
            statement_entry_id=f"{prefix}-statement-entry",
            statement_id=statement_id,
            statement_line_id=statement_line_id,
            source_type=1,
            source_record_id=fee_result_id,
            original_fee_result_id=fee_result_id,
            coupon_id=coupon_id,
            order_id=order_id,
            fee_direction=1,
            original_business_month="2026-08",
            statement_posting_month="2026-08",
            product_scope="all",
            product_type="all",
            base_amount_cent=100,
            fee_amount_cent=10,
            rule_version=rule_version_id,
        )
    )
    db_session.commit()
    return {
        "store_id": store_id,
        "rule_version_id": rule_version_id,
        "base_generation_id": base_generation_id,
        "score_run_id": score_run_id,
        "snapshot_id": snapshot_id,
        "coupon_id": coupon_id,
        "fee_result_id": fee_result_id,
        "statement_id": statement_id,
    }


def test_certification_does_not_copy_or_mutate_authority_values_and_counts(
    db_session: Session,
):
    _seed_full_authority_fixture(db_session, prefix="snapshot")
    authority_tables = (
        "agg_store_monthly_settlement",
        "agg_store_ranking",
        "store_score_snapshot_runs",
        "store_score_snapshots",
        "settlement_monthly_overlay",
        "settlement_ranking_overlay",
        "store_score_snapshot_generation",
        "settlement_order_details",
        "settlement_fee_result",
        "settlement_fee_result_current",
        "settlement_fee_adjustment",
        "settlement_statement",
        "settlement_statement_line",
        "settlement_statement_entry",
    )
    with _factory(db_session)() as before_session:
        before = _value_snapshot(before_session, authority_tables)
    assert all(count >= 1 for count, _digest in before.values()), before
    assert all(count == 1 for count, _digest in before.values()), before

    control_tables = {
        "SETTLEMENT_PROJECTION_GENERATION",
        "SETTLEMENT_PROJECTION_PARTITION_MANIFEST",
        "SETTLEMENT_PROJECTION_ACTIVE",
    }
    runtime_dml_targets: list[str] = []
    runtime_dml_parse_errors: list[str] = []
    dml_pattern = re.compile(
        r"^(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([\"`\[]?[A-Z0-9_.]+[\"`\]]?)"
    )
    bind = db_session.get_bind()

    @event.listens_for(bind, "before_cursor_execute")
    def _capture_certification_dml(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ):
        normalized = re.sub(r"\s+", " ", statement.strip()).upper()
        if not re.match(r"^(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", normalized):
            return
        match = dml_pattern.match(normalized)
        if match is None:
            runtime_dml_parse_errors.append(normalized)
            return
        target = match.group(1).strip('"`[]').split(".")[-1]
        runtime_dml_targets.append(target)

    try:
        result = certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=3)
        )
    finally:
        event.remove(bind, "before_cursor_execute", _capture_certification_dml)
    assert result.status == "published"
    assert not runtime_dml_parse_errors, runtime_dml_parse_errors
    assert runtime_dml_targets, "certification emitted no captured control-table DML"
    assert set(runtime_dml_targets) == control_tables, runtime_dml_targets
    with _factory(db_session)() as after_session:
        after = _value_snapshot(after_session, authority_tables)
    assert after == before


def test_static_certification_dml_ast_is_fail_closed_and_control_only():
    """Audit every production DML constructor without broad string matching."""

    source = Path(bootstrap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(bootstrap.__file__))
    expected = {
        "settlement_projection_generation",
        "settlement_projection_compaction_closure",
        "settlement_projection_partition_manifest",
        "settlement_projection_active",
    }
    class_to_table = {
        "SettlementProjectionGeneration": "settlement_projection_generation",
        "SettlementProjectionCompactionClosure": "settlement_projection_compaction_closure",
        "SettlementProjectionPartitionManifest": "settlement_projection_partition_manifest",
        "SettlementProjectionActive": "settlement_projection_active",
    }

    def _name(node: ast.AST | None) -> str | None:
        return node.id if isinstance(node, ast.Name) else None

    def _table_from_expr(node: ast.AST | None, aliases: dict[str, str]) -> str | None:
        if isinstance(node, ast.Name):
            return class_to_table.get(node.id) or aliases.get(node.id)
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "__table__"
            and isinstance(node.value, ast.Name)
        ):
            return class_to_table.get(node.value.id)
        return None

    def _literal_sql(node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = _literal_sql(node.left)
            right = _literal_sql(node.right)
            if left is not None and right is not None:
                return left + right
            return None
        if isinstance(node, ast.JoinedStr):
            values: list[str] = []
            for value in node.values:
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    return None
                values.append(value.value)
            return "".join(values)
        return None

    def _sql_prefix(node: ast.AST | None) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.strip().upper()
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = _sql_prefix(node.left)
            if left:
                return left
            return _sql_prefix(node.right)
        if isinstance(node, ast.JoinedStr):
            prefix: list[str] = []
            for value in node.values:
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    break
                prefix.append(value.value)
            return "".join(prefix).strip().upper()
        return ""

    targets: set[str] = set()
    aliases: dict[str, str] = {}
    dml_pattern = re.compile(
        r"^(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([\"`\[]?[A-Z0-9_.]+[\"`\]]?)"
    )

    class Visitor(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign):  # noqa: N802
            table = _table_from_expr(node.value, aliases)
            if table is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases[target.id] = table
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign):  # noqa: N802
            table = _table_from_expr(node.value, aliases)
            if table is not None and isinstance(node.target, ast.Name):
                aliases[node.target.id] = table
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):  # noqa: N802
            function_name = _name(node.func)
            if function_name is None and isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            if function_name in {"insert", "update", "delete", "dialect_insert"}:
                if not node.args:
                    raise AssertionError(
                        f"DML constructor has no table expression at line {node.lineno}"
                    )
                table = _table_from_expr(node.args[0], aliases)
                if table is None:
                    raise AssertionError(
                        f"unresolvable DML table at line {node.lineno}: "
                        f"{ast.unparse(node.args[0])}"
                    )
                targets.add(table)
            elif function_name == "text" and node.args:
                prefix = _sql_prefix(node.args[0])
                verb = prefix.split(None, 1)[0] if prefix else ""
                if verb in {"INSERT", "UPDATE", "DELETE"}:
                    sql = _literal_sql(node.args[0])
                    if sql is None:
                        raise AssertionError(
                            f"dynamic DML text target at line {node.lineno}"
                        )
                    match = dml_pattern.match(re.sub(r"\s+", " ", sql.strip()).upper())
                    if match is None:
                        raise AssertionError(
                            f"unresolvable DML text target at line {node.lineno}"
                        )
                    targets.add(match.group(1).strip('"`[]').split(".")[-1].lower())
            self.generic_visit(node)

    Visitor().visit(tree)
    assert targets == expected, targets


def test_legacy_reader_parity_before_and_after_certification(db_session: Session):
    _seed_full_authority_fixture(db_session, prefix="reader")

    def canonical_visible(value):
        if isinstance(value, dict):
            return {
                key: canonical_visible(item)
                for key, item in value.items()
                if key != "generated_at"
            }
        if isinstance(value, (list, tuple)):
            return [canonical_visible(item) for item in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return format(value, "f")
        return value

    def aggregate_visible(store: DashboardDataStore):
        return {
            "sale_months": store.list_sale_months(),
            "verify_months": store.list_verify_months(),
            "statement_months": store.list_statement_months(),
            "ranking_report": store.store_ranking_report(
                {
                    "period_type": "MONTHLY",
                    "period_key": "2026-08",
                    "product_scope": "all",
                    "product_type": "all",
                    "page": 1,
                    "page_size": 10,
                }
            ),
            "monthly_report": store.monthly_settlement_report(
                {
                    "store_id": "reader-store",
                    "month": "2026-08",
                    "product_scope": "all",
                    "product_type": "all",
                }
            ),
            "ranking": store.store_ranking(
                month="2026-08", product_type="all", product_scope="all", limit=10
            ),
            "ranking_totals": store.store_ranking_totals(
                month="2026-08", product_type="all", product_scope="all"
            ),
            "monthly_context": store.monthly_settlement_context_exists(
                "reader-store", "2026-08"
            ),
            "monthly": store.monthly_settlement(
                store_id="reader-store",
                month="2026-08",
                product_type="all",
                product_scope="all",
            ),
        }

    score_filters = {
        "snapshot_date": date(2026, 8, 1),
        "page": 1,
        "page_size": 50,
        "_username": "reader-test",
    }

    def authority_visible(store: DashboardDataStore):
        fee_filters = {
            "fee_direction": "PROMOTION",
            "product_scope": "all",
            "product_type": "all",
            "page": 1,
            "page_size": 10,
        }
        return {
            "statement_lines": store._statement_report_lines(
                statement_id=None,
                store_id="reader-store",
                month="2026-08",
                product_scope="all",
                product_type="all",
            ),
            "order_fee_details": store.order_fee_details(fee_filters),
            "order_fee_source": store._order_fee_source_rows(fee_filters),
            "order_details": store.order_details({"page": 1, "page_size": 10}),
            "receivable": store._receivable_rows(
                "reader-store", "2026-08", "all", "all"
            ),
            "payable": store._payable_rows("reader-store", "2026-08", "all", "all"),
            "non_commission": store._non_commission_rows(
                "reader-store", "2026-08", "all", "all"
            ),
        }

    with _factory(db_session)() as before_session:
        before_store = DashboardDataStore(before_session)
        before_visible = {
            "aggregates": aggregate_visible(before_store),
            "monthly_source": before_store._monthly_source_rows(month="2026-08"),
            "ranking_source": before_store._ranking_source_rows(
                period_type=1, period_key="2026-08"
            ),
            "score": list_store_score_snapshots(store=before_store, **score_filters),
            "score_exact_run": list_store_score_snapshots(
                store=before_store,
                snapshot_run_id="reader-score-run",
                **{key: value for key, value in score_filters.items() if key != "snapshot_date"},
            ),
            "authority": authority_visible(before_store),
        }

    result = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=3)
    )
    assert result.status == "published"
    authority_sql: list[str] = []

    @event.listens_for(db_session.get_bind(), "before_cursor_execute")
    def _capture_authority_sql(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ):
        upper = statement.upper()
        if any(
            table in upper
            for table in (
                "SETTLEMENT_STATEMENT",
                "SETTLEMENT_ORDER_DETAILS",
                "SETTLEMENT_FEE_RESULT",
                "SETTLEMENT_FEE_ADJUSTMENT",
            )
        ):
            authority_sql.append(upper)

    with _factory(db_session)() as after_session:
        after_store = DashboardDataStore(after_session)
        after_visible = {
            "aggregates": aggregate_visible(after_store),
            "monthly_source": after_store._monthly_source_rows(month="2026-08"),
            "ranking_source": after_store._ranking_source_rows(
                period_type=1, period_key="2026-08"
            ),
            "score": list_store_score_snapshots(store=after_store, **score_filters),
            "score_exact_run": list_store_score_snapshots(
                store=after_store,
                snapshot_run_id="reader-score-run",
                **{key: value for key, value in score_filters.items() if key != "snapshot_date"},
            ),
            "authority": authority_visible(after_store),
        }

    assert canonical_visible(after_visible) == canonical_visible(before_visible)
    assert authority_sql
    assert all("GENERATION_ID" not in statement for statement in authority_sql)


def test_resource_preflight_drift_add_partition_fails_before_cap_plus_one_manifest(
    db_session: Session, monkeypatch
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="resource-add-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="resource-add-run-a",
        )
    )
    db_session.commit()
    original_preflight = bootstrap._resource_preflight
    injected = {"done": False}

    def add_partition_after_preflight(factory, limits):
        resource = original_preflight(factory, limits)
        if not injected["done"] and isinstance(resource, tuple):
            injected["done"] = True
            with factory() as writer:
                writer.add(
                    AggStoreMonthlySettlement(
                        month="2026-09",
                        store_id="resource-add-store",
                        product_scope="all",
                        product_type="all",
                        statement_status=1,
                        projection_run_id="resource-add-run-b",
                    )
                )
                writer.commit()
        return resource

    monkeypatch.setattr(bootstrap, "_resource_preflight", add_partition_after_preflight)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="resource|partition"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None
        assert generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None
        assert (
            check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest))
            <= 1
        )
        assert (
            generation.estimated_write_rows,
            generation.estimated_write_bytes,
            generation.estimated_wal_bytes,
            generation.estimated_disk_headroom_bytes,
        ) == (
            1,
            20_480,
            40_960,
            1_000_000,
        )

    monkeypatch.setattr(bootstrap, "_resource_preflight", original_preflight)
    retry = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=2)
    )
    assert retry.status == "published"
    assert retry.generation_id == bootstrap._generation_id()
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 1
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 2


def test_resource_preflight_drift_delete_partition_fails_then_cleanup_refreshes(
    db_session: Session, monkeypatch
):
    db_session.add_all(
        [
            AggStoreMonthlySettlement(
                month="2026-08",
                store_id="resource-delete-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="resource-delete-run-a",
            ),
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="resource-delete-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="resource-delete-run-b",
            ),
        ]
    )
    db_session.commit()
    original_preflight = bootstrap._resource_preflight
    injected = {"done": False}

    def delete_partition_after_preflight(factory, limits):
        resource = original_preflight(factory, limits)
        if not injected["done"] and isinstance(resource, tuple):
            injected["done"] = True
            with factory() as writer:
                writer.query(AggStoreMonthlySettlement).filter(
                    AggStoreMonthlySettlement.month == "2026-09"
                ).delete(synchronize_session=False)
                writer.commit()
        return resource

    monkeypatch.setattr(bootstrap, "_resource_preflight", delete_partition_after_preflight)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="resource|partition"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=2)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None

    monkeypatch.setattr(bootstrap, "_resource_preflight", original_preflight)
    retry = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )
    assert retry.status == "published"
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "published"
        assert generation.estimated_write_rows == 1
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 1


def test_resource_preflight_drift_multi_partition_page_guards_before_upsert(
    db_session: Session, monkeypatch
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="resource-page-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="resource-page-run-a",
        )
    )
    db_session.commit()
    original_preflight = bootstrap._resource_preflight
    injected = {"done": False}

    def add_second_partition(factory, limits):
        resource = original_preflight(factory, limits)
        if not injected["done"] and isinstance(resource, tuple):
            injected["done"] = True
            with factory() as writer:
                writer.add(
                    AggStoreMonthlySettlement(
                        month="2026-09",
                        store_id="resource-page-store",
                        product_scope="all",
                        product_type="all",
                        statement_status=1,
                        projection_run_id="resource-page-run-b",
                    )
                )
                writer.commit()
        return resource

    monkeypatch.setattr(bootstrap, "_resource_preflight", add_second_partition)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="resource|partition"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=2, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) <= 1


def test_different_winner_race_cleans_unpublished_loser_after_real_publish(
    db_session: Session, monkeypatch
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="winner-race-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="winner-race-run",
        )
    )
    db_session.commit()
    other_generation_id = "legacy-null-root:other-winner"
    winner_values = {
        "generation_id": other_generation_id,
        "projection_name": "settlement",
        "state": "published",
        "input_fingerprint": "f" * 64,
        "lineage_depth": 0,
        "estimated_write_rows": 77,
        "estimated_write_bytes": 88_888,
        "estimated_wal_bytes": 177_776,
        "estimated_disk_headroom_bytes": 999_999,
        "checkpoint_json": {"winner": "immutable"},
        "manifest_checksum": "a" * 64,
        "source_input_json": {"winner": "immutable"},
    }
    db_session.add(SettlementProjectionGeneration(**winner_values))
    db_session.commit()
    original_finalize = bootstrap._finalize_generation_fenced
    injected = {"done": False}

    def finalize_after_other_winner(factory, generation_id, resource, batch_size, resumed):
        if not injected["done"]:
            injected["done"] = True
            with factory() as writer:
                writer.add(
                    SettlementProjectionActive(
                        projection_name="settlement", generation_id=other_generation_id
                    )
                )
                writer.commit()
        return original_finalize(factory, generation_id, resource, batch_size, resumed)

    monkeypatch.setattr(bootstrap, "_finalize_generation_fenced", finalize_after_other_winner)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="another generation|different generation"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )

    with _factory(db_session)() as check:
        winner = check.get(SettlementProjectionGeneration, other_generation_id)
        assert winner is not None
        assert winner.state == winner_values["state"]
        assert winner.manifest_checksum == winner_values["manifest_checksum"]
        assert winner.checkpoint_json == winner_values["checkpoint_json"]
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert pointer is not None and pointer.generation_id == other_generation_id
        assert check.get(SettlementProjectionGeneration, bootstrap._generation_id()) is None
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 0


def _seed_different_winner_cleanup_pair(
    db_session: Session,
    *,
    loser_id: str,
    loser_state: str = "ready",
    manifest_cap: int = 1,
    with_manifest: bool = True,
) -> tuple[str, str]:
    winner_id = f"{loser_id}:winner"
    db_session.add_all(
        [
            SettlementProjectionGeneration(
                generation_id=winner_id,
                projection_name="settlement",
                state="published",
                input_fingerprint="w" * 64,
                lineage_depth=0,
                estimated_write_rows=3,
                estimated_write_bytes=28_672,
                estimated_wal_bytes=57_344,
                estimated_disk_headroom_bytes=1_000_000,
                checkpoint_json={"winner": winner_id},
                manifest_checksum="c" * 64,
                source_input_json={"winner": winner_id},
            ),
            SettlementProjectionGeneration(
                generation_id=loser_id,
                projection_name="settlement",
                state=loser_state,
                input_fingerprint="l" * 64,
                lineage_depth=0,
                estimated_write_rows=manifest_cap,
                estimated_write_bytes=20_480,
                estimated_wal_bytes=40_960,
                estimated_disk_headroom_bytes=1_000_000,
                checkpoint_json={"loser": loser_id},
                source_input_json={"loser": loser_id},
            ),
            SettlementProjectionActive(
                projection_name="settlement", generation_id=winner_id
            ),
        ]
    )
    if with_manifest:
        db_session.add(
            SettlementProjectionPartitionManifest(
                generation_id=loser_id,
                artifact="monthly",
                partition_key="2026-08",
                owner_state="owned",
                source_kind="legacy_root",
                data_generation_id=None,
                base_generation_id=None,
                row_count=1,
                amount_total_cent=0,
                status_counts_json={"1": 1},
                checksum="d" * 64,
                last_key="loser-last-key",
            )
        )
    db_session.commit()
    return winner_id, loser_id


@pytest.mark.parametrize("loser_state", ["staging", "ready", "failed"])
def test_initial_different_winner_cleans_preexisting_deterministic_loser(
    db_session: Session, loser_state: str
):
    winner_id, loser_id = _seed_different_winner_cleanup_pair(
        db_session,
        loser_id=bootstrap._generation_id(),
        loser_state=loser_state,
    )
    with _factory(db_session)() as before:
        winner = before.get(SettlementProjectionGeneration, winner_id)
        pointer = before.get(SettlementProjectionActive, "settlement")
        assert winner is not None and pointer is not None
        winner_snapshot = tuple(
            getattr(winner, column.name)
            for column in SettlementProjectionGeneration.__table__.columns
        )
        pointer_snapshot = tuple(
            getattr(pointer, column.name)
            for column in SettlementProjectionActive.__table__.columns
        )

    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError,
        match="active pointer identifies a different generation",
    ):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )

    with _factory(db_session)() as after:
        winner = after.get(SettlementProjectionGeneration, winner_id)
        pointer = after.get(SettlementProjectionActive, "settlement")
        assert winner is not None and pointer is not None
        assert tuple(
            getattr(winner, column.name)
            for column in SettlementProjectionGeneration.__table__.columns
        ) == winner_snapshot
        assert tuple(
            getattr(pointer, column.name)
            for column in SettlementProjectionActive.__table__.columns
        ) == pointer_snapshot
        assert after.get(SettlementProjectionGeneration, loser_id) is None
        assert (
            after.scalar(
                select(func.count()).select_from(SettlementProjectionPartitionManifest)
            )
            == 0
        )


def test_same_deterministic_already_published_never_invokes_loser_cleanup(
    db_session: Session, monkeypatch
):
    first = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
    )
    assert first.status == "published"

    def unexpected_cleanup(*_args, **_kwargs):
        raise AssertionError("same deterministic winner must not invoke loser cleanup")

    monkeypatch.setattr(bootstrap, "_cleanup_different_winner_loser", unexpected_cleanup)
    retry = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
    )
    assert retry.status == "already_published"


def test_published_deterministic_loser_is_never_deleted(db_session: Session):
    winner_id, loser_id = _seed_different_winner_cleanup_pair(
        db_session, loser_id="legacy-null-root:published-loser", loser_state="published"
    )
    bootstrap._cleanup_different_winner_loser(_factory(db_session), loser_id)
    with _factory(db_session)() as check:
        assert check.get(SettlementProjectionGeneration, winner_id) is not None
        assert check.get(SettlementProjectionGeneration, loser_id) is not None
        assert check.get(
            SettlementProjectionPartitionManifest,
            (loser_id, "monthly", "2026-08"),
        ) is not None


def test_different_winner_cleanup_cap_failure_is_typed_and_preserves_loser(
    db_session: Session,
):
    _winner_id, loser_id = _seed_different_winner_cleanup_pair(
        db_session,
        loser_id="legacy-null-root:cap-loser",
        loser_state="ready",
        manifest_cap=0,
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="cap"):
        bootstrap._cleanup_different_winner_loser(_factory(db_session), loser_id)
    with _factory(db_session)() as check:
        assert check.get(SettlementProjectionGeneration, loser_id) is not None
        assert check.get(
            SettlementProjectionPartitionManifest,
            (loser_id, "monthly", "2026-08"),
        ) is not None


def test_different_winner_cleanup_commit_crash_rolls_back_and_retry_converges(
    db_session: Session,
):
    _winner_id, loser_id = _seed_different_winner_cleanup_pair(
        db_session, loser_id="legacy-null-root:crash-loser", loser_state="failed"
    )
    state = {"fail": True}

    class FailingCleanupSession(Session):
        def commit(self):  # type: ignore[override]
            if state["fail"]:
                state["fail"] = False
                raise RuntimeError("injected loser cleanup commit crash")
            return super().commit()

    failing_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        future=True,
        class_=FailingCleanupSession,
    )
    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError,
        match="cleanup",
    ):
        bootstrap._cleanup_different_winner_loser(failing_factory, loser_id)
    with _factory(db_session)() as check:
        assert check.get(SettlementProjectionGeneration, loser_id) is not None
        assert check.get(
            SettlementProjectionPartitionManifest,
            (loser_id, "monthly", "2026-08"),
        ) is not None

    bootstrap._cleanup_different_winner_loser(_factory(db_session), loser_id)
    with _factory(db_session)() as check:
        assert check.get(SettlementProjectionGeneration, loser_id) is None
        assert check.get(
            SettlementProjectionPartitionManifest,
            (loser_id, "monthly", "2026-08"),
        ) is None


def test_r2c2_final_coordinator_contract_is_explicitly_fenced():
    helper = getattr(bootstrap, "_finalize_generation_fenced", None)
    assert callable(helper), "final publication must use a fenced coordinator"
    source = inspect.getsource(helper) + inspect.getsource(bootstrap._begin_final_fence)
    assert "BEGIN IMMEDIATE" in source
    lock_order = (
        "agg_store_monthly_settlement",
        "agg_store_ranking",
        "store_score_snapshot_runs",
        "store_score_snapshots",
    )
    positions = [source.index(name) for name in lock_order]
    assert positions == sorted(positions)
    assert "join_transaction_mode" in source
    certify_source = inspect.getsource(bootstrap.certify_legacy_null_root)
    assert "_ensure_null_pointer(" not in certify_source
    assert "_publish(" not in certify_source


def test_r2c2_final_pages_share_coordinator_connection_and_single_commit(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="legacy-fence-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{Path(directory) / 'fence.db'}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as seed:
            seed.add(
                AggStoreMonthlySettlement(
                    month="2026-08",
                    store_id="fence-store",
                    product_scope="all",
                    product_type="all",
                    statement_status=1,
                    projection_run_id="fence-run",
                )
            )
            seed.commit()

        state = {"fenced": False, "fence_id": None, "page_ids": [], "commits": 0, "session_commits": 0}
        original_begin = bootstrap._begin_final_fence

        def begin_and_capture(connection, deadline):
            result = original_begin(connection, deadline)
            state["fenced"] = True
            state["fence_id"] = id(connection.connection.driver_connection)
            return result

        monkeypatch.setattr(bootstrap, "_begin_final_fence", begin_and_capture)

        def capture_page_connection(
            connection, _cursor, statement, _parameters, _context, _executemany
        ):
            if state["fenced"]:
                upper = statement.upper()
                if "SELECT ID," in upper or "SELECT GENERATION_ID, ARTIFACT" in upper:
                    state["page_ids"].append(id(connection.connection.driver_connection))

        def capture_commit(connection):
            if state["fenced"]:
                state["commits"] += 1
                assert id(connection.connection.driver_connection) == state["fence_id"]

        def capture_session_commit(session):
            if state["fenced"]:
                state["session_commits"] += 1

        event.listen(engine, "before_cursor_execute", capture_page_connection)
        event.listen(engine, "commit", capture_commit)
        event.listen(Session, "before_commit", capture_session_commit)
        try:
            result = certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits(rows=1))
        finally:
            event.remove(engine, "before_cursor_execute", capture_page_connection)
            event.remove(engine, "commit", capture_commit)
            event.remove(Session, "before_commit", capture_session_commit)
            engine.dispose()

        assert result.status == "published"
        assert state["page_ids"]
        assert set(state["page_ids"]) == {state["fence_id"]}
        assert state["commits"] == 1
        assert state["session_commits"] == 0


@pytest.mark.parametrize("mutation", ["insert", "update", "delete"])
def test_r2c2_source_mutation_after_final_verify_is_linearized_after_publish(
    monkeypatch, mutation: str
):
    with tempfile.TemporaryDirectory(prefix="legacy-fence-writer-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{Path(directory) / 'fence.db'}",
            connect_args={"check_same_thread": False, "timeout": 0.2},
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as seed:
            seed.add(
                AggStoreMonthlySettlement(
                    month="2026-08",
                    store_id="writer-store",
                    product_scope="all",
                    product_type="all",
                    statement_status=1,
                    projection_run_id="writer-run",
                )
            )
            seed.commit()

        state = {"fence_id": None, "fence_commit_at": None, "writer_commit_at": None, "writer_error": None}
        writer_done = threading.Event()
        original_begin = bootstrap._begin_final_fence

        def begin_and_capture(connection, deadline):
            result = original_begin(connection, deadline)
            state["fence_id"] = id(connection.connection.driver_connection)
            return result

        monkeypatch.setattr(bootstrap, "_begin_final_fence", begin_and_capture)

        def capture_commit(connection):
            if state["fence_id"] == id(connection.connection.driver_connection):
                state["fence_commit_at"] = time.monotonic()

        event.listen(engine, "commit", capture_commit)
        original_verify = bootstrap._verify_artifact
        writer_thread: threading.Thread | None = None

        def verify_then_start_writer(factory_arg, generation_id, artifact, page_size):
            result = original_verify(factory_arg, generation_id, artifact, page_size)
            nonlocal writer_thread
            if artifact == "score" and writer_thread is None:
                def mutate_source():
                    try:
                        with factory() as writer:
                            if mutation == "insert":
                                writer.add(
                                    AggStoreMonthlySettlement(
                                        month="2026-09",
                                        store_id="writer-store",
                                        product_scope="all",
                                        product_type="all",
                                        statement_status=1,
                                        projection_run_id="writer-run-2",
                                    )
                                )
                            else:
                                row = writer.scalar(select(AggStoreMonthlySettlement))
                                assert row is not None
                                if mutation == "update":
                                    row.promotion_net_fee_cent = 999
                                else:
                                    writer.delete(row)
                            writer.commit()
                            state["writer_commit_at"] = time.monotonic()
                    except Exception as exc:  # SQLite may time out while fenced.
                        state["writer_error"] = str(exc)
                    finally:
                        writer_done.set()

                writer_thread = threading.Thread(target=mutate_source, daemon=True)
                writer_thread.start()
            return result

        monkeypatch.setattr(bootstrap, "_verify_artifact", verify_then_start_writer)
        try:
            result = certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits(rows=1))
            assert result.status == "published"
            assert writer_done.wait(3), "writer did not finish after publication"
            if writer_thread is not None:
                writer_thread.join(timeout=1)
            assert state["fence_commit_at"] is not None
            if state["writer_commit_at"] is not None:
                assert state["writer_commit_at"] >= state["fence_commit_at"]
            else:
                assert state["writer_error"]
                assert any(
                    marker in state["writer_error"].lower()
                    for marker in ("locked", "timeout", "busy")
                )
        finally:
            event.remove(engine, "commit", capture_commit)
            engine.dispose()


def test_r2c2_external_writer_lock_is_transient_and_retryable(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="legacy-fence-lock-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{Path(directory) / 'fence.db'}",
            connect_args={"check_same_thread": False, "timeout": 0.2},
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as seed:
            seed.add(
                AggStoreMonthlySettlement(
                    month="2026-08",
                    store_id="deadline-store",
                    product_scope="all",
                    product_type="all",
                    statement_status=1,
                    projection_run_id="deadline-run",
                )
            )
            seed.commit()

        lock_holder = {"connection": None}
        original_promote = bootstrap._promote_staging_to_ready

        def promote_then_lock(factory_arg, generation_id):
            generation = original_promote(factory_arg, generation_id)
            if lock_holder["connection"] is None:
                lock_holder["connection"] = engine.connect()
                lock_holder["connection"].exec_driver_sql("BEGIN IMMEDIATE")
            return generation

        monkeypatch.setattr(bootstrap, "_promote_staging_to_ready", promote_then_lock)
        monkeypatch.setattr(bootstrap, "_FINAL_FENCE_DEADLINE_SECONDS", 0.05)
        try:
            with pytest.raises(
                bootstrap.LegacyProjectionBootstrapError,
                match="fence|deadline|timeout|locked",
            ):
                certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits(rows=1))
            with factory() as check:
                generation = check.scalar(select(SettlementProjectionGeneration))
                pointer = check.get(SettlementProjectionActive, "settlement")
                assert generation is not None
                assert generation.state in {"staging", "ready"}
                assert generation.state not in {"failed", "published"}
                assert pointer is None or pointer.generation_id is None
        finally:
            if lock_holder["connection"] is not None:
                lock_holder["connection"].rollback()
                lock_holder["connection"].close()

        retry = certify_legacy_null_root(
            factory, batch_size=1, resource_limits=_limits(rows=1)
        )
        assert retry.status == "published"
        engine.dispose()


def test_r2c2_deadline_expiry_between_pages_preserves_retryable_generation(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="legacy-fence-pages-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{Path(directory) / 'fence.db'}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as seed:
            seed.add(
                AggStoreMonthlySettlement(
                    month="2026-08",
                    store_id="page-deadline-store",
                    product_scope="all",
                    product_type="all",
                    statement_status=1,
                    projection_run_id="page-deadline-run",
                )
            )
            seed.commit()

        state = {"expire": False}
        original_remaining = bootstrap._fence_remaining
        original_verify = bootstrap._verify_artifact

        def expire_after_monthly(factory_arg, generation_id, artifact, page_size):
            result = original_verify(factory_arg, generation_id, artifact, page_size)
            if artifact == "monthly":
                state["expire"] = True
            return result

        def expire_between_pages(deadline):
            if state["expire"]:
                raise bootstrap._FenceTransientError("fence deadline expired between pages")
            return original_remaining(deadline)

        monkeypatch.setattr(bootstrap, "_verify_artifact", expire_after_monthly)
        monkeypatch.setattr(bootstrap, "_fence_remaining", expire_between_pages)
        with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="deadline|fence"):
            certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits(rows=1))
        with factory() as check:
            generation = check.scalar(select(SettlementProjectionGeneration))
            pointer = check.get(SettlementProjectionActive, "settlement")
            assert generation is not None
            assert generation.state in {"staging", "ready"}
            assert generation.state not in {"failed", "published"}
            assert pointer is None or pointer.generation_id is None

        monkeypatch.setattr(bootstrap, "_fence_remaining", original_remaining)
        monkeypatch.setattr(bootstrap, "_verify_artifact", original_verify)
        retry = certify_legacy_null_root(
            factory, batch_size=1, resource_limits=_limits(rows=1)
        )
        assert retry.status == "published"
        engine.dispose()


def test_r2c2_real_pointer_cas_fault_rolls_back_outer_transaction(db_session: Session):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="cas-fault-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="cas-fault-run",
        )
    )
    db_session.commit()
    state = {"failed": False}
    bind = db_session.get_bind()

    def fail_after_real_cas(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        if (
            not state["failed"]
            and "UPDATE SETTLEMENT_PROJECTION_ACTIVE SET GENERATION_ID" in statement.upper()
        ):
            state["failed"] = True
            raise RuntimeError("injected final pointer CAS crash before commit")

    event.listen(bind, "after_cursor_execute", fail_after_real_cas)
    try:
        with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="certification failed|CAS"):
            certify_legacy_null_root(
                _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
            )
    finally:
        event.remove(bind, "after_cursor_execute", fail_after_real_cas)
    assert state["failed"] is True
    with _factory(db_session)() as check:
        generation = check.scalar(select(SettlementProjectionGeneration))
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert generation is not None
        assert generation.state in {"staging", "ready"}
        assert generation.state not in {"failed", "published"}
        assert pointer is None or pointer.generation_id is None

    retry = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )
    assert retry.status == "published"


def test_r2c2_same_root_advisory_lock_wraps_pointer_and_preflight(
    monkeypatch, db_session: Session
):
    """A same-root contender must serialize before reading peer progress.

    The production PG gate exercises the real two-backend interleaving.  This
    unit seam is deliberately narrower: it proves that the lock lifecycle
    encloses the first pointer read (and therefore all preflight/scan work),
    so a peer-advanced checkpoint is adopted only after the winner releases
    the session-level lock.
    """

    events: list[tuple[str, str | None]] = []
    generation_id = bootstrap._generation_id()

    class StopAfterPointer(RuntimeError):
        pass

    class FakeLock:
        def __init__(self):
            self.session_factory = _factory(db_session)

        def release(self):
            events.append(("release", None))

    def acquire(_factory, requested_generation_id):
        events.append(("acquire", requested_generation_id))
        return FakeLock()

    def read_pointer(_factory):
        events.append(("pointer", None))
        raise StopAfterPointer("stop after pointer probe")

    monkeypatch.setattr(
        bootstrap, "_acquire_generation_advisory_lock", acquire, raising=False
    )
    monkeypatch.setattr(bootstrap, "_read_active_pointer", read_pointer)

    with pytest.raises(StopAfterPointer, match="stop after pointer probe"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )

    assert events == [
        ("acquire", generation_id),
        ("pointer", None),
        ("release", None),
    ]


def test_r2c2_advisory_probe_releases_false_connection_and_binds_winner(
    monkeypatch,
):
    class Result:
        def __init__(self, value):
            self.value = value

        def scalar(self):
            return self.value

    class FakeDialect:
        name = "postgresql"

    class Connection:
        dialect = FakeDialect()

        def __init__(self, responses):
            self.responses = list(responses)
            self.sql: list[str] = []
            self.commits = 0
            self.rollbacks = 0
            self.closes = 0

        def exec_driver_sql(self, statement, parameters=None):
            self.sql.append(statement)
            if "pg_try_advisory_lock" in statement:
                return Result(self.responses.pop(0))
            if "pg_advisory_unlock" in statement:
                return Result(True)
            raise AssertionError(statement)

        def execute(self, statement, parameters=None):
            return self.exec_driver_sql(getattr(statement, "text", str(statement)), parameters)

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            self.closes += 1

    first = Connection([False])
    second = Connection([True])
    probes = iter([(first, True), (second, True)])
    monkeypatch.setattr(bootstrap, "_fence_connection", lambda _factory: next(probes))
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _seconds: None)

    lock = bootstrap._acquire_generation_advisory_lock(
        lambda: None, bootstrap._generation_id()
    )
    assert first.closes == 1
    assert lock.connection is second
    assert lock.session_factory.kw["bind"] is second
    assert first.commits == 1
    assert second.commits == 1
    lock.release()
    assert any("pg_advisory_unlock" in statement for statement in second.sql)
    assert second.closes == 1


def test_r2c2_advisory_timeout_has_no_generation_or_pointer_write(
    monkeypatch, db_session: Session
):
    def timeout(*_args, **_kwargs):
        raise bootstrap._FenceTransientError("generation advisory lock timeout")

    monkeypatch.setattr(bootstrap, "_acquire_generation_advisory_lock", timeout)
    with pytest.raises(bootstrap._FenceTransientError, match="advisory lock"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0
        assert check.scalar(select(func.count()).select_from(SettlementProjectionActive)) == 0


def test_r2c2_advisory_unlock_failure_still_closes_connection(monkeypatch):
    class Result:
        def scalar(self):
            return True

    class Dialect:
        name = "postgresql"

    class Connection:
        dialect = Dialect()

        def __init__(self):
            self.closes = 0
            self.rollbacks = 0

        def exec_driver_sql(self, statement, _parameters=None):
            if "pg_try_advisory_lock" in statement:
                return Result()
            raise RuntimeError("injected advisory unlock failure")

        def execute(self, statement, _parameters=None):
            return self.exec_driver_sql(getattr(statement, "text", str(statement)), _parameters)

        def commit(self):
            pass

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            self.closes += 1

    connection = Connection()
    monkeypatch.setattr(
        bootstrap,
        "_fence_connection",
        lambda _factory: (connection, True),
    )
    lock = bootstrap._acquire_generation_advisory_lock(
        lambda: None, bootstrap._generation_id()
    )
    lock.release()
    assert connection.rollbacks == 1
    assert connection.closes == 1


def test_r3_source_drift_message_is_not_misclassified_as_different_winner(
    db_session: Session, monkeypatch
):
    marker_store = "timeout-deadline-another-generation-compare-and-swap-lost"
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id=marker_store,
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="r3-drift-run",
        )
    )
    db_session.commit()
    cleanup_calls: list[str] = []

    def cleanup_spy(*_args, **_kwargs):
        cleanup_calls.append("called")

    def drift_after_scan(factory, generation_id, resource, batch_size, resumed):
        with factory() as writer:
            writer.execute(
                update(AggStoreMonthlySettlement)
                .where(AggStoreMonthlySettlement.store_id == marker_store)
                .values(promotion_net_fee_cent=999)
            )
            writer.commit()
        raise bootstrap.LegacyProjectionBootstrapError(
            "source drift timeout deadline another generation compare-and-swap lost"
        )

    monkeypatch.setattr(bootstrap, "_finalize_generation_fenced", drift_after_scan)
    monkeypatch.setattr(bootstrap, "_cleanup_different_winner_loser", cleanup_spy)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="source drift"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    assert cleanup_calls == []
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None


def test_r3_different_winner_entry_uses_dedicated_conflict_type(db_session: Session):
    other_id = "legacy-null-root:r3-other-winner"
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=other_id,
            projection_name="settlement",
            state="published",
            input_fingerprint="f" * 64,
            lineage_depth=0,
            estimated_write_rows=0,
            estimated_write_bytes=16_384,
            estimated_wal_bytes=32_768,
            estimated_disk_headroom_bytes=1_000_000,
            checkpoint_json={"protocol": "other", "operation": "other"},
            source_input_json={},
        )
    )
    db_session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id=other_id
        )
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError) as caught:
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits()
        )
    assert caught.value.__class__.__name__ == "_DifferentWinnerConflict"


@pytest.mark.parametrize(
    ("artifact", "field", "value"),
    [
        ("monthly", "statement_status", True),
        ("monthly", "statement_status", 1.5),
        ("monthly", "statement_status", "1"),
        ("ranking", "period_type", True),
        ("ranking", "period_type", 1.5),
        ("ranking", "period_type", "1"),
    ],
)
def test_r3_source_identity_types_fail_before_generation_write(
    db_session: Session, monkeypatch, artifact: str, field: str, value: object
):
    if artifact == "monthly":
        raw = {
            "id": 1,
            "month": "2026-08",
            "store_id": "r3-strict-monthly-store",
            "product_scope": "all",
            "product_type": "all",
            "projection_run_id": "r3-strict-monthly-run",
            "statement_status": value,
        }
    else:
        raw = {
            "id": 1,
            "period_type": value,
            "period_key": "2026-08",
            "month": "2026-08",
            "store_id": "r3-strict-ranking-store",
            "product_scope": "all",
            "product_type": "all",
            "projection_run_id": "r3-strict-ranking-run",
        }
    calls: dict[tuple[str, bool], int] = {}

    def source_page(_session, requested_artifact, _batch_size, cursor):
        key = (requested_artifact, cursor is None)
        calls[key] = calls.get(key, 0) + 1
        if requested_artifact == artifact and cursor is None:
            return [raw]
        return []

    monkeypatch.setattr(bootstrap, "_select_source_page", source_page)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0
        assert check.scalar(select(func.count()).select_from(SettlementProjectionActive)) == 0


def test_r3_preflight_validates_mapped_values_before_generation_write(
    db_session: Session, monkeypatch
):
    raw = {
        "snapshot_id": "r3-score-snapshot",
        "snapshot_run_id": "r3-score-run",
        "store_id": "r3-score-store",
        "snapshot_date": date(2026, 8, 1),
        "run_snapshot_date": date(2026, 8, 1),
        "rule_version_id": "r3-rule",
        "config_json": "{malformed",
    }

    def source_page(_session, artifact, _batch_size, cursor):
        if artifact == "score" and cursor is None:
            return [raw]
        return []

    monkeypatch.setattr(bootstrap, "_select_source_page", source_page)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="JSON"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionGeneration)) == 0


@pytest.mark.parametrize(
    "source_input",
    [
        {},
        {**bootstrap._PROTOCOL_ENVELOPE, "extra": "r3"},
        {**bootstrap._PROTOCOL_ENVELOPE, "artifacts": ["monthly"]},
    ],
)
def test_r3_source_input_envelope_must_match_exactly(
    db_session: Session, source_input: dict[str, object]
):
    resource = (0, 16_384, 32_768, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="scan",
                artifact="monthly",
                cursor=None,
                stats=bootstrap._ScanStats(),
                resource=resource,
            ),
            source_input_json=source_input,
        )
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="source|input|envelope"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None


@pytest.mark.parametrize(
    ("state", "phase"),
    [("ready", "scan"), ("staging", "verify"), ("staging", "cleanup")],
)
def test_r3_checkpoint_state_phase_pair_is_strict(
    db_session: Session, state: str, phase: str
):
    resource = (0, 16_384, 32_768, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state=state,
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase=phase,
                artifact=None,
                cursor=None,
                stats=bootstrap._ScanStats(),
                resource=resource,
            ),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="phase"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"


def test_r3_published_root_batch_and_last_key_tamper_is_fatal_without_write(
    db_session: Session
):
    resource = (0, 16_384, 32_768, 1_000_000)
    checkpoint = bootstrap._checkpoint(
        phase="publish",
        artifact=None,
        cursor=None,
        stats=bootstrap._ScanStats(batch_count=999),
        resource=resource,
    )
    checkpoint["batch_size"] = 1
    generation_id = bootstrap._generation_id()
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="published",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=checkpoint,
            last_key="bogus-terminal-last-key",
            manifest_checksum=bootstrap._empty_manifest_checksum(),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.add(
        SettlementProjectionActive(projection_name="settlement", generation_id=generation_id)
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="published|checkpoint|last_key|batch"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, generation_id)
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert generation is not None and generation.state == "published"
        assert pointer is not None and pointer.generation_id == generation_id


@pytest.mark.parametrize("tamper", ["batch_count", "last_key"])
def test_r3_ready_valid_manifest_terminal_metadata_tamper_is_fatal(
    db_session: Session, monkeypatch, tamper: str
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id=f"r3-ready-{tamper}-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id=f"r3-ready-{tamper}-run",
        )
    )
    db_session.commit()
    original_finalize = bootstrap._finalize_generation_fenced

    def tamper_ready(factory, generation_id, resource, batch_size, resumed):
        with factory() as writer:
            generation = writer.get(SettlementProjectionGeneration, generation_id)
            assert generation is not None
            checkpoint = dict(generation.checkpoint_json)
            if tamper == "batch_count":
                checkpoint["batch_count"] = 999
            else:
                generation.last_key = "bogus-terminal-last-key"
            writer.execute(
                update(SettlementProjectionGeneration)
                .where(SettlementProjectionGeneration.generation_id == generation_id)
                .values(checkpoint_json=checkpoint, last_key=generation.last_key)
            )
            writer.commit()
        return original_finalize(factory, generation_id, resource, batch_size, resumed)

    monkeypatch.setattr(bootstrap, "_finalize_generation_fenced", tamper_ready)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="terminal|checkpoint|batch|last_key"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None


@pytest.mark.parametrize("tamper", ["batch_count", "last_key"])
def test_r3_published_already_path_rejects_each_terminal_tamper(
    db_session: Session, tamper: str
):
    resource = (0, 16_384, 32_768, 1_000_000)
    checkpoint = bootstrap._checkpoint(
        phase="publish",
        artifact=None,
        cursor=None,
        stats=bootstrap._ScanStats(),
        resource=resource,
        batch_size=1,
    )
    generation_id = bootstrap._generation_id()
    last_key = None
    if tamper == "batch_count":
        checkpoint["batch_count"] = 999
    else:
        last_key = "bogus-terminal-last-key"
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="published",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=checkpoint,
            last_key=last_key,
            manifest_checksum=bootstrap._empty_manifest_checksum(),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.add(
        SettlementProjectionActive(projection_name="settlement", generation_id=generation_id)
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="published|checkpoint|batch|last_key"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
        )


def _r3_published_manifest(
    artifact: str, partition_key: str, cursor: dict[str, object]
) -> dict[str, object]:
    return {
        "generation_id": bootstrap._generation_id(),
        "artifact": artifact,
        "partition_key": partition_key,
        "owner_state": "owned",
        "source_kind": "legacy_root",
        "data_generation_id": None,
        "base_generation_id": None,
        "row_count": 1,
        "amount_total_cent": 0,
        "status_counts_json": {"1": 1} if artifact == "monthly" else {},
        "checksum": "a" * 64,
        "last_key": bootstrap._cursor_token(artifact, cursor),
    }


def test_r3_published_terminal_derivation_orders_each_artifact_cursor(
    db_session: Session, monkeypatch
):
    manifests = [
        _r3_published_manifest(
            "monthly",
            "2026-08",
            {
                "month": "2026-08",
                "store_id": "r3-terminal-store",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": "r3-terminal-run",
                "id": 1,
            },
        ),
        # ``cumulative`` sorts before ``monthly`` as a partition string, but
        # period_type=2 is the terminal ranking cursor.
        _r3_published_manifest(
            "ranking",
            "cumulative:2026-08",
            {
                "period_type": 2,
                "period_key": "2026-08",
                "store_id": "r3-terminal-store",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": "r3-terminal-run",
                "id": 2,
            },
        ),
        _r3_published_manifest(
            "ranking",
            "monthly:2026-08",
            {
                "period_type": 1,
                "period_key": "2026-08",
                "store_id": "r3-terminal-store",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": "r3-terminal-run",
                "id": 1,
            },
        ),
        _r3_published_manifest(
            "score",
            "2026-08-01|4:rule|5:store",
            {
                "snapshot_date": "2026-08-01",
                "rule_version_id": "rule",
                "store_id": "store",
                "snapshot_run_id": "run",
                "snapshot_id": "snapshot",
            },
        ),
    ]
    assert bootstrap._published_artifact_terminal_last_key("ranking", manifests[1:3]) == manifests[1]["last_key"]
    assert bootstrap._published_artifact_terminal_last_key("monthly", manifests[:1]) == manifests[0]["last_key"]
    assert bootstrap._published_artifact_terminal_last_key("score", manifests[3:]) == manifests[3]["last_key"]
    resource = (4, 32_768, 65_536, 1_000_000)
    checksum = bootstrap._manifest_checksum(manifests)
    checkpoint = bootstrap._checkpoint(
        phase="publish",
        artifact=None,
        cursor=None,
        stats=bootstrap._ScanStats(
            batch_count=4, partition_count=4, source_row_count=4
        ),
        resource=resource,
        batch_size=1,
    )
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="published",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=checkpoint,
        last_key=manifests[3]["last_key"],
        manifest_checksum=checksum,
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    monkeypatch.setattr(
        bootstrap,
        "_fetch_all_generation_manifests",
        lambda _factory, _generation_id, artifact, **_kwargs: [
            row for row in manifests if row["artifact"] == artifact
        ],
    )
    bootstrap._validate_published_root(_factory(db_session), generation)


@pytest.mark.parametrize("tamper", ["rows", "bytes", "wal"])
def test_r3_published_resource_facts_are_recomputed_from_manifests(
    db_session: Session, monkeypatch, tamper: str
):
    manifest = _r3_published_manifest(
        "monthly",
        "2026-08",
        {
            "month": "2026-08",
            "store_id": "r3-resource-store",
            "product_scope": "all",
            "product_type": "all",
            "projection_run_id": "r3-resource-run",
            "id": 1,
        },
    )
    expected_resource = (1, 20_480, 40_960, 1_000_000)
    resource = list(expected_resource)
    resource_index = {"rows": 0, "bytes": 1, "wal": 2}[tamper]
    resource[resource_index] -= 1
    resource = tuple(resource)
    checkpoint = bootstrap._checkpoint(
        phase="publish",
        artifact=None,
        cursor=None,
        stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
        resource=resource,
        batch_size=1,
    )
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="published",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=checkpoint,
        last_key=manifest["last_key"],
        manifest_checksum=bootstrap._manifest_checksum([manifest]),
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    monkeypatch.setattr(
        bootstrap,
        "_fetch_all_generation_manifests",
        lambda *_args, **_kwargs: [manifest] if _args[2] == "monthly" else [],
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="resource|manifest"):
        bootstrap._validate_published_root(_factory(db_session), generation)


@pytest.mark.parametrize(
    ("artifact", "cursor"),
    [
        ("monthly", {"month": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": 0.5}),
        ("monthly", {"month": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": "1"}),
        ("monthly", {"month": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": True}),
        ("ranking", {"period_type": 1.5, "period_key": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": 1}),
        ("ranking", {"period_type": "1", "period_key": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": 1}),
        ("ranking", {"period_type": True, "period_key": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": 1}),
        ("ranking", {"period_type": 1, "period_key": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": 0.5}),
        ("ranking", {"period_type": 1, "period_key": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": "1"}),
        ("ranking", {"period_type": 1, "period_key": "2026-08", "store_id": "s", "product_scope": "all", "product_type": "all", "projection_run_id": "r", "id": True}),
    ],
)
def test_r3_checkpoint_cursor_types_are_strict(artifact: str, cursor: dict[str, object]):
    resource = (0, 16_384, 32_768, 1_000_000)
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=bootstrap._checkpoint(
            phase="scan",
            artifact=artifact,
            cursor=cursor,
            stats=bootstrap._ScanStats(),
            resource=resource,
        ),
        last_key=bootstrap._cursor_token(artifact, cursor),
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="cursor|period_type|id"):
        bootstrap._validate_checkpoint(generation, resource)


def test_r3_begin_pg_fence_sets_read_committed_before_share_locks():
    class Dialect:
        name = "postgresql"

    class Connection:
        dialect = Dialect()

        def __init__(self):
            self.statements: list[str] = []

        def exec_driver_sql(self, statement, *_args):
            self.statements.append(statement)

    connection = Connection()
    dialect = bootstrap._begin_final_fence(connection, time.monotonic() + 5)
    assert dialect == "postgresql"
    assert connection.statements[0] == "BEGIN"
    assert connection.statements[1] == "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
    first_lock = next(index for index, item in enumerate(connection.statements) if item.startswith("LOCK TABLE"))
    assert connection.statements[first_lock - 2].startswith("SET LOCAL lock_timeout")
    assert connection.statements[first_lock - 1].startswith("SET LOCAL statement_timeout")


def test_r3_fence_timeout_refresh_helper_is_explicit_and_bounded(monkeypatch):
    class Dialect:
        name = "postgresql"

    class Connection:
        dialect = Dialect()

        def __init__(self):
            self.statements: list[str] = []

        def exec_driver_sql(self, statement, *_args):
            self.statements.append(statement)

    remaining_values = iter([4.9, 4.8, 4.7, 4.6])
    observed_remaining: list[float] = []

    def remaining(_deadline):
        value = next(remaining_values)
        observed_remaining.append(value)
        return value

    monkeypatch.setattr(bootstrap, "_fence_remaining", remaining)
    connection = Connection()
    timeout = bootstrap._refresh_fence_timeouts(connection, 1.0, "postgresql")
    assert timeout <= int(observed_remaining[0] * 1000)
    assert connection.statements[0].startswith("SET LOCAL lock_timeout")
    assert connection.statements[1].startswith("SET LOCAL statement_timeout")
    lock_ms = int(re.search(r"'(\d+)ms'", connection.statements[0]).group(1))
    statement_ms = int(re.search(r"'(\d+)ms'", connection.statements[1]).group(1))
    assert lock_ms <= int(observed_remaining[0] * 1000)
    assert statement_ms <= int(observed_remaining[1] * 1000)


def test_r3_coordinator_refreshes_timeouts_before_each_final_dml(
    db_session: Session, monkeypatch
):
    calls: list[str] = []
    original_refresh = bootstrap._refresh_fence_timeouts

    def traced_refresh(connection, deadline, dialect_name=None):
        calls.append(str(dialect_name))
        return original_refresh(connection, deadline, dialect_name)

    monkeypatch.setattr(bootstrap, "_refresh_fence_timeouts", traced_refresh)
    result = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
    )
    assert result.status == "published"
    assert len(calls) >= 7


def _r5_control_snapshot(session: Session) -> tuple[object, object, object]:
    generation = session.get(SettlementProjectionGeneration, bootstrap._generation_id())
    pointer = session.get(SettlementProjectionActive, "settlement")
    manifests = session.execute(
        select(SettlementProjectionPartitionManifest)
        .order_by(
            SettlementProjectionPartitionManifest.artifact,
            SettlementProjectionPartitionManifest.partition_key,
        )
    ).scalars().all()
    generation_snapshot = None
    if generation is not None:
        generation_snapshot = (
            generation.state,
            generation.checkpoint_json,
            generation.last_key,
            generation.manifest_checksum,
            generation.estimated_write_rows,
            generation.estimated_write_bytes,
            generation.estimated_wal_bytes,
            generation.estimated_disk_headroom_bytes,
        )
    pointer_snapshot = None if pointer is None else pointer.generation_id
    manifest_snapshot = [
        (
            row.artifact,
            row.partition_key,
            row.owner_state,
            row.source_kind,
            row.data_generation_id,
            row.base_generation_id,
            row.row_count,
            row.amount_total_cent,
            row.status_counts_json,
            row.checksum,
            row.last_key,
        )
        for row in manifests
    ]
    return generation_snapshot, pointer_snapshot, manifest_snapshot


def test_r10_mark_failed_preserves_published_winner_snapshot(db_session: Session):
    factory = _factory(db_session)
    result = certify_legacy_null_root(factory, batch_size=1, resource_limits=_limits(rows=0))
    assert result.status == "published"
    with factory() as before:
        snapshot_before = _r5_control_snapshot(before)

    bootstrap._mark_failed(factory, result.generation_id, "stale", "stale error")

    with factory() as after:
        # RED: the pre-fix update ignores current state and mutates this winner.
        assert _r5_control_snapshot(after) == snapshot_before


@pytest.mark.parametrize("state", ["staging", "ready"])
def test_r10_mark_failed_still_marks_recoverable_generation(
    db_session: Session, state: str
):
    factory = _factory(db_session)
    resource = (0, 16_384, 32_768, 1_000_000)
    phase = "staging" if state == "staging" else "verify"
    generation_id = bootstrap._generation_id()
    with factory() as seed:
        seed.add(
            SettlementProjectionGeneration(
                generation_id=generation_id,
                projection_name="settlement",
                state=state,
                input_fingerprint=bootstrap._input_fingerprint(),
                lineage_depth=0,
                estimated_write_rows=resource[0],
                estimated_write_bytes=resource[1],
                estimated_wal_bytes=resource[2],
                estimated_disk_headroom_bytes=resource[3],
                checkpoint_json=bootstrap._checkpoint(
                    phase=phase,
                    artifact="monthly" if state == "staging" else None,
                    cursor=None,
                    stats=bootstrap._ScanStats(),
                    resource=resource,
                    batch_size=1,
                ),
                source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
            )
        )
        seed.commit()

    bootstrap._mark_failed(factory, generation_id, "stale", "stale error")
    with factory() as check:
        generation = check.get(SettlementProjectionGeneration, generation_id)
        assert generation is not None
        assert generation.state == "failed"
        assert generation.failure_code == "stale"


def test_r10_stale_mark_failed_cannot_clobber_peer_published_winner():
    with tempfile.TemporaryDirectory(prefix="r10-winner-cas-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{directory}/winner.sqlite",
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        resource = (0, 16_384, 32_768, 1_000_000)
        generation_id = bootstrap._generation_id()
        with factory() as seed:
            seed.add(
                SettlementProjectionGeneration(
                    generation_id=generation_id,
                    projection_name="settlement",
                    state="staging",
                    input_fingerprint=bootstrap._input_fingerprint(),
                    lineage_depth=0,
                    estimated_write_rows=resource[0],
                    estimated_write_bytes=resource[1],
                    estimated_wal_bytes=resource[2],
                    estimated_disk_headroom_bytes=resource[3],
                    checkpoint_json=bootstrap._checkpoint(
                        phase="staging",
                        artifact="monthly",
                        cursor=None,
                        stats=bootstrap._ScanStats(),
                        resource=resource,
                        batch_size=1,
                    ),
                    source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
                )
            )
            seed.commit()

        barrier = threading.Barrier(2)
        published = threading.Event()

        def stale_failure():
            with factory() as stale:
                observed = stale.get(SettlementProjectionGeneration, generation_id)
                assert observed is not None and observed.state == "staging"
            barrier.wait(timeout=10)
            assert published.wait(timeout=10)
            bootstrap._mark_failed(factory, generation_id, "stale", "stale error")

        def peer_publish():
            barrier.wait(timeout=10)
            with factory() as winner:
                winner.execute(
                    update(SettlementProjectionGeneration)
                    .where(
                        SettlementProjectionGeneration.generation_id == generation_id,
                        SettlementProjectionGeneration.state == "staging",
                    )
                    .values(state="published")
                )
                winner.add(
                    SettlementProjectionActive(
                        projection_name="settlement", generation_id=generation_id
                    )
                )
                winner.commit()
            published.set()

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                list(executor.map(lambda fn: fn(), (stale_failure, peer_publish)))
            with factory() as check:
                generation = check.get(SettlementProjectionGeneration, generation_id)
                pointer = check.get(SettlementProjectionActive, "settlement")
                assert generation is not None and generation.state == "published"
                assert pointer is not None and pointer.generation_id == generation_id
        finally:
            engine.dispose()


def _r11_seed_failed_cleanup(
    factory: sessionmaker,
    resource: tuple[int, int, int, int],
    manifests: list[tuple[str, str]],
) -> str:
    generation_id = bootstrap._generation_id()
    with factory() as seed:
        seed.add(
            SettlementProjectionGeneration(
                generation_id=generation_id,
                projection_name="settlement",
                state="failed",
                input_fingerprint=bootstrap._input_fingerprint(),
                lineage_depth=0,
                estimated_write_rows=resource[0],
                estimated_write_bytes=resource[1],
                estimated_wal_bytes=resource[2],
                estimated_disk_headroom_bytes=resource[3],
                checkpoint_json=bootstrap._checkpoint(
                    phase="staging",
                    artifact="monthly",
                    cursor=None,
                    stats=bootstrap._ScanStats(),
                    resource=resource,
                    batch_size=1,
                ),
                source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
                failure_code="injected",
                failure_reason="injected",
            )
        )
        for artifact, partition_key in manifests:
            seed.add(
                SettlementProjectionPartitionManifest(
                    generation_id=generation_id,
                    artifact=artifact,
                    partition_key=partition_key,
                    owner_state="owned",
                    source_kind="legacy_root",
                    data_generation_id=None,
                    base_generation_id=None,
                    row_count=1,
                    amount_total_cent=0,
                    status_counts_json={"1": 1} if artifact == "monthly" else {},
                    checksum="a" * 64,
                    last_key=None,
                )
            )
        seed.commit()
    return generation_id


def test_r11_cleanup_no_page_cannot_reset_peer_published_generation():
    with tempfile.TemporaryDirectory(prefix="r11-cleanup-empty-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{directory}/cleanup.sqlite",
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        resource = (0, 16_384, 32_768, 1_000_000)
        generation_id = _r11_seed_failed_cleanup(factory, resource, [])
        paused = threading.Event()
        release = threading.Event()
        armed = {"value": True}

        def pause_after_no_page_select(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ):
            upper = statement.upper().replace("\n", " ")
            if armed["value"] and upper.strip().startswith(
                "SELECT ARTIFACT, PARTITION_KEY"
            ):
                armed["value"] = False
                paused.set()
                assert release.wait(timeout=15)

        event.listen(engine, "before_cursor_execute", pause_after_no_page_select)
        try:
            with factory() as stale:
                stale_generation = stale.get(SettlementProjectionGeneration, generation_id)

            def stale_cleanup():
                return bootstrap._cleanup_failed_generation(
                    factory, stale_generation, 1, resource
                )

            peer_started = threading.Event()
            peer_done = threading.Event()
            peer_result: dict[str, object] = {}

            def peer_publish():
                peer_started.set()
                peer_result["result"] = certify_legacy_null_root(
                    factory, batch_size=1, resource_limits=_limits(rows=0)
                )
                peer_done.set()

            with ThreadPoolExecutor(max_workers=2) as executor:
                pending = executor.submit(stale_cleanup)
                assert paused.wait(timeout=15)
                peer = executor.submit(peer_publish)
                assert peer_started.wait(timeout=15)
                # The fixed short writer transaction must keep the peer behind
                # the stale page until that page commits.
                assert not peer_done.wait(timeout=2)
                release.set()
                pending.result(timeout=15)
                peer.result(timeout=15)
                result = peer_result["result"]
                assert isinstance(result, bootstrap.CertificationResult)
                assert result.status == "published"

            with factory() as check:
                generation = check.get(SettlementProjectionGeneration, generation_id)
                pointer = check.get(SettlementProjectionActive, "settlement")
                # RED: stale no-page reset currently regresses the winner to staging.
                assert generation is not None and generation.state == "published"
                assert pointer is not None and pointer.generation_id == generation_id
        finally:
            event.remove(engine, "before_cursor_execute", pause_after_no_page_select)
            engine.dispose()


def test_r11_cleanup_page_cannot_delete_peer_published_manifest():
    with tempfile.TemporaryDirectory(prefix="r11-cleanup-page-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{directory}/cleanup.sqlite",
            connect_args={"check_same_thread": False, "timeout": 30},
            isolation_level="AUTOCOMMIT",
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        resource = (1, 20_480, 40_960, 1_000_000)
        generation_id = _r11_seed_failed_cleanup(factory, resource, [("monthly", "2026-08")])
        with factory() as seed:
            seed.add(
                AggStoreMonthlySettlement(
                    month="2026-08",
                    store_id="r11-store",
                    product_scope="all",
                    product_type="all",
                    statement_status=1,
                    projection_run_id="r11-run",
                )
            )
            seed.commit()

        paused = threading.Event()
        release = threading.Event()
        armed = {"value": True}

        def pause_before_cleanup_delete(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ):
            upper = statement.upper().replace("\n", " ")
            if armed["value"] and upper.strip().startswith(
                "DELETE FROM SETTLEMENT_PROJECTION_PARTITION_MANIFEST"
            ):
                armed["value"] = False
                paused.set()
                assert release.wait(timeout=15)

        event.listen(engine, "before_cursor_execute", pause_before_cleanup_delete)
        try:
            with factory() as stale:
                stale_generation = stale.get(SettlementProjectionGeneration, generation_id)

            def stale_cleanup():
                return bootstrap._cleanup_failed_generation(
                    factory, stale_generation, 1, resource
                )

            peer_started = threading.Event()
            peer_done = threading.Event()
            peer_result: dict[str, object] = {}

            def peer_publish():
                peer_started.set()
                peer_result["result"] = certify_legacy_null_root(
                    factory, batch_size=1, resource_limits=_limits(rows=1)
                )
                peer_done.set()

            with ThreadPoolExecutor(max_workers=2) as executor:
                pending = executor.submit(stale_cleanup)
                assert paused.wait(timeout=15)
                peer = executor.submit(peer_publish)
                assert peer_started.wait(timeout=15)
                # The fixed short writer transaction must keep the peer behind
                # the stale page until that page commits.
                assert not peer_done.wait(timeout=2)
                release.set()
                pending.result(timeout=15)
                peer.result(timeout=15)
                result = peer_result["result"]
                assert isinstance(result, bootstrap.CertificationResult)
                assert result.status == "published"
                with factory() as before_release:
                    published_snapshot = _r5_control_snapshot(before_release)

            with factory() as after_release:
                # RED: stale page DELETE/reset currently changes the published
                # manifest set or generation after the peer has committed.
                assert _r5_control_snapshot(after_release) == published_snapshot
        finally:
            event.remove(engine, "before_cursor_execute", pause_before_cleanup_delete)
            engine.dispose()


@pytest.mark.parametrize(
    ("limits", "expected_code"),
    [
        (_limits(rows=0), "manifest_rows_exceed_limit"),
        (_limits(rows=1, write=20_479), "estimated_write_bytes_exceed_limit"),
        (_limits(rows=1, wal=40_959), "estimated_wal_bytes_exceed_limit"),
        (_limits(rows=1, headroom=61_439), "disk_headroom_insufficient"),
    ],
)
def test_r5_published_root_resource_guard_precedes_idempotency(
    db_session: Session, monkeypatch, limits: ResourceGateConfig, expected_code: str
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r5-resource-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="r5-resource-run",
        )
    )
    db_session.commit()
    first = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )
    assert first.status == "published"
    with _factory(db_session)() as check:
        before = _r5_control_snapshot(check)

    source_calls = {"count": 0}

    def source_must_not_be_read(*_args, **_kwargs):
        source_calls["count"] += 1
        raise AssertionError("published resource guard must not reread source")

    monkeypatch.setattr(bootstrap, "_select_source_page", source_must_not_be_read)
    result = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=limits
    )
    assert result == bootstrap.CertificationResult(
        generation_id=None,
        status="resource_guard",
        published=False,
        resumed=False,
        batch_count=0,
        partition_count=0,
        source_row_count=0,
        last_key=None,
        manifest_checksum=None,
        failure_code=expected_code,
    )
    assert source_calls["count"] == 0
    with _factory(db_session)() as check:
        assert _r5_control_snapshot(check) == before


@pytest.mark.parametrize(
    ("state", "phase"),
    [("ready", "verify"), ("published", "publish")],
)
def test_r5_verify_and_publish_checkpoint_require_null_artifact_cursor(
    db_session: Session, state: str, phase: str
):
    resource = (0, 16_384, 32_768, 1_000_000)
    generation_id = bootstrap._generation_id()
    checkpoint = bootstrap._checkpoint(
        phase=phase,
        artifact="monthly",
        cursor=None,
        stats=bootstrap._ScanStats(),
        resource=resource,
        batch_size=1,
    )
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state=state,
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=checkpoint,
            manifest_checksum=bootstrap._empty_manifest_checksum(),
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    if state == "published":
        db_session.add(
            SettlementProjectionActive(
                projection_name="settlement", generation_id=generation_id
            )
        )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="artifact|cursor|phase"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=0)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, generation_id)
        pointer = check.get(SettlementProjectionActive, "settlement")
        assert generation is not None
        if state == "ready":
            assert generation.state == "failed"
            assert pointer is None
        else:
            assert generation.state == "published"
            assert pointer is not None and pointer.generation_id == generation_id


@pytest.mark.parametrize(
    ("artifact", "partition_key"),
    [
        ("monthly", "2026-8"),
        ("ranking", "quarterly:2026-08"),
        ("score", "20260801|4:rule|5:store"),
    ],
)
def test_r5_cleanup_cursor_requires_canonical_partition_key(
    db_session: Session, artifact: str, partition_key: str
):
    resource = (1, 20_480, 40_960, 1_000_000)
    generation_id = bootstrap._generation_id()
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=generation_id,
            projection_name="settlement",
            state="failed",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="cleanup",
                artifact=None,
                cursor={"artifact": artifact, "partition_key": partition_key},
                stats=bootstrap._ScanStats(),
                resource=resource,
                batch_size=1,
            ),
            last_key=f"cleanup:{artifact}:{partition_key}",
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.add(
        SettlementProjectionPartitionManifest(
            generation_id=generation_id,
            artifact=artifact,
            partition_key=partition_key,
            owner_state="owned",
            source_kind="legacy_root",
            data_generation_id=None,
            base_generation_id=None,
            row_count=1,
            amount_total_cent=0,
            status_counts_json={"1": 1} if artifact == "monthly" else {},
            checksum="a" * 64,
            last_key=None,
        )
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="partition|cleanup"):
        bootstrap._cleanup_failed_generation(
            _factory(db_session),
            db_session.get(SettlementProjectionGeneration, generation_id),
            1,
            resource,
        )
    with _factory(db_session)() as check:
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 1


def _r5_manifest(
    artifact: str,
    partition_key: str,
    cursor: dict[str, object],
    *,
    row_count: int = 1,
    amount_total_cent: int = 0,
    status_counts_json: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "generation_id": bootstrap._generation_id(),
        "artifact": artifact,
        "partition_key": partition_key,
        "owner_state": "owned",
        "source_kind": "legacy_root",
        "data_generation_id": None,
        "base_generation_id": None,
        "row_count": row_count,
        "amount_total_cent": amount_total_cent,
        "status_counts_json": (
            {"1": 1} if artifact == "monthly" and status_counts_json is None else status_counts_json or {}
        ),
        "checksum": "a" * 64,
        "last_key": bootstrap._cursor_token(artifact, cursor),
    }


@pytest.mark.parametrize(
    ("artifact", "partition_key", "cursor"),
    [
        (
            "monthly",
            "2026-08",
            {
                "month": "2026-09",
                "store_id": "store",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": "run",
                "id": 1,
            },
        ),
        (
            "ranking",
            "monthly:2026-08",
            {
                "period_type": 2,
                "period_key": "2026-08",
                "store_id": "store",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": "run",
                "id": 1,
            },
        ),
        (
            "score",
            "2026-08-01|4:rule|5:store",
            {
                "snapshot_date": "2026-08-01",
                "rule_version_id": "other",
                "store_id": "store",
                "snapshot_run_id": "run",
                "snapshot_id": "snapshot",
            },
        ),
    ],
)
def test_r5_manifest_last_key_must_bind_to_canonical_partition(
    artifact: str, partition_key: str, cursor: dict[str, object]
):
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="partition|cursor|key"):
        bootstrap._validate_manifest_row(
            _r5_manifest(artifact, partition_key, cursor), artifact
        )


@pytest.mark.parametrize(
    ("partition_key", "cursor"),
    [
        (
            "2026-08-01|04:rule|05:store",
            {
                "snapshot_date": "2026-08-01",
                "rule_version_id": "rule",
                "store_id": "store",
                "snapshot_run_id": "run",
                "snapshot_id": "snapshot",
            },
        ),
        (
            "2026-08-01|4:rule|5:store",
            {
                "snapshot_date": "2026-08-02",
                "rule_version_id": "rule",
                "store_id": "store",
                "snapshot_run_id": "run",
                "snapshot_id": "snapshot",
            },
        ),
        (
            "2026-08-01|4:rule|5:store",
            {
                "snapshot_date": "2026-08-01",
                "rule_version_id": "other",
                "store_id": "store",
                "snapshot_run_id": "run",
                "snapshot_id": "snapshot",
            },
        ),
        (
            "2026-08-01|4:rule|5:other",
            {
                "snapshot_date": "2026-08-01",
                "rule_version_id": "rule",
                "store_id": "store",
                "snapshot_run_id": "run",
                "snapshot_id": "snapshot",
            },
        ),
    ],
)
def test_r5_score_partition_key_is_strict_and_cursor_bound(
    partition_key: str, cursor: dict[str, object]
):
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="partition|key|cursor|date"):
        bootstrap._validate_manifest_row(
            _r5_manifest("score", partition_key, cursor), "score"
        )


@pytest.mark.parametrize(
    ("rule_id", "store_id"),
    [
        ("rule|with:pipe", "store"),
        ("rule", "store:with|pipe"),
        ("规则|版本:一", "门店:北|A"),
    ],
)
def test_r6_score_partition_parser_accepts_delimited_unicode_identities(
    rule_id: str, store_id: str
):
    partition_key = bootstrap.canonical_score_partition_key(
        date(2026, 8, 1), rule_id, store_id
    )
    assert bootstrap._canonical_partition_key("score", partition_key) == partition_key
    cursor = {
        "snapshot_date": "2026-08-01",
        "rule_version_id": rule_id,
        "store_id": store_id,
        "snapshot_run_id": "run",
        "snapshot_id": "snapshot",
    }
    manifest = _r5_manifest("score", partition_key, cursor)
    bootstrap._validate_manifest_row(manifest, "score")


@pytest.mark.parametrize("raw_date", ["20260801", "2021-W01-1"])
def test_r5_score_dates_require_canonical_iso_round_trip(raw_date: str):
    row = {
        "snapshot_id": "snapshot",
        "snapshot_run_id": "run",
        "snapshot_date": raw_date,
        "run_snapshot_date": raw_date,
        "store_id": "store",
        "rule_version_id": "rule",
    }
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="date|canonical"):
        bootstrap._score_partition(row)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="date|canonical"):
        bootstrap._cursor_from_row("score", row)
    checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact="score",
        cursor={
            "snapshot_date": raw_date,
            "rule_version_id": "rule",
            "store_id": "store",
            "snapshot_run_id": "run",
            "snapshot_id": "snapshot",
        },
        stats=bootstrap._ScanStats(),
        resource=(0, 16_384, 32_768, 1_000_000),
        batch_size=1,
    )
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=0,
        estimated_write_bytes=16_384,
        estimated_wal_bytes=32_768,
        estimated_disk_headroom_bytes=1_000_000,
        checkpoint_json=checkpoint,
        last_key=bootstrap._cursor_token("score", checkpoint["cursor"]),
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="date|canonical"):
        bootstrap._validate_checkpoint(generation, (0, 16_384, 32_768, 1_000_000))


@pytest.mark.parametrize(
    "status_counts",
    [{}, {"1": 1}, {"1": 1, "2": 1}, {"1": 0, "2": 1}],
)
def test_r5_monthly_status_counts_are_positive_and_sum_to_rows(
    status_counts: dict[str, int]
):
    manifest = _r5_manifest(
        "monthly",
        "2026-08",
        {
            "month": "2026-08",
            "store_id": "store",
            "product_scope": "all",
            "product_type": "all",
            "projection_run_id": "run",
            "id": 1,
        },
        row_count=1 if status_counts != {"1": 1} else 2,
        status_counts_json=status_counts,
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="status"):
        bootstrap._validate_manifest_row(manifest, "monthly")


def test_r5_score_manifest_amount_must_be_zero():
    manifest = _r5_manifest(
        "score",
        "2026-08-01|4:rule|5:store",
        {
            "snapshot_date": "2026-08-01",
            "rule_version_id": "rule",
            "store_id": "store",
            "snapshot_run_id": "run",
            "snapshot_id": "snapshot",
        },
        amount_total_cent=1,
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="amount|score"):
        bootstrap._validate_manifest_row(manifest, "score")


def test_r5_already_published_coherent_monthly_status_tamper_is_immutable(
    db_session: Session,
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r5-tamper-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="r5-tamper-run",
        )
    )
    db_session.commit()
    first = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )
    assert first.status == "published"
    with _factory(db_session)() as tamper:
        manifest = tamper.scalar(select(SettlementProjectionPartitionManifest))
        assert manifest is not None
        manifest.status_counts_json = {"1": 1, "2": 0}
        tamper.flush()
        manifest_mapping = tamper.execute(
            select(SettlementProjectionPartitionManifest.__table__).where(
                SettlementProjectionPartitionManifest.generation_id == bootstrap._generation_id()
            )
        ).mappings().one()
        generation = tamper.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None
        generation.manifest_checksum = bootstrap._manifest_checksum([dict(manifest_mapping)])
        tamper.commit()
        before = _r5_control_snapshot(tamper)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="status|manifest"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        assert _r5_control_snapshot(check) == before


def test_r5_already_published_coherent_partition_cursor_tamper_is_immutable(
    db_session: Session, monkeypatch
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r5-cursor-tamper-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="r5-cursor-tamper-run",
        )
    )
    db_session.commit()
    first = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )
    assert first.status == "published"
    with _factory(db_session)() as tamper:
        manifest = tamper.scalar(select(SettlementProjectionPartitionManifest))
        generation = tamper.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert manifest is not None and generation is not None
        token = json.loads(str(manifest.last_key))
        wrong_cursor = dict(token["cursor"])
        wrong_cursor["month"] = "2026-09"
        manifest.last_key = bootstrap._cursor_token("monthly", wrong_cursor)
        tamper.flush()
        mapping = tamper.execute(
            select(SettlementProjectionPartitionManifest.__table__).where(
                SettlementProjectionPartitionManifest.generation_id == bootstrap._generation_id()
            )
        ).mappings().one()
        generation.manifest_checksum = bootstrap._manifest_checksum([dict(mapping)])
        generation.last_key = manifest.last_key
        generation.checkpoint_json = bootstrap._checkpoint(
            phase="publish",
            artifact=None,
            cursor=None,
            stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
            resource=(1, 20_480, 40_960, 1_000_000),
            batch_size=1,
        )
        tamper.commit()
        before = _r5_control_snapshot(tamper)

    source_calls = {"count": 0}

    def source_must_not_be_read(*_args, **_kwargs):
        source_calls["count"] += 1
        raise AssertionError("published metadata corruption must not reread source")

    monkeypatch.setattr(bootstrap, "_select_source_page", source_must_not_be_read)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="partition|cursor|key"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    assert source_calls["count"] == 0
    with _factory(db_session)() as check:
        assert _r5_control_snapshot(check) == before


_R7_REQUIRED_CHECKPOINT_KEYS = (
    "protocol",
    "operation",
    "phase",
    "artifact",
    "cursor",
    "batch_count",
    "batch_size",
    "partition_count",
    "source_row_count",
    "estimated_manifest_rows",
    "estimated_write_bytes",
    "estimated_wal_bytes",
    "estimated_disk_headroom_bytes",
    "expected_active_pointer",
)


@pytest.mark.parametrize("state,phase", [("ready", "verify"), ("published", "publish")])
@pytest.mark.parametrize("missing_key", _R7_REQUIRED_CHECKPOINT_KEYS)
def test_r7_checkpoint_missing_any_required_key_is_rejected(
    state: str, phase: str, missing_key: str
):
    resource = (1, 20_480, 40_960, 1_000_000)
    checkpoint = bootstrap._checkpoint(
        phase=phase,
        artifact=None,
        cursor=None,
        stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
        resource=resource,
        batch_size=1,
    )
    checkpoint.pop(missing_key)
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state=state,
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=checkpoint,
        last_key=None,
        manifest_checksum=bootstrap._empty_manifest_checksum() if state == "published" else None,
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="checkpoint|missing|required"):
        bootstrap._validate_checkpoint(generation, resource)


def test_r7_score_partition_oversized_length_prefix_is_typed_error():
    oversized_length = "9" * 5_001
    partition_key = f"2026-08-01|{oversized_length}:rule|5:store"
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="partition|key|length"):
        bootstrap._canonical_partition_key("score", partition_key)


@pytest.mark.parametrize("missing_key", ["artifact", "cursor", "expected_active_pointer"])
def test_r7_ready_missing_checkpoint_key_fails_closed(
    db_session: Session, monkeypatch, missing_key: str
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id=f"r7-ready-{missing_key}-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id=f"r7-ready-{missing_key}-run",
        )
    )
    db_session.commit()
    original_finalize = bootstrap._finalize_generation_fenced

    def tamper_ready(factory, generation_id, resource, batch_size, resumed):
        with factory() as writer:
            generation = writer.get(SettlementProjectionGeneration, generation_id)
            assert generation is not None
            checkpoint = dict(generation.checkpoint_json)
            checkpoint.pop(missing_key)
            writer.execute(
                update(SettlementProjectionGeneration)
                .where(SettlementProjectionGeneration.generation_id == generation_id)
                .values(checkpoint_json=checkpoint)
            )
            writer.commit()
        return original_finalize(factory, generation_id, resource, batch_size, resumed)

    monkeypatch.setattr(bootstrap, "_finalize_generation_fenced", tamper_ready)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="checkpoint|missing|required"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"
        assert check.get(SettlementProjectionActive, "settlement") is None


@pytest.mark.parametrize("missing_key", ["artifact", "cursor", "expected_active_pointer"])
def test_r7_published_missing_checkpoint_key_is_immutable(
    db_session: Session, monkeypatch, missing_key: str
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id=f"r7-published-{missing_key}-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id=f"r7-published-{missing_key}-run",
        )
    )
    db_session.commit()
    first = certify_legacy_null_root(
        _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
    )
    assert first.status == "published"
    with _factory(db_session)() as tamper:
        generation = tamper.get(SettlementProjectionGeneration, first.generation_id)
        assert generation is not None
        checkpoint = dict(generation.checkpoint_json)
        checkpoint.pop(missing_key)
        generation.checkpoint_json = checkpoint
        tamper.commit()
        before = _r5_control_snapshot(tamper)

    source_calls = {"count": 0}

    def source_must_not_be_read(*_args, **_kwargs):
        source_calls["count"] += 1
        raise AssertionError("published checkpoint corruption must not reread source")

    monkeypatch.setattr(bootstrap, "_select_source_page", source_must_not_be_read)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="checkpoint|missing|required"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    assert source_calls["count"] == 0
    with _factory(db_session)() as check:
        assert _r5_control_snapshot(check) == before


def test_r8_initial_monthly_checkpoint_requires_empty_last_key_and_totals():
    resource = (1, 20_480, 40_960, 1_000_000)
    checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact="monthly",
        cursor=None,
        stats=bootstrap._ScanStats(),
        resource=resource,
        batch_size=1,
    )
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=checkpoint,
        last_key="bogus-initial-last-key",
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="initial|last_key|checkpoint"):
        bootstrap._validate_checkpoint(generation, resource)


@pytest.mark.parametrize("artifact", ["ranking", "score"])
def test_r8_transition_checkpoint_cursor_none_keeps_previous_terminal_last_key(artifact: str):
    resource = (2, 24_576, 49_152, 1_000_000)
    if artifact == "ranking":
        previous_last_key = bootstrap._cursor_token(
            "monthly",
            {
                "month": "2026-08",
                "store_id": "store",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": "monthly-run",
                "id": 1,
            },
        )
    else:
        previous_last_key = bootstrap._cursor_token(
            "ranking",
            {
                "period_type": 1,
                "period_key": "2026-08",
                "store_id": "store",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": "ranking-run",
                "id": 1,
            },
        )
    checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact=artifact,
        cursor=None,
        stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
        resource=resource,
        batch_size=1,
    )
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=checkpoint,
        last_key=previous_last_key,
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    assert bootstrap._validate_checkpoint(generation, resource)["artifact"] == artifact


@pytest.mark.parametrize("artifact", ["ranking", "score", None])
def test_r8_empty_prior_transition_cursor_none_keeps_empty_last_key(artifact: str | None):
    resource = (0, 16_384, 32_768, 1_000_000)
    checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact=artifact,
        cursor=None,
        stats=bootstrap._ScanStats(),
        resource=resource,
        batch_size=1,
    )
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=checkpoint,
        last_key=None,
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    assert bootstrap._validate_checkpoint(generation, resource)["artifact"] == artifact


def test_r8_empty_initial_monthly_checkpoint_remains_valid():
    resource = (0, 16_384, 32_768, 1_000_000)
    checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact="monthly",
        cursor=None,
        stats=bootstrap._ScanStats(),
        resource=resource,
        batch_size=1,
    )
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=checkpoint,
        last_key=None,
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    assert bootstrap._validate_checkpoint(generation, resource)["artifact"] == "monthly"


def test_r8_existing_initial_checkpoint_with_source_row_fails_before_publish(
    db_session: Session,
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r8-initial-corrupt-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="r8-initial-corrupt-run",
        )
    )
    resource = (1, 20_480, 40_960, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="scan",
                artifact="monthly",
                cursor=None,
                stats=bootstrap._ScanStats(),
                resource=resource,
                batch_size=1,
            ),
            last_key="bogus-initial-last-key",
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="initial|last_key|checkpoint"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"
        assert generation.last_key == "bogus-initial-last-key"
        assert check.get(SettlementProjectionActive, "settlement") is None
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 0


def test_r8_existing_ranking_initial_checkpoint_with_source_row_fails_before_publish(
    db_session: Session,
):
    db_session.add(
        AggStoreRanking(
            period_type=1,
            period_key="2026-08",
            month="2026-08",
            store_id="r8-ranking-corrupt-store",
            store_name="R8 Ranking Store",
            product_scope="all",
            product_type="all",
            projection_run_id="r8-ranking-corrupt-run",
            promotion_net_fee_cent=2,
            management_net_fee_cent=1,
            net_settlement_reference_cent=1,
        )
    )
    resource = (1, 20_480, 40_960, 1_000_000)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=bootstrap._checkpoint(
                phase="scan",
                artifact="ranking",
                cursor=None,
                stats=bootstrap._ScanStats(),
                resource=resource,
                batch_size=1,
            ),
            last_key="bogus-ranking-initial-last-key",
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="initial|last_key|checkpoint"):
        certify_legacy_null_root(
            _factory(db_session), batch_size=1, resource_limits=_limits(rows=1)
        )
    with _factory(db_session)() as check:
        generation = check.get(SettlementProjectionGeneration, bootstrap._generation_id())
        assert generation is not None and generation.state == "failed"
        assert generation.last_key == "bogus-ranking-initial-last-key"
        assert check.get(SettlementProjectionActive, "settlement") is None
        assert check.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)) == 0


def test_r8_reload_after_cas_failure_rejects_malformed_peer_checkpoint(
    db_session: Session, monkeypatch
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r8-reload-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="r8-reload-run",
        )
    )
    resource = (1, 20_480, 40_960, 1_000_000)
    initial_checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact="monthly",
        cursor=None,
        stats=bootstrap._ScanStats(),
        resource=resource,
        batch_size=1,
    )
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=initial_checkpoint,
            last_key=None,
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.commit()
    original_upsert = bootstrap._upsert_manifests
    injected = {"done": False}

    def inject_malformed_peer(session, payloads):
        if not injected["done"]:
            injected["done"] = True
            malformed = dict(initial_checkpoint)
            malformed.pop("batch_count")
            session.execute(
                update(SettlementProjectionGeneration)
                .where(SettlementProjectionGeneration.generation_id == bootstrap._generation_id())
                .values(checkpoint_json=malformed, last_key=None)
            )
            session.commit()
        return original_upsert(session, payloads)

    monkeypatch.setattr(bootstrap, "_upsert_manifests", inject_malformed_peer)
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="required|checkpoint"):
        bootstrap._scan_artifact(
            _factory(db_session),
            bootstrap._generation_id(),
            "monthly",
            1,
            initial_checkpoint,
            resource,
        )


def test_r8_adopt_peer_after_prefix_error_rejects_malformed_checkpoint(
    db_session: Session, monkeypatch
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r8-adopt-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="r8-adopt-run",
        )
    )
    db_session.commit()
    raw = bootstrap._select_source_page(db_session, "monthly", 1, None)[0]
    cursor = bootstrap._cursor_from_row("monthly", raw)
    token = bootstrap._cursor_token("monthly", cursor)
    resource = (1, 20_480, 40_960, 1_000_000)
    initial_checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact="monthly",
        cursor=cursor,
        stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
        resource=resource,
        batch_size=1,
    )
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            checkpoint_json=initial_checkpoint,
            last_key=token,
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.commit()

    def inject_malformed_prefix(*args, **kwargs):
        with _factory(db_session)() as peer:
            generation = peer.get(SettlementProjectionGeneration, bootstrap._generation_id())
            assert generation is not None
            malformed = dict(generation.checkpoint_json)
            malformed.pop("partition_count")
            peer.execute(
                update(SettlementProjectionGeneration)
                .where(SettlementProjectionGeneration.generation_id == bootstrap._generation_id())
                .values(checkpoint_json=malformed)
            )
            peer.commit()
        raise bootstrap.LegacyProjectionBootstrapError(
            "source prefix has no certified manifest"
        )

    monkeypatch.setattr(
        bootstrap, "_validate_existing_manifests_prefix_once", inject_malformed_prefix
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="required|checkpoint"):
        bootstrap._scan_artifact(
            _factory(db_session),
            bootstrap._generation_id(),
            "monthly",
            1,
            initial_checkpoint,
            resource,
        )


def test_r8_remote_progress_rejects_malformed_checkpoint_before_page_read(
    db_session: Session,
):
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r8-remote-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="r8-remote-run",
        )
    )
    resource = (1, 20_480, 40_960, 1_000_000)
    initial_checkpoint = bootstrap._checkpoint(
        phase="scan",
        artifact="monthly",
        cursor=None,
        stats=bootstrap._ScanStats(),
        resource=resource,
        batch_size=1,
    )
    malformed = dict(initial_checkpoint)
    malformed.pop("source_row_count")
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=bootstrap._generation_id(),
            projection_name="settlement",
            state="staging",
            input_fingerprint=bootstrap._input_fingerprint(),
            lineage_depth=0,
            estimated_write_rows=resource[0],
            estimated_write_bytes=resource[1],
            estimated_wal_bytes=resource[2],
            estimated_disk_headroom_bytes=resource[3],
            checkpoint_json=malformed,
            last_key=None,
            source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
        )
    )
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="required|checkpoint"):
        bootstrap._scan_artifact(
            _factory(db_session),
            bootstrap._generation_id(),
            "monthly",
            1,
            initial_checkpoint,
            resource,
        )


def test_r8_transition_last_key_with_unknown_artifact_is_typed_error():
    resource = (1, 20_480, 40_960, 1_000_000)
    cursor = {
        "snapshot_date": "2026-08-01",
        "rule_version_id": "rule",
        "store_id": "store",
        "snapshot_run_id": "run",
        "snapshot_id": "snapshot",
    }
    bogus_last_key = bootstrap._cursor_token("bogus", cursor)
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=bootstrap._checkpoint(
            phase="scan",
            artifact=None,
            cursor=None,
            stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
            resource=resource,
            batch_size=1,
        ),
        last_key=bogus_last_key,
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="artifact|last_key|checkpoint"):
        bootstrap._validate_checkpoint(generation, resource)


@pytest.mark.parametrize(
    "constant", [float("nan"), float("inf")], ids=["NaN", "Infinity"]
)
def test_r8_transition_last_key_nonstandard_json_constant_is_typed_error(constant: str):
    resource = (1, 20_480, 40_960, 1_000_000)
    cursor = {
        "snapshot_date": "2026-08-01",
        "rule_version_id": "rule",
        "store_id": "store",
        "snapshot_run_id": "run",
        "snapshot_id": constant,
    }
    nonstandard_last_key = json.dumps(
        {"artifact": "score", "cursor": cursor},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=True,
    )
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=bootstrap._checkpoint(
            phase="scan",
            artifact=None,
            cursor=None,
            stats=bootstrap._ScanStats(batch_count=1, partition_count=1, source_row_count=1),
            resource=resource,
            batch_size=1,
        ),
        last_key=nonstandard_last_key,
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="JSON|last_key|cursor"):
        bootstrap._validate_checkpoint(generation, resource)


@pytest.mark.parametrize(
    "totals",
    [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
)
def test_r8_checkpoint_totals_require_cursor_source_consistency(
    totals: tuple[int, int, int]
):
    resource = (1, 20_480, 40_960, 1_000_000)
    cursor = {
        "month": "2026-08",
        "store_id": "store",
        "product_scope": "all",
        "product_type": "all",
        "projection_run_id": "run",
        "id": 1,
    }
    generation = SettlementProjectionGeneration(
        generation_id=bootstrap._generation_id(),
        projection_name="settlement",
        state="staging",
        input_fingerprint=bootstrap._input_fingerprint(),
        lineage_depth=0,
        estimated_write_rows=resource[0],
        estimated_write_bytes=resource[1],
        estimated_wal_bytes=resource[2],
        estimated_disk_headroom_bytes=resource[3],
        checkpoint_json=bootstrap._checkpoint(
            phase="scan",
            artifact="monthly",
            cursor=cursor,
            stats=bootstrap._ScanStats(
                batch_count=totals[0],
                partition_count=totals[1],
                source_row_count=totals[2],
            ),
            resource=resource,
            batch_size=1,
        ),
        last_key=bootstrap._cursor_token("monthly", cursor),
        source_input_json=dict(bootstrap._PROTOCOL_ENVELOPE),
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="totals|cursor|checkpoint"):
        bootstrap._validate_checkpoint(generation, resource)


def _seed_task3c_lineage(db_session: Session, *, prefix: str = "task3c") -> dict[str, str]:
    root_id = f"{prefix}-root"
    head_id = f"{prefix}-head"
    monthly_last_key = bootstrap._cursor_token(
        "monthly",
        {
            "month": "2026-09",
            "store_id": f"{prefix}-store",
            "product_scope": "all",
            "product_type": "all",
            "projection_run_id": f"{prefix}-run",
            "id": 1,
        },
    )
    root_manifest = {
        "artifact": "monthly",
        "partition_key": "2026-08",
        "owner_state": "owned",
        "source_kind": "legacy_root",
        "data_generation_id": None,
        "base_generation_id": None,
        "row_count": 1,
        "amount_total_cent": 100,
        "status_counts_json": {"1": 1},
        "checksum": "1" * 64,
        "last_key": bootstrap._cursor_token(
            "monthly",
            {
                "month": "2026-08",
                "store_id": f"{prefix}-legacy-store",
                "product_scope": "all",
                "product_type": "all",
                "projection_run_id": f"{prefix}-legacy-run",
                "id": 1,
            },
        ),
    }
    head_manifests = [
        {
            "artifact": "monthly",
            "partition_key": "2026-09",
            "owner_state": "owned",
            "source_kind": "overlay",
            "data_generation_id": head_id,
            "base_generation_id": root_id,
            "row_count": 1,
            "amount_total_cent": 250,
            "status_counts_json": {"2": 1},
            "checksum": "2" * 64,
            "last_key": monthly_last_key,
        },
        {
            "artifact": "ranking",
            "partition_key": "monthly:2026-09",
            "owner_state": "tombstone",
            "source_kind": "tombstone",
            "data_generation_id": None,
            "base_generation_id": root_id,
            "row_count": 0,
            "amount_total_cent": 0,
            "status_counts_json": {},
            "checksum": None,
            "last_key": None,
        },
    ]
    db_session.add_all(
        [
            SettlementProjectionGeneration(
                generation_id=root_id,
                generation_kind="legacy_root",
                projection_name="settlement",
                state="superseded",
                input_fingerprint="a" * 64,
                lineage_depth=0,
                checkpoint_json={},
                manifest_checksum=bootstrap._manifest_checksum([root_manifest]),
                source_input_json={},
            ),
            SettlementProjectionGeneration(
                generation_id=head_id,
                base_generation_id=root_id,
                generation_kind="lineage",
                projection_name="settlement",
                state="published",
                input_fingerprint="b" * 64,
                lineage_depth=1,
                checkpoint_json={},
                manifest_checksum=bootstrap._manifest_checksum(head_manifests),
                source_input_json={},
            ),
        ]
    )
    db_session.flush()
    db_session.add(
        SettlementProjectionPartitionManifest(
            generation_id=root_id,
            published_at=datetime.now(timezone.utc),
            **root_manifest,
        )
    )
    db_session.add_all(
        [
            SettlementProjectionPartitionManifest(
                generation_id=head_id,
                published_at=datetime.now(timezone.utc),
                **manifest,
            )
            for manifest in head_manifests
        ]
    )
    db_session.add(
        SettlementMonthlyOverlay(
            generation_id=head_id,
            base_generation_id=root_id,
            month="2026-09",
            partition_key="2026-09",
            store_id=f"{prefix}-store",
            product_scope="all",
            product_type="all",
            sales_order_count=1,
            sales_amount_cent=250,
            statement_status=2,
        )
    )
    db_session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id=head_id
        )
    )
    db_session.commit()
    return {"root": root_id, "head": head_id}


def _compaction_threshold(*, depth: int = 1, batch_size: int = 2):
    return CompactionThresholdConfig(
        minimum_lineage_depth=depth,
        batch_size=batch_size,
    )


def test_task3c_threshold_not_met_is_zero_write(db_session: Session):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-threshold")
    before = (
        db_session.scalar(select(func.count()).select_from(SettlementProjectionGeneration)),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionCompactionClosure)),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)),
    )

    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(depth=2),
        resource_limits=_limits(rows=10),
    )

    db_session.expire_all()
    after = (
        db_session.scalar(select(func.count()).select_from(SettlementProjectionGeneration)),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionCompactionClosure)),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)),
    )
    assert result.status == "not_needed"
    assert result.ready is False
    assert result.generation_id is None
    assert after == before


def test_task3c_builds_ready_compact_metadata_without_publishing(db_session: Session):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-build")
    business_before = db_session.scalar(
        select(func.count()).select_from(SettlementMonthlyOverlay)
    )

    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(),
        resource_limits=_limits(rows=10),
    )

    assert result.status == "ready"
    assert result.ready is True
    assert result.generation_id is not None
    db_session.expire_all()
    generation = db_session.get(SettlementProjectionGeneration, result.generation_id)
    pointer = db_session.get(SettlementProjectionActive, "settlement")
    closures = db_session.scalars(
        select(SettlementProjectionCompactionClosure).where(
            SettlementProjectionCompactionClosure.compact_generation_id
            == result.generation_id
        )
    ).all()
    manifests = db_session.scalars(
        select(SettlementProjectionPartitionManifest)
        .where(SettlementProjectionPartitionManifest.generation_id == result.generation_id)
        .order_by(
            SettlementProjectionPartitionManifest.artifact,
            SettlementProjectionPartitionManifest.partition_key,
        )
    ).all()

    assert generation is not None
    assert generation.state == "ready"
    assert generation.generation_kind == "compact"
    assert generation.base_generation_id is None
    assert generation.compaction_base_generation_id == ids["head"]
    assert generation.lineage_depth == 0
    assert generation.published_at is None
    assert pointer is not None and pointer.generation_id == ids["head"]
    assert {row.source_generation_id for row in closures} == {
        ids["root"],
        ids["head"],
    }
    assert [(row.artifact, row.partition_key) for row in manifests] == [
        ("monthly", "2026-09"),
        ("ranking", "monthly:2026-09"),
    ]
    monthly, tombstone = manifests
    assert monthly.owner_state == "owned"
    assert monthly.source_kind == "overlay"
    assert monthly.data_generation_id == ids["head"]
    assert monthly.reference_head_generation_id == result.generation_id
    assert monthly.base_generation_id is None
    assert tombstone.owner_state == "tombstone"
    assert tombstone.data_generation_id is None
    assert tombstone.reference_head_generation_id is None
    assert result.manifest_checksum == generation.manifest_checksum

    retry = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(),
        resource_limits=_limits(rows=10),
    )
    assert retry.status == "already_ready"
    assert retry.generation_id == result.generation_id
    assert retry.manifest_checksum == result.manifest_checksum
    assert db_session.scalar(
        select(func.count()).select_from(SettlementProjectionGeneration)
    ) == 3
    assert db_session.scalar(
        select(func.count()).select_from(SettlementMonthlyOverlay)
    ) == business_before


@pytest.mark.parametrize(
    "limits,code",
    [
        (_limits(rows=1), "manifest_rows_exceed_limit"),
        (_limits(rows=10, write=1), "estimated_write_bytes_exceed_limit"),
        (_limits(rows=10, wal=1), "estimated_wal_bytes_exceed_limit"),
        (_limits(rows=10, headroom=1), "disk_headroom_insufficient"),
    ],
)
def test_task3c_resource_guard_precedes_all_writes(
    db_session: Session, limits: ResourceGateConfig, code: str
):
    ids = _seed_task3c_lineage(db_session, prefix=f"task3c-guard-{code}")
    before = (
        db_session.scalar(select(func.count()).select_from(SettlementProjectionGeneration)),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionCompactionClosure)),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)),
    )

    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(),
        resource_limits=limits,
    )

    db_session.expire_all()
    after = (
        db_session.scalar(select(func.count()).select_from(SettlementProjectionGeneration)),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionCompactionClosure)),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionPartitionManifest)),
    )
    assert result.status == "resource_guard"
    assert result.failure_code == code
    assert after == before


def test_task3c_crash_after_committed_page_resumes_same_generation(db_session: Session):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-resume")
    state = {"commits": 0, "crashed": False}

    class CrashAfterFirstPageSession(Session):
        def commit(self):  # type: ignore[override]
            result = super().commit()
            state["commits"] += 1
            if state["commits"] == 2 and not state["crashed"]:
                state["crashed"] = True
                raise RuntimeError("task3c injected post-page crash")
            return result

    crashing_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        future=True,
        class_=CrashAfterFirstPageSession,
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="compaction failed"):
        compact_projection_metadata(
            crashing_factory,
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(batch_size=1),
            resource_limits=_limits(rows=10),
        )

    with _factory(db_session)() as check:
        compact = check.scalar(
            select(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_kind == "compact"
            )
        )
        assert compact is not None
        assert compact.state == "staging"
        assert compact.checkpoint_json["partition_count"] == 1
        compact_id = compact.generation_id
        assert check.scalar(
            select(func.count())
            .select_from(SettlementProjectionPartitionManifest)
            .where(SettlementProjectionPartitionManifest.generation_id == compact_id)
        ) == 1

    resumed = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(batch_size=1),
        resource_limits=_limits(rows=10),
    )
    assert resumed.status == "ready"
    assert resumed.resumed is True
    assert resumed.generation_id == compact_id
    assert resumed.partition_count == 2
    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementProjectionPartitionManifest)
        .where(SettlementProjectionPartitionManifest.generation_id == compact_id)
    ) == 2


def test_task3c_ready_metadata_resolves_depth_zero_after_generic_publish_simulation(
    db_session: Session,
):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-resolve")
    old_pinned = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["2026-09"],
        pinned_generation_id=ids["head"],
    )["2026-09"]
    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(),
        resource_limits=_limits(rows=10),
    )
    assert result.status == "ready"

    # Task 3c deliberately does not own publication. Simulate the later generic
    # mutation solely to exercise the accepted Task 3b compact resolver.
    compact = db_session.get(SettlementProjectionGeneration, result.generation_id)
    base = db_session.get(SettlementProjectionGeneration, ids["head"])
    pointer = db_session.get(SettlementProjectionActive, "settlement")
    assert compact is not None and base is not None and pointer is not None
    compact.state = "published"
    compact.published_at = datetime.now(timezone.utc)
    pointer.generation_id = result.generation_id
    db_session.commit()

    resolved_monthly = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["2026-08", "2026-09"],
        pinned_generation_id=result.generation_id,
    )
    resolved_ranking = resolve_projection_partitions(
        db_session,
        artifact="ranking",
        partition_keys=["monthly:2026-09"],
        pinned_generation_id=result.generation_id,
    )
    still_old = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["2026-09"],
        pinned_generation_id=ids["head"],
    )["2026-09"]

    assert resolved_monthly["2026-08"].source_kind == "legacy_root"
    assert resolved_monthly["2026-08"].source_generation_ids == frozenset()
    assert resolved_monthly["2026-09"].lineage_depth == 0
    assert resolved_monthly["2026-09"].actual_data_generation_id == ids["head"]
    assert resolved_monthly["2026-09"].source_generation_ids == frozenset(
        {ids["head"]}
    )
    assert resolved_ranking["monthly:2026-09"].source_kind == "tombstone"
    assert resolved_ranking["monthly:2026-09"].source_generation_ids == frozenset()
    assert still_old.actual_data_generation_id == old_pinned.actual_data_generation_id


def test_task3c_corrupt_ready_manifest_fails_then_bounded_cleanup_rebuilds(
    db_session: Session,
):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-cleanup")
    first = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(batch_size=1),
        resource_limits=_limits(rows=10),
    )
    assert first.status == "ready"
    manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == first.generation_id,
            SettlementProjectionPartitionManifest.source_kind == "overlay",
        )
    )
    assert manifest is not None
    manifest.amount_total_cent += 1
    db_session.commit()

    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError, match="verification|manifest"
    ):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(batch_size=1),
            resource_limits=_limits(rows=10),
        )
    db_session.expire_all()
    failed = db_session.get(SettlementProjectionGeneration, first.generation_id)
    assert failed is not None
    assert failed.state == "failed"
    assert failed.failure_code == "compaction_failed"

    rebuilt = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(batch_size=1),
        resource_limits=_limits(rows=10),
    )
    assert rebuilt.status == "ready"
    assert rebuilt.resumed is True
    assert rebuilt.generation_id == first.generation_id
    db_session.expire_all()
    generation = db_session.get(SettlementProjectionGeneration, first.generation_id)
    assert generation is not None and generation.state == "ready"
    assert generation.failure_code is None
    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementProjectionCompactionClosure)
        .where(
            SettlementProjectionCompactionClosure.compact_generation_id
            == first.generation_id
        )
    ) == 2
    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementProjectionPartitionManifest)
        .where(SettlementProjectionPartitionManifest.generation_id == first.generation_id)
    ) == 2


def _seed_task3c_many_tombstones(
    db_session: Session, *, prefix: str, count: int
) -> dict[str, str]:
    root_id = f"{prefix}-root"
    head_id = f"{prefix}-head"
    manifests = []
    for index in range(count):
        year = 2020 + index // 12
        month = 1 + index % 12
        manifests.append(
            {
                "artifact": "ranking",
                "partition_key": f"monthly:{year:04d}-{month:02d}",
                "owner_state": "tombstone",
                "source_kind": "tombstone",
                "data_generation_id": None,
                "base_generation_id": root_id,
                "row_count": 0,
                "amount_total_cent": 0,
                "status_counts_json": {},
                "checksum": None,
                "last_key": None,
            }
        )
    db_session.add_all(
        [
            SettlementProjectionGeneration(
                generation_id=root_id,
                generation_kind="legacy_root",
                projection_name="settlement",
                state="superseded",
                input_fingerprint="c" * 64,
                lineage_depth=0,
                checkpoint_json={},
                manifest_checksum=bootstrap._manifest_checksum([]),
                source_input_json={},
            ),
            SettlementProjectionGeneration(
                generation_id=head_id,
                base_generation_id=root_id,
                generation_kind="lineage",
                projection_name="settlement",
                state="published",
                input_fingerprint="d" * 64,
                lineage_depth=1,
                checkpoint_json={},
                manifest_checksum=bootstrap._manifest_checksum(manifests),
                source_input_json={},
            ),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            SettlementProjectionPartitionManifest(
                generation_id=head_id,
                published_at=datetime.now(timezone.utc),
                **manifest,
            )
            for manifest in manifests
        ]
    )
    db_session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id=head_id
        )
    )
    db_session.commit()
    return {"root": root_id, "head": head_id}


def test_task3c_keyset_batches_are_400_bounded_and_dml_is_control_only(
    db_session: Session, monkeypatch
):
    ids = _seed_task3c_many_tombstones(
        db_session, prefix="task3c-bounded", count=401
    )
    batch_sizes: list[int] = []
    original_upsert = bootstrap._upsert_compaction_manifests

    def capture_upsert(session, generation_id, payloads):
        batch_sizes.append(len(payloads))
        return original_upsert(session, generation_id, payloads)

    monkeypatch.setattr(bootstrap, "_upsert_compaction_manifests", capture_upsert)
    dml_targets: list[str] = []
    max_bind_count = 0
    dml_re = re.compile(
        r"^(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([\"`\[]?[A-Z0-9_.]+[\"`\]]?)"
    )
    bind = db_session.get_bind()

    def capture_sql(_conn, _cursor, statement, parameters, _context, _executemany):
        nonlocal max_bind_count
        normalized = re.sub(r"\s+", " ", statement.strip()).upper()
        if isinstance(parameters, (tuple, list, dict)):
            max_bind_count = max(max_bind_count, len(parameters))
        match = dml_re.match(normalized)
        if match is not None:
            dml_targets.append(match.group(1).strip('"`[]').split(".")[-1].lower())

    event.listen(bind, "before_cursor_execute", capture_sql)
    try:
        result = compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(batch_size=400),
            resource_limits=_limits(
                rows=500, write=10_000_000, wal=20_000_000, headroom=100_000_000
            ),
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture_sql)

    assert result.status == "ready"
    assert result.partition_count == 401
    assert result.batch_count == 2
    assert batch_sizes == [400, 1]
    assert max_bind_count < 999
    assert set(dml_targets) == {
        "settlement_projection_generation",
        "settlement_projection_compaction_closure",
        "settlement_projection_partition_manifest",
    }


def _seed_task3c_all_artifacts(db_session: Session, *, prefix: str) -> dict[str, str]:
    fixture = _seed_full_authority_fixture(db_session, prefix=prefix)
    base_id = fixture["base_generation_id"]
    head_id = f"{prefix}-lineage-head"
    db_session.add(
        SettlementRankingOverlay(
            generation_id=base_id,
            base_generation_id=None,
            period_type=2,
            period_key="2026-08",
            store_id=fixture["store_id"],
            store_name=f"{prefix.title()} Store",
            product_scope="all",
            product_type="all",
            partition_key="cumulative:2026-08",
            promotion_net_fee_cent=150,
            management_net_fee_cent=50,
            net_settlement_reference_cent=100,
            projection_run_id=f"{prefix}-ranking-cumulative-overlay",
            month="2026-08",
            checksum="c" * 64,
        )
    )
    score_key = bootstrap.canonical_score_partition_key(
        date(2026, 8, 1), fixture["rule_version_id"], fixture["store_id"]
    )
    manifests = [
        {
            "artifact": "monthly",
            "partition_key": "2026-08",
            "owner_state": "owned",
            "source_kind": "overlay",
            "data_generation_id": base_id,
            "base_generation_id": None,
            "row_count": 1,
            "amount_total_cent": 100,
            "status_counts_json": {"1": 1},
            "checksum": "1" * 64,
            "last_key": None,
        },
        {
            "artifact": "ranking",
            "partition_key": "monthly:2026-08",
            "owner_state": "owned",
            "source_kind": "overlay",
            "data_generation_id": base_id,
            "base_generation_id": None,
            "row_count": 1,
            "amount_total_cent": 100,
            "status_counts_json": {},
            "checksum": "2" * 64,
            "last_key": None,
        },
        {
            "artifact": "ranking",
            "partition_key": "cumulative:2026-08",
            "owner_state": "owned",
            "source_kind": "overlay",
            "data_generation_id": base_id,
            "base_generation_id": None,
            "row_count": 1,
            "amount_total_cent": 100,
            "status_counts_json": {},
            "checksum": "4" * 64,
            "last_key": None,
        },
        {
            "artifact": "score",
            "partition_key": score_key,
            "owner_state": "owned",
            "source_kind": "overlay",
            "data_generation_id": base_id,
            "base_generation_id": None,
            "row_count": 1,
            "amount_total_cent": 0,
            "status_counts_json": {},
            "checksum": "3" * 64,
            "last_key": None,
        },
    ]
    base = db_session.get(SettlementProjectionGeneration, base_id)
    assert base is not None
    base.manifest_checksum = bootstrap._manifest_checksum(manifests)
    db_session.add_all(
        [
            SettlementProjectionPartitionManifest(
                generation_id=base_id,
                published_at=datetime.now(timezone.utc),
                **manifest,
            )
            for manifest in manifests
        ]
    )
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=head_id,
            base_generation_id=base_id,
            generation_kind="lineage",
            projection_name="settlement",
            state="published",
            input_fingerprint="e" * 64,
            lineage_depth=1,
            checkpoint_json={},
            manifest_checksum=bootstrap._manifest_checksum([]),
            source_input_json={},
        )
    )
    db_session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id=head_id
        )
    )
    db_session.commit()
    return {**fixture, "head": head_id, "score_key": score_key}


def test_task3c_all_artifacts_copy_metadata_only_and_resolve_original_sources(
    db_session: Session,
):
    ids = _seed_task3c_all_artifacts(db_session, prefix="task3c-artifacts")
    authority_tables = (
        "agg_store_monthly_settlement",
        "agg_store_ranking",
        "store_score_snapshot_runs",
        "store_score_snapshots",
        "settlement_monthly_overlay",
        "settlement_ranking_overlay",
        "store_score_snapshot_generation",
        "settlement_order_details",
        "settlement_fee_result",
        "settlement_fee_result_current",
        "settlement_fee_adjustment",
        "settlement_statement",
        "settlement_statement_line",
        "settlement_statement_entry",
    )
    with _factory(db_session)() as snapshot_session:
        authority_before = _value_snapshot(snapshot_session, authority_tables)
    business_before = (
        db_session.scalar(select(func.count()).select_from(SettlementMonthlyOverlay)),
        db_session.scalar(select(func.count()).select_from(SettlementRankingOverlay)),
        db_session.scalar(select(func.count()).select_from(StoreScoreSnapshotGeneration)),
    )
    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(),
        resource_limits=_limits(rows=10, write=1_000_000, wal=2_000_000),
    )
    assert result.status == "ready"
    compact_manifests = db_session.scalars(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == result.generation_id
        )
    ).all()
    assert {row.artifact for row in compact_manifests} == {
        "monthly",
        "ranking",
        "score",
    }
    assert all(
        row.data_generation_id == ids["base_generation_id"]
        and row.reference_head_generation_id == result.generation_id
        for row in compact_manifests
    )
    business_after = (
        db_session.scalar(select(func.count()).select_from(SettlementMonthlyOverlay)),
        db_session.scalar(select(func.count()).select_from(SettlementRankingOverlay)),
        db_session.scalar(select(func.count()).select_from(StoreScoreSnapshotGeneration)),
    )
    assert business_after == business_before
    with _factory(db_session)() as snapshot_session:
        assert _value_snapshot(snapshot_session, authority_tables) == authority_before

    compact = db_session.get(SettlementProjectionGeneration, result.generation_id)
    pointer = db_session.get(SettlementProjectionActive, "settlement")
    assert compact is not None and pointer is not None
    compact.state = "published"
    compact.published_at = datetime.now(timezone.utc)
    pointer.generation_id = result.generation_id
    db_session.commit()
    requested = {
        "monthly": ["2026-08"],
        "ranking": ["monthly:2026-08", "cumulative:2026-08"],
        "score": [ids["score_key"]],
    }
    for artifact, partition_keys in requested.items():
        resolutions = resolve_projection_partitions(
            db_session,
            artifact=artifact,
            partition_keys=partition_keys,
            pinned_generation_id=result.generation_id,
        )
        for partition_key in partition_keys:
            resolved = resolutions[partition_key]
            assert resolved.lineage_depth == 0
            assert resolved.actual_data_generation_id == ids["base_generation_id"]
            assert resolved.source_generation_ids == frozenset(
                {ids["base_generation_id"]}
            )


def test_task3c_expected_base_mismatch_fails_before_compaction_write(
    db_session: Session,
):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-base-mismatch")
    pointer = db_session.get(SettlementProjectionActive, "settlement")
    assert pointer is not None
    pointer.generation_id = ids["root"]
    root = db_session.get(SettlementProjectionGeneration, ids["root"])
    assert root is not None
    root.state = "published"
    db_session.commit()
    before = db_session.scalar(
        select(func.count()).select_from(SettlementProjectionGeneration)
    )

    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="active|base"):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(),
            resource_limits=_limits(rows=10),
        )

    assert db_session.scalar(
        select(func.count()).select_from(SettlementProjectionGeneration)
    ) == before
    assert db_session.scalar(
        select(func.count()).select_from(SettlementProjectionCompactionClosure)
    ) == 0


def test_task3c_preflight_and_verify_retain_only_bounded_payload_pages(
    db_session: Session, monkeypatch
):
    ids = _seed_task3c_many_tombstones(
        db_session, prefix="task3c-streaming", count=101
    )
    original = bootstrap._compaction_source_payload_page
    references: list[weakref.ReferenceType[dict]] = []
    peak_live = 0

    class TrackedPayload(dict):
        pass

    def tracked_payload_page(*args, **kwargs):
        nonlocal peak_live
        gc.collect()
        peak_live = max(peak_live, sum(ref() is not None for ref in references))
        payloads = [TrackedPayload(row) for row in original(*args, **kwargs)]
        references.extend(weakref.ref(row) for row in payloads)
        peak_live = max(peak_live, sum(ref() is not None for ref in references))
        return payloads

    monkeypatch.setattr(
        bootstrap, "_compaction_source_payload_page", tracked_payload_page
    )
    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(batch_size=5),
        resource_limits=_limits(
            rows=200, write=10_000_000, wal=20_000_000, headroom=100_000_000
        ),
    )

    assert result.status == "ready"
    # A source page, an output page, and the just-committed terminal page may
    # briefly coexist.  Retaining the complete 101-row plan before the resource
    # gate would exceed this page-proportional bound.
    assert peak_live <= 15


def test_task3c_same_root_contenders_converge_to_ready_and_already_ready(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="task3c-same-root-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{directory}/compaction.sqlite",
            connect_args={"check_same_thread": False, "timeout": 30},
            isolation_level="AUTOCOMMIT",
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as seed:
            ids = _seed_task3c_many_tombstones(
                seed, prefix="task3c-contenders", count=3
            )

        barrier = threading.Barrier(2)
        original_verify = bootstrap._verify_compaction_ready

        def verify_then_release_together(*args, **kwargs):
            checkpoint = original_verify(*args, **kwargs)
            barrier.wait(timeout=15)
            return checkpoint

        monkeypatch.setattr(
            bootstrap, "_verify_compaction_ready", verify_then_release_together
        )

        def run_compaction():
            return compact_projection_metadata(
                factory,
                base_generation_id=ids["head"],
                threshold_config=_compaction_threshold(batch_size=1),
                resource_limits=_limits(
                    rows=10,
                    write=1_000_000,
                    wal=2_000_000,
                    headroom=10_000_000,
                ),
            )

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _index: run_compaction(), range(2)))
            assert sorted(result.status for result in results) == [
                "already_ready",
                "ready",
            ]
            assert len({result.generation_id for result in results}) == 1
            with factory() as check:
                compact_rows = check.scalars(
                    select(SettlementProjectionGeneration).where(
                        SettlementProjectionGeneration.generation_kind == "compact"
                    )
                ).all()
                assert len(compact_rows) == 1
                assert compact_rows[0].state == "ready"
                assert compact_rows[0].failure_code is None
        finally:
            engine.dispose()


def test_task3c_source_manifest_digest_drift_fails_before_compaction_write(
    db_session: Session,
):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-source-drift")
    source_manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == ids["head"],
            SettlementProjectionPartitionManifest.source_kind == "overlay",
        )
    )
    assert source_manifest is not None
    source_manifest.amount_total_cent += 1
    db_session.commit()

    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError, match="manifest|checksum|digest"
    ):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(),
            resource_limits=_limits(rows=10),
        )

    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementProjectionGeneration)
        .where(SettlementProjectionGeneration.generation_kind == "compact")
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(SettlementProjectionCompactionClosure)
    ) == 0


@pytest.mark.parametrize(
    ("base_generation_id", "threshold", "limits", "expected_code"),
    [
        ("", _compaction_threshold(), _limits(), "invalid_base_generation_id"),
        (" spaced ", _compaction_threshold(), _limits(), "invalid_base_generation_id"),
        ("base", object(), _limits(), "invalid_threshold_config"),
        (
            "base",
            CompactionThresholdConfig(minimum_lineage_depth=0, batch_size=1),
            _limits(),
            "invalid_threshold_config",
        ),
        (
            "base",
            CompactionThresholdConfig(minimum_lineage_depth=1, batch_size=401),
            _limits(),
            "invalid_threshold_config",
        ),
        (
            "base",
            _compaction_threshold(),
            ResourceGateConfig(-1, 1, 1, 1, 0),
            "invalid_resource_config",
        ),
    ],
)
def test_task3c_invalid_arguments_are_zero_write_resource_guards(
    db_session: Session,
    base_generation_id,
    threshold,
    limits,
    expected_code: str,
):
    before = (
        db_session.scalar(select(func.count()).select_from(SettlementProjectionGeneration)),
        db_session.scalar(
            select(func.count()).select_from(SettlementProjectionCompactionClosure)
        ),
        db_session.scalar(
            select(func.count()).select_from(SettlementProjectionPartitionManifest)
        ),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionActive)),
    )
    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=base_generation_id,
        threshold_config=threshold,
        resource_limits=limits,
    )
    after = (
        db_session.scalar(select(func.count()).select_from(SettlementProjectionGeneration)),
        db_session.scalar(
            select(func.count()).select_from(SettlementProjectionCompactionClosure)
        ),
        db_session.scalar(
            select(func.count()).select_from(SettlementProjectionPartitionManifest)
        ),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionActive)),
    )
    assert result.status == "resource_guard"
    assert result.failure_code == expected_code
    assert after == before


def test_task3c_committed_prefix_corruption_fails_closed_and_marks_generation_failed(
    db_session: Session,
):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-prefix-drift")
    state = {"commits": 0, "crashed": False}

    class CrashAfterFirstPageSession(Session):
        def commit(self):  # type: ignore[override]
            result = super().commit()
            state["commits"] += 1
            if state["commits"] == 2 and not state["crashed"]:
                state["crashed"] = True
                raise RuntimeError("task3c injected prefix crash")
            return result

    crashing_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        future=True,
        class_=CrashAfterFirstPageSession,
    )
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError, match="compaction failed"):
        compact_projection_metadata(
            crashing_factory,
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(batch_size=1),
            resource_limits=_limits(rows=10),
        )

    db_session.expire_all()
    compact = db_session.scalar(
        select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_kind == "compact"
        )
    )
    assert compact is not None and compact.state == "staging"
    prefix = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == compact.generation_id
        )
    )
    assert prefix is not None
    prefix.amount_total_cent += 1
    db_session.commit()

    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError, match="verification|manifest"
    ):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(batch_size=1),
            resource_limits=_limits(rows=10),
        )
    db_session.expire_all()
    failed = db_session.get(SettlementProjectionGeneration, compact.generation_id)
    assert failed is not None and failed.state == "failed"
    assert failed.failure_code == "compaction_failed"


def test_task3c_ready_closure_drift_fails_closed_and_marks_generation_failed(
    db_session: Session,
):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-closure-drift")
    first = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(),
        resource_limits=_limits(rows=10),
    )
    closure = db_session.scalar(
        select(SettlementProjectionCompactionClosure).where(
            SettlementProjectionCompactionClosure.compact_generation_id
            == first.generation_id
        )
    )
    assert closure is not None
    closure.source_digest = "0" * 64
    db_session.commit()

    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError, match="closure|metadata"
    ):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(),
            resource_limits=_limits(rows=10),
        )
    db_session.expire_all()
    failed = db_session.get(SettlementProjectionGeneration, first.generation_id)
    assert failed is not None and failed.state == "failed"
    assert failed.failure_code == "compaction_failed"


@pytest.mark.parametrize("corruption", ["incomplete", "nested_compact"])
def test_task3c_invalid_lineage_fails_before_compaction_write(
    db_session: Session, corruption: str
):
    ids = _seed_task3c_lineage(db_session, prefix=f"task3c-lineage-{corruption}")
    head = db_session.get(SettlementProjectionGeneration, ids["head"])
    root = db_session.get(SettlementProjectionGeneration, ids["root"])
    assert head is not None and root is not None
    if corruption == "incomplete":
        head.lineage_depth = 2
    else:
        root.generation_kind = "compact"
        root.compaction_base_generation_id = ids["head"]
    db_session.commit()
    before = (
        db_session.scalar(
            select(func.count())
            .select_from(SettlementProjectionGeneration)
            .where(SettlementProjectionGeneration.generation_kind == "compact")
        ),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionCompactionClosure)),
    )

    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError, match="incomplete|nested compact"
    ):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(),
            resource_limits=_limits(rows=10),
        )

    db_session.expire_all()
    after = (
        db_session.scalar(
            select(func.count())
            .select_from(SettlementProjectionGeneration)
            .where(SettlementProjectionGeneration.generation_kind == "compact")
        ),
        db_session.scalar(select(func.count()).select_from(SettlementProjectionCompactionClosure)),
    )
    assert after == before


def test_task3c_crash_after_initial_metadata_commit_resumes_same_generation(
    db_session: Session, monkeypatch
):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-initial-crash")
    original_upsert = bootstrap._upsert_compaction_manifests
    armed = {"value": True}

    def crash_before_first_page(session, generation_id, payloads):
        if armed["value"]:
            armed["value"] = False
            raise RuntimeError("injected crash after initial metadata commit")
        return original_upsert(session, generation_id, payloads)

    monkeypatch.setattr(
        bootstrap, "_upsert_compaction_manifests", crash_before_first_page
    )
    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError, match="metadata compaction failed"
    ):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(batch_size=1),
            resource_limits=_limits(rows=10),
        )
    compact = db_session.scalar(
        select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_kind == "compact"
        )
    )
    assert compact is not None and compact.state == "staging"
    generation_id = compact.generation_id
    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementProjectionCompactionClosure)
        .where(
            SettlementProjectionCompactionClosure.compact_generation_id
            == generation_id
        )
    ) == 2
    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementProjectionPartitionManifest)
        .where(SettlementProjectionPartitionManifest.generation_id == generation_id)
    ) == 0

    monkeypatch.setattr(bootstrap, "_upsert_compaction_manifests", original_upsert)
    resumed = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(batch_size=1),
        resource_limits=_limits(rows=10),
    )
    assert resumed.status == "ready"
    assert resumed.resumed is True
    assert resumed.generation_id == generation_id
    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementProjectionCompactionClosure)
        .where(
            SettlementProjectionCompactionClosure.compact_generation_id
            == generation_id
        )
    ) == 2


@pytest.mark.parametrize("missing_key", ["cursor", "effective_checksum", "batch_count"])
def test_task3c_ready_checkpoint_tamper_is_typed_and_marks_failed(
    db_session: Session, missing_key: str
):
    ids = _seed_task3c_lineage(
        db_session, prefix=f"task3c-checkpoint-{missing_key}"
    )
    first = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(),
        resource_limits=_limits(rows=10),
    )
    generation = db_session.get(SettlementProjectionGeneration, first.generation_id)
    assert generation is not None and generation.state == "ready"
    checkpoint = dict(generation.checkpoint_json)
    checkpoint.pop(missing_key)
    generation.checkpoint_json = checkpoint
    db_session.commit()

    with pytest.raises(
        bootstrap.LegacyProjectionBootstrapError, match="checkpoint|metadata"
    ):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(),
            resource_limits=_limits(rows=10),
        )
    db_session.expire_all()
    failed = db_session.get(SettlementProjectionGeneration, first.generation_id)
    assert failed is not None and failed.state == "failed"
    assert failed.failure_code == "compaction_failed"


def test_task3c_failed_cleanup_crash_rolls_back_then_retry_rebuilds(
    db_session: Session,
):
    ids = _seed_task3c_lineage(db_session, prefix="task3c-cleanup-crash")
    first = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(batch_size=1),
        resource_limits=_limits(rows=10),
    )
    manifest = db_session.scalar(
        select(SettlementProjectionPartitionManifest).where(
            SettlementProjectionPartitionManifest.generation_id == first.generation_id,
            SettlementProjectionPartitionManifest.source_kind == "overlay",
        )
    )
    assert manifest is not None
    manifest.amount_total_cent += 1
    db_session.commit()
    with pytest.raises(bootstrap.LegacyProjectionBootstrapError):
        compact_projection_metadata(
            _factory(db_session),
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(batch_size=1),
            resource_limits=_limits(rows=10),
        )
    db_session.expire_all()
    failed = db_session.get(SettlementProjectionGeneration, first.generation_id)
    assert failed is not None and failed.state == "failed"
    before = _r5_control_snapshot(db_session)
    armed = {"value": True}
    bind = db_session.get_bind()

    def crash_after_cleanup_delete(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ):
        if (
            armed["value"]
            and statement.strip().upper().startswith(
                "DELETE FROM SETTLEMENT_PROJECTION_PARTITION_MANIFEST"
            )
        ):
            armed["value"] = False
            raise RuntimeError("injected compaction cleanup crash")

    event.listen(bind, "after_cursor_execute", crash_after_cleanup_delete)
    try:
        with pytest.raises(
            bootstrap.LegacyProjectionBootstrapError, match="metadata compaction failed"
        ):
            compact_projection_metadata(
                _factory(db_session),
                base_generation_id=ids["head"],
                threshold_config=_compaction_threshold(batch_size=1),
                resource_limits=_limits(rows=10),
            )
    finally:
        event.remove(bind, "after_cursor_execute", crash_after_cleanup_delete)
    db_session.expire_all()
    assert _r5_control_snapshot(db_session) == before

    rebuilt = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=_compaction_threshold(batch_size=1),
        resource_limits=_limits(rows=10),
    )
    assert rebuilt.status == "ready"
    assert rebuilt.generation_id == first.generation_id
    assert rebuilt.resumed is True


def test_task3c_stale_failed_cleanup_cannot_mutate_peer_ready_winner(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="task3c-stale-cleanup-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{directory}/compaction.sqlite",
            connect_args={"check_same_thread": False, "timeout": 30},
            isolation_level="AUTOCOMMIT",
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as seed:
            ids = _seed_task3c_lineage(seed, prefix="task3c-stale-cleanup")
        first = compact_projection_metadata(
            factory,
            base_generation_id=ids["head"],
            threshold_config=_compaction_threshold(batch_size=1),
            resource_limits=_limits(rows=10),
        )
        with factory() as corrupt:
            manifest = corrupt.scalar(
                select(SettlementProjectionPartitionManifest).where(
                    SettlementProjectionPartitionManifest.generation_id
                    == first.generation_id,
                    SettlementProjectionPartitionManifest.source_kind == "overlay",
                )
            )
            assert manifest is not None
            manifest.amount_total_cent += 1
            corrupt.commit()
        with pytest.raises(bootstrap.LegacyProjectionBootstrapError):
            compact_projection_metadata(
                factory,
                base_generation_id=ids["head"],
                threshold_config=_compaction_threshold(batch_size=1),
                resource_limits=_limits(rows=10),
            )

        lineage_rows = bootstrap._load_compaction_lineage(factory, ids["head"])
        summary = bootstrap._summarize_compaction_plan(
            factory, ids["head"], lineage_rows, 1
        )
        resource, guard = bootstrap._compaction_resource(
            summary.manifest_rows, len(lineage_rows), _limits(rows=10)
        )
        assert guard is None
        fingerprint = bootstrap._compaction_fingerprint(
            ids["head"],
            str(lineage_rows[0]["manifest_checksum"]),
            summary.effective_checksum,
        )
        with factory() as stale_session:
            stale_generation = stale_session.get(
                SettlementProjectionGeneration, first.generation_id
            )
            assert stale_generation is not None and stale_generation.state == "failed"
            stale_session.expunge(stale_generation)

        paused = threading.Event()
        release = threading.Event()
        stale_thread = {"id": None}
        armed = {"value": True}

        def pause_stale_before_writer_lock(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ):
            if (
                armed["value"]
                and threading.get_ident() == stale_thread["id"]
                and statement.strip().upper() == "BEGIN IMMEDIATE"
            ):
                armed["value"] = False
                paused.set()
                assert release.wait(timeout=15)

        event.listen(engine, "before_cursor_execute", pause_stale_before_writer_lock)
        try:
            def stale_cleanup():
                stale_thread["id"] = threading.get_ident()
                return bootstrap._cleanup_failed_compaction(
                    factory,
                    stale_generation,
                    base_generation_id=ids["head"],
                    lineage_rows=lineage_rows,
                    effective_checksum=summary.effective_checksum,
                    resource=resource,
                    batch_size=1,
                    fingerprint=fingerprint,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                stale_future = executor.submit(stale_cleanup)
                assert paused.wait(timeout=15)
                peer_future = executor.submit(
                    compact_projection_metadata,
                    factory,
                    base_generation_id=ids["head"],
                    threshold_config=_compaction_threshold(batch_size=1),
                    resource_limits=_limits(rows=10),
                )
                peer = peer_future.result(timeout=15)
                assert peer.status == "ready"
                with factory() as check:
                    winner_snapshot = _r5_control_snapshot(check)
                release.set()
                stale_result = stale_future.result(timeout=15)
                assert stale_result.state == "ready"
            with factory() as check:
                assert _r5_control_snapshot(check) == winner_snapshot
        finally:
            release.set()
            event.remove(engine, "before_cursor_execute", pause_stale_before_writer_lock)
            engine.dispose()
