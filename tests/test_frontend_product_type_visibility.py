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
    assert 'label: "商品口径", icon: "filter"' in shell_source
    assert 'href: "/admin/product-types"' in home_source

    assert "商品口径控制" in page_source
    assert "启用商品类型限制" in page_source
    assert "全部选择" in page_source
    assert "清空选择" in page_source
    assert "保存口径" in page_source
    assert "fetchProductTypeVisibility" in page_source
    assert "saveProductTypeVisibility" in page_source
    assert "product-type-option-grid" in page_source

    assert "export interface ProductTypeVisibilityData" in types_source
    assert "export interface ProductTypeVisibilityUpdate" in types_source
    assert "export async function fetchProductTypeVisibility" in client_source
    assert 'requestJson<ProductTypeVisibilityData>("/admin/product-type-visibility")' in client_source
    assert "export async function saveProductTypeVisibility" in client_source
    assert "/admin/product-type-visibility" in client_source

    assert ".product-visibility-panel" in styles_source
    assert ".product-type-option-grid" in styles_source
    assert ".product-type-option.is-selected" in styles_source
