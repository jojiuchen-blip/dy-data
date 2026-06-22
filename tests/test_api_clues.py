from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes import _data as data_module  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    ClueAssignmentRound,
    ClueCenterOrder,
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
    assert metrics["self_store_verify_rate"] == 0.5

    details = client.get("/api/v1/clues/assignment-rounds?assigned_store_id=store-1")
    assert details.status_code == 200
    payload = details.json()["data"]
    assert payload["pagination"]["total"] == 2
    row = payload["rows"][0]
    assert row["phone_masked"] in {"138****5678", "139****5678"}
    assert "telephone" not in row
    assert row["remaining_reassign_seconds"] is None


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
        def decrypt_mask_cipher_texts(self, cipher_texts: list[str]) -> dict[str, str]:
            assert cipher_texts == ["Enc.phone-1"]
            return {"Enc.phone-1": "138****5678"}

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


def test_clue_phone_reveal_decrypts_encrypted_phone_on_demand(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_clue_center(db_session)
    db_session.add(
        RawDouyinClue(
            clue_row_key="raw-enc-phone-1",
            clue_id="clue-1",
            create_time_detail=_dt(1),
            telephone="",
            enc_telephone="Enc.phone-1",
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

    response = client.get("/api/v1/clues/orders/order-1/phone")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload == {
        "order_id": "order-1",
        "phone": "13812345678",
        "phone_masked": "138****5678",
    }


def test_clue_phone_reveal_returns_404_when_no_phone(
    client: TestClient, db_session: Session
) -> None:
    _seed_clue_center(db_session)
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
