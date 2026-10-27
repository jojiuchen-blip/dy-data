"""Frozen finance previews through real synthetic FastAPI/SQLite and Chromium.

Browser plugin not available. Only authentication is supplied by the existing
Playwright harness; successful API responses are never replaced.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from sqlalchemy import select

from test_visual_smoke import (
    LIVE_ADMIN_SESSION_FACTORIES, browser, live_admin_fastapi_base_url,
    vite_live_admin_api_base_url,
)
from dy_api.models import DimStore, FinanceImportBatch, FinanceImportRow, StoreFinanceProfile

live_admin_fastapi_base_url = pytest.fixture(scope="module")(live_admin_fastapi_base_url.__wrapped__)
vite_live_admin_api_base_url = pytest.fixture(scope="module")(vite_live_admin_api_base_url.__wrapped__)

MONTH = "2026-08"
STORE_IDS = [str(9007199254740993000000000 + index) for index in range(61)]


@pytest.fixture(scope="module")
def preview_stores(live_admin_fastapi_base_url):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    with factory() as session:
        for index, store_id in enumerate(STORE_IDS):
            session.add(DimStore(store_id=store_id, store_name=f"冻结预览门店{index:03}", is_active=True))
            session.add(StoreFinanceProfile(
                profile_id=f"preview-profile-{index}", store_id=store_id,
                profile_type=1, source_type=3, version_no=1, is_current=True,
                store_name_snapshot=f"冻结预览门店{index:03}", sap_code=f"SAP-OLD-{index:03}",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ))
        session.commit()
    return factory


def content(count=61, *, blocked=False, suffix="NEW"):
    rows = ["storeId,storeName,sapCode,importedAt"]
    rows.extend(f"{store_id},冻结预览门店{index:03},SAP-{suffix}-{index:03},2026-08-20T08:00:00+08:00"
                for index, store_id in enumerate(STORE_IDS[:count]))
    if blocked:
        rows[-1] = "synthetic-missing-store,不存在门店,SAP-BLOCKED,2026-08-20T08:00:00+08:00"
    return "\n".join(rows).encode("utf-8")


def upload(context, api, body, import_type="BASIC_INFO"):
    response = context.request.post(api + "/api/v1/admin/finance-imports", multipart={
        "importType": import_type, "statementMonth": MONTH,
        "file": {"name": "synthetic-preview.csv", "mimeType": "text/csv", "buffer": body},
    }, headers={"Idempotency-Key": f"preview-{uuid4().hex}"})
    assert response.status == 200, response.text()
    return response.json()["data"]


def open_batch(page, web, batch_id):
    page.goto(web + "/finance/imports?month=" + MONTH)
    expect(page.get_by_role("heading", name="导入记录", exact=True, level=1)).to_be_visible()
    page.get_by_role("button", name=batch_id, exact=True).click()
    preview = page.get_by_role("region", name="逐行字段预览", exact=True)
    expect(preview).to_be_visible()
    return preview


def test_upload_frozen_before_pagination_permission_failure_and_retry(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url, preview_stores, tmp_path,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    runtime_errors, posts, held = [], [], []
    page.on("pageerror", lambda error: runtime_errors.append(str(error)))
    page.on("console", lambda message: runtime_errors.append(message.text)
            if message.type == "error" and not message.text.startswith("Failed to load resource:") else None)
    page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
    page.route("**/api/v1/admin/finance-imports/*/rows?*", lambda route: held.append(route))
    try:
        page.goto(vite_live_admin_api_base_url + "/finance/stores?month=" + MONTH)
        expect(page).to_have_title("抖音经营数据引擎")
        page.get_by_role("button", name="导入门店基础信息", exact=True).click()
        panel = page.locator(".finance-import-card")
        panel.get_by_label("文件", exact=True).set_input_files({"name": "preview.csv", "mimeType": "text/csv", "buffer": content()})
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/finance-imports")) as uploaded:
            panel.get_by_role("button", name="上传并预览", exact=True).click()
        assert uploaded.value.status == 200
        batch = uploaded.value.json()["data"]
        preview = panel.get_by_role("region", name="逐行字段预览", exact=True)
        expect(preview).to_contain_text("正在加载逐行预览")
        expect(panel.get_by_role("button", name="确认提交", exact=True)).to_be_disabled()
        assert held
        with preview_stores() as session:
            profile = session.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.profile_id == "preview-profile-0"))
            profile.sap_code = "AFTER-UPLOAD-MUST-NOT-SHOW"
            session.commit()
        page.unroute("**/api/v1/admin/finance-imports/*/rows?*")
        expect(preview).to_contain_text("SAP-OLD-000")
        expect(preview).not_to_contain_text("AFTER-UPLOAD-MUST-NOT-SHOW")
        expect(preview).to_contain_text(STORE_IDS[0])
        expect(panel.get_by_role("button", name="确认提交", exact=True)).to_be_enabled()
        preview.get_by_label("输入页码", exact=True).fill("1")
        preview.get_by_role("button", name="跳转", exact=True).click()
        expect(panel.get_by_role("button", name="确认提交", exact=True)).to_be_enabled()
        pagination = preview.get_by_role("navigation", name="表格分页")
        expect(pagination).to_contain_text("共 61 条")
        pagination.get_by_role("button", name="下一页", exact=True).click()
        expect(pagination).to_contain_text("显示 51-61")
        context.add_cookies([{"name": "dy_e2e_role", "value": "store", "url": vite_live_admin_api_base_url}])
        pagination.get_by_role("button", name="上一页", exact=True).click()
        expect(preview).to_contain_text("当前账号没有执行此操作的权限")
        expect(panel.get_by_role("button", name="确认提交", exact=True)).to_be_disabled()
        context.add_cookies([{"name": "dy_e2e_role", "value": "admin", "url": vite_live_admin_api_base_url}])
        preview.get_by_role("button", name="重试预览", exact=True).click()
        expect(preview).to_contain_text("显示 1-50")
        expect(panel.get_by_role("button", name="确认提交", exact=True)).to_be_enabled()
        assert not any(url.endswith(("/commits", "/corrections")) for url in posts)
        page.screenshot(path=str(tmp_path / "frozen-preview-desktop.png"), full_page=False)
        assert not runtime_errors
        with preview_stores() as session:
            assert session.scalar(select(FinanceImportBatch).where(FinanceImportBatch.batch_id == batch["batchId"])).committed_at is None
    finally:
        context.close()


def test_batch_switch_legacy_unknown_and_empty_rows_do_not_reuse_previous_data(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url, preview_stores, tmp_path,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        previous = upload(context, live_admin_fastapi_base_url, content(1, suffix="RACE-OLD"))
        batch = upload(context, live_admin_fastapi_base_url, content(1, suffix="DETAIL"))
        held = []
        pattern = f"**/api/v1/admin/finance-imports/{previous['batchId']}/rows?*"
        page.route(pattern, lambda route: held.append(route))
        preview = open_batch(page, vite_live_admin_api_base_url, previous["batchId"])
        expect(preview).to_contain_text("正在加载逐行预览")
        page.get_by_role("button", name=batch["batchId"], exact=True).click()
        expect(preview).to_contain_text("SAP-DETAIL-000")
        assert held
        page.unroute(pattern)
        expect(preview).not_to_contain_text("SAP-RACE-OLD-000")
        page.get_by_role("button", name="uat-error-import", exact=True).click()
        expect(preview).to_contain_text("此批次未保存完整字段预览")
        expect(preview).not_to_contain_text("SAP-DETAIL-000")
        expect(preview).to_contain_text("无法核对，请重新上传")
        page.get_by_role("button", name="uat-basic-info-import", exact=True).click()
        expect(preview).to_contain_text("本批次没有可展示的预览行")
        expect(preview).not_to_contain_text("显示 1-0")
        expect(preview).not_to_contain_text("SAP-DETAIL-000")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("heading", name="导入记录", exact=True, level=1)).to_be_visible()
        preview.scroll_into_view_if_needed()
        expect(preview).to_contain_text("本批次没有可展示的预览行")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(tmp_path / "legacy-preview-mobile.png"), full_page=False)
    finally:
        context.close()


def test_blocked_row_on_second_page_prevents_commit_on_first_page(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url, preview_stores,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/finance/stores?month=" + MONTH)
        page.get_by_role("button", name="导入门店基础信息", exact=True).click()
        panel = page.locator(".finance-import-card")
        panel.get_by_label("文件", exact=True).set_input_files({"name": "blocked.csv", "mimeType": "text/csv", "buffer": content(blocked=True)})
        panel.get_by_role("button", name="上传并预览", exact=True).click()
        preview = panel.get_by_role("region", name="逐行字段预览", exact=True)
        expect(preview).to_contain_text("整批共有 1 行被阻断")
        expect(panel.get_by_role("button", name="确认提交", exact=True)).to_be_disabled()
        preview.get_by_role("button", name="下一页", exact=True).click()
        expect(preview).to_contain_text("synthetic-missing-store")
        expect(preview).to_contain_text("门店 ID 不存在")
        expect(preview).to_contain_text("本次变更被阻断")
    finally:
        context.close()


def test_zero_null_and_missing_field_remain_distinct_in_frozen_snapshot(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url, preview_stores,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        batch = upload(context, live_admin_fastapi_base_url,
            b"invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n25322000001784352160,APPROVED_SETTLED,,2026-08-12,12864050\n",
            "PROMOTION_FACTORY_RESULT")
        # Seed historical frozen values through the synthetic DB. The real GET
        # must preserve them and must not refill missing fields from live data.
        with preview_stores() as session:
            row = session.scalar(select(FinanceImportRow).where(FinanceImportRow.batch_id == batch["batchId"]))
            payload = copy.deepcopy(row.normalized_payload)
            payload["__preview"]["before"]["settlementAmountCent"] = 0
            payload["__preview"]["before"]["settlementDate"] = None
            del payload["__preview"]["before"]["rejectionReason"]
            row.normalized_payload = payload
            session.commit()
        preview = open_batch(page, vite_live_admin_api_base_url, batch["batchId"])
        expect(preview).to_contain_text("¥0.00")
        expect(preview).to_contain_text("空值（未记录）")
        expect(preview).to_contain_text("未提供")
        expect(preview).to_contain_text("25322000001784352160")
        expect(preview).not_to_contain_text("APPROVED_SETTLED")
    finally:
        context.close()


def test_frozen_preview_requires_explicit_confirm_and_commits_real_profile(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url, preview_stores,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/finance/stores?month=" + MONTH)
        page.get_by_role("button", name="导入门店基础信息", exact=True).click()
        panel = page.locator(".finance-import-card")
        panel.get_by_label("文件", exact=True).set_input_files({"name": "confirm.csv", "mimeType": "text/csv", "buffer": content(1, suffix="CONFIRMED")})
        panel.get_by_role("button", name="上传并预览", exact=True).click()
        expect(panel.get_by_role("region", name="逐行字段预览", exact=True)).to_contain_text("SAP-CONFIRMED-000")
        confirm = panel.get_by_role("button", name="确认提交", exact=True)
        expect(confirm).to_be_enabled()
        with preview_stores() as session:
            assert session.scalar(select(StoreFinanceProfile.sap_code).where(StoreFinanceProfile.store_id == STORE_IDS[0], StoreFinanceProfile.is_current.is_(True))) != "SAP-CONFIRMED-000"
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(("/commits", "/corrections"))) as committed:
            confirm.click()
        assert committed.value.status == 200, committed.value.text()
        expect(panel).to_contain_text("导入结果已生效")
        with preview_stores() as session:
            assert session.scalar(select(StoreFinanceProfile.sap_code).where(StoreFinanceProfile.store_id == STORE_IDS[0], StoreFinanceProfile.is_current.is_(True))) == "SAP-CONFIRMED-000"
    finally:
        context.close()
