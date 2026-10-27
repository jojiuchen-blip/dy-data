"""Oct23 invoice flow through real isolated FastAPI, SQLite, Vite and Chromium.

Browser plugin not available; use the repository Playwright harness. Only auth is
injected. Success, stale version and permission rejection use production routes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone

import pytest
import uvicorn
from fastapi import Request
from playwright.sync_api import expect
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from test_visual_smoke import browser, find_free_port, stop_process_tree, wait_for_url
from test_dashboard_publication_browser import WEB
from publication_fixture_helpers import publish_fixture
from dy_api.access_control import ALL_PAGE_KEYS
from dy_api.auth import AuthContext, get_current_user
from dy_api.db import Base
from dy_api.main import create_app
from dy_api.models import AggStoreMonthlySettlement, DimStore, PromotionInvoice, SettlementStatement
from dy_api.routes._data import get_session_dependency


@pytest.fixture()
def invoice_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DY_API_CORS_ORIGINS", "*")
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'invoice.sqlite3').as_posix()}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as session:
        session.add(DimStore(store_id="oct23-store", store_name="十月开票联调门店", is_active=True))
        session.add(AggStoreMonthlySettlement(month="2026-09", store_id="oct23-store",
                                             product_scope="all", product_type="all"))
        session.add(SettlementStatement(
            statement_id="oct23-bill", store_id="oct23-store", statement_month="2026-09",
            version_no=1, is_current=True, statement_status=1,
            promotion_original_fee_cent=10601, promotion_adjustment_fee_cent=0,
            promotion_net_fee_cent=10601, management_original_fee_cent=10601,
            management_adjustment_fee_cent=0, management_net_fee_cent=10601,
            created_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        session.commit()
        publish_fixture(session, "settlement")
    app = create_app()

    def user(request: Request):
        revoked = request.cookies.get("oct23_permission") == "revoked"
        return AuthContext(user_id="oct23-user", username="oct23-user", display_name="Invoice QA",
            role="admin", store_ids=(), store_scope_mode="none" if revoked else "all",
            auth_type="user", page_keys=tuple(ALL_PAGE_KEYS))

    def database():
        with factory() as session:
            yield session

    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_session_dependency] = database
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for_url(f"{url}/docs")
        yield url, factory
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()


@pytest.fixture()
def invoice_web(invoice_api, tmp_path):
    port = find_free_port()
    with (tmp_path / "vite.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
            "--host", "127.0.0.1", "--port", str(port), "--strictPort"], cwd=WEB,
            env={**os.environ, "VITE_USE_MOCKS": "false", "VITE_API_BASE_URL": f"{invoice_api[0]}/api/v1"},
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        url = f"http://127.0.0.1:{port}"
        try:
            wait_for_url(url)
            yield url
        finally:
            stop_process_tree(process)


def confirm_and_open(page, web):
    # The confirmation action depends on the live bill, which loads after the
    # publication metadata. Await that response before checking its UI action.
    with page.expect_response(lambda response: response.request.method == "GET"
            and "/store-settlements?" in response.url and "month=2026-09" in response.url) as loaded:
        page.goto(f"{web}/settlement?storeId=oct23-store&month=2026-09")
    assert loaded.value.status == 200, loaded.value.text()
    assert any(row["statementId"] == "oct23-bill" for row in loaded.value.json()["data"]["list"])
    button = page.get_by_role("button", name="确认推广服务费", exact=True)
    expect(button).to_be_enabled()
    button.click()
    with page.expect_response(lambda response: response.request.method == "POST" and "/confirmations" in response.url) as confirmed:
        page.get_by_role("button", name="确认提交", exact=True).click()
    assert confirmed.value.status == 200, confirmed.value.text()
    page.get_by_role("link", name="进入推广费开票").click()
    assert "/settlement/invoice" in page.url
    expect(page).to_have_title("抖音经营数据引擎")
    expect(page.get_by_role("heading", name="开票确认", exact=True)).to_be_visible()
    info = page.locator(".store-finance-invoice-info")
    expect(info).to_contain_text("106.01")
    return info


def fill_registration(page, number="00123456789012345678"):
    page.get_by_label("填写人电话", exact=True).fill("13800138000")
    page.get_by_label("开票日期", exact=True).fill(datetime.now(timezone(timedelta(hours=8))).date().isoformat())
    page.get_by_label("20 位数电专票号码", exact=True).fill(number)


@pytest.mark.parametrize("width,height", [(390, 844), (768, 1024), (1440, 900)])
def test_confirmed_bill_displays_server_tax_and_registers_without_manual_amounts(
    browser, invoice_web, invoice_api, tmp_path, width, height,
):
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    summaries = []
    posts = []
    page.on("request", lambda request: posts.append(request) if request.method == "POST" and request.url.endswith("/promotion-invoices") else None)
    page.on("response", lambda response: summaries.append(response) if "/store-settlements?" in response.url else None)
    try:
        info = confirm_and_open(page, invoice_web)
        assert summaries
        statement_data = summaries[-1].json()["data"]
        summary = statement_data["promotionInvoiceSummary"]
        group_id = statement_data["list"][0]["promotionInvoiceGroupId"]
        assert summary == {"invoiceAmountCent": 10601, "netAmountCent": 10001,
                           "taxAmountCent": 600, "taxRatePercent": 6,
                           "requiredStatementIds": ["oct23-bill"]}
        for label, amount in (("价税合计（含税总额）", "106.01"), ("不含税金额", "100.01"), ("税额（6%）", "6.00")):
            expect(info.locator("dl > div").filter(has=page.locator("dt", has_text=label))).to_contain_text(amount)
        for label in ("购买方名称", "税率", "不含税金额", "税额", "价税合计"):
            expect(page.get_by_label(label, exact=True)).to_have_count(0)
        expect(page.get_by_text("仅校验号码格式与登记条件，不进行税务验真。", exact=True)).to_be_visible()
        fill_registration(page)
        assert page.locator("body").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        expect(page.locator("vite-error-overlay")).to_have_count(0)
        page.screenshot(path=str(tmp_path / f"invoice-before-submit-{width}.png"), full_page=True)
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/promotion-invoices")) as registered:
            if width == 1440:
                page.locator("form.finance-form-grid").evaluate("form => { form.requestSubmit(); form.requestSubmit(); }")
            else:
                page.get_by_role("button", name="校验并登记发票", exact=True).click()
        assert len(posts) == 1
        response = registered.value
        assert response.status == 200, response.text()
        payload = response.request.post_data_json
        assert payload["invoiceNumber"] == "00123456789012345678"
        assert not {"buyerName", "taxRatePercent", "netAmountCent", "taxAmountCent", "invoiceAmountCent"}.intersection(payload)
        assert payload["allocations"] == [{"statementId": "oct23-bill", "statementMonth": "2026-09",
                                           "readVersion": 1, "promotionInvoiceGroupId": group_id}]
        expect(page.get_by_text("发票信息已登记，状态已更新。", exact=True)).to_be_visible()
        expect(page.get_by_label("20 位数电专票号码", exact=True)).to_have_value("")
        with invoice_api[1]() as session:
            row = session.scalar(select(PromotionInvoice).where(PromotionInvoice.invoice_number == "00123456789012345678"))
            assert row is not None
            assert (row.invoice_amount_cent, row.net_amount_cent, row.tax_amount_cent) == (10601, 10001, 600)
        assert errors == []
        page.screenshot(path=str(tmp_path / f"invoice-success-{width}.png"), full_page=True)
    finally:
        context.close()



def test_invalid_ascii_numbers_and_real_submit_failures_never_show_success(
    browser, invoice_web, invoice_api, tmp_path,
):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    posts = []
    page.on("request", lambda request: posts.append(request) if request.method == "POST" and request.url.endswith("/promotion-invoices") else None)
    try:
        confirm_and_open(page, invoice_web)
        fill_registration(page)
        number = page.get_by_label("20 位数电专票号码", exact=True)
        button = page.get_by_role("button", name="校验并登记发票", exact=True)
        for invalid in ("", "1" * 19, "1" * 21, "１" * 20, "١" * 20, "1234567890123456789a", " 1234567890123456789"):
            number.fill(invalid)
            button.click()
            expect(page.get_by_text("核验未通过：数电专票号码必须为20位半角数字且不得重复。", exact=True)).to_be_visible()
            expect(number).to_have_value(invalid)
            expect(page.get_by_text("发票信息已登记，状态已更新。", exact=True)).to_have_count(0)
        assert posts == []
        number.fill("00123456789012345678")
        page.get_by_label("开票日期", exact=True).fill("2026-09-01")
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/promotion-invoices")) as invalid_date:
            button.click()
        assert invalid_date.value.status == 422, invalid_date.value.text()
        expect(page.get_by_text("登记未成功，请核对下方错误后重试。", exact=True)).to_be_visible()
        expect(page.get_by_text("格式校验通过", exact=False)).to_have_count(0)
        expect(number).to_have_value("00123456789012345678")
        expect(page.get_by_text("发票信息已登记，状态已更新。", exact=True)).to_have_count(0)
        page.get_by_label("开票日期", exact=True).fill(datetime.now(timezone(timedelta(hours=8))).date().isoformat())
        with invoice_api[1]() as session:
            session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "oct23-bill")).version_no = 2
            session.commit()
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/promotion-invoices")) as conflict:
            button.click()
        assert conflict.value.status == 409, conflict.value.text()
        expect(number).to_have_value("00123456789012345678")
        expect(page.get_by_text("发票信息已登记，状态已更新。", exact=True)).to_have_count(0)
        expect(page.get_by_text("格式校验通过，正在提交服务器登记。", exact=True)).to_have_count(0)
        # Reload gets the new read version, then permission changes at the real API boundary.
        page.reload()
        expect(page.locator(".store-finance-invoice-info")).to_contain_text("106.01")
        fill_registration(page)
        context.add_cookies([{"name": "oct23_permission", "value": "revoked", "url": invoice_api[0]}])
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/promotion-invoices")) as denied:
            button.click()
        assert denied.value.status == 403, denied.value.text()
        expect(page.locator(".store-finance-invoice-info")).not_to_contain_text("106.01")
        expect(page.get_by_text("发票信息已登记，状态已更新。", exact=True)).to_have_count(0)
        expect(number).to_have_value("00123456789012345678")
        page.screenshot(path=str(tmp_path / "invoice-real-permission-failure.png"), full_page=True)
        with invoice_api[1]() as session:
            assert session.scalar(select(PromotionInvoice)) is None
    finally:
        context.close()
