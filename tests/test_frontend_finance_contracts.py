from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"


def source(relative_path: str) -> str:
    return (WEB / relative_path).read_text(encoding="utf-8")


def test_fee_pages_follow_the_frozen_module_order_and_headers() -> None:
    page = source("pages/FinanceFeePage.tsx")
    client = source("api/client.ts")
    render = page.split("  return (", 1)[1]

    assert "finance-heading__actions" in page
    for action in [
        "下载推广服务费厂家导入模板",
        "导入推广服务费厂家信息",
        "下载管理服务费厂家导入模板",
        "导入管理服务费厂家信息",
    ]:
        assert action in page
    assert "downloadFinanceImportTemplate" in page + client
    assert "downloadFinanceInvoices" in page + client
    assert render.index("finance-metric-grid") < render.index("<FinanceImportActionPanel")
    assert render.index("<FinanceImportActionPanel") < render.index("推广费发票明细")

    for metric in [
        "推广费总额",
        "已确认金额",
        "待开票金额",
        "已开票金额",
        "审核通过已结算金额",
        "管理费总额",
    ]:
        assert metric in page
    assert "finance-metric-grid--four" in page
    assert "metrics?.statementTotalCent ?? 0" not in page

    for header in [
        "门店",
        "有效 SAP",
        "账期",
        "推广费总额",
        "管理费总额",
        "已确认金额",
        "数电专票号码",
        "提交成功时间",
        "结算归属月",
        "发票审核状态",
        "审核原因",
        "发票金额",
        "开票时间",
        "状态",
    ]:
        assert f'title: "{header}"' in page
    assert "/finance/orders/promotion" in page
    assert "/finance/orders/management" in page

    status_options = re.search(
        r'const statusOptions = feeDirection === "PROMOTION"\s*\?\s*\[(.*?)\]\s*:\s*\[(.*?)\];',
        page,
        re.DOTALL,
    )
    assert status_options is not None
    promotion_options, management_options = status_options.groups()
    assert "PENDING_INVOICE" not in promotion_options
    assert "PENDING_INVOICE" in management_options


def test_order_details_use_the_confirmed_two_row_filters_and_full_table() -> None:
    page = source("pages/FinanceOrderDetailsPage.tsx")
    types = source("types/dashboard.ts")
    labels = source("utils/userFacingLabels.ts")

    for contract in [
        "q: string",
        "settlementStatus: string",
        'className="finance-order-filters__row finance-order-filters__row--primary"',
        'className="finance-order-filters__row finance-order-filters__row--secondary"',
        "应用筛选",
        "重置筛选",
    ]:
        assert contract in page
    for query_field in ["q?: string", "settlementStatus?: string"]:
        assert query_field in types

    for header in [
        "账期",
        "账单归属门店",
        "服务店名称",
        "有效 SAP",
        "订单",
        "券",
        "状态",
        "商品",
        "SKU ID",
        "商品类型",
        "销售渠道",
        "销售门店",
        "核销门店",
        "销售时间",
        "核销时间",
        "退款时间",
        "实收金额",
        "实际费率",
        "对应发票号码",
        "发票提交时间",
        "发票审核状态",
        "发票结算日期",
        "审核不通过原因",
    ]:
        assert f'title: "{header}"' in page
    for field in [
        "row.billingStoreName",
        "row.serviceStoreName",
        "row.effectiveSapCode",
        "row.productType",
        "row.settlementDate",
    ]:
        assert field in page
    assert "const invoiceStatusOptions = feeDirection === \"PROMOTION\"" in page
    assert 'APPROVED_SETTLED", label: "已开票"' in page
    assert 'REJECTED_REUPLOAD", label: "审核不通过"' in page
    assert "displayOrderInvoiceStatus(row.invoiceStatus, row.feeDirection)" in page
    assert 'USED: "已核销"' in labels


def test_store_page_has_base_and_sap_contract_actions_and_single_correction() -> None:
    page = source("pages/FinanceStoresPage.tsx")
    client = source("api/client.ts")
    types = source("types/dashboard.ts")

    assert 'import { Tabs } from "../components/SelectionControls";' in page
    for label in [
        "基础信息",
        "SAP异议处理",
        "下载基础信息导入模板",
        "导出门店基础信息",
        "导入门店基础信息",
        "导出 SAP 编码差异清单",
        "下载 SAP 编码确认模板",
        "导入最终确认 SAP 编码",
        "单条矫正有效 SAP",
    ]:
        assert label in page
    for header in [
        "门店ID（所属账户关联poi-id）",
        "服务店名称",
        "有效SAP编码",
        "最近导入时间",
        "SAP确认状态",
        "异议编号",
        "门店",
        "有效 SAP",
        "当前状态",
        "检测时间",
        "操作",
    ]:
        assert f'title: "{header}"' in page
    for function_name in [
        "downloadFinanceImportTemplate",
        "downloadFinanceStores",
        "downloadFinanceSapDiscrepancies",
        "correctFinanceStoreSap",
    ]:
        assert function_name in page + client
    for field in [
        "storeMaintainedSapCode",
        "financeImportedSapCode",
        "effectiveSapCode",
        "effectiveSapVersion",
        "effectiveSapUpdatedBy",
        "effectiveSapUpdatedAt",
    ]:
        assert field in types
    assert "submitSapSuggestion" not in page
    assert "decideSapSuggestion" not in page
    assert 'sapDiscrepanciesOnly: tab === "sap"' in page
    assert "[month, feeDirection, metricScope, query, tab]" in page


def test_disputes_use_persisted_async_detection_without_fake_progress() -> None:
    page = source("pages/FinanceDisputesPage.tsx")
    client = source("api/client.ts")
    types = source("types/dashboard.ts")
    labels = source("utils/userFacingLabels.ts")

    for function_name in [
        "downloadFinanceDisputes",
        "startFinanceDisputeDetection",
        "fetchFinanceDisputeDetection",
    ]:
        assert function_name in page + client
    assert "useEffect" in page
    assert "setTimeout" in page
    assert "启动系统检测" in page
    assert "查看检测进度" in page
    assert "重新检测" in page
    for field in [
        "latestDetection",
        "progressPercent",
        "resultSummary",
        "failureReason",
    ]:
        assert field in page + types
    assert "displayFinanceDisputeDetectionStatus" in page + labels
    assert "progressPercent +" not in page
    assert "Math.min(100" not in page
    assert 'type="file"' not in page
    assert "上传证明材料" not in page

    for metric in ["账单金额异议", "系统检测中", "待管理员处理", "今日已完成"]:
        assert metric in page
    for header in [
        "异议编号",
        "异议类型",
        "门店",
        "费用方向 / 账期",
        "异议金额",
        "系统检测结果",
        "状态",
        "操作",
    ]:
        assert f'title: "{header}"' in page


def test_dispute_transitions_follow_server_state_machine_and_reuse_one_idempotency_key() -> None:
    page = source("pages/FinanceDisputesPage.tsx")
    client = source("api/client.ts")

    for current_status in ["PENDING", "IN_REVIEW", "PENDING_ADMIN_APPROVAL"]:
        assert f'{current_status}:' in page
    assert "transitionOptionsFor(selected.status)" in page
    assert "transitionOptions.length > 0" in page
    assert "transitionKey" in page
    assert "setTransitionKey(crypto.randomUUID())" in page
    assert "transitionFinanceDispute(" in page
    assert "selected.disputeId" in page
    assert "transitionKey" in client
    assert '"Idempotency-Key": transitionKey' in client


def test_detection_and_management_correction_reuse_keys_only_for_identical_retries() -> None:
    disputes = source("pages/FinanceDisputesPage.tsx")
    fees = source("pages/FinanceFeePage.tsx")

    assert "detectionKey" in disputes
    assert "selected.disputeId, detectionKey" in disputes
    assert "selected.disputeId, crypto.randomUUID()" not in disputes
    assert "updateCorrection" in fees
    assert "idempotencyKey: crypto.randomUUID()" in fees
    assert "correction.idempotencyKey" in fees


def test_finance_sibling_routes_remount_direction_specific_pages() -> None:
    app = source("App.tsx")

    for key in [
        'key="finance-fee-promotion"',
        'key="finance-fee-management"',
        'key="finance-orders-promotion"',
        'key="finance-orders-management"',
    ]:
        assert key in app


def test_management_correction_blocks_invalid_fields_before_api_submission() -> None:
    fees = source("pages/FinanceFeePage.tsx")

    assert "managementCorrectionValidationError" in fees
    assert "发票号码必须为 20 位数字" in fees
    assert "发票金额与厂家扣款金额必须为相同的正整数分" in fees
    assert "更正原因不得超过 1000 字" in fees
    assert "correctionValidationError" in fees
    assert "!correctionValidationError" in fees


def test_management_pending_rows_keep_nullable_invoice_fields_read_only() -> None:
    fees = source("pages/FinanceFeePage.tsx")
    types = source("types/dashboard.ts")

    invoice_row = types.split("export interface FinanceInvoiceRow", 1)[1].split(
        "export interface FinanceInvoiceListData", 1
    )[0]
    for field in [
        "invoiceId: string | null",
        "effectiveSapCode: string | null",
        "statementAmountCent: number",
        "confirmedAmountCent: number | null",
        "versionNo: number | null",
        "isCurrent: boolean | null",
        "invoiceNumber: string | null",
        "invoiceDate: string | null",
        "invoiceAmountCent: number | null",
        "registeredAt: string | null",
        "settlementBatchMonth: string | null",
    ]:
        assert field in invoice_row

    assert 'row.invoiceNumber ?? "—"' in fees
    assert 'typeof row.invoiceAmountCent === "number"' in fees
    assert 'row.invoiceDate ?? "—"' in fees
    assert "row.effectiveSapCode" in fees
    assert "row.statementAmountCent" in fees
    assert "row.settlementBatchMonth" in fees
    assert 'row.invoiceId && row.isCurrent ? "更正" : undefined' in fees
    assert "!row.invoiceId" in fees
    assert "!row.isCurrent" in fees


def test_imports_page_keeps_uploads_out_and_matches_the_frozen_log_order() -> None:
    page = source("pages/FinanceImportsPage.tsx")
    render = page.split("  return (", 1)[1]

    assert "整批成功或整批失败" in page
    assert "仅保存导入日志，不保存原始上传文件" in page
    assert "历史导入日志" in page
    assert 'className="records-section"' in page
    assert render.index("finance-import-policy") < render.index("records-section")
    for header in [
        "导入编号",
        "导入类型",
        "源文件名称（仅日志）",
        "记录数",
        "状态",
        "操作人",
        "导入时间",
        "结果摘要",
    ]:
        assert f'title: "{header}"' in page
    assert "row.resultSummary" in page
    assert "uploadFinanceImport" not in page
    assert "commitFinanceImport" not in page


def test_import_commit_reuses_one_idempotency_key_until_preview_changes() -> None:
    panel = source("components/FinanceImportActionPanel.tsx")

    assert "commitKey" in panel
    assert "setCommitKey(crypto.randomUUID())" in panel
    assert "payload, commitKey" in panel
    assert "payload, crypto.randomUUID()" not in panel
    assert "fileInputVersion" in panel
    assert "finance-import-file-${fileInputVersion}" in panel


def test_finance_contract_has_explicit_responsive_layouts_for_three_viewports() -> None:
    styles = source("styles.css")

    for selector in [
        ".finance-heading__actions",
        ".finance-order-filters__row--primary",
        ".finance-order-filters__row--secondary",
        ".finance-order-filter-actions",
        ".finance-dispute-detection",
        ".finance-detail-drawer",
    ]:
        assert selector in styles
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in styles
    assert "min-width: 0;" in styles
    assert "overflow-x: auto;" in styles
    assert "@media (max-width: 1100px)" in styles
    assert "@media screen and (max-width: 760px)" in styles


def test_frontend_client_uses_consistent_admin_finance_endpoints() -> None:
    client = source("api/client.ts")

    for endpoint in [
        "/admin/finance-imports/templates/",
        "/admin/finance/invoices/export",
        "/admin/finance/stores/export",
        "/admin/finance/stores/sap-discrepancies/export",
        "/sap-corrections",
        "/admin/disputes/export",
        "/detections",
    ]:
        assert endpoint in client


def test_finance_row_actions_remain_available_in_mobile_cards_and_by_keyboard() -> None:
    table = source("components/DataTable.tsx")
    fees = source("pages/FinanceFeePage.tsx")
    orders = source("pages/FinanceOrderDetailsPage.tsx")

    assert "onRowAction" in table
    assert "rowActionLabel" in table
    assert "data-table-mobile-card__action" in table
    assert 'event.key === "Enter" || event.key === " "' in table
    assert 'rowActionLabel={(row) => row.invoiceId && row.isCurrent ? "更正" : undefined}' in fees
    assert 'rowActionLabel={() => "查看完整字段"}' in orders
