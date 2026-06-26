from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_admin_accounts_page_lists_unactivated_stores() -> None:
    page_source = read_source("pages/AdminAccountsPage.tsx")
    client_source = read_source("api/client.ts")
    types_source = read_source("types/dashboard.ts")

    assert "fetchUnactivatedAccountStores" in client_source
    assert '"/admin/accounts/unactivated-stores"' in client_source
    assert "UnactivatedStoreAccountRow" in types_source
    assert "unactivatedStoreColumns" in page_source
    assert "未激活门店" in page_source
    assert "所属账户ID/POI ID" in page_source
    assert "account_ids" in page_source
    assert "poi_ids" in page_source
