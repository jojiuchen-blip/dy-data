"""Private real API fixtures keep successful UI imports out of shared UAT state."""

import csv
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from openpyxl import load_workbook
from playwright.sync_api import expect
from sqlalchemy import select

from apps.api.dy_api.models import StoreFinanceProfile
from test_finance_export_browser import api_data, click_download, goto
from test_visual_smoke import (
    LIVE_ADMIN_SESSION_FACTORIES,
    browser,  # noqa: F401
    live_admin_fastapi_base_url as base_api_fixture,
    vite_live_admin_api_base_url as base_vite_fixture,
)


@pytest.fixture()
def private_api(tmp_path_factory):
    """Reuse the existing synthetic server factory with a private DB per test."""
    yield from base_api_fixture.__wrapped__(tmp_path_factory)


@pytest.fixture()
def private_web(private_api):
    """Point an ordinary Vite server at the same private, real FastAPI instance."""
    yield from base_vite_fixture.__wrapped__(private_api)


@pytest.mark.parametrize("width", [390, 1440])
def test_download_fill_preview_commit_refresh_and_reenter_show_real_stored_value(browser, private_api, private_web, width):
    context = browser.new_context(viewport={"width": width, "height": 1000})
    page = context.new_page()
    try:
        query = {"month": "2026-08", "feeDirection": "PROMOTION", "metricScope": "MONTH", "q": "store-1"}
        before = api_data(context, private_api, "/admin/finance/stores", **query)["list"][0]
        goto(page, private_web, "/finance/stores?month=2026-08&q=store-1", "门店基础信息")
        downloaded = click_download(page, "下载基础信息导入模板")
        workbook = load_workbook(BytesIO(Path(downloaded.path()).read_bytes()))
        new_sap = "000012345678901234567890"
        workbook["数据导入"].append([before["storeId"], before["storeName"], new_sap, "2026-08-30T10:00:00+08:00"])
        workbook.active = 1
        content = BytesIO()
        workbook.save(content)
        page.get_by_role("button", name="导入门店基础信息", exact=True).click()
        page.get_by_label("文件", exact=True).set_input_files({"name": "中文基础信息.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": content.getvalue()})
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/admin/finance-imports")) as uploaded:
            page.get_by_role("button", name="上传并预览", exact=True).click()
        batch = uploaded.value.json()["data"]
        assert batch["totalRows"] == 1 and batch["errorRows"] == 0
        expect(page.get_by_label("整批处理分类")).to_contain_text("已写入0")
        expect(page.get_by_role("button", name="确认提交", exact=True)).to_be_enabled()
        with page.expect_response(lambda response: response.request.method == "POST" and (response.url.endswith("/commits") or response.url.endswith("/corrections"))) as committed:
            page.get_by_role("button", name="确认提交", exact=True).click()
        assert committed.value.status == 200
        expect(page.locator(".finance-store-table")).to_contain_text(new_sap)
        if width == 390:
            expect(page.locator(".data-table-mobile-list").get_by_text(new_sap, exact=True)).to_be_visible()
        factory = LIVE_ADMIN_SESSION_FACTORIES[private_api]
        with factory() as fresh:
            current = fresh.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.store_id == before["storeId"], StoreFinanceProfile.profile_type == 1, StoreFinanceProfile.is_current.is_(True)))
            assert current.sap_code == new_sap
            assert current.version_no == before["effectiveSapVersion"] + 1
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(".finance-store-table")).to_contain_text(new_sap)
        goto(page, private_web, "/finance/stores?month=2026-08&q=000012345678901234567890", "门店基础信息")
        expect(page.locator(".finance-store-table")).to_contain_text(new_sap)
        expect(page.get_by_role("columnheader", name="SAP确认状态", exact=True)).to_have_count(0)
        exported = click_download(page, "导出门店基础信息")
        rows = list(csv.DictReader(StringIO(Path(exported.path()).read_text(encoding="utf-8-sig"))))
        assert len(rows) == 1 and rows[0]["有效SAP编码"] == new_sap
        assert "sap_status" not in rows[0] and "SAP确认状态" not in rows[0]
        target = Path(f".tmp/oct30-finance-import-committed-{width}.png")
        target.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        context.close()
