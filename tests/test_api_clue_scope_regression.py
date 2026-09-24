"""Exercise the real clue routes with authenticated principals of different scopes."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency
from test_clue_follow_up_atomicity import seed_active_round
from apps.api.dy_api.models import ClueCenterOrder, DimStore, DimStoreOrgAssignment


@pytest.mark.parametrize("stale_projection_store", [False, True])
@pytest.mark.parametrize("role,mode,store_ids,allowed", [
    ("admin", "all", (), True),
    ("admin", "specified", ("audit-store",), True),
    ("admin", "specified", ("other-store",), False),
    ("admin", "specified", (), False),
    ("admin", "none", ("audit-store",), False),
    ("store", "specified", ("audit-store",), True),
    ("store", "specified", ("other-store",), False),
    ("store", "all", ("audit-store",), False),
])
def test_scope_matches_list_detail_phone_and_follow_up(
    monkeypatch, db_session, role: str, mode: str, store_ids: tuple[str, ...], allowed: bool, stale_projection_store: bool,
) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    seed_active_round(db_session)
    db_session.add(DimStore(store_id="audit-store", store_name="Audit Store", service_store_code="AUDIT", is_active=True))
    db_session.add(DimStoreOrgAssignment(service_store_code="AUDIT", group_name="Audit Group", service_center_name="Audit Center", district_name="Audit District", area_name="Audit Area"))
    db_session.commit()
    if stale_projection_store:
        db_session.get(ClueCenterOrder, "audit-order").assigned_store_id = "old-store"
        db_session.commit()
    principal = AuthContext(
        user_id="audit-user", username="audit-user", display_name="Audit User",
        role=role, auth_type="user", store_scope_mode=mode, store_ids=store_ids,
        page_keys=("A02",),
    )
    app = create_app()

    def scoped_session():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_session_dependency] = scoped_session
    with TestClient(app) as client:
        options = client.get("/api/v1/clues/filter-options/organizations", params={"level": "area"})
        assert options.status_code == 200
        assert bool(options.json()["data"]["options"]) is allowed
        query = {"org_level": "area", "org_key": '["Audit Center","Audit District","Audit Area"]'}
        scoped = client.get("/api/v1/clues/assignment-rounds", params=query)
        assert scoped.status_code == 200
        assert bool(scoped.json()["data"]["rows"]) is allowed
        overview = client.get("/api/v1/clues/overview", params=query)
        assert bool(overview.json()["data"]["total_clues"]) is allowed
        exported = client.get("/api/v1/clues/assignment-rounds/export", params=query)
        assert exported.status_code == 200
        assert ("audit-order" in exported.text) is allowed
        invalid = client.get("/api/v1/clues/assignment-rounds", params={"org_level": "area", "org_key": '["Audit Area"]'})
        assert invalid.status_code == 422
        listing = client.get("/api/v1/clues/assignment-rounds").json()["data"]
        assert bool(listing["rows"]) is allowed
        if allowed:
            assert listing["rows"][0]["can_operate_current_round"] is True
        detail = client.get("/api/v1/clues/orders/audit-order")
        assert detail.status_code == (200 if allowed else 404)
        phone = client.get("/api/v1/clues/orders/audit-order/phone")
        assert phone.status_code == (200 if allowed else 404)
        follow = client.post("/api/v1/clues/orders/audit-order/follow-up", json={
            "assignment_round_id": "audit-round", "follow_result": "appointment",
        })
        assert follow.status_code == (200 if allowed else 403)
