from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    ClueAllocationDecision, ClueAssignmentRound, ClueCenterOrder,
    ClueFollowUpRecord, ClueHeadquartersPoolEntry, ClueLeadRuleVersionBinding, ClueMasterLead,
    DimSkuProductRule, DimStorePoiMapping, RawDouyinClue, RawDouyinOrder,
    RawDouyinOrderCoupon, RawDouyinVerifyRecord,
)
from apps.worker import clue_allocation, clue_allocation_engine as engine
from apps.worker.clue_rule_versions import bind_lead_rule_version
from apps.worker.formal_allocation_runtime import run_formal_allocation_batch
from test_clue_allocation_engine import _add_sale_store, _lead, _publish_global_rule, _store


NOW = datetime(2026, 11, 18, 3, tzinfo=timezone.utc)


@pytest.fixture
def lists(monkeypatch):
    state = {"published": True, "stores": {"anchor", "sale", "near", "far"}}
    monkeypatch.setattr(engine, "has_published_product_store_list", lambda *_: state["published"])
    monkeypatch.setattr(engine, "load_product_store_ids", lambda *_: set(state["stores"]))
    return state


def _flow(session, *, stores=None, key="lead-1", order_id="order-1", scope="jingcheng"):
    session.add_all(stores or [_store("anchor"), _store("sale"), _store("near"), _store("far")])
    lead = _lead(key, order_id=order_id)
    lead.routing_mode, lead.routing_product_id = "flow", "product-1"
    session.add(lead)
    _publish_global_rule(session)
    binding = bind_lead_rule_version(session, lead_key=key, anchor_store_id="anchor", anchor_city_code="CN-SH")
    binding.rule_version_snapshot = {**binding.rule_version_snapshot, "product_scope": scope,
        "min_samples": 1, "schema_version": 2}
    session.add(ClueCenterOrder(order_id=order_id, lead_status="pending_allocation",
        current_round_status="pending_allocation"))
    session.flush()
    return lead


def _expire(session, lead, now):
    row = session.get(ClueAssignmentRound, lead.current_assignment_round_id)
    row.round_status, row.closed_at = "closed_follow_up_expired", now
    row.matured_at = now
    lead.current_assignment_round_id = None
    lead.allocation_state = "pending_reassign"
    session.flush()
    return row


def test_three_business_rounds_are_distinct_and_retries_do_not_repeat_stores(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = {"sale", "near", "far"}
    _add_sale_store(db_session, order_id=lead.order_id, store_id="sale", coupon_id="sale-coupon")
    db_session.flush()
    first = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert first.selected_store_id == "sale"
    assert db_session.get(ClueAssignmentRound, first.assignment_round_id).round_no == 0
    assert db_session.get(ClueAssignmentRound, first.assignment_round_id).auto_expiry_enabled is True
    first_id = first.assignment_round_id
    assert engine.continue_product_routing(db_session, lead.lead_key, now=NOW, transition_key="duplicate").assignment_round_id == first_id
    _expire(db_session, lead, NOW + timedelta(hours=24))
    second = engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(hours=24), transition_key="due:0")
    assert second.selected_store_id == "far"  # equal scores/distances use fixed ID
    assert db_session.get(ClueAssignmentRound, second.assignment_round_id).round_no == 1
    _expire(db_session, lead, NOW + timedelta(hours=48))
    third = engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(hours=48), transition_key="due:1")
    assert third.selected_store_id == "near"
    assert db_session.get(ClueAssignmentRound, third.assignment_round_id).round_no == 2
    assert engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(hours=48), transition_key="due:1").assignment_round_id == third.assignment_round_id
    _expire(db_session, lead, NOW + timedelta(hours=72))
    final = engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(hours=72), transition_key="due:2")
    assert final.status == "closed"
    assert len({first_id, second.assignment_round_id, third.assignment_round_id}) == 3
    assert db_session.query(ClueAssignmentRound).count() == 3
    assert lead.lifecycle_status == "closed_order"
    assert engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(hours=73), transition_key="again").status == "skipped"


def test_sales_store_outside_list_is_skipped_and_first_actual_round_is_one(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = {"near"}
    _add_sale_store(db_session, order_id=lead.order_id, store_id="sale", coupon_id="sale-coupon")
    db_session.flush()
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert result.selected_store_id == "near"
    assert db_session.get(ClueAssignmentRound, result.assignment_round_id).round_no == 1
    first = db_session.get(ClueAllocationDecision, result.decision_ids[0])
    assert first.decision_status == "skipped"
    assert "product_store_not_applicable" in first.decision_snapshot["candidates"][0]["exclusion_reasons"]


def test_successful_sales_round_never_queries_historical_scores(db_session, lists, monkeypatch):
    lead = _flow(db_session)
    _add_sale_store(db_session, order_id=lead.order_id, store_id="sale", coupon_id="sale-coupon")
    db_session.flush()
    monkeypatch.setattr(engine, "load_product_store_scores",
        lambda *_args, **_kwargs: pytest.fail("sales priority must not query scores"))
    assert engine.allocate_lead(db_session, lead.lead_key, now=NOW).selected_store_id == "sale"


def test_no_eligible_store_closes_without_querying_historical_scores(db_session, lists, monkeypatch):
    lead = _flow(db_session)
    lists["stores"] = set()
    monkeypatch.setattr(engine, "load_product_store_scores",
        lambda *_args, **_kwargs: pytest.fail("no candidate requires no scoring"))
    assert engine.allocate_lead(db_session, lead.lead_key, now=NOW).status == "closed"


def test_product_city_scoring_is_loaded_once_per_bound_version_batch(db_session, lists, monkeypatch):
    lead = _flow(db_session)
    second = _lead("lead-two", order_id="order-two")
    second.routing_mode, second.routing_product_id = "flow", "product-1"
    db_session.add(second)
    binding = bind_lead_rule_version(db_session, lead_key=second.lead_key,
        anchor_store_id=second.anchor_store_id, anchor_city_code=second.anchor_city_code)
    binding.rule_version_snapshot = dict(db_session.get(ClueLeadRuleVersionBinding, lead.lead_key).rule_version_snapshot)
    db_session.flush()
    calls = []
    def scores(*_args, **_kwargs):
        calls.append(True)
        return {}
    monkeypatch.setattr(engine, "load_product_store_scores", scores)
    results = engine.allocate_leads(db_session, [lead.lead_key, second.lead_key], now=NOW)
    assert all(result.status == "assigned" for result in results)
    assert len(calls) == 1


@pytest.mark.parametrize("distance,city,expected_round", [(10, "CN-SH", 1), (11, "CN-SH", 2), (3, "OTHER", None)])
def test_nearby_ten_kilometer_and_same_city_boundaries(db_session, lists, monkeypatch, distance, city, expected_round):
    lead = _flow(db_session, stores=[_store("anchor"), _store("near", city_code=city)])
    lists["stores"] = {"near"}
    monkeypatch.setattr(engine, "_distance_from_anchor", lambda *_: float(distance))
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    if expected_round is None:
        assert result.status == "closed"
        assert db_session.query(ClueHeadquartersPoolEntry).count() == 0
    else:
        assert result.selected_store_id == "near"
        assert db_session.get(ClueAssignmentRound, result.assignment_round_id).round_no == expected_round


def test_old_transition_replay_cannot_advance_a_later_pending_round(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = {"far", "near"}
    first = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    _expire(db_session, lead, NOW + timedelta(days=1))
    replay = engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(days=1), transition_key="first:lead-1")
    assert replay.status == "skipped"
    assert replay.reason == "transition_already_processed"
    assert replay.assignment_round_id == first.assignment_round_id
    assert db_session.query(ClueAssignmentRound).count() == 1
    result = engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(days=1), transition_key="due:round-one")
    assert result.status == "assigned"
    assert db_session.get(ClueAssignmentRound, result.assignment_round_id).round_no == 2


def test_latest_list_is_used_only_at_next_selection(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = {"near"}
    first = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    lists["stores"] = {"far"}
    assert engine.allocate_lead(db_session, lead.lead_key, now=NOW).assignment_round_id == first.assignment_round_id
    _expire(db_session, lead, NOW + timedelta(days=1))
    second = engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(days=1), transition_key="list-change")
    assert second.selected_store_id == "far"
    assert db_session.get(ClueAssignmentRound, second.assignment_round_id).round_no == 2


def test_missing_list_enters_headquarters_without_tasks_then_resumes_current_stage(db_session, lists):
    lead = _flow(db_session)
    lists["published"] = False
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert result.status == "headquarters"
    assert result.reason == "product_store_list_missing"
    assert db_session.query(ClueAssignmentRound).count() == 0
    entry = db_session.query(ClueHeadquartersPoolEntry).filter_by(status="active").one()
    assert entry.source_snapshot["product_routing"] == {
        "product_id": "product-1", "routing_mode": "flow", "pending_round_no": 0,
        "business_round_no": 0, "transition_key": "first:lead-1"}
    lists["published"] = True
    lists["stores"] = {"near"}
    resumed = engine.resume_product_routing(db_session, lead.lead_key, now=NOW + timedelta(minutes=1), actor="admin", expected_entry_id=entry.headquarters_pool_entry_id)
    assert resumed.status == "assigned"
    assert db_session.get(ClueAssignmentRound, resumed.assignment_round_id).round_no == 1
    repeated = engine.resume_product_routing(db_session, lead.lead_key, now=NOW + timedelta(minutes=2), actor="admin", expected_entry_id=entry.headquarters_pool_entry_id)
    assert repeated.status == "skipped"
    assert repeated.reason == "headquarters_entry_changed"
    assert db_session.query(ClueAssignmentRound).count() == 1


def test_headquarters_after_round_one_retains_round_two(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = {"near"}
    engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    _expire(db_session, lead, NOW + timedelta(days=1))
    lists["published"] = False
    result = engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(days=1), transition_key="due:one")
    assert result.status == "headquarters"
    entry = db_session.query(ClueHeadquartersPoolEntry).filter_by(status="active").one()
    assert entry.source_snapshot["product_routing"]["pending_round_no"] == 2
    lists["published"], lists["stores"] = True, {"far"}
    result = engine.resume_product_routing(db_session, lead.lead_key, now=NOW + timedelta(days=2), actor="admin")
    assert result.selected_store_id == "far"
    assert db_session.get(ClueAssignmentRound, result.assignment_round_id).round_no == 2


@pytest.mark.parametrize("field,value", [("anchor_city_code", None), ("anchor_latitude", None), ("anchor_poi_id", None)])
def test_missing_anchor_inputs_enter_headquarters(db_session, lists, field, value):
    lead = _flow(db_session)
    setattr(lead, field, value)
    db_session.flush()
    assert engine.allocate_lead(db_session, lead.lead_key, now=NOW).status == "headquarters"
    assert db_session.query(ClueAssignmentRound).count() == 0


def test_published_empty_list_is_valid_data_and_closes_without_candidate(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = set()
    assert engine.allocate_lead(db_session, lead.lead_key, now=NOW).status == "closed"
    assert db_session.query(ClueAssignmentRound).count() == 0
    assert lead.ended_without_assignment is True


def test_headquarters_resume_checks_live_terminal_order_before_list(db_session, lists):
    lead = _flow(db_session)
    lists["published"] = False
    engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    db_session.add(RawDouyinOrder(order_id=lead.order_id, order_status="已退款", source_observed_at=NOW, raw_payload={}))
    db_session.flush()
    result = engine.resume_product_routing(db_session, lead.lead_key, now=NOW + timedelta(minutes=1), actor="admin")
    assert result.status == "skipped"
    assert lead.normalized_order_status == "refunded"
    assert db_session.query(ClueAssignmentRound).count() == 0
    assert db_session.query(ClueHeadquartersPoolEntry).filter_by(status="active").count() == 0


def test_direct_assignment_does_not_require_rule_list_or_geography(db_session, lists):
    store = _store("anchor")
    store.latitude = store.longitude = None
    store.location_status = "missing"
    store.is_douyin_clue_applicable = False
    lead = _lead()
    lead.routing_mode, lead.routing_product_id = "direct", "byd-product"
    lead.anchor_latitude = lead.anchor_longitude = None
    lead.anchor_unavailable_reason = "anchor_coordinates_invalid"
    db_session.add_all([store, lead])
    db_session.flush()
    lists["published"] = False
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert result.selected_store_id == "anchor"
    row = db_session.get(ClueAssignmentRound, result.assignment_round_id)
    assert row.auto_expiry_enabled is False
    assert row.rule_version_id is None
    assert engine.continue_product_routing(db_session, lead.lead_key, now=NOW + timedelta(days=2), transition_key="due").status == "skipped"
    assert db_session.query(ClueAssignmentRound).count() == 1


def test_product_trial_only_persists_decisions_and_preserves_formal_state(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = {"near"}
    before = clue_allocation._master_state_signature(lead)
    result = engine.allocate_lead(db_session, lead.lead_key, execution_mode="trial", now=NOW)
    assert result.status == "assigned"
    assert result.assignment_round_id is None
    assert clue_allocation._master_state_signature(lead) == before
    assert db_session.query(ClueAssignmentRound).count() == 0
    assert db_session.query(ClueHeadquartersPoolEntry).count() == 0
    assert db_session.get(ClueCenterOrder, lead.order_id).current_assignment_round_id is None
    assert all(row.execution_mode == "trial" for row in db_session.query(ClueAllocationDecision))
    formal = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert formal.assignment_round_id is not None
    assert formal.selected_store_id == "near"


def test_scoring_uses_scoped_task_counts_fixed_seventy_thirty_and_stable_ties(db_session, lists, monkeypatch):
    lead = _flow(db_session)
    lists["stores"] = {"far", "near"}
    calls = []
    def totals(session, store_ids, start, end, **kwargs):
        calls.append(kwargs)
        return {"near": SimpleNamespace(conversion_numerator=0, conversion_denominator=1,
            follow_24h_numerator=1, follow_24h_denominator=1),
            "far": SimpleNamespace(conversion_numerator=1, conversion_denominator=1,
            follow_24h_numerator=0, follow_24h_denominator=1)}
    monkeypatch.setattr(clue_allocation, "load_store_task_totals", totals)
    monkeypatch.setattr(engine, "_latest_scores", lambda *_args, **_kwargs: pytest.fail("mixed-product scores read"))
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert result.selected_store_id == "far"
    assert calls[0]["product_scope"] == "jingcheng"
    decision = db_session.get(ClueAllocationDecision, result.decision_ids[-1])
    scores = {item["store_id"]: item["score"] for item in decision.decision_snapshot["candidates"]}
    assert scores["far"]["composite_score"] == 0.7
    assert scores["near"]["composite_score"] == 0.3
    assert scores["far"]["product_scope"] == "jingcheng"
    assert scores["far"]["conversion_numerator"] == 1


def test_formal_first_allocation_enables_only_bound_product_flow(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = {"near"}
    db_session.add(RawDouyinClue(clue_row_key=lead.source_clue_row_key, order_id=lead.order_id, order_status="201", raw_payload={}))
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    assert run_formal_allocation_batch(factory, now=NOW)["assigned"] == 1
    with factory() as reader:
        assert reader.query(ClueAssignmentRound).one().auto_expiry_enabled is True


def test_real_task_scoring_excludes_byd_verification_samples(db_session, lists):
    lead = _flow(db_session)
    lists["stores"] = {"near", "far"}
    assigned_at = NOW - timedelta(days=2)
    for order_id, store, scope in (("jc-near", "near", "精诚养车"),
        ("jc-far", "far", "精诚养车"), ("byd-far", "far", "比亚迪")):
        db_session.add_all([
            DimSkuProductRule(sku_id=order_id, product_id=order_id,
                product_scope=scope, product_type=scope),
            RawDouyinOrder(order_id=order_id, sku_id=order_id,
                order_status_normalized="active", source_observed_at=assigned_at, updated_at=assigned_at),
            ClueAssignmentRound(assignment_round_id=order_id, order_id=order_id,
                assigned_store_id=store, assigned_at=assigned_at, round_no=1,
                execution_mode="formal", round_status="closed_follow_up_expired",
                closed_at=NOW - timedelta(days=1), created_at=assigned_at, updated_at=assigned_at),
        ])
    db_session.add_all([
        ClueFollowUpRecord(follow_up_record_id="jc-follow", order_id="jc-near",
            assignment_round_id="jc-near", assigned_store_id="near", round_no=1,
            follow_result="further_follow_up", created_at=assigned_at + timedelta(hours=1)),
        DimStorePoiMapping(store_id="far", poi_id="poi-far"),
        RawDouyinOrderCoupon(order_id="byd-far", coupon_id="byd-coupon", source_observed_at=assigned_at),
        RawDouyinVerifyRecord(verify_id="byd-verification", coupon_id="byd-coupon",
            verify_status="success", poi_id="poi-far", verify_time=assigned_at + timedelta(hours=2),
            source_observed_at=assigned_at + timedelta(hours=2)),
    ])
    db_session.flush()
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert result.selected_store_id == "near"
    decision = db_session.get(ClueAllocationDecision, result.decision_ids[-1])
    candidates = {row["store_id"]: row["score"] for row in decision.decision_snapshot["candidates"]}
    assert candidates["near"]["composite_score"] == 0.3
    assert candidates["far"]["composite_score"] == 0
    assert candidates["far"]["conversion_denominator"] == 1


def test_original_without_ingress_version_cannot_late_bind_new_publication(db_session):
    lead = _lead()
    lead.routing_mode, lead.routing_product_id = "original", "product-1"
    db_session.add_all([lead, _store("anchor")])
    _publish_global_rule(db_session)
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert result.status == "headquarters"
    assert db_session.get(ClueLeadRuleVersionBinding, lead.lead_key) is None


def test_duplicate_order_master_cannot_start_second_task_stream(db_session, lists):
    lead = _flow(db_session)
    engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    duplicate = _lead("duplicate", order_id=lead.order_id)
    duplicate.routing_mode, duplicate.routing_product_id = "flow", "product-1"
    db_session.add(duplicate)
    db_session.flush()
    result = engine.allocate_lead(db_session, duplicate.lead_key, now=NOW)
    assert result.status == "skipped"
    assert result.reason == "order_already_has_task_stream"
    assert db_session.query(ClueAssignmentRound).count() == 1


def test_order_with_unlinked_legacy_task_cannot_start_product_task_stream(db_session, lists):
    lead = _flow(db_session)
    db_session.add(ClueAssignmentRound(assignment_round_id="unlinked-legacy", order_id=lead.order_id,
        execution_mode="legacy", round_no=1, assigned_at=NOW - timedelta(days=1),
        assigned_store_id="anchor", round_status="active_unfollowed"))
    db_session.flush()
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert result.status == "skipped"
    assert result.reason == "order_already_has_task_stream"
    assert db_session.query(ClueAssignmentRound).count() == 1


@pytest.fixture
def ingress(monkeypatch, db_session):
    state = {"mode": "flow", "calls": []}
    def bind(session, lead, product_id, now):
        state["calls"].append((lead.lead_key, product_id))
        lead.routing_mode, lead.routing_product_id = state["mode"], product_id
        if state["mode"] == "flow":
            bind_lead_rule_version(session, lead_key=lead.lead_key,
                anchor_store_id=lead.anchor_store_id, anchor_city_code=lead.anchor_city_code)
    monkeypatch.setattr(clue_allocation, "bind_product_routing", bind)
    db_session.add_all([_store("anchor"), _store("other"),
        DimStorePoiMapping(store_id="anchor", poi_id="poi-anchor"),
        DimStorePoiMapping(store_id="other", poi_id="poi-other")])
    _publish_global_rule(db_session)
    return state


def _ingest(session, *, key="raw-one", order_id="order-one", poi="poi-anchor", product="product-one", observed=NOW, status="201"):
    raw = session.get(RawDouyinClue, key)
    if raw is None:
        raw = RawDouyinClue(clue_row_key=key, clue_id=f"clue-{key}", raw_payload={})
        session.add(raw)
    raw.order_id, raw.order_status = order_id, status
    raw.product_id, raw.follow_poi_id = product, poi
    raw.source_observed_at = observed
    raw.observation_key = observed.isoformat()
    session.flush()
    clue_allocation.materialize_clue_master_leads(session, raw_clues=[raw], now=observed)
    session.flush()
    return session.scalar(select(ClueMasterLead).where(ClueMasterLead.source_clue_row_key == key))


def test_ingress_binds_pending_once_and_rerun_keeps_first_valid_anchor(db_session, ingress):
    lead = _ingest(db_session)
    binding_id = db_session.get(ClueLeadRuleVersionBinding, lead.lead_key).rule_version_id
    ingress["mode"] = "direct"
    again = _ingest(db_session, product="different-product", poi="poi-other", observed=NOW + timedelta(hours=1))
    assert again.lead_key == lead.lead_key
    assert again.routing_mode == "flow"
    assert again.routing_product_id == "product-one"
    assert again.anchor_store_id == "anchor"
    assert again.anchor_poi_id == "poi-anchor"
    assert db_session.get(ClueLeadRuleVersionBinding, lead.lead_key).rule_version_id == binding_id
    assert len(ingress["calls"]) == 1
    assert db_session.query(ClueMasterLead).count() == 1


def test_first_invalid_anchor_can_be_repaired_once_then_freezes(db_session, ingress):
    lead = _ingest(db_session, poi=None)
    assert lead.pool_location == "headquarters_pool"
    assert lead.anchor_store_id is None
    lead = _ingest(db_session, poi="poi-anchor", observed=NOW + timedelta(hours=1))
    assert lead.anchor_store_id == "anchor"
    assert lead.anchor_unavailable_reason is None
    lead = _ingest(db_session, poi="poi-other", observed=NOW + timedelta(hours=2))
    assert lead.anchor_store_id == "anchor"
    assert len(ingress["calls"]) == 1


@pytest.mark.parametrize("missing", ["mapping", "coordinates"])
def test_headquarters_resume_repairs_current_original_facts_without_new_raw_observation(db_session, ingress, lists, missing):
    if missing == "coordinates":
        store = db_session.get(clue_allocation.DimStore, "anchor")
        store.latitude = store.longitude = None
        db_session.flush()
    poi = "poi-repaired" if missing == "mapping" else "poi-anchor"
    lead = _ingest(db_session, poi=poi)
    assert lead.pool_location == "headquarters_pool"
    if missing == "mapping":
        db_session.add(DimStorePoiMapping(store_id="anchor", poi_id=poi))
    else:
        store.latitude, store.longitude = Decimal("31.23"), Decimal("121.47")
    db_session.flush()
    # The unchanged source observation is deliberately skipped by collection.
    _ingest(db_session, poi=poi)
    assert lead.anchor_unavailable_reason is not None
    lists["stores"] = {"anchor"}
    result = engine.resume_product_routing(db_session, lead.lead_key, now=NOW + timedelta(minutes=1), actor="hq-admin")
    assert result.status == "assigned"
    assert lead.anchor_store_id == "anchor"
    assert lead.anchor_unavailable_reason is None
    assert lead.anchor_poi_id == poi
    assert lead.anchor_latitude == Decimal("31.23")
    assert lead.anchor_longitude == Decimal("121.47")


def test_unmapped_original_poi_is_preserved_across_later_platform_store_change(db_session, ingress, lists):
    lead = _ingest(db_session, poi="poi-original-unmapped")
    assert lead.anchor_poi_id == "poi-original-unmapped"
    _ingest(db_session, poi="poi-other", observed=NOW + timedelta(hours=1))
    assert lead.anchor_poi_id == "poi-original-unmapped"
    assert lead.anchor_store_id is None
    db_session.add(DimStorePoiMapping(store_id="anchor", poi_id="poi-original-unmapped"))
    db_session.flush()
    lists["stores"] = {"anchor"}
    result = engine.resume_product_routing(db_session, lead.lead_key, now=NOW + timedelta(hours=2), actor="hq-admin")
    assert result.selected_store_id == "anchor"
    assert lead.anchor_store_id == "anchor"
    assert lead.anchor_poi_id == "poi-original-unmapped"


def test_isolated_source_binding_survives_order_recovery(db_session, ingress):
    lead = _ingest(db_session, order_id=None)
    first_key = lead.lead_key
    assert lead.master_kind == 2
    assert lead.routing_mode == "flow"
    ingress["mode"] = "direct"
    lead = _ingest(db_session, observed=NOW + timedelta(hours=1))
    assert lead.lead_key == first_key
    assert lead.master_kind == 1
    assert lead.routing_mode == "flow"
    assert len(ingress["calls"]) == 1
    assert db_session.query(ClueMasterLead).count() == 1


def test_existing_null_pending_lead_stays_legacy_when_ingested_after_enable(db_session, ingress):
    lead = _lead("legacy", order_id="order-one")
    lead.source_clue_row_key = "raw-one"
    lead.routing_mode = None
    lead.last_seen_at = NOW - timedelta(days=1)
    db_session.add(lead)
    db_session.flush()
    refreshed = _ingest(db_session)
    assert refreshed.lead_key == "legacy"
    assert refreshed.routing_mode is None
    assert ingress["calls"] == []


def test_direct_materialization_missing_geography_remains_eligible(db_session, ingress):
    ingress["mode"] = "direct"
    store = db_session.get(clue_allocation.DimStore, "anchor")
    store.latitude = store.longitude = None
    store.location_status = "missing"
    db_session.flush()
    lead = _ingest(db_session)
    assert lead.routing_mode == "direct"
    assert lead.pool_location is None
    assert lead.allocation_state == "pending_allocation"


def test_business_closure_is_not_reopened_by_active_repull_or_late_verification(db_session, ingress, lists):
    lead = _ingest(db_session)
    lists["stores"] = set()
    result = engine.allocate_lead(db_session, lead.lead_key, now=NOW)
    assert result.status == "closed"
    closed_at = lead.closed_at
    lead = _ingest(db_session, observed=NOW + timedelta(days=1))
    assert lead.lifecycle_status == "closed_order"
    assert lead.closed_at.replace(tzinfo=timezone.utc) == closed_at
    assert lead.closed_reason == "product_routing_no_candidate"
    assert lead.allocation_state == "closed"
    lead = _ingest(db_session, status="unknown", observed=NOW + timedelta(days=1, hours=1))
    assert lead.lifecycle_status == "closed_order"
    assert lead.allocation_state == "closed"
    assert lead.closed_reason == "product_routing_no_candidate"
    lead = _ingest(db_session, observed=NOW + timedelta(days=1, hours=2))
    assert lead.lifecycle_status == "closed_order"
    assert lead.allocation_state == "closed"
    db_session.add(RawDouyinOrder(order_id=lead.order_id, order_status="已退款", source_observed_at=NOW + timedelta(days=2), raw_payload={}))
    db_session.flush()
    assert clue_allocation.refresh_terminal_evidence_for_locked_lead(db_session, lead, now=NOW + timedelta(days=2)) is True
    assert lead.normalized_order_status == "refunded"
    assert lead.closed_at.replace(tzinfo=timezone.utc) == closed_at
    assert db_session.query(ClueAssignmentRound).count() == 0
