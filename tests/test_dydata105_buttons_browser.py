"""Finance button writes run only against the existing disposable API fixture."""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect
from openpyxl import Workbook
from sqlalchemy import func, select

from test_visual_smoke import (
    LIVE_ADMIN_SESSION_FACTORIES, browser, live_admin_fastapi_base_url,
    vite_live_admin_api_base_url,
)
from dy_api.models import (
    FinanceImportBatch, FinanceImportRow, FinanceOperationAudit,
    InvoiceRecord, PromotionInvoice, StoreFinanceProfile,
    DimStore, SettlementStatement, SettlementStatementConfirmation,
    PromotionInvoiceAllocation, PromotionInvoiceLifecycleEvent,
    SettlementDispute, AggStoreRanking, SapSuggestion,
)
from publication_fixture_helpers import publish_fixture

# Writes in this acceptance module must not change the session-level fixture
# consumed by the existing export/visual regressions in a full-suite run.
live_admin_fastapi_base_url = pytest.fixture(scope="module")(live_admin_fastapi_base_url.__wrapped__)
vite_live_admin_api_base_url = pytest.fixture(scope="module")(vite_live_admin_api_base_url.__wrapped__)


IMPORTS = [
    ("BASIC_INFO", "/finance/stores", "导入门店基础信息",
     "storeId,storeName,sapCode,importedAt\nstore-1,深圳临港认证服务店,SAP1050001,2026-08-21T10:00:00+08:00\n"),
    ("SAP_CONFIRMATION", "/finance/stores?tab=sap", "导入最终确认 SAP 编码",
     "storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,factoryConfirmationResult,confirmedAt\nstore-1,深圳临港认证服务店,SAP1050001,SVC105,SAP1050002,CONFIRMED,2026-08-21T11:00:00+08:00\n"),
    ("PROMOTION_FACTORY_RESULT", "/finance/promotion", "导入推广服务费厂家信息",
     "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n25322000001784352171,APPROVED_SETTLED,,2026-08-21,7642000\n"),
    ("MANAGEMENT_FACTORY_RESULT", "/finance/management", "导入管理服务费厂家信息",
     "storeId,statementMonth,storeName,invoiceNumber,invoiceDate,deductionDate,deductionAmountCent\nstore-2,2026-08,杭州滨江直营服务店,22345678901234560105,2026-08-20,2026-08-21,230000\n"),
]


def upload_from_page(page, content):
    page.get_by_label("文件", exact=True).set_input_files(
        {"name": "synthetic-105.csv", "mimeType": "text/csv", "buffer": content.encode("utf-8")}
    )
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/admin/finance-imports")) as pending:
        page.get_by_role("button", name="上传并预览", exact=True).click()
    response = pending.value
    assert response.status == 200, response.text()
    return response.json()["data"]


@pytest.mark.parametrize("import_type,path,open_label,content", IMPORTS)
def test_dydata105_four_import_buttons_commit_readback_replay_and_reverse(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
    tmp_path, import_type, path, open_label, content,
):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + path + ("&" if "?" in path else "?") + "month=2026-08")
        page.get_by_role("button", name=open_label, exact=True).click()
        batch = upload_from_page(page, content)
        assert batch["errorRows"] == 0, context.request.get(live_admin_fastapi_base_url + f"/api/v1/admin/finance-imports/{batch['batchId']}").text()
        assert batch["scenario"] in {"FIRST_IMPORT_READY", "DIFF_CONFIRMATION_REQUIRED"}
        page.get_by_label("变更原因", exact=True).fill("DYDATA105合成数据按钮验收")
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(("/commits", "/corrections"))) as pending:
            page.get_by_role("button", name="确认提交", exact=True).click()
        committed = pending.value
        assert committed.status == 200, committed.text()
        expect(page.get_by_text("导入结果已生效；导入时间作为审核通过或结算完成时间。", exact=True)).to_be_visible()
        with factory() as session:
            persisted = session.scalar(select(FinanceImportBatch).where(FinanceImportBatch.batch_id == batch["batchId"]))
            assert persisted.batch_status in (5, 8)
            rows = list(session.scalars(select(FinanceImportRow).where(FinanceImportRow.batch_id == batch["batchId"])))
            assert len(rows) == 1 and rows[0].target_record_id
            target_id = rows[0].target_record_id
            model = PromotionInvoice if import_type == "PROMOTION_FACTORY_RESULT" else InvoiceRecord if import_type == "MANAGEMENT_FACTORY_RESULT" else StoreFinanceProfile
            id_field = model.invoice_id if model in (PromotionInvoice, InvoiceRecord) else model.profile_id
            fact = session.scalar(select(model).where(id_field == target_id))
            assert fact is not None and fact.is_current
            if import_type == "BASIC_INFO":
                assert fact.sap_code == "SAP1050001"
            elif import_type == "SAP_CONFIRMATION":
                assert fact.sap_code == "SAP1050002" and fact.factory_confirmed
            elif import_type == "MANAGEMENT_FACTORY_RESULT":
                assert fact.invoice_amount_cent == fact.factory_deduction_amount_cent == 230000
            else:
                assert fact.invoice_status == 3 and fact.invoice_amount_cent == 7642000
            audit_count = session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(FinanceOperationAudit.target_id == batch["batchId"]))
        # Retry the exact browser request. It must replay instead of adding a version.
        replay = context.request.post(committed.url, data=committed.request.post_data_json,
                                      headers={"Idempotency-Key": committed.request.headers["idempotency-key"]})
        assert replay.status == 200, replay.text()
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(FinanceOperationAudit.target_id == batch["batchId"])) == audit_count
        unchanged = upload_from_page(page, content)
        assert unchanged["scenario"] == "NO_CHANGE"
        expect(page.get_by_role("button", name="确认提交", exact=True)).to_be_disabled()
        page.goto(vite_live_admin_api_base_url + f"/finance/imports?month=2026-08&importType={import_type}")
        page.get_by_role("button", name=batch["batchId"], exact=True).click()
        page.get_by_placeholder("说明为何需要生成更正覆盖版本", exact=True).fill("撤销合成验收结果")
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/reversals")) as reverse_pending:
            page.get_by_role("button", name="撤销批次", exact=True).click()
        reversed_response = reverse_pending.value
        assert reversed_response.status == 200, reversed_response.text()
        detail = context.request.get(live_admin_fastapi_base_url + f"/api/v1/admin/finance-imports/{batch['batchId']}").json()["data"]
        assert detail["reversedByBatchId"] and not detail["canReverse"]
        with factory() as session:
            fact = session.scalar(select(model).where(id_field == target_id))
            assert fact is not None and not fact.is_current
            assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
                FinanceOperationAudit.target_id == detail["reversedByBatchId"],
                FinanceOperationAudit.operation_type == "FINANCE_IMPORT_REVERSAL")) == 1
        page.screenshot(path=tmp_path / f"{import_type}-reversed.png", full_page=True)
    finally:
        context.close()


@pytest.mark.parametrize("import_type,path,open_label,content", IMPORTS)
def test_dydata105_four_import_error_files_are_complete_without_business_writes(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
    import_type, path, open_label, content,
):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    def business_counts():
        with factory() as session:
            return tuple(session.scalar(select(func.count()).select_from(model)) for model in (StoreFinanceProfile, InvoiceRecord, PromotionInvoice))
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        before = business_counts()
        page.goto(vite_live_admin_api_base_url + path + ("&" if "?" in path else "?") + "month=2026-08")
        page.get_by_role("button", name=open_label, exact=True).click()
        header = content.splitlines()[0]
        invalid = header + "\n" + "".join(f"INVALID{index:03d}" + "," * header.count(",") + "\n" for index in range(61))
        batch = upload_from_page(page, invalid)
        assert batch["errorRows"] > 0
        detail = context.request.get(live_admin_fastapi_base_url + f"/api/v1/admin/finance-imports/{batch['batchId']}").json()["data"]
        with page.expect_download() as pending:
            page.get_by_role("button", name="下载全部错误", exact=True).click()
        payload = Path(pending.value.path()).read_bytes()
        assert payload.startswith(b"\xef\xbb\xbf")
        errors = list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))
        assert len(errors) == detail["errors"]["total"] > 0
        assert all(row["reason"] and row["field"] for row in errors)
        expect(page.get_by_role("button", name="确认提交", exact=True)).to_be_disabled()
        assert business_counts() == before
        page.get_by_role("link", name="查看导入记录", exact=True).click()
        page.get_by_role("button", name=batch["batchId"], exact=True).click()
        detail_panel = page.locator(".finance-import-detail")
        pagination = detail_panel.get_by_role("navigation", name="表格分页")
        expect(pagination).to_contain_text(f"共 {detail['errors']['total']} 条")
        pagination.get_by_role("button", name="末页", exact=True).click()
        expect(pagination).not_to_contain_text("第 1 /")
        pagination.get_by_role("button", name="上一页", exact=True).click()
        pagination.get_by_role("button", name="首页", exact=True).click()
        expect(pagination).to_contain_text("第 1 /")
        detail_panel.get_by_role("button", name="关闭", exact=True).click()
        expect(detail_panel).to_have_count(0)
        assert business_counts() == before
    finally:
        context.close()


@pytest.mark.parametrize("import_type,path,open_label,content", IMPORTS)
def test_dydata105_xlsx_preview_abandon_has_zero_business_writes(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
    import_type, path, open_label, content,
):
    """All four Excel uploads preview only; hiding the panel abandons the batch."""
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    models = (StoreFinanceProfile, InvoiceRecord, PromotionInvoice)
    with factory() as session:
        before = tuple(session.scalar(select(func.count()).select_from(model)) for model in models)
    workbook = Workbook()
    for row in csv.reader(StringIO(content)):
        workbook.active.append(row)
    data = BytesIO()
    workbook.save(data)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + path + ("&" if "?" in path else "?") + "month=2026-08")
        page.get_by_role("button", name=open_label, exact=True).click()
        page.get_by_label("文件", exact=True).set_input_files({
            "name": "synthetic-105.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "buffer": data.getvalue(),
        })
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/admin/finance-imports")) as pending:
            page.get_by_role("button", name="上传并预览", exact=True).click()
        response = pending.value
        assert response.status == 200, response.text()
        batch = response.json()["data"]
        assert batch["errorRows"] == 0 and batch["successRows"] == 1
        page.get_by_role("button", name=open_label, exact=True).click()
        expect(page.get_by_role("heading", name="导入财务数据", exact=True)).to_have_count(0)
        with factory() as session:
            persisted = session.scalar(select(FinanceImportBatch).where(FinanceImportBatch.batch_id == batch["batchId"]))
            assert persisted.committed_at is None
            assert tuple(session.scalar(select(func.count()).select_from(model)) for model in models) == before
    finally:
        context.close()


@pytest.mark.parametrize("event_label,event_type,suffix", [("登记红冲", "RED_FLUSHED", "1"), ("登记作废", "VOIDED", "2")])
def test_dydata105_store_confirm_invoice_lifecycle_and_replacement_real_readback(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
    tmp_path, event_label, event_type, suffix,
):
    """Actual buttons -> formal API -> database; native cancel makes zero writes."""
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    key = "B105-flow-" + suffix
    with factory() as session:
        session.add(DimStore(store_id=key, store_name="合成开票闭环" + suffix, is_active=True))
        session.add(SettlementStatement(
            statement_id=key, store_id=key, statement_month="2026-09", version_no=1,
            is_current=True, statement_status=1, promotion_original_fee_cent=12345,
            promotion_net_fee_cent=12345, promotion_adjustment_fee_cent=0,
            management_original_fee_cent=6789, management_net_fee_cent=6789,
            management_adjustment_fee_cent=0, store_name_snapshot="合成开票闭环" + suffix,
            sap_code_snapshot="SAP105FLOW", store_snapshot_status="LIVE_CAPTURED",
            created_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        ))
        session.commit()
        publish_fixture(session, "settlement")
    context = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + f"/settlement?storeId={key}&month=2026-09")
        for direction in ("推广服务费", "管理服务费"):
            page.get_by_role("button", name="确认" + direction, exact=True).click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_role("button", name="返回查看", exact=True).click()
            expect(page.get_by_role("dialog")).to_have_count(0)
            with factory() as session:
                direction_code = 1 if direction == "推广服务费" else 2
                assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation).where(
                    SettlementStatementConfirmation.statement_id == key,
                    SettlementStatementConfirmation.fee_direction == direction_code)) == 0
            page.get_by_role("button", name="确认" + direction, exact=True).click()
            with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/confirmations")) as pending:
                page.get_by_role("dialog").get_by_role("button", name="确认提交", exact=True).click()
            assert pending.value.status == 200, pending.value.text()
        with factory() as session:
            confirmations = list(session.scalars(select(SettlementStatementConfirmation).where(SettlementStatementConfirmation.statement_id == key)))
            assert {row.confirmed_amount_cent for row in confirmations} == {12345, 6789}
        for tab in ("管理费明细", "推广费明细"):
            page.get_by_role("tab", name=tab, exact=True).click()
            expect(page.get_by_role("tab", name=tab, exact=True)).to_have_attribute("aria-selected", "true")
        page.get_by_role("button", name="发起账单异议", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        page.get_by_role("button", name="发起账单异议", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="确认发起", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(SettlementDispute).where(SettlementDispute.statement_id == key)) == 0
        page.get_by_role("link", name="进入推广费开票", exact=True).click()
        expect(page.get_by_role("heading", name="开票确认", exact=True, level=1)).to_be_visible()
        page.get_by_role("button", name="一键复制全部开票信息", exact=True).click()
        assert "比亚迪汽车销售有限公司" in page.evaluate("navigator.clipboard.readText()")

        def register(number):
            for label, value in (("购买方名称", "比亚迪汽车销售有限公司"), ("填写人电话", "13812345678"), ("税率", "6"),
                                 ("开票日期", datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()), ("20 位数电专票号码", number),
                                 ("不含税金额", "116.46"), ("税额", "6.99"), ("价税合计", "123.45")):
                page.get_by_label(label, exact=True).fill(value)
            with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/promotion-invoices")) as pending:
                page.get_by_role("button", name="核验并登记发票", exact=True).click()
            assert pending.value.status == 200, pending.value.text()
            return pending.value.json()["data"]

        page.get_by_role("button", name="核验并登记发票", exact=True).click()
        expect(page.get_by_text("系统校验结果", exact=True)).to_be_visible()
        number = "1050000000000000000" + suffix
        register(number)
        # Lifecycle controls intentionally appear only after a formal factory rejection.
        page.goto(vite_live_admin_api_base_url + "/finance/promotion?month=2026-09")
        page.get_by_role("button", name="导入推广服务费厂家信息", exact=True).click()
        rejection = upload_from_page(page,
            "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
            + number + ",REJECTED_REUPLOAD,合成厂家退回,,\n")
        assert rejection["errorRows"] == 0, rejection
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(("/commits", "/corrections"))) as rejected:
            page.get_by_role("button", name="确认提交", exact=True).click()
        assert rejected.value.status == 200, rejected.value.text()
        with factory() as session:
            invoice = session.scalar(select(PromotionInvoice).where(PromotionInvoice.invoice_number == number, PromotionInvoice.is_current.is_(True)))
            assert invoice is not None and invoice.invoice_amount_cent == 12345 and invoice.invoice_status == 4
            invoice_id = invoice.invoice_id
        page.goto(vite_live_admin_api_base_url + f"/settlement/invoice/status?storeId={key}&month=2026-09")
        page.get_by_label("发票号码", exact=True).fill("123")
        page.get_by_role("button", name="服务端精确查询", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("20")
        page.get_by_label("发票号码", exact=True).fill(number)
        with page.expect_response(lambda response: "/api/v1/store-invoice-status?" in response.url and f"invoiceNumber={number}" in response.url) as queried:
            page.get_by_role("button", name="服务端精确查询", exact=True).click()
        assert queried.value.status == 200
        expect(page.get_by_text(number, exact=True).first).to_be_visible()
        page.get_by_role("button", name="查看详情", exact=True).click()
        page.once("dialog", lambda dialog: dialog.dismiss())
        page.get_by_role("button", name=event_label, exact=True).click()
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(PromotionInvoiceLifecycleEvent).where(PromotionInvoiceLifecycleEvent.invoice_id == invoice_id)) == 0
        def accept_native(dialog):
            dialog.accept("合成系统外完成事实" if dialog.type == "prompt" else None)
        page.on("dialog", accept_native)
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/lifecycle-events")) as lifecycle:
            page.get_by_role("button", name=event_label, exact=True).click()
        assert lifecycle.value.status == 200, lifecycle.value.text()
        page.remove_listener("dialog", accept_native)
        expect(page.get_by_role("heading", name="开票确认", exact=True, level=1)).to_be_visible()
        page.get_by_role("button", name="重新加载释放账期", exact=True).click()
        expect(page.get_by_text("已重新加载全部释放账期。", exact=True)).to_be_visible()
        register("1060000000000000000" + suffix)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(PromotionInvoiceLifecycleEvent).where(PromotionInvoiceLifecycleEvent.invoice_id == invoice_id)) == 1
            old_allocations = list(session.scalars(select(PromotionInvoiceAllocation).where(PromotionInvoiceAllocation.invoice_id == invoice_id)))
            assert old_allocations and all(not allocation.is_current for allocation in old_allocations)
            replacement = session.scalar(select(PromotionInvoice).where(PromotionInvoice.invoice_number == "1060000000000000000" + suffix, PromotionInvoice.is_current.is_(True)))
            assert replacement is not None and replacement.invoice_amount_cent == 12345
        page.screenshot(path=tmp_path / f"{event_type}-replacement.png", full_page=True)
    finally:
        context.close()


@pytest.mark.parametrize("direction,order_id,channel,amount", [
    ("promotion", "DY2026071900842", "直播", 128641),
    ("management", "DY20260622001935", "短视频", 32000),
])
def test_dydata105_finance_order_apply_reset_detail_and_full_filter_bytes(
    browser, vite_live_admin_api_base_url, direction, order_id, channel, amount,
):
    # These exact UTC boundaries model a Shanghai user's selected calendar days;
    # do not inherit the CI runner's UTC timezone or the developer host timezone.
    context = browser.new_context(viewport={"width": 1440, "height": 900}, timezone_id="Asia/Shanghai")
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + f"/finance/orders/{direction}?month=2026-08")
        expect(page.get_by_role("cell", name=order_id, exact=True).first).to_be_visible(timeout=20000)
        page.get_by_role("cell", name=order_id, exact=True).first.dblclick()
        drawer = page.get_by_role("complementary", name="订单完整字段")
        expect(drawer).to_contain_text(order_id)
        drawer.get_by_role("button", name="关闭", exact=True).click()
        page.get_by_label("搜索", exact=True).fill("no-matching-105")
        page.get_by_role("button", name="应用筛选", exact=True).click()
        expect(page.get_by_text("当前筛选下暂无订单明细", exact=True).first).to_be_visible()
        with page.expect_download() as empty_download:
            page.get_by_role("button", name="导出全部命中结果", exact=True).click()
        assert list(csv.DictReader(StringIO(Path(empty_download.value.path()).read_bytes().decode("utf-8-sig")))) == []
        page.get_by_role("button", name="重置筛选", exact=True).click()
        page.get_by_label("筛选账期", exact=True).fill("2026-08")
        page.get_by_label("搜索", exact=True).fill(order_id)
        page.get_by_label("销售渠道", exact=True).click()
        page.get_by_role("option", name=channel, exact=True).click()
        page.get_by_label("核销开始日期", exact=True).fill("2026-08-01")
        page.get_by_label("核销结束日期", exact=True).fill("2026-08-31")
        page.get_by_label("发票提交开始日期", exact=True).fill("2026-08-01")
        page.get_by_label("发票提交结束日期", exact=True).fill("2026-08-31")
        with page.expect_response(lambda response: "/api/v1/admin/finance/order-details?" in response.url) as applied:
            page.get_by_role("button", name="应用筛选", exact=True).click()
        assert applied.value.status == 200, applied.value.text()
        assert applied.value.json()["data"]["total"] == 1
        with page.expect_response(lambda response: "/api/v1/admin/finance/order-details/export?" in response.url) as exported:
            with page.expect_download() as downloaded:
                page.get_by_role("button", name="导出全部命中结果", exact=True).click()
        filters = parse_qs(urlparse(exported.value.url).query)
        assert filters["q"] == [order_id]
        assert filters["month"] == ["2026-08"]
        for key, value in (("verifyFrom", "2026-07-31T16:00:00.000Z"), ("verifyTo", "2026-08-31T15:59:59.999Z"), ("submittedFrom", "2026-07-31T16:00:00.000Z"), ("submittedTo", "2026-08-31T15:59:59.999Z")):
            assert filters[key] == [value]
        assert "page" not in filters and "pageSize" not in filters
        payload = Path(downloaded.value.path()).read_bytes()
        assert payload.startswith(b"\xef\xbb\xbf")
        records = list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))
        assert len(records) == 1 and records[0]["order_id"] == order_id
        assert sum(int(row["frozen_fee_amount_cent"]) for row in records) == amount
    finally:
        context.close()


def test_dydata105_management_correction_reads_live_version_and_persists(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/finance/management?month=2026-08")
        # Desktop exposes the whole row as the keyboard action; the labelled
        # "更正" button is the narrow-screen card action.
        page.locator("tr[role=button]").filter(has_text="store-1").press("Enter")
        panel = page.locator(".finance-correction-panel")
        expect(panel.get_by_label("发票金额（分）", exact=True)).to_have_value("320000", timeout=20000)
        panel.get_by_role("button", name="读取当前记录", exact=True).click()
        expect(panel.get_by_label("发票金额（分）", exact=True)).to_have_value("320000")
        panel.get_by_label("发票号码", exact=True).fill("22345678901234560106")
        panel.get_by_label("更正原因", exact=True).fill("合成管理发票更正")
        with page.expect_response(lambda response: response.request.method == "POST" and "/management-invoices/" in response.url and response.url.endswith("/corrections")) as pending:
            panel.get_by_role("button", name="确认更正", exact=True).click()
        assert pending.value.status == 200, pending.value.text()
        expect(panel.get_by_text("更正已保存并保留历史版本，经营结果随后台发布更新。", exact=True)).to_be_visible()
        with factory() as session:
            row = session.scalar(select(InvoiceRecord).where(InvoiceRecord.store_id == "store-1", InvoiceRecord.is_current.is_(True)))
            assert row.invoice_number == "22345678901234560106"
            assert row.invoice_amount_cent == row.factory_deduction_amount_cent == 320000
            assert row.version_no > 1
        panel.get_by_role("button", name="关闭", exact=True).click()
        expect(panel).to_have_count(0)
    finally:
        context.close()


def test_dydata105_sap_detail_cancel_then_correct_database_version(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
):
    """Closing SAP correction is read-only; confirmed correction versions the fact."""
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    with factory() as session:
        session.add(DimStore(store_id="B105-SAP", store_name="合成SAP矫正店", is_active=True))
        session.add(StoreFinanceProfile(profile_id="B105-SAP", store_id="B105-SAP", profile_type=1,
            source_type=3, version_no=1, is_current=True, store_name_snapshot="合成SAP矫正店", sap_code="OLD105"))
        session.add(SapSuggestion(suggestion_id="B105-SAP", store_id="B105-SAP", version_no=1,
            is_current=True, suggested_sap_code="REQUESTED105", suggestion_status=1, suggestion_note="合成差异",
            submitted_by="synthetic", submitted_at=datetime.now(timezone.utc)))
        session.commit()
        before_count = session.scalar(select(func.count()).select_from(StoreFinanceProfile))
        before = session.scalar(select(StoreFinanceProfile).where(
            StoreFinanceProfile.store_id == "B105-SAP", StoreFinanceProfile.is_current.is_(True)))
        version = before.version_no
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/finance/stores?month=2026-08&tab=sap&q=B105-SAP")
        page.get_by_role("button", name="查看详情", exact=True).click()
        drawer = page.get_by_role("complementary", name="SAP 差异详情")
        drawer.get_by_label("最终有效 SAP", exact=True).fill("SYNTHETIC105")
        drawer.get_by_role("button", name="关闭", exact=True).click()
        expect(drawer).to_have_count(0)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(StoreFinanceProfile)) == before_count
        page.get_by_role("button", name="查看详情", exact=True).click()
        drawer.get_by_label("最终有效 SAP", exact=True).fill("SYNTHETIC105")
        drawer.get_by_label("矫正原因", exact=True).fill("合成SAP按钮验收")
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/sap-corrections")) as pending:
            drawer.get_by_role("button", name="确认矫正并生成新版本", exact=True).click()
        assert pending.value.status == 200, pending.value.text()
        with factory() as session:
            current = session.scalar(select(StoreFinanceProfile).where(
                StoreFinanceProfile.store_id == "B105-SAP", StoreFinanceProfile.is_current.is_(True)))
            assert current.sap_code == "SYNTHETIC105" and current.version_no > version
            assert session.scalar(select(func.count()).select_from(StoreFinanceProfile)) == before_count + 1
    finally:
        context.close()


def test_dydata105_dispute_real_detection_transition_and_readback(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/finance/disputes?month=2026-08")
        page.get_by_role("button", name="处理", exact=True).first.click()
        drawer = page.get_by_role("complementary", name="账单异议详情")
        drawer.get_by_role("button", name="关闭", exact=True).click()
        expect(drawer).to_have_count(0)
        page.get_by_role("button", name="处理", exact=True).first.click()
        drawer.get_by_role("button", name="启动系统检测", exact=True).click()
        expect(drawer.get_by_text("系统检测完成", exact=True)).to_be_visible(timeout=20000)
        drawer.get_by_role("button", name="重新检测", exact=True).click()
        expect(drawer.get_by_text("系统检测完成", exact=True)).to_be_visible(timeout=20000)
        drawer.get_by_label("处理结果", exact=True).click()
        page.get_by_role("option", name="不成立", exact=True).click()
        drawer.get_by_label("处理说明", exact=True).fill("合成异议人工核验不成立")
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/transitions")) as pending:
            drawer.get_by_role("button", name="确认处理", exact=True).click()
        assert pending.value.status == 200, pending.value.text()
        with factory() as session:
            dispute = session.scalar(select(SettlementDispute).where(SettlementDispute.dispute_id == "uat-dispute-001"))
            assert dispute.status == 5
            assert dispute.resolution_note == "合成异议人工核验不成立"
        expect(drawer).to_have_count(0)
        page.reload()
        expect(page.get_by_role("cell", name="不成立", exact=True).first).to_be_visible(timeout=20000)
    finally:
        context.close()


def test_dydata105_finance_download_scope_and_expired_session_are_enforced(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        context.add_cookies([{"name": "dy_e2e_role", "value": "admin_restricted", "url": live_admin_fastapi_base_url}])
        page = context.new_page()
        page.goto(vite_live_admin_api_base_url + "/finance/promotion?month=2026-08")
        expect(page.get_by_role("cell", name="深圳临港认证服务店 store-1", exact=False).first).to_be_visible(timeout=20000)
        with page.expect_download() as pending:
            page.get_by_role("button", name="导出当前筛选结果", exact=True).click()
        rows = list(csv.DictReader(StringIO(Path(pending.value.path()).read_bytes().decode("utf-8-sig"))))
        assert rows and {row["store_id"] for row in rows} == {"store-1"}
        context.add_cookies([{"name": "dy_e2e_role", "value": "anonymous", "url": live_admin_fastapi_base_url}])
        response = context.request.get(live_admin_fastapi_base_url + "/api/v1/admin/finance/invoices/export?month=2026-08&feeDirection=PROMOTION&metricScope=MONTH")
        assert response.status == 401
        page.reload()
        expect(page.get_by_role("button", name="导出当前筛选结果", exact=True)).to_have_count(0)
    finally:
        context.close()


def test_dydata105_ranking_filters_drill_and_order_fee_direction_downloads(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url, tmp_path,
):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    with factory() as session:
        for index in range(60):
            store_id = f"B105-RANK-{index:03d}"
            session.add(DimStore(store_id=store_id, store_name=f"合成排行店{index:03d}", is_active=True))
            session.add(AggStoreRanking(
                period_type=1, period_key="2026-08", month="2026-08",
                store_id=store_id, store_name=f"合成排行店{index:03d}",
                product_scope="all", product_type="all", sales_order_count=1,
                sales_amount_cent=10000, verified_order_count=1, verified_amount_cent=10000,
                promotion_net_fee_cent=100, management_net_fee_cent=50, net_settlement_reference_cent=50,
            ))
        for period_type in (1, 2):
            for product_scope in ("all", "原产品范围"):
                session.add(AggStoreRanking(
                    period_type=period_type, period_key="2026-08", month="2026-08",
                    store_id="store-1", store_name="深圳临港认证服务店",
                    product_scope=product_scope, product_type="all",
                    sales_order_count=2, sales_amount_cent=1606405,
                    verified_order_count=2, verified_amount_cent=1606405,
                    promotion_net_fee_cent=128641, management_net_fee_cent=32000,
                    net_settlement_reference_cent=96641,
                ))
        publish_fixture(session, "settlement")
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.clock.install(time="2026-10-22T00:00:00Z")
    request_order = []
    page.on("request", lambda request: request_order.append(("request", request.url))
            if "/monthly-settlement?" in request.url else None)
    page.on("response", lambda response: request_order.append(("response", response.url, response.status))
            if "/monthly-settlement?" in response.url else None)
    try:
        page.goto(vite_live_admin_api_base_url + "/ranking?periodKey=2026-08")
        expect(page.get_by_role("heading", name="全国门店月度榜单", exact=True)).to_be_visible()
        pagination = page.get_by_role("navigation", name="表格分页")
        expect(pagination).to_contain_text("共 61 条", timeout=20000)
        pagination.get_by_role("button", name="下一页", exact=True).click()
        expect(pagination).to_contain_text("第 2 / 4 页", timeout=20000)
        pagination.get_by_role("button", name="末页", exact=True).click()
        expect(pagination).to_contain_text("显示 61-61", timeout=20000)
        pagination.get_by_role("button", name="上一页", exact=True).click()
        expect(pagination).to_contain_text("第 3 / 4 页", timeout=20000)
        pagination.get_by_role("button", name="首页", exact=True).click()
        expect(pagination).to_contain_text("第 1 / 4 页", timeout=20000)
        pagination.get_by_label("输入页码", exact=True).fill("2")
        pagination.get_by_role("button", name="跳转", exact=True).click()
        expect(pagination).to_contain_text("第 2 / 4 页", timeout=20000)
        page.get_by_label("账期", exact=True).click()
        page.get_by_role("option", name="2026-08", exact=True).click()
        expect(page.get_by_text("深圳临港认证服务店", exact=True).first).to_be_visible(timeout=20000)
        page.get_by_label("搜索门店", exact=True).fill("不存在105门店")
        expect(page.get_by_text("当前筛选下没有门店结果。", exact=True)).to_be_visible()
        page.get_by_label("搜索门店", exact=True).fill("深圳")
        expect(page.get_by_text("深圳临港认证服务店", exact=True).first).to_be_visible()
        for label, option in (("排行依据", "累计推广服务费"), ("统计方式", "月度"), ("产品范围", "原产品范围")):
            page.get_by_label(label, exact=True).click()
            page.get_by_role("option", name=option, exact=True).click()
            expect(page.get_by_text("深圳临港认证服务店", exact=True).first).to_be_visible(timeout=20000)
        page.get_by_role("link").filter(has_text="深圳临港认证服务店").click()
        expect(page).to_have_url(re.compile(r"/settlement\?.*storeId=store-1"))
        page.get_by_label("账期", exact=True).click()
        page.get_by_role("option", name="2026-08", exact=True).click()
        expect(page.get_by_role("combobox", name="门店", exact=True)).to_be_visible()
        store_select = page.locator(".searchable-store-select").get_by_role("combobox")
        expect(store_select).to_be_enabled()
        page.evaluate("""() => {
          window.storeSelectionEvents = [];
          for (const type of ['focus', 'blur', 'input']) {
            document.addEventListener(type, (event) => {
              if (event.target.matches?.('.searchable-store-select input')) {
                window.storeSelectionEvents.push({ type, value: event.target.value,
                  expanded: event.target.getAttribute('aria-expanded'), time: performance.now() });
              }
            }, true);
          }
        }""")
        store_select.fill("杭州")
        page.get_by_role("option", name="杭州滨江直营服务店", exact=True).click()
        expect(store_select).to_have_value("杭州滨江直营服务店")
        expect(store_select).to_be_enabled()
        # Re-enter before the preceding blur callback runs. This models native
        # keyboard focus changes, using virtual time rather than a fixed sleep.
        page.clock.pause_at(datetime.fromtimestamp(page.evaluate("Date.now() + 1000") / 1000, tz=timezone.utc))
        store_select.click()
        store_select.press("Tab")
        store_select.fill("深圳")
        expect(store_select).to_have_value("深圳")
        expect(store_select).to_have_attribute("aria-expanded", "true")
        page.clock.fast_forward(150)
        expect(store_select).to_have_value("深圳")
        expect(store_select).to_have_attribute("aria-expanded", "true")
        page.get_by_role("option", name="深圳临港认证服务店", exact=True).click()
        expect(store_select).to_have_value("深圳临港认证服务店")
        expect(store_select).to_be_enabled()
        store_select.fill("不存在105门店")
        store_select.press("Tab")
        page.clock.fast_forward(150)
        expect(store_select).to_have_value("深圳临港认证服务店")
        expect(store_select).to_have_attribute("aria-expanded", "false")
        page.clock.resume()
        for tab in ("管理费明细", "推广费明细"):
            page.get_by_role("tab", name=tab, exact=True).click()
            expect(page.get_by_role("tab", name=tab, exact=True)).to_have_attribute("aria-selected", "true")
        (tmp_path / "store-selection-events.txt").write_text(str({
            "input_events": page.evaluate("window.storeSelectionEvents || []"),
            "request_order": request_order,
            "dom": page.locator(".searchable-store-select").evaluate_all("items => items.map(item => item.outerHTML)"),
        }), encoding="utf-8")
        page.screenshot(path=str(tmp_path / "store-selection-restored.png"), full_page=True)
        page.goto(vite_live_admin_api_base_url + "/details?storeId=store-1&month=2026-08")
        for label, order_id, amount in (("推广服务费", "DY2026071900842", 128641), ("管理服务费", "DY20260622001935", 32000)):
            page.get_by_label("搜索", exact=True).fill("")
            page.get_by_role("button", name=label, exact=True).click()
            expect(page.get_by_text(order_id, exact=True).first).to_be_visible(timeout=20000)
            page.get_by_label("搜索", exact=True).fill("missing105")
            expect(page.get_by_text("当前筛选下没有费用记录。", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="导出", exact=True)).to_be_disabled()
            page.get_by_label("搜索", exact=True).fill(order_id)
            expect(page.get_by_text(order_id, exact=True).first).to_be_visible()
            with page.expect_download() as pending:
                page.get_by_role("button", name="导出", exact=True).click()
            records = list(csv.DictReader(StringIO(Path(pending.value.path()).read_bytes().decode("utf-8-sig"))))
            assert len(records) == 1 and records[0]["订单ID"] == order_id
            assert int(records[0]["调整后净额"]) == amount
    except Exception:
        page.screenshot(path=str(tmp_path / "store-selection-failure.png"), full_page=True)
        (tmp_path / "store-selection-events.txt").write_text(str({
            "input_events": page.evaluate("window.storeSelectionEvents || []"),
            "request_order": request_order,
            "dom": page.locator(".searchable-store-select").evaluate_all("items => items.map(item => item.outerHTML)"),
        }), encoding="utf-8")
        raise
    finally:
        context.close()
