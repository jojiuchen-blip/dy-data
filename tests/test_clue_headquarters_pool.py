from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueHeadquartersPoolEntry,
    ClueMasterLead,
    DimStore,
    DimStorePoiMapping,
    RawDouyinClue,
)
from apps.worker import clue_allocation
from apps.worker.clue_allocation_engine import allocate_lead
from apps.worker.clue_rule_versions import create_rule, create_rule_version, publish_rule_version


def _dt(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def _store(store_id: str, *, candidate: bool = False) -> DimStore:
    return DimStore(
        store_id=store_id,
        store_name=store_id,
        is_active=candidate,
        standard_province="CN-SH",
        standard_city="CN-SH",
        city_code="CN-SH",
        longitude=Decimal("121.470000"),
        latitude=Decimal("31.230000"),
        is_douyin_clue_applicable=candidate,
        participates_in_clue_allocation=candidate,
        location_source="test",
        location_status="valid",
        location_updated_at=_dt(1),
    )


def _lead(*, missing_anchor: bool = False) -> ClueMasterLead:
    return ClueMasterLead(
        lead_key="lead-1",
        source_clue_row_key="raw-1",
        source_identity_key="identity-1",
        canonical_clue_id="clue-1",
        order_id="order-1",
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state="pending_allocation",
        anchor_poi_id=None if missing_anchor else "poi-anchor",
        anchor_store_id=None if missing_anchor else "anchor",
        anchor_source=None if missing_anchor else "douyin_follow_poi",
        anchor_unavailable_reason="follow_poi_missing" if missing_anchor else None,
        anchor_province=None if missing_anchor else "CN-SH",
        anchor_city=None if missing_anchor else "CN-SH",
        anchor_city_code=None if missing_anchor else "CN-SH",
        anchor_longitude=None if missing_anchor else Decimal("121.470000"),
        anchor_latitude=None if missing_anchor else Decimal("31.230000"),
        first_seen_at=_dt(1),
        last_seen_at=_dt(1),
        created_at=_dt(1),
        updated_at=_dt(1),
    )


def _publish_global_rule(session: Session):
    rule = create_rule(session, name="Global default", scope_type="global", created_by="test-admin")
    version = create_rule_version(
        session,
        rule.rule_id,
        auto_expiry_enabled=True,
        first_follow_up_sla_hours=24,
        protection_days=7,
        conversion_weight=Decimal("0.7"),
        follow_24h_weight=Decimal("0.3"),
        lookback_days=30,
        min_samples=20,
        strategy_configs=[
            {
                "strategy_type": "sales_store_priority",
                "enabled": True,
                "execution_order": 1,
                "params": {"max_distance_km": 10},
            },
            {
                "strategy_type": "nearby_city_optimization",
                "enabled": True,
                "execution_order": 2,
                "params": {"max_distance_km": 15},
            },
            {"strategy_type": "city_fallback", "enabled": True, "execution_order": 3, "params": {}},
        ],
        created_by="test-admin",
    )
    return publish_rule_version(session, version.rule_version_id, published_by="test-admin")


def test_exhausted_candidates_open_an_auditable_hq_entry_without_a_round(db_session: Session) -> None:
    lead = _lead()
    db_session.add_all([_store("anchor"), lead])
    version = _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin", now=_dt(2))
    db_session.commit()

    entry = db_session.scalar(select(ClueHeadquartersPoolEntry).where(ClueHeadquartersPoolEntry.lead_key == lead.lead_key))
    master = db_session.get(ClueMasterLead, lead.lead_key)
    assert entry is not None
    assert entry.status == "active"
    assert entry.reason == "no_candidate"
    assert entry.source_assignment_round_id is None
    assert entry.source_decision_id == result.decision_ids[-1]
    assert entry.source_rule_version_id == version.rule_version_id
    assert entry.allocation_cycle_id is None
    assert entry.entered_at is not None
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    assert master is not None
    assert master.pool_location == "headquarters_pool"
    assert master.allocation_state == "headquarters"
    assert master.current_assignment_round_id is None
    assert db_session.get(ClueCenterOrder, lead.order_id) is None


def test_missing_anchor_opens_a_distinct_auditable_hq_entry_without_a_round(db_session: Session) -> None:
    lead = _lead(missing_anchor=True)
    db_session.add(lead)
    _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, lead.lead_key, actor="test-admin", now=_dt(2))
    db_session.commit()

    entry = db_session.scalar(select(ClueHeadquartersPoolEntry).where(ClueHeadquartersPoolEntry.lead_key == lead.lead_key))
    assert result.status == "headquarters"
    assert result.reason == "follow_poi_missing"
    assert entry is not None
    assert entry.reason == "follow_poi_missing"
    assert entry.source_assignment_round_id is None
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0


def test_engine_rejects_direct_reentry_from_headquarters_pool(db_session: Session) -> None:
    lead = _lead()
    lead.pool_location = "headquarters_pool"
    lead.allocation_state = "headquarters"
    db_session.add_all([_store("anchor"), _store("store-a", candidate=True), lead])
    _publish_global_rule(db_session)
    db_session.commit()

    with pytest.raises(ValueError, match="headquarters_reentry_not_supported"):
        allocate_lead(db_session, lead.lead_key, actor="test-admin", now=_dt(2))


def test_materialization_preserves_a_final_headquarters_pool_entry(db_session: Session) -> None:
    db_session.add_all(
        [
            _store("anchor"),
            DimStorePoiMapping(store_id="anchor", poi_id="poi-anchor", mapping_source="test"),
            RawDouyinClue(
                clue_row_key="materialized-raw-1",
                clue_id="materialized-clue-1",
                order_id="materialized-order-1",
                order_status="履约中",
                follow_poi_id="poi-anchor",
                create_time_detail=_dt(1),
                fetched_at=_dt(1),
                raw_payload={"clue_id": "materialized-clue-1"},
                imported_at=_dt(1),
                updated_at=_dt(1),
            ),
        ]
    )
    db_session.commit()
    clue_allocation.materialize_clue_master_leads(db_session, now=_dt(2))
    master = db_session.scalar(
        select(ClueMasterLead).where(ClueMasterLead.order_id == "materialized-order-1")
    )
    assert master is not None
    _publish_global_rule(db_session)
    db_session.commit()

    result = allocate_lead(db_session, master.lead_key, actor="test-admin", now=_dt(3))
    assert result.status == "headquarters"
    db_session.commit()

    clue_allocation.materialize_clue_master_leads(db_session, now=_dt(4))

    preserved = db_session.get(ClueMasterLead, master.lead_key)
    entry = db_session.scalar(
        select(ClueHeadquartersPoolEntry)
        .where(ClueHeadquartersPoolEntry.lead_key == master.lead_key)
        .where(ClueHeadquartersPoolEntry.status == "active")
    )
    assert preserved is not None
    assert preserved.pool_location == "headquarters_pool"
    assert preserved.allocation_state == "headquarters"
    assert preserved.current_assignment_round_id is None
    assert entry is not None


def test_terminal_materialization_closes_the_active_headquarters_entry(db_session: Session) -> None:
    db_session.add_all(
        [
            _store("anchor"),
            DimStorePoiMapping(store_id="anchor", poi_id="poi-anchor", mapping_source="test"),
            RawDouyinClue(
                clue_row_key="terminal-raw-1",
                clue_id="terminal-clue-1",
                order_id="terminal-order-1",
                order_status="履约中",
                follow_poi_id="poi-anchor",
                create_time_detail=_dt(1),
                fetched_at=_dt(1),
                raw_payload={"clue_id": "terminal-clue-1"},
                imported_at=_dt(1),
                updated_at=_dt(1),
            ),
        ]
    )
    db_session.commit()
    clue_allocation.materialize_clue_master_leads(db_session, now=_dt(2))
    master = db_session.scalar(
        select(ClueMasterLead).where(ClueMasterLead.order_id == "terminal-order-1")
    )
    assert master is not None
    _publish_global_rule(db_session)
    db_session.commit()
    assert allocate_lead(db_session, master.lead_key, actor="test-admin", now=_dt(3)).status == "headquarters"
    raw = db_session.get(RawDouyinClue, "terminal-raw-1")
    assert raw is not None
    raw.order_status = "已核销"
    db_session.commit()

    clue_allocation.materialize_clue_master_leads(db_session, now=_dt(4))

    closed_master = db_session.get(ClueMasterLead, master.lead_key)
    entry = db_session.scalar(
        select(ClueHeadquartersPoolEntry)
        .where(ClueHeadquartersPoolEntry.lead_key == master.lead_key)
        .order_by(ClueHeadquartersPoolEntry.entered_at.desc())
    )
    assert closed_master is not None
    assert closed_master.lifecycle_status == "closed_verified"
    assert closed_master.pool_location == "closed"
    assert entry is not None
    assert entry.status == "closed"
    assert entry.close_reason == "order_verified"
