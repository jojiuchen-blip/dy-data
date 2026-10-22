"""Bounded real-API acceptance for the seven remaining DYDATA-105 controls.

Every row is synthetic and owned by this module's disposable API/database.
No successful API response is intercepted. Teardown disposes the whole service.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect
from sqlalchemy import func, select

from test_visual_smoke import (
    LIVE_ADMIN_SESSION_FACTORIES, browser, live_admin_fastapi_base_url,
    vite_live_admin_api_base_url,
)
from dy_api.models import (
    DimStore, FinanceImportBatch, FinanceImportRow, FinanceOperationAudit,
    InvoiceRecord, PromotionInvoice, PromotionInvoiceAllocation,
    PromotionInvoiceLifecycleEvent, PromotionInvoiceNumberRegistry,
    RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
    SettlementFeeAdjustment, SettlementFeeResult, SettlementFeeResultCurrent,
    SettlementStatement, SettlementStatementConfirmation, StoreFinanceProfile,
)
from publication_fixture_helpers import publish_fixture

live_admin_fastapi_base_url = pytest.fixture(scope="module")(live_admin_fastapi_base_url.__wrapped__)
vite_live_admin_api_base_url = pytest.fixture(scope="module")(vite_live_admin_api_base_url.__wrapped__)
NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def choose(page, label, option):
    control = page.get_by_role("combobox").first if label == "导入类型" else page.get_by_label(label, exact=True)
    control.click()
    if label == "导入类型":
        control.fill(option)
    page.get_by_role("option", name=option, exact=True).click()


def exercise_pagination(nav, total, *, size=50):
    """Exercise all navigation controls against a real multi-page result."""
    pages = (total + size - 1) // size
    expect(nav).to_contain_text(f"共 {total} 条", timeout=20000)
    nav.get_by_role("button", name="下一页", exact=True).click()
    expect(nav).to_contain_text(f"第 2 / {pages} 页", timeout=20000)
    nav.get_by_role("button", name="上一页", exact=True).click()
    expect(nav).to_contain_text(f"第 1 / {pages} 页", timeout=20000)
    nav.get_by_role("button", name="末页", exact=True).click()
    expect(nav).to_contain_text(f"第 {pages} / {pages} 页", timeout=20000)
    nav.get_by_role("button", name="首页", exact=True).click()
    expect(nav).to_contain_text(f"第 1 / {pages} 页", timeout=20000)
    nav.get_by_label("输入页码", exact=True).fill(str(pages))
    nav.get_by_role("button", name="跳转", exact=True).click()
    expect(nav).to_contain_text(f"第 {pages} / {pages} 页", timeout=20000)
    nav.get_by_role("button", name="首页", exact=True).click()


def clone(source, **overrides):
    values = {attr.key: getattr(source, attr.key) for attr in source.__mapper__.column_attrs if attr.key != "id"}
    return type(source)(**(values | overrides))


def test_remaining_details_months_states_pagination_adjustment_and_invalid_return(
    browser, live_admin_fastapi_base_url, vite_live_admin_api_base_url, tmp_path,
):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    with factory() as session:
        source = session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == "uat-fee-promotion"))
        for index in range(61):
            key = f"R105-D-{index:03d}"
            order = RawDouyinOrder(order_id=key, sale_time=datetime(2026, 8, 2, tzinfo=timezone.utc),
                order_status_normalized="COMPLETED", sku_id=key, product_name="合成明细分页", order_paid_amount_cent=1286405)
            session.add(order)
            session.flush()
            session.add(RawDouyinOrderCoupon(coupon_id=key, order_id=key, raw_order_id=order.id,
                coupon_status_normalized="USED", coupon_paid_amount_cent=1286405))
            session.add(RawDouyinVerifyRecord(verify_id=key, coupon_id=key, verify_status="USED",
                verify_time=datetime(2026, 8, 3, tzinfo=timezone.utc)))
            session.add(clone(source, fee_result_id=key, coupon_id=key, order_id=key, sku_id=key))
            session.add(SettlementFeeResultCurrent(coupon_id=key, fee_direction=1, fee_result_id=key))
        session.add(SettlementFeeAdjustment(adjustment_id="R105-adjust", original_fee_result_id="R105-D-000",
            coupon_id="R105-D-000", order_id="R105-D-000", fee_direction=1,
            original_business_month="2026-08", adjustment_posting_month="2026-08", adjustment_type=1,
            adjustment_base_cent=-10, adjustment_fee_cent=-1, rule_version="uat-rule-v1",
            adjustment_reason="合成一分退款调整", occurred_at=NOW, created_by="synthetic"))
        session.commit()
        publish_fixture(session, "settlement")
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/details?storeId=store-1&month=2026-08&q=R105-D-")
        nav = page.get_by_role("navigation", name="表格分页")
        exercise_pagination(nav, 61)
        choose(page, "销售月份", "2026-08")
        expect(nav).to_contain_text("共 61 条", timeout=20000)
        choose(page, "核销月份", "2026-08")
        expect(nav).to_contain_text("共 61 条", timeout=20000)
        choose(page, "数据状态", "有效")
        expect(nav).to_contain_text("共 60 条", timeout=20000)
        choose(page, "数据状态", "有调整")
        expect(nav).to_contain_text("共 1 条", timeout=20000)
        adjustment = page.locator("table details").first
        adjustment.locator("summary").click()
        expect(adjustment.locator("p")).to_contain_text("合成一分退款调整")
        adjustment.locator("summary").click()
        expect(adjustment.locator("p")).not_to_be_visible()
        choose(page, "数据状态", "全部")
        expect(nav).to_contain_text("共 61 条", timeout=20000)
        with page.expect_download() as pending:
            page.get_by_role("button", name="导出", exact=True).click()
        rows = list(csv.DictReader(StringIO(Path(pending.value.path()).read_bytes().decode("utf-8-sig"))))
        assert len(rows) == 61
        assert sum(int(row["调整后净额"]) for row in rows) == 61 * 128641 - 1
        page.screenshot(path=tmp_path / "remaining-details-real.png", full_page=True)
        page.goto(vite_live_admin_api_base_url + "/details?storeId=store-1&month=2026-08&feeRates=0.999999")
        page.get_by_role("button", name="返回单店分账", exact=True).click()
        expect(page).to_have_url(re.compile(r"/settlement\?.*storeId=store-1.*month=2026-08"))
    finally:
        context.close()


@pytest.mark.parametrize("direction,order_id,status_label", [
    ("promotion", "DY2026071900842", "审核通过，已结算"),
    ("management", "DY20260622001935", "已开票"),
])
def test_remaining_finance_order_status_filters_and_source_disclosure(
    browser, vite_live_admin_api_base_url, direction, order_id, status_label,
):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + f"/finance/orders/{direction}?month=2026-08&q={order_id}")
        expect(page.get_by_text(order_id, exact=True).first).to_be_visible(timeout=20000)
        choose(page, "发票审核状态", status_label)
        choose(page, "结算状态", "已结算")
        with page.expect_response(lambda response: "/admin/finance/order-details?" in response.url and "settlementStatus=SETTLED" in response.url) as pending:
            page.get_by_role("button", name="应用筛选", exact=True).click()
        assert pending.value.status == 200, pending.value.text()
        assert pending.value.json()["data"]["total"] == 1
        choose(page, "结算状态", "未结算")
        page.get_by_role("button", name="应用筛选", exact=True).click()
        expect(page.get_by_text("当前筛选下暂无订单明细", exact=True).first).to_be_visible()
        disclosure = page.locator("details").filter(has=page.locator("summary", has_text="字段来源与计算说明"))
        disclosure.locator("summary").click()
        expect(disclosure).to_have_attribute("open", "")
        expect(disclosure.locator("dt").first).to_be_visible()
        disclosure.locator("summary").click()
        expect(disclosure).not_to_have_attribute("open", "")
    finally:
        context.close()


def test_remaining_management_mobile_correction_real_readback(
    browser, live_admin_fastapi_base_url, vite_live_admin_api_base_url, tmp_path,
):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    with factory() as session:
        old = session.scalar(select(InvoiceRecord).where(InvoiceRecord.invoice_id == "uat-management-invoice"))
        version = old.version_no
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/finance/management?month=2026-08&q=深圳")
        page.get_by_role("button", name="更正", exact=True).click()
        panel = page.locator(".finance-correction-panel")
        expect(panel.get_by_label("发票金额（分）", exact=True)).to_have_value("320000", timeout=20000)
        panel.get_by_label("发票号码", exact=True).fill("71050000000000009999")
        panel.get_by_label("更正原因", exact=True).fill("合成窄屏更正")
        with page.expect_response(lambda response: response.request.method == "POST" and "/management-invoices/" in response.url) as pending:
            panel.get_by_role("button", name="确认更正", exact=True).click()
        assert pending.value.status == 200, pending.value.text()
        with factory() as session:
            current = session.scalar(select(InvoiceRecord).where(InvoiceRecord.store_id == "store-1", InvoiceRecord.is_current.is_(True)))
            assert current.version_no == version + 1
            assert current.invoice_number == "71050000000000009999"
            assert current.invoice_amount_cent == current.factory_deduction_amount_cent == 320000
        page.screenshot(path=tmp_path / "remaining-mobile-correction.png", full_page=True)
        panel.get_by_role("button", name="关闭", exact=True).click()
        expect(panel).to_have_count(0)
    finally:
        context.close()


def upload(request, api, content):
    response = request.post(api + "/api/v1/admin/finance-imports", headers={"Idempotency-Key": str(uuid4())},
        multipart={"importType": "BASIC_INFO", "statementMonth": "2026-09", "file": {
            "name": "synthetic-remaining.csv", "mimeType": "text/csv", "buffer": content.encode("utf8")}})
    assert response.status == 200, response.text()
    return response.json()["data"]


def test_remaining_import_list_filters_and_nested_error_reversal_pagination(
    browser, live_admin_fastapi_base_url, vite_live_admin_api_base_url, tmp_path,
):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    with factory() as session:
        for index in range(61):
            key = f"R105-I-{index:03d}"
            session.add(DimStore(store_id=key, store_name=f"合成导入店{index:03d}", is_active=True))
            session.add(FinanceImportBatch(batch_id=key, import_type=1, statement_month="2026-10",
                file_name="synthetic.csv", file_sha256=f"{index:064x}", normalized_sha256=f"{index:064x}",
                read_version=0, current_version=0, batch_status=1, total_rows=0,
                success_rows=0, error_rows=0, content_changed=False, submitted_by="synthetic", submitted_at=NOW))
        session.commit()
        before = session.scalar(select(func.count()).select_from(StoreFinanceProfile))
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/finance/imports?month=2026-10&importType=BASIC_INFO")
        nav = page.get_by_role("navigation", name="表格分页")
        exercise_pagination(nav, 61)
        choose(page, "导入类型", "SAP 确认")
        expect(nav).to_contain_text("共 0 条", timeout=20000)
        choose(page, "导入类型", "门店基础信息")
        expect(nav).to_contain_text("共 61 条", timeout=20000)
        page.get_by_label("业务账期", exact=True).fill("2026-07")
        expect(nav).to_contain_text("共 0 条", timeout=20000)
        page.get_by_label("业务账期", exact=True).fill("2026-10")
        expect(nav).to_contain_text("共 61 条", timeout=20000)
        choose(page, "每页条数", "每页 20 条")
        exercise_pagination(nav, 61, size=20)
        header = "storeId,storeName,sapCode,importedAt\n"
        invalid = upload(context.request, live_admin_fastapi_base_url, header + "".join(f"R105-BAD-{index:03d},,,\n" for index in range(61)))
        assert invalid["errorRows"] == 61
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(StoreFinanceProfile)) == before
        page.goto(vite_live_admin_api_base_url + "/finance/imports?month=2026-09&importType=BASIC_INFO")
        page.get_by_role("button", name=invalid["batchId"], exact=True).click()
        panel = page.locator(".finance-import-detail")
        errors_nav = panel.get_by_role("navigation", name="表格分页")
        error_detail = context.request.get(live_admin_fastapi_base_url + f"/api/v1/admin/finance-imports/{invalid['batchId']}").json()["data"]
        errors_total = error_detail["errors"]["total"]
        exercise_pagination(errors_nav, errors_total)
        errors_nav.get_by_label("每页条数", exact=True).click()
        page.get_by_role("option", name="每页 20 条", exact=True).click()
        exercise_pagination(errors_nav, errors_total, size=20)
        with page.expect_download() as downloaded:
            panel.get_by_role("button", name="下载全部错误", exact=True).click()
        assert len(list(csv.DictReader(StringIO(Path(downloaded.value.path()).read_bytes().decode("utf-8-sig"))))) == errors_total
        panel.get_by_role("button", name="关闭", exact=True).click()
        valid = upload(context.request, live_admin_fastapi_base_url, header + "".join(
            f"R105-I-{index:03d},合成导入店{index:03d},R105SAP{index:03d},2026-09-20T10:00:00+08:00\n" for index in range(61)))
        assert valid["errorRows"] == 0 and valid["successRows"] == 61
        endpoint = "/corrections" if valid["scenario"] == "DIFF_CONFIRMATION_REQUIRED" else "/commits"
        committed = context.request.post(live_admin_fastapi_base_url + f"/api/v1/admin/finance-imports/{valid['batchId']}" + endpoint,
            data={"readVersion": valid["readVersion"], "changeReason": "合成61行业务键"}, headers={"Idempotency-Key": str(uuid4())})
        assert committed.status == 200, committed.text()
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(StoreFinanceProfile)) == before + 61
        page.reload()
        page.get_by_role("button", name=valid["batchId"], exact=True).click()
        panel.get_by_label("撤销原因", exact=True).fill("合成61行撤销验收")
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/reversals")) as reversed_response:
            panel.get_by_role("button", name="撤销批次", exact=True).click()
        assert reversed_response.value.status == 200, reversed_response.value.text()
        lineage_nav = panel.get_by_role("navigation", name="表格分页")
        exercise_pagination(lineage_nav, 61)
        lineage_nav.get_by_label("每页条数", exact=True).click()
        page.get_by_role("option", name="每页 20 条", exact=True).click()
        exercise_pagination(lineage_nav, 61, size=20)
        with factory() as session:
            original_rows = list(session.scalars(select(FinanceImportRow).where(FinanceImportRow.batch_id == valid["batchId"])))
            assert len(original_rows) == 61
            original_ids = [row.target_record_id for row in original_rows]
            assert session.scalar(select(func.count()).select_from(StoreFinanceProfile).where(
                StoreFinanceProfile.profile_id.in_(original_ids), StoreFinanceProfile.is_current.is_(True))) == 0
            assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
                FinanceOperationAudit.operation_type == "FINANCE_IMPORT_REVERSAL",
                FinanceOperationAudit.target_id == reversed_response.value.json()["data"]["batchId"])) == 1
        page.screenshot(path=tmp_path / "remaining-imports-lineage-61.png", full_page=True)
    finally:
        context.close()


def test_remaining_status_pagination_and_real_terminated_candidate_recovery(
    browser, live_admin_fastapi_base_url, vite_live_admin_api_base_url, tmp_path,
):
    """A real single-period page is bounded to one current invoice by the DB.

    The separate replacement-candidate control preserves that current-list scope.
    """
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    with factory() as session:
        for store_id, amount in (("R105-RESUME", 12345),):
            session.add(DimStore(store_id=store_id, store_name=store_id, is_active=True))
            session.add(SettlementStatement(statement_id=store_id, store_id=store_id, statement_month="2026-09",
                version_no=1, is_current=True, statement_status=2, promotion_original_fee_cent=amount,
                promotion_adjustment_fee_cent=0, promotion_net_fee_cent=amount,
                management_original_fee_cent=0, management_adjustment_fee_cent=0, management_net_fee_cent=0,
                store_name_snapshot=store_id, sap_code_snapshot="R105SAP", store_snapshot_status="LIVE_CAPTURED"))
            session.add(SettlementStatementConfirmation(confirmation_id=store_id, statement_id=store_id,
                fee_direction=1, confirmation_status=1, confirmed_amount_cent=amount, confirmed_by="synthetic", confirmed_at=NOW))
        for index in (61,):
            is_resume = index == 61
            key = f"R105-P-{index:03d}"
            store_id = "R105-RESUME" if is_resume else "R105-STATUS"
            amount = 12345 if is_resume else 100
            number = f"7105{index:016d}"
            session.add(PromotionInvoice(invoice_id=key, physical_invoice_id=key, store_id=store_id,
                version_no=1, version_kind=1, is_current=True, invoice_number=number,
                invoice_date=date(2026, 9, 1), invoice_amount_cent=amount, buyer_name="比亚迪汽车销售有限公司",
                tax_rate_percent=6, invoice_status=4 if is_resume else 3, registered_by="synthetic", registered_at=NOW + timedelta(seconds=index)))
            session.add(PromotionInvoiceNumberRegistry(invoice_number=number, physical_invoice_id=key, first_invoice_id=key, store_id=store_id))
            session.add(PromotionInvoiceAllocation(allocation_id=key, invoice_id=key, store_id=store_id,
                statement_id=store_id, statement_month="2026-09", settlement_batch_month="2026-09",
                allocated_amount_cent=amount, is_current=True))
        session.commit()
        publish_fixture(session, "settlement")
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(vite_live_admin_api_base_url + "/settlement/invoice/status?storeId=R105-RESUME&month=2026-09")
        nav = page.get_by_role("navigation", name="表格分页")
        expect(nav).to_contain_text("共 1 条", timeout=20000)
        for label in ("首页", "上一页", "下一页", "末页"):
            expect(nav.get_by_role("button", name=label, exact=True)).to_be_disabled()
        nav.get_by_label("输入页码", exact=True).fill("0")
        nav.get_by_role("button", name="跳转", exact=True).click()
        assert nav.get_by_label("输入页码", exact=True).evaluate("element => element.validity.rangeUnderflow")
        expect(nav).to_contain_text("第 1 / 1 页")
        nav.get_by_label("输入页码", exact=True).fill("1")
        nav.get_by_role("button", name="跳转", exact=True).click()
        expect(nav).to_contain_text("第 1 / 1 页")
        terminated = context.request.post(live_admin_fastapi_base_url + "/api/v1/promotion-invoices/R105-P-061/lifecycle-events",
            data={"eventType": "VOIDED", "reason": "合成系统外作废", "readVersion": 1}, headers={"Idempotency-Key": str(uuid4())})
        assert terminated.status == 200, terminated.text()
        status_result = context.request.get(live_admin_fastapi_base_url + "/api/v1/store-invoice-status",
            params={"storeId": "R105-RESUME", "month": "2026-09"})
        candidates = context.request.get(live_admin_fastapi_base_url + "/api/v1/promotion-invoices/replacement-candidates",
            params={"storeId": "R105-RESUME"})
        assert status_result.status == candidates.status == 200
        assert status_result.json()["data"]["promotionTotal"] == 0
        assert [row["invoice"]["invoiceId"] for row in candidates.json()["data"]["list"]] == ["R105-P-061"]
        page.goto(vite_live_admin_api_base_url + "/settlement/invoice?storeId=R105-RESUME&month=2026-09")
        page.get_by_role("button", name="恢复替换 71050000000000000061", exact=True).click()
        expect(page.get_by_text("替换原发票 71050000000000000061", exact=False)).to_be_visible()
        page.evaluate("sessionStorage.clear()")
        with factory() as session:
            before_navigation = tuple(session.scalar(select(func.count()).select_from(model)) for model in
                (PromotionInvoice, PromotionInvoiceAllocation, PromotionInvoiceLifecycleEvent))
        page.goto(vite_live_admin_api_base_url + "/settlement/invoice/status?storeId=R105-RESUME&month=2026-09")
        expect(page.get_by_role("heading", name="发票状态查看", exact=True)).to_be_visible()
        page.get_by_role("button", name=re.compile(r"^重新开票")).click()
        expect(page.get_by_role("heading", name="开票确认", exact=True)).to_be_visible()
        expect(page.get_by_text("替换原发票 71050000000000000061", exact=False)).to_be_visible()
        with factory() as session:
            assert tuple(session.scalar(select(func.count()).select_from(model)) for model in
                (PromotionInvoice, PromotionInvoiceAllocation, PromotionInvoiceLifecycleEvent)) == before_navigation
        for label, value in (("购买方名称", "比亚迪汽车销售有限公司"), ("填写人电话", "13812345678"), ("税率", "6"),
            ("开票日期", datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()),
            ("20 位数电专票号码", "71050000000000009998"), ("不含税金额", "116.46"), ("税额", "6.99"), ("价税合计", "123.45")):
            page.get_by_label(label, exact=True).fill(value)
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/promotion-invoices")) as replacement:
            page.get_by_role("button", name="核验并登记发票", exact=True).click()
        assert replacement.value.status == 200, replacement.value.text()
        with factory() as session:
            old = session.scalar(select(PromotionInvoice).where(PromotionInvoice.invoice_id == "R105-P-061"))
            new = session.scalar(select(PromotionInvoice).where(PromotionInvoice.invoice_number == "71050000000000009998"))
            assert not old.is_current and new.is_current and new.replaces_invoice_id == old.invoice_id
            assert new.invoice_amount_cent == 12345
            assert session.scalar(select(func.count()).select_from(PromotionInvoiceLifecycleEvent).where(PromotionInvoiceLifecycleEvent.invoice_id == old.invoice_id)) == 1
        page.screenshot(path=tmp_path / "remaining-real-resumed-invoice.png", full_page=True)
    finally:
        context.close()
