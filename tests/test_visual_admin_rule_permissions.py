"""Ordinary-admin rule publishing against a real, isolated FastAPI server."""

import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import uvicorn
from playwright.sync_api import Browser, expect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from test_api_fee_admin import _login_rule_operator, _seed_sku
from test_visual_smoke import (
    HOST, browser, find_free_port, wait_for_url,
    vite_live_admin_api_base_url,
)
from dy_api.main import create_app
from dy_api.models import Base, DimStore, User, UserStoreScope
from dy_api.auth import hash_password_pbkdf2
from dy_api.access_control import ensure_access_control_seed
from dy_api.routes._data import get_session_dependency


@pytest.fixture()
def rule_api(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("DY_API_CORS_ORIGINS", "*")
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DY_SESSION_COOKIE_NAME", "dy_rule_browser_session")
    monkeypatch.setenv("DY_SESSION_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("DY_SESSION_TTL_SECONDS", "3600")
    monkeypatch.setenv("DY_SESSION_SECRET", "isolated-rule-browser-test-secret")
    # Each concurrent HTTP request needs its own session and connection.
    database_path = tmp_path / "rule-browser.sqlite3"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    app = create_app()

    def session_dependency():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session_dependency] = session_dependency
    # Only uvicorn owns the application lifespan; the MCP manager is single-use.
    client = TestClient(app)
    with factory() as session:
        # A migrated installation has this catalog before parallel page reads.
        ensure_access_control_seed(session)
        session.commit()
        _seed_sku(session, "SKU-PERMISSION-BROWSER", "权限浏览器测试商品")
        _login_rule_operator(client, session)
        session.add_all([
            DimStore(store_id="store-1", store_name="Scoped Store", is_active=True),
            User(user_id="scoped-rule-operator", username="scoped-rule-operator", display_name="Scoped Operator",
                 role="admin", status="active", is_initialized=True, store_scope_mode="specified",
                 password_hash=hash_password_pbkdf2("isolated-password")),
            UserStoreScope(user_id="scoped-rule-operator", store_id="store-1"),
        ])
        session.commit()
    client.close()
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://{HOST}:{port}"
    try:
        wait_for_url(f"{url}/docs")
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()


@pytest.fixture()
def rule_web(rule_api: str):
    yield from vite_live_admin_api_base_url.__wrapped__(rule_api)


def test_admin_publishes_refreshes_and_sees_conflict_in_browser(
    browser: Browser, rule_api: str, rule_web: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        login = context.request.post(f"{rule_api}/api/v1/auth/login", data={
            "username": "rule-operator", "password": "isolated-password",
        })
        assert login.status == 200
        identity = context.request.get(f"{rule_api}/api/v1/auth/me").json()["data"]
        assert identity["role"] == "admin"
        assert identity["can_manage_accounts"] is True
        assert identity["can_manage_global_settings"] is True
        page = context.new_page()
        initialization_errors = []
        page.on("response", lambda response: initialization_errors.append(
            (urlsplit(response.url).path, response.status)
        ) if response.url.startswith(rule_api) and response.status >= 400 else None)
        page.goto(f"{rule_web}/admin/rules", wait_until="domcontentloaded")
        try:
            expect(page.get_by_role("button", name="重新计算结算结果", exact=True)).to_be_disabled()
        except AssertionError as error:
            raise AssertionError(f"Rule initialization HTTP errors: {initialization_errors}") from error
        assert initialization_errors == []

        def prepare_publish(reason: str) -> None:
            section = page.get_by_role("heading", name="1. SKU 查询与批量选择", exact=True).locator("xpath=ancestor::section")
            section.get_by_label("SKU ID", exact=True).fill("SKU-PERMISSION-BROWSER")
            section.get_by_role("button", name="查询并选择", exact=True).click()
            fee = page.get_by_role("heading", name="2. SKU-ID分佣比例确认", exact=True).locator("xpath=ancestor::section")
            fee.get_by_label("变更原因", exact=True).fill(reason)
            fee.get_by_role("button", name="应用比例并检查预选", exact=True).click()
            page.get_by_role("button", name="确认发布", exact=True).first.click()
            page.get_by_role("dialog", name="分佣规则发布确认").get_by_role("button", name="确认发布", exact=True).click()

        prepare_publish("isolated browser publish")
        expect(page.get_by_text("已发布 1 个 SKU", exact=False)).to_be_visible(timeout=15000)
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_role("button", name="重新计算结算结果", exact=True)).to_be_enabled()
        rows = context.request.get(f"{rule_api}/api/v1/admin/sku-fee-rules?skuId=SKU-PERMISSION-BROWSER").json()["data"]["list"]
        assert len(rows) == 1
        assert rows[0]["createdBy"] == "rule-operator"
        proof = Path("output/dydata105-admin")
        proof.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(proof / "global-admin-published.png"), full_page=True)
        prepare_publish("isolated conflicting date")
        expect(page.get_by_text("错误码：SKU_FEE_RULE_DATE_CONFLICT", exact=False)).to_be_visible(timeout=15000)
    finally:
        context.close()


def test_scoped_admin_reads_rules_but_global_write_buttons_are_disabled(browser: Browser, rule_api: str, rule_web: str) -> None:
    """Real authentication and read API; no mocked success responses."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        response = context.request.post(f"{rule_api}/api/v1/auth/login", data={
            "username": "scoped-rule-operator", "password": "isolated-password",
        })
        assert response.status == 200
        identity = response.json()["data"]
        assert identity["role"] == "admin"
        assert identity["can_manage_accounts"] is True
        assert identity["can_manage_global_settings"] is False
        page = context.new_page()
        page.goto(f"{rule_web}/admin/rules", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="商品分账规则管理", exact=True)).to_be_visible()
        expect(page.get_by_text("当前可查看规则。", exact=False)).to_be_visible()
        expect(page.get_by_role("button", name="批量导入设置", exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="确认发布", exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="重新计算结算结果", exact=True)).to_be_disabled()
        proof = Path("output/dydata105-admin")
        proof.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(proof / "scoped-admin-read-only.png"), full_page=True)
        page.get_by_role("tab", name="例外账号（0）", exact=True).click()
        expect(page.get_by_role("button", name="保存账号规则并重建", exact=True)).to_be_disabled()
        assert context.request.get(f"{rule_api}/api/v1/admin/sku-fee-rules").json()["data"]["list"] == []
    finally:
        context.close()


def test_committed_publish_survives_refresh_failure(browser: Browser, rule_api: str, rule_web: str) -> None:
    """Real publish and DB read-back; only the subsequent read failure is injected."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        assert context.request.post(f"{rule_api}/api/v1/auth/login", data={
            "username": "rule-operator", "password": "isolated-password",
        }).status == 200
        page = context.new_page()
        published_requests = []
        page.on("request", lambda request: published_requests.append(request.url)
                if request.method == "POST" and request.url.endswith("/admin/sku-fee-rules") else None)
        page.goto(f"{rule_web}/admin/rules", wait_until="domcontentloaded")
        section = page.get_by_role("heading", name="1. SKU 查询与批量选择", exact=True).locator("xpath=ancestor::section")
        section.get_by_label("SKU ID", exact=True).fill("SKU-PERMISSION-BROWSER")
        section.get_by_role("button", name="查询并选择", exact=True).click()
        fee = page.get_by_role("heading", name="2. SKU-ID分佣比例确认", exact=True).locator("xpath=ancestor::section")
        fee.get_by_label("变更原因", exact=True).fill("isolated refresh failure")
        fee.get_by_role("button", name="应用比例并检查预选", exact=True).click()
        page.route("**/admin/sku-fee-rules?**", lambda route: route.fulfill(status=503, json={
            "detail": {"code": "TEST_READ_UNAVAILABLE", "message": "injected internal read failure", "requestId": "test-refresh-only"},
        }))
        page.get_by_role("button", name="确认发布", exact=True).first.click()
        page.get_by_role("dialog", name="分佣规则发布确认").get_by_role("button", name="确认发布", exact=True).click()
        expect(page.get_by_text("已发布 1 个 SKU", exact=False)).to_be_visible(timeout=15000)
        expect(page.get_by_text("页面刷新失败", exact=False)).to_be_visible()
        expect(page.get_by_role("dialog", name="分佣规则发布确认")).to_have_count(0)
        assert len(published_requests) == 1
        rows = context.request.get(f"{rule_api}/api/v1/admin/sku-fee-rules?skuId=SKU-PERMISSION-BROWSER").json()["data"]["list"]
        assert len(rows) == 1
        assert rows[0]["changeReason"] == "isolated refresh failure"
    finally:
        context.close()


@pytest.mark.parametrize("alias,canonical", [
    ("/invoice", "/settlement/invoice"),
    ("/finance", "/finance/promotion"),
])
def test_legacy_alias_preserves_filters_and_fragment(
    browser: Browser, rule_api: str, rule_web: str, alias: str, canonical: str,
) -> None:
    """Exercise the actual App redirect with a real signed-in session."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        assert context.request.post(f"{rule_api}/api/v1/auth/login", data={
            "username": "rule-operator", "password": "isolated-password",
        }).status == 200
        page = context.new_page()
        suffix = "?store_id=store-1&month=2026-08&context=keep%2Fvalue#receipt"
        page.goto(f"{rule_web}{alias}{suffix}", wait_until="domcontentloaded")
        expect(page).to_have_url(f"{rule_web}{canonical}{suffix}")
    finally:
        context.close()


@pytest.mark.parametrize("username,global_scope", [
    ("rule-operator", True), ("scoped-rule-operator", False),
])
def test_admin_creates_updates_store_account_and_sees_fixed_role_matrix(
    browser: Browser, rule_api: str, rule_web: str, username: str, global_scope: bool,
) -> None:
    """Use the real account writes, reloads and scope-filtered directory."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        assert context.request.post(f"{rule_api}/api/v1/auth/login", data={
            "username": username, "password": "isolated-password",
        }).status == 200
        page = context.new_page()
        page.goto(f"{rule_web}/admin/accounts", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="新建账号", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="批量开通账号", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="删除账号", exact=True)).to_have_count(0)
        page.get_by_label("角色", exact=True).click()
        expect(page.get_by_role("option", name="管理员", exact=True)).to_have_count(1 if global_scope else 0)
        expect(page.get_by_role("option", name="最高管理员", exact=True)).to_have_count(0)
        page.keyboard.press("Escape")
        page.get_by_role("button", name="门店权限 · 已选 0 家", exact=True).click()
        dialog = page.get_by_role("dialog", name="选择门店权限")
        dialog.locator(".account-scope-row input").check()
        dialog.get_by_role("button", name="完成选择（1 家）", exact=True).click()
        page.get_by_label("显示名称", exact=True).fill("隔离账号新增")
        page.get_by_label("所属账户编号", exact=True).fill(f"new-{username}")
        page.get_by_label("密码", exact=True).fill("AccountTest123!")
        page.get_by_label("确认密码", exact=True).fill("AccountTest123!")
        page.locator("form.account-form button[type=submit]").click()
        with page.expect_response(lambda response: response.url.endswith("/admin/accounts") and response.request.method == "POST") as created:
            page.get_by_role("button", name="确认创建", exact=True).click()
        assert created.value.status == 200, created.value.text()
        account = created.value.json()["data"]
        assert account["role"] == "store"
        assert [store["store_id"] for store in account["stores"]] == ["store-1"]
        expect(page.get_by_text("账号已创建。", exact=True)).to_be_visible()
        page.get_by_label("显示名称", exact=True).fill("隔离账号已变更")
        with page.expect_response(lambda response: response.url.endswith(f"/admin/accounts/{account['user_id']}") and response.request.method == "PUT") as updated:
            page.get_by_role("button", name="保存账号", exact=True).click()
        assert updated.value.status == 200, updated.value.text()
        rows = context.request.get(f"{rule_api}/api/v1/admin/accounts").json()["data"]["rows"]
        assert next(row for row in rows if row["user_id"] == account["user_id"])["display_name"] == "隔离账号已变更"
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_role("cell").get_by_text("隔离账号已变更", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="删除账号", exact=True)).to_have_count(0)
        page.get_by_role("tab", name="角色权限", exact=True).click()
        pages = context.request.get(f"{rule_api}/api/v1/admin/access-control").json()["data"]["pages"]
        for registered_page in pages:
            permission = page.get_by_role("checkbox", name=f"{registered_page['page_name']} 管理员", exact=True)
            expect(permission).to_be_checked()
            expect(permission).to_be_disabled()
        button = page.get_by_role("button", name="保存门店账号默认权限", exact=True)
        if global_scope:
            expect(button).to_be_enabled()
        else:
            expect(button).to_be_disabled()
        proof = Path("output/dydata105-admin")
        proof.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(proof / f"account-{username}-updated.png"), full_page=True)
    except Exception:
        proof = Path("output/dydata105-admin")
        proof.mkdir(parents=True, exist_ok=True)
        for index, current_page in enumerate(context.pages):
            current_page.screenshot(path=str(proof / f"account-{username}-failure-{index}.png"), full_page=True)
        raise
    finally:
        context.close()
