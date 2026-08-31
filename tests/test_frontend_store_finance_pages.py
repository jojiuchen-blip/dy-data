from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = REPO_ROOT / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_invoice_status_is_a_stable_b02_route_in_the_existing_settlement_shell() -> None:
    app = read_source("App.tsx")
    shell = read_source("components/Shell.tsx")

    assert 'import("./pages/StoreInvoiceStatusPage")' in app
    assert '["/settlement/invoice/status", "B02"]' in app
    assert 'location.pathname === "/settlement/invoice/status"' in app
    assert '<StoreInvoiceStatusPage currentUser={user} searchParams={searchParams} />' in app

    assert '"/settlement/invoice/status"' in shell
    assert '{ href: "/settlement/invoice/status", label: "发票状态查看", pageKey: "B02" }' in shell
    assert '{ href: "/settlement/invoice", label: "开票确认", pageKey: "B02" }' in shell
    assert 'icon: "chart"' in shell

    # The store-only change must not rewrite the protected finance navigation.
    for protected_item in [
        '{ href: "/finance/promotion", label: "推广服务费", pageKey: "D01" }',
        '{ href: "/finance/management", label: "管理服务费", pageKey: "D01" }',
        '{ href: "/finance/orders/promotion", label: "订单明细", pageKey: "D01" }',
        '{ href: "/finance/stores", label: "门店基础信息", pageKey: "D01" }',
        '{ href: "/finance/disputes", label: "账单异议", pageKey: "D01" }',
        '{ href: "/finance/imports", label: "导入记录", pageKey: "D01" }',
    ]:
        assert protected_item in shell


def test_store_shell_does_not_change_the_protected_finance_access_contract() -> None:
    app = read_source("App.tsx")
    shell = read_source("components/Shell.tsx")

    assert '{ href: "/finance/stores", label: "SAP \u5efa\u8bae", pageKey: "B02" }' not in shell
    assert 'pathname === "/finance/stores" && user.role === "store"' not in app
    assert 'currentPath === "/finance/stores" && currentUser?.role === "store"' not in shell

    # The finance/admin entry remains owned by the protected finance navigation.
    assert '{ href: "/finance/stores", label: "\u95e8\u5e97\u57fa\u7840\u4fe1\u606f", pageKey: "D01" }' in shell


def test_store_finance_pages_share_the_business_timeline_without_demo_copy() -> None:
    timeline = read_source("components/StoreFinanceTimeline.tsx")
    settlement = read_source("pages/StoreSettlementPage.tsx")
    invoice = read_source("pages/StoreInvoicePage.tsx")
    status = read_source("pages/StoreInvoiceStatusPage.tsx")

    for required_step in [
        "月度结束",
        "系统核查",
        "账单确认",
        "自动确认",
        "发票提交",
        "厂端审核",
        "审核通过/已结算",
    ]:
        assert required_step in timeline

    for required_deadline in [
        'meta: "每月最后一日"',
        'meta: "次月1日"',
        'meta: "次月1—6日"',
        'meta: "次月6日24:00"',
        'meta: "当月10日前"',
    ]:
        assert required_deadline in timeline

    for forbidden_deadline in [
        'meta: "完成当月闭环"',
        'meta: "次月 1—5 日"',
        'meta: "次月 8 日 24:00 前"',
        'meta: "逾期按系统账单处理"',
    ]:
        assert forbidden_deadline not in timeline

    assert "StoreFinanceTimeline" in invoice
    assert "StoreFinanceTimeline" not in settlement
    assert "StoreFinanceTimeline" not in status
    for page in [settlement, invoice, status]:
        for forbidden in [
            "DYDATA-19 · Mock",
            "会议演示",
            "F01—F10",
            "验收场景",
            "演示角色",
            "演示数据仅用于流程确认",
        ]:
            assert forbidden not in page


def test_store_settlement_exposes_direction_cards_and_real_order_detail_resources() -> None:
    page = read_source("pages/StoreSettlementPage.tsx")

    assert "fetchOrderFeeDetails" in page
    assert 'feeDirection: "PROMOTION"' in page
    assert 'feeDirection: "MANAGEMENT"' in page
    assert "promotionOrderResource" in page
    assert "managementOrderResource" in page
    assert "store-finance-fee-tabs" in page
    assert "推广费明细" in page
    assert "管理费明细" in page
    assert "推广费明细" in page
    assert "管理费明细" in page
    for field in [
        "订单号",
        "商品",
        "销售渠道",
        "核销时间",
        "实收金额",
        "实际费率",
        "服务费",
    ]:
        assert field in page

    assert "DYDATA-82" not in page
    assert "DYDATA-83" not in page
    assert "submitStoreBillingDispute" not in page
    assert "账单异议" in page
    assert "异议类型" in page
    assert "发起账单异议" in page
    assert "受控证明对象键" not in page
    assert "证明材料受控上传尚未开放，当前不能提交异议。" in page


def test_store_invoice_keeps_real_registration_and_adds_formal_invoice_guidance() -> None:
    page = read_source("pages/StoreInvoicePage.tsx")

    assert "registerPromotionInvoice" in page
    assert "crypto.randomUUID()" in page
    assert "StoreFinanceTimeline" in page
    assert "购买方开票信息" in page
    assert "一键复制全部开票信息" in page
    assert 'icon="copy"' in page
    assert "store-finance-registration-reminder" not in page
    assert "当月10号前开票提交，当月结算；10号后开票提交将在下月结算。" in page
    assert "当月10日前登记成功进入当月结算批次；10日后登记进入下月结算批次。" in page
    assert "10日24:00前" not in page
    assert "20 位数电专票号码" in page
    assert "核验并登记发票" in page
    assert "不含税金额" in page
    assert "税额" in page
    assert "replacementCandidateResource.error" not in page.split("<ResourceNotice", 1)[1].split("/>", 1)[0]
    assert "开票记录" not in page


def test_invoice_status_page_filters_backend_rows_and_loads_detail() -> None:
    page = read_source("pages/StoreInvoiceStatusPage.tsx")
    app = read_source("App.tsx")

    assert "fetchStoreInvoiceStatus" in page
    assert "fetchPromotionInvoiceDetail" in page
    assert "displayFinanceInvoiceStatus" in page
    assert "invoiceNumberInput" in page
    assert "invoiceNumberQuery" in page
    assert "applyInvoiceSearch" in page
    assert "selectedInvoiceId" in page
    assert "invoiceNumber: normalizedInvoiceNumber || undefined" in page
    assert "normalizedInvoiceNumber ? undefined : activeMonth" in page
    assert ".includes(normalizedQuery)" not in page
    assert '{ label: "待开票", value: "PENDING_INVOICE" }' not in page
    assert "审核原因尚未同步" not in page
    assert "DYDATA-83" not in page
    assert "PENDING_INVOICE" not in page
    assert "row.invoiceNumber.toLowerCase().includes" not in page
    assert "服务端跨授权账期精确查询后分页" in page
    assert 'page: invoicePage' in page
    assert 'pageSize: INVOICE_PAGE_SIZE' in page
    assert "<TablePagination" in page
    assert "currentUser.store_ids" in page
    assert "<StoreInvoiceStatusPage currentUser={user}" in app
    for label in [
        "账期",
        "发票号码",
        "发票状态",
        "审核结果",
        "原因",
        "结算归属",
        "服务名称",
        "开票日期",
        "差额原因",
        "差额金额",
        "目标账期",
        "查看详情",
    ]:
        assert label in page


def test_store_finance_styles_are_scoped_and_responsive() -> None:
    styles = read_source("styles.css")

    assert ".store-finance-timeline" in styles
    assert ".store-finance-direction-card" in styles
    assert ".store-finance-invoice-info" in styles
    assert ".store-finance-status-detail" in styles
    assert "@media (max-width: 768px)" in styles
    assert "@media (max-width: 480px)" in styles


def test_ranking_and_store_settlement_use_page_specific_compact_metrics() -> None:
    ranking = read_source("pages/StoreRankingPage.tsx")
    settlement = read_source("pages/StoreSettlementPage.tsx")
    styles = read_source("styles.css")

    for page in [ranking, settlement]:
        assert 'className="metric-grid store-summary-metrics"' in page
        assert 'label="\u5f53\u671f\u63a8\u5e7f\u670d\u52a1\u8d39"' in page
        assert 'label="\u7d2f\u8ba1\u63a8\u5e7f\u670d\u52a1\u8d39"' in page
        assert 'label="\u7ed3\u7b97\u53c2\u8003\u51c0\u989d"' not in page

    assert 'label="\u5f53\u671f\u7ba1\u7406\u670d\u52a1\u8d39"' not in ranking
    assert 'label="\u7d2f\u8ba1\u7ba1\u7406\u670d\u52a1\u8d39"' not in ranking
    assert 'label="\u5f53\u671f\u7ba1\u7406\u670d\u52a1\u8d39"' in settlement
    assert 'label="\u7d2f\u8ba1\u7ba1\u7406\u670d\u52a1\u8d39"' in settlement

    assert "rankingBasis," in ranking
    assert "comparisonResource" not in ranking
    assert "salesAmountCumulativeCent" in ranking
    assert "verifiedAmountCumulativeCent" in ranking
    assert "promotionMonthFeeCent" in ranking
    assert "promotionCumulativeFeeCent" in ranking
    assert 'billingMetrics?.cumulative?.promotionAmountCent' in settlement
    assert 'billingMetrics?.cumulative?.managementAmountCent' in settlement
    assert 'title: "管理服务费净额"' not in ranking
    assert 'title: "结算参考净额"' not in ranking
    assert '{ value: "MANAGEMENT_FEE"' not in ranking
    assert '{ value: "NET_SETTLEMENT_REFERENCE"' not in ranking
    assert ".store-summary-metrics" in styles
    metric_rule = styles.split(".store-summary-metrics", 1)[1].split("}", 1)[0]
    assert "grid-auto-flow: column" in metric_rule
    assert "grid-auto-columns: minmax(0, 1fr)" in metric_rule
    assert "grid-auto-flow: column" in styles
    assert "overflow-x: auto" in styles


def test_invoice_confirmation_restores_the_reference_verification_workspace() -> None:
    page = read_source("pages/StoreInvoicePage.tsx")
    styles = read_source("styles.css")

    for required_copy in [
        "购买方开票信息",
        "填写数电专票信息",
        "一键复制全部开票信息",
        "不含税金额",
        "税额",
        "价税合计",
        "系统校验结果",
        "数电专票号码必须为20位纯数字且不得重复",
        "不含税金额 + 税额必须等于开票金额",
        "价税合计必须等于系统确定账期的推广服务费",
    ]:
        assert required_copy in page

    assert "calculateInvoiceTaxBreakdown" not in page
    assert "税额必须与不含税金额按6%税率计算一致" not in page
    assert "parseInvoiceAmountCent" in page
    assert "Math.abs(netAmountCent + taxAmountCent - invoiceAmountCent) <= 1" in page
    assert "validateInvoiceRegistration" in page
    assert 'className="store-finance-invoice-workspace"' in page
    assert 'className="store-finance-verification-list"' in page
    assert 'className="store-finance-validation-response"' in page
    assert "selectedStatements.length === 0" in page
    assert ".store-finance-invoice-workspace" in styles
    assert ".store-finance-verification-list" in styles


def test_invoice_period_is_system_selected_and_all_billable_periods_are_included() -> None:
    page = read_source("pages/StoreInvoicePage.tsx")

    assert "fetchSettlementFilterMeta" in page
    assert "loadSystemSelectedInvoiceGroup" in page
    assert "selectAllRegisterableInvoiceStatements" in page
    assert "selectedGroupStatements" in page
    assert 'className="finance-filter-bar finance-filter-bar--invoice"' not in page
    assert "toggleInvoiceGroup" not in page
    assert "选择抵扣组" not in page
    assert "移除整组" not in page
    assert 'type="month"' not in page
    assert "逐月筛选" not in page
    assert "跨筛选月份保留" not in page


def test_invoice_registration_uses_all_billable_periods_and_validates_entered_fields() -> None:
    page = read_source("pages/StoreInvoicePage.tsx")

    assert "selectAllRegisterableInvoiceStatements" in page
    assert "selectSystemInvoiceAnchor" not in page
    assert "替换原发票" in page

    for field in [
        'aria-label="购买方名称"',
        'aria-label="填写人电话"',
        'aria-label="税率"',
        'aria-label="不含税金额"',
        'aria-label="税额"',
        'aria-label="价税合计"',
    ]:
        assert field in page

    for removed_field in [
        'aria-label="纳税人识别号"',
        'aria-label="地址"',
        'aria-label="电话"',
        'aria-label="开户行及账号"',
        'aria-label="项目名称"',
        'aria-label="税收分类编码"',
    ]:
        assert removed_field not in page

    assert "本项应该填写6%，请检查您开具的发票税率是否为6%。" in page
    assert "本项应该填写“比亚迪汽车销售有限公司”，请检查您开具的发票购买方名称是否正确。" in page
    assert "parseInvoiceAmountCent" in page
    assert "不含税金额 + 税额必须等于开票金额" in page
    assert "currentUser.store_ids.includes" in page
    assert "showValidationFeedback" in page
    assert "failedInvoiceValidationItems" in page
    assert 'className="store-finance-validation-response"' in page
    assert 'className="store-finance-verification finance-form-grid__wide"' not in page
    assert 'disabled={submitting}' in page
    assert "noValidate" in page
    assert "请填写开票信息填写人电话" in page


def test_store_finance_defaults_use_account_store_and_api_latest_period() -> None:
    app = read_source("App.tsx")
    settlement = read_source("pages/StoreSettlementPage.tsx")
    invoice = read_source("pages/StoreInvoicePage.tsx")
    status = read_source("pages/StoreInvoiceStatusPage.tsx")

    assert "<StoreSettlementPage currentUser={user} searchParams={searchParams} />" in app
    assert "<StoreInvoiceStatusPage currentUser={user} searchParams={searchParams} />" in app
    for page in [settlement, status]:
        assert "currentUser.store_ids[0]" in page
        assert "meta?.statementMonths[0]" in page
    assert "defaultStatementMonth" not in invoice
    assert "new Date()" not in invoice
    assert "filterMeta?.statementMonths[0]" in invoice


def test_missing_store_finance_metrics_are_not_rendered_as_real_zero_values() -> None:
    ranking = read_source("pages/StoreRankingPage.tsx")
    settlement = read_source("pages/StoreSettlementPage.tsx")
    invoice = read_source("pages/StoreInvoicePage.tsx")

    assert 'const displayMetricCurrency = (value: number | undefined) =>' in ranking
    assert 'const displayMetricCount = (value: number | undefined, unit: string) =>' in ranking
    assert 'value={formatCurrency(salesAndVerificationTotals?.salesAmountCent ?? 0)}' not in ranking

    assert 'const displayMetricCurrency = (value: number | undefined) =>' in settlement
    assert 'value={formatCurrency(metrics?.salesAmountCent ?? 0)}' not in settlement
    assert 'formatCurrency(originalAmount ?? 0)' not in settlement

    assert 'selectedStatements.length ? formatCurrency(selectedAmountCent) : "尚未生成"' in invoice
    assert '<div><dt>价税合计</dt><dd>{selectedStatements.length ? formatCurrency(selectedAmountCent) : "尚未生成"}</dd></div>' in invoice
    assert 'promotionAmountCent ?? 0)}' not in invoice


def test_store_finance_pages_do_not_publish_developer_issue_copy() -> None:
    for relative_path in [
        "pages/StoreSettlementPage.tsx",
        "pages/StoreInvoicePage.tsx",
        "pages/StoreInvoiceStatusPage.tsx",
    ]:
        page = read_source(relative_path)
        assert "DYDATA-82" not in page
        assert "DYDATA-83" not in page


def test_store_finance_current_stage_uses_brand_highlight_tokens() -> None:
    styles = read_source("styles.css")

    status_rule = styles.split(".store-finance-timeline__status", 1)[1].split("}", 1)[0]
    assert "var(--brand-orange-soft)" in status_rule
    assert "var(--brand-orange)" in status_rule
    assert "var(--brand-orange-ink)" in status_rule
