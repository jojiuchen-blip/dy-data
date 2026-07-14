from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_activation_form_has_field_guidance_copy_and_focus_bindings() -> None:
    source = read_source("pages/AuthPage.tsx")

    assert "activationFieldHints" in source
    assert "activeActivationHint" in source
    assert "所属账户编号或门店位置编号（POI ID）" in source
    assert "账号名、所属账户编号或门店位置编号（POI ID）" in source
    assert "抖音来客电脑端右上角个人头像下方的“账户 ID”" in source
    assert "手机端“我的-个人中心-我的账户 ID”" in source
    assert "也可以填写对应门店的位置编号（POI ID）" in source
    assert "抖音来客账号绑定的公司主体全名" in source
    assert source.count("自行设置") >= 3

    for field in (
        "external_account_id",
        "certified_subject_name",
        "username",
        "display_name",
        "password",
        "password_confirm",
    ):
        assert f'setActiveActivationHint("{field}")' in source


def test_activation_guidance_card_has_layout_styles() -> None:
    source = read_source("styles.css")

    assert ".auth-shell--with-help" in source
    assert ".auth-help-card" in source
    assert ".auth-help-card__eyebrow" in source
    assert "grid-template-columns: minmax(0, 520px) minmax(300px, 420px)" not in source
    assert "position: fixed;" in source
