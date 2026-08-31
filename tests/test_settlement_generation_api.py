from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.routes._data import DashboardDataStore
from apps.api.dy_api.routes import admin as admin_routes
from apps.api.dy_api.routes.admin import (
    _score_fact_batches,
    _score_sidecar_rule_map,
    list_store_score_snapshots,
    _store_score_run_payload,
    _store_score_snapshot_payload,
)
from apps.api.dy_api.schemas import StoreScoreSnapshotRow, StoreScoreSnapshotRunData
from apps.worker.projection_lineage import (
    MAX_LINEAGE_DEPTH,
    MAX_PARTITION_KEYS,
    LineageError,
    active_generation_id,
    canonical_score_partition_key,
    resolve_projection_partitions,
)
from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    AggStoreRanking,
    DimStore,
    RawDouyinVerifyRecord,
    SettlementMonthlyOverlay,
    SettlementOrderDetail,
    SettlementRankingOverlay,
    StoreScoreSnapshot,
    StoreScoreSnapshotGeneration,
    StoreScoreSnapshotRun,
)


def _generation(
    db_session,
    generation_id: str,
    *,
    base_generation_id: str | None = None,
    state: str = "published",
    depth: int = 0,
) -> None:
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_generation
                (generation_id, base_generation_id, projection_name, state,
                 input_fingerprint, lineage_depth, estimated_write_rows,
                 estimated_write_bytes, estimated_wal_bytes,
                 estimated_disk_headroom_bytes, checkpoint_json, source_input_json,
                 created_at)
            VALUES (:generation_id, :base_generation_id, 'settlement', :state,
                    :fingerprint, :depth, 0, 0, 0, 0, '{}', '{}', :created_at)
            """
        ),
        {
            "generation_id": generation_id,
            "base_generation_id": base_generation_id,
            "state": state,
            "fingerprint": f"fingerprint-{generation_id}",
            "depth": depth,
            "created_at": datetime.now(timezone.utc),
        },
    )


def _manifest(
    db_session,
    generation_id: str,
    artifact: str,
    partition_key: str,
    *,
    owner_state: str = "owned",
    source_kind: str = "overlay",
    data_generation_id: str | None = None,
    base_generation_id: str | None = None,
) -> None:
    if base_generation_id is None:
        base_generation_id = db_session.execute(
            text(
                "SELECT base_generation_id FROM settlement_projection_generation "
                "WHERE generation_id = :generation_id"
            ),
            {"generation_id": generation_id},
        ).scalar_one_or_none()
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_partition_manifest
                (generation_id, artifact, partition_key, owner_state, source_kind,
                 data_generation_id, base_generation_id, row_count, amount_total_cent,
                 status_counts_json, created_at)
            VALUES (:generation_id, :artifact, :partition_key, :owner_state,
                    :source_kind, :data_generation_id, :base_generation_id,
                    0, 0, '{}', :created_at)
            """
        ),
        {
            "generation_id": generation_id,
            "artifact": artifact,
            "partition_key": partition_key,
            "owner_state": owner_state,
            "source_kind": source_kind,
            "data_generation_id": data_generation_id,
            "base_generation_id": base_generation_id,
            "created_at": datetime.now(timezone.utc),
        },
    )


_DIRECT_MONTHLY_METRIC_KEYS = {
    "estimated_receivable_commission_cent",
    "commissionable_total_cent",
    "estimated_payable_commission_cent",
}


def _assert_direct_monthly_metrics(
    result: dict[str, object],
    *,
    receivable: int = 0,
    commissionable: int = 0,
    payable: int = 0,
) -> None:
    assert set(result["metrics"]) == _DIRECT_MONTHLY_METRIC_KEYS  # type: ignore[index]
    assert result["metrics"] == {  # type: ignore[index]
        "estimated_receivable_commission_cent": receivable,
        "commissionable_total_cent": commissionable,
        "estimated_payable_commission_cent": payable,
    }


def test_null_pointer_resolves_legacy_root_and_pydantic_fields(db_session) -> None:
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_active (projection_name, generation_id)
            VALUES ('settlement', NULL)
            """
        )
    )
    db_session.commit()

    assert active_generation_id(db_session) is None
    resolved = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["2026-08"],
        pinned_generation_id=None,
    )
    result = resolved["2026-08"]
    assert result.source_kind == "legacy_root"
    assert result.actual_data_generation_id is None

    run = StoreScoreSnapshotRunData(
        snapshot_run_id="run-1",
        snapshot_date=date(2026, 8, 1),
        run_mode="manual",
        window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        rule_version_id="rule-1",
    )
    row = StoreScoreSnapshotRow(
        store_id="store-1",
        conversion_value_source="observed",
        follow_24h_value_source="observed",
        rule_version_id="rule-1",
    )
    assert run.model_dump()["rule_version_id"] == "rule-1"
    assert row.model_dump()["rule_version_id"] == "rule-1"


def test_lineage_nearest_owner_overlay_legacy_and_tombstone(db_session) -> None:
    _generation(db_session, "g0")
    _generation(db_session, "g1", base_generation_id="g0", depth=1)
    _generation(db_session, "g2", base_generation_id="g1", depth=2)
    _manifest(db_session, "g0", "monthly", "2026-08", source_kind="legacy_root")
    _manifest(
        db_session,
        "g1",
        "monthly",
        "2026-08",
        source_kind="overlay",
        data_generation_id="g1",
    )
    _manifest(
        db_session,
        "g2",
        "monthly",
        "2026-09",
        owner_state="tombstone",
        source_kind="tombstone",
    )
    db_session.commit()

    resolved = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["2026-08", "2026-09", "2026-10"],
        pinned_generation_id="g2",
    )
    assert resolved["2026-08"].nearest_manifest_owner_generation == "g1"
    assert resolved["2026-08"].actual_data_generation_id == "g1"
    assert resolved["2026-09"].source_kind == "tombstone"
    assert resolved["2026-10"].source_kind == "legacy_root"


def test_lineage_query_count_is_bounded_by_partition_count(db_session) -> None:
    _generation(db_session, "g0")
    _manifest(db_session, "g0", "monthly", "2026-08", source_kind="legacy_root")
    _manifest(db_session, "g0", "monthly", "2026-09", source_kind="legacy_root")
    db_session.commit()
    statements: list[str] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "settlement_projection" in statement:
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=[f"2026-{month:02d}" for month in range(1, 13)],
            pinned_generation_id="g0",
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)
    assert len(statements) <= 3


def test_lineage_corruption_fails_closed(db_session) -> None:
    _generation(db_session, "g0", state="staging")
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_active (projection_name, generation_id)
            VALUES ('settlement', 'g0')
            """
        )
    )
    db_session.commit()
    with pytest.raises(LineageError):
        active_generation_id(db_session)


def test_overlay_manifest_with_missing_rows_fails_closed(db_session) -> None:
    _generation(db_session, "g0")
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_active (projection_name, generation_id)
            VALUES ('settlement', 'g0')
            """
        )
    )
    _manifest(db_session, "g0", "monthly", "2026-08", data_generation_id="g0")
    db_session.execute(
        text(
            """
            UPDATE settlement_projection_partition_manifest
            SET row_count = 1
            WHERE generation_id = 'g0' AND artifact = 'monthly' AND partition_key = '2026-08'
            """
        )
    )
    db_session.commit()
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g0",
        )


def test_score_payload_keeps_optional_rule_version_id() -> None:
    run = SimpleNamespace(
        snapshot_run_id="run-1",
        snapshot_date=date(2026, 8, 1),
        run_mode="manual",
        window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
        candidate_store_count=1,
        snapshot_count=1,
        triggered_by="test",
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        config_json={"rule_version_id": "rule-1"},
    )
    row = SimpleNamespace(
        store_id="store-1",
        city_code=None,
        conversion_numerator=1,
        conversion_denominator=1,
        conversion_rate=1,
        conversion_value_source="observed",
        follow_24h_numerator=1,
        follow_24h_denominator=1,
        follow_24h_rate=1,
        follow_24h_value_source="observed",
        store_weight=1,
        composite_score=1,
        config_json={"rule_version_id": "rule-1"},
    )
    assert _store_score_run_payload(run)["rule_version_id"] == "rule-1"
    assert _store_score_snapshot_payload(row)["rule_version_id"] == "rule-1"


def test_pinned_aggregate_readers_do_not_mix_root_and_overlay(db_session) -> None:
    db_session.add(DimStore(store_id="store-1", store_name="Store 1"))
    db_session.add(
        AggStoreRanking(
            period_type=1,
            period_key="2026-08",
            month="2026-08",
            store_id="store-1",
            store_name="Legacy Store",
            product_scope="all",
            product_type="all",
            sales_order_count=1,
            sales_amount_cent=100,
            verified_order_count=1,
            verified_amount_cent=100,
            promotion_net_fee_cent=10,
            management_net_fee_cent=2,
            net_settlement_reference_cent=8,
            projection_run_id="legacy",
        )
    )
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="store-1",
            product_scope="all",
            product_type="all",
            sales_order_count=2,
            sales_amount_cent=240,
            verified_order_count=1,
            verified_amount_cent=120,
            promotion_base_cent=30,
            promotion_original_fee_cent=26,
            promotion_adjustment_fee_cent=-2,
            promotion_net_fee_cent=24,
            management_base_cent=17,
            management_original_fee_cent=13,
            management_adjustment_fee_cent=-3,
            management_net_fee_cent=10,
            statement_status=1,
            projection_run_id="legacy",
            estimated_receivable_commission_cent=10,
            commissionable_total_cent=100,
            estimated_payable_commission_cent=2,
        )
    )
    _generation(db_session, "g1")
    _generation(db_session, "g2")
    _manifest(db_session, "g1", "ranking", "monthly:2026-08", data_generation_id="g1")
    _manifest(db_session, "g1", "monthly", "2026-08", data_generation_id="g1")
    db_session.add(
        SettlementRankingOverlay(
            generation_id="g1",
            period_type=1,
            period_key="2026-08",
            month="2026-08",
            partition_key="monthly:2026-08",
            store_id="store-1",
            store_name="Overlay Store",
            product_scope="all",
            product_type="all",
            sales_order_count=9,
            sales_amount_cent=900,
            verified_order_count=9,
            verified_amount_cent=900,
            promotion_net_fee_cent=90,
            management_net_fee_cent=9,
            net_settlement_reference_cent=81,
            projection_run_id="g1",
        )
    )
    db_session.add(
        SettlementMonthlyOverlay(
            generation_id="g1",
            month="2026-08",
            partition_key="2026-08",
            store_id="store-1",
            product_scope="all",
            product_type="all",
            sales_order_count=9,
            sales_amount_cent=900,
            verified_order_count=8,
            verified_amount_cent=720,
            promotion_base_cent=93,
            promotion_original_fee_cent=87,
            promotion_adjustment_fee_cent=4,
            promotion_net_fee_cent=91,
            management_base_cent=26,
            management_original_fee_cent=21,
            management_adjustment_fee_cent=3,
            management_net_fee_cent=24,
            statement_status=1,
            projection_run_id="g1",
            estimated_receivable_commission_cent=90,
            commissionable_total_cent=900,
            estimated_payable_commission_cent=9,
        )
    )
    db_session.flush()
    legacy_report = DashboardDataStore(db_session).monthly_settlement_report(
        {
            "store_id": "store-1",
            "month": "2026-08",
            "product_scope": "all",
            "product_type": "all",
        }
    )
    assert legacy_report["metrics"]["sales_order_count"] == 2
    assert legacy_report["metrics"] == {
        "sales_order_count": 2,
        "sales_amount_cent": 240,
        "verified_order_count": 1,
        "verified_amount_cent": 120,
        "promotion_base_cent": 30,
        "promotion_original_fee_cent": 26,
        "promotion_adjustment_fee_cent": -2,
        "promotion_net_fee_cent": 24,
        "management_base_cent": 17,
        "management_original_fee_cent": 13,
        "management_adjustment_fee_cent": -3,
        "management_net_fee_cent": 10,
        "net_settlement_reference_cent": 14,
    }
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) VALUES ('settlement', 'g1')"
        )
    )
    db_session.commit()

    store = DashboardDataStore(db_session)
    ranking = store.store_ranking_report(
        {
            "period_type": "MONTHLY",
            "period_key": "2026-08",
            "product_scope": "all",
            "product_type": "all",
            "page": 1,
            "page_size": 20,
            "sort_by": "SALES_AMOUNT",
            "sort_order": "DESC",
        }
    )
    assert ranking["totals"]["sales_order_count"] == 9
    pinned_report = store.monthly_settlement_report(
        {
            "store_id": "store-1",
            "month": "2026-08",
            "product_scope": "all",
            "product_type": "all",
        }
    )
    assert pinned_report["metrics"]["sales_order_count"] == 9
    assert pinned_report["metrics"]["sales_amount_cent"] == 900
    assert pinned_report["metrics"]["promotion_net_fee_cent"] == 91
    assert pinned_report["metrics"] == {
        "sales_order_count": 9,
        "sales_amount_cent": 900,
        "verified_order_count": 8,
        "verified_amount_cent": 720,
        "promotion_base_cent": 93,
        "promotion_original_fee_cent": 87,
        "promotion_adjustment_fee_cent": 4,
        "promotion_net_fee_cent": 91,
        "management_base_cent": 26,
        "management_original_fee_cent": 21,
        "management_adjustment_fee_cent": 3,
        "management_net_fee_cent": 24,
        "net_settlement_reference_cent": 67,
    }
    monthly = store.monthly_settlement(
        store_id="store-1", month="2026-08", product_type="all", product_scope="all"
    )
    _assert_direct_monthly_metrics(monthly, receivable=90, commissionable=900, payable=9)

    db_session.execute(
        text("UPDATE settlement_projection_active SET generation_id = 'g2' WHERE projection_name = 'settlement'")
    )
    db_session.commit()
    assert store.store_ranking_totals(month="2026-08", product_type="all")["sales_order_count"] == 9


def test_score_request_rule_filter_and_snapshot_run_priority(db_session) -> None:
    _generation(db_session, "g-score")
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) VALUES ('settlement', 'g-score')"
        )
    )
    db_session.add(DimStore(store_id="score-store", store_name="Score Store"))
    for run_id, computed_at, rule_id, score in (
        ("run-old", datetime(2026, 8, 2, tzinfo=timezone.utc), "rule-a", 1),
        ("run-new", datetime(2026, 8, 3, tzinfo=timezone.utc), "rule-b", 2),
    ):
        db_session.add(
            StoreScoreSnapshotRun(
                snapshot_run_id=run_id,
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                candidate_store_count=1,
                snapshot_count=1,
                config_json={"rule_version_id": rule_id},
                computed_at=computed_at,
            )
        )
        db_session.add(
            StoreScoreSnapshot(
                snapshot_id=f"snapshot-{run_id}",
                snapshot_run_id=run_id,
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                store_id="score-store",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                conversion_value_source="observed",
                follow_24h_value_source="observed",
                composite_score=score,
                config_json={"rule_version_id": rule_id},
            )
        )
        db_session.add(
            StoreScoreSnapshotGeneration(
                generation_id="g-score",
                snapshot_run_id=run_id,
                store_id="score-store",
                rule_version_id=rule_id,
                snapshot_date=date(2026, 8, 1),
                partition_key=canonical_score_partition_key(
                    date(2026, 8, 1), rule_id, "score-store"
                ),
            )
        )
        _manifest(
            db_session,
            "g-score",
            "score",
            canonical_score_partition_key(date(2026, 8, 1), rule_id, "score-store"),
            data_generation_id="g-score",
        )
    db_session.commit()
    store = SimpleNamespace(available=True, session=db_session)

    filtered = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        rule_version_id="rule-a",
        page=1,
        page_size=20,
        _username="admin",
        store=store,
    )
    assert filtered["data"]["run"]["snapshot_run_id"] == "run-old"
    assert filtered["data"]["run"]["rule_version_id"] == "rule-a"
    exact_mismatch = list_store_score_snapshots(
        snapshot_run_id="run-new",
        rule_version_id="rule-a",
        page=1,
        page_size=20,
        _username="admin",
        store=store,
    )
    assert exact_mismatch["data"]["run"] is None


def test_active_lineage_month_lists_ignore_unrelated_generation_manifests(db_session) -> None:
    _generation(db_session, "g-active")
    _generation(db_session, "g-staging", state="staging")
    _manifest(
        db_session,
        "g-staging",
        "monthly",
        "2099-01",
        data_generation_id="g-staging",
    )
    _manifest(
        db_session,
        "g-staging",
        "ranking",
        "monthly:2099-02",
        data_generation_id="g-staging",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-active')"
        )
    )
    db_session.commit()
    store = DashboardDataStore(db_session)
    assert "2099-01" not in store.list_statement_months()
    assert "2099-02" not in store.list_sale_months()


def _insert_score_fixture(
    db_session,
    *,
    generation_id: str,
    run_id: str,
    rule_id: str,
    score: int,
    snapshot_date: date = date(2026, 8, 1),
    computed_at: datetime = datetime(2026, 8, 2, tzinfo=timezone.utc),
) -> str:
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id=run_id,
            snapshot_date=snapshot_date,
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            candidate_store_count=1,
            snapshot_count=1,
            config_json={"rule_version_id": rule_id},
            computed_at=computed_at,
        )
    )
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id=f"snapshot-{run_id}",
            snapshot_run_id=run_id,
            snapshot_date=snapshot_date,
            run_mode="scheduled",
            store_id="score-store",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            conversion_value_source="observed",
            follow_24h_value_source="observed",
            composite_score=score,
            config_json={"rule_version_id": rule_id},
        )
    )
    partition_key = canonical_score_partition_key(snapshot_date, rule_id, "score-store")
    db_session.add(
        StoreScoreSnapshotGeneration(
            generation_id=generation_id,
            snapshot_run_id=run_id,
            store_id="score-store",
            rule_version_id=rule_id,
            snapshot_date=snapshot_date,
            partition_key=partition_key,
        )
    )
    return partition_key


def test_score_tombstone_hides_base_score_rows(db_session) -> None:
    _generation(db_session, "g-score-base")
    _generation(db_session, "g-score-active", base_generation_id="g-score-base", depth=1)
    partition_key = _insert_score_fixture(
        db_session,
        generation_id="g-score-base",
        run_id="run-tombstoned",
        rule_id="rule-tombstone",
        score=77,
    )
    _manifest(
        db_session,
        "g-score-base",
        "score",
        partition_key,
        data_generation_id="g-score-base",
    )
    _manifest(
        db_session,
        "g-score-active",
        "score",
        partition_key,
        owner_state="tombstone",
        source_kind="tombstone",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-score-active')"
        )
    )
    db_session.commit()
    store = SimpleNamespace(available=True, session=db_session)
    result = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        page=1,
        page_size=20,
        _username="admin",
        store=store,
    )
    assert result["data"]["run"] is None
    assert result["data"]["rows"] == []


def test_rule_filter_does_not_stop_at_fixed_500_runs(db_session) -> None:
    _generation(db_session, "g-score-history")
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-score-history')"
        )
    )
    # The matching legacy-config run is deliberately older than 500 newer runs.
    _insert_score_fixture(
        db_session,
        generation_id="g-score-history",
        run_id="run-matching-old",
        rule_id="rule-target",
        score=1,
        computed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.flush()
    db_session.execute(
        text(
            "DELETE FROM store_score_snapshot_generation "
            "WHERE snapshot_run_id = 'run-matching-old'"
        )
    )
    for index in range(501):
        db_session.add(
            StoreScoreSnapshotRun(
                snapshot_run_id=f"run-new-{index:04d}",
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                candidate_store_count=0,
                snapshot_count=0,
                config_json={"rule_version_id": "rule-other"},
                computed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
        )
    db_session.commit()
    store = SimpleNamespace(available=True, session=db_session)
    result = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        rule_version_id="rule-target",
        page=1,
        page_size=20,
        _username="admin",
        store=store,
    )
    assert result["data"]["run"]["snapshot_run_id"] == "run-matching-old"


def test_partition_key_stream_stops_at_cap_and_depth_metadata_is_validated(db_session) -> None:
    _generation(db_session, "g-stream")
    consumed = 0

    def keys():
        nonlocal consumed
        for _ in range(MAX_PARTITION_KEYS + 50):
            consumed += 1
            yield f"k-{consumed}"

    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=keys(),
            pinned_generation_id="g-stream",
        )
    assert consumed <= MAX_PARTITION_KEYS + 1

    db_session.execute(
        text(
            "UPDATE settlement_projection_generation SET lineage_depth = :depth "
            "WHERE generation_id = 'g-stream'"
        ),
        {"depth": MAX_LINEAGE_DEPTH + 100},
    )
    db_session.commit()
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-stream",
        )


def test_tombstone_only_overlay_rows_fail_presence_validation(db_session) -> None:
    _generation(db_session, "g-tombstone-data")
    _manifest(
        db_session,
        "g-tombstone-data",
        "monthly",
        "2026-08",
        data_generation_id="g-tombstone-data",
    )
    db_session.execute(
        text(
            "UPDATE settlement_projection_partition_manifest SET row_count = 1 "
            "WHERE generation_id = 'g-tombstone-data' AND artifact = 'monthly'"
        )
    )
    db_session.add(
        SettlementMonthlyOverlay(
            generation_id="g-tombstone-data",
            month="2026-08",
            partition_key="2026-08",
            store_id="score-store",
            product_scope="all",
            product_type="all",
            tombstone=True,
        )
    )
    db_session.commit()
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-tombstone-data",
        )


def test_pinned_ranking_scope_only_applies_to_authorized_mode(db_session) -> None:
    _generation(db_session, "g-scope")
    _manifest(
        db_session,
        "g-scope",
        "ranking",
        "monthly:2026-08",
        data_generation_id="g-scope",
    )
    for store_id, amount in (("store-1", 100), ("store-2", 200)):
        db_session.add(
            SettlementRankingOverlay(
                generation_id="g-scope",
                period_type=1,
                period_key="2026-08",
                month="2026-08",
                partition_key="monthly:2026-08",
                store_id=store_id,
                store_name=store_id,
                product_scope="all",
                product_type="all",
                sales_order_count=1,
                sales_amount_cent=amount,
                promotion_net_fee_cent=amount,
                net_settlement_reference_cent=amount,
            )
        )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-scope')"
        )
    )
    db_session.commit()
    filters = {
        "period_type": "MONTHLY",
        "period_key": "2026-08",
        "product_scope": "all",
        "product_type": "all",
        "page": 1,
        "page_size": 20,
        "scope_store_ids": ["store-1"],
        "sort_by": "SALES_AMOUNT",
        "sort_order": "DESC",
    }
    store = DashboardDataStore(db_session)
    assert store.store_ranking_report({**filters, "scope_mode": "ALL"})["total"] == 2
    assert store.store_ranking_report({**filters, "scope_mode": "AUTHORIZED"})["total"] == 1


def test_overlay_presence_query_handles_more_than_500_partitions(db_session) -> None:
    _generation(db_session, "g-many")
    keys = [f"2026-{index:04d}"[-7:] for index in range(1, 502)]
    # Use a compact SQL seed to keep the test focused on resolver query shape.
    for index, key in enumerate(keys):
        _manifest(
            db_session,
            "g-many",
            "monthly",
            key,
            data_generation_id="g-many",
        )
        db_session.add(
            SettlementMonthlyOverlay(
                generation_id="g-many",
                month=key,
                partition_key=key,
                store_id=f"store-{index}",
                product_scope="all",
                product_type="all",
            )
        )
    db_session.execute(
        text(
            "UPDATE settlement_projection_partition_manifest SET row_count = 1 "
            "WHERE generation_id = 'g-many' AND artifact = 'monthly'"
        )
    )
    db_session.commit()
    resolved = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=keys,
        pinned_generation_id="g-many",
    )
    assert len(resolved) == len(keys)


def test_null_pointer_preserves_all_nine_aggregate_reader_shapes_and_a09_compatibility(
    db_session,
) -> None:
    db_session.add(DimStore(store_id="legacy-store", store_name="Legacy Store"))
    db_session.add(
        AggStoreRanking(
            period_type=1,
            period_key="2026-08",
            month="2026-08",
            store_id="legacy-store",
            store_name="Legacy Store",
            product_scope="all",
            product_type="all",
            sales_order_count=3,
            sales_amount_cent=300,
            verified_order_count=2,
            verified_amount_cent=200,
            promotion_net_fee_cent=30,
            management_net_fee_cent=10,
            net_settlement_reference_cent=20,
        )
    )
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="legacy-store",
            product_scope="all",
            product_type="all",
            sales_order_count=3,
            sales_amount_cent=300,
            verified_order_count=2,
            verified_amount_cent=200,
            promotion_base_cent=30,
            promotion_original_fee_cent=30,
            promotion_adjustment_fee_cent=0,
            promotion_net_fee_cent=30,
            management_base_cent=10,
            management_original_fee_cent=10,
            management_adjustment_fee_cent=0,
            management_net_fee_cent=10,
            statement_status=1,
            estimated_receivable_commission_cent=30,
            commissionable_total_cent=300,
            estimated_payable_commission_cent=10,
        )
    )
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="legacy-score-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            candidate_store_count=1,
            snapshot_count=1,
            config_json={"rule_version_id": "legacy-rule"},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id="legacy-score-row",
            snapshot_run_id="legacy-score-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            store_id="legacy-store",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            conversion_value_source="observed",
            follow_24h_value_source="observed",
            composite_score=1,
            config_json={"rule_version_id": "legacy-rule"},
        )
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', NULL)"
        )
    )
    db_session.commit()
    store = DashboardDataStore(db_session)
    assert store.list_sale_months() == ["2026-08"]
    assert store.list_verify_months() == []
    assert store.list_statement_months() == ["2026-08"]
    assert store.store_ranking(month="2026-08", product_type="all", limit=10)
    assert store.store_ranking_totals(month="2026-08", product_type="all")["sales_order_count"] == 3
    assert store.store_ranking_report(
        {
            "period_type": "MONTHLY",
            "period_key": "2026-08",
            "product_scope": "all",
            "product_type": "all",
            "page": 1,
            "page_size": 10,
            "sort_by": "SALES_AMOUNT",
            "sort_order": "DESC",
        }
    )["total"] == 1
    assert store.monthly_settlement_context_exists("legacy-store", "2026-08")
    assert store.monthly_settlement(
        store_id="legacy-store", month="2026-08", product_type="all"
    )["metrics"]["commissionable_total_cent"] == 300
    report = store.monthly_settlement_report(
        {
            "store_id": "legacy-store",
            "month": "2026-08",
            "product_scope": "all",
            "product_type": "all",
        }
    )
    assert report["metrics"]["sales_order_count"] == 3
    a09 = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert a09["data"]["run"]["snapshot_run_id"] == "legacy-score-run"


def test_lineage_cycle_missing_base_invalid_state_and_corrupt_manifest_fail_closed(db_session) -> None:
    _generation(db_session, "g-cycle-a", base_generation_id="g-cycle-b", depth=1)
    _generation(db_session, "g-cycle-b", base_generation_id="g-cycle-a", depth=0)
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-cycle-a",
        )

    _generation(db_session, "g-missing-base", base_generation_id="does-not-exist", depth=1)
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-missing-base",
        )

    _generation(db_session, "g-invalid-state", state="ready")
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-invalid-state",
        )

    _generation(db_session, "g-corrupt-manifest")
    _manifest(
        db_session,
        "g-corrupt-manifest",
        "monthly",
        "2026-08",
        data_generation_id="outside-generation",
    )
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-corrupt-manifest",
        )


def test_lineage_db_failure_is_typed_and_fail_closed() -> None:
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OSError("database unavailable")

    with pytest.raises(LineageError):
        active_generation_id(BrokenSession())
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            BrokenSession(),
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-any",
        )


def test_pinned_ranking_uses_sql_limit_for_large_owned_partition(db_session) -> None:
    _generation(db_session, "g-large")
    _manifest(
        db_session,
        "g-large",
        "ranking",
        "monthly:2026-08",
        data_generation_id="g-large",
    )
    for index in range(20):
        amount = 1000 - index
        db_session.add(
            SettlementRankingOverlay(
                generation_id="g-large",
                period_type=1,
                period_key="2026-08",
                month="2026-08",
                partition_key="monthly:2026-08",
                store_id=f"large-store-{index:02d}",
                store_name=f"Large {index}",
                product_scope="all",
                product_type="all",
                sales_order_count=1,
                sales_amount_cent=amount,
                promotion_net_fee_cent=amount,
                net_settlement_reference_cent=amount,
            )
        )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-large')"
        )
    )
    db_session.commit()
    statements: list[str] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "settlement_ranking_overlay" in statement:
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        rows = DashboardDataStore(db_session).store_ranking(
            month="2026-08", product_type="all", limit=5
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)
    assert len(rows) == 5
    assert any("LIMIT" in statement.upper() for statement in statements)


def test_legacy_score_without_valid_rule_id_stays_unversioned(db_session) -> None:
    db_session.add(DimStore(store_id="unversioned-store", store_name="Unversioned"))
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="unversioned-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            candidate_store_count=1,
            snapshot_count=1,
            config_json={"rule_version_id": 123},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id="unversioned-row",
            snapshot_run_id="unversioned-run",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            store_id="unversioned-store",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            conversion_value_source="observed",
            follow_24h_value_source="observed",
            composite_score=1,
            config_json={"rule_version_id": 123},
        )
    )
    db_session.commit()
    result = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"]["rule_version_id"] is None
    assert result["data"]["rows"][0]["rule_version_id"] is None


def test_pinned_cumulative_ranking_uses_its_own_partition_identity(db_session) -> None:
    _generation(db_session, "g-cumulative")
    _manifest(
        db_session,
        "g-cumulative",
        "ranking",
        "cumulative:2026-08",
        data_generation_id="g-cumulative",
    )
    db_session.add(
        SettlementRankingOverlay(
            generation_id="g-cumulative",
            period_type=2,
            period_key="2026-08",
            month="2026-08",
            partition_key="cumulative:2026-08",
            store_id="cumulative-store",
            store_name="Cumulative Store",
            product_scope="all",
            product_type="all",
            sales_order_count=11,
            sales_amount_cent=1100,
            promotion_net_fee_cent=110,
            net_settlement_reference_cent=110,
        )
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-cumulative')"
        )
    )
    db_session.commit()
    report = DashboardDataStore(db_session).store_ranking_report(
        {
            "period_type": "CUMULATIVE",
            "period_key": "2026-08",
            "product_scope": "all",
            "product_type": "all",
            "page": 1,
            "page_size": 10,
            "sort_by": "SALES_AMOUNT",
            "sort_order": "DESC",
        }
    )
    assert report["total"] == 1
    assert report["totals"]["sales_order_count"] == 11


# ---------------------------------------------------------------------------
# Remediation round 2 (R9-R14): contract tests are intentionally added before
# the implementation changes.  The fixtures below exercise the fail-closed
# lineage rules and bounded score-reader control plane directly.
# ---------------------------------------------------------------------------


def test_r9_root_lineage_depth_is_absolute_and_must_start_at_zero(db_session) -> None:
    _generation(db_session, "g-root-depth-one", depth=1)
    db_session.commit()
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-root-depth-one",
        )


def test_r9_blank_pinned_and_base_generation_ids_fail_closed(db_session) -> None:
    _generation(db_session, "g-blank-base", base_generation_id="   ", depth=0)
    db_session.commit()
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-blank-base",
        )

    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="   ",
        )


def _insert_score_run_with_stores(
    db_session,
    *,
    run_id: str,
    snapshot_date: date,
    computed_at: datetime,
    rule_id: str,
    store_ids: list[str],
    scores: list[int] | None = None,
) -> None:
    scores = scores or list(range(len(store_ids), 0, -1))
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id=run_id,
            snapshot_date=snapshot_date,
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            candidate_store_count=len(store_ids),
            snapshot_count=len(store_ids),
            config_json={"rule_version_id": rule_id},
            computed_at=computed_at,
        )
    )
    for index, store_id in enumerate(store_ids):
        db_session.add(DimStore(store_id=store_id, store_name=store_id))
        db_session.add(
            StoreScoreSnapshot(
                snapshot_id=f"{run_id}-{store_id}",
                snapshot_run_id=run_id,
                snapshot_date=snapshot_date,
                run_mode="scheduled",
                store_id=store_id,
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                conversion_value_source="observed",
                follow_24h_value_source="observed",
                composite_score=scores[index],
                config_json={"rule_version_id": rule_id},
            )
        )


def test_r10_date_only_selection_skips_fully_tombstoned_latest_run(db_session) -> None:
    _generation(db_session, "g-score-root")
    _generation(db_session, "g-score-active", base_generation_id="g-score-root", depth=1)
    db_session.add(DimStore(store_id="score-store", store_name="Score Store"))
    old_key = _insert_score_fixture(
        db_session,
        generation_id="g-score-root",
        run_id="run-visible-old",
        rule_id="rule-old",
        score=10,
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    latest_key = _insert_score_fixture(
        db_session,
        generation_id="g-score-root",
        run_id="run-hidden-latest",
        rule_id="rule-latest",
        score=20,
        computed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    _manifest(db_session, "g-score-root", "score", old_key, data_generation_id="g-score-root")
    _manifest(db_session, "g-score-root", "score", latest_key, data_generation_id="g-score-root")
    _manifest(
        db_session,
        "g-score-active",
        "score",
        latest_key,
        owner_state="tombstone",
        source_kind="tombstone",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-score-active')"
        )
    )
    db_session.commit()
    result = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"]["snapshot_run_id"] == "run-visible-old"


def test_r10_partial_tombstone_keeps_latest_run_and_visible_rows(db_session) -> None:
    _generation(db_session, "g-partial-root")
    _generation(db_session, "g-partial", base_generation_id="g-partial-root", depth=1)
    _insert_score_run_with_stores(
        db_session,
        run_id="run-partial-latest",
        snapshot_date=date(2026, 8, 1),
        computed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        rule_id="rule-partial",
        store_ids=["partial-a", "partial-b"],
        scores=[20, 10],
    )
    for store_id in ("partial-a", "partial-b"):
        key = canonical_score_partition_key(date(2026, 8, 1), "rule-partial", store_id)
        _manifest(db_session, "g-partial-root", "score", key, data_generation_id="g-partial-root")
        db_session.add(
            StoreScoreSnapshotGeneration(
                generation_id="g-partial-root",
                snapshot_run_id="run-partial-latest",
                store_id=store_id,
                rule_version_id="rule-partial",
                snapshot_date=date(2026, 8, 1),
                partition_key=key,
            )
        )
    visible_key = canonical_score_partition_key(
        date(2026, 8, 1), "rule-partial", "partial-b"
    )
    _manifest(
        db_session,
        "g-partial",
        "score",
        visible_key,
        source_kind="overlay",
        data_generation_id="g-partial-root",
    )
    tombstone_key = canonical_score_partition_key(
        date(2026, 8, 1), "rule-partial", "partial-a"
    )
    _manifest(
        db_session,
        "g-partial",
        "score",
        tombstone_key,
        owner_state="tombstone",
        source_kind="tombstone",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-partial')"
        )
    )
    db_session.commit()
    result = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"]["snapshot_run_id"] == "run-partial-latest"
    assert [row["store_id"] for row in result["data"]["rows"]] == ["partial-b"]


def test_r10_exact_zero_row_rule_mismatch_returns_empty(db_session) -> None:
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="run-exact-empty-rule-b",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            candidate_store_count=0,
            snapshot_count=0,
            config_json={"rule_version_id": "rule-b"},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    result = list_store_score_snapshots(
        snapshot_run_id="run-exact-empty-rule-b",
        rule_version_id="rule-a",
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"] is None


def test_r10_exact_zero_row_invalid_config_rule_returns_empty(db_session) -> None:
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="run-exact-empty-invalid-rule",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            candidate_store_count=0,
            snapshot_count=0,
            config_json={"rule_version_id": 123},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    result = list_store_score_snapshots(
        snapshot_run_id="run-exact-empty-invalid-rule",
        rule_version_id="rule-a",
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"] is None


def test_r10_candidate_history_is_keyset_paged_and_bounded(db_session, monkeypatch) -> None:
    _generation(db_session, "g-candidate-pages")
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-candidate-pages')"
        )
    )
    target_run_id = "run-candidate-0000"
    for index in range(1200):
        db_session.add(
            StoreScoreSnapshotRun(
                snapshot_run_id=f"run-candidate-{index:04d}",
                snapshot_date=date(2026, 8, 1),
                run_mode="scheduled",
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
                candidate_store_count=0,
                snapshot_count=0,
                config_json={"rule_version_id": "rule-page"},
                computed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
                + timedelta(hours=index),
            )
        )
    db_session.commit()
    page_lengths: list[int] = []

    def fake_candidate_states(session, runs, *, pinned_generation_id):
        page_lengths.append(len(runs))
        return {
            str(run.snapshot_run_id): {
                "raw_count": 0 if str(run.snapshot_run_id) == target_run_id else 1,
                "visible_count": 0,
                "effective_rules": set(),
                "fallback_rule": "rule-page",
            }
            for run in runs
        }

    monkeypatch.setattr(admin_routes, "_score_candidate_page_states", fake_candidate_states)
    statements: list[str] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "store_score_snapshot_runs" in statement.lower():
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        result = list_store_score_snapshots(
            snapshot_date=date(2026, 8, 1),
            rule_version_id="rule-page",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)
    assert result["data"]["run"]["snapshot_run_id"] == target_run_id
    assert statements
    assert all("LIMIT" in statement.upper() for statement in statements)
    assert page_lengths and max(page_lengths) <= 100


def test_r11_score_reader_batches_more_than_one_thousand_stores(
    db_session,
    monkeypatch,
) -> None:
    _generation(db_session, "g-1201-sidecar")
    _insert_score_run_with_stores(
        db_session,
        run_id="run-1201-stores",
        snapshot_date=date(2026, 8, 1),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        rule_id="rule-1201",
        store_ids=[f"score-1201-{index:04d}" for index in range(1201)],
    )
    db_session.flush()
    sidecar_rows = []
    manifest_rows = []
    for index in range(1201):
        store_id = f"score-1201-{index:04d}"
        key = canonical_score_partition_key(date(2026, 8, 1), "rule-1201", store_id)
        sidecar_rows.append(
            StoreScoreSnapshotGeneration(
                generation_id="g-1201-sidecar",
                snapshot_run_id="run-1201-stores",
                store_id=store_id,
                rule_version_id="rule-1201",
                snapshot_date=date(2026, 8, 1),
                partition_key=key,
            )
        )
        manifest_rows.append(
            {
                "generation_id": "g-1201-sidecar",
                "artifact": "score",
                "partition_key": key,
                "created_at": datetime.now(timezone.utc),
            }
        )
    db_session.add_all(sidecar_rows)
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_partition_manifest
                (generation_id, artifact, partition_key, owner_state, source_kind,
                 data_generation_id, base_generation_id, row_count, amount_total_cent,
                 status_counts_json, created_at)
            VALUES (:generation_id, :artifact, :partition_key, 'owned', 'overlay',
                    :generation_id, NULL, 0, 0, '{}', :created_at)
            """
        ),
        manifest_rows,
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-1201-sidecar')"
        )
    )
    db_session.commit()
    statements: list[str] = []
    sidecar_statements: list[str] = []
    batch_lengths: list[int] = []
    original_resolve_fact_batch = admin_routes._score_resolve_fact_batch

    def spy_resolve_fact_batch(session, rows, runs_by_id, *, pinned_generation_id):
        batch_lengths.append(len(rows))
        return original_resolve_fact_batch(
            session,
            rows,
            runs_by_id,
            pinned_generation_id=pinned_generation_id,
        )

    monkeypatch.setattr(admin_routes, "_score_resolve_fact_batch", spy_resolve_fact_batch)

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "store_score_snapshots" in statement.lower():
            statements.append(statement)
        if "select generation_id, snapshot_run_id, store_id" in statement.lower():
            sidecar_statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        result = list_store_score_snapshots(
            snapshot_date=date(2026, 8, 1),
            page=61,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)
    assert result["data"]["pagination"]["total"] == 1201
    assert len(result["data"]["rows"]) == 1
    assert statements
    assert all("LIMIT" in statement.upper() for statement in statements)
    assert len(sidecar_statements) >= 4
    assert all("LIMIT" in statement.upper() for statement in sidecar_statements)
    assert batch_lengths and max(batch_lengths) <= 400


def test_r11_hidden_candidate_page_does_not_issue_one_score_query_per_run(
    db_session,
) -> None:
    _generation(db_session, "g-hidden-root")
    _generation(db_session, "g-hidden-active", base_generation_id="g-hidden-root", depth=1)
    store_ids = [f"hidden-{index:02d}" for index in range(20)]
    for index, store_id in enumerate(store_ids):
        db_session.add(DimStore(store_id=store_id, store_name=store_id))
        key = _insert_score_fixture(
            db_session,
            generation_id="g-hidden-root",
            run_id=f"run-hidden-{index:02d}",
            rule_id="rule-hidden",
            score=index + 1,
            computed_at=datetime(2026, 8, 3, tzinfo=timezone.utc).replace(minute=index),
        )
        db_session.flush()
        # Move the fixture identity to a distinct store so each hidden run has
        # a distinct score partition without changing the shared helper shape.
        db_session.execute(
            text(
                "UPDATE store_score_snapshots SET store_id=:store_id, snapshot_id=:snapshot_id "
                "WHERE snapshot_run_id=:run_id"
            ),
            {
                "store_id": store_id,
                "snapshot_id": f"run-hidden-{index:02d}-{store_id}",
                "run_id": f"run-hidden-{index:02d}",
            },
        )
        db_session.execute(
            text(
                "UPDATE store_score_snapshot_generation SET store_id=:store_id, partition_key=:partition_key "
                "WHERE snapshot_run_id=:run_id"
            ),
            {
                "store_id": store_id,
                "partition_key": canonical_score_partition_key(
                    date(2026, 8, 1), "rule-hidden", store_id
                ),
                "run_id": f"run-hidden-{index:02d}",
            },
        )
        _manifest(
            db_session,
            "g-hidden-root",
            "score",
            canonical_score_partition_key(date(2026, 8, 1), "rule-hidden", store_id),
            data_generation_id="g-hidden-root",
        )
        _manifest(
            db_session,
            "g-hidden-active",
            "score",
            canonical_score_partition_key(date(2026, 8, 1), "rule-hidden", store_id),
            owner_state="tombstone",
            source_kind="tombstone",
        )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-hidden-active')"
        )
    )
    db_session.commit()
    statements: list[str] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "store_score_snapshots" in statement.lower():
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        result = list_store_score_snapshots(
            snapshot_date=date(2026, 8, 1),
            rule_version_id="rule-hidden",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)
    assert result["data"]["run"] is None
    assert len(statements) <= 3


def test_r11_sidecar_reader_keyset_pages_more_than_four_hundred_rows(db_session) -> None:
    _generation(db_session, "g-sidecar-active")
    db_session.add(DimStore(store_id="sidecar-page-store", store_name="Sidecar Page"))
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id="run-sidecar-page",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            candidate_store_count=1,
            snapshot_count=1,
            config_json={"rule_version_id": "rule-sidecar-page"},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        StoreScoreSnapshot(
            snapshot_id="snapshot-sidecar-page",
            snapshot_run_id="run-sidecar-page",
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            store_id="sidecar-page-store",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            conversion_value_source="observed",
            follow_24h_value_source="observed",
            composite_score=1,
            config_json={"rule_version_id": "rule-sidecar-page"},
        )
    )
    db_session.flush()
    generation_rows = [
        {
            "generation_id": f"g-sidecar-{index:04d}",
            "created_at": datetime.now(timezone.utc),
        }
        for index in range(401)
    ]
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_generation
                (generation_id, base_generation_id, projection_name, state,
                 input_fingerprint, lineage_depth, estimated_write_rows,
                 estimated_write_bytes, estimated_wal_bytes,
                 estimated_disk_headroom_bytes, checkpoint_json, source_input_json,
                 created_at)
            VALUES (:generation_id, NULL, 'settlement', 'published',
                    :fingerprint, 0, 0, 0, 0, 0, '{}', '{}', :created_at)
            """
        ),
        [{**row, "fingerprint": row["generation_id"]} for row in generation_rows],
    )
    active_key = canonical_score_partition_key(
        date(2026, 8, 1), "rule-sidecar-page", "sidecar-page-store"
    )
    _manifest(
        db_session,
        "g-sidecar-active",
        "score",
        active_key,
        data_generation_id="g-sidecar-active",
    )
    db_session.execute(
        text(
            """
            INSERT INTO store_score_snapshot_generation
                (generation_id, snapshot_run_id, store_id, rule_version_id,
                 snapshot_date, partition_key, owner_state, created_at)
            VALUES (:generation_id, 'run-sidecar-page', 'sidecar-page-store',
                    'rule-sidecar-page', '2026-08-01', :partition_key,
                    'owned', :created_at)
            """
        ),
        [
            {
                "generation_id": row["generation_id"],
                "partition_key": active_key,
                "created_at": row["created_at"],
            }
            for row in generation_rows
        ],
    )
    db_session.execute(
        text(
            """
            INSERT INTO store_score_snapshot_generation
                (generation_id, snapshot_run_id, store_id, rule_version_id,
                 snapshot_date, partition_key, owner_state, created_at)
            VALUES ('g-sidecar-active', 'run-sidecar-page', 'sidecar-page-store',
                    'rule-sidecar-page', '2026-08-01', :partition_key,
                    'owned', :created_at)
            """
        ),
        {"partition_key": active_key, "created_at": datetime.now(timezone.utc)},
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-sidecar-active')"
        )
    )
    db_session.commit()
    statements: list[str] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "select generation_id, snapshot_run_id, store_id" in statement.lower():
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        result = _score_sidecar_rule_map(
            db_session,
            snapshot_run_ids=["run-sidecar-page"],
            pinned_generation_id="g-sidecar-active",
            identities=[("run-sidecar-page", "sidecar-page-store")],
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)
    assert result == {("run-sidecar-page", "sidecar-page-store"): "rule-sidecar-page"}
    assert len(statements) >= 2
    assert all("LIMIT" in statement.upper() for statement in statements)


def test_r11_fact_batch_iterator_handles_a_faithful_ten_thousand_row_stream() -> None:
    class PagedResult:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class FaithfulPagedSession:
        def __init__(self):
            self.calls = 0

        def scalars(self, _statement):
            self.calls += 1
            batch_index = self.calls - 1
            if batch_index >= 25:
                return PagedResult([])
            start = batch_index * 400
            rows = [
                SimpleNamespace(
                    snapshot_run_id="run-faithful-10k",
                    composite_score=10000 - start - offset,
                    store_id=f"faithful-{start + offset:05d}",
                )
                for offset in range(400)
            ]
            return PagedResult(rows)

    session = FaithfulPagedSession()
    batches = list(
        _score_fact_batches(
            session,
            snapshot_run_ids=["run-faithful-10k"],
        )
    )
    assert len(batches) == 25
    assert sum(len(batch) for batch in batches) == 10000
    assert max(len(batch) for batch in batches) <= 400
    assert session.calls == 26


def test_r12_mixed_effective_rules_fail_closed(db_session) -> None:
    _generation(db_session, "g-r12")
    _insert_score_run_with_stores(
        db_session,
        run_id="run-r12-conflict",
        snapshot_date=date(2026, 8, 1),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        rule_id="rule-config",
        store_ids=["r12-sidecar", "r12-config"],
        scores=[20, 10],
    )
    sidecar_key = canonical_score_partition_key(date(2026, 8, 1), "rule-sidecar", "r12-sidecar")
    _manifest(db_session, "g-r12", "score", sidecar_key, data_generation_id="g-r12")
    db_session.add(
        StoreScoreSnapshotGeneration(
            generation_id="g-r12",
            snapshot_run_id="run-r12-conflict",
            store_id="r12-sidecar",
            rule_version_id="rule-sidecar",
            snapshot_date=date(2026, 8, 1),
            partition_key=sidecar_key,
        )
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-r12')"
        )
    )
    db_session.commit()
    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_date=date(2026, 8, 1),
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r12_sidecar_rule_wins_over_stale_run_config_for_every_row(db_session) -> None:
    _generation(db_session, "g-r12-sidecar")
    _insert_score_run_with_stores(
        db_session,
        run_id="run-r12-sidecar",
        snapshot_date=date(2026, 8, 1),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        rule_id="rule-stale-config",
        store_ids=["r12-a", "r12-b"],
        scores=[20, 10],
    )
    for store_id in ("r12-a", "r12-b"):
        key = canonical_score_partition_key(date(2026, 8, 1), "rule-sidecar", store_id)
        _manifest(db_session, "g-r12-sidecar", "score", key, data_generation_id="g-r12-sidecar")
        db_session.add(
            StoreScoreSnapshotGeneration(
                generation_id="g-r12-sidecar",
                snapshot_run_id="run-r12-sidecar",
                store_id=store_id,
                rule_version_id="rule-sidecar",
                snapshot_date=date(2026, 8, 1),
                partition_key=key,
            )
        )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-r12-sidecar')"
        )
    )
    db_session.commit()
    result = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"]["rule_version_id"] == "rule-sidecar"
    assert {row["rule_version_id"] for row in result["data"]["rows"]} == {"rule-sidecar"}


def test_r12_multiple_visible_sidecar_rules_fail_closed(db_session) -> None:
    _generation(db_session, "g-r12-multi")
    _insert_score_run_with_stores(
        db_session,
        run_id="run-r12-multi",
        snapshot_date=date(2026, 8, 1),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        rule_id="rule-stale",
        store_ids=["r12-multi-a", "r12-multi-b"],
        scores=[20, 10],
    )
    for store_id, rule_id in (("r12-multi-a", "rule-a"), ("r12-multi-b", "rule-b")):
        key = canonical_score_partition_key(date(2026, 8, 1), rule_id, store_id)
        _manifest(db_session, "g-r12-multi", "score", key, data_generation_id="g-r12-multi")
        db_session.add(
            StoreScoreSnapshotGeneration(
                generation_id="g-r12-multi",
                snapshot_run_id="run-r12-multi",
                store_id=store_id,
                rule_version_id=rule_id,
                snapshot_date=date(2026, 8, 1),
                partition_key=key,
            )
        )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-r12-multi')"
        )
    )
    db_session.commit()
    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_date=date(2026, 8, 1),
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r12_tombstoned_sidecar_identity_cannot_fall_back_to_stale_config(
    db_session,
) -> None:
    _generation(db_session, "g-tombstone-sidecar-root")
    _generation(
        db_session,
        "g-tombstone-sidecar-active",
        base_generation_id="g-tombstone-sidecar-root",
        depth=1,
    )
    _insert_score_run_with_stores(
        db_session,
        run_id="run-tombstone-sidecar",
        snapshot_date=date(2026, 8, 1),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        rule_id="rule-stale-config",
        store_ids=["tombstone-sidecar-store"],
        scores=[10],
    )
    sidecar_key = canonical_score_partition_key(
        date(2026, 8, 1), "rule-authoritative", "tombstone-sidecar-store"
    )
    _manifest(
        db_session,
        "g-tombstone-sidecar-root",
        "score",
        sidecar_key,
        data_generation_id="g-tombstone-sidecar-root",
    )
    _manifest(
        db_session,
        "g-tombstone-sidecar-active",
        "score",
        sidecar_key,
        owner_state="tombstone",
        source_kind="tombstone",
    )
    db_session.add(
        StoreScoreSnapshotGeneration(
            generation_id="g-tombstone-sidecar-root",
            snapshot_run_id="run-tombstone-sidecar",
            store_id="tombstone-sidecar-store",
            rule_version_id="rule-authoritative",
            snapshot_date=date(2026, 8, 1),
            partition_key=sidecar_key,
        )
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-tombstone-sidecar-active')"
        )
    )
    db_session.commit()
    result = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        snapshot_run_id="run-tombstone-sidecar",
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"] is None


def test_r12_tombstone_owner_sidecar_is_corruption(db_session) -> None:
    _generation(db_session, "g-tombstone-owner-corrupt")
    _insert_score_run_with_stores(
        db_session,
        run_id="run-tombstone-owner-corrupt",
        snapshot_date=date(2026, 8, 1),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        rule_id="rule-corrupt",
        store_ids=["tombstone-owner-store"],
        scores=[1],
    )
    key = canonical_score_partition_key(
        date(2026, 8, 1), "rule-corrupt", "tombstone-owner-store"
    )
    _manifest(
        db_session,
        "g-tombstone-owner-corrupt",
        "score",
        key,
        owner_state="tombstone",
        source_kind="tombstone",
    )
    db_session.add(
        StoreScoreSnapshotGeneration(
            generation_id="g-tombstone-owner-corrupt",
            snapshot_run_id="run-tombstone-owner-corrupt",
            store_id="tombstone-owner-store",
            rule_version_id="rule-corrupt",
            snapshot_date=date(2026, 8, 1),
            partition_key=key,
        )
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-tombstone-owner-corrupt')"
        )
    )
    db_session.commit()
    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id="run-tombstone-owner-corrupt",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r13_a09_candidate_db_failure_is_typed_and_fail_closed() -> None:
    class BrokenCandidateSession:
        def scalar(self, *args, **kwargs):
            raise OSError("candidate query unavailable")

    store = SimpleNamespace(
        available=True,
        session=BrokenCandidateSession(),
        _pinned_aggregate_generation=lambda: None,
    )
    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_date=date(2026, 8, 1),
            page=1,
            page_size=20,
            _username="admin",
            store=store,
        )


def test_r13_a09_score_fact_db_failure_is_typed_and_fail_closed(db_session) -> None:
    _generation(db_session, "g-fact-failure")
    _insert_score_fixture(
        db_session,
        generation_id="g-fact-failure",
        run_id="run-fact-failure",
        rule_id="rule-fact-failure",
        score=1,
    )
    db_session.commit()

    class BrokenFactSession:
        def __init__(self, delegate):
            self.delegate = delegate

        def scalar(self, *args, **kwargs):
            return self.delegate.scalar(*args, **kwargs)

        def execute(self, *args, **kwargs):
            return self.delegate.execute(*args, **kwargs)

        def scalars(self, *args, **kwargs):
            raise OSError("score fact query unavailable")

    store = SimpleNamespace(
        available=True,
        session=BrokenFactSession(db_session),
        _pinned_aggregate_generation=lambda: None,
    )
    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_date=date(2026, 8, 1),
            page=1,
            page_size=20,
            _username="admin",
            store=store,
        )


# ---------------------------------------------------------------------------
# Remediation round 3 (R15-R19): sidecar identity/date integrity, pointer-NULL
# response compatibility, SQLite bind portability, and behavioral large-data
# bounds.  These tests are deliberately added before the round-3 implementation
# changes so the focused RED run captures the current behavioral gaps.
# ---------------------------------------------------------------------------


def _activate_generation(db_session, generation_id: str) -> None:
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', :generation_id)"
        ),
        {"generation_id": generation_id},
    )


def test_r15_valid_sidecar_key_and_date_remain_visible(db_session) -> None:
    _generation(db_session, "g-r15-valid")
    partition_key = _insert_score_fixture(
        db_session,
        generation_id="g-r15-valid",
        run_id="run-r15-valid",
        rule_id="rule-r15-valid",
        score=42,
    )
    _manifest(
        db_session,
        "g-r15-valid",
        "score",
        partition_key,
        data_generation_id="g-r15-valid",
    )
    db_session.execute(
        text(
            "UPDATE settlement_projection_partition_manifest SET row_count = 1 "
            "WHERE generation_id = 'g-r15-valid' AND artifact = 'score'"
        )
    )
    _activate_generation(db_session, "g-r15-valid")
    db_session.commit()

    result = list_store_score_snapshots(
        snapshot_run_id="run-r15-valid",
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"]["snapshot_run_id"] == "run-r15-valid"
    assert result["data"]["run"]["rule_version_id"] == "rule-r15-valid"
    assert result["data"]["rows"][0]["rule_version_id"] == "rule-r15-valid"


def test_r15_wrong_stored_sidecar_partition_key_fails_closed(db_session) -> None:
    _generation(db_session, "g-r15-wrong-key")
    partition_key = _insert_score_fixture(
        db_session,
        generation_id="g-r15-wrong-key",
        run_id="run-r15-wrong-key",
        rule_id="rule-r15-wrong-key",
        score=42,
    )
    db_session.flush()
    db_session.execute(
        text(
            "UPDATE store_score_snapshot_generation SET partition_key = 'wrong-key' "
            "WHERE generation_id = 'g-r15-wrong-key' AND snapshot_run_id = 'run-r15-wrong-key'"
        )
    )
    _manifest(
        db_session,
        "g-r15-wrong-key",
        "score",
        partition_key,
        data_generation_id="g-r15-wrong-key",
    )
    db_session.execute(
        text(
            "UPDATE settlement_projection_partition_manifest SET row_count = 1 "
            "WHERE generation_id = 'g-r15-wrong-key' AND artifact = 'score'"
        )
    )
    _activate_generation(db_session, "g-r15-wrong-key")
    db_session.commit()

    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id="run-r15-wrong-key",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r15_sidecar_snapshot_date_must_match_fact_and_run(db_session) -> None:
    _generation(db_session, "g-r15-sidecar-date")
    partition_key = _insert_score_fixture(
        db_session,
        generation_id="g-r15-sidecar-date",
        run_id="run-r15-sidecar-date",
        rule_id="rule-r15-sidecar-date",
        score=42,
    )
    db_session.flush()
    mismatched_key = canonical_score_partition_key(
        date(2026, 8, 2), "rule-r15-sidecar-date", "score-store"
    )
    db_session.execute(
        text(
            "UPDATE store_score_snapshot_generation "
            "SET snapshot_date = '2026-08-02', partition_key = :partition_key "
            "WHERE generation_id = 'g-r15-sidecar-date' "
            "AND snapshot_run_id = 'run-r15-sidecar-date'"
        ),
        {"partition_key": mismatched_key},
    )
    _manifest(
        db_session,
        "g-r15-sidecar-date",
        "score",
        mismatched_key,
        data_generation_id="g-r15-sidecar-date",
    )
    db_session.execute(
        text(
            "UPDATE settlement_projection_partition_manifest SET row_count = 1 "
            "WHERE generation_id = 'g-r15-sidecar-date' AND artifact = 'score'"
        )
    )
    _activate_generation(db_session, "g-r15-sidecar-date")
    db_session.commit()
    assert partition_key != mismatched_key

    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id="run-r15-sidecar-date",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


@pytest.mark.parametrize("with_sidecar", [False, True])
def test_r15_fact_snapshot_date_must_match_selected_run(
    db_session,
    with_sidecar: bool,
) -> None:
    generation_id = f"g-r15-fact-date-{int(with_sidecar)}"
    _generation(db_session, generation_id)
    partition_key = _insert_score_fixture(
        db_session,
        generation_id=generation_id,
        run_id=f"run-r15-fact-date-{int(with_sidecar)}",
        rule_id="rule-r15-fact-date",
        score=42,
    )
    db_session.flush()
    if not with_sidecar:
        db_session.execute(
            text(
                "DELETE FROM store_score_snapshot_generation WHERE generation_id = :generation_id"
            ),
            {"generation_id": generation_id},
        )
    else:
        _manifest(
            db_session,
            generation_id,
            "score",
            partition_key,
            data_generation_id=generation_id,
        )
        db_session.execute(
            text(
                "UPDATE settlement_projection_partition_manifest SET row_count = 1 "
                "WHERE generation_id = :generation_id AND artifact = 'score'"
            ),
            {"generation_id": generation_id},
        )
    db_session.execute(
        text(
            "UPDATE store_score_snapshots SET snapshot_date = '2026-08-02' "
            "WHERE snapshot_run_id = :run_id"
        ),
        {"run_id": f"run-r15-fact-date-{int(with_sidecar)}"},
    )
    _activate_generation(db_session, generation_id)
    db_session.commit()

    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id=f"run-r15-fact-date-{int(with_sidecar)}",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r15_mismatched_sidecar_cannot_resurrect_tombstoned_legacy_fact(db_session) -> None:
    _generation(db_session, "g-r15-tombstone-root")
    _generation(
        db_session,
        "g-r15-tombstone-active",
        base_generation_id="g-r15-tombstone-root",
        depth=1,
    )
    key = _insert_score_fixture(
        db_session,
        generation_id="g-r15-tombstone-root",
        run_id="run-r15-tombstone",
        rule_id="rule-r15-tombstone",
        score=42,
    )
    db_session.flush()
    db_session.execute(
        text(
            "UPDATE store_score_snapshot_generation SET partition_key = 'wrong-key' "
            "WHERE generation_id = 'g-r15-tombstone-root'"
        )
    )
    _manifest(
        db_session,
        "g-r15-tombstone-root",
        "score",
        key,
        data_generation_id="g-r15-tombstone-root",
    )
    _manifest(
        db_session,
        "g-r15-tombstone-active",
        "score",
        key,
        owner_state="tombstone",
        source_kind="tombstone",
    )
    _activate_generation(db_session, "g-r15-tombstone-active")
    db_session.commit()

    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id="run-r15-tombstone",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r15_duplicate_conflicting_sidecar_metadata_fails_closed(db_session) -> None:
    _generation(db_session, "g-r15-duplicate-root")
    _generation(
        db_session,
        "g-r15-duplicate-child",
        base_generation_id="g-r15-duplicate-root",
        depth=1,
    )
    key_a = _insert_score_fixture(
        db_session,
        generation_id="g-r15-duplicate-root",
        run_id="run-r15-duplicate",
        rule_id="rule-r15-a",
        score=42,
    )
    key_b = canonical_score_partition_key(
        date(2026, 8, 1), "rule-r15-b", "score-store"
    )
    db_session.add(
        StoreScoreSnapshotGeneration(
            generation_id="g-r15-duplicate-child",
            snapshot_run_id="run-r15-duplicate",
            store_id="score-store",
            rule_version_id="rule-r15-b",
            snapshot_date=date(2026, 8, 1),
            partition_key=key_b,
        )
    )
    _manifest(
        db_session,
        "g-r15-duplicate-root",
        "score",
        key_a,
        data_generation_id="g-r15-duplicate-root",
    )
    _manifest(
        db_session,
        "g-r15-duplicate-child",
        "score",
        key_b,
        data_generation_id="g-r15-duplicate-child",
    )
    db_session.execute(
        text(
            "UPDATE settlement_projection_partition_manifest SET row_count = 1 "
            "WHERE artifact = 'score'"
        )
    )
    _activate_generation(db_session, "g-r15-duplicate-child")
    db_session.commit()

    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id="run-r15-duplicate",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r16_pointer_null_monthly_metrics_keep_exact_legacy_keys(db_session) -> None:
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r16-store",
            product_scope="all",
            product_type="all",
            sales_order_count=7,
            estimated_receivable_commission_cent=70,
            commissionable_total_cent=700,
            estimated_payable_commission_cent=7,
        )
    )
    db_session.commit()
    result = DashboardDataStore(db_session).monthly_settlement(
        store_id="r16-store",
        month="2026-08",
        product_type="all",
    )
    _assert_direct_monthly_metrics(result, receivable=70, commissionable=700, payable=7)


def test_r16_sql_null_pointer_monthly_metrics_keep_exact_legacy_keys(db_session) -> None:
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r16-sql-null",
            product_scope="all",
            product_type="all",
            sales_order_count=8,
            estimated_receivable_commission_cent=80,
            commissionable_total_cent=800,
            estimated_payable_commission_cent=8,
        )
    )
    db_session.flush()
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', NULL)"
        )
    )
    db_session.commit()

    result = DashboardDataStore(db_session).monthly_settlement(
        store_id="r16-sql-null", month="2026-08", product_type="all"
    )
    _assert_direct_monthly_metrics(result, receivable=80, commissionable=800, payable=8)


def test_r16_pointer_null_empty_or_no_session_metrics_keep_same_legacy_keys(db_session) -> None:
    db_session.commit()
    empty_result = DashboardDataStore(db_session).monthly_settlement(
        store_id="r16-empty",
        month="2026-08",
        product_type="all",
    )
    unavailable_result = DashboardDataStore(None).monthly_settlement(
        store_id="r16-empty",
        month="2026-08",
        product_type="all",
    )
    _assert_direct_monthly_metrics(empty_result)
    _assert_direct_monthly_metrics(unavailable_result)


def test_r16_pointer_null_row_matches_certified_legacy_root_exactly(db_session) -> None:
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r16-parity",
            product_scope="all",
            product_type="all",
            sales_order_count=7,
            estimated_receivable_commission_cent=70,
            commissionable_total_cent=700,
            estimated_payable_commission_cent=7,
        )
    )
    db_session.commit()
    before = DashboardDataStore(db_session).monthly_settlement(
        store_id="r16-parity", month="2026-08", product_type="all"
    )

    _generation(db_session, "g-r16-certified-root")
    _manifest(
        db_session,
        "g-r16-certified-root",
        "monthly",
        "2026-08",
        owner_state="owned",
        source_kind="legacy_root",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-r16-certified-root')"
        )
    )
    db_session.commit()
    after = DashboardDataStore(db_session).monthly_settlement(
        store_id="r16-parity", month="2026-08", product_type="all"
    )

    _assert_direct_monthly_metrics(after, receivable=70, commissionable=700, payable=7)
    assert after["metrics"] == before["metrics"]


def test_r16_certified_empty_legacy_root_keeps_exact_legacy_keys(db_session) -> None:
    _generation(db_session, "g-r16-certified-empty")
    _manifest(
        db_session,
        "g-r16-certified-empty",
        "monthly",
        "2026-08",
        owner_state="owned",
        source_kind="legacy_root",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-r16-certified-empty')"
        )
    )
    db_session.commit()

    result = DashboardDataStore(db_session).monthly_settlement(
        store_id="r16-certified-empty", month="2026-08", product_type="all"
    )
    _assert_direct_monthly_metrics(result)


def test_r16_overlay_monthly_direct_metrics_keep_exact_legacy_keys(db_session) -> None:
    _generation(db_session, "g-r16-overlay")
    _manifest(
        db_session,
        "g-r16-overlay",
        "monthly",
        "2026-08",
        owner_state="owned",
        source_kind="overlay",
        data_generation_id="g-r16-overlay",
    )
    db_session.add(
        SettlementMonthlyOverlay(
            generation_id="g-r16-overlay",
            month="2026-08",
            partition_key="2026-08",
            store_id="r16-overlay",
            product_scope="all",
            product_type="all",
            sales_order_count=9,
            promotion_net_fee_cent=90,
            management_net_fee_cent=9,
            estimated_receivable_commission_cent=90,
            commissionable_total_cent=900,
            estimated_payable_commission_cent=9,
        )
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-r16-overlay')"
        )
    )
    db_session.commit()

    result = DashboardDataStore(db_session).monthly_settlement(
        store_id="r16-overlay", month="2026-08", product_type="all"
    )
    _assert_direct_monthly_metrics(result, receivable=90, commissionable=900, payable=9)


def test_r2_active_monthly_tombstone_does_not_resurrect_legacy_row(db_session) -> None:
    legacy_metrics = {
        "estimated_receivable_commission_cent": 120,
        "commissionable_total_cent": 1200,
        "estimated_payable_commission_cent": 12,
    }
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="r2-tombstone",
            product_scope="all",
            product_type="all",
            sales_order_count=12,
            **legacy_metrics,
        )
    )
    _generation(db_session, "g-r2-tombstone", state="published")
    _manifest(
        db_session,
        "g-r2-tombstone",
        "monthly",
        "2026-08",
        owner_state="tombstone",
        source_kind="tombstone",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_active (projection_name, generation_id) "
            "VALUES ('settlement', 'g-r2-tombstone')"
        )
    )
    db_session.commit()

    assert active_generation_id(db_session) == "g-r2-tombstone"
    result = DashboardDataStore(db_session).monthly_settlement(
        store_id="r2-tombstone", month="2026-08", product_type="all"
    )

    _assert_direct_monthly_metrics(result)
    assert result["metrics"] != legacy_metrics
    assert result["metrics"]["commissionable_total_cent"] != legacy_metrics[
        "commissionable_total_cent"
    ]


def test_r17_one_thousand_manifest_keys_stay_below_sqlite_bind_limit(db_session) -> None:
    _generation(db_session, "g-r17-bind")
    keys = [f"r17-{index:04d}" for index in range(1000)]
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_partition_manifest
                (generation_id, artifact, partition_key, owner_state, source_kind,
                 data_generation_id, base_generation_id, row_count, amount_total_cent,
                 status_counts_json, created_at)
            VALUES (:generation_id, 'monthly', :partition_key, 'owned', 'overlay',
                    :generation_id, NULL, 0, 0, '{}', :created_at)
            """
        ),
        [
            {
                "generation_id": "g-r17-bind",
                "partition_key": key,
                "created_at": datetime.now(timezone.utc),
            }
            for key in keys
        ],
    )
    db_session.commit()
    manifest_bind_counts: list[int] = []
    manifest_key_batches: list[int] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "from settlement_projection_partition_manifest" not in statement.lower():
            return
        compiled = getattr(context, "compiled", None)
        compiled_params = getattr(compiled, "params", None)
        if not isinstance(compiled_params, dict):
            return
        manifest_bind_counts.append(len(compiled_params))
        manifest_key_batches.append(
            sum(key.startswith("manifest_partition_") for key in compiled_params)
        )

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        resolved = resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=keys,
            pinned_generation_id="g-r17-bind",
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)
    assert len(resolved) == 1000
    assert resolved[keys[-1]].source_kind == "overlay"
    assert manifest_bind_counts and max(manifest_bind_counts) < 999
    assert manifest_key_batches and max(manifest_key_batches) <= 400
    assert len(manifest_key_batches) >= 3


def test_r17_late_manifest_corruption_fails_closed_after_key_batch_boundary(db_session) -> None:
    if db_session.get_bind().dialect.name == "sqlite":
        db_session.execute(text("PRAGMA foreign_keys=ON"))
    _generation(db_session, "g-r17-late-wrong-base")
    _generation(db_session, "g-r17-late-root")
    _generation(
        db_session,
        "g-r17-late-child",
        base_generation_id="g-r17-late-root",
        depth=1,
    )
    keys = [f"r17-late-{index:04d}" for index in range(1000)]
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_partition_manifest
                (generation_id, artifact, partition_key, owner_state, source_kind,
                 data_generation_id, base_generation_id, row_count, amount_total_cent,
                 status_counts_json, created_at)
            VALUES ('g-r17-late-root', 'monthly', :partition_key, 'owned', 'overlay',
                    'g-r17-late-root', NULL, 0, 0, '{}', :created_at)
            """
        ),
        [
            {"partition_key": key, "created_at": datetime.now(timezone.utc)}
            for key in keys
        ],
    )
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_partition_manifest
                (generation_id, artifact, partition_key, owner_state, source_kind,
                 data_generation_id, base_generation_id, row_count, amount_total_cent,
                 status_counts_json, created_at)
            VALUES ('g-r17-late-child', 'monthly', :partition_key, 'owned', 'overlay',
                    'g-r17-late-child', 'g-r17-late-wrong-base', 0, 0, '{}', :created_at)
            """
        ),
        {
            "partition_key": keys[-1],
            "created_at": datetime.now(timezone.utc),
        },
    )
    db_session.commit()
    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=keys,
            pinned_generation_id="g-r17-late-child",
        )


def test_r18_real_ten_thousand_score_facts_are_streamed_in_bounded_batches(
    db_session,
    monkeypatch,
) -> None:
    run_id = "run-r18-10k"
    db_session.add(
        StoreScoreSnapshotRun(
            snapshot_run_id=run_id,
            snapshot_date=date(2026, 8, 1),
            run_mode="scheduled",
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            candidate_store_count=10000,
            snapshot_count=10000,
            config_json={"rule_version_id": "rule-r18-10k"},
            computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()
    db_session.bulk_insert_mappings(
        StoreScoreSnapshot,
        [
            {
                "snapshot_id": f"{run_id}-{index:05d}",
                "snapshot_run_id": run_id,
                "snapshot_date": date(2026, 8, 1),
                "run_mode": "scheduled",
                "store_id": f"r18-10k-{index:05d}",
                "window_start": datetime(2026, 8, 1, tzinfo=timezone.utc),
                "window_end": datetime(2026, 8, 2, tzinfo=timezone.utc),
                "conversion_value_source": "observed",
                "follow_24h_value_source": "observed",
                "composite_score": 10000 - index,
                "config_json": {"rule_version_id": "rule-r18-10k"},
            }
            for index in range(10000)
        ],
    )
    db_session.commit()
    batch_lengths: list[int] = []
    original_resolve_fact_batch = admin_routes._score_resolve_fact_batch

    def spy_resolve_fact_batch(session, rows, runs_by_id, *, pinned_generation_id):
        batch_lengths.append(len(rows))
        return original_resolve_fact_batch(
            session,
            rows,
            runs_by_id,
            pinned_generation_id=pinned_generation_id,
        )

    monkeypatch.setattr(admin_routes, "_score_resolve_fact_batch", spy_resolve_fact_batch)
    store = SimpleNamespace(available=True, session=db_session)
    first_page = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        page=1,
        page_size=20,
        _username="admin",
        store=store,
    )
    last_page = list_store_score_snapshots(
        snapshot_date=date(2026, 8, 1),
        page=500,
        page_size=20,
        _username="admin",
        store=store,
    )
    assert first_page["data"]["pagination"]["total"] == 10000
    assert last_page["data"]["pagination"]["total"] == 10000
    assert first_page["data"]["rows"][0]["store_id"] == "r18-10k-00000"
    assert last_page["data"]["rows"][-1]["store_id"] == "r18-10k-09999"
    assert batch_lengths and max(batch_lengths) <= admin_routes.SCORE_FACT_BATCH_SIZE


def test_r18_generation_owned_score_batches_count_all_relevant_reads(
    db_session,
    monkeypatch,
) -> None:
    _generation(db_session, "g-r18-owned")
    store_ids = [f"r18-owned-{index:04d}" for index in range(801)]
    _insert_score_run_with_stores(
        db_session,
        run_id="run-r18-owned",
        snapshot_date=date(2026, 8, 1),
        computed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        rule_id="rule-r18-owned",
        store_ids=store_ids,
    )
    db_session.flush()
    sidecar_rows = []
    manifest_rows = []
    for store_id in store_ids:
        key = canonical_score_partition_key(date(2026, 8, 1), "rule-r18-owned", store_id)
        sidecar_rows.append(
            StoreScoreSnapshotGeneration(
                generation_id="g-r18-owned",
                snapshot_run_id="run-r18-owned",
                store_id=store_id,
                rule_version_id="rule-r18-owned",
                snapshot_date=date(2026, 8, 1),
                partition_key=key,
            )
        )
        manifest_rows.append(
            {
                "generation_id": "g-r18-owned",
                "artifact": "score",
                "partition_key": key,
                "created_at": datetime.now(timezone.utc),
            }
        )
    db_session.add_all(sidecar_rows)
    db_session.execute(
        text(
            """
            INSERT INTO settlement_projection_partition_manifest
                (generation_id, artifact, partition_key, owner_state, source_kind,
                 data_generation_id, base_generation_id, row_count, amount_total_cent,
                 status_counts_json, created_at)
            VALUES (:generation_id, :artifact, :partition_key, 'owned', 'overlay',
                    :generation_id, NULL, 1, 0, '{}', :created_at)
            """
        ),
        manifest_rows,
    )
    _activate_generation(db_session, "g-r18-owned")
    db_session.commit()
    batch_lengths: list[int] = []
    original_resolve_fact_batch = admin_routes._score_resolve_fact_batch

    def spy_resolve_fact_batch(session, rows, runs_by_id, *, pinned_generation_id):
        batch_lengths.append(len(rows))
        return original_resolve_fact_batch(
            session,
            rows,
            runs_by_id,
            pinned_generation_id=pinned_generation_id,
        )

    monkeypatch.setattr(admin_routes, "_score_resolve_fact_batch", spy_resolve_fact_batch)
    statement_counts = {
        "candidate": 0,
        "facts": 0,
        "sidecars": 0,
        "manifest": 0,
        "presence": 0,
    }

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if not lowered.lstrip().startswith("select"):
            return
        if "store_score_snapshot_runs" in lowered:
            statement_counts["candidate"] += 1
        if "from store_score_snapshots" in lowered:
            statement_counts["facts"] += 1
        if "from store_score_snapshot_generation" in lowered:
            statement_counts["sidecars"] += 1
            if "count(*)" in lowered:
                statement_counts["presence"] += 1
        if "from settlement_projection_partition_manifest" in lowered:
            statement_counts["manifest"] += 1

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        result = list_store_score_snapshots(
            snapshot_date=date(2026, 8, 1),
            page=41,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)
    assert result["data"]["pagination"]["total"] == 801
    assert len(result["data"]["rows"]) == 1
    assert batch_lengths and max(batch_lengths) <= admin_routes.SCORE_FACT_BATCH_SIZE
    assert 1 <= statement_counts["candidate"] <= 2
    assert 1 <= statement_counts["facts"] <= 8
    assert 1 <= statement_counts["sidecars"] <= 24
    assert 1 <= statement_counts["manifest"] <= 16
    assert 1 <= statement_counts["presence"] <= 16


# ---------------------------------------------------------------------------
# Remediation round 4 (R20-R23): close the in-lineage missing-manifest sidecar
# bypass, bound pinned raw month candidates in SQL, and make the R17 corruption
# fixture valid with foreign-key enforcement.
# ---------------------------------------------------------------------------


def test_r20_in_lineage_sidecar_wrong_date_without_manifest_fails_closed(db_session) -> None:
    _generation(db_session, "g-r20-missing-manifest-date")
    _insert_score_fixture(
        db_session,
        generation_id="g-r20-missing-manifest-date",
        run_id="run-r20-missing-manifest-date",
        rule_id="rule-r15-missing-manifest",
        score=42,
    )
    db_session.flush()
    wrong_date_key = canonical_score_partition_key(
        date(2026, 8, 2), "rule-r15-missing-manifest", "score-store"
    )
    db_session.execute(
        text(
            "UPDATE store_score_snapshot_generation "
            "SET snapshot_date = '2026-08-02', partition_key = :partition_key "
            "WHERE generation_id = 'g-r20-missing-manifest-date' "
            "AND snapshot_run_id = 'run-r20-missing-manifest-date'"
        ),
        {"partition_key": wrong_date_key},
    )
    _activate_generation(db_session, "g-r20-missing-manifest-date")
    db_session.commit()

    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id="run-r20-missing-manifest-date",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r20_in_lineage_sidecar_correct_date_without_manifest_fails_closed(db_session) -> None:
    _generation(db_session, "g-r20-missing-manifest-correct")
    _insert_score_fixture(
        db_session,
        generation_id="g-r20-missing-manifest-correct",
        run_id="run-r20-missing-manifest-correct",
        rule_id="rule-r20-missing-manifest",
        score=42,
    )
    _activate_generation(db_session, "g-r20-missing-manifest-correct")
    db_session.commit()

    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id="run-r20-missing-manifest-correct",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r20_in_lineage_sidecar_explicit_legacy_root_manifest_fails_closed(db_session) -> None:
    _generation(db_session, "g-r20-explicit-legacy")
    partition_key = _insert_score_fixture(
        db_session,
        generation_id="g-r20-explicit-legacy",
        run_id="run-r20-explicit-legacy",
        rule_id="rule-r20-explicit-legacy",
        score=42,
    )
    db_session.flush()
    _manifest(
        db_session,
        "g-r20-explicit-legacy",
        "score",
        partition_key,
        source_kind="legacy_root",
    )
    _activate_generation(db_session, "g-r20-explicit-legacy")
    db_session.commit()

    with pytest.raises(LineageError):
        list_store_score_snapshots(
            snapshot_run_id="run-r20-explicit-legacy",
            page=1,
            page_size=20,
            _username="admin",
            store=SimpleNamespace(available=True, session=db_session),
        )


def test_r20_unrelated_generation_sidecar_remains_ignored(db_session) -> None:
    _generation(db_session, "g-r20-unrelated-sidecar")
    _generation(db_session, "g-r20-active-lineage")
    _insert_score_fixture(
        db_session,
        generation_id="g-r20-unrelated-sidecar",
        run_id="run-r20-unrelated-sidecar",
        rule_id="rule-r20-unrelated",
        score=42,
    )
    _activate_generation(db_session, "g-r20-active-lineage")
    db_session.commit()

    result = list_store_score_snapshots(
        snapshot_run_id="run-r20-unrelated-sidecar",
        page=1,
        page_size=20,
        _username="admin",
        store=SimpleNamespace(available=True, session=db_session),
    )
    assert result["data"]["run"]["snapshot_run_id"] == "run-r20-unrelated-sidecar"
    assert result["data"]["rows"][0]["rule_version_id"] == "rule-r20-unrelated"


def test_r21_pinned_raw_month_candidates_are_sql_bounded_and_newest_first(db_session) -> None:
    _generation(db_session, "g-r21-month-bound")
    month_count = MAX_PARTITION_KEYS + 1
    month_rows = []
    verify_rows = []
    for index in range(month_count):
        month_number = (2020 * 12) + index
        year, month_offset = divmod(month_number, 12)
        month_date = date(year, month_offset + 1, 1)
        timestamp = datetime.combine(month_date, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        month_rows.append(
            {
                "coupon_id": f"r21-coupon-{index:04d}",
                "order_id": f"r21-order-{index:04d}",
                "product_type": "all",
                "sale_time": timestamp,
                "verify_time": timestamp,
            }
        )
        verify_rows.append(
            {
                "verify_id": f"r21-verify-{index:04d}",
                "verify_time": timestamp,
            }
        )
    db_session.bulk_insert_mappings(SettlementOrderDetail, month_rows)
    db_session.bulk_insert_mappings(RawDouyinVerifyRecord, verify_rows)
    _activate_generation(db_session, "g-r21-month-bound")
    db_session.commit()
    raw_statements: list[tuple[str, str]] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if "select distinct" not in lowered:
            return
        for table in (
            "settlement_order_details",
            "raw_douyin_orders",
            "raw_douyin_verify_records",
        ):
            if table in lowered:
                raw_statements.append((table, statement))
                break

    event.listen(db_session.get_bind(), "before_cursor_execute", before_execute)
    try:
        store = DashboardDataStore(db_session)
        sale_months = store.list_sale_months()
        verify_months = store.list_verify_months()
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", before_execute)

    expected_newest = f"{2020 + (month_count - 1) // 12:04d}-{(month_count - 1) % 12 + 1:02d}"
    assert sale_months[0] == expected_newest
    assert verify_months[0] == expected_newest
    assert len(sale_months) <= MAX_PARTITION_KEYS
    assert len(verify_months) <= MAX_PARTITION_KEYS
    assert len(raw_statements) >= 3
    assert all("ORDER BY" in statement.upper() for _, statement in raw_statements)
    assert all("LIMIT" in statement.upper() for _, statement in raw_statements)


# ---------------------------------------------------------------------------
# Remediation round 5 (R24): raw non-NULL blank manifest identifiers must fail
# closed while SQL NULL keeps the existing root/legacy-root/tombstone semantics.
# ---------------------------------------------------------------------------


def _manifest_with_checks_disabled(
    db_session,
    generation_id: str,
    artifact: str,
    partition_key: str,
    *,
    owner_state: str = "owned",
    source_kind: str = "overlay",
    data_generation_id: str | None = None,
    base_generation_id: str | None = None,
) -> None:
    """Insert deliberately corrupt SQLite metadata for resolver-only tests."""

    assert db_session.get_bind().dialect.name == "sqlite"
    db_session.execute(text("PRAGMA ignore_check_constraints = ON"))
    try:
        _manifest(
            db_session,
            generation_id,
            artifact,
            partition_key,
            owner_state=owner_state,
            source_kind=source_kind,
            data_generation_id=data_generation_id,
            base_generation_id=base_generation_id,
        )
    finally:
        db_session.execute(text("PRAGMA ignore_check_constraints = OFF"))


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_r24_root_manifest_blank_base_generation_id_fails_closed(
    db_session,
    blank_value: str,
) -> None:
    _generation(db_session, "g-r24-root-blank-base")
    _manifest_with_checks_disabled(
        db_session,
        "g-r24-root-blank-base",
        "monthly",
        "2026-08",
        source_kind="legacy_root",
        base_generation_id=blank_value,
    )
    db_session.commit()

    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-r24-root-blank-base",
        )


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_r24_legacy_root_manifest_blank_data_generation_id_fails_closed(
    db_session,
    blank_value: str,
) -> None:
    _generation(db_session, "g-r24-legacy-blank-data")
    _manifest_with_checks_disabled(
        db_session,
        "g-r24-legacy-blank-data",
        "monthly",
        "2026-08",
        source_kind="legacy_root",
        data_generation_id=blank_value,
    )
    db_session.commit()

    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-r24-legacy-blank-data",
        )


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_r24_tombstone_manifest_blank_data_generation_id_fails_closed(
    db_session,
    blank_value: str,
) -> None:
    _generation(db_session, "g-r24-tombstone-blank-data")
    _manifest_with_checks_disabled(
        db_session,
        "g-r24-tombstone-blank-data",
        "monthly",
        "2026-08",
        owner_state="tombstone",
        source_kind="tombstone",
        data_generation_id=blank_value,
    )
    db_session.commit()

    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id="g-r24-tombstone-blank-data",
        )


def test_r24_sql_null_manifest_controls_keep_existing_resolution_semantics(db_session) -> None:
    _generation(db_session, "g-r24-null-controls")
    _manifest(
        db_session,
        "g-r24-null-controls",
        "monthly",
        "2026-08",
        source_kind="legacy_root",
        data_generation_id=None,
        base_generation_id=None,
    )
    _manifest(
        db_session,
        "g-r24-null-controls",
        "monthly",
        "2026-09",
        owner_state="tombstone",
        source_kind="tombstone",
        data_generation_id=None,
        base_generation_id=None,
    )
    db_session.commit()

    resolved = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["2026-08", "2026-09", "2026-10"],
        pinned_generation_id="g-r24-null-controls",
    )
    assert resolved["2026-08"].source_kind == "legacy_root"
    assert resolved["2026-08"].actual_data_generation_id is None
    assert resolved["2026-09"].source_kind == "tombstone"
    assert resolved["2026-09"].actual_data_generation_id is None
    assert resolved["2026-10"].source_kind == "legacy_root"
    assert resolved["2026-10"].actual_data_generation_id is None


def _compact_generation_fixture(
    db_session,
    generation_id: str,
    *,
    generation_kind: str,
    state: str,
    manifest_checksum: str,
    compaction_base_generation_id: str | None = None,
) -> None:
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_generation "
            "(generation_id, base_generation_id, generation_kind, "
            "compaction_base_generation_id, projection_name, state, "
            "input_fingerprint, lineage_depth, estimated_write_rows, "
            "estimated_write_bytes, estimated_wal_bytes, "
            "estimated_disk_headroom_bytes, checkpoint_json, manifest_checksum, "
            "source_input_json, created_at, published_at) VALUES "
            "(:generation_id, NULL, :generation_kind, :compaction_base_generation_id, "
            "'settlement', :state, :fingerprint, 0, 0, 0, 0, 0, '{}', "
            ":manifest_checksum, '{}', :now, :now)"
        ),
        {
            "generation_id": generation_id,
            "generation_kind": generation_kind,
            "compaction_base_generation_id": compaction_base_generation_id,
            "state": state,
            "fingerprint": f"compact-fixture-{generation_id}",
            "manifest_checksum": manifest_checksum,
            "now": datetime.now(timezone.utc),
        },
    )


def _compact_evidence_manifest(
    db_session,
    *,
    generation_id: str,
    partition_key: str,
    data_generation_id: str,
    reference_head_generation_id: str | None,
    checksum: str,
    artifact: str = "monthly",
    row_count: int = 1,
    amount_total_cent: int = 100,
    status_counts: str = '{"1":1}',
) -> None:
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_partition_manifest "
            "(generation_id, artifact, partition_key, owner_state, source_kind, "
            "data_generation_id, base_generation_id, reference_head_generation_id, "
            "row_count, amount_total_cent, status_counts_json, checksum, created_at, "
            "published_at) VALUES "
            "(:generation_id, :artifact, :partition_key, 'owned', 'overlay', "
            ":data_generation_id, NULL, :reference_head_generation_id, "
            ":row_count, :amount_total_cent, "
            ":status_counts, :checksum, :now, :now)"
        ),
        {
            "generation_id": generation_id,
            "artifact": artifact,
            "partition_key": partition_key,
            "data_generation_id": data_generation_id,
            "reference_head_generation_id": reference_head_generation_id,
            "row_count": row_count,
            "amount_total_cent": amount_total_cent,
            "status_counts": status_counts,
            "checksum": checksum,
            "now": datetime.now(timezone.utc),
        },
    )


def test_compact_resolution_selects_only_the_partition_detached_source(db_session) -> None:
    source_digest = "a" * 64
    partition_digest = "b" * 64
    _compact_generation_fixture(
        db_session,
        "compact-source",
        generation_kind="legacy_root",
        state="superseded",
        manifest_checksum=source_digest,
    )
    _compact_generation_fixture(
        db_session,
        "compact-head",
        generation_kind="compact",
        state="published",
        manifest_checksum="c" * 64,
        compaction_base_generation_id="compact-source",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_compaction_closure "
            "(compact_generation_id, source_generation_id, source_digest) "
            "VALUES ('compact-head', 'compact-source', :source_digest)"
        ),
        {"source_digest": source_digest},
    )
    _compact_evidence_manifest(
        db_session,
        generation_id="compact-source",
        partition_key="2026-08",
        data_generation_id="compact-source",
        reference_head_generation_id=None,
        checksum=partition_digest,
    )
    _compact_evidence_manifest(
        db_session,
        generation_id="compact-head",
        partition_key="2026-08",
        data_generation_id="compact-source",
        reference_head_generation_id="compact-head",
        checksum=partition_digest,
    )
    db_session.add(
        SettlementMonthlyOverlay(
            generation_id="compact-source",
            month="2026-08",
            partition_key="2026-08",
            store_id="compact-store",
            product_scope="all",
            product_type="all",
            sales_order_count=1,
            sales_amount_cent=100,
            statement_status=1,
        )
    )
    db_session.commit()

    resolution = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["2026-08"],
        pinned_generation_id="compact-head",
    )["2026-08"]

    assert resolution.nearest_manifest_owner_generation == "compact-head"
    assert resolution.actual_data_generation_id == "compact-source"
    assert resolution.lineage_generation_ids == frozenset({"compact-head"})
    assert resolution.source_generation_ids == frozenset({"compact-source"})


def _seed_valid_compact_monthly(db_session, prefix: str) -> tuple[str, str]:
    source_id = f"{prefix}-source"
    head_id = f"{prefix}-head"
    source_digest = "a" * 64
    partition_digest = "b" * 64
    _compact_generation_fixture(
        db_session,
        source_id,
        generation_kind="legacy_root",
        state="superseded",
        manifest_checksum=source_digest,
    )
    _compact_generation_fixture(
        db_session,
        head_id,
        generation_kind="compact",
        state="published",
        manifest_checksum="c" * 64,
        compaction_base_generation_id=source_id,
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_compaction_closure "
            "(compact_generation_id, source_generation_id, source_digest) "
            "VALUES (:head_id, :source_id, :source_digest)"
        ),
        {
            "head_id": head_id,
            "source_id": source_id,
            "source_digest": source_digest,
        },
    )
    _compact_evidence_manifest(
        db_session,
        generation_id=source_id,
        partition_key="2026-08",
        data_generation_id=source_id,
        reference_head_generation_id=None,
        checksum=partition_digest,
    )
    _compact_evidence_manifest(
        db_session,
        generation_id=head_id,
        partition_key="2026-08",
        data_generation_id=source_id,
        reference_head_generation_id=head_id,
        checksum=partition_digest,
    )
    db_session.add(
        SettlementMonthlyOverlay(
            generation_id=source_id,
            month="2026-08",
            partition_key="2026-08",
            store_id=f"{prefix}-store",
            product_scope="all",
            product_type="all",
            sales_order_count=1,
            sales_amount_cent=100,
            statement_status=1,
        )
    )
    db_session.commit()
    return source_id, head_id


@pytest.mark.parametrize(
    "mutation_sql,mutation_params",
    [
        (
            "UPDATE settlement_projection_compaction_closure "
            "SET source_digest = :replacement WHERE compact_generation_id = :head_id",
            {"replacement": "d" * 64},
        ),
        (
            "UPDATE settlement_projection_generation SET state = 'staging' "
            "WHERE generation_id = :source_id",
            {},
        ),
        (
            "UPDATE settlement_projection_generation SET manifest_checksum = NULL "
            "WHERE generation_id = :source_id",
            {},
        ),
        (
            "UPDATE settlement_projection_generation SET manifest_checksum = :replacement "
            "WHERE generation_id = :source_id",
            {"replacement": " " + "a" * 64},
        ),
        (
            "UPDATE settlement_projection_generation "
            "SET generation_kind = 'compact', compaction_base_generation_id = :head_id "
            "WHERE generation_id = :source_id",
            {},
        ),
        (
            "UPDATE settlement_projection_partition_manifest SET checksum = :replacement "
            "WHERE generation_id = :source_id AND artifact = 'monthly'",
            {"replacement": "d" * 64},
        ),
        (
            "UPDATE settlement_projection_partition_manifest SET row_count = 2 "
            "WHERE generation_id = :source_id AND artifact = 'monthly'",
            {},
        ),
        (
            "UPDATE settlement_projection_partition_manifest SET amount_total_cent = 101 "
            "WHERE generation_id = :source_id AND artifact = 'monthly'",
            {},
        ),
        (
            "UPDATE settlement_projection_partition_manifest "
            "SET status_counts_json = :replacement "
            "WHERE generation_id = :source_id AND artifact = 'monthly'",
            {"replacement": '{"2":1}'},
        ),
        (
            "UPDATE settlement_projection_partition_manifest "
            "SET status_counts_json = :replacement "
            "WHERE generation_id = :source_id AND artifact = 'monthly'",
            {"replacement": '{"1":1.0}'},
        ),
        (
            "UPDATE settlement_projection_partition_manifest SET base_generation_id = :head_id "
            "WHERE generation_id = :source_id AND artifact = 'monthly'",
            {},
        ),
        (
            "DELETE FROM settlement_projection_partition_manifest "
            "WHERE generation_id = :source_id AND artifact = 'monthly'",
            {},
        ),
        (
            "DELETE FROM settlement_monthly_overlay WHERE generation_id = :source_id",
            {},
        ),
    ],
)
def test_compact_resolution_rejects_corrupt_detached_source_evidence(
    db_session,
    mutation_sql: str,
    mutation_params: dict[str, str],
) -> None:
    source_id, head_id = _seed_valid_compact_monthly(db_session, "compact-corrupt")
    db_session.execute(
        text(mutation_sql),
        {"source_id": source_id, "head_id": head_id, **mutation_params},
    )
    db_session.commit()

    with pytest.raises(LineageError):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id=head_id,
        )


def test_compact_resolution_requires_exact_source_presence(db_session) -> None:
    source_id, head_id = _seed_valid_compact_monthly(db_session, "compact-extra")
    db_session.add(
        SettlementMonthlyOverlay(
            generation_id=source_id,
            month="2026-08",
            partition_key="2026-08",
            store_id="compact-extra-second-store",
            product_scope="all",
            product_type="all",
            sales_order_count=1,
            sales_amount_cent=1,
            statement_status=1,
        )
    )
    db_session.commit()

    with pytest.raises(LineageError, match="row count"):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-08"],
            pinned_generation_id=head_id,
        )


def test_compact_tombstone_and_missing_partition_keep_source_set_empty(db_session) -> None:
    _, head_id = _seed_valid_compact_monthly(db_session, "compact-sparse")
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_partition_manifest "
            "(generation_id, artifact, partition_key, owner_state, source_kind, "
            "data_generation_id, base_generation_id, reference_head_generation_id, "
            "row_count, amount_total_cent, status_counts_json, created_at) VALUES "
            "(:head_id, 'monthly', '2026-09', 'tombstone', 'tombstone', "
            "NULL, NULL, NULL, 0, 0, '{}', :now)"
        ),
        {"head_id": head_id, "now": datetime.now(timezone.utc)},
    )
    db_session.commit()

    resolved = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["2026-08", "2026-09", "2026-10"],
        pinned_generation_id=head_id,
    )

    assert resolved["2026-08"].source_generation_ids
    assert resolved["2026-09"].source_kind == "tombstone"
    assert resolved["2026-09"].source_generation_ids == frozenset()
    assert resolved["2026-10"].source_kind == "legacy_root"
    assert resolved["2026-10"].source_generation_ids == frozenset()


def test_compact_head_rejects_explicit_legacy_root_manifest(db_session) -> None:
    _, head_id = _seed_valid_compact_monthly(db_session, "compact-explicit-legacy")
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_partition_manifest "
            "(generation_id, artifact, partition_key, owner_state, source_kind, "
            "data_generation_id, base_generation_id, reference_head_generation_id, "
            "row_count, amount_total_cent, status_counts_json, created_at) VALUES "
            "(:head_id, 'monthly', '2026-09', 'owned', 'legacy_root', "
            "NULL, NULL, NULL, 0, 0, '{}', :now)"
        ),
        {"head_id": head_id, "now": datetime.now(timezone.utc)},
    )
    db_session.commit()

    with pytest.raises(LineageError, match="compact manifest"):
        resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=["2026-09"],
            pinned_generation_id=head_id,
        )


def _seed_compact_closure_sources(
    db_session,
    *,
    prefix: str,
    source_count: int,
) -> tuple[str, list[str]]:
    source_ids: list[str] = []
    closure_rows: list[dict[str, str]] = []
    for index in range(source_count):
        source_id = f"{prefix}-source-{index:02d}"
        digest = f"{index + 1:064x}"
        _compact_generation_fixture(
            db_session,
            source_id,
            generation_kind="legacy_root",
            state="superseded",
            manifest_checksum=digest,
        )
        source_ids.append(source_id)
        closure_rows.append(
            {"source_id": source_id, "source_digest": digest}
        )
    head_id = f"{prefix}-head"
    _compact_generation_fixture(
        db_session,
        head_id,
        generation_kind="compact",
        state="published",
        manifest_checksum="f" * 64,
        compaction_base_generation_id=source_ids[0],
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_compaction_closure "
            "(compact_generation_id, source_generation_id, source_digest) "
            "VALUES (:head_id, :source_id, :source_digest)"
        ),
        [{"head_id": head_id, **row} for row in closure_rows],
    )
    db_session.commit()
    return head_id, source_ids


def test_compact_closure_accepts_65_sources_and_rejects_66_before_row_reads(
    db_session,
) -> None:
    head_65, _ = _seed_compact_closure_sources(
        db_session,
        prefix="compact-limit-ok",
        source_count=MAX_LINEAGE_DEPTH + 1,
    )
    resolved = resolve_projection_partitions(
        db_session,
        artifact="monthly",
        partition_keys=["missing"],
        pinned_generation_id=head_65,
    )["missing"]
    assert resolved.source_kind == "legacy_root"
    assert resolved.source_generation_ids == frozenset()

    head_66, _ = _seed_compact_closure_sources(
        db_session,
        prefix="compact-limit-bad",
        source_count=MAX_LINEAGE_DEPTH + 2,
    )
    observed_sql: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        observed_sql.append(statement.lower())

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_sql)
    try:
        with pytest.raises(LineageError, match="maximum source count"):
            resolve_projection_partitions(
                db_session,
                artifact="monthly",
                partition_keys=["missing"],
                pinned_generation_id=head_66,
            )
    finally:
        event.remove(bind, "before_cursor_execute", capture_sql)
    assert not any(
        "from settlement_projection_partition_manifest" in statement
        or "from settlement_monthly_overlay" in statement
        for statement in observed_sql
    )


def test_compact_1000_partition_resolution_is_set_based_and_bind_bounded(
    db_session,
) -> None:
    source_id = "compact-1000-source"
    head_id = "compact-1000-head"
    source_digest = "a" * 64
    checksum = "b" * 64
    _compact_generation_fixture(
        db_session,
        source_id,
        generation_kind="legacy_root",
        state="superseded",
        manifest_checksum=source_digest,
    )
    _compact_generation_fixture(
        db_session,
        head_id,
        generation_kind="compact",
        state="published",
        manifest_checksum="c" * 64,
        compaction_base_generation_id=source_id,
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_compaction_closure "
            "(compact_generation_id, source_generation_id, source_digest) "
            "VALUES (:head_id, :source_id, :source_digest)"
        ),
        {
            "head_id": head_id,
            "source_id": source_id,
            "source_digest": source_digest,
        },
    )
    keys = [f"p{index:04d}" for index in range(MAX_PARTITION_KEYS)]
    now = datetime.now(timezone.utc)
    manifest_sql = text(
        "INSERT INTO settlement_projection_partition_manifest "
        "(generation_id, artifact, partition_key, owner_state, source_kind, "
        "data_generation_id, base_generation_id, reference_head_generation_id, "
        "row_count, amount_total_cent, status_counts_json, checksum, created_at) "
        "VALUES (:generation_id, 'monthly', :partition_key, 'owned', 'overlay', "
        ":source_id, NULL, :reference_head, 1, 100, :status_counts, :checksum, :now)"
    )
    source_manifest_rows = [
        {
            "generation_id": source_id,
            "partition_key": key,
            "source_id": source_id,
            "reference_head": None,
            "status_counts": '{"1":1}',
            "checksum": checksum,
            "now": now,
        }
        for key in keys
    ]
    head_manifest_rows = [
        {
            "generation_id": head_id,
            "partition_key": key,
            "source_id": source_id,
            "reference_head": head_id,
            "status_counts": '{"1":1}',
            "checksum": checksum,
            "now": now,
        }
        for key in keys
    ]
    db_session.execute(manifest_sql, source_manifest_rows)
    db_session.execute(manifest_sql, head_manifest_rows)
    db_session.add_all(
        [
            SettlementMonthlyOverlay(
                generation_id=source_id,
                month=key,
                partition_key=key,
                store_id=f"store-{index:04d}",
                product_scope="all",
                product_type="all",
                sales_order_count=1,
                sales_amount_cent=100,
                statement_status=1,
            )
            for index, key in enumerate(keys)
        ]
    )
    db_session.commit()

    observed: list[tuple[str, int]] = []

    def capture_sql(_conn, _cursor, statement, parameters, _context, _executemany):
        normalized = statement.lstrip().lower()
        if normalized.startswith("select") or normalized.startswith("with"):
            observed.append((normalized, len(parameters)))

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_sql)
    try:
        resolved = resolve_projection_partitions(
            db_session,
            artifact="monthly",
            partition_keys=keys,
            pinned_generation_id=head_id,
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture_sql)

    assert len(resolved) == MAX_PARTITION_KEYS
    assert all(
        value.source_generation_ids == frozenset({source_id})
        for value in resolved.values()
    )
    assert len(observed) <= 11
    assert max(bound_count for _, bound_count in observed) < 999


def test_compact_1001_partition_request_rejects_before_database_read(db_session) -> None:
    observed: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        observed.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_sql)
    try:
        with pytest.raises(LineageError, match="maximum"):
            resolve_projection_partitions(
                db_session,
                artifact="monthly",
                partition_keys=[f"p{index:04d}" for index in range(MAX_PARTITION_KEYS + 1)],
                pinned_generation_id="unread-compact-head",
            )
    finally:
        event.remove(bind, "before_cursor_execute", capture_sql)
    assert observed == []


def test_compact_ranking_monthly_and_cumulative_partitions_resolve(db_session) -> None:
    source_id = "compact-ranking-source"
    head_id = "compact-ranking-head"
    source_digest = "a" * 64
    partition_digest = "b" * 64
    _compact_generation_fixture(
        db_session,
        source_id,
        generation_kind="lineage",
        state="superseded",
        manifest_checksum=source_digest,
    )
    _compact_generation_fixture(
        db_session,
        head_id,
        generation_kind="compact",
        state="published",
        manifest_checksum="c" * 64,
        compaction_base_generation_id=source_id,
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_compaction_closure "
            "(compact_generation_id, source_generation_id, source_digest) "
            "VALUES (:head_id, :source_id, :source_digest)"
        ),
        {
            "head_id": head_id,
            "source_id": source_id,
            "source_digest": source_digest,
        },
    )
    for key in ("monthly:2026-08", "cumulative:2026-08"):
        _compact_evidence_manifest(
            db_session,
            generation_id=source_id,
            artifact="ranking",
            partition_key=key,
            data_generation_id=source_id,
            reference_head_generation_id=None,
            checksum=partition_digest,
            status_counts="{}",
        )
        _compact_evidence_manifest(
            db_session,
            generation_id=head_id,
            artifact="ranking",
            partition_key=key,
            data_generation_id=source_id,
            reference_head_generation_id=head_id,
            checksum=partition_digest,
            status_counts="{}",
        )
    db_session.add_all(
        [
            SettlementRankingOverlay(
                generation_id=source_id,
                period_type=period_type,
                period_key="2026-08",
                month="2026-08",
                partition_key=partition_key,
                store_id=f"compact-ranking-{period_type}",
                store_name="Compact ranking",
                product_scope="all",
                product_type="all",
                sales_order_count=1,
                sales_amount_cent=100,
                promotion_net_fee_cent=100,
                management_net_fee_cent=20,
                net_settlement_reference_cent=80,
                projection_run_id=source_id,
            )
            for period_type, partition_key in (
                (1, "monthly:2026-08"),
                (2, "cumulative:2026-08"),
            )
        ]
    )
    db_session.commit()

    resolved = resolve_projection_partitions(
        db_session,
        artifact="ranking",
        partition_keys=["monthly:2026-08", "cumulative:2026-08"],
        pinned_generation_id=head_id,
    )
    assert all(
        resolution.actual_data_generation_id == source_id
        and resolution.source_generation_ids == frozenset({source_id})
        for resolution in resolved.values()
    )


def test_compact_a09_selects_only_partition_source_and_tombstone_stays_hidden(
    db_session,
) -> None:
    head_id, source_ids = _seed_compact_closure_sources(
        db_session,
        prefix="compact-a09",
        source_count=2,
    )
    selected_source, stale_source = source_ids
    selected_key = canonical_score_partition_key(
        date(2026, 8, 1), "rule-compact", "store-selected"
    )
    tombstone_key = canonical_score_partition_key(
        date(2026, 8, 1), "rule-hidden", "store-hidden"
    )
    _compact_evidence_manifest(
        db_session,
        generation_id=selected_source,
        artifact="score",
        partition_key=selected_key,
        data_generation_id=selected_source,
        reference_head_generation_id=None,
        checksum="b" * 64,
        amount_total_cent=0,
        status_counts="{}",
    )
    _compact_evidence_manifest(
        db_session,
        generation_id=head_id,
        artifact="score",
        partition_key=selected_key,
        data_generation_id=selected_source,
        reference_head_generation_id=head_id,
        checksum="b" * 64,
        amount_total_cent=0,
        status_counts="{}",
    )
    db_session.execute(
        text(
            "INSERT INTO settlement_projection_partition_manifest "
            "(generation_id, artifact, partition_key, owner_state, source_kind, "
            "data_generation_id, base_generation_id, reference_head_generation_id, "
            "row_count, amount_total_cent, status_counts_json, created_at) VALUES "
            "(:head_id, 'score', :partition_key, 'tombstone', 'tombstone', "
            "NULL, NULL, NULL, 0, 0, '{}', :now)"
        ),
        {
            "head_id": head_id,
            "partition_key": tombstone_key,
            "now": datetime.now(timezone.utc),
        },
    )
    sidecar_sql = text(
        "INSERT INTO store_score_snapshot_generation "
        "(generation_id, snapshot_run_id, store_id, rule_version_id, "
        "snapshot_date, partition_key, owner_state, created_at) VALUES "
        "(:generation_id, :run_id, :store_id, :rule_id, '2026-08-01', "
        ":partition_key, 'owned', :now)"
    )
    db_session.execute(
        sidecar_sql,
        [
            {
                "generation_id": selected_source,
                "run_id": "run-selected",
                "store_id": "store-selected",
                "rule_id": "rule-compact",
                "partition_key": selected_key,
                "now": datetime.now(timezone.utc),
            },
            {
                "generation_id": stale_source,
                "run_id": "run-selected",
                "store_id": "store-selected",
                "rule_id": "rule-compact",
                "partition_key": selected_key,
                "now": datetime.now(timezone.utc),
            },
            {
                "generation_id": selected_source,
                "run_id": "run-hidden",
                "store_id": "store-hidden",
                "rule_id": "rule-hidden",
                "partition_key": tombstone_key,
                "now": datetime.now(timezone.utc),
            },
        ],
    )
    db_session.commit()

    selected = _score_sidecar_rule_map(
        db_session,
        snapshot_run_ids=["run-selected"],
        pinned_generation_id=head_id,
        identities=[("run-selected", "store-selected")],
    )
    hidden = _score_sidecar_rule_map(
        db_session,
        snapshot_run_ids=["run-hidden"],
        pinned_generation_id=head_id,
        identities=[("run-hidden", "store-hidden")],
    )
    assert selected == {("run-selected", "store-selected"): "rule-compact"}
    assert hidden == {}
