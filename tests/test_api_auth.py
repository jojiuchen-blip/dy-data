from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    DimStore,
    DimStorePoiMapping,
    RawAwemeBinding,
    User,
    UserStoreScope,
)
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DY_SESSION_COOKIE_SAMESITE", "lax")
    monkeypatch.delenv("DY_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("DY_SUPER_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("DY_ADMIN_PASSWORD_HASH", raising=False)
    return TestClient(create_app())


def add_activation_seed(
    db_session,
    *,
    store_id: str,
    poi_id: str,
    binding_status: str = "认证成功",
    account_type: str | None = "子机构经营号",
    is_active: bool = True,
) -> None:
    raw_payload = {} if account_type is None else {"账号类型": account_type}
    db_session.add_all(
        [
            DimStore(
                store_id=store_id,
                store_name=f"Store {store_id}",
                certified_subject_name=f"Subject {store_id}",
                is_active=is_active,
            ),
            DimStorePoiMapping(
                store_id=store_id,
                poi_id=poi_id,
                poi_name=f"POI {poi_id}",
                mapping_source="test",
            ),
            RawAwemeBinding(
                binding_key=f"{store_id}:{poi_id}:{binding_status}:{account_type}",
                account_id=store_id,
                account_name=f"Account {store_id}",
                poi_id=poi_id,
                binding_status=binding_status,
                raw_payload=raw_payload,
            ),
        ]
    )


def create_database_client(db_session) -> TestClient:
    app = create_app()

    from dy_api.routes._data import get_session_dependency  # noqa: WPS433

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def test_login_sets_http_only_cookie_and_logout_clears_session(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["username"] == "system-admin"
    assert response.json()["data"]["role"] == "admin"
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "secure" not in set_cookie

    assert client.get("/api/v1/auth/me").status_code == 200

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_activation_status_requires_same_verified_sub_account_record(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")

    add_activation_seed(db_session, store_id="store-1", poi_id="poi-1")
    add_activation_seed(db_session, store_id="store-2", poi_id="poi-2")
    add_activation_seed(
        db_session,
        store_id="store-3",
        poi_id="poi-3",
        binding_status="认证中",
    )
    add_activation_seed(
        db_session,
        store_id="store-4",
        poi_id="poi-4",
        account_type="总部官方号",
    )
    db_session.add(
        User(
            user_id="existing",
            username="existing2",
            external_account_id="store-2",
            display_name="Store Two Account",
            role="store",
            status="active",
            is_initialized=False,
            password_hash=hash_password_pbkdf2("secret"),
        )
    )
    db_session.commit()
    client = create_database_client(db_session)

    ready = client.post(
        "/api/v1/auth/activation-status",
        json={"external_account_id": "store-1", "poi_id": "poi-1"},
    )
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"

    activated = client.post(
        "/api/v1/auth/activation-status",
        json={"external_account_id": "store-2", "poi_id": "poi-2"},
    )
    assert activated.status_code == 200
    assert activated.json()["data"]["status"] == "activated"

    for external_account_id, poi_id in (
        ("store-1", "poi-2"),
        ("store-3", "poi-3"),
        ("store-4", "poi-4"),
        ("missing", "missing"),
    ):
        invalid = client.post(
            "/api/v1/auth/activation-status",
            json={
                "external_account_id": external_account_id,
                "poi_id": poi_id,
            },
        )
        assert invalid.status_code == 200
        assert invalid.json()["data"]["status"] == "invalid"


def test_store_account_can_initialize_login_and_change_password(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")

    add_activation_seed(db_session, store_id="store-1", poi_id="poi-1")
    db_session.commit()
    client = create_database_client(db_session)

    init = client.post(
        "/api/v1/auth/initialize",
        json={
            "external_account_id": "store-1",
            "poi_id": "poi-1",
            "username": "storeone1",
            "password": "first-pass",
            "password_confirm": "first-pass",
        },
    )
    assert init.status_code == 200
    assert init.json()["data"]["store_ids"] == ["store-1"]
    user = db_session.query(User).filter_by(username="storeone1").one()
    assert user.display_name == "Store store-1"

    client.post("/api/v1/auth/logout")
    by_username = client.post(
        "/api/v1/auth/login",
        json={"username": "storeone1", "password": "first-pass"},
    )
    assert by_username.status_code == 200
    assert by_username.json()["data"]["role"] == "store"

    client.post("/api/v1/auth/logout")
    by_external_id = client.post(
        "/api/v1/auth/login",
        json={"username": "store-1", "password": "first-pass"},
    )
    assert by_external_id.status_code == 200

    client.post("/api/v1/auth/logout")
    by_poi_id = client.post(
        "/api/v1/auth/login",
        json={"username": "poi-1", "password": "first-pass"},
    )
    assert by_poi_id.status_code == 200

    change_password = client.post(
        "/api/v1/auth/change-password",
        json={
            "password": "second-pass",
            "password_confirm": "second-pass",
        },
    )
    assert change_password.status_code == 200
    client.post("/api/v1/auth/logout")
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "storeone1", "password": "second-pass"},
        ).status_code
        == 200
    )


def test_store_account_initialize_rejects_cross_record_and_invalid_username(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")

    add_activation_seed(db_session, store_id="store-1", poi_id="poi-1")
    add_activation_seed(db_session, store_id="store-2", poi_id="poi-2")
    db_session.commit()
    client = create_database_client(db_session)

    cross_record = client.post(
        "/api/v1/auth/initialize",
        json={
            "external_account_id": "store-1",
            "poi_id": "poi-2",
            "username": "storeone1",
            "password": "first-pass",
            "password_confirm": "first-pass",
        },
    )
    assert cross_record.status_code == 401

    invalid_username = client.post(
        "/api/v1/auth/initialize",
        json={
            "external_account_id": "store-1",
            "poi_id": "poi-1",
            "username": "store-one",
            "password": "first-pass",
            "password_confirm": "first-pass",
        },
    )
    assert invalid_username.status_code == 422

    missing_poi = client.post(
        "/api/v1/auth/initialize",
        json={
            "external_account_id": "store-1",
            "username": "storeone1",
            "password": "first-pass",
            "password_confirm": "first-pass",
        },
    )
    assert missing_poi.status_code == 422


def test_existing_store_account_can_login_with_poi_id(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")

    db_session.add_all(
        [
            DimStore(
                store_id="store-1",
                store_name="Store One",
                certified_subject_name="Subject One",
                is_active=True,
            ),
            DimStorePoiMapping(
                store_id="store-1",
                poi_id="poi-1",
                poi_name="Store One POI",
                mapping_source="test",
            ),
            User(
                user_id="existing",
                username="store-one",
                external_account_id="store-1",
                display_name="Store One Account",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret"),
            ),
            UserStoreScope(user_id="existing", store_id="store-1"),
        ]
    )
    db_session.commit()

    app = create_app()

    from dy_api.routes._data import get_session_dependency  # noqa: WPS433

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "poi-1", "password": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["store_ids"] == ["store-1"]


def test_store_account_can_reset_password_with_dual_id_verification(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")

    add_activation_seed(db_session, store_id="store-1", poi_id="poi-1")
    add_activation_seed(db_session, store_id="store-2", poi_id="poi-2")
    add_activation_seed(db_session, store_id="store-3", poi_id="poi-3")
    db_session.add_all(
        [
            User(
                user_id="existing",
                username="store-one",
                external_account_id="store-1",
                display_name="Store One Account",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("old-pass"),
            ),
            User(
                user_id="disabled",
                username="store-two",
                external_account_id="store-2",
                display_name="Store Two Account",
                role="store",
                status="disabled",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("old-pass"),
            ),
            UserStoreScope(user_id="existing", store_id="store-1"),
            UserStoreScope(user_id="disabled", store_id="store-2"),
        ]
    )
    db_session.commit()
    client = create_database_client(db_session)

    cross_record = client.post(
        "/api/v1/auth/reset-password",
        json={
            "external_account_id": "store-1",
            "poi_id": "poi-2",
            "password": "new-pass",
            "password_confirm": "new-pass",
        },
    )
    assert cross_record.status_code == 401

    unactivated = client.post(
        "/api/v1/auth/reset-password",
        json={
            "external_account_id": "store-3",
            "poi_id": "poi-3",
            "password": "new-pass",
            "password_confirm": "new-pass",
        },
    )
    assert unactivated.status_code == 409

    disabled = client.post(
        "/api/v1/auth/reset-password",
        json={
            "external_account_id": "store-2",
            "poi_id": "poi-2",
            "password": "new-pass",
            "password_confirm": "new-pass",
        },
    )
    assert disabled.status_code == 401

    reset = client.post(
        "/api/v1/auth/reset-password",
        json={
            "external_account_id": "store-1",
            "poi_id": "poi-1",
            "password": "new-pass",
            "password_confirm": "new-pass",
        },
    )
    assert reset.status_code == 200
    assert reset.json()["data"]["username"] == "store-one"
    assert reset.json()["data"]["store_ids"] == ["store-1"]
    db_session.refresh(db_session.query(User).filter_by(user_id="existing").one())
    preserved_user = db_session.query(User).filter_by(user_id="existing").one()
    assert preserved_user.username == "store-one"
    assert preserved_user.display_name == "Store One Account"

    client.post("/api/v1/auth/logout")
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "store-one", "password": "old-pass"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "store-one", "password": "new-pass"},
        ).status_code
        == 200
    )


def test_store_account_initialize_rejects_duplicate_username(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    add_activation_seed(db_session, store_id="store-2", poi_id="poi-2")
    db_session.add_all(
        [
            DimStore(
                store_id="store-1",
                store_name="Store One",
                certified_subject_name="Subject One",
                is_active=True,
            ),
            User(
                user_id="existing",
                username="taken",
                external_account_id="store-1",
                display_name="Existing",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret"),
            ),
            UserStoreScope(user_id="existing", store_id="store-1"),
        ]
    )
    db_session.commit()

    client = create_database_client(db_session)

    response = client.post(
        "/api/v1/auth/initialize",
        json={
            "external_account_id": "store-2",
            "poi_id": "poi-2",
            "username": "taken",
            "password": "pass",
            "password_confirm": "pass",
        },
    )
    assert response.status_code == 409


def test_login_rejects_wrong_password(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "wrong"},
    )

    assert response.status_code == 401


def test_default_admin_password_is_not_enabled_without_explicit_config(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.delenv("DY_SUPER_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("DY_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("DY_TEST_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("DY_SUPER_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("DY_ADMIN_PASSWORD_HASH", raising=False)

    client = TestClient(create_app())

    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    )

    assert response.status_code == 401


def test_configured_admin_username_requires_configured_password(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.delenv("DY_TEST_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("DY_SUPER_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("DY_ADMIN_PASSWORD_HASH", raising=False)

    client = TestClient(create_app())

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )

    assert response.status_code == 503


def test_password_hash_env_is_supported_without_test_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DY_API_TEST_MODE", "false")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DY_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "ops-root")
    monkeypatch.setenv("DY_SUPER_ADMIN_PASSWORD_HASH", hash_password_pbkdf2("s3cret"))

    client = TestClient(create_app())

    wrong = client.post(
        "/api/v1/auth/login", json={"username": "ops-root", "password": "admin"}
    )
    assert wrong.status_code == 401

    ok = client.post(
        "/api/v1/auth/login", json={"username": "ops-root", "password": "s3cret"}
    )
    assert ok.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/auth/me"),
        ("post", "/api/v1/auth/logout"),
        ("get", "/api/v1/jobs/recent"),
    ],
)
def test_protected_endpoints_return_401_without_session(
    client: TestClient, method: str, path: str
):
    response = getattr(client, method)(path)

    assert response.status_code == 401
