import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = REPO_ROOT / "apps" / "web" / "src"
API_SRC = REPO_ROOT / "apps" / "api" / "dy_api"
DESIGN_SYSTEM = REPO_ROOT / "docs" / "design-system"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_source(relative_path: str) -> str:
    return read(WEB_SRC / relative_path)


def test_internal_production_values_use_shared_safe_presenters() -> None:
    labels = read_source("utils/userFacingLabels.ts")

    required_presenters = [
        "displayOrderStatus",
        "displayFollowUpTimingState",
        "displayClueReason",
        "displaySyncJobName",
        "displaySyncPhaseName",
        "displaySyncFailureReason",
        "displayWorkerMode",
        "displayAllocationStrategy",
        "displayAllocationDecisionStatus",
        "displayAllocationCycleStatus",
        "displayAllocationEventType",
        "displayAllocationExecutionMode",
        "displayAllocationCycleType",
        "displayUserRole",
        "displayFeeDirection",
        "displayFinanceInvoiceStatus",
        "displayFinanceImportType",
        "displayFinanceImportScenario",
        "displayFinanceDisputeStatus",
        "displayFinanceDisputeType",
    ]
    for presenter in required_presenters:
        assert f"export function {presenter}" in labels

    for mapping in [
        'fulfilling: "履约中"',
        'verified: "已核销"',
        'active: "跟进有效期内"',
        'protected: "跟进保护期内"',
        'orders: "订单数据同步"',
        'admin: "管理员"',
    ]:
        assert mapping in labels

    assert "return labels[value] ?? value" not in labels
    assert "return labels[normalized] ?? normalized" not in labels
    assert "console.warn" in labels


def test_clue_detail_does_not_render_raw_order_timing_or_reason_values() -> None:
    source = read_source("pages/ClueCenterPage.tsx")

    for presenter in [
        "displayOrderStatus",
        "displayFollowUpTimingState",
        "displayClueReason",
    ]:
        assert presenter in source

    assert "return labels[value] ?? value" not in source
    assert "row.status_reason ??" not in source
    assert "[record.timing_state, record.status_reason]" not in source
    assert "labelFor(activeDetailRound.order_current_status" not in source


def test_admin_and_dashboard_pages_do_not_expose_audited_internal_terms() -> None:
    dashboard_api = read(API_SRC / "routes" / "dashboard.py")
    client = read_source("api/client.ts")
    sales = read_source("pages/SalesDashboardPage.tsx")
    sync = read_source("pages/AdminSyncPage.tsx")
    allocation = read_source("pages/AdminClueAllocationPage.tsx")
    feedback = read_source("pages/AdminFeedbackPage.tsx")
    home = read_source("pages/HomePage.tsx")

    assert "sale_time 到 verify_time" not in sales
    assert "按 sale_time 归属月份" not in sales
    assert "按 verify_time 归属月份" not in sales
    assert "按 order_id 去重" not in sales

    for internal_term in [
        "按 order_id 去重",
        "is_refund_excluded=true",
        "sale_time 到 verify_time",
    ]:
        assert internal_term not in client
        assert internal_term not in dashboard_api

    for raw_render in [
        "`${phase.name}",
        "job.job_name }",
        "job.error_message || phaseSummary(job)",
        "? workerStatus.latest_failure.error_message",
        "return mode ||",
        'setStatusText("同步配置已保存，worker',
        ">Worker 状态<",
    ]:
        assert raw_render not in sync
    for presenter in [
        "displaySyncJobName",
        "displaySyncPhaseName",
        "displaySyncFailureReason",
        "displayWorkerMode",
    ]:
        assert presenter in sync

    for raw_render in [
        "poolReasonLabels[reason] ?? reason",
        "strategyLabels[decision.strategy_type] ?? decision.strategy_type",
        "decisionStatusLabels[decision.decision_status] ?? decision.decision_status",
        "render: (cycle) => cycle.status",
        "render: (row) => row.event_type",
        "首次跟进 SLA",
    ]:
        assert raw_render not in allocation
    for presenter in [
        "displayAllocationStrategy",
        "displayAllocationDecisionStatus",
        "displayAllocationCycleStatus",
        "displayAllocationEventType",
    ]:
        assert presenter in allocation

    assert "{row.user_role}" not in feedback
    assert "displayUserRole" in feedback
    assert "MVP" not in home
    assert "月度明细和 SKU 分账规则管理" not in home


def test_business_tsx_does_not_directly_render_high_risk_internal_fields() -> None:
    direct_render = re.compile(
        r">\s*\{[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\."
        r"(?:status_reason|timing_state|job_name|event_type|user_role|"
        r"execution_mode|strategy_type|decision_status)\}\s*<"
    )
    offenders: list[str] = []

    for path in WEB_SRC.rglob("*.tsx"):
        if direct_render.search(read(path)):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_required_acronyms_are_explained_at_first_user_facing_use() -> None:
    auth = read_source("pages/AuthPage.tsx")
    accounts = read_source("pages/AdminAccountsPage.tsx")
    sync = read_source("pages/AdminSyncPage.tsx")
    sku_rules = read_source("pages/AdminSkuRulesPage.tsx")

    assert "门店位置编号（POI ID）" in auth
    assert "门店位置编号（POI ID）" in accounts
    assert "所属账户ID" not in accounts
    assert "门店位置数据（POI）" in sync
    assert "商品规格（SKU）" in sku_rules


def test_secondary_navigation_matches_v02_flat_text_contract() -> None:
    shell = read_source("components/Shell.tsx")
    styles = read_source("styles.css")

    render_secondary = shell.split("const renderSecondaryNav", 1)[1].split(
        "const handleFeedbackSubmit", 1
    )[0]
    active_matcher = shell.split("function activeSecondaryNavHref", 1)[1].split(
        "function roleLabel", 1
    )[0]
    assert "<SolarIcon" not in render_secondary
    assert "right.href.length - left.href.length" in active_matcher
    assert "normalizedPath.startsWith(`${item.href}/`)" in active_matcher
    assert "const active = item.href === activeSecondaryHref;" in render_secondary

    item_rule = re.search(
        r"\.workspace-subnav a \{(?P<body>.*?)\n\}", styles, re.DOTALL
    )
    active_rule = re.search(
        r'\.workspace-subnav a\[aria-current="page"\] \{(?P<body>.*?)\n\}',
        styles,
        re.DOTALL,
    )
    assert item_rule and active_rule
    assert "min-height: var(--control-height);" in item_rule.group("body")
    assert "border: 0;" in item_rule.group("body")
    assert "border-bottom: 2px solid transparent;" in item_rule.group("body")
    assert "border-radius" not in item_rule.group("body")
    assert "box-shadow" not in active_rule.group("body")
    assert "border-bottom-color: var(--brand-orange);" in active_rule.group("body")
    assert ".workspace-subnav a:focus-visible" in styles


def test_tertiary_navigation_uses_shared_route_links() -> None:
    component = read_source("components/TertiaryNav.tsx")
    allocation = read_source("pages/AdminClueAllocationPage.tsx")
    app = read_source("App.tsx")
    styles = read_source("styles.css")

    assert '<nav aria-label={label} className="tertiary-nav">' in component
    assert "<a" in component
    assert "href={item.href}" in component
    assert 'aria-current={item.current ? "page" : undefined}' in component

    assert "<TertiaryNav" in allocation
    assert "aria-pressed" not in allocation
    assert "setActiveSubview" not in allocation
    for path in [
        "/admin/clue-allocation/rules",
        "/admin/clue-allocation/trial",
        "/admin/clue-allocation/records",
        "/admin/clue-allocation/headquarters",
    ]:
        assert path in allocation or path in app

    assert ".tertiary-nav__item" in styles
    assert "border-bottom: 2px solid transparent;" in styles
    assert "border-bottom-color: var(--brand-orange);" in styles
    assert ".tertiary-nav__item:focus-visible" in styles
    tertiary_styles = styles.split(".tertiary-nav {", 1)[1].split(
        ".clue-allocation-control__actions", 1
    )[0]
    assert "var(--blue)" not in tertiary_styles
    assert "font-weight: 700;" in tertiary_styles


def test_design_system_records_copy_favicon_and_navigation_guardrails() -> None:
    tokens = json.loads(read(DESIGN_SYSTEM / "tokens.json"))
    html = read(DESIGN_SYSTEM / "index.html")
    readme = read(DESIGN_SYSTEM / "README.md")

    secondary = tokens["components"]["navigation"]["secondary"]
    assert secondary["structure"] == "nav > a"
    assert secondary["iconRule"] == "text-only; icons belong to primary navigation and explicit actions"
    assert secondary["desktopItemHeight"] == "38px"
    assert secondary["mobileMinTarget"] == "44px"
    assert secondary["activeIndicator"] == "2px solid #fe5205"
    assert secondary["focusVisible"] == "global focus ring"
    assert (
        secondary["activeRouteRule"]
        == "exact or nested prefix; resolve overlaps to the longest href; exactly one aria-current=page"
    )

    filter_bar = tokens["components"]["filterBar"]
    assert filter_bar["desktopBehavior"] == "Always expanded on desktop."
    assert (
        filter_bar["collapseActionVisibility"]
        == "Only visible when the filter panel can actually collapse; hidden in always-expanded layouts."
    )

    favicon = tokens["components"]["navigation"]["favicon"]
    assert favicon["file"] == "apps/web/public/business-engine-icon-v2.svg"
    assert favicon["lightBrowserChrome"] == "#d63b00"
    assert favicon["darkBrowserChrome"] == "#fe5205"
    assert favicon["outerTile"] == "none"
    assert "static brand asset" in tokens["tokens"]["icon"]["brandAssetException"]
    internal_values = tokens["contentGuidelines"]["internalValues"]
    assert "never render the raw value" in internal_values["unknownFallback"]
    assert "developer logs" in internal_values["logging"]
    assert "backend error messages" in internal_values["mapping"]
    assert "open api returned 0 rows" in internal_values["forbiddenExamples"]

    for document in [html, readme]:
        assert "内部生产值不得直接展示" in document
        assert "未知状态 / 未知类型 / 未知原因" in document
        assert "二级导航不使用图标" in document
        assert "父子路径同时命中时，只允许最长路径对应的导航项进入当前页状态" in document
        assert "收起筛选只在筛选面板确实可折叠的窄屏布局中显示" in document
        assert "浏览器标签图标" in document
        assert "后端错误" in document

    favicon_demo = html.split("浏览器标签图标（BrowserFavicon）", 1)[1].split(
        "用户可见值（ContentPresenter）", 1
    )[0]
    assert 'data-brand-asset="browser-favicon"' in favicon_demo
    assert 'data-solar-icon="brand"' not in favicon_demo
    assert 'data-solar-icon="brand-mark"' not in favicon_demo


def test_settlement_pages_use_the_t3_1_camel_case_contract_without_silent_fallback() -> None:
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")
    ranking = read_source("pages/StoreRankingPage.tsx")
    settlement = read_source("pages/StoreSettlementPage.tsx")
    details = read_source("pages/OrderDetailsPage.tsx")
    app = read_source("App.tsx")

    for contract_field in [
        "statementMonths", "periodTypes", "feeDirections",
        "promotionNetFeeCent", "managementNetFeeCent",
        "statementLineId", "adjustedNetFeeCent",
    ]:
        assert contract_field in types

    settlement_ranking_client = client.split("export function fetchSettlementStoreRanking", 1)[1].split("export function fetchSettlementMonthly", 1)[0]
    assert 'requestJson<SettlementStoreRankingData>("/dashboard/store-ranking"' in settlement_ranking_client
    assert "periodType" in client and "periodKey" in client
    assert 'requestJson<OrderFeeDetailsData>("/order-fee-details"' in client
    assert 'requestDownload("/order-fee-details/export"' in client
    assert "fallbackOnError: false" in client
    assert "promotionMonthFeeCent" in ranking
    assert "promotionCumulativeFeeCent" in ranking
    assert "managementNetFeeCent" not in ranking
    assert "RankingBasis" in ranking
    assert 'sortOrder: SortOrder = "DESC"' in ranking
    assert "meta?.saleMonths[0]" in ranking
    assert 'ranking.scopeMode === "AUTHORIZED" ? (row)' in ranking
    for enum_value in [
        "SALES_AMOUNT",
        "VERIFIED_AMOUNT",
        "PROMOTION_FEE",
    ]:
        assert enum_value in ranking
    assert 'sortOrder?: SortOrder' in client
    assert 'sortBy?: RankingSortBy' in client
    assert "statementId" in settlement
    assert "fetchStoreBillingStatements" in settlement
    assert "fetchOrderFeeDetails" in settlement
    assert "view?.metrics" in settlement
    assert "statement?.statementId" in settlement
    assert "disabled={!meta}" in settlement
    assert "promotionOrderResource" in settlement and "managementOrderResource" in settlement
    assert "feeDirection" in details
    assert "adjustedNetFeeCent" in details
    assert 'searchParams.get("month") ?? undefined' in details
    assert "meta?.stores[0]" not in details
    assert "directionIsFrozen" in details
    api_errors = read_source("utils/apiErrors.ts")
    assert "请求编号" in api_errors
    assert "错误码" in api_errors
    assert "metaResource.rawError" in ranking
    assert "metaResource.rawError" in settlement
    assert "statusLabel(row.resultStatus)" in details
    assert ".trim().toUpperCase()" in details
    assert "DATA_QUALITY_BLOCKED" in details and "SUPERSEDED" in details
    assert "adjustmentBaseCent" in details and "occurredAt" in details
    assert "const { page: _page, pageSize: _pageSize, ...exportQuery }" in client
    resource_hook = read_source("hooks/useApiResource.ts")
    assert "data: current.data" in resource_hook
    assert "refreshing: current.data !== undefined" in resource_hook
    assert "requestId !== requestIdRef.current" in resource_hook
    assert 'location.pathname === "/settlement/invoice"' in app
    assert 'import("./pages/StoreInvoicePage")' in app
    assert '["/settlement/invoice", "B02"]' in app
    assert '["/invoice", "B02"]' in app


def test_metric_cards_use_one_neutral_visual_treatment() -> None:
    component = read_source("components/MetricCard.tsx")
    styles = read_source("styles.css")
    tokens = json.loads(read(DESIGN_SYSTEM / "tokens.json"))
    html = read(DESIGN_SYSTEM / "index.html")
    readme = read(DESIGN_SYSTEM / "README.md")

    assert "tone?:" not in component
    assert "metric-card--${tone}" not in component
    assert ".metric-card::before" not in styles
    assert not re.search(r"\.metric-card--[\w-]+::before", styles)

    offenders: list[str] = []
    for path in WEB_SRC.rglob("*.tsx"):
        source = read(path)
        if re.search(r"<MetricCard\b(?:(?!/>).)*\btone=", source, re.DOTALL):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []

    metric_card = tokens["components"]["metricCard"]
    assert metric_card["surface"] == "#ffffff"
    assert metric_card["visualVariants"] == ["standard", "loading"]
    assert "topAccentHeight" not in metric_card
    assert "primary" not in metric_card
    assert "semantic" not in metric_card

    for document in [html, readme]:
        assert "关键指标卡统一使用白底圆角矩形" in document
        assert "不使用彩色顶线" in document
    assert 'class="metric-preview primary"' not in html
    assert 'class="metric-preview semantic"' not in html


def test_dydata_19_production_finance_routes_use_live_api_contract() -> None:
    app = read_source("App.tsx")
    shell = read_source("components/Shell.tsx")
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")
    invoice_page = read_source("pages/StoreInvoicePage.tsx")
    status_page = read_source("pages/StoreInvoiceStatusPage.tsx")
    finance_page = read_source("pages/FinanceFeePage.tsx")
    disputes_page = read_source("pages/FinanceDisputesPage.tsx")
    imports_page = read_source("pages/FinanceImportsPage.tsx")
    labels = read_source("utils/userFacingLabels.ts")

    production_routes = [
        "/settlement/invoice",
        "/finance/promotion",
        "/finance/management",
        "/finance/orders/promotion",
        "/finance/orders/management",
        "/finance/stores",
        "/finance/disputes",
        "/finance/imports",
    ]
    for route in production_routes:
        assert route in app
        assert route in shell

    assert 'location.pathname === "/finance"' in app
    assert 'window.history.replaceState(null, "", "/finance/promotion")' in app
    assert 'import("./pages/StoreInvoicePage")' in app
    assert "InvoiceGuidePage" not in app
    assert 'export type BillingMetricScope = "MONTH" | "CUMULATIVE"' in types
    for live_field in [
        "statementId", "promotionAmountCent", "invoiceNumber",
        "statementTotalCent", "orderId", "storeName", "disputeId",
        "batchId", "pageSize",
    ]:
        assert live_field in types
    assert "FinanceImportActionPanel" in finance_page
    import_panel = read_source("components/FinanceImportActionPanel.tsx")
    for import_type in [
        "BASIC_INFO",
        "PROMOTION_FACTORY_RESULT",
        "MANAGEMENT_FACTORY_RESULT",
        "SAP_CONFIRMATION",
    ]:
        assert import_type in import_panel
    for obsolete_import_type in [
        "PROMOTION_REVIEW_RESULT",
        "MANAGEMENT_INVOICE_DETAIL",
        "SAP_SETTLEMENT_RESULT",
    ]:
        assert obsolete_import_type not in import_panel
        assert obsolete_import_type not in imports_page
    assert "uploadFinanceImport" not in imports_page
    assert "commitFinanceImport" not in imports_page
    assert "processSteps" not in invoice_page
    assert "发票提交财务审核" not in invoice_page
    assert "registerPromotionInvoice" in invoice_page
    assert "比亚迪汽车销售有限公司" in invoice_page
    assert "914403007604674476" in invoice_page
    assert "const PROMOTION_INVOICE_TAX_RATE_PERCENT = 6" in invoice_page
    assert "taxRatePercent: Number(taxRatePercent" in invoice_page
    for promotion_invoice_field in [
        "buyerName",
        "taxRatePercent",
        "settlementBatchMonth",
        "promotionInvoiceableAmountCent",
        "promotionCarryforwardBalanceCent",
        "promotionInvoiceGroupId",
        "promotionRequiredStatementIds",
    ]:
        assert promotion_invoice_field in types
    assert "promotionInvoiceGroupId: statement.promotionInvoiceGroupId" in invoice_page
    assert "toggleInvoiceGroup" not in invoice_page
    assert "loadSystemSelectedInvoiceGroup" in invoice_page
    assert "selectAllRegisterableInvoiceStatements" in invoice_page
    assert "selectSystemInvoiceAnchor" not in invoice_page
    assert "selectedGroupStatements" in invoice_page
    assert "positiveOriginalAmountCent" not in invoice_page
    assert "negativeOffsetAmountCent" not in invoice_page
    assert "已释放账期仍在结转抵扣中" in invoice_page
    assert "正数原费用" not in invoice_page
    assert "负数抵扣" not in invoice_page
    assert '<dt>净开票金额' not in invoice_page
    assert "PromotionInvoiceRegistrationResult" in types
    assert "ApiLoadResult<PromotionInvoiceRegistrationResult>" in client
    for lifecycle_contract in [
        "PromotionInvoiceLifecycleEvent",
        "PromotionInvoiceDetail",
        "replacesInvoiceId",
        "physicalInvoiceId",
        "versionKind",
    ]:
        assert lifecycle_contract in types
    for lifecycle_client in [
        "fetchPromotionInvoiceDetail",
        "fetchPromotionInvoiceReplacementCandidates",
        "createPromotionInvoiceLifecycleEvent",
        "releasedStatementMonths",
    ]:
        assert lifecycle_client in client + invoice_page + status_page
    for lifecycle_copy in [
        "登记红冲",
        "登记作废",
        "系统只登记事实并释放全部账期",
        "必须使用新发票号码覆盖账期",
    ]:
        assert lifecycle_copy in invoice_page + status_page
    for recovery_contract in [
        "待替换发票",
        "恢复替换",
        "replacementCandidateResource",
        "fetchPromotionInvoiceDetail(selectedInvoiceId ?? \"\")",
        "replacementChain",
    ]:
        assert recovery_contract in invoice_page + status_page + client + types
    assert "SUBMITTED_PENDING_REVIEW" not in invoice_page
    assert "SUBMITTED_PENDING_FACTORY_REVIEW" in labels
    for presenter, source in [
        ("displayFinanceInvoiceStatus", invoice_page + finance_page),
        ("displayFinanceImportType", imports_page),
        ("displayFinanceImportScenario", imports_page + import_panel),
        ("displayFinanceDisputeStatus", disputes_page),
        ("displayFinanceDisputeType", disputes_page),
        ("displayFeeDirection", disputes_page),
    ]:
        assert presenter in source
    for raw_fallback in [
        "?? row.status",
        "?? row.importType",
        "?? row.scenario",
        "?? row.disputeType",
    ]:
        assert raw_fallback not in invoice_page + finance_page + disputes_page + imports_page

    required_endpoints = [
        '"/store-settlements"',
        '"/promotion-invoices"',
        '"/admin/finance/summary"',
        '"/admin/finance/invoices"',
        '"/admin/finance/order-details"',
        '"/admin/finance/order-details/export"',
        '"/admin/finance/stores"',
        '"/admin/disputes"',
        '"/admin/finance-imports"',
    ]
    for endpoint in required_endpoints:
        assert endpoint in client

    for type_name in [
        "StoreBillingStatement",
        "PromotionInvoiceRow",
        "FinanceSummaryData",
        "FinanceInvoiceRow",
        "FinanceOrderDetailRow",
        "FinanceStoreRow",
        "FinanceDisputeRow",
        "FinanceImportBatchRow",
    ]:
        assert f"interface {type_name}" in types


def test_dydata_19_g2_frontend_exposes_correction_sap_and_reversal_actions() -> None:
    app = read_source("App.tsx")
    shell = read_source("components/Shell.tsx")
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")
    management_page = read_source("pages/FinanceFeePage.tsx")
    stores_page = read_source("pages/FinanceStoresPage.tsx")
    imports_page = read_source("pages/FinanceImportsPage.tsx")

    assert 'pathname === "/finance/stores" && user.role === "store"' not in app
    assert '{ href: "/finance/stores", label: "SAP 建议", pageKey: "B02" }' not in shell
    assert 'currentPath === "/finance/stores" && currentUser?.role === "store"' not in shell
    assert "correctManagementInvoice" in client + management_page
    assert "更正管理服务费记录" in management_page
    assert "readVersion" in management_page
    assert "历史版本" in management_page
    assert "invoiceAmountCent: string" in management_page
    assert "deductionAmountCent: string" in management_page
    assert 'type="number"' in management_page
    assert "<input disabled" not in management_page
    assert "correctFinanceStoreSap" in client + stores_page
    assert "submitSapSuggestion" not in stores_page
    assert "decideSapSuggestion" not in stores_page
    assert "effectiveSapVersion" in stores_page
    assert "财务导入值" in stores_page
    assert "currentUser={user}" in app
    assert "reverseFinanceImport" in client + imports_page


def test_dydata_19_g3_order_detail_page_exposes_complete_server_filters_pagination_export_state_and_definitions() -> None:
    """The two fee-direction pages share a complete, observable order-detail workflow."""
    page = read_source("pages/FinanceOrderDetailsPage.tsx")
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")
    imports_page = read_source("pages/FinanceImportsPage.tsx")

    for index, control in enumerate([
        "sapCode",
        "invoiceNumber",
        "orderId",
        "skuId",
        "saleChannel",
        "invoiceStatus",
        "submittedFrom",
        "submittedTo",
        "verifyFrom",
        "verifyTo",
        "pageSize",
        "导出中",
        "字段来源与计算说明",
        "上一页",
        "下一页",
        "重置筛选",
    ]):
        assert control in page or (index in {13, 14} and "TablePagination" in page)
    assert "onPageSizeChange" in page
    assert "fetchFinanceOrderDetails" in page
    assert "downloadFinanceOrderDetails" in page
    assert "finance-order-detail-grid" in page
    for field in [
        "statementEntryId",
        "statementId",
        "statementMonth",
        "feeDirection",
        "orderStatus",
        "couponStatus",
        "saleStoreId",
        "saleStoreName",
        "verifyStoreId",
        "verifyStoreName",
        "saleTime",
        "refundTime",
        "adjustmentType",
        "submittedAt",
        "settledAt",
        "rejectionReason",
        "importedAt",
        "factoryDeductionDate",
        "factoryDeductionAmountCent",
    ]:
        assert f"row.{field}" in page
    assert "FinanceOrderDetailFieldDefinitions" in types
    assert "FinanceOrderDetailsQuery" in types
    download_contract = client.split(
        "export function downloadFinanceOrderDetails", 1
    )[1].split("export function fetchFinanceStores", 1)[0]
    assert "Promise<void>" not in download_contract
    assert "撤销批次" in imports_page
    assert "changeReason" in imports_page
    for field in [
        "sourceType",
        "suggestionStatus",
        "suggestionVersion",
        "confirmedVersion",
        "reversesBatchId",
        "reversedByBatchId",
        "reverseNotAllowedReason",
        "reversalChain",
        "canReverse",
    ]:
        assert field in types
    for field in [
        "originalTargetRecordId",
        "previousTargetRecordId",
        "reversalTargetRecordId",
        "effectType",
        "isCurrent",
        "reversalRows",
    ]:
        assert field in types
    assert "逐业务键撤销覆盖链" in imports_page
    assert "originalTargetRecordId" in imports_page
    for field in ["reversedByBatchId", "reverseNotAllowedReason", "reversalChain"]:
        assert field in imports_page


def test_finance_navigation_and_headings_match_the_v2_clean_contract() -> None:
    shell = read_source("components/Shell.tsx")
    order_details = read_source("pages/FinanceOrderDetailsPage.tsx")
    fee_page = read_source("pages/FinanceFeePage.tsx")
    stores_page = read_source("pages/FinanceStoresPage.tsx")
    disputes_page = read_source("pages/FinanceDisputesPage.tsx")
    imports_page = read_source("pages/FinanceImportsPage.tsx")

    for item in [
        '{ href: "/finance/promotion", label: "推广服务费"',
        '{ href: "/finance/management", label: "管理服务费"',
        '{ href: "/finance/orders/promotion", label: "订单明细"',
        '{ href: "/finance/stores", label: "门店基础信息"',
        '{ href: "/finance/disputes", label: "账单异议"',
        '{ href: "/finance/imports", label: "导入记录"',
    ]:
        assert item in shell
    assert '"/finance/orders/management": "/finance/orders/promotion"' in shell
    assert 'href: "/finance/orders/management", label:' not in shell

    assert 'import { TertiaryNav } from "../components/TertiaryNav";' in order_details
    assert '<TertiaryNav' in order_details
    assert 'label="订单明细费用方向"' in order_details
    for item in [
        '`/finance/orders/promotion?month=${encodeURIComponent(draft.month)}`',
        '`/finance/orders/management?month=${encodeURIComponent(draft.month)}`',
    ]:
        assert item in order_details
    assert '<TertiaryNav' in order_details.split('<section className="page-heading', 1)[0]
    assert 'feeDirection === "PROMOTION" ? "推广服务费订单明细" : "管理服务费订单明细"' in order_details

    assert 'const title = feeDirection === "PROMOTION" ? "推广服务费" : "管理服务费";' in fee_page
    assert '<h1>门店基础信息</h1>' in stores_page
    assert 'label: "SAP异议处理"' in stores_page
    assert '<h1>账单异议</h1>' in disputes_page
    assert '<h1>导入记录</h1>' in imports_page


def test_dydata_81_finance_is_an_independent_primary_module_before_admin() -> None:
    app = read_source("App.tsx")
    shell = read_source("components/Shell.tsx")

    assert 'type NavSection = "settlement" | "verification" | "clues" | "finance" | "admin";' in shell
    assert 'const financePaths = new Set([' in shell
    assert 'section: "finance"' in shell
    assert 'href: "/finance/promotion"' in shell
    assert 'pageKeys: ["FIN01", "FIN02", "FIN03", "FIN04", "FIN05", "FIN06"]' in shell
    assert 'icon: "details"' in shell
    assert 'label: "财务"' in shell
    assert shell.index('label: "财务"') < shell.index('label: "后台"')
    assert 'finance: "财务中心"' in shell
    assert 'if (section === "finance")' in shell
    assert 'return financeNavItems;' in shell
    assert 'if (currentPath.startsWith("/finance"))' not in shell

    admin_paths = shell.split("const adminPaths = new Set([", 1)[1].split("]);", 1)[0]
    assert '"/finance/' not in admin_paths
    assert 'pathname === "/finance/stores" && user.role === "store"' not in app
    assert 'user.page_keys.includes("B02")' not in app.split(
        "export function hasPageAccess", 1
    )[1].split("function AuthGate", 1)[0]
