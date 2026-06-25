from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_SYSTEM_DIR = REPO_ROOT / "docs" / "design-system"
TOKENS_PATH = DESIGN_SYSTEM_DIR / "tokens.json"
HTML_PATH = DESIGN_SYSTEM_DIR / "index.html"
APP_STYLES_PATH = REPO_ROOT / "apps" / "web" / "src" / "styles.css"
DESIGN_TOKENS_CSS_PATH = REPO_ROOT / "apps" / "web" / "src" / "design-tokens.css"
WEB_PACKAGE_PATH = REPO_ROOT / "apps" / "web" / "package.json"
SOLAR_ICON_PATH = REPO_ROOT / "apps" / "web" / "src" / "components" / "SolarIcon.tsx"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_tokens() -> dict:
    return json.loads(read_text(TOKENS_PATH))


def css_variable_value(source: str, variable_name: str) -> str:
    match = re.search(rf"{re.escape(variable_name)}:\s*([^;]+);", source)
    assert match, f"{variable_name} should exist in CSS"
    return " ".join(match.group(1).split())


def test_design_system_artifacts_exist_and_identify_their_status() -> None:
    tokens = load_tokens()
    html = read_text(HTML_PATH)

    assert tokens["meta"]["version"] == "0.1.0"
    assert tokens["meta"]["status"] == "draft"
    assert tokens["meta"]["colorMode"] == "light-only"
    assert tokens["meta"]["darkModeStatus"] == "not-supported-in-v0.1"
    assert "抖音经营数据引擎 UI 设计规范 V0.1" in html
    assert "Draft" in html
    assert "模式：浅色优先" in html
    assert "本阶段只固化浅色模式" in html
    assert "更新：2026-06-25" in html
    assert "docs/design-system/tokens.json" in html
    assert "Lorem" not in html


def test_core_app_css_tokens_match_design_system_tokens() -> None:
    tokens = load_tokens()["tokens"]
    runtime_tokens = read_text(DESIGN_TOKENS_CSS_PATH)
    styles = read_text(APP_STYLES_PATH)

    assert '@import "./design-tokens.css";' in styles

    app_variables = [
        ("--bg", tokens["color"]["bg"]["value"]),
        ("--surface", tokens["color"]["surface"]["value"]),
        ("--surface-muted", tokens["color"]["surfaceMuted"]["value"]),
        ("--surface-subtle", tokens["color"]["surfaceSubtle"]["value"]),
        ("--ink", tokens["color"]["ink"]["value"]),
        ("--muted", tokens["color"]["muted"]["value"]),
        ("--line", tokens["color"]["line"]["value"]),
        ("--line-strong", tokens["color"]["lineStrong"]["value"]),
        ("--green", tokens["color"]["green"]["value"]),
        ("--green-soft", tokens["color"]["greenSoft"]["value"]),
        ("--blue", tokens["color"]["blue"]["value"]),
        ("--blue-soft", tokens["color"]["blueSoft"]["value"]),
        ("--amber", tokens["color"]["amber"]["value"]),
        ("--amber-soft", tokens["color"]["amberSoft"]["value"]),
        ("--danger", tokens["color"]["danger"]["value"]),
        ("--target-min", tokens["control"]["targetMin"]["value"]),
        ("--touch-target", tokens["control"]["touchTarget"]["value"]),
        ("--workspace-topbar-height", tokens["layout"]["workspaceTopbarHeight"]["value"]),
        ("--workspace-subnav-height", tokens["layout"]["workspaceSubnavHeight"]["value"]),
        ("--table-sticky-gap", tokens["layout"]["tableStickyGap"]["value"]),
        ("--z-table-sticky-column", str(tokens["zIndex"]["tableStickyColumn"]["value"])),
        ("--z-table-header", str(tokens["zIndex"]["tableHeader"]["value"])),
        ("--z-table-header-corner", str(tokens["zIndex"]["tableHeaderCorner"]["value"])),
        ("--focus-ring", tokens["shadow"]["focusRing"]["value"]),
        ("--shadow", tokens["shadow"]["shadow"]["value"]),
        ("--shadow-soft", tokens["shadow"]["shadowSoft"]["value"]),
    ]

    for variable_name, expected_value in app_variables:
        assert css_variable_value(runtime_tokens, variable_name) == expected_value


def test_design_system_html_renders_key_decision_surfaces() -> None:
    html = read_text(HTML_PATH)

    required_sections = [
        'id="workflow"',
        'id="color"',
        'id="typography"',
        'id="spacing-radius"',
        'id="components"',
        'id="iconography"',
        'id="table-sticky"',
        'id="mobile-card"',
        'id="page-templates"',
        'id="decisions"',
        'id="enforcement"',
    ]
    for section in required_sections:
        assert section in html

    assert html.count('class="token-card"') >= 15
    assert html.count('class="component-card"') >= 4
    assert "color-scheme: light;" in html
    assert "color-scheme: light dark" not in html
    assert "prefers-color-scheme" not in html
    assert 'class="button-like primary"' in html
    assert 'class="button-like is-disabled"' in html
    assert '<span class="button-like' not in html
    assert '<button class="mobile-filter-button" type="button">筛选</button>' in html
    assert "height: 38px;" in html
    assert "max-height: 38px;" in html
    assert 'class="field-control field-control--select field-control--focus"' in html
    assert 'class="field-control field-control--error"' in html
    assert 'class="select-indicator" aria-hidden="true"' in html
    assert "select.field::-ms-expand" in html
    assert "field-chevron" not in html
    assert 'class="field-error" role="alert"' in html
    assert "控件文字不用粗体，避免像按钮" in html
    assert 'class="status-row"' in html
    assert "min-height: 26px;" in html
    assert "@iconify/react" in html
    assert "@iconify-icons/solar" in html
    assert "apps/web/src/components/SolarIcon.tsx" in html
    assert "默认变体为 Solar" in html
    assert "bold-duotone" in html
    assert "cluesLine" in html
    assert "线索表格冻结表头" in html
    assert "--table-sticky-gap: 8px" in html
    assert "topbar 82px + subnav 51px + gap 8px" in html
    assert 'class="sticky-demo-shell"' in html
    assert 'class="sticky-offset-demo"' in html
    assert 'class="table-preview-wrap table-preview-wrap--sticky"' in html
    assert "max-height: 248px;" in html
    assert "top: var(--table-sticky-top);" not in html
    assert "移动端线索卡片" in html
    assert "桌面 38px，移动 44px" in html


def test_design_system_html_does_not_depend_on_remote_assets() -> None:
    html = read_text(HTML_PATH)

    assert "https://" not in html
    assert "http://" not in html
    assert "../../apps/web/public/business-engine-icon.svg" in html
    assert "business-loop-icon.svg" not in html


def test_design_system_icon_rules_match_current_frontend_icon_stack() -> None:
    tokens = load_tokens()
    html = read_text(HTML_PATH)
    package_json = json.loads(read_text(WEB_PACKAGE_PATH))
    solar_icon = read_text(SOLAR_ICON_PATH)

    dependencies = package_json["dependencies"]
    assert "@iconify/react" in dependencies
    assert "@iconify-icons/solar" in dependencies

    icon_tokens = tokens["tokens"]["icon"]
    assert icon_tokens["library"]["value"] == "@iconify/react"
    assert icon_tokens["family"]["value"] == "@iconify-icons/solar"
    assert icon_tokens["componentEntry"]["value"] == "apps/web/src/components/SolarIcon.tsx"
    assert icon_tokens["variantSelection"]["default"] == "linear"
    assert icon_tokens["variantSelection"]["emphasis"] == "bold-duotone"
    assert icon_tokens["variantSelection"]["namingRule"].endswith("cluesLine and clues.")

    assert "chatRoundDotsLinear" in solar_icon
    assert "chatRoundDotsBoldDuotone" in solar_icon
    assert "cluesLine" in solar_icon
    assert "clues" in solar_icon
    assert "@iconify/react" in html
