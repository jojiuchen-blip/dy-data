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
    assert "所属账户编号或门店位置编号（POI ID）" in page_source
    assert "account_ids" in page_source
    assert "poi_ids" in page_source


def test_dydata32_account_permission_page_uses_live_api() -> None:
    app_source = read_source("App.tsx")
    page_source = read_source("pages/AdminAccountsPage.tsx")
    shell_source = read_source("components/Shell.tsx")
    client_source = read_source("api/client.ts")
    types_source = read_source("types/dashboard.ts")

    assert "AdminAccountsDydata32PreviewPage" not in app_source
    assert 'searchParams.get("preview")' not in app_source
    assert "hasPageAccess" in app_source
    assert "page_keys" in shell_source
    assert "fetchAccessControl" in page_source
    assert "updateAccountPagePermissions" in page_source
    assert "updateRolePagePermissions" in page_source
    assert "fetchAccountPermissionAuditLogs" in page_source
    assert "变更记录" in page_source
    assert "actorUsername" in page_source
    assert "createdFrom" in page_source
    assert "createdTo" in page_source
    assert "操作类型" in page_source
    assert '"/admin/access-control"' in client_source
    assert "/page-permissions" in client_source
    assert "AccessControlData" in types_source
    assert "effective_page_keys" in types_source
