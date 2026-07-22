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

from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    ClueAllocationAuditLog,
    ClueAllocationCycle,
    ClueAssignmentRound,
    ClueHeadquartersPoolEntry,
    ClueMasterLead,
    DimStore,
    User,
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
    assert client.get("/api/v1/admin/clue-allocation/audit-logs").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/rules").status_code == 200
    assert client.get("/api/v1/admin/clue-allocation/decisions").status_code == 200
    assert client.post(
        "/api/v1/admin/clue-allocation/rules",
        json={"name": "ordinary-admin-rule", "scope": {"scope_type": "global"}},
    ).status_code == 403
    assert client.post(
        "/api/v1/admin/clue-allocation/cycles/preview",
        json={"lead_keys": ["trial-lead"]},
    ).status_code == 403
    assert client.post(
        "/api/v1/admin/clue-allocation/cycles/trial",
        json={"lead_keys": ["trial-lead"], "confirm": True},
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
        "/api/v1/admin/clue-allocation/cycles/preview",
        json={"lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["summary"]["assigned"] == 1
    preview_token = preview.json()["data"]["preview_token"]
    assert db_session.scalar(select(ClueAllocationCycle)) is None
    assert db_session.scalar(select(ClueAssignmentRound)) is None

    missing_preview = client.post(
        "/api/v1/admin/clue-allocation/cycles/trial",
        json={"lead_keys": [lead.lead_key], "confirm": True},
    )
    assert missing_preview.status_code == 422

    missing_confirmation = client.post(
        "/api/v1/admin/clue-allocation/cycles/trial",
        json={"lead_keys": [lead.lead_key], "preview_token": preview_token},
    )
    assert missing_confirmation.status_code == 422

    executed = client.post(
        "/api/v1/admin/clue-allocation/cycles/trial",
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview_token,
            "confirm": True,
        },
    )
    assert executed.status_code == 200
    payload = executed.json()["data"]
    assert payload["execution_mode"] == "trial"
    assert payload["summary"]["assigned"] == 1
    round_row = db_session.scalar(select(ClueAssignmentRound))
    assert round_row is not None
    assert round_row.execution_mode == "trial"
    assert round_row.auto_expiry_enabled is False

    retried = client.post(
        "/api/v1/admin/clue-allocation/cycles/trial",
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview_token,
            "confirm": True,
        },
    )
    assert retried.status_code == 200
    assert retried.json()["data"]["allocation_cycle_id"] == payload["allocation_cycle_id"]
    assert db_session.scalar(select(ClueAllocationCycle).where(ClueAllocationCycle.preview_token_hash.is_not(None)))
    assert db_session.scalar(select(ClueAllocationAuditLog)).detail_json["preview_token_hash"] != preview_token

    cycles = client.get("/api/v1/admin/clue-allocation/cycles")
    audits = client.get("/api/v1/admin/clue-allocation/audit-logs")
    assert cycles.status_code == 200
    assert cycles.json()["data"]["rows"][0]["allocation_cycle_id"] == payload["allocation_cycle_id"]
    assert audits.status_code == 200
    assert audits.json()["data"]["rows"][0]["event_type"] == "trial_executed"
    assert "phone" not in json.dumps(audits.json(), ensure_ascii=False).lower()


def test_m3_trial_preview_refuses_execution_when_the_eligible_set_changes(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="stale-preview-lead")
    _login(client)
    preview = client.post(
        "/api/v1/admin/clue-allocation/cycles/preview",
        json={"lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200

    lead.lifecycle_status = "closed_verified"
    db_session.commit()

    execution = client.post(
        "/api/v1/admin/clue-allocation/cycles/trial",
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview.json()["data"]["preview_token"],
            "confirm": True,
        },
    )

    assert execution.status_code == 422
    assert "preview_no_longer_matches" in execution.json()["detail"]


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
    assert row["reason"] == "no_candidate"
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
            "pool_status": "active",
            "reason": "no_candidate",
            "entered_date_start": "2026-07-02",
            "entered_date_end": "2026-07-02",
            "order_status": "active",
            "order_id": "filter-match",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 1
    assert data["summary"] == {"current_inventory": 3, "filtered_total": 1}
    assert data["filter_options"]["pool_statuses"] == ["active", "closed"]
    assert data["filter_options"]["reasons"] == [
        "follow_poi_missing",
        "no_candidate",
        "strategies_exhausted",
    ]
    assert data["filter_options"]["order_statuses"] == ["active", "verified"]
    row = data["rows"][0]
    assert row["lead_key"] == "hq-filter-match"
    assert row["order_id"] == "order-filter-match-001"
    assert row["order_status"] == "active"
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


def test_m3_rebuild_uses_a_source_cycle_and_matching_preview(
    client: TestClient, db_session: Session
) -> None:
    lead = _seed_trial_ready_lead(db_session, lead_key="rebuild-lead")
    _login(client)
    preview = client.post(
        "/api/v1/admin/clue-allocation/cycles/preview",
        json={"lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200
    trial = client.post(
        "/api/v1/admin/clue-allocation/cycles/trial",
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview.json()["data"]["preview_token"],
            "confirm": True,
        },
    )
    assert trial.status_code == 200
    source_cycle_id = trial.json()["data"]["allocation_cycle_id"]

    missing_preview = client.post(
        "/api/v1/admin/clue-allocation/cycles/rebuild",
        json={"source_cycle_id": source_cycle_id, "confirm": True},
    )
    assert missing_preview.status_code == 422

    rebuild_preview = client.post(
        "/api/v1/admin/clue-allocation/cycles/preview",
        json={"operation": "rebuild", "source_cycle_id": source_cycle_id},
    )
    assert rebuild_preview.status_code == 200
    assert rebuild_preview.json()["data"]["operation"] == "rebuild"
    assert rebuild_preview.json()["data"]["source_cycle_id"] == source_cycle_id

    rebuilt = client.post(
        "/api/v1/admin/clue-allocation/cycles/rebuild",
        json={
            "source_cycle_id": source_cycle_id,
            "preview_token": rebuild_preview.json()["data"]["preview_token"],
            "confirm": True,
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
        "/api/v1/admin/clue-allocation/cycles/preview",
        json={"lead_keys": [lead.lead_key]},
    )
    assert preview.status_code == 200
    trial = client.post(
        "/api/v1/admin/clue-allocation/cycles/trial",
        json={
            "lead_keys": [lead.lead_key],
            "preview_token": preview.json()["data"]["preview_token"],
            "confirm": True,
        },
    )
    assert trial.status_code == 200
    source_cycle_id = trial.json()["data"]["allocation_cycle_id"]

    rebuild_preview = client.post(
        "/api/v1/admin/clue-allocation/cycles/preview",
        json={"operation": "rebuild", "source_cycle_id": source_cycle_id},
    )
    assert rebuild_preview.status_code == 200

    mismatched_execution = client.post(
        "/api/v1/admin/clue-allocation/cycles/rebuild",
        json={
            "source_cycle_id": source_cycle_id,
            "preview_token": rebuild_preview.json()["data"]["preview_token"],
            "confirm": True,
            "privileged_confirmation": True,
        },
    )

    assert mismatched_execution.status_code == 422
    assert "preview_token_mismatch" in mismatched_execution.json()["detail"]
