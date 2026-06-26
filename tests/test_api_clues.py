from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes import _data as data_module  # noqa: E402
from dy_api.routes import admin as admin_module  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueFollowUpRecord,
    DimStore,
    RawDouyinClue,
    User,
    UserStoreScope,
)
from dy_api.auth import hash_password_pbkdf2  # noqa: E402


def _dt(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 6, day, hour, 0, tzinfo=timezone.utc)


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


def _login_user(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def _seed_clue_center(session: Session) -> None:
    session.add_all(
        [
            DimStore(
                store_id="store-1",
                store_name="Store One",
                certified_subject_name="Subject One",
                is_active=True,
            ),
            DimStore(
                store_id="store-2",
                store_name="Store Two",
                certified_subject_name="Subject Two",
                is_active=True,
            ),
            ClueCenterOrder(
                order_id="order-1",
                source_clue_ids=["clue-1"],
                source_clue_count=1,
                canonical_clue_id="clue-1",
                lead_status="converted",
                current_assignment_round_id="order-1-1",
                current_round_no=1,
                current_round_status="active_followed",
                assigned_at=_dt(1),
                assigned_at_source="clue_create_time_detail",
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                assigned_city="Shanghai",
                assigned_province="Shanghai",
                phone_plain="13812345678",
                phone_masked="138****5678",
                phone_source="telephone",
                product_id="sku-1",
                product_name="Service Product",
                product_type="Car Service",
                author_nickname="Author",
                follow_result="success",
                is_followed=True,
                is_follow_success=True,
                verified_store_id="store-1",
                verified_store_name="Store One",
                verified_at=_dt(2),
                is_self_store_verified=True,
                created_at=_dt(1),
                updated_at=_dt(2),
            ),
            ClueAssignmentRound(
                assignment_round_id="order-1-1",
                order_id="order-1",
                round_no=1,
                assigned_at=_dt(1),
                assigned_at_source="clue_create_time_detail",
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                followed_at=_dt(1, 12),
                follow_result="success",
                is_followed=True,
                is_follow_success=True,
                round_status="active_followed",
                verified_store_id="store-1",
                verified_store_name="Store One",
                verified_at=_dt(2),
                is_self_store_verified=True,
                created_at=_dt(1),
                updated_at=_dt(2),
            ),
            ClueCenterOrder(
                order_id="order-2",
                source_clue_ids=["clue-2"],
                source_clue_count=1,
                canonical_clue_id="clue-2",
                lead_status="active",
                current_assignment_round_id="order-2-1",
                current_round_no=1,
                current_round_status="active_unfollowed",
                assigned_at=_dt(1),
                assigned_at_source="clue_create_time_detail",
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                assigned_city="Shanghai",
                assigned_province="Shanghai",
                phone_plain="13912345678",
                phone_masked="139****5678",
                phone_source="telephone",
                product_id="sku-2",
                product_name="Other Product",
                product_type="Car Service",
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                is_self_store_verified=False,
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
            ClueAssignmentRound(
                assignment_round_id="order-2-1",
                order_id="order-2",
                round_no=1,
                assigned_at=_dt(1),
                assigned_at_source="clue_create_time_detail",
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                round_status="active_unfollowed",
                is_self_store_verified=False,
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
        ]
    )
    session.commit()


def test_clue_dashboard_contract(client: TestClient, db_session: Session) -> None:
    _seed_clue_center(db_session)
    _login(client)

    filters = client.get("/api/v1/clues/filters")
    assert filters.status_code == 200
    assert filters.json()["data"]["assigned_stores"] == [
        {"store_id": "store-1", "store_name": "Store One"}
    ]

    overview = client.get("/api/v1/clues/overview?assigned_store_id=store-1")
    assert overview.status_code == 200
    metrics = overview.json()["data"]
    assert metrics["total_clues"] == 2
    assert metrics["active_clues"] == 2
    assert metrics["follow_rate"] == 0.5
    assert metrics["follow_success_rate"] == 0.5
    assert metrics["verified_count"] == 1
    assert metrics["self_store_verify_rate"] == 0.5

    details = client.get("/api/v1/clues/assignment-rounds?assigned_store_id=store-1")
    assert details.status_code == 200
    payload = details.json()["data"]
    assert payload["pagination"]["total"] == 2
    row = payload["rows"][0]
    assert row["phone_masked"] in {"138****5678", "139****5678"}
    assert row["product_name"] in {"Service Product", "Other Product"}
    assert row["store_display_status"] in {"待跟进", "已核销"}
    assert "telephone" not in row
    assert row["remaining_reassign_seconds"] is None


def test_clue_filters_include_store_location_and_verification_status(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    _login(client)

    filters = client.get("/api/v1/clues/filters")
    assert filters.status_code == 200
    data = filters.json()["data"]
    assert data["assigned_provinces"] == ["Shanghai"]
    assert data["assigned_cities"] == ["Shanghai"]
    assert data["verification_statuses"] == [
        "unverified",
        "self_store_verified",
        "other_store_verified",
    ]


def test_clue_date_end_filter_includes_selected_calendar_day(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    db_session.add_all(
        [
            ClueCenterOrder(
                order_id="order-3",
                source_clue_ids=["clue-3"],
                source_clue_count=1,
                canonical_clue_id="clue-3",
                lead_status="active",
                current_assignment_round_id="order-3-1",
                current_round_no=1,
                current_round_status="active_unfollowed",
                assigned_at=_dt(2, 9),
                assigned_at_source="clue_create_time_detail",
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                assigned_city="Shanghai",
                assigned_province="Shanghai",
                phone_plain="13712345678",
                phone_masked="137****5678",
                phone_source="telephone",
                product_id="sku-3",
                product_name="Calendar Day Product",
                product_type="Car Service",
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                is_self_store_verified=False,
                created_at=_dt(2, 9),
                updated_at=_dt(2, 9),
            ),
            ClueAssignmentRound(
                assignment_round_id="order-3-1",
                order_id="order-3",
                round_no=1,
                assigned_at=_dt(2, 9),
                assigned_at_source="clue_create_time_detail",
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                round_status="active_unfollowed",
                is_self_store_verified=False,
                created_at=_dt(2, 9),
                updated_at=_dt(2, 9),
            ),
        ]
    )
    db_session.commit()
    _login(client)

    response = client.get(
        "/api/v1/clues/assignment-rounds",
        params={
            "assigned_date_start": "2026-06-01",
            "assigned_date_end": "2026-06-02",
        },
    )

    assert response.status_code == 200
    order_ids = {row["order_id"] for row in response.json()["data"]["rows"]}
    assert order_ids == {"order-1", "order-2", "order-3"}


def test_clue_rounds_can_filter_by_location_store_and_verification_status(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    _login(client)

    unverified = client.get(
        "/api/v1/clues/assignment-rounds",
        params={"province": "Shanghai", "verification_status": "unverified"},
    )
    assert unverified.status_code == 200
    assert [row["order_id"] for row in unverified.json()["data"]["rows"]] == [
        "order-2"
    ]

    verified = client.get(
        "/api/v1/clues/assignment-rounds",
        params={
            "assigned_store_id": "store-1",
            "city": "Shanghai",
            "verification_status": "self_store_verified",
        },
    )
    assert verified.status_code == 200
    assert [row["order_id"] for row in verified.json()["data"]["rows"]] == [
        "order-1"
    ]

    pending_follow = client.get(
        "/api/v1/clues/assignment-rounds",
        params={"store_display_status": "待跟进"},
    )
    assert pending_follow.status_code == 200
    assert [row["order_id"] for row in pending_follow.json()["data"]["rows"]] == [
        "order-2"
    ]

    converted = client.get(
        "/api/v1/clues/overview",
        params={"store_display_status": "已核销"},
    )
    assert converted.status_code == 200
    assert converted.json()["data"]["total_clues"] == 1

    other_province = client.get(
        "/api/v1/clues/overview",
        params={"province": "Beijing", "verification_status": "unverified"},
    )
    assert other_province.status_code == 200
    assert other_province.json()["data"]["total_clues"] == 0


def test_clue_order_detail_returns_all_assignment_rounds(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    db_session.add(
        ClueAssignmentRound(
            assignment_round_id="order-1-2",
            order_id="order-1",
            round_no=2,
            assigned_at=_dt(2, 9),
            assigned_at_source="manual_reassign",
            assigned_store_id="store-2",
            assigned_store_name="Store Two",
            followed_at=None,
            follow_result="pending",
            is_followed=False,
            is_follow_success=False,
            round_status="active_unfollowed",
            reassign_reason="timeout",
            is_self_store_verified=False,
            created_at=_dt(2, 9),
            updated_at=_dt(2, 9),
        )
    )
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/clues/orders/order-1")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["order_id"] == "order-1"
    assert payload["phone_masked"] == "138****5678"
    assert "telephone" not in payload
    assert payload["product_id"] == "sku-1"
    assert payload["product_name"] == "Service Product"
    assert payload["product_type"] == "Car Service"
    assert [row["assignment_round_id"] for row in payload["rounds"]] == [
        "order-1-1",
        "order-1-2",
    ]
    assert payload["rounds"][0]["follow_result"] == "success"
    assert payload["rounds"][1]["reassign_reason"] == "timeout"
    assert payload["follow_up_records"] == []


def test_admin_can_record_current_follow_up_and_detail_returns_history(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    _login(client)

    response = client.post(
        "/api/v1/clues/orders/order-2/follow-up",
        json={
            "assignment_round_id": "order-2-1",
            "follow_result": "unreachable",
            "note": "No answer after two calls.",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["order_id"] == "order-2"
    assert payload["assignment_round_id"] == "order-2-1"
    assert payload["round_no"] == 1
    assert payload["assigned_store_id"] == "store-1"
    assert payload["follow_result"] == "unreachable"
    assert payload["note"] == "No answer after two calls."
    assert payload["operator_username"] == "system-admin"
    assert "phone" not in payload
    assert "phone_plain" not in payload
    assert "telephone" not in payload

    order = db_session.get(ClueCenterOrder, "order-2")
    round_row = db_session.get(ClueAssignmentRound, "order-2-1")
    assert order is not None
    assert round_row is not None
    assert order.follow_result == "unreachable"
    assert order.is_followed is True
    assert order.is_follow_success is False
    assert order.current_round_status == "active_followed"
    assert order.lead_status == "active"
    assert round_row.follow_result == "unreachable"
    assert round_row.is_followed is True
    assert round_row.is_follow_success is False
    assert round_row.round_status == "active_followed"
    assert round_row.followed_at is not None

    records = db_session.execute(
        text(
            """
            SELECT order_id, assignment_round_id, round_no, assigned_store_id,
                   follow_result, note, operator_username
            FROM clue_follow_up_records
            WHERE order_id = :order_id
            """
        ),
        {"order_id": "order-2"},
    ).mappings().all()
    assert [dict(row) for row in records] == [
        {
            "order_id": "order-2",
            "assignment_round_id": "order-2-1",
            "round_no": 1,
            "assigned_store_id": "store-1",
            "follow_result": "unreachable",
            "note": "No answer after two calls.",
            "operator_username": "system-admin",
        }
    ]

    detail = client.get("/api/v1/clues/orders/order-2")
    assert detail.status_code == 200
    detail_payload = detail.json()["data"]
    assert detail_payload["follow_up_records"][0]["follow_result"] == "unreachable"
    assert detail_payload["follow_up_records"][0]["note"] == "No answer after two calls."
    serialized_detail = json.dumps(detail_payload, ensure_ascii=False)
    assert "phone_plain" not in serialized_detail
    assert "telephone" not in serialized_detail


def test_admin_can_delete_follow_up_record_and_summary_rolls_back(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    _login(client)
    created = client.post(
        "/api/v1/clues/orders/order-2/follow-up",
        json={
            "assignment_round_id": "order-2-1",
            "follow_result": "unreachable",
            "note": "No answer after two calls.",
        },
    )
    assert created.status_code == 200
    record_id = created.json()["data"]["follow_up_record_id"]

    deleted = client.delete(f"/api/v1/clues/follow-up-records/{record_id}")

    assert deleted.status_code == 200
    payload = deleted.json()["data"]
    assert payload["follow_up_record_id"] == record_id
    assert payload["follow_result"] == "unreachable"
    assert db_session.get(ClueFollowUpRecord, record_id) is None
    db_session.expire_all()
    order = db_session.get(ClueCenterOrder, "order-2")
    round_row = db_session.get(ClueAssignmentRound, "order-2-1")
    assert order is not None
    assert round_row is not None
    assert order.follow_result == "pending"
    assert order.is_followed is False
    assert order.is_follow_success is False
    assert order.current_round_status == "active_unfollowed"
    assert order.lead_status == "active"
    assert round_row.follow_result == "pending"
    assert round_row.is_followed is False
    assert round_row.is_follow_success is False
    assert round_row.round_status == "active_unfollowed"
    assert round_row.followed_at is None

    detail = client.get("/api/v1/clues/orders/order-2")
    assert detail.status_code == 200
    assert detail.json()["data"]["follow_up_records"] == []


def test_store_cannot_delete_follow_up_record(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    db_session.add_all(
        [
            User(
                user_id="user-store-1",
                username="store-current",
                external_account_id="store-current",
                display_name="Store Current",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret-current"),
            ),
            UserStoreScope(user_id="user-store-1", store_id="store-1"),
            ClueFollowUpRecord(
                follow_up_record_id="record-store-delete-forbidden",
                order_id="order-2",
                assignment_round_id="order-2-1",
                round_no=1,
                assigned_store_id="store-1",
                follow_result="unreachable",
                note="Existing note",
                operator_user_id="admin",
                operator_username="system-admin",
                created_at=_dt(1, 14),
            ),
        ]
    )
    db_session.commit()
    _login_user(client, "store-current", "secret-current")

    response = client.delete(
        "/api/v1/clues/follow-up-records/record-store-delete-forbidden"
    )

    assert response.status_code == 403
    assert db_session.get(ClueFollowUpRecord, "record-store-delete-forbidden") is not None


def test_lost_follow_up_moves_order_to_pending_reassign_and_blocks_phone_reveal(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    _login(client)

    response = client.post(
        "/api/v1/clues/orders/order-2/follow-up",
        json={
            "assignment_round_id": "order-2-1",
            "follow_result": "lost",
            "note": "Customer declined.",
        },
    )

    assert response.status_code == 200
    order = db_session.get(ClueCenterOrder, "order-2")
    round_row = db_session.get(ClueAssignmentRound, "order-2-1")
    assert order is not None
    assert round_row is not None
    assert order.follow_result == "lost"
    assert order.is_followed is True
    assert order.is_follow_success is False
    assert order.current_round_status == "failed_pending_reassign"
    assert order.lead_status == "pending_reassign"
    assert order.reassign_reason == "follow_lost"
    assert round_row.round_status == "failed_pending_reassign"
    assert round_row.reassign_reason == "follow_lost"

    phone = client.get("/api/v1/clues/orders/order-2/phone")
    assert phone.status_code == 404


def test_follow_up_conflicts_if_current_round_changes_after_precheck(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    store = data_module.DashboardDataStore(db_session)
    original_requested_round = store._requested_operation_round

    def stale_requested_round(order_id: str, assignment_round_id: str):
        row = original_requested_round(order_id, assignment_round_id)
        order = db_session.get(ClueCenterOrder, "order-2")
        round_row = db_session.get(ClueAssignmentRound, "order-2-1")
        assert order is not None
        assert round_row is not None
        order.lead_status = "pending_reassign"
        order.current_round_status = "failed_pending_reassign"
        order.reassign_reason = "follow_lost"
        round_row.round_status = "failed_pending_reassign"
        round_row.reassign_reason = "follow_lost"
        db_session.flush()
        return row

    monkeypatch.setattr(store, "_requested_operation_round", stale_requested_round)

    result_status, record = store.save_clue_follow_up(
        "order-2",
        {
            "assignment_round_id": "order-2-1",
            "follow_result": "success",
            "note": "stale follow-up",
        },
        {"role": "admin", "username": "system-admin", "user_id": "admin"},
    )

    assert result_status == "conflict"
    assert record is None
    assert db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM clue_follow_up_records
            WHERE order_id = :order_id
            """
        ),
        {"order_id": "order-2"},
    ).scalar_one() == 0
    db_session.expire_all()
    order = db_session.get(ClueCenterOrder, "order-2")
    round_row = db_session.get(ClueAssignmentRound, "order-2-1")
    assert order is not None
    assert round_row is not None
    assert order.lead_status == "pending_reassign"
    assert order.current_round_status == "failed_pending_reassign"
    assert order.follow_result == "pending"
    assert round_row.round_status == "failed_pending_reassign"
    assert round_row.follow_result == "pending"


def test_follow_up_conflicts_if_same_round_is_followed_after_precheck(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    store = data_module.DashboardDataStore(db_session)
    original_requested_round = store._requested_operation_round

    def stale_requested_round(order_id: str, assignment_round_id: str):
        row = original_requested_round(order_id, assignment_round_id)
        order = db_session.get(ClueCenterOrder, "order-2")
        round_row = db_session.get(ClueAssignmentRound, "order-2-1")
        assert order is not None
        assert round_row is not None
        order.current_round_status = "active_followed"
        order.follow_result = "unreachable"
        order.is_followed = True
        round_row.round_status = "active_followed"
        round_row.follow_result = "unreachable"
        round_row.is_followed = True
        db_session.flush()
        return row

    monkeypatch.setattr(store, "_requested_operation_round", stale_requested_round)

    result_status, record = store.save_clue_follow_up(
        "order-2",
        {
            "assignment_round_id": "order-2-1",
            "follow_result": "success",
            "note": "stale success",
        },
        {"role": "admin", "username": "system-admin", "user_id": "admin"},
    )

    assert result_status == "conflict"
    assert record is None
    assert db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM clue_follow_up_records
            WHERE order_id = :order_id
            """
        ),
        {"order_id": "order-2"},
    ).scalar_one() == 0
    db_session.expire_all()
    order = db_session.get(ClueCenterOrder, "order-2")
    round_row = db_session.get(ClueAssignmentRound, "order-2-1")
    assert order is not None
    assert round_row is not None
    assert order.current_round_status == "active_followed"
    assert order.follow_result == "unreachable"
    assert round_row.round_status == "active_followed"
    assert round_row.follow_result == "unreachable"


def test_store_can_record_current_scoped_follow_up(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    db_session.add_all(
        [
            User(
                user_id="user-store-1",
                username="store-current",
                external_account_id="store-current",
                display_name="Store Current",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret-current"),
            ),
            UserStoreScope(user_id="user-store-1", store_id="store-1"),
        ]
    )
    db_session.commit()
    _login_user(client, "store-current", "secret-current")

    response = client.post(
        "/api/v1/clues/orders/order-2/follow-up",
        json={
            "assignment_round_id": "order-2-1",
            "follow_result": "success",
            "note": "Reached customer.",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["operator_user_id"] == "user-store-1"
    assert payload["operator_username"] == "store-current"
    order = db_session.get(ClueCenterOrder, "order-2")
    round_row = db_session.get(ClueAssignmentRound, "order-2-1")
    assert order is not None
    assert round_row is not None
    assert order.follow_result == "success"
    assert order.is_follow_success is True
    assert order.lead_status == "active"
    assert round_row.round_status == "active_followed"


def test_viewer_cannot_record_follow_up(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    db_session.add(
        User(
            user_id="viewer-1",
            username="viewer",
            external_account_id="viewer",
            display_name="Viewer",
            role="viewer",
            status="active",
            is_initialized=True,
            password_hash=hash_password_pbkdf2("viewer-secret"),
        )
    )
    db_session.commit()
    _login_user(client, "viewer", "viewer-secret")

    response = client.post(
        "/api/v1/clues/orders/order-2/follow-up",
        json={
            "assignment_round_id": "order-2-1",
            "follow_result": "success",
            "note": "Viewer should not save.",
        },
    )

    assert response.status_code == 403


def test_clue_assignment_rounds_fall_back_to_raw_masked_phone(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    order.phone_masked = None
    order.phone_source = None
    db_session.add(
        RawDouyinClue(
            clue_row_key="raw-phone-fallback-1",
            clue_id="clue-1",
            create_time_detail=_dt(1),
            telephone="13812345678",
            product_id="sku-1",
            product_name="Service Product",
            order_id="order-1",
            order_status="履约中",
            follow_life_account_id="store-1",
            follow_life_account_name="Store One",
            raw_payload={"clue_id": "clue-1"},
            imported_at=_dt(1),
            updated_at=_dt(1),
        )
    )
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/clues/assignment-rounds?assigned_store_id=store-1")

    assert response.status_code == 200
    rows = response.json()["data"]["rows"]
    target = next(row for row in rows if row["order_id"] == "order-1")
    assert target["phone_masked"] == "138****5678"
    assert "telephone" not in target


def test_clue_order_detail_falls_back_to_raw_masked_phone(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    order.phone_masked = None
    order.phone_source = None
    db_session.add(
        RawDouyinClue(
            clue_row_key="raw-phone-fallback-detail-1",
            clue_id="clue-1",
            create_time_detail=_dt(1),
            raw_payload={"telephone": "13812345678"},
            product_id="sku-1",
            product_name="Service Product",
            order_id="order-1",
            order_status="履约中",
            follow_life_account_id="store-1",
            follow_life_account_name="Store One",
            imported_at=_dt(1),
            updated_at=_dt(1),
        )
    )
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/clues/orders/order-1")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["phone_masked"] == "138****5678"
    assert payload["rounds"][0]["phone_masked"] == "138****5678"
    assert "telephone" not in payload


def test_clue_order_detail_falls_back_to_encrypted_masked_phone(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_clue_center(db_session)
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    order.phone_masked = None
    order.phone_source = None
    db_session.add(
        RawDouyinClue(
            clue_row_key="raw-enc-phone-mask-detail-1",
            clue_id="clue-1",
            create_time_detail=_dt(1),
            telephone="",
            enc_telephone="Enc.phone-1",
            raw_payload={"clue_id": "clue-1"},
            product_id="sku-1",
            product_name="Service Product",
            order_id="order-1",
            order_status="履约中",
            follow_life_account_id="store-1",
            follow_life_account_name="Store One",
            imported_at=_dt(1),
            updated_at=_dt(1),
        )
    )
    db_session.commit()

    class FakeDouyinClient:
        def decrypt_cipher_texts(self, cipher_texts: list[str]) -> dict[str, str]:
            assert cipher_texts == ["Enc.phone-1"]
            return {"Enc.phone-1": "13812345678"}

    monkeypatch.setattr(
        data_module,
        "build_douyin_client_from_env",
        lambda: FakeDouyinClient(),
        raising=False,
    )
    _login(client)

    response = client.get("/api/v1/clues/orders/order-1")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["phone_masked"] == "138****5678"
    assert payload["rounds"][0]["phone_masked"] == "138****5678"
    assert "telephone" not in payload


def test_clue_phone_reveal_returns_full_phone_on_demand(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    order.lead_status = "active"
    db_session.add(
        RawDouyinClue(
            clue_row_key="raw-phone-1",
            clue_id="clue-1",
            create_time_detail=_dt(1),
            telephone="13812345678",
            product_id="sku-1",
            product_name="Service Product",
            order_id="order-1",
            order_status="履约中",
            follow_life_account_id="store-1",
            follow_life_account_name="Store One",
            raw_payload={"clue_id": "clue-1"},
            imported_at=_dt(1),
            updated_at=_dt(1),
        )
    )
    db_session.commit()
    _login(client)

    detail = client.get("/api/v1/clues/orders/order-1")
    assert detail.status_code == 200
    assert "telephone" not in detail.json()["data"]

    response = client.get("/api/v1/clues/orders/order-1/phone")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload == {
        "order_id": "order-1",
        "phone": "13812345678",
        "phone_masked": "138****5678",
    }


def test_clue_phone_reveal_uses_cached_plain_phone_without_decrypting(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_clue_center(db_session)
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    order.lead_status = "active"
    order.phone_plain = "13812345678"
    order.phone_masked = "138****5678"
    db_session.commit()

    class FakeDouyinClient:
        def decrypt_cipher_texts(self, cipher_texts: list[str]) -> dict[str, str]:
            raise AssertionError(f"should not decrypt when cached phone exists: {cipher_texts!r}")

    monkeypatch.setattr(
        data_module,
        "build_douyin_client_from_env",
        lambda: FakeDouyinClient(),
        raising=False,
    )
    _login(client)

    response = client.get("/api/v1/clues/orders/order-1/phone")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload == {
        "order_id": "order-1",
        "phone": "13812345678",
        "phone_masked": "138****5678",
    }


def test_clue_phone_reveal_returns_404_for_converted_order(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    _login(client)

    response = client.get("/api/v1/clues/orders/order-1/phone")

    assert response.status_code == 404


def test_clue_phone_reveal_returns_404_when_no_phone(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    order.phone_plain = None
    order.phone_masked = None
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/clues/orders/order-1/phone")

    assert response.status_code == 404


def test_unknown_clue_order_detail_returns_404(client: TestClient) -> None:
    _login(client)
    response = client.get("/api/v1/clues/orders/missing-order")

    assert response.status_code == 404


def test_store_account_sees_only_own_round_but_can_open_full_order_detail(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    order.lead_status = "active"
    order.current_assignment_round_id = "order-1-2"
    order.current_round_no = 2
    order.current_round_status = "active_unfollowed"
    order.assigned_store_id = "store-2"
    order.assigned_store_name = "Store Two"
    db_session.add(
        ClueAssignmentRound(
            assignment_round_id="order-1-2",
            order_id="order-1",
            round_no=2,
            assigned_at=_dt(2, 9),
            assigned_at_source="manual_reassign",
            assigned_store_id="store-2",
            assigned_store_name="Store Two",
            follow_result="pending",
            is_followed=False,
            is_follow_success=False,
            round_status="active_unfollowed",
            reassign_reason="timeout",
            is_self_store_verified=False,
            created_at=_dt(2, 9),
            updated_at=_dt(2, 9),
        )
    )
    db_session.add_all(
        [
            User(
                user_id="user-a",
                username="store-a",
                external_account_id="store-1",
                display_name="Store A",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret-a"),
            ),
            UserStoreScope(user_id="user-a", store_id="store-1"),
        ]
    )
    db_session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "store-a", "password": "secret-a"},
    )
    assert login.status_code == 200

    rounds = client.get("/api/v1/clues/assignment-rounds")
    assert rounds.status_code == 200
    payload = rounds.json()["data"]
    assert {row["assignment_round_id"] for row in payload["rows"]} == {
        "order-1-1",
        "order-2-1",
    }
    order_one = next(row for row in payload["rows"] if row["order_id"] == "order-1")
    assert order_one["is_current_round"] is False
    assert order_one["round_effective_status"] == "inactive"
    assert order_one["current_assigned_store_id"] == "store-2"

    detail = client.get("/api/v1/clues/orders/order-1")
    assert detail.status_code == 200
    assert [row["assignment_round_id"] for row in detail.json()["data"]["rounds"]] == [
        "order-1-1",
        "order-1-2",
    ]
    assert detail.json()["data"]["phone_masked"] == "138****5678"

    phone = client.get("/api/v1/clues/orders/order-1/phone")
    assert phone.status_code == 404

    follow_up = client.post(
        "/api/v1/clues/orders/order-1/follow-up",
        json={
            "assignment_round_id": "order-1-2",
            "follow_result": "success",
            "note": "Historical store should not save current round.",
        },
    )
    assert follow_up.status_code == 403

    forbidden = client.get("/api/v1/clues/assignment-rounds?assigned_store_id=store-2")
    assert forbidden.status_code == 200
    assert forbidden.json()["data"]["rows"] == []


def test_admin_clue_rule_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/admin/clue-reassign-rule").status_code == 401
    assert client.put("/api/v1/admin/clue-reassign-rule", json={"reassign_sla_hours": None}).status_code == 401


def test_admin_can_save_null_and_numeric_clue_rule(client: TestClient) -> None:
    _login(client)

    response = client.get("/api/v1/admin/clue-reassign-rule")
    assert response.status_code == 200
    assert response.json()["data"]["reassign_sla_hours"] is None

    response = client.put("/api/v1/admin/clue-reassign-rule", json={"reassign_sla_hours": None})
    assert response.status_code == 200
    assert response.json()["data"]["reassign_sla_hours"] is None

    response = client.put("/api/v1/admin/clue-reassign-rule", json={"reassign_sla_hours": 24})
    assert response.status_code == 200
    assert response.json()["data"]["reassign_sla_hours"] == 24


def test_admin_can_rebuild_clues(client: TestClient, db_session: Session) -> None:
    db_session.add(
        RawDouyinClue(
            clue_row_key="raw-1",
            clue_id="clue-1",
            create_time_detail=_dt(1),
            telephone="13812345678",
            product_id="sku-1",
            product_name="Service Product",
            order_id="order-1",
            order_status="履约中",
            follow_life_account_id="store-1",
            follow_life_account_name="Store One",
            raw_payload={"clue_id": "clue-1"},
            imported_at=_dt(1),
            updated_at=_dt(1),
        )
    )
    db_session.commit()

    _login(client)
    response = client.post("/api/v1/admin/clues/rebuild")

    assert response.status_code == 200
    assert response.json()["data"]["rebuilt_order_count"] == 1
    assert db_session.get(ClueCenterOrder, "order-1") is not None


def test_admin_rebuild_decrypts_encrypted_clue_phone(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(
        RawDouyinClue(
            clue_row_key="raw-enc-1",
            clue_id="clue-enc-1",
            create_time_detail=_dt(1),
            telephone="",
            enc_telephone="Enc.phone-1",
            product_id="sku-1",
            product_name="Service Product",
            order_id="order-1",
            order_status="履约中",
            follow_life_account_id="store-1",
            follow_life_account_name="Store One",
            raw_payload={"clue_id": "clue-enc-1"},
            imported_at=_dt(1),
            updated_at=_dt(1),
        )
    )
    db_session.commit()
    calls: list[list[str]] = []

    class FakeDouyinClient:
        def decrypt_cipher_texts(self, cipher_texts: list[str]) -> dict[str, str]:
            calls.append(cipher_texts)
            return {"Enc.phone-1": "13812345678"}

    monkeypatch.setattr(
        admin_module,
        "build_douyin_client_from_env",
        lambda: FakeDouyinClient(),
    )

    _login(client)
    response = client.post("/api/v1/admin/clues/rebuild")

    assert response.status_code == 200
    assert calls == [["Enc.phone-1"]]
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    assert order.phone_plain == "13812345678"
    assert order.phone_masked == "138****5678"
