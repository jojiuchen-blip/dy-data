from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"
PUBLIC_GUIDE = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "public"
    / "account-activation-guide"
)


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_activation_guide_is_a_public_auth_independent_page() -> None:
    guide_html = (PUBLIC_GUIDE / "index.html").read_text(encoding="utf-8")

    assert "账号激活指引" in guide_html
    assert "正在检查登录状态" not in guide_html
    assert "/auth/me" not in guide_html
    assert (PUBLIC_GUIDE / "output" / "pdf" / "account-activation-guide.pdf").is_file()


def test_activation_form_uses_two_step_identity_check_flow() -> None:
    source = read_source("pages/AuthPage.tsx")

    assert "activationFieldHints" in source
    assert "activeActivationHint" in source
    assert 'useState<ActivationStep>("identity")' in source
    assert "账户所属ID" in source
    assert "所属账户关联 POI ID" in source
    assert "激活状态核验" in source
    assert "账户所属ID和所属账户关联POI ID不正确" in source
    assert "账户已激活过，需要前往账户登录" in source
    assert "前往账户登录" in source
    assert "checkAccountActivationStatus" in source
    assert 'result.data.status === "ready"' in source
    assert 'result.data.status === "activated"' in source

    for field in ("external_account_id", "poi_id"):
        assert f'setActiveActivationHint("{field}")' in source

    assert "【店铺管理】-【抖音号管理】-【子机构经营号】" in source
    assert "【导出数据】" in source
    assert "【账户所属id】" in source
    assert "【所属账户关联poi_id】" in source


def test_activation_credentials_step_has_restricted_username_and_guide_link() -> None:
    source = read_source("pages/AuthPage.tsx")

    assert "账号名只能使用数字和英文字母。" in source
    assert "/^[A-Za-z0-9]+$/" in source
    assert "返回修改门店信息" in source
    assert "设置账号并完成激活" in source
    assert "查看账号激活指引" in source
    assert 'href="/account-activation-guide/index.html"' in source
    assert 'target="_blank"' in source
    assert 'rel="noreferrer"' in source

    activation_branch = source.split('activationStep === "identity"', maxsplit=1)[1]
    assert "显示名称" not in activation_branch
    assert "认证主体全称" not in activation_branch


def test_password_reset_uses_dual_id_check_before_password_change() -> None:
    source = read_source("pages/AuthPage.tsx")

    assert 'mode === "reset"' in source
    assert 'useState<ResetStep>("identity")' in source
    assert "账户尚未激活，请先完成账号激活" in source
    assert source.count('result.data.status === "activated"') >= 2
    assert "resetAccountPassword" in source

    reset_branch = source.split(') : mode === "reset" ? (', maxsplit=1)[1]
    reset_branch = reset_branch.split(') : activationStep === "identity" ?', maxsplit=1)[0]
    assert "账户所属ID" in reset_branch
    assert "所属账户关联 POI ID" in reset_branch
    assert "认证主体全称" not in reset_branch
    assert "显示名称" not in reset_branch


def test_activation_guidance_card_has_layout_styles() -> None:
    source = read_source("styles.css")

    assert ".auth-shell--with-help" in source
    assert ".auth-help-card" in source
    assert ".auth-help-card__eyebrow" in source
    assert ".auth-field-label" in source
    assert ".auth-help-trigger" in source
    assert ".auth-activation-actions" in source
    assert "grid-template-columns: minmax(0, 520px) minmax(300px, 420px)" not in source
    assert "position: fixed;" in source
