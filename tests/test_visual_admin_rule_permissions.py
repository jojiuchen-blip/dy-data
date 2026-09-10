"""Ordinary-admin rule publishing against a real, isolated FastAPI server."""

import threading

import pytest
import uvicorn
from playwright.sync_api import Browser, expect
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from test_api_fee_admin import _login_rule_operator, _seed_sku
from test_visual_smoke import (
    HOST, browser, find_free_port, wait_for_url,
    vite_live_admin_api_base_url,
)
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency


@pytest.fixture()
def rule_api(monkeypatch: pytest.MonkeyPatch, db_session: Session):
    monkeypatch.setenv("DY_API_CORS_ORIGINS", "*")
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()

    def session_dependency():
        yield db_session

    app.dependency_overrides[get_session_dependency] = session_dependency
    _seed_sku(db_session, "SKU-PERMISSION-BROWSER", "权限浏览器测试商品")
    _login_rule_operator(TestClient(app), db_session)
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
        assert identity["is_highest_admin"] is False
        page = context.new_page()
        page.goto(f"{rule_web}/admin/rules", wait_until="domcontentloaded")
        expect(page.get_by_role("button", name="重建结算投影", exact=True)).to_be_disabled()
        expect(page.get_by_text("仅最高管理员可手动重建", exact=False)).to_be_visible()

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
        expect(page.get_by_role("button", name="重建结算投影", exact=True)).to_be_disabled()
        rows = context.request.get(f"{rule_api}/api/v1/admin/sku-fee-rules?skuId=SKU-PERMISSION-BROWSER").json()["data"]["list"]
        assert len(rows) == 1
        assert rows[0]["createdBy"] == "rule-operator"
        prepare_publish("isolated conflicting date")
        expect(page.get_by_text("该生效日期已存在版本", exact=False)).to_be_visible(timeout=15000)
    finally:
        context.close()
