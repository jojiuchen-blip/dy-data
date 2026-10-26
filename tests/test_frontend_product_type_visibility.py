from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_admin_product_type_visibility_page_is_wired_to_shell_and_api_client() -> None:
    app_source = read_source("App.tsx")
    shell_source = read_source("components/Shell.tsx")
    home_source = read_source("pages/AdminHomePage.tsx")
    page_source = read_source("pages/AdminProductTypeVisibilityPage.tsx")
    client_source = read_source("api/client.ts")
    types_source = read_source("types/dashboard.ts")
    styles_source = read_source("styles.css")

    assert "AdminProductTypeVisibilityPage" in app_source
    assert 'location.pathname === "/admin/product-types"' in app_source
    assert '"/admin/product-types"' in shell_source
    assert 'href: "/admin/product-types", label: "商品口径"' in shell_source
    assert 'href: "/admin/product-types"' in home_source

    assert "待完善" in page_source
    assert "已配置" in page_source
    assert "configurationStatus" in page_source
    assert "PENDING" in page_source
    assert "CONFIGURED" in page_source
    assert "默认每页 50 条" in page_source
    assert "跨页" in page_source
    assert "产品范围" not in page_source
    assert "商品类型" in page_source
    assert "批量设置" in page_source
    assert "批量导入" in page_source
    assert "订单分佣" in page_source
    assert "有效分佣规则" in page_source
    assert "fetchSkuProducts" in page_source
    assert "bulkUpdateSkuProducts" in page_source
    assert "expectedManualModifiedAt: editingRow.manualModifiedAt" in page_source
    assert "uploadSkuProductImport" in page_source
    assert "commitSkuProductImport" in page_source

    assert "export type SkuProductConfigurationStatus" in types_source
    assert "expectedManualModifiedAt: string | null" in types_source
    assert "statusCounts" in types_source
    assert "export interface SkuProductImportUploadData" in types_source
    assert "configurationStatus?:" in client_source
    assert "export async function bulkUpdateSkuProducts" in client_source
    assert '"/admin/sku-products/bulk"' in client_source
    assert "export async function uploadSkuProductImport" in client_source
    assert "/admin/sku-product-imports" in client_source

    assert ".product-types-workbench" in styles_source
    assert ".product-types-tabs" in styles_source
    assert ".product-types-drawer" in styles_source


def test_legacy_sku_governance_editor_sends_manual_version() -> None:
    panel_source = read_source("components/AdminSkuGovernancePanel.tsx")

    assert "expectedManualModifiedAt: selectedProduct.manualModifiedAt" in panel_source


def test_business_product_filters_use_metadata_default_product_type() -> None:
    options_source = read_source("utils/options.ts")
    ranking_source = read_source("pages/StoreRankingPage.tsx")
    settlement_source = read_source("pages/StoreSettlementPage.tsx")
    details_source = read_source("pages/OrderDetailsPage.tsx")
    clues_source = read_source("pages/ClueCenterPage.tsx")

    assert "defaultProductType" in options_source
    assert "meta?.defaultProductType" in ranking_source
    assert "meta?.defaultProductType" in settlement_source
    assert "meta?.defaultProductType" in details_source
    assert "clueDefaultProductType(meta)" in clues_source


def test_sales_dashboard_uses_real_product_type_without_scope() -> None:
    page_source = read_source("pages/SalesDashboardPage.tsx")
    assert 'label="产品范围"' not in page_source
    assert 'label="商品类型"' in page_source
    assert "productOptions(meta, activeProductType)" in page_source
    assert "const type = productType || defaultProductType(filters);" in page_source
    assert "[storeId, month, year, productType]" in page_source
    assert "replaceBusinessFiltersInUrl" in page_source


def test_store_finance_filters_follow_the_product_type_contract() -> None:
    for path in ["pages/StoreRankingPage.tsx", "pages/StoreSettlementPage.tsx", "pages/OrderDetailsPage.tsx"]:
        source = read_source(path)
        assert 'label="产品范围"' not in source
        assert 'label="商品类型"' in source
        assert "initialStatementMonth(searchParams)" in source
        assert "replaceBusinessFiltersInUrl" in source
        assert "productScope" not in source
    assert '"product_scope"' not in read_source("utils/settlement.ts")


def test_clue_types_come_from_metadata_and_douyin_keeps_its_scope_contract() -> None:
    clues = read_source("pages/ClueCenterPage.tsx")
    assert "meta?.product_types" in clues
    assert 'value: "jingcheng"' not in clues
    assert 'value: "byd"' not in clues
    ranking = read_source("pages/DouyinRankingPage.tsx")
    export = read_source("components/DouyinRankingExportDialog.tsx")
    assert '["all", "jingcheng", "byd"]' in ranking
    assert "productScope={productScope}" in ranking
    assert "productScope, periodStart" in export


def test_product_type_editor_accepts_custom_values_with_existing_suggestions() -> None:
    page_source = read_source("pages/AdminProductTypeVisibilityPage.tsx")

    assert 'list="product-type-suggestions"' in page_source
    assert 'id="product-type-suggestions"' in page_source
    assert "可输入新值，也可选择已有建议" in page_source
    assert 'placeholder="输入或选择商品类型"' in page_source


def test_product_configuration_payloads_never_send_scope() -> None:
    page = read_source("pages/AdminProductTypeVisibilityPage.tsx")
    panel = read_source("components/AdminSkuGovernancePanel.tsx")
    assert "productType: typeValue.trim()" in page
    assert "payload.productScope" not in page
    assert "productScope:" not in panel
    assert "skuId、productType" in page
    assert "精诚养车商品统一归类为精诚养车" in page
    assert "await loadRows()" in page
    assert "await loadProducts()" in panel
    assert "options.fallbackOnError !== true" in read_source("api/client.ts")
