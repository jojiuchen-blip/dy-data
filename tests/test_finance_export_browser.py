"""DYDATA-97 导出/下载按钮真实浏览器回归（测试先行，不改生产代码）。

来源：``logs/dydata97/all-export-audit.md`` §7 的针对性验证矩阵（V1-V9）。
本模块只新增测试与最小合成种子，生产缺陷由 Codex 在跑红后修复，本模块不降低断言。

夹具复用（不新建框架）
----------------------
- 真实本地 FastAPI + SQLite + Vite（跨域）：``live_admin_fastapi_base_url`` 与
  ``vite_live_admin_api_base_url``，定义并维护在 ``tests/test_visual_smoke.py``。
  本模块通过导入其 fixture 对象复用同一套真实服务与会话数据库。
- 认证沿用既有 E2E override：``live_admin_fastapi_base_url`` 里的
  ``get_current_user`` 读取 ``dy_e2e_role`` cookie，默认 ``admin``；门店权限用
  ``context.add_cookies`` 设置 ``dy_e2e_role=store``（store_ids=("store-1",)）。
  这是测试期认证注入，不代表真实登录链路。
- ``live_admin_fastapi_base_url`` 已内联 ``LiveSettlementStore`` 等价的最小合成
  种子（见 ``tests/test_visual_smoke.py`` 中 DYDATA-97 注释块），本模块不改生产
  代码、不写真实数据、不引入秘密。

主范围 14 个按钮到本模块用例的映射
----------------------------------
#1  /details 导出                      -> ``..._order_fee_details_button_...``
#2  /finance/promotion 模板            -> ``..._finance_fee_buttons_...``
#3  /finance/promotion 导出            -> ``..._finance_fee_buttons_...``
#4  /finance/management 模板           -> ``..._finance_fee_buttons_...``
#5  /finance/management 导出           -> ``..._finance_fee_buttons_...``
#6  /finance/orders/promotion 导出      -> ``..._finance_order_detail_buttons_...``
#7  /finance/orders/management 导出     -> ``..._finance_order_detail_buttons_...``
#8  /finance/stores 基础信息模板        -> ``..._finance_store_buttons_...``
#9  /finance/stores 基础信息导出        -> ``..._finance_store_buttons_...``
#10 /finance/stores SAP 差异导出        -> ``..._finance_store_buttons_...``
#11 /finance/stores SAP 确认模板        -> ``..._finance_store_buttons_...``
#12 /finance/imports 批次详情错误下载   -> ``..._import_error_file_downloads_real_batch_rows``
#13 导入面板错误下载（推广/管理/门店）  -> ``..._import_panel_error_file_downloads_real_bytes``
   代表实例：promotion 页的 PROMOTION_FACTORY_RESULT 面板 + stores 页的
   BASIC_INFO 面板（两个实例，覆盖厂家结果与基础信息两类模板）。
#14 /finance/disputes 导出              -> ``..._dispute_button_downloads_real_csv``

成功链路只使用真实本地 fixture；``page.route`` 仅用于明确的失败/网络错误分支
（函数名或 docstring 已标注），不用于任何成功断言。D2/D3/D4 的预期红测见
``test_dydata97_export_*filename*`` / ``*notices_report_empty`` /
``*feedback_visible*`` / ``*failure_is_visible*``。
"""

from __future__ import annotations

import csv
import re
from io import StringIO
from pathlib import Path
from urllib.parse import quote

import pytest
from playwright.sync_api import Browser, Download, Page, expect

# 复用 tests/test_visual_smoke.py 中已有的真实浏览器/本地 FastAPI fixture。
from test_visual_smoke import (  # noqa: E402
    browser,
    live_admin_fastapi_base_url,
    vite_live_admin_api_base_url,
)

API_PREFIX = "/api/v1"

# 服务端 CSV 表头契约（与 apps/api/dy_api/routes 内 DictWriter fieldnames 一致）。
INVOICE_EXPORT_FIELDS = [
    "invoice_id",
    "store_id",
    "store_name",
    "effective_sap_code",
    "statement_id",
    "statement_month",
    "settlement_batch_month",
    "statement_amount_cent",
    "confirmed_amount_cent",
    "invoice_number",
    "invoice_date",
    "invoice_amount_cent",
    "status",
    "rejection_reason",
    "registered_at",
    "factory_deduction_date",
    "factory_deduction_amount_cent",
    "processing_status",
]

ORDER_DETAIL_EXPORT_FIELDS = [
    "statement_entry_id",
    "statement_id",
    "store_id",
    "store_name",
    "sap_code",
    "billing_store_id",
    "billing_store_name",
    "service_store_name",
    "effective_sap_code",
    "statement_month",
    "fee_direction",
    "order_id",
    "coupon_id",
    "order_status",
    "coupon_status",
    "product_name",
    "product_type",
    "sku_id",
    "sku_name",
    "sale_channel",
    "sale_store_id",
    "sale_store_name",
    "verify_store_id",
    "verify_store_name",
    "sale_time",
    "verify_time",
    "received_amount_cent",
    "frozen_fee_base_cent",
    "actual_fee_rate",
    "frozen_fee_amount_cent",
    "refund_time",
    "adjustment_type",
    "row_type",
    "invoice_number",
    "submitted_at",
    "invoice_status",
    "settled_at",
    "settlement_date",
    "rejection_reason",
    "imported_at",
    "settlement_status",
    "factory_deduction_date",
    "factory_deduction_amount_cent",
]

STORE_EXPORT_FIELDS = [
    "store_id",
    "store_name",
    "store_maintained_sap_code",
    "finance_imported_sap_code",
    "effective_sap_code",
    "effective_sap_version",
    "effective_sap_updated_by",
    "effective_sap_updated_at",
    "sap_status",
    "statement_total_cent",
    "confirmed_amount_cent",
    "pending_invoice_amount_cent",
    "issued_amount_cent",
    "settled_or_deducted_amount_cent",
]

SAP_EXPORT_FIELDS = [
    "discrepancy_id",
    "store_id",
    "store_name",
    "store_maintained_sap_code",
    "finance_imported_sap_code",
    "effective_sap_code",
    "effective_sap_version",
    "effective_sap_updated_by",
    "effective_sap_updated_at",
    "sap_status",
    "discrepancy_detected_at",
]

DISPUTE_EXPORT_FIELDS = [
    "dispute_id",
    "statement_id",
    "store_id",
    "statement_month",
    "fee_direction",
    "dispute_type",
    "status",
    "disputed_amount_cent",
    "description",
    "contact_name",
    "contact_phone_masked",
    "linked_order_count",
    "linked_order_ids",
    "submitted_at",
    "resolution_note",
    "result_statement_id",
]

# order_fee_details_export_csv 使用中文表头。
ORDER_FEE_DETAIL_FIELDS = [
    "订单ID",
    "券ID",
    "费用方向",
    "原始发生月份",
    "销售月份",
    "核销月份",
    "调整入账月份",
    "规则匹配日",
    "销售门店",
    "核销门店",
    "SKU ID",
    "产品范围",
    "商品类型",
    "原始基数",
    "调整基数",
    "净基数",
    "费率",
    "原始费用",
    "调整费用",
    "调整后净额",
    "规则版本",
    "账单状态",
]

ERROR_FILE_FIELDS = [
    "rowNumber",
    "businessKey",
    "field",
    "originalValue",
    "reason",
    "suggestion",
]

# 四种财务导入模板表头（FINANCE_IMPORT_TEMPLATE_FIELDS）。
TEMPLATE_FIELDS = {
    "PROMOTION_FACTORY_RESULT": [
        "invoiceNumber",
        "reviewResult",
        "rejectionReason",
        "settlementDate",
        "settlementAmountCent",
    ],
    "MANAGEMENT_FACTORY_RESULT": [
        "storeId",
        "statementMonth",
        "storeName",
        "invoiceNumber",
        "invoiceDate",
        "deductionDate",
        "deductionAmountCent",
    ],
    "BASIC_INFO": ["storeId", "storeName", "sapCode", "importedAt"],
    "SAP_CONFIRMATION": [
        "storeId",
        "storeName",
        "financeInitialSap",
        "serviceStoreCode",
        "finalSapCode",
        "factoryConfirmationResult",
        "confirmedAt",
    ],
}

ERROR_BATCH_ID = "uat-error-import"
HISTORY_INVOICE_NUMBER = "12345678901234567800"

# 空结果下载用例：真实 200 + 仅表头，且页面必须给出 EMPTY 提示。
# stores 导出按门店而非账期筛选，用不存在的门店关键字制造空集。
EMPTY_CASES = [
    (
        "promotion-invoices",
        "/finance/promotion?month=2025-01",
        "导出当前筛选结果",
        INVOICE_EXPORT_FIELDS,
        "当前筛选无记录，已下载仅含表头的文件。",
    ),
    (
        "management-invoices",
        "/finance/management?month=2025-01",
        "导出当前筛选结果",
        INVOICE_EXPORT_FIELDS,
        "当前筛选无记录，已下载仅含表头的文件。",
    ),
    (
        "order-details",
        "/finance/orders/promotion?month=2025-01",
        "导出全部命中结果",
        ORDER_DETAIL_EXPORT_FIELDS,
        "筛选结果为空，已下载仅含表头的文件。",
    ),
    (
        "stores",
        f"/finance/stores?month=2025-01&q={quote('无此门店')}",
        "导出门店基础信息",
        STORE_EXPORT_FIELDS,
        "当前筛选无门店，已下载仅含表头的文件。",
    ),
    (
        "disputes",
        "/finance/disputes?month=2025-01",
        "导出账单异议",
        DISPUTE_EXPORT_FIELDS,
        "当前筛选无异议，已下载仅含表头的文件。",
    ),
]


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def download_rows(download: Download) -> list[list[str]]:
    """读取落地字节：非空、带 UTF-8 BOM、可用 utf-8-sig 解码。"""

    path = download.path()
    assert path is not None, "下载必须落地到磁盘后才能断言"
    raw = Path(path).read_bytes()
    assert raw, "下载文件不得为 0 字节"
    assert raw.startswith(b"\xef\xbb\xbf"), "服务端 CSV 必须带 UTF-8 BOM"
    text = raw.decode("utf-8-sig")
    assert text.strip(), "下载 CSV 至少应包含表头"
    return list(csv.reader(StringIO(text)))


def click_download(page: Page, button_name: str, timeout: int = 15000) -> Download:
    with page.expect_download(timeout=timeout) as info:
        page.get_by_role("button", name=button_name, exact=True).click()
    return info.value


def api_data(context, api_base: str, path: str, **params) -> dict:
    response = context.request.get(f"{api_base}{API_PREFIX}{path}", params=params)
    assert response.status == 200, f"{path} -> {response.status} {response.text()}"
    return response.json()["data"]


def admin_context(browser: Browser):
    return browser.new_context(viewport={"width": 1440, "height": 900})


def store_context(browser: Browser, api_base: str):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies(
        [{"name": "dy_e2e_role", "value": "store", "url": api_base}]
    )
    return context


def goto(page: Page, vite_base: str, path: str, heading: str) -> None:
    page.goto(f"{vite_base}{path}", wait_until="domcontentloaded")
    page.get_by_role("heading", name=heading, exact=True, level=1).wait_for(
        timeout=20000
    )


# --------------------------------------------------------------------------- #
# 成功链路：逐个点击 14 个按钮并核对真实落地字节
# --------------------------------------------------------------------------- #
def test_dydata97_export_finance_fee_buttons_download_real_csv(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """#2/#3 推广服务费、#4/#5 管理服务费：模板 + 列表/导出行数一致。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/promotion?month=2026-08", "推广服务费")

        # #2 下载推广服务费厂家导入模板
        template = click_download(page, "下载推广服务费厂家导入模板")
        rows = download_rows(template)
        assert rows == [TEMPLATE_FIELDS["PROMOTION_FACTORY_RESULT"]]

        # #3 导出当前筛选结果
        promotion = api_data(
            context,
            live_admin_fastapi_base_url,
            "/admin/finance/invoices",
            month="2026-08",
            feeDirection="PROMOTION",
            metricScope="MONTH",
            pageSize=50,
        )
        export = click_download(page, "导出当前筛选结果")
        rows = download_rows(export)
        assert rows[0] == INVOICE_EXPORT_FIELDS
        assert len(rows) - 1 == promotion["total"], (rows, promotion["total"])
        assert len(rows) > 1, "推广服务费导出不应只有表头"

        goto(page, vite_live_admin_api_base_url, "/finance/management?month=2026-08", "管理服务费")

        # #4 下载管理服务费厂家导入模板
        template = click_download(page, "下载管理服务费厂家导入模板")
        rows = download_rows(template)
        assert rows == [TEMPLATE_FIELDS["MANAGEMENT_FACTORY_RESULT"]]

        # #5 导出当前筛选结果（默认 includeHistory=false）
        management = api_data(
            context,
            live_admin_fastapi_base_url,
            "/admin/finance/invoices",
            month="2026-08",
            feeDirection="MANAGEMENT",
            metricScope="MONTH",
            pageSize=50,
        )
        export = click_download(page, "导出当前筛选结果")
        rows = download_rows(export)
        assert rows[0] == INVOICE_EXPORT_FIELDS
        assert len(rows) - 1 == management["total"], (rows, management["total"])
        assert len(rows) > 1, "管理服务费导出不应只有表头"
    finally:
        context.close()


def test_dydata97_export_finance_order_detail_buttons_download_real_csv(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """#6/#7 订单明细导出：冻结 entry 种子保证有可下载行。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        for direction, path, heading, order_id in (
            ("PROMOTION", "/finance/orders/promotion?month=2026-08", "推广服务费订单明细", "DY2026071900842"),
            ("MANAGEMENT", "/finance/orders/management?month=2026-08", "管理服务费订单明细", "DY20260622001935"),
        ):
            goto(page, vite_live_admin_api_base_url, path, heading)
            page.get_by_text(order_id, exact=True).first.wait_for(timeout=20000)
            listed = api_data(
                context,
                live_admin_fastapi_base_url,
                "/admin/finance/order-details",
                month="2026-08",
                feeDirection=direction,
                page=1,
                pageSize=50,
            )
            assert listed["total"] > 0, f"{direction} 订单明细种子缺失"
            export = click_download(page, "导出全部命中结果")
            rows = download_rows(export)
            assert rows[0] == ORDER_DETAIL_EXPORT_FIELDS
            assert len(rows) - 1 == listed["total"], (rows, listed["total"])
    finally:
        context.close()


def test_dydata97_export_finance_store_buttons_download_real_csv(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """#8/#9 门店基础信息、#10/#11 SAP 异议：模板表头 + 行数一致。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/stores?month=2026-08", "门店基础信息")

        # #8 下载基础信息导入模板
        template = click_download(page, "下载基础信息导入模板")
        assert download_rows(template) == [TEMPLATE_FIELDS["BASIC_INFO"]]

        # #9 导出门店基础信息
        stores = api_data(
            context,
            live_admin_fastapi_base_url,
            "/admin/finance/stores",
            month="2026-08",
            feeDirection="PROMOTION",
            metricScope="MONTH",
            pageSize=50,
        )
        export = click_download(page, "导出门店基础信息")
        rows = download_rows(export)
        assert rows[0] == STORE_EXPORT_FIELDS
        assert len(rows) - 1 == stores["total"], (rows, stores["total"])
        assert len(rows) > 1, "门店基础信息导出不应只有表头"

        # #10 导出 SAP 编码差异清单
        page.get_by_role("tab", name="SAP异议处理", exact=True).click()
        page.get_by_text("uat-store-1-sap-suggestion", exact=True).first.wait_for(
            timeout=20000
        )
        sap = api_data(
            context,
            live_admin_fastapi_base_url,
            "/admin/finance/stores",
            month="2026-08",
            feeDirection="PROMOTION",
            metricScope="MONTH",
            sapDiscrepanciesOnly="true",
            pageSize=50,
        )
        assert sap["total"] > 0, "SAP 差异种子缺失"
        export = click_download(page, "导出 SAP 编码差异清单")
        rows = download_rows(export)
        assert rows[0] == SAP_EXPORT_FIELDS
        assert len(rows) - 1 == sap["total"], (rows, sap["total"])

        # #11 下载 SAP 编码确认模板
        template = click_download(page, "下载 SAP 编码确认模板")
        assert download_rows(template) == [TEMPLATE_FIELDS["SAP_CONFIRMATION"]]
    finally:
        context.close()


def test_dydata97_export_order_fee_details_button_downloads_real_csv(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """#1 /details 导出：真实 fee result + current 种子驱动。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/details?storeId=store-1&month=2026-08", "推广费订单明细")
        page.get_by_text("DY2026071900842", exact=True).first.wait_for(timeout=20000)
        listed = api_data(
            context,
            live_admin_fastapi_base_url,
            "/order-fee-details",
            storeId="store-1",
            month="2026-08",
            feeDirection="PROMOTION",
            page=1,
            pageSize=50,
        )
        assert listed["total"] > 0, "order-fee-details 种子缺失"
        export = click_download(page, "导出")
        rows = download_rows(export)
        assert rows[0] == ORDER_FEE_DETAIL_FIELDS
        assert len(rows) - 1 == listed["total"], (rows, listed["total"])
        assert any("DY2026071900842" in cell for row in rows[1:] for cell in row)
    finally:
        context.close()


def test_dydata97_export_order_fee_details_store_scope_success_and_forbidden(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """#1 门店角色：授权范围内可导出；越权门店返回 403（真实 API）。"""

    context = store_context(browser, live_admin_fastapi_base_url)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/details?storeId=store-1&month=2026-08", "推广费订单明细")
        page.get_by_text("DY2026071900842", exact=True).first.wait_for(timeout=20000)
        export = click_download(page, "导出")
        rows = download_rows(export)
        assert rows[0] == ORDER_FEE_DETAIL_FIELDS
        assert len(rows) > 1

        forbidden = context.request.get(
            f"{live_admin_fastapi_base_url}{API_PREFIX}/order-fee-details",
            params={
                "storeId": "store-2",
                "month": "2026-08",
                "feeDirection": "PROMOTION",
            },
        )
        assert forbidden.status == 403, forbidden.text()
    finally:
        context.close()


def test_dydata97_export_import_error_file_downloads_real_batch_rows(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """#12 导入记录批次详情「下载全部错误」：合成错误批次 == 2 条错误行。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/imports", "导入记录")
        page.get_by_role("button", name=ERROR_BATCH_ID, exact=True).click()
        page.get_by_role("heading", name="批次详情", exact=True).wait_for(timeout=20000)
        detail = api_data(
            context,
            live_admin_fastapi_base_url,
            f"/admin/finance-imports/{ERROR_BATCH_ID}",
        )
        assert detail["errors"]["total"] == 2
        export = click_download(page, "下载全部错误")
        rows = download_rows(export)
        assert rows[0] == ERROR_FILE_FIELDS
        assert len(rows) - 1 == detail["errors"]["total"], (rows, detail["errors"])
        assert any("门店 ID 不存在" in row for row in rows[1:])
    finally:
        context.close()


def test_dydata97_export_import_panel_error_file_downloads_real_bytes(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """#13 导入面板错误下载：真实上传合成错误文件后下载全部错误。

    覆盖两个代表实例：
    - promotion 页 -> PROMOTION_FACTORY_RESULT 面板；
    - stores 页   -> BASIC_INFO 面板。
    成功链路使用真实本地 API 上传，不使用 page.route 伪造。
    """

    context = admin_context(browser)
    page = context.new_page()
    try:
        promotion_csv = (
            "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
            "25322000001784352160,UNKNOWN,,,\n"
        ).encode("utf-8")
        stores_csv = (
            "storeId,storeName,sapCode,importedAt\n"
            "store-1,深圳临港认证服务店,,2026-08-08T08:00:00+08:00\n"
        ).encode("utf-8")

        cases = [
            (
                "/finance/promotion?month=2026-08",
                "推广服务费",
                "导入推广服务费厂家信息",
                "promotion-errors.csv",
                promotion_csv,
            ),
            (
                "/finance/stores?month=2026-08",
                "门店基础信息",
                "导入门店基础信息",
                "stores-errors.csv",
                stores_csv,
            ),
        ]
        for path, heading, open_label, file_name, payload in cases:
            goto(page, vite_live_admin_api_base_url, path, heading)
            page.get_by_role("button", name=open_label, exact=True).click()
            page.get_by_role("heading", name="导入财务数据", exact=True, level=2).wait_for(
                timeout=20000
            )
            page.get_by_label("文件", exact=True).set_input_files(
                files=[{"name": file_name, "mimeType": "text/csv", "buffer": payload}]
            )
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/admin/finance-imports")
            ) as upload_info:
                page.get_by_role("button", name="上传并预览", exact=True).click()
            uploaded = upload_info.value.json()["data"]
            assert uploaded["errorRows"] >= 1, uploaded
            detail = api_data(
                context,
                live_admin_fastapi_base_url,
                f"/admin/finance-imports/{uploaded['batchId']}",
            )
            assert detail["errors"]["total"] == uploaded["errorRows"], (
                uploaded,
                detail["errors"],
            )
            export = click_download(page, "下载全部错误")
            rows = download_rows(export)
            assert rows[0] == ERROR_FILE_FIELDS
            assert len(rows) - 1 == detail["errors"]["total"], (
                rows,
                detail["errors"],
            )
    finally:
        context.close()


def test_dydata97_export_dispute_button_downloads_real_csv(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """#14 账单异议导出：未打开详情抽屉时的成功链路。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/disputes?month=2026-08", "账单异议")
        page.get_by_text("uat-dispute-001", exact=True).first.wait_for(timeout=20000)
        listed = api_data(
            context,
            live_admin_fastapi_base_url,
            "/admin/disputes",
            month="2026-08",
            page=1,
            pageSize=50,
        )
        assert listed["total"] > 0, "异议种子缺失"
        export = click_download(page, "导出账单异议")
        rows = download_rows(export)
        assert rows[0] == DISPUTE_EXPORT_FIELDS
        assert len(rows) - 1 == listed["total"], (rows, listed["total"])
    finally:
        context.close()


def test_dydata97_export_management_history_rows_in_list_and_export(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    """D1 真实 API 回归：管理费 includeHistory 开/关时列表与导出行集一致。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/management?month=2026-08", "管理服务费")
        page.get_by_text("12345678901234567891", exact=True).first.wait_for(timeout=20000)
        expect(page.get_by_text(HISTORY_INVOICE_NUMBER, exact=True)).to_have_count(0)

        base = dict(month="2026-08", feeDirection="MANAGEMENT", metricScope="MONTH", pageSize=50)
        without_history = api_data(
            context, live_admin_fastapi_base_url, "/admin/finance/invoices", **base
        )

        page.get_by_role("button", name="查看历史版本", exact=True).click()
        page.get_by_text(HISTORY_INVOICE_NUMBER, exact=True).first.wait_for(timeout=20000)
        with_history = api_data(
            context,
            live_admin_fastapi_base_url,
            "/admin/finance/invoices",
            includeHistory="true",
            **base,
        )
        assert with_history["total"] == without_history["total"] + 1, (
            without_history["total"],
            with_history["total"],
        )

        export = click_download(page, "导出当前筛选结果")
        rows = download_rows(export)
        assert rows[0] == INVOICE_EXPORT_FIELDS
        assert len(rows) - 1 == with_history["total"]
        assert any(HISTORY_INVOICE_NUMBER in row for row in rows[1:])

        page.get_by_role("button", name="仅看当前版本", exact=True).click()
        expect(page.get_by_text(HISTORY_INVOICE_NUMBER, exact=True)).to_have_count(0)
        export = click_download(page, "导出当前筛选结果")
        rows = download_rows(export)
        assert len(rows) - 1 == without_history["total"]
        assert not any(HISTORY_INVOICE_NUMBER in row for row in rows[1:])
    finally:
        context.close()


@pytest.mark.parametrize(
    "name,path,button,fields,notice",
    EMPTY_CASES,
    ids=[case[0] for case in EMPTY_CASES],
)
def test_dydata97_export_empty_finance_downloads_are_header_only(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    name: str,
    path: str,
    button: str,
    fields: list[str],
    notice: str,
) -> None:
    """空结果仍需 200 且仅含表头（冻结契约，绿色基线）。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        page.goto(f"{vite_live_admin_api_base_url}{path}", wait_until="domcontentloaded")
        page.locator("h1").wait_for(timeout=20000)
        export = click_download(page, button)
        rows = download_rows(export)
        assert rows == [fields], (name, rows)
    finally:
        context.close()


def test_dydata97_export_finance_admin_export_endpoints_reject_store_role(
    browser: Browser,
    live_admin_fastapi_base_url: str,
) -> None:
    """权限矩阵：store 角色对全部财务导出/模板/错误行端点返回 403（真实 API）。"""

    context = store_context(browser, live_admin_fastapi_base_url)
    try:
        endpoints = [
            ("/admin/finance/invoices/export", {"month": "2026-08", "feeDirection": "PROMOTION", "metricScope": "MONTH"}),
            ("/admin/finance/invoices/export", {"month": "2026-08", "feeDirection": "MANAGEMENT", "metricScope": "MONTH"}),
            ("/admin/finance/order-details/export", {"month": "2026-08", "feeDirection": "PROMOTION"}),
            ("/admin/finance/order-details/export", {"month": "2026-08", "feeDirection": "MANAGEMENT"}),
            ("/admin/finance/stores/export", {"month": "2026-08", "feeDirection": "PROMOTION", "metricScope": "MONTH"}),
            ("/admin/finance/stores/sap-discrepancies/export", {"month": "2026-08", "feeDirection": "PROMOTION", "metricScope": "MONTH"}),
            ("/admin/finance-imports/templates/BASIC_INFO", {}),
            ("/admin/finance-imports/templates/PROMOTION_FACTORY_RESULT", {}),
            (f"/admin/finance-imports/{ERROR_BATCH_ID}/error-file", {}),
            ("/admin/disputes/export", {"month": "2026-08"}),
        ]
        for path, params in endpoints:
            response = context.request.get(
                f"{live_admin_fastapi_base_url}{API_PREFIX}{path}", params=params
            )
            assert response.status == 403, (path, response.status, response.text())
            detail = response.json().get("detail")
            code = detail.get("code") if isinstance(detail, dict) else None
            assert code in {"DATA_SCOPE_FORBIDDEN", "PAGE_ACCESS_FORBIDDEN"}, (path, detail)
    finally:
        context.close()


# --------------------------------------------------------------------------- #
# D2 预期红测：跨域响应头不可读 -> 文件名/EMPTY 语义错误
# --------------------------------------------------------------------------- #
def test_dydata97_export_finance_fee_filenames_match_content_disposition(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D2 红测：#2-#5 建议文件名必须来自服务端 Content-Disposition。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/promotion?month=2026-08", "推广服务费")
        assert click_download(page, "下载推广服务费厂家导入模板").suggested_filename == (
            "finance-import-promotion_factory_result-template.csv"
        )
        assert re.fullmatch(
            r"finance-promotion-invoices-\d{4}-\d{2}-\d{2}\.csv",
            click_download(page, "导出当前筛选结果").suggested_filename,
        )

        goto(page, vite_live_admin_api_base_url, "/finance/management?month=2026-08", "管理服务费")
        assert click_download(page, "下载管理服务费厂家导入模板").suggested_filename == (
            "finance-import-management_factory_result-template.csv"
        )
        assert re.fullmatch(
            r"finance-management-invoices-\d{4}-\d{2}-\d{2}\.csv",
            click_download(page, "导出当前筛选结果").suggested_filename,
        )
    finally:
        context.close()


def test_dydata97_export_finance_order_detail_filenames_match_content_disposition(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D2 红测：#6/#7 订单明细导出文件名必须来自服务端响应头。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        for path, heading in (
            ("/finance/orders/promotion?month=2026-08", "推广服务费订单明细"),
            ("/finance/orders/management?month=2026-08", "管理服务费订单明细"),
        ):
            goto(page, vite_live_admin_api_base_url, path, heading)
            assert re.fullmatch(
                r"finance-order-details-\d{4}-\d{2}-\d{2}\.csv",
                click_download(page, "导出全部命中结果").suggested_filename,
            )
    finally:
        context.close()


def test_dydata97_export_finance_store_filenames_match_content_disposition(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D2 红测：#8-#11 门店模板/导出文件名必须来自服务端响应头。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/stores?month=2026-08", "门店基础信息")
        assert click_download(page, "下载基础信息导入模板").suggested_filename == (
            "finance-import-basic_info-template.csv"
        )
        assert re.fullmatch(
            r"finance-stores-\d{4}-\d{2}-\d{2}\.csv",
            click_download(page, "导出门店基础信息").suggested_filename,
        )
        page.get_by_role("tab", name="SAP异议处理", exact=True).click()
        page.get_by_text("uat-store-1-sap-suggestion", exact=True).first.wait_for(
            timeout=20000
        )
        assert re.fullmatch(
            r"finance-sap-discrepancies-\d{4}-\d{2}-\d{2}\.csv",
            click_download(page, "导出 SAP 编码差异清单").suggested_filename,
        )
        assert click_download(page, "下载 SAP 编码确认模板").suggested_filename == (
            "finance-import-sap_confirmation-template.csv"
        )
    finally:
        context.close()


def test_dydata97_export_order_fee_details_filename_matches_content_disposition(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D2 红测：#1 /details 导出文件名必须来自服务端响应头。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/details?storeId=store-1&month=2026-08", "推广费订单明细")
        page.get_by_text("DY2026071900842", exact=True).first.wait_for(timeout=20000)
        assert re.fullmatch(
            r"order-fee-details-\d{4}-\d{2}-\d{2}\.csv",
            click_download(page, "导出").suggested_filename,
        )
    finally:
        context.close()


def test_dydata97_export_import_error_filename_matches_content_disposition(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D2 红测：#12 错误行下载文件名必须来自服务端响应头。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/imports", "导入记录")
        page.get_by_role("button", name=ERROR_BATCH_ID, exact=True).click()
        page.get_by_role("heading", name="批次详情", exact=True).wait_for(timeout=20000)
        assert click_download(page, "下载全部错误").suggested_filename == (
            f"finance-import-errors-{ERROR_BATCH_ID}.csv"
        )
    finally:
        context.close()


def test_dydata97_export_dispute_filename_matches_content_disposition(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D2 红测：#14 异议导出文件名必须来自服务端响应头。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/disputes?month=2026-08", "账单异议")
        page.get_by_text("uat-dispute-001", exact=True).first.wait_for(timeout=20000)
        assert re.fullmatch(
            r"finance-disputes-\d{4}-\d{2}-\d{2}\.csv",
            click_download(page, "导出账单异议").suggested_filename,
        )
    finally:
        context.close()


@pytest.mark.parametrize(
    "name,path,button,fields,notice",
    EMPTY_CASES,
    ids=[case[0] for case in EMPTY_CASES],
)
def test_dydata97_export_empty_finance_download_notices_report_empty(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    name: str,
    path: str,
    button: str,
    fields: list[str],
    notice: str,
) -> None:
    """D2 红测：X-Export-Result=EMPTY 必须驱动「仅含表头」提示。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        page.goto(f"{vite_live_admin_api_base_url}{path}", wait_until="domcontentloaded")
        page.locator("h1").wait_for(timeout=20000)
        click_download(page, button)
        expect(page.get_by_text(notice, exact=True)).to_be_visible(timeout=5000)
    finally:
        context.close()


# --------------------------------------------------------------------------- #
# D3 预期红测：异议详情抽屉吞掉导出反馈
# --------------------------------------------------------------------------- #
def test_dydata97_export_dispute_feedback_visible_after_detail_opened(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D3 红测：打开异议详情后再导出，成功反馈仍必须可见。"""

    context = admin_context(browser)
    page = context.new_page()
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/disputes?month=2026-08", "账单异议")
        page.get_by_text("uat-dispute-001", exact=True).first.wait_for(timeout=20000)
        page.get_by_role("button", name="处理", exact=True).click()
        expect(page.get_by_role("complementary", name="账单异议详情")).to_be_visible(
            timeout=20000
        )
        export = click_download(page, "导出账单异议")
        assert download_rows(export)[0] == DISPUTE_EXPORT_FIELDS
        expect(
            page.get_by_text("已导出账单异议：", exact=False)
        ).to_be_visible(timeout=5000)
    finally:
        context.close()


def test_dydata97_export_dispute_failure_uses_alert_role(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D3 红测：异议导出失败必须用 role=alert 呈现（失败分支，单独 mock）。"""

    context = admin_context(browser)
    page = context.new_page()
    # 非成功链路：人为中断导出请求，验证失败呈现，不代表真实接口契约。
    page.route("**/api/v1/admin/disputes/export*", lambda route: route.abort())
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/disputes?month=2026-08", "账单异议")
        page.get_by_text("uat-dispute-001", exact=True).first.wait_for(timeout=20000)
        page.get_by_role("button", name="处理", exact=True).click()
        expect(page.get_by_role("complementary", name="账单异议详情")).to_be_visible(
            timeout=20000
        )
        page.get_by_role("button", name="导出账单异议", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("失败", timeout=5000)
    finally:
        context.close()


# --------------------------------------------------------------------------- #
# D4 预期红测：错误行下载无异常处理 / 无反馈
# --------------------------------------------------------------------------- #
def test_dydata97_export_import_error_failure_is_visible_in_imports_page(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D4 红测：#12 错误行下载失败必须有可见失败提示（失败分支，单独 mock）。"""

    context = admin_context(browser)
    page = context.new_page()
    # 非成功链路：人为中断下载请求。
    page.route(
        f"**/api/v1/admin/finance-imports/{ERROR_BATCH_ID}/error-file*",
        lambda route: route.abort(),
    )
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/imports", "导入记录")
        page.get_by_role("button", name=ERROR_BATCH_ID, exact=True).click()
        page.get_by_role("heading", name="批次详情", exact=True).wait_for(timeout=20000)
        page.get_by_role("button", name="下载全部错误", exact=True).click()
        expect(page.get_by_text(re.compile("下载失败|下载全部错误失败"))).to_be_visible(
            timeout=5000
        )
    finally:
        context.close()


def test_dydata97_export_import_panel_error_failure_is_visible_after_abort(
    browser: Browser,
    vite_live_admin_api_base_url: str,
) -> None:
    """D4 红测：#13 导入面板错误行下载失败必须有可见失败提示（失败分支，单独 mock）。"""

    context = admin_context(browser)
    page = context.new_page()
    # 非成功链路：真实上传后人为中断错误行下载请求。
    page.route(
        "**/api/v1/admin/finance-imports/*/error-file*",
        lambda route: route.abort(),
    )
    try:
        goto(page, vite_live_admin_api_base_url, "/finance/promotion?month=2026-08", "推广服务费")
        page.get_by_role("button", name="导入推广服务费厂家信息", exact=True).click()
        page.get_by_role("heading", name="导入财务数据", exact=True, level=2).wait_for(
            timeout=20000
        )
        payload = (
            "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
            "25322000001784352160,UNKNOWN,,,\n"
        ).encode("utf-8")
        page.get_by_label("文件", exact=True).set_input_files(
            files=[{"name": "panel-errors.csv", "mimeType": "text/csv", "buffer": payload}]
        )
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/admin/finance-imports")
        ):
            page.get_by_role("button", name="上传并预览", exact=True).click()
        page.get_by_role("button", name="下载全部错误", exact=True).click()
        expect(page.get_by_text(re.compile("下载失败|下载全部错误失败"))).to_be_visible(
            timeout=5000
        )
    finally:
        context.close()
