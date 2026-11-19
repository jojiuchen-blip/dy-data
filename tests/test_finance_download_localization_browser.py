"""Browser downloads use the Chinese presentation and retain official facts.

The optional DYDATA_BROWSER_DATABASE_URL runs the existing synthetic FastAPI
fixture in an isolated PostgreSQL schema. Authentication uses its test roles.
"""

from __future__ import annotations

import csv
import os
import re
import uuid
from decimal import Decimal
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect
from openpyxl import load_workbook
from sqlalchemy import create_engine, select, text

import test_visual_smoke as live_fixture
from test_finance_export_browser import click_download, goto
from test_visual_smoke import browser  # noqa: F401
from apps.api.dy_api.models import FinanceImportBatch


@pytest.fixture(scope="module")
def localized_api(tmp_path_factory):
    database_url = os.environ.get("DYDATA_BROWSER_DATABASE_URL")
    if not database_url:
        yield from live_fixture.live_admin_fastapi_base_url.__wrapped__(tmp_path_factory)
        return

    schema = "finance_download_" + uuid.uuid4().hex
    maintenance = create_engine(database_url)
    with maintenance.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    original_create_engine = live_fixture.create_engine

    def isolated_engine(*_args, **_kwargs):
        return create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={schema}"},
            future=True,
        )

    generator = None
    try:
        live_fixture.create_engine = isolated_engine
        generator = live_fixture.live_admin_fastapi_base_url.__wrapped__(tmp_path_factory)
        base_url = next(generator)
        live_fixture.create_engine = original_create_engine
        yield base_url
    finally:
        live_fixture.create_engine = original_create_engine
        if generator is not None:
            generator.close()
        with maintenance.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        maintenance.dispose()


@pytest.fixture(scope="module")
def localized_web(localized_api):
    yield from live_fixture.vite_live_admin_api_base_url.__wrapped__(localized_api)


@pytest.mark.parametrize("direction,title", [("PROMOTION", "推广服务费"), ("MANAGEMENT", "管理服务费")])
def test_user_invoice_download_keeps_amounts_statuses_filters_and_long_ids(
    browser, localized_api, localized_web, direction, title, tmp_path,
):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        path = f"/finance/{direction.lower()}?month=2026-08"
        goto(page, localized_web, path, title)
        endpoint = "/api/v1/admin/finance/invoices"
        query = {"month": "2026-08", "feeDirection": direction, "metricScope": "MONTH", "pageSize": 50}
        before = context.request.get(f"{localized_api}{endpoint}", params=query).json()["data"]
        with page.expect_response(lambda response: "/admin/finance/invoices/export?" in response.url) as response_info:
            download = click_download(page, "导出当前筛选结果")
        response = response_info.value
        assert response.status == 200
        params = parse_qs(urlsplit(response.url).query)
        assert params["locale"] == ["zh-CN"]
        assert params["month"] == ["2026-08"]
        assert params["feeDirection"] == [direction]
        assert params.get("publication_id")
        assert re.fullmatch(rf"{title}开票记录_2026年08月_\d{{4}}年\d{{2}}月\d{{2}}日\.csv", download.suggested_filename)
        raw = Path(download.path()).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        evidence = Path(os.environ.get("DYDATA_BROWSER_EVIDENCE_DIR", str(tmp_path)))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / download.suggested_filename).write_bytes(raw)
        page.screenshot(path=str(evidence / f"{direction}-中文下载.png"), full_page=True)
        rows = list(csv.DictReader(StringIO(raw.decode("utf-8-sig"))))
        assert len(rows) == before["total"] > 0
        assert "status" not in rows[0]
        total_field = "推广费总额（元）" if direction == "PROMOTION" else "管理费总额（元）"
        for field in ["发票记录ID", "账期", total_field, "发票金额（元）", "开票状态", "登记时间"]:
            assert field in rows[0]
        assert "账单金额（元）" not in rows[0]
        expected_statuses = {
            "PENDING_INVOICE": "待开票",
            "SUBMITTED_PENDING_FACTORY_REVIEW": "已提交待厂家审核",
            "APPROVED_SETTLED": "审核通过已结算" if direction == "PROMOTION" else "已开票",
            "REJECTED_REUPLOAD": "已驳回待重传",
        }
        by_id = {(row["发票记录ID"], row["门店ID"]): row for row in rows}
        for invoice in before["list"]:
            row = by_id[(invoice["invoiceId"] or "", invoice["storeId"])]
            assert row["账期"] == "2026年08月"
            assert Decimal(row[total_field]) * 100 == invoice["statementAmountCent"]
            if invoice["invoiceAmountCent"] is None:
                assert row["发票金额（元）"] == ""
            else:
                assert Decimal(row["发票金额（元）"]) * 100 == invoice["invoiceAmountCent"]
            assert row["开票状态"] == expected_statuses[invoice["status"]]
            if invoice["registeredAt"]:
                registered_at = datetime.fromisoformat(invoice["registeredAt"].replace("Z", "+00:00"))
                assert row["登记时间"] == registered_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日 %H:%M:%S")
            if invoice["invoiceNumber"]:
                assert row["发票号码"].removeprefix("'") == invoice["invoiceNumber"]
                if len(invoice["invoiceNumber"]) > 15:
                    assert row["发票号码"].startswith("'")
        after = context.request.get(f"{localized_api}{endpoint}", params=query).json()["data"]
        assert after == before
        expect(page.get_by_role("status").filter(has_text="已导出当前筛选结果")).to_be_visible()
    finally:
        context.close()


IMPORT_CASES = [
    ("BASIC_INFO", "/finance/stores?month=2026-08&q=store-1", "门店基础信息",
     "下载基础信息导入模板", "导入门店基础信息",
     ["store-1", "深圳临港认证服务店", "000012345678901234567890", "2026-08-30T10:00:00+08:00"]),
    ("SAP_CONFIRMATION", "/finance/stores?month=2026-08&tab=sap", "门店基础信息",
     "下载 SAP 编码确认模板", "导入最终确认 SAP 编码",
     ["store-2", "杭州滨江直营服务店", "S1003178", "STORE-03178", "S1003999", "已确认", "2026-08-30T10:00:00+08:00"]),
    ("PROMOTION_FACTORY_RESULT", "/finance/promotion?month=2026-08", "推广服务费",
     "下载推广服务费厂家导入模板", "导入推广服务费厂家信息",
     ["25322000001784352171", "审核不通过需重新上传", "隔离浏览器核对原因", "", ""]),
    ("MANAGEMENT_FACTORY_RESULT", "/finance/management?month=2026-08", "管理服务费",
     "下载管理服务费厂家导入模板", "导入管理服务费厂家信息",
     ["store-2", "2026-08", "杭州滨江直营服务店", "00991234567890123456", "2026-08-30", "2026-08-31", "230000"]),
]


@pytest.mark.parametrize("kind,path,heading,template_button,import_button,values", IMPORT_CASES)
def test_chinese_template_preview_commit_persists_and_refreshes_actual_page(
    browser, localized_api, localized_web, kind, path, heading, template_button, import_button, values, tmp_path,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        goto(page, localized_web, path, heading)
        downloaded = click_download(page, template_button)
        workbook = load_workbook(BytesIO(Path(downloaded.path()).read_bytes()))
        workbook["数据导入"].append(values)
        filled = BytesIO()
        workbook.save(filled)
        page.get_by_role("button", name=import_button, exact=True).click()
        page.get_by_label("文件", exact=True).set_input_files({
            "name": f"{kind}-中文输入.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "buffer": filled.getvalue(),
        })
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/admin/finance-imports")) as upload:
            page.get_by_role("button", name="上传并预览", exact=True).click()
        assert upload.value.status == 200, upload.value.text()
        batch = upload.value.json()["data"]
        assert batch["errorRows"] == 0 and batch["successRows"] == 1
        factory = live_fixture.LIVE_ADMIN_SESSION_FACTORIES[localized_api]
        with factory() as session:
            assert session.scalar(select(FinanceImportBatch).where(FinanceImportBatch.batch_id == batch["batchId"])).committed_at is None
        expect(page.get_by_role("button", name="确认提交", exact=True)).to_be_enabled()
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(("/commits", "/corrections"))) as commit:
            page.get_by_role("button", name="确认提交", exact=True).click()
        assert commit.value.status == 200, commit.value.text()
        with factory() as session:
            assert session.scalar(select(FinanceImportBatch).where(FinanceImportBatch.batch_id == batch["batchId"])).committed_at is not None
        if kind in {"BASIC_INFO", "SAP_CONFIRMATION"}:
            expected_sap = values[2] if kind == "BASIC_INFO" else values[4]
            goto(page, localized_web, f"/finance/stores?month=2026-08&q={values[0]}", "门店基础信息")
            expect(page.locator(".finance-store-table")).to_contain_text(expected_sap)
            expect(page.get_by_role("columnheader", name="SAP确认状态", exact=True)).to_have_count(0)
            exported = click_download(page, "导出门店基础信息")
            rows = list(csv.DictReader(StringIO(Path(exported.path()).read_text(encoding="utf-8-sig"))))
            assert len(rows) == 1 and rows[0]["有效SAP编码"].removeprefix("'") == expected_sap
        else:
            page.reload(wait_until="domcontentloaded")
            expect(page.get_by_text("隔离浏览器核对原因" if kind == "PROMOTION_FACTORY_RESULT" else values[3], exact=True).first).to_be_visible()
            exported = click_download(page, "导出当前筛选结果")
            rows = list(csv.DictReader(StringIO(Path(exported.path()).read_text(encoding="utf-8-sig"))))
            matched = next(row for row in rows if row["发票号码"].removeprefix("'") == (values[0] if kind == "PROMOTION_FACTORY_RESULT" else values[3]))
            assert matched["开票状态"] == ("已驳回待重传" if kind == "PROMOTION_FACTORY_RESULT" else "已开票")
        evidence = Path(os.environ.get("DYDATA_BROWSER_EVIDENCE_DIR", str(tmp_path)))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / f"{kind}-提交后.csv").write_bytes(Path(exported.path()).read_bytes())
        page.screenshot(path=str(evidence / f"{kind}-提交后.png"), full_page=True)
        goto(page, localized_web, f"/finance/imports?importType={kind}&month=2026-08", "导入记录")
        page.get_by_role("button", name=batch["batchId"], exact=True).click()
        if kind == "MANAGEMENT_FACTORY_RESULT":
            expect(page.get_by_role("button", name="撤销批次", exact=True)).to_have_count(0)
        else:
            page.get_by_placeholder("说明为何需要生成更正覆盖版本").fill("隔离浏览器恢复上一版")
            with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/reversals")) as reversal:
                page.get_by_role("button", name="撤销批次", exact=True).click()
            assert reversal.value.status == 200, reversal.value.text()
            assert reversal.value.json()["data"]["reversesBatchId"] == batch["batchId"]
    finally:
        context.close()


@pytest.mark.parametrize("disposition,filename", [
    (None, "财务导出结果.csv"),
    ('attachment; filename="fallback.csv"; filename*=UTF-8\'\'%ZZ', "fallback.csv"),
])
def test_invalid_or_missing_filename_header_still_downloads_with_visible_feedback(
    browser, localized_web, disposition, filename,
):
    """Only the explicitly malformed export response is intercepted here."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        goto(page, localized_web, "/finance/promotion?month=2026-08", "推广服务费")
        headers = {"Access-Control-Allow-Origin": page.url.split("/finance/")[0], "Access-Control-Allow-Credentials": "true"}
        if disposition is not None:
            headers["Content-Disposition"] = disposition
        headers["Access-Control-Expose-Headers"] = "Content-Disposition"
        page.route("**/admin/finance/invoices/export?**", lambda route: route.fulfill(
            status=200, content_type="text/csv; charset=utf-8", headers=headers,
            body="\ufeff开票状态\r\n待开票\r\n",
        ))
        downloaded = click_download(page, "导出当前筛选结果")
        assert downloaded.suggested_filename == filename
        assert "待开票" in Path(downloaded.path()).read_text(encoding="utf-8-sig")
        expect(page.get_by_role("status").filter(has_text="已导出当前筛选结果")).to_be_visible()
    finally:
        context.close()
