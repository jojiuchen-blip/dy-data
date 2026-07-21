from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = REPO_ROOT / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_t3_3_client_exposes_frozen_admin_contracts() -> None:
    client = read_source("api/client.ts")

    for endpoint in [
        '"/admin/sku-products"',
        '"/admin/sku-fee-rules"',
        '"/admin/sku-fee-rule-imports"',
        '"/admin/sku-fee-rule-imports/template"',
        '"/admin/product-sync-runs"',
    ]:
        assert endpoint in client

    assert '"Idempotency-Key"' in client
    assert "FormData" in client
    assert "effectiveDate" in client


def test_rules_page_uses_new_product_fee_and_atomic_import_panel() -> None:
    page = read_source("pages/AdminSkuRulesPage.tsx")
    panel = read_source("components/AdminSkuGovernancePanel.tsx")

    assert "<AdminSkuGovernancePanel" in page
    assert "旧单费率兼容区" in page
    assert "正式双费率发布、版本追溯与批量导入请使用上方新入口" in page
    for copy in [
        "商品人工分类",
        "双费率版本发布",
        "批量导入与原子提交",
        "整批未写入",
        "推广服务费比例",
        "管理服务费比例",
        "生效自然日",
        "变更原因",
    ]:
        assert copy in panel
    assert "rowNumber" in panel
    assert "error.field" in panel
    assert "error.message" in panel
    assert "PENDING_COMMIT" in panel


def test_sync_page_shows_product_runs_details_and_safe_statuses() -> None:
    page = read_source("pages/AdminSyncPage.tsx")
    panel = read_source("components/AdminProductSyncPanel.tsx")
    labels = read_source("utils/userFacingLabels.ts")

    assert "<AdminProductSyncPanel" in page
    for copy in [
        "商品主数据同步",
        "触发成功只表示任务已入队",
        "最近成功同步",
        "数据质量问题",
        "受影响 SKU 样例",
    ]:
        assert copy in panel
    for presenter in [
        "displayProductStatus",
        "displayFeeRuleStatus",
        "displayImportBatchStatus",
        "displayImportRowStatus",
        "displayProductSyncStatus",
        "displayProductSyncMode",
    ]:
        assert f"export function {presenter}" in labels
        assert presenter in panel or presenter in read_source(
            "components/AdminSkuGovernancePanel.tsx"
        )


def test_admin_contract_types_are_camel_case_and_keep_audit_fields() -> None:
    types = read_source("types/dashboard.ts")

    for interface_name in [
        "SkuProductItem",
        "SkuFeeRuleItem",
        "ImportBatchItem",
        "ImportRowItem",
        "ProductSyncRunItem",
        "SkuSyncHistoryItem",
    ]:
        assert f"export interface {interface_name}" in types

    for field in [
        "manualModifiedAt",
        "previousRuleVersion",
        "changeReason",
        "publishedAt",
        "commitMode",
        "hasResultFile",
        "latestSuccessfulSyncedAt",
        "nextCursorMasked",
        "payloadSha256",
    ]:
        assert field in types
