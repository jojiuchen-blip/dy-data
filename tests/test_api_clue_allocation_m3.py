from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
IDEMPOTENCY_HEADERS = {"Idempotency-Key": "test-clue-allocation-cycle"}
REBUILD_IDEMPOTENCY_HEADERS = {"Idempotency-Key": "test-clue-allocation-rebuild-cycle"}

from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.access_control import ALL_PAGE_KEYS, replace_user_overrides  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    ClueAllocationAuditLog,
    ClueAllocationCandidate,
    ClueAllocationCycle,
    ClueAllocationCycleItem,
    ClueAllocationDecision,
    ClueAllocationRule,
    ClueAssignmentRound,
    ClueHeadquartersPoolEntry,
    ClueMasterLead,
    ClueStoreGroup,
    ClueStoreGroupMember,
    DimStore,
    StoreScoreSnapshot,
    StoreScoreSnapshotRun,
    User,
    UserPagePermissionOverride,
    UserStoreScope,
)
from apps.worker.clue_headquarters_pool import (  # noqa: E402
    close_current_headquarters_pool_entry,
    enter_headquarters_pool,
)
from apps.worker.clue_rule_versions import (  # noqa: E402
    create_rule,
    create_rule_version,
    publish_rule_version,
)


def _dt(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def _seed_trial_ready_lead(session: Session, *, lead_key: str = "trial-lead") -> ClueMasterLead:
    anchor = DimStore(
        store_id=f"anchor-{lead_key}",
        store_name="Anchor",
        is_active=False,
        standard_province="CN-SH",
        standard_city="CN-SH",
        city_code="CN-SH",
        longitude=Decimal("121.470000"),
        latitude=Decimal("31.230000"),
        is_douyin_clue_applicable=False,
        participates_in_clue_allocation=False,
        location_source="test",
        location_status="valid",
        location_updated_at=_dt(1),
    )
    candidate = DimStore(
        store_id=f"candidate-{lead_key}",
        store_name="Candidate",
        is_active=True,
        standard_province="CN-SH",
        standard_city="CN-SH",
        city_code="CN-SH",
        longitude=Decimal("121.471000"),
        latitude=Decimal("31.231000"),
        is_douyin_clue_applicable=True,
        participates_in_clue_allocation=True,
        location_source="test",
        location_status="valid",
        location_updated_at=_dt(1),
    )
    lead = ClueMasterLead(
        lead_key=lead_key,
        source_clue_row_key=f"raw-{lead_key}",
        source_identity_key=f"identity-{lead_key}",
        canonical_clue_id=f"clue-{lead_key}",
        order_id=f"order-{lead_key}",
        raw_order_status="履约中",
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state="pending_allocation",
        anchor_poi_id=f"poi-{lead_key}",
        anchor_store_id=anchor.store_id,
        anchor_source="douyin_follow_poi",
        anchor_province="CN-SH",
        anchor_city="CN-SH",
        anchor_city_code="CN-SH",
        anchor_longitude=Decimal("121.470000"),
        anchor_latitude=Decimal("31.230000"),
        first_seen_at=_dt(1),
        last_seen_at=_dt(1),
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    session.add_all([anchor, candidate, lead])
    rule = create_rule(session, name=f"global-{lead_key}", scope_type="global", created_by="system-admin")
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
            {"strategy_type": "sales_store_priority", "enabled": False, "execution_order": 1, "params": {"max_distance_km": 10}},
            {"strategy_type": "nearby_city_optimization", "enabled": True, "execution_order": 2, "params": {"max_distance_km": 15}},
            {"strategy_type": "city_fallback", "enabled": True, "execution_order": 3, "params": {}},
        ],
        created_by="system-admin",
    )
    publish_rule_version(session, version.rule_version_id, published_by="system-admin")
    session.commit()
    return lead


def _seed_headquarters_lead(
    session: Session,
    *,
    lead_key: str,
    order_id: str,
    normalized_order_status: str,
    raw_order_status: str,
    reason: str,
    entered_at: datetime,
    pool_status: str = "active",
) -> ClueMasterLead:
    lifecycle_status = "active" if normalized_order_status == "active" else f"closed_{normalized_order_status}"
    lead = ClueMasterLead(
        lead_key=lead_key,
        source_clue_row_key=f"raw-{lead_key}",
        source_identity_key=f"identity-{lead_key}",
        canonical_clue_id=f"clue-{lead_key}",
        order_id=order_id,
        raw_order_status=raw_order_status,
        normalized_order_status=normalized_order_status,
        status_source="test",
        lifecycle_status=lifecycle_status,
        pool_location="headquarters_pool",
        allocation_state="headquarters",
        anchor_store_id=f"anchor-{lead_key}",
        anchor_city="上海市",
        anchor_city_code="CN-SH",
        first_seen_at=entered_at,
        last_seen_at=entered_at,
        created_at=entered_at,
        updated_at=entered_at,
    )
    session.add(lead)
    enter_headquarters_pool(
        session,
        lead=lead,
        reason=reason,
        entered_at=entered_at,
        source_snapshot={"phone_plain": "13812345678", "reason": reason},
    )
    if pool_status != "active":
        close_current_headquarters_pool_entry(
            session,
            lead.lead_key,
            closed_at=_dt(4),
            close_reason="order_status_changed",
            status=pool_status,
        )
    session.commit()
    return lead


def test_m3_allocation_control_allows_admin_read_only_and_requires_highest_admin_for_execution(
    client: TestClient, db_session: Session
) -> None:
    _seed_trial_ready_lead(db_session)
    db_session.add(
        User(
            user_id="ordinary-admin",
            username="ordinary-admin",
            display_name="Ordinary Admin",
            role="admin",
            status="active",
            is_initialized=True,
            password_hash=hash_password_pbkdf2("ordinary-admin-password"),
        )
    )
    db_session.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "ordinary-admin", "password": "ordinary-admin-password"},
    )
    assert login.status_code == 200

    assert client.get("/api/v1/admin/clue-allocation/eligible-leads").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/headquarters-pool").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/cycles").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/audit-logs").status_code == 403
    assert client.get("/api/v1/admin/clue-allocation/rules").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/decisions").status_code == 200
    assert client.post(
        "/api/v1/admin/clue-allocation/rules",
        json={"name": "ordinary-admin-rule", "scope": {"scope_type": "global"}},
    ).status_code == 403
    assert client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": ["trial-lead"]},
    ).status_code == 403
    assert client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=IDEMPOTENCY_HEADERS,
        json={"lead_keys": ["trial-lead"], "confirmation_text": "确认试运行"},
    ).status_code == 403


def test_m3_preview_is_nonpersistent_and_trial_requires_confirmation(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session)
    _login(client)

    eligible = client.get("/api/v1/admin/clue-allocation/eligible-leads")
    assert eligible.status_code == 200
    assert eligible.json()["data"]["rows"][0]["lead_key"] == lead.lead_key

    preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["summary"]["assigned"] == 1
    preview_token = preview.json()["data"]["preview_token"]
    assert db_session.scalar(select(ClueAllocationCycle)) is None
    assert db_session.scalar(select(ClueAssignmentRound)) is None

    missing_preview = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=IDEMPOTENCY_HEADERS,
        json={"lead_keys": [lead.lead_key], "confirmation_text": "确认试运行"},
    )
    assert missing_preview.status_code == 422

    missing_confirmation = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=IDEMPOTENCY_HEADERS,
        json={"lead_keys": [lead.lead_key], "preview_token": preview_token},
    )
    assert missing_confirmation.status_code == 422

    missing_idempotency_key = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview_token,
            "confirmation_text": "确认试运行",
        },
    )
    assert missing_idempotency_key.status_code == 422

    executed = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=IDEMPOTENCY_HEADERS,
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview_token,
            "confirmation_text": "确认试运行",
        },
    )
    assert executed.status_code == 200
    payload = executed.json()["data"]
    assert payload["cycle_id"] == payload["allocation_cycle_id"]
    assert payload["cycle_mode"] == "trial"
    assert payload["cycle_status"] == "completed"
    assert payload["eligible_lead_count"] == 1
    assert payload["assigned_lead_count"] == 1
    assert payload["execution_mode"] == "trial"
    assert payload["summary"]["assigned"] == 1
    assert db_session.scalar(select(ClueAssignmentRound)) is None
    persisted_decisions = list(
        db_session.scalars(
            select(ClueAllocationDecision)
            .where(ClueAllocationDecision.allocation_cycle_id == payload["cycle_id"])
        )
    )
    assert persisted_decisions
    assert all(decision.assignment_round_id is None for decision in persisted_decisions)
    refreshed_lead = db_session.get(ClueMasterLead, lead.lead_key)
    assert refreshed_lead is not None
    assert refreshed_lead.current_assignment_round_id is None
    assert refreshed_lead.allocation_state == "pending_allocation"

    retried = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=IDEMPOTENCY_HEADERS,
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview_token,
            "confirmation_text": "确认试运行",
        },
    )
    assert retried.status_code == 200
    assert retried.json()["data"]["allocation_cycle_id"] == payload["allocation_cycle_id"]
    assert db_session.scalar(select(ClueAllocationCycle).where(ClueAllocationCycle.preview_token_hash.is_not(None)))
    assert db_session.scalar(select(ClueAllocationAuditLog)).detail_json["preview_token_hash"] != preview_token

    cycles = client.get("/api/v1/admin/clue-allocation/cycles")
    audits = client.get("/api/v1/admin/clue-allocation/audit-logs")
    assert cycles.status_code == 200
    cycle_row = cycles.json()["data"]["rows"][0]
    assert cycle_row["cycle_id"] == payload["cycle_id"]
    assert cycle_row["cycle_mode"] == "trial"
    assert cycle_row["cycle_status"] == "completed"
    assert cycle_row["actor_username"] == "system-admin"
    assert cycle_row["actor_user_id"] == "environment:system-admin"
    filtered_cycles = client.get(
        "/api/v1/admin/clue-allocation/cycles",
        params={
            "cycle_mode": "trial",
            "cycle_status": "completed",
        },
    )
    assert filtered_cycles.status_code == 200
    assert filtered_cycles.json()["data"]["pagination"]["total"] == 1
    cycle_detail = client.get(f"/api/v1/admin/clue-allocation/cycles/{payload['cycle_id']}")
    assert cycle_detail.status_code == 200
    assert cycle_detail.json()["data"]["cycle"]["cycle_id"] == payload["cycle_id"]
    assert cycle_detail.json()["data"]["items"][0]["lead_key"] == lead.lead_key
    assert cycle_detail.json()["data"]["items"][0]["assignment_round_id"] is None
    decisions = client.get(
        "/api/v1/admin/clue-allocation/decisions",
        params={"cycle_id": payload["cycle_id"], "dataset_kind": "trial"},
    )
    assert decisions.status_code == 200
    decision_rows = decisions.json()["data"]["rows"]
    assert decision_rows
    assert all(row["cycle_id"] == payload["cycle_id"] for row in decision_rows)
    selected_decision = next(row for row in decision_rows if row["candidate_count"] > 0)
    decision_detail = client.get(
        f"/api/v1/admin/clue-allocation/decisions/{selected_decision['decision_id']}"
    )
    assert decision_detail.status_code == 200
    assert decision_detail.json()["data"]["candidates"]
    assert "phone" not in json.dumps(decision_detail.json(), ensure_ascii=False).lower()
    assert client.get(
        "/api/v1/admin/clue-allocation/decisions",
        params={"dataset_kind": "legacy"},
    ).status_code == 422
    assert audits.status_code == 200
    audit_row = audits.json()["data"]["rows"][0]
    assert audit_row["event_type"] == "trial_executed"
    assert audit_row["actor_username_snapshot"] == "system-admin"
    assert audit_row["actor_role_snapshot"] == "highest_admin"
    assert audit_row["actor_scope_snapshot"] == {"mode": "all", "store_ids": []}
    assert audit_row["request_id"]
    assert audit_row["result_status"] == "completed"
    assert "phone" not in json.dumps(audits.json(), ensure_ascii=False).lower()


def test_m3_removed_legacy_trial_and_direct_materialization_routes_are_not_callable(
    client: TestClient,
) -> None:
    _login(client)

    for path in (
        "/api/v1/admin/clue-allocation/cycles/preview",
        "/api/v1/admin/clue-allocation/cycles/trial",
        "/api/v1/admin/clue-allocation/cycles/rebuild",
        "/api/v1/admin/sync/clue-center/rebuild",
    ):
        assert client.post(path, json={}).status_code in {404, 405}


def test_m3_trial_preview_refuses_execution_when_the_eligible_set_changes(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="stale-preview-lead")
    _login(client)
    preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200

    lead.lifecycle_status = "closed_verified"
    db_session.commit()

    execution = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=IDEMPOTENCY_HEADERS,
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview.json()["data"]["preview_token"],
            "confirmation_text": "确认试运行",
        },
    )

    assert execution.status_code == 422
    assert "preview_no_longer_matches" in execution.json()["detail"]


def test_m3_trial_preview_refuses_execution_when_the_lead_state_version_changes(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="versioned-preview-lead")
    _login(client)
    preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200

    lead.state_version = (lead.state_version or 1) + 1
    lead.updated_at = _dt(2)
    db_session.commit()

    execution = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers={"Idempotency-Key": "state-version-preview-cycle"},
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview.json()["data"]["preview_token"],
            "confirmation_text": "确认试运行",
        },
    )

    assert execution.status_code == 422
    assert "preview_no_longer_matches" in execution.json()["detail"]


def test_m3_trial_preview_refuses_execution_when_the_published_rule_changes(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="rule-preview-lead")
    _login(client)
    preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200

    rule = db_session.scalar(
        select(ClueAllocationRule).where(
            ClueAllocationRule.rule_name == f"global-{lead.lead_key}"
        )
    )
    assert rule is not None
    replacement = create_rule_version(
        db_session,
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
                "enabled": False,
                "execution_order": 1,
                "params": {"max_distance_km": 10},
            },
            {
                "strategy_type": "nearby_city_optimization",
                "enabled": True,
                "execution_order": 2,
                "params": {"max_distance_km": 12},
            },
            {
                "strategy_type": "city_fallback",
                "enabled": True,
                "execution_order": 3,
                "params": {},
            },
        ],
        created_by="system-admin",
    )
    publish_rule_version(
        db_session,
        replacement.rule_version_id,
        published_by="system-admin",
    )
    db_session.commit()

    execution = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers={"Idempotency-Key": "rule-version-preview-cycle"},
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview.json()["data"]["preview_token"],
            "confirmation_text": "确认试运行",
        },
    )

    assert execution.status_code == 422
    assert "preview_no_longer_matches" in execution.json()["detail"]


def test_m3_trial_idempotency_key_rejects_a_different_preview_request(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="idempotent-preview-lead")
    _login(client)
    first_preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": [lead.lead_key]},
    )
    assert first_preview.status_code == 200
    headers = {"Idempotency-Key": "fixed-idempotency-request"}
    first = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=headers,
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": first_preview.json()["data"]["preview_token"],
            "confirmation_text": "确认试运行",
        },
    )
    assert first.status_code == 200

    second_preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": [lead.lead_key]},
    )
    assert second_preview.status_code == 200
    conflict = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=headers,
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": second_preview.json()["data"]["preview_token"],
            "confirmation_text": "确认试运行",
        },
    )

    assert conflict.status_code == 409
    assert "idempotency_key_conflict" in conflict.json()["detail"]


def test_m3_allocation_page_permissions_match_each_subview_api_contract(
    client: TestClient, db_session: Session
) -> None:
    def login_with_only(page_key: str) -> None:
        user_id = f"admin-{page_key.lower()}"
        user = User(
            user_id=user_id,
            username=user_id,
            display_name=user_id,
            role="admin",
            status="active",
            is_initialized=True,
            password_hash=hash_password_pbkdf2("permission-password"),
        )
        db_session.add(user)
        db_session.flush()
        replace_user_overrides(
            db_session,
            user,
            extra_allow={page_key},
            extra_deny=set(ALL_PAGE_KEYS) - {page_key},
            updated_by="system-admin",
        )
        db_session.commit()
        client.cookies.clear()
        login = client.post(
            "/api/v1/auth/login",
            json={"username": user_id, "password": "permission-password"},
        )
        assert login.status_code == 200

    login_with_only("D06")
    assert client.get("/api/v1/admin/clue-allocation/eligible-leads").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/cycles").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/decisions").status_code == 403
    assert client.get("/api/v1/admin/clue-allocation/headquarters-pool").status_code == 403

    login_with_only("D07")
    assert client.get("/api/v1/admin/clue-allocation/cycles").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/decisions").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/master-leads").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/eligible-leads").status_code == 403
    assert client.get("/api/v1/admin/clue-allocation/headquarters-pool").status_code == 403

    login_with_only("D08")
    assert client.get("/api/v1/admin/clue-allocation/headquarters-pool").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/cycles").status_code == 403
    assert client.get("/api/v1/admin/clue-allocation/decisions").status_code == 403
    assert client.get("/api/v1/admin/clue-allocation/eligible-leads").status_code == 403


def test_m3_read_models_are_restricted_to_the_admin_store_scope(
    client: TestClient,
    db_session: Session,
) -> None:
    scoped_lead = _seed_trial_ready_lead(db_session, lead_key="scoped-lead")
    scoped_store_id = scoped_lead.anchor_store_id
    assert scoped_store_id is not None
    outside_store = DimStore(
        store_id="outside-store",
        store_name="Outside Store",
        is_active=True,
        standard_province="CN-BJ",
        standard_city="CN-BJ",
        city_code="CN-BJ",
        longitude=Decimal("116.407000"),
        latitude=Decimal("39.904000"),
        is_douyin_clue_applicable=True,
        participates_in_clue_allocation=True,
        location_source="test",
        location_status="valid",
        location_updated_at=_dt(1),
    )
    outside_lead = ClueMasterLead(
        lead_key="outside-lead",
        source_clue_row_key="raw-outside-lead",
        source_identity_key="identity-outside-lead",
        canonical_clue_id="clue-outside-lead",
        order_id="order-outside-lead",
        raw_order_status="履约中",
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state="pending_allocation",
        anchor_poi_id="poi-outside-lead",
        anchor_store_id=outside_store.store_id,
        anchor_source="douyin_follow_poi",
        anchor_province="CN-BJ",
        anchor_city="CN-BJ",
        anchor_city_code="CN-BJ",
        anchor_longitude=outside_store.longitude,
        anchor_latitude=outside_store.latitude,
        first_seen_at=_dt(1),
        last_seen_at=_dt(1),
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    cycle = ClueAllocationCycle(
        allocation_cycle_id="scope-cycle",
        cycle_type="trial",
        execution_mode="trial",
        status="completed",
        selected_lead_keys=[scoped_lead.lead_key, outside_lead.lead_key],
        requested_lead_count=2,
        active_lead_count=2,
        planned_impact_json={
            "lead_keys": [scoped_lead.lead_key, outside_lead.lead_key],
            "auto_expiry_enabled": False,
        },
        actual_impact_json={"assigned": 2, "headquarters": 0, "skipped": 0, "failed": 0},
        actor="system-admin",
        created_at=_dt(2),
        executed_at=_dt(2),
        completed_at=_dt(2),
    )
    scoped_decision = ClueAllocationDecision(
        decision_id="scope-decision",
        attempt_key="scope-attempt",
        lead_key=scoped_lead.lead_key,
        order_id=scoped_lead.order_id,
        strategy_type="nearby_city_optimization",
        execution_order=1,
        allocation_cycle_id=cycle.allocation_cycle_id,
        execution_mode="trial",
        selected_store_id=scoped_store_id,
        selected_store_name="Anchor",
        decision_status="selected",
        decision_snapshot={
            "candidates": [
                {"store_id": scoped_store_id, "store_name": "Anchor"},
                {"store_id": outside_store.store_id, "store_name": outside_store.store_name},
            ],
            "selected_store_id": scoped_store_id,
        },
        actor="system-admin",
        executed_at=_dt(2),
    )
    outside_decision = ClueAllocationDecision(
        decision_id="outside-decision",
        attempt_key="outside-attempt",
        lead_key=outside_lead.lead_key,
        order_id=outside_lead.order_id,
        strategy_type="nearby_city_optimization",
        execution_order=1,
        allocation_cycle_id=cycle.allocation_cycle_id,
        execution_mode="trial",
        selected_store_id=outside_store.store_id,
        selected_store_name=outside_store.store_name,
        decision_status="selected",
        decision_snapshot={},
        actor="system-admin",
        executed_at=_dt(2),
    )
    score_run = StoreScoreSnapshotRun(
        snapshot_run_id="scope-score-run",
        snapshot_date=_dt(2).date(),
        run_mode="manual",
        window_start=_dt(1),
        window_end=_dt(2),
        candidate_store_count=2,
        snapshot_count=2,
        triggered_by="system-admin",
        computed_at=_dt(2),
    )
    group = ClueStoreGroup(
        store_group_id="scope-group",
        group_name="Mixed Scope Group",
        created_by="system-admin",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all(
        [
            outside_store,
            outside_lead,
            cycle,
            ClueAllocationCycleItem(
                cycle_item_id="scope-item",
                allocation_cycle_id=cycle.allocation_cycle_id,
                sequence_no=1,
                lead_key=scoped_lead.lead_key,
                order_id=scoped_lead.order_id,
                item_status="assigned",
                decision_id=scoped_decision.decision_id,
                attempt_count=1,
                started_at=_dt(2),
                completed_at=_dt(2),
                created_at=_dt(2),
                updated_at=_dt(2),
            ),
            ClueAllocationCycleItem(
                cycle_item_id="outside-item",
                allocation_cycle_id=cycle.allocation_cycle_id,
                sequence_no=2,
                lead_key=outside_lead.lead_key,
                order_id=outside_lead.order_id,
                item_status="assigned",
                decision_id=outside_decision.decision_id,
                attempt_count=1,
                started_at=_dt(2),
                completed_at=_dt(2),
                created_at=_dt(2),
                updated_at=_dt(2),
            ),
            scoped_decision,
            outside_decision,
            ClueAllocationCandidate(
                candidate_id="scope-candidate",
                decision_id=scoped_decision.decision_id,
                lead_key=scoped_lead.lead_key,
                order_id=scoped_lead.order_id,
                strategy_type=scoped_decision.strategy_type,
                store_id=scoped_store_id,
                store_name_snapshot="Anchor",
                eligibility_status="eligible",
                is_serviceable=True,
                is_selected=True,
                evaluated_at=_dt(2),
                created_at=_dt(2),
                updated_at=_dt(2),
            ),
            ClueAllocationCandidate(
                candidate_id="hidden-candidate",
                decision_id=scoped_decision.decision_id,
                lead_key=scoped_lead.lead_key,
                order_id=scoped_lead.order_id,
                strategy_type=scoped_decision.strategy_type,
                store_id=outside_store.store_id,
                store_name_snapshot=outside_store.store_name,
                eligibility_status="excluded",
                is_serviceable=False,
                is_selected=False,
                evaluated_at=_dt(2),
                created_at=_dt(2),
                updated_at=_dt(2),
            ),
            score_run,
            StoreScoreSnapshot(
                snapshot_id="scope-score",
                snapshot_run_id=score_run.snapshot_run_id,
                snapshot_date=score_run.snapshot_date,
                run_mode=score_run.run_mode,
                store_id=scoped_store_id,
                city_code="CN-SH",
                window_start=score_run.window_start,
                window_end=score_run.window_end,
                composite_score=Decimal("0.8"),
                computed_at=_dt(2),
            ),
            StoreScoreSnapshot(
                snapshot_id="outside-score",
                snapshot_run_id=score_run.snapshot_run_id,
                snapshot_date=score_run.snapshot_date,
                run_mode=score_run.run_mode,
                store_id=outside_store.store_id,
                city_code="CN-BJ",
                window_start=score_run.window_start,
                window_end=score_run.window_end,
                composite_score=Decimal("0.9"),
                computed_at=_dt(2),
            ),
            group,
            ClueStoreGroupMember(store_group_id=group.store_group_id, store_id=scoped_store_id),
            ClueStoreGroupMember(store_group_id=group.store_group_id, store_id=outside_store.store_id),
            User(
                user_id="scoped-admin",
                username="scoped-admin",
                display_name="Scoped Admin",
                role="admin",
                status="active",
                is_initialized=True,
                store_scope_mode="specified",
                password_hash=hash_password_pbkdf2("scoped-admin-password"),
            ),
        ]
    )
    db_session.flush()
    db_session.add(UserStoreScope(user_id="scoped-admin", store_id=scoped_store_id))

    scoped_hq_lead = _seed_headquarters_lead(
        db_session,
        lead_key="scope-hq-lead",
        order_id="scope-hq-order",
        normalized_order_status="active",
        raw_order_status="履约中",
        reason="no_candidate",
        entered_at=_dt(3),
    )
    outside_hq_lead = _seed_headquarters_lead(
        db_session,
        lead_key="outside-hq-lead",
        order_id="outside-hq-order",
        normalized_order_status="active",
        raw_order_status="履约中",
        reason="no_candidate",
        entered_at=_dt(3),
    )
    scoped_hq_lead.anchor_store_id = scoped_store_id
    outside_hq_lead.anchor_store_id = outside_store.store_id
    db_session.commit()

    client.cookies.clear()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "scoped-admin", "password": "scoped-admin-password"},
    )
    assert login.status_code == 200

    master_rows = client.get("/api/v1/admin/clue-allocation/master-leads").json()["data"]["rows"]
    assert {row["order_id"] for row in master_rows} == {
        scoped_lead.order_id,
        scoped_hq_lead.order_id,
    }
    assert {row["anchor_store_id"] for row in master_rows} == {scoped_store_id}
    eligible_rows = client.get("/api/v1/admin/clue-allocation/eligible-leads").json()["data"]["rows"]
    assert [row["lead_key"] for row in eligible_rows] == [scoped_lead.lead_key]

    cycle_response = client.get("/api/v1/admin/clue-allocation/cycles")
    assert cycle_response.status_code == 200
    cycle_row = cycle_response.json()["data"]["rows"][0]
    assert cycle_row["selected_lead_keys"] == [scoped_lead.lead_key]
    assert cycle_row["requested_lead_count"] == 1
    assert cycle_row["actual_impact"] == {
        "assigned": 1,
        "headquarters": 0,
        "skipped": 0,
        "failed": 0,
        "total": 1,
    }
    cycle_detail = client.get(f"/api/v1/admin/clue-allocation/cycles/{cycle.allocation_cycle_id}")
    assert cycle_detail.status_code == 200
    assert [row["lead_key"] for row in cycle_detail.json()["data"]["items"]] == [scoped_lead.lead_key]

    decision_rows = client.get("/api/v1/admin/clue-allocation/decisions").json()["data"]["rows"]
    assert [row["decision_id"] for row in decision_rows] == [scoped_decision.decision_id]
    assert client.get(
        f"/api/v1/admin/clue-allocation/decisions/{outside_decision.decision_id}"
    ).status_code == 404
    decision_detail = client.get(
        f"/api/v1/admin/clue-allocation/decisions/{scoped_decision.decision_id}"
    ).json()["data"]
    assert [row["store_id"] for row in decision_detail["candidates"]] == [scoped_store_id]
    assert [row["store_id"] for row in decision_detail["decision"]["payload"]["candidates"]] == [
        scoped_store_id
    ]

    score_data = client.get("/api/v1/admin/clue-allocation/store-scores").json()["data"]
    score_rows = score_data["rows"]
    assert [row["store_id"] for row in score_rows] == [scoped_store_id]
    assert score_data["run"]["candidate_store_count"] == 1
    assert score_data["run"]["snapshot_count"] == 1
    assert score_data["run"]["triggered_by"] is None
    headquarters_data = client.get("/api/v1/admin/clue-allocation/headquarters-pool").json()["data"]
    assert [row["lead_key"] for row in headquarters_data["rows"]] == [scoped_hq_lead.lead_key]
    assert headquarters_data["summary"]["current_inventory"] == 1
    group_rows = client.get("/api/v1/admin/clue-allocation/store-groups").json()["data"]["rows"]
    assert len(group_rows) == 1
    assert group_rows[0]["store_group_id"] == group.store_group_id
    assert group_rows[0]["member_store_ids"] == [scoped_store_id]
    assert client.get("/api/v1/admin/clue-allocation/audit-logs").status_code == 403


def test_m3_headquarters_pool_is_readable_without_contact_data(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="headquarters-lead")
    lead.pool_location = "headquarters_pool"
    lead.allocation_state = "headquarters"
    enter_headquarters_pool(
        db_session,
        lead=lead,
        reason="no_candidate",
        entered_at=_dt(2),
        source_snapshot={"phone_plain": "13812345678", "reason": "no_candidate"},
    )
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/admin/clue-allocation/headquarters-pool?pool_status=active")
    eligible = client.get("/api/v1/admin/clue-allocation/eligible-leads")

    assert response.status_code == 200
    row = response.json()["data"]["rows"][0]
    assert row["lead_key"] == lead.lead_key
    assert row["reason_code"] == "no_eligible_candidate"
    assert row["reason_label"] == "所有启用策略均无可用门店"
    assert row["reason"] == "no_eligible_candidate"
    assert row["entry_status"] == "active"
    assert row["normalized_order_status"] == "active"
    assert "phone" not in json.dumps(row, ensure_ascii=False).lower()
    assert eligible.status_code == 200
    assert eligible.json()["data"]["rows"] == []
    assert db_session.scalar(select(ClueHeadquartersPoolEntry)) is not None
    assert db_session.scalar(select(ClueAllocationAuditLog)) is None


def test_m3_headquarters_pool_filters_inventory_and_order_status(
    client: TestClient, db_session: Session
) -> None:
    _seed_headquarters_lead(
        db_session,
        lead_key="hq-filter-match",
        order_id="order-filter-match-001",
        normalized_order_status="active",
        raw_order_status="履约中",
        reason="no_candidate",
        entered_at=_dt(2, 15),
    )
    _seed_headquarters_lead(
        db_session,
        lead_key="hq-next-local-day",
        order_id="order-next-day-002",
        normalized_order_status="active",
        raw_order_status="履约中",
        reason="no_candidate",
        entered_at=_dt(2, 16),
    )
    _seed_headquarters_lead(
        db_session,
        lead_key="hq-other-reason",
        order_id="order-other-reason-003",
        normalized_order_status="active",
        raw_order_status="履约中",
        reason="follow_poi_missing",
        entered_at=_dt(2, 12),
    )
    _seed_headquarters_lead(
        db_session,
        lead_key="hq-closed-verified",
        order_id="order-verified-004",
        normalized_order_status="verified",
        raw_order_status="已核销",
        reason="strategies_exhausted",
        entered_at=_dt(1),
        pool_status="closed",
    )
    _login(client)

    response = client.get(
        "/api/v1/admin/clue-allocation/headquarters-pool",
        params={
            "entry_status": "active",
            "reason_code": "no_eligible_candidate",
            "entered_date_start": "2026-07-02",
            "entered_date_end": "2026-07-02",
            "normalized_order_status": "active",
            "city_code": "CN-SH",
            "q": "filter-match",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 1
    assert data["summary"] == {"current_inventory": 3, "filtered_total": 1}
    assert data["filter_options"]["pool_statuses"] == ["active", "closed"]
    assert data["filter_options"]["reasons"] == [
        "missing_follow_poi",
        "no_eligible_candidate",
        "all_strategies_exhausted",
    ]
    assert data["filter_options"]["order_statuses"] == ["active", "verified"]
    assert data["filter_options"]["entry_statuses"] == ["active", "closed"]
    assert data["filter_options"]["reason_codes"] == [
        "missing_follow_poi",
        "no_eligible_candidate",
        "all_strategies_exhausted",
    ]
    assert data["filter_options"]["normalized_order_statuses"] == ["active", "verified"]
    assert data["filter_options"]["city_codes"] == ["CN-SH"]
    row = data["rows"][0]
    assert row["lead_key"] == "hq-filter-match"
    assert row["order_id"] == "order-filter-match-001"
    assert row["order_status"] == "active"
    assert row["normalized_order_status"] == "active"
    assert row["raw_order_status"] == "履约中"
    assert "phone" not in json.dumps(data, ensure_ascii=False).lower()


def test_m3_headquarters_pool_rejects_an_inverted_entry_date_range(
    client: TestClient,
) -> None:
    _login(client)

    response = client.get(
        "/api/v1/admin/clue-allocation/headquarters-pool",
        params={"entered_date_start": "2026-07-03", "entered_date_end": "2026-07-02"},
    )

    assert response.status_code == 422


def test_m3_store_account_cannot_read_headquarters_pool_even_with_d08_override(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add(
        User(
            user_id="hq-store-user",
            username="hq-store-user",
            display_name="HQ Store User",
            role="store",
            status="active",
            is_initialized=True,
            password_hash=hash_password_pbkdf2("store-password"),
            store_scope_mode="specified",
        )
    )
    db_session.commit()
    _login(client)
    db_session.add(
        UserPagePermissionOverride(
            user_id="hq-store-user",
            page_key="D08",
            effect="allow",
            updated_by="system-admin",
            updated_at=_dt(1),
        )
    )
    db_session.commit()
    client.post("/api/v1/auth/logout")
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "hq-store-user", "password": "store-password"},
    )
    assert login.status_code == 200

    response = client.get("/api/v1/admin/clue-allocation/headquarters-pool")

    assert response.status_code == 403
    assert response.json()["detail"] == "Administrator access required"


def test_m3_rebuild_uses_a_source_cycle_and_matching_preview(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="rebuild-lead")
    _login(client)
    preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200
    trial = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=IDEMPOTENCY_HEADERS,
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview.json()["data"]["preview_token"],
            "confirmation_text": "确认试运行",
        },
    )
    assert trial.status_code == 200
    source_cycle_id = trial.json()["data"]["allocation_cycle_id"]

    missing_preview = client.post(
        "/api/v1/admin/clue-allocation/rebuild-cycles",
        headers=REBUILD_IDEMPOTENCY_HEADERS,
        json={"source_cycle_id": source_cycle_id, "confirmation_text": "确认重建试运行"},
    )
    assert missing_preview.status_code == 422

    rebuild_preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial_rebuild", "source_cycle_id": source_cycle_id},
    )
    assert rebuild_preview.status_code == 200
    assert rebuild_preview.json()["data"]["operation"] == "trial_rebuild"
    assert rebuild_preview.json()["data"]["source_cycle_id"] == source_cycle_id

    rebuilt = client.post(
        "/api/v1/admin/clue-allocation/rebuild-cycles",
        headers=REBUILD_IDEMPOTENCY_HEADERS,
        json={
            "source_cycle_id": source_cycle_id,
            "preview_token": rebuild_preview.json()["data"]["preview_token"],
            "confirmation_text": "确认重建试运行",
        },
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["data"]["parent_cycle_id"] == source_cycle_id


def test_m3_rebuild_preview_token_cannot_elevate_privileged_confirmation(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="rebuild-confirmation-lead")
    _login(client)
    preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial", "lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200
    trial = client.post(
        "/api/v1/admin/clue-allocation/trial-cycles",
        headers=IDEMPOTENCY_HEADERS,
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview.json()["data"]["preview_token"],
            "confirmation_text": "确认试运行",
        },
    )
    assert trial.status_code == 200
    source_cycle_id = trial.json()["data"]["allocation_cycle_id"]

    rebuild_preview = client.post(
        "/api/v1/admin/clue-allocation/cycle-previews",
        json={"operation": "trial_rebuild", "source_cycle_id": source_cycle_id},
    )
    assert rebuild_preview.status_code == 200

    mismatched_execution = client.post(
        "/api/v1/admin/clue-allocation/rebuild-cycles",
        headers=REBUILD_IDEMPOTENCY_HEADERS,
        json={
            "source_cycle_id": source_cycle_id,
            "preview_token": rebuild_preview.json()["data"]["preview_token"],
            "confirmation_text": "确认重建试运行",
            "privileged_confirmation": True,
        },
    )

    assert mismatched_execution.status_code == 422
    assert "preview_token_mismatch" in mismatched_execution.json()["detail"]
