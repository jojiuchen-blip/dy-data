"""Ordinary verify identities must not authorize historical POI fanout."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    DimStore,
    DimStorePoiMapping,
    JobImpact,
    JobStageRun,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementOrderDetail,
    SettlementStatementEntry,
)
import apps.worker.settlement as settlement_worker
from apps.worker.daily_task import _normalize_incremental_settlement_summary
from apps.worker.stage_runner import run_daily_stages
from test_data_settlement_incremental_postgres import (
    POSTGRES_URL,
    postgres_stack,  # noqa: F401
)
from test_data_settlement_incremental import _coupon_local_snapshot, _seed_local_coupon
from test_worker_stage_transactions import _seed_job


@pytest.fixture(params=("sqlite", "postgres"))
def selector_factory(request, db_session):
    if request.param == "postgres":
        if not POSTGRES_URL:
            pytest.skip("dedicated local PostgreSQL test URL is not configured")
        _engine, factory = request.getfixturevalue("postgres_stack")
        with factory.begin() as session:
            for model in (
                SettlementOrderDetail, JobImpact, RawDouyinVerifyRecord,
                RawDouyinOrderCoupon, RawDouyinOrder, DimStorePoiMapping, DimStore,
            ):
                session.execute(delete(model))
        return factory
    db_session.commit()
    return sessionmaker(bind=db_session.get_bind(), future=True)


def _seed_coupon(session, coupon_id, *, poi_id=None, intention_poi_id=None):
    order_id = f"order-{coupon_id}"
    session.add(RawDouyinOrder(order_id=order_id, intention_poi_id=intention_poi_id))
    session.flush()
    session.add(RawDouyinOrderCoupon(coupon_id=coupon_id, order_id=order_id))
    if poi_id is not None:
        session.add(RawDouyinVerifyRecord(
            verify_id=f"verify-{coupon_id}", coupon_id=coupon_id, poi_id=poi_id,
            verify_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ))
    session.flush()


def _impact(run_id, *, entity_type="verify", entity_key="verify-exact", **values):
    return JobImpact(
        impact_key=f"{run_id}-{entity_key}", source_run_id=run_id,
        entity_type=entity_type, entity_key=entity_key, **values,
    )


def _record_batches(monkeypatch):
    visited = []

    def settle_batch(_factory, *, coupon_ids, **_kwargs):
        visited.extend(coupon_ids)
        return {
            "detail_count": 0, "result_count": 0, "adjustment_count": 0,
            "affected_months": [], "affected_store_ids": [],
        }

    monkeypatch.setattr(settlement_worker, "_settle_coupon_batch", settle_batch)
    return visited


@pytest.mark.parametrize("impact_batch_size", (1, 64))
def test_verify_insert_and_crosspage_exclude_same_poi_and_intention_history(
    selector_factory, monkeypatch, impact_batch_size,
):
    run_id = f"verify-inserts-{impact_batch_size}"
    with selector_factory.begin() as session:
        for coupon_id in ("exact-a", "exact-b", "history-verify"):
            _seed_coupon(session, coupon_id, poi_id="poi-shared")
        _seed_coupon(session, "history-intention", intention_poi_id="poi-shared")
        _seed_coupon(session, "history-enriched", intention_poi_id="poi-sale")
        for coupon_id in ("exact-a", "exact-b"):
            session.add(_impact(
                run_id, entity_key=f"verify-{coupon_id}",
                old_values_json={}, new_values_json={"coupon_id": coupon_id, "poi_id": "poi-shared"},
                affected_closure_json={
                    "coupon_ids": [coupon_id], "poi_ids": ["poi-shared", "poi-sale"],
                    "order_ids": [f"order-{coupon_id}"], "store_ids": ["store-old", "store-new"],
                    "affected_months": ["2026-09", "2026-10"],
                },
            ))
    visited = _record_batches(monkeypatch)
    result = settlement_worker.settle_impacted_coupons(
        selector_factory, run_id, None, impact_batch_size, 1,
    )
    assert result["completed"] is True
    assert visited == ["exact-a", "exact-b"]
    assert result["coupon_count"] == 2
    assert result["affected_months"] == ["2026-09", "2026-10"]
    assert result["affected_store_ids"] == ["store-new", "store-old"]


def test_verify_update_selects_old_new_coupon_and_verify_identities(selector_factory, monkeypatch):
    run_id = "verify-update"
    with selector_factory.begin() as session:
        for coupon_id in ("old", "new", "via-old-verify", "via-new-verify", "history"):
            _seed_coupon(session, coupon_id, poi_id="poi-update")
        session.add(_impact(
            run_id, old_values_json={
                "coupon_id": "old", "verify_id": "verify-via-old-verify",
                "verify_time": "2026-08-31T23:30:00Z", "store_ids": ["store-old"],
            }, new_values_json={
                "coupon_id": "new", "verify_id": "verify-via-new-verify",
                "verify_time": "2026-10-01T00:00:00Z", "store_ids": ["store-new"],
            }, affected_closure_json={"poi_ids": ["poi-update"]},
        ))
    visited = _record_batches(monkeypatch)
    result = settlement_worker.settle_impacted_coupons(selector_factory, run_id, None, 64, 2)
    assert visited == ["new", "old", "via-new-verify", "via-old-verify"]
    assert result["affected_months"] == ["2026-08", "2026-09", "2026-10"]
    assert result["affected_store_ids"] == ["store-new", "store-old"]


def test_verify_id_only_uses_exact_raw_identity(selector_factory, monkeypatch):
    run_id = "verify-id-only"
    with selector_factory.begin() as session:
        _seed_coupon(session, "fallback", poi_id="poi-fallback")
        _seed_coupon(session, "unrelated", poi_id="poi-fallback")
        session.add(_impact(
            run_id, entity_key="verify-fallback",
            affected_closure_json={"poi_ids": ["poi-fallback"]},
        ))
    visited = _record_batches(monkeypatch)
    result = settlement_worker.settle_impacted_coupons(selector_factory, run_id, None, 64, 1)
    assert result["completed"] is True
    assert visited == ["fallback"]


def test_mapping_preserves_full_historical_old_new_poi_and_store_links(selector_factory, monkeypatch):
    run_id = "mapping-history"
    with selector_factory.begin() as session:
        session.add_all([
            DimStore(store_id="store-map-old", store_name="Old"),
            DimStore(store_id="store-map-new", store_name="New"),
        ])
        session.flush()
        session.add_all([
            DimStorePoiMapping(store_id="store-map-old", poi_id="poi-old-store-link"),
            DimStorePoiMapping(store_id="store-map-new", poi_id="poi-new-store-link"),
        ])
        for prefix, poi_id in (
            ("old", "poi-old"), ("new", "poi-new"),
            ("old-store", "poi-old-store-link"), ("new-store", "poi-new-store-link"),
        ):
            _seed_coupon(session, f"{prefix}-verify", poi_id=poi_id)
            _seed_coupon(session, f"{prefix}-intention", intention_poi_id=poi_id)
        _seed_coupon(session, "mapping-unrelated", poi_id="poi-unrelated")
        session.add(_impact(
            run_id, entity_type="store_poi_mapping", entity_key="poi-new",
            old_values_json={"poi_id": "poi-old", "store_id": "store-map-old"},
            new_values_json={"poi_id": "poi-new", "store_id": "store-map-new"},
        ))
    visited = _record_batches(monkeypatch)
    result = settlement_worker.settle_impacted_coupons(selector_factory, run_id, None, 1, 2)
    assert result["completed"] is True
    assert visited == sorted(
        f"{prefix}-{kind}"
        for prefix in ("old", "new", "old-store", "new-store")
        for kind in ("verify", "intention")
    )
    assert result["coupon_count"] == 8


@pytest.mark.parametrize("raw_coupon_available", (True, False))
def test_verify_id_falls_back_to_exact_historical_detail(
    selector_factory, monkeypatch, raw_coupon_available,
):
    run_id = "verify-detail-fallback"
    with selector_factory.begin() as session:
        _seed_coupon(session, "old-detail")
        _seed_coupon(session, "new-raw", poi_id="poi-fallback-detail")
        _seed_coupon(session, "detail-unrelated", poi_id="poi-fallback-detail")
        session.add(SettlementOrderDetail(
            coupon_id="old-detail", order_id="order-old-detail",
            verify_id="verify-new-raw", product_type="service",
        ))
        if not raw_coupon_available:
            session.get(RawDouyinVerifyRecord, "verify-new-raw").coupon_id = None
        session.add(_impact(
            run_id, entity_key="verify-new-raw",
            affected_closure_json={"poi_ids": ["poi-fallback-detail"]},
        ))
    visited = _record_batches(monkeypatch)
    result = settlement_worker.settle_impacted_coupons(selector_factory, run_id, None, 64, 1)
    assert visited == (["new-raw", "old-detail"] if raw_coupon_available else ["old-detail"])
    assert result["unresolved_verify_impact_count"] == 0


def test_unresolved_verify_identities_are_counted_without_store_fanout(selector_factory, monkeypatch):
    run_id = "verify-orphans"
    with selector_factory.begin() as session:
        _seed_coupon(session, "orphan-unrelated", poi_id="poi-orphan")
        session.add(RawDouyinVerifyRecord(verify_id="verify-null-coupon", coupon_id=None))
        session.add(SettlementOrderDetail(
            coupon_id="deleted-coupon", order_id="deleted-order",
            verify_id="verify-detail-orphan", product_type="service",
        ))
        for key, new_values in (
            ("verify-null-coupon", {}), ("verify-missing", {}),
            ("verify-detail-orphan", {}), ("verify-deleted", {"coupon_id": "deleted-coupon"}),
            ("", {}),
        ):
            session.add(_impact(
                run_id, entity_key=key, new_values_json=new_values,
                affected_closure_json={
                    "poi_ids": ["poi-orphan"], "store_ids": ["store-orphan"],
                    "affected_months": ["2026-06"],
                },
            ))
    visited = _record_batches(monkeypatch)
    result = settlement_worker.settle_impacted_coupons(selector_factory, run_id, None, 2, 1)
    assert result["completed"] is True  # Stream consumed; orphan fees remain unresolved.
    assert result["impact_count"] == result["unresolved_verify_impact_count"] == 5
    assert visited == []
    assert result["affected_months"] == ["2026-06"]
    assert result["affected_store_ids"] == ["store-orphan"]


def test_unresolved_count_survives_normalization_and_durable_stage_checkpoint(db_session):
    _seed_job(db_session, "verify-orphan-checkpoint")
    db_session.add(_impact("verify-orphan-checkpoint", entity_key="verify-checkpoint-orphan"))
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)

    def settle(_session):
        summary = settlement_worker.settle_impacted_coupons(
            factory, "verify-orphan-checkpoint", None, 64, 1,
        )
        return {"settlement_summary": _normalize_incremental_settlement_summary(summary)}

    run_daily_stages(
        factory, job_id="verify-orphan-checkpoint",
        handlers={"collect": lambda _session: None, "materialize": lambda _session: None, "settle": settle},
    )
    with factory() as session:
        stage = session.scalar(select(JobStageRun).where(
            JobStageRun.job_id == "verify-orphan-checkpoint", JobStageRun.stage_name == "settle",
        ))
        assert stage.checkpoint_json["settlement_summary"]["unresolved_verify_impact_count"] == 1
        assert stage.checkpoint_json["settlement_summary"]["completed"] is True


def test_legitimate_same_coupon_impacts_keep_existing_crosspage_semantics(selector_factory, monkeypatch):
    run_id = "verify-legitimate-repeat"
    with selector_factory.begin() as session:
        _seed_coupon(session, "repeated", poi_id="poi-repeat")
        _seed_coupon(session, "repeat-unrelated", poi_id="poi-repeat")
        for key in ("verify-repeat-a", "verify-repeat-b"):
            session.add(_impact(
                run_id, entity_key=key, new_values_json={"coupon_id": "repeated"},
                affected_closure_json={"poi_ids": ["poi-repeat"]},
            ))
    visited = _record_batches(monkeypatch)
    result = settlement_worker.settle_impacted_coupons(selector_factory, run_id, None, 1, 1)
    assert visited == ["repeated", "repeated"]
    assert result["unresolved_verify_impact_count"] == 0


def test_verify_selection_keeps_unchanged_fees_and_locked_history_intact(db_session):
    exact = _seed_local_coupon(db_session, "real-exact")
    history = _seed_local_coupon(db_session, "real-history", seed_dimensions=False)
    db_session.add(DimStorePoiMapping(store_id="store-sale", poi_id="owner-sale"))
    db_session.flush()
    for coupon in (exact, history):
        settlement_worker.settle_coupon_local(db_session, coupon, "real-initial")
    db_session.commit()
    statement = settlement_worker.lock_settlement_statement(
        db_session, store_id="store-sale", statement_month="2026-08", lock_run_id="real-lock",
    )
    db_session.commit()
    assert statement.promotion_net_fee_cent > 0
    assert set(db_session.scalars(select(SettlementStatementEntry.coupon_id).where(
        SettlementStatementEntry.statement_id == statement.statement_id,
    ))) == {exact.coupon_id, history.coupon_id}
    before_exact = _coupon_local_snapshot(db_session, exact.coupon_id)
    before_history = _coupon_local_snapshot(db_session, history.coupon_id)
    assert len(before_exact["results"]) == len(before_history["results"]) == 2
    before_statement = (
        statement.statement_status, statement.lock_version,
        statement.promotion_net_fee_cent, statement.management_net_fee_cent,
    )
    db_session.add(_impact(
        "real-verify-run", entity_key="verify-real-exact",
        new_values_json={"coupon_id": exact.coupon_id},
        affected_closure_json={"poi_ids": ["poi-verify"]},
    ))
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), future=True)
    result = settlement_worker.settle_impacted_coupons(factory, "real-verify-run", None, 64, 1)
    db_session.expire_all()
    assert result["coupon_count"] == 1
    assert result["result_count"] == result["adjustment_count"] == 0
    after_exact = _coupon_local_snapshot(db_session, exact.coupon_id)
    # The affected coupon may refresh its DQI source-run audit metadata; its
    # fee identities, amounts and current heads must remain unchanged.
    for key in ("detail", "results", "current", "adjustments"):
        assert after_exact[key] == before_exact[key]
    assert _coupon_local_snapshot(db_session, history.coupon_id) == before_history
    assert (
        statement.statement_status, statement.lock_version,
        statement.promotion_net_fee_cent, statement.management_net_fee_cent,
    ) == before_statement
