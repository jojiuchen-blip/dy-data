from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = REPO_ROOT / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_ranking_uses_uat_basis_selector_and_cumulative_sales_metrics() -> None:
    page = read_source("pages/StoreRankingPage.tsx")

    assert "RankingBasis" in page
    assert 'label="排行依据"' in page
    assert "销售金额（累计）" in page
    assert "核销金额（累计）" in page
    assert "累计推广服务费" in page
    assert 'title: "销售订单"' not in page
    assert 'title: "核销订单"' not in page
    assert 'label="排序指标"' not in page
    assert 'label="排序方向"' not in page
    assert "rankingBasis," in page
    assert "comparisonResource" not in page
    assert "salesAmountCumulativeCent" in page
    assert "verifiedAmountCumulativeCent" in page
    assert "promotionMonthFeeCent" in page
    assert "promotionCumulativeFeeCent" in page


def test_settlement_embeds_two_fee_detail_tabs_and_safe_dispute_intake() -> None:
    page = read_source("pages/StoreSettlementPage.tsx")
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")

    assert "store-finance-confirmation-grid" in page
    assert "费用明细" in page
    assert "推广费明细" in page
    assert "管理费明细" in page
    assert "发起账单异议" in page
    assert "submitStoreBillingDispute" not in page
    assert "受控证明对象键" not in page
    assert 'type="file"' in page
    assert "证明材料受控上传尚未开放，当前不能提交异议。" in page
    assert "disputeType" in page
    assert "feeDirection" in page
    assert "StoreBillingDisputePayload" in types
    assert "/disputes" in client
    assert "当前未生成可确认账单，页面保留预览数据" not in page
    assert 'label="产品范围"' not in page
    assert 'label="商品类型"' not in page


def test_invoice_status_has_cross_period_status_contract_and_summary_sections() -> None:
    page = read_source("pages/StoreInvoiceStatusPage.tsx")
    client = read_source("api/client.ts")

    assert "fetchStoreInvoiceStatus" in page
    assert "账单总额" in page
    assert "已确认金额" in page
    assert "已开票金额" in page
    assert "审核通过/已结算金额" in page
    assert "待开票金额" in page
    assert "推广发票记录" in page
    assert "管理服务费发票信息" in page
    assert "差额台账" in page
    assert "normalizedInvoiceNumber ? undefined : activeMonth" in page
    assert 'value: "PENDING_INVOICE"' not in page
    assert 'requestJson<StoreInvoiceStatusData>("/store-invoice-status"' in client


def test_store_shell_uses_four_page_uat_navigation_and_keeps_details_as_drilldown_only() -> None:
    shell = read_source("components/Shell.tsx")

    nav_block = shell.split("const settlementNavItems", 1)[1].split("const financeNavItems", 1)[0]
    assert '{ href: "/settlement", label: "单店分账", pageKey: "B02" }' in nav_block
    assert '{ href: "/settlement/invoice", label: "开票确认", pageKey: "B02" }' in nav_block
    assert '{ href: "/settlement/invoice/status", label: "发票状态查看", pageKey: "B02" }' in nav_block
    assert '{ href: "/settlement/details", label: "订单费用明细"' not in nav_block
    assert '{ href: "/details", label: "订单费用明细"' not in nav_block


def test_formal_settlement_shell_has_no_demo_trial_copy() -> None:
    shell = read_source("components/Shell.tsx")

    assert "settlementTrialNotice" not in shell
    assert "预计分佣比例、金额仅为试运行参考" not in shell
    assert 'badge: "试运行"' not in shell
    assert 'description: "试运行"' not in shell


def test_store_dispute_dialog_does_not_fake_submission_before_controlled_upload_exists() -> None:
    page = read_source("pages/StoreSettlementPage.tsx")

    assert 'form="store-dispute-form"' not in page
    assert 'type="submit"' not in page
    assert "提交异议并开始检测" in page
    assert "disabled" in page
    assert 'dispatchEvent(new Event("submit"' not in page


def test_store_dispute_entry_is_compact_and_confirms_before_opening_the_form() -> None:
    page = read_source("pages/StoreSettlementPage.tsx")

    assert "disputeConfirmationOpen" in page
    assert 'title="确认发起账单异议"' in page
    assert "发起异议前请准备充分资料，是否发起？" in page
    assert 'className="store-finance-dispute-entry__label"' in page
    assert '<h3>账单异议</h3>' not in page


def test_invoice_page_uses_the_frozen_uat_workspace_without_duplicate_intro_blocks() -> None:
    page = read_source("pages/StoreInvoicePage.tsx")

    assert "开票在系统外完成；" not in page
    assert "前往发票状态查看" not in page
    assert "<h2>登记发票信息</h2>" not in page
    assert 'className="store-finance-invoice-workspace"' in page
    assert 'className="store-finance-invoice-badge"' not in page
    assert "fillerPhone: fillerPhone.trim()" in page
    assert "netAmountCent" in page
    assert "taxAmountCent" in page


def test_invoice_status_uses_explicit_exact_search_without_store_period_pickers() -> None:
    page = read_source("pages/StoreInvoiceStatusPage.tsx")

    assert "invoiceNumberInput" in page
    assert "applyInvoiceSearch" in page
    assert "服务端精确查询" in page
    assert "输入完整发票号码" in page
    assert '<FilterBar>' not in page
    assert 'label="审核状态"' not in page
    assert "SearchableStoreSelect" not in page
