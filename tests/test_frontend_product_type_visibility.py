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

    assert "商品口径控制" in page_source
    assert "启用商品类型限制" in page_source
    assert "产品范围" in page_source
    assert "默认显示范围" in page_source
    assert "全部选择" in page_source
    assert "清空选择" in page_source
    assert "保存口径" in page_source
    assert "fetchProductTypeVisibility" in page_source
    assert "saveProductTypeVisibility" in page_source
    assert "product-type-option-grid" in page_source
    assert "selectedProductScopes" in page_source
    assert "visible_product_scopes" in page_source
    assert "product_scope_type_map" in page_source

    assert "export interface ProductTypeVisibilityData" in types_source
    assert "export interface ProductTypeVisibilityUpdate" in types_source
    assert "visible_product_scopes" in types_source
    assert "available_product_scopes" in types_source
    assert "product_scope_type_map" in types_source
    assert "default_product_type" in types_source
    assert "export async function fetchProductTypeVisibility" in client_source
    assert 'requestJson<ProductTypeVisibilityData>("/admin/product-type-visibility")' in client_source
    assert "export async function saveProductTypeVisibility" in client_source
    assert "/admin/product-type-visibility" in client_source

    assert ".product-visibility-panel" in styles_source
    assert ".product-type-option-grid" in styles_source
    assert ".product-type-option.is-selected" in styles_source


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


def test_sales_dashboard_has_product_scope_filter_before_product_type() -> None:
    page_source = read_source("pages/SalesDashboardPage.tsx")
    client_source = read_source("api/client.ts")
    options_source = read_source("utils/options.ts")
    types_source = read_source("types/dashboard.ts")

    assert 'label="产品范围"' in page_source
    assert page_source.index('label="产品范围"') < page_source.index(
        'label="商品类型"'
    )
    assert "productScopeOptions(meta, activeProductScope)" in page_source
    assert "productOptionsForScope(" in page_source
    assert "productScope: activeProductScope" in page_source
    assert "product_scope: productScope" in client_source
    assert "product_scopes?: string[]" in types_source
    assert "product_scope_type_map?: Record<string, string[]>" in types_source
    assert "export function productScopeOptions" in options_source
    assert "export function productOptionsForScope" in options_source


def test_settlement_pages_have_product_scope_before_product_type_filters() -> None:
    ranking_source = read_source("pages/StoreRankingPage.tsx")
    settlement_source = read_source("pages/StoreSettlementPage.tsx")
    details_source = read_source("pages/OrderDetailsPage.tsx")
    client_source = read_source("api/client.ts")
    types_source = read_source("types/dashboard.ts")
    utils_source = read_source("utils/settlement.ts")

    for source in [ranking_source, settlement_source]:
        assert 'label="产品范围"' in source
        assert 'label="商品类型"' in source
        assert source.index('label="产品范围"') < source.index('label="商品类型"')
        assert "meta?.productScopeTypeMap[productScope]" in source
        assert "meta?.productTypes" in source

    assert "productScope," in ranking_source
    assert "productScope," in settlement_source
    assert 'searchParams.get("productScope")' in details_source
    assert 'searchParams.get("productType")' in details_source
    assert "productScope," in details_source
    assert "productType," in details_source
    assert "product_scope: productScope" in client_source
    assert "productScope: string;" in client_source
    assert "productScope: string;" in types_source
    assert "product_scope?: string;" in types_source
    assert '"product_scope"' in utils_source
