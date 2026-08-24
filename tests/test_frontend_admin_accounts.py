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


def test_account_creation_requires_confirmation_and_masks_password() -> None:
    page_source = read_source("pages/AdminAccountsPage.tsx")

    assert 'title="新建账号信息确认"' in page_source
    assert "pendingCreatePayload" in page_source
    assert "confirmCreateAccount" in page_source
    assert "showCreatePassword" in page_source
    assert "显示密码" in page_source
    assert "隐藏密码" in page_source
    assert "返回修改" in page_source
    assert "确认创建" in page_source
    assert page_source.index("const handleSave") < page_source.index(
        "const confirmCreateAccount"
    )
    handle_save = page_source[
        page_source.index("const handleSave") : page_source.index(
            "const confirmCreateAccount"
        )
    ]
    assert "createAccount(" not in handle_save


def test_account_list_owns_its_scroll_region() -> None:
    page_source = read_source("pages/AdminAccountsPage.tsx")
    styles_source = read_source("styles.css")

    assert 'className="account-admin-main__scroll"' in page_source
    assert ".account-admin-main__scroll" in styles_source
    scroll_styles = styles_source[
        styles_source.index(".account-admin-main__scroll") :
        styles_source.index(".account-editor")
    ]
    assert "overflow: auto" in scroll_styles
    assert "max-height:" in scroll_styles


def test_account_create_hides_technical_username_and_supports_store_batch_selection() -> None:
    page_source = read_source("pages/AdminAccountsPage.tsx")
    types_source = read_source("types/dashboard.ts")

    create_form = page_source[
        page_source.index('<form className="content-section account-form"') :
        page_source.index("{editingAccount &&")
    ]
    confirmation = page_source[page_source.index('title="新建账号信息确认"') :]

    assert "<span>账号名</span>" not in create_form
    assert "<dt>账号名</dt>" not in confirmation
    assert "username?: string" in types_source
    assert "storeQuery" in page_source
    assert "filteredStores" in page_source
    assert "selectedStoreIds" in page_source
    assert "selectedStores" in page_source
    assert "[...selectedStores, ...filteredStores]" in page_source
    assert "importAccountStores" in page_source
    assert "下载门店导入模板" in page_source
    assert "批量导入门店" in page_source
    assert "门店名称或门店 ID" in page_source
    assert "指定门店" in confirmation


def test_account_editor_owns_an_independent_scroll_region() -> None:
    styles_source = read_source("styles.css")
    editor_styles = styles_source[
        styles_source.index(".account-editor {") :
        styles_source.index(".account-form {")
    ]

    assert "max-height:" in editor_styles
    assert "overflow-y: auto" in editor_styles
    assert "overscroll-behavior: contain" in editor_styles
