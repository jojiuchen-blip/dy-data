from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_SYSTEM_DIR = REPO_ROOT / "docs" / "design-system"
TOKENS_PATH = DESIGN_SYSTEM_DIR / "tokens.json"
HTML_PATH = DESIGN_SYSTEM_DIR / "index.html"
CANDIDATE_TOKENS_PATH = DESIGN_SYSTEM_DIR / "tokens.v0.2-candidate.json"
CANDIDATE_HTML_PATH = DESIGN_SYSTEM_DIR / "candidate-v0.2.html"
TERTIARY_PLAN_PATH = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-07-13-dydata-v02-tertiary-navigation.md"
)
APP_STYLES_PATH = REPO_ROOT / "apps" / "web" / "src" / "styles.css"
DESIGN_TOKENS_CSS_PATH = REPO_ROOT / "apps" / "web" / "src" / "design-tokens.css"
WEB_PACKAGE_PATH = REPO_ROOT / "apps" / "web" / "package.json"
SOLAR_ICON_PATH = REPO_ROOT / "apps" / "web" / "src" / "components" / "SolarIcon.tsx"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_tokens() -> dict:
    return json.loads(read_text(TOKENS_PATH))


def test_v02_is_the_active_runtime_design_system() -> None:
    tokens = load_tokens()
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))
    html = read_text(HTML_PATH)

    assert tokens["meta"] == {
        "name": "dy-data UI Design System",
        "version": "0.2.0",
        "status": "active",
        "lastUpdated": "2026-07-13",
        "language": "zh-CN",
        "colorMode": "light-only",
        "darkModeStatus": "not-supported-in-v0.2",
        "sourceOfTruth": "docs/design-system/tokens.json",
        "currentImplementationSource": "apps/web/src/design-tokens.css",
        "purpose": "Provide the formal V0.2 design system and runtime contract for dy-data product UI.",
        "issue": "DYDATA-4",
        "relatedIssues": ["DYDATA-3", "DYDATA-5"],
        "stage": "runtime-active",
        "runtimeApplied": True,
    }

    colors = tokens["tokens"]["color"]
    assert colors["brandDeepOrange"]["value"] == "#d63b00"
    assert colors["brandDeepOrangeHover"]["value"] == "#c73700"
    assert colors["brandDeepOrangeActive"]["value"] == "#ad3000"
    assert colors["brandOrange"]["value"] == "#fe5205"
    assert colors["brandOrangeSoft"]["value"] == "#fff4ef"
    assert colors["ink"]["value"] == "#181818"
    assert colors["surfaceMuted"]["value"] == "#f2f2ee"
    assert colors["green"]["role"] == "Success and verified state"
    assert colors["greenSoft"]["role"] == "Success and verified background"
    assert all(
        not color["role"].startswith("Candidate")
        for color in colors.values()
        if "role" in color
    )
    principles = json.dumps(tokens["principles"], ensure_ascii=False)
    assert "V0.1 只固化" not in principles
    assert "候选品牌橙" not in principles

    components = tokens["components"]
    assert components["button"]["secondaryBorder"] == colors["lineStrong"]["value"]
    assert components["field"]["border"] == colors["lineStrong"]["value"]
    assert "Solar chevronDown" in components["field"]["selectIndicator"]
    assert "CSS or text chevron" in components["field"]["selectIndicator"]

    assert colors["green"]["value"] == candidate["tokens"]["color"]["green"]["value"]
    assert colors["blue"]["value"] == candidate["tokens"]["color"]["blue"]["value"]
    assert colors["amber"]["value"] == candidate["tokens"]["color"]["amber"]["value"]
    assert colors["danger"]["value"] == candidate["tokens"]["color"]["danger"]["value"]

    assert "dy-data UI 设计规范 V0.2" in html
    assert "状态：active" in html
    assert "源文件：tokens.json" in html
    assert "PREVIEW ONLY" not in html
    assert "pending-human-approval" not in html
    assert candidate["meta"]["status"] == "pending-human-approval"
    assert candidate["meta"]["runtimeApplied"] is False


def css_variable_value(source: str, variable_name: str) -> str:
    match = re.search(rf"{re.escape(variable_name)}:\s*([^;]+);", source)
    assert match, f"{variable_name} should exist in CSS"
    return " ".join(match.group(1).split())


def test_formal_v02_artifacts_identify_the_active_runtime_contract() -> None:
    tokens = load_tokens()
    html = read_text(HTML_PATH)

    assert tokens["meta"]["version"] == "0.2.0"
    assert tokens["meta"]["status"] == "active"
    assert tokens["meta"]["colorMode"] == "light-only"
    assert tokens["meta"]["darkModeStatus"] == "not-supported-in-v0.2"
    assert "dy-data UI 设计规范 V0.2" in html
    assert "状态：active" in html
    assert "模式：light-only" in html
    assert "更新：2026-07-13" in html
    assert "源文件：tokens.json" in html
    assert "PREVIEW ONLY" not in html
    assert "pending-human-approval" not in html
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
        ("--brand-deep-orange", tokens["color"]["brandDeepOrange"]["value"]),
        ("--brand-deep-orange-hover", tokens["color"]["brandDeepOrangeHover"]["value"]),
        ("--brand-deep-orange-active", tokens["color"]["brandDeepOrangeActive"]["value"]),
        ("--brand-orange", tokens["color"]["brandOrange"]["value"]),
        ("--brand-orange-soft", tokens["color"]["brandOrangeSoft"]["value"]),
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
        ("--shadow-none", tokens["shadow"]["shadowNone"]["value"]),
        ("--shadow-card", tokens["shadow"]["shadowCard"]["value"]),
        ("--shadow-popover", tokens["shadow"]["shadowPopover"]["value"]),
        ("--shadow-dialog", tokens["shadow"]["shadowDialog"]["value"]),
        ("--shadow-workbench", tokens["shadow"]["shadowWorkbench"]["value"]),
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
        'id="clue-followup-workbench"',
        'id="clue-followup-mobile-detail"',
        'id="page-templates"',
        'id="decisions"',
        'id="enforcement"',
    ]
    for section in required_sections:
        assert section in html

    assert html.count('class="token-card"') >= 12
    assert html.count('class="component-card"') >= 4
    assert "color-scheme: light;" in html
    assert "color-scheme: light dark" not in html
    assert "prefers-color-scheme" not in html
    assert 'class="button-like primary"' in html
    assert 'class="button-like is-disabled"' in html
    assert '<span class="button-like' not in html
    assert '<button class="mobile-filter-trigger" type="button"' in html
    assert "height: 38px;" in html
    assert "max-height: 38px;" in html
    assert 'class="field-control field-control--select field-control--focus"' in html
    assert 'class="field-control field-control--error"' in html
    assert 'data-solar-icon="chevronDown"' in html
    assert '<span class="select-indicator"' not in html
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
    assert "action bar 58px + gap 8px" in html
    assert "移动端 top subnav 为 DYDATA-5 未来范围" in html
    assert "明细工作台页面模板" in html
    assert "page-frame--data-workspace" in html
    assert 'class="data-workspace-demo__result"' in html
    assert "外层页面不纵向滚动" in html
    assert "分页始终在结果区底部可见" in html
    assert "TablePagination / DataPager" in html
    assert "显示 1-50 / 共 22,332 条" in html
    assert "每页 50 条" in html
    assert 'aria-label="输入页码"' in html
    assert 'max="447"' in html
    assert "跳转</button>" in html
    assert "请输入 1-447 之间的页码" in html
    assert "移动端保留页码输入，按 Enter 跳转" in html
    assert "分页属于结果区，不放进表格滚动容器" in html
    assert "页码输入只允许 1 到总页数之间的正整数" in html
    assert "DYDATA-5 未来移动明细页面模板" in html
    assert "新增明细长表" in html
    assert "action bar 58px + subnav 51px + gap 8px" not in html
    assert 'class="sticky-demo-shell"' in html
    assert 'class="sticky-offset-demo"' in html
    assert 'class="table-preview-wrap table-preview-wrap--sticky"' in html
    assert "max-height: 248px;" in html
    assert "top: var(--table-sticky-top);" not in html
    assert "移动端线索卡片" in html
    assert "桌面 38px，移动 44px" in html
    assert "线索跟进详情工作台浮层" in html
    assert "width: min(1440px, 100vw - 48px)" in html
    assert "height: min(920px, calc(100dvh - 32px))" in html
    assert "联系方式 · 号码操作" in html
    assert "订单编号" in html
    assert "下单时间" in html
    assert "线索跟进历史" in html
    assert "分配轮次与跟进历史" not in html
    assert "2 轮 · 3 条跟进记录" in html
    assert "号码操作" in html
    assert "跟进操作" in html
    assert "未接通也算产生跟进行为" in html
    assert "失效、已核销、已退款时显示“已失效不可跟进”" in html
    assert "店端：" in html
    assert "不展示内部轮次 ID" in html
    mobile_detail_section = html.split('id="clue-followup-mobile-detail"', 1)[1].split(
        'id="page-templates"', 1
    )[0]
    assert "移动端线索详情" in mobile_detail_section
    assert 'class="mobile-clue-detail-demo"' in mobile_detail_section
    assert "手机号与状态" in mobile_detail_section
    assert "保存本次跟进" in mobile_detail_section
    assert "第2轮 / 当前" in mobile_detail_section
    assert "2轮 · 3条记录" in mobile_detail_section
    assert "移动端实现规则" in mobile_detail_section
    assert "实时数据" not in mobile_detail_section


def test_design_system_html_does_not_depend_on_remote_assets() -> None:
    html = read_text(HTML_PATH)

    assert "https://" not in html
    assert "http://" not in html
    assert 'class="solar-icon-sprite"' in html
    assert "business-engine-icon.svg" not in html
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


def test_candidate_design_system_is_machine_readable_and_preview_only() -> None:
    active = load_tokens()
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))

    assert set(candidate) >= {
        "meta",
        "principles",
        "tokens",
        "components",
        "pageTemplates",
        "enforcement",
        "candidateDecision",
        "approvalGate",
    }
    assert candidate["meta"]["name"] == "dy-data UI Design System Candidate"
    assert candidate["meta"]["version"] == "0.2.0-candidate"
    assert candidate["meta"]["status"] == "pending-human-approval"
    assert candidate["meta"]["issue"] == "DYDATA-3"
    assert candidate["meta"]["stage"] == "design-system-preview-only"
    assert candidate["meta"]["runtimeApplied"] is False
    assert candidate["meta"]["colorMode"] == "light-only"
    assert set(candidate["tokens"]) == set(active["tokens"])
    assert set(active["components"]) <= set(candidate["components"])
    assert set(active["pageTemplates"]) <= set(candidate["pageTemplates"])

    palette = candidate["candidateDecision"]["palette"]
    expected_palette = {
        "deepOrange": "#d63b00",
        "orange": "#fe5205",
        "softOrange": "#fff4ef",
        "black": "#181818",
        "gray": "#686a66",
        "softGray": "#f2f2ee",
        "white": "#ffffff",
    }
    assert {name: token["value"] for name, token in palette.items()} == expected_palette

    primary_button = candidate["candidateDecision"]["primaryButton"]
    assert primary_button["rest"] == "#d63b00"
    assert primary_button["hover"] == "#c73700"
    assert primary_button["active"] == "#ad3000"
    assert primary_button["focus"] == "#fe5205"
    assert primary_button["disabledBackground"] == "#dadbd6"
    assert primary_button["disabledText"] == "#8a8c87"
    assert primary_button["loadingRule"] == "Preserve width and prevent duplicate submission"

    semantic_boundary = candidate["candidateDecision"]["semanticBoundary"]
    assert semantic_boundary == {
        "success": "Keep active V0.1 green tokens",
        "warning": "Keep active V0.1 amber tokens",
        "error": "Keep active V0.1 danger tokens",
        "info": "Keep active V0.1 blue tokens",
    }

    gate = candidate["approvalGate"]
    assert gate["requiredLinearConfirmation"] == "确认进入阶段 2"
    assert gate["blockedIssue"] == "DYDATA-4"
    assert "apps/web/src/design-tokens.css" in gate["runtimeFilesExcluded"]
    assert "apps/web/src" in gate["runtimeFilesExcluded"]

    colors = candidate["tokens"]["color"]
    assert colors["ink"]["value"] == "#181818"
    assert colors["muted"]["value"] == "#686a66"
    assert colors["surfaceMuted"]["value"] == "#f2f2ee"
    assert colors["brandDeepOrange"]["value"] == "#d63b00"
    assert colors["brandOrange"]["value"] == "#fe5205"
    assert colors["brandOrangeSoft"]["value"] == "#fff4ef"
    assert colors["green"]["value"] == active["tokens"]["color"]["green"]["value"]
    assert colors["blue"]["value"] == active["tokens"]["color"]["blue"]["value"]
    assert colors["amber"]["value"] == active["tokens"]["color"]["amber"]["value"]
    assert colors["danger"]["value"] == active["tokens"]["color"]["danger"]["value"]
    assert candidate["components"]["button"]["primaryBackground"] == "#d63b00"
    assert candidate["components"]["field"]["background"] == "#ffffff"
    assert candidate["components"]["dataTable"]["headerBackground"] == "#f2f2ee"
    assert candidate["components"]["metricCard"]["states"] == [
        "standard",
        "primary",
        "semantic",
        "loading",
    ]
    assert candidate["components"]["navigation"]["mobileBottomItems"] == [
        "数据表现",
        "结算",
        "线索",
        "后台",
    ]
    shadows = candidate["tokens"]["shadow"]
    assert {
        "shadowNone",
        "shadowCard",
        "shadowPopover",
        "shadowDialog",
        "shadowWorkbench",
    } <= set(shadows)
    assert all(
        "rgb(24 24 24 /" in shadows[token]["value"] or shadows[token]["value"] == "none"
        for token in (
            "shadowNone",
            "shadowCard",
            "shadowPopover",
            "shadowDialog",
            "shadowWorkbench",
        )
    )
    assert candidate["candidateDecision"]["brandMark"] == {
        "outerTile": "#fff4ef",
        "tileSize": "56px",
        "primary": "#d63b00",
        "accent": "#fe5205",
        "rule": "Use the enlarged trend and status-node mark centered in a soft orange rounded square.",
    }


def test_candidate_html_renders_palette_states_components_and_approval_gate() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    required_content = [
        "dy-data UI 设计规范 V0.2 候选版",
        "DYDATA-3",
        "待人工确认",
        "#D63B00",
        "#FE5205",
        "#FFF4EF",
        "#181818",
        "#686A66",
        "#F2F2EE",
        "#FFFFFF",
        "Rest",
        "Hover",
        "Active",
        "Focus",
        "Disabled",
        "Loading",
        "真实界面样板",
        "线索看板",
        "应用筛选",
        "下一页",
        "语义色保持原义",
        "确认进入阶段 2",
        "当前业务 UI 不会在本阶段切换",
    ]
    for phrase in required_content:
        assert phrase in html

    complete_sections = [
        "规范如何生效",
        "颜色 token",
        "排版层级",
        "间距与圆角",
        "组件家族",
        "图标体系",
        "线索表格冻结表头",
        "移动端线索卡片",
        "线索跟进详情工作台浮层",
        "移动端线索详情",
        "页面骨架",
        "决策记录",
        "协作约束",
    ]
    complete_components = [
        "IconButton",
        "Select 展开态",
        "StatusChip",
        "CountPill",
        "FilterChip",
        "RoleBadge",
        "Dialog / ConfirmDialog",
        "DataTable",
        "TablePagination / DataPager",
        "Solar 图标选择矩阵",
        "标准指标",
        "重点指标",
        "语义指标",
        "加载指标",
        "NavigationItem",
        "层级与阴影",
        "数据表现",
    ]
    for phrase in complete_sections + complete_components:
        assert phrase in html

    assert "color-scheme: light;" in html
    assert "prefers-color-scheme" not in html
    assert "https://" not in html
    assert "http://" not in html
    assert html.count("<h1") == 1
    assert html.count('rel="icon"') == 1
    assert 'class="candidate-brand-mark solar-icon-sample"' in html
    assert 'data-solar-icon="brand"' in html
    assert "business-engine-icon.svg" not in html


def test_candidate_table_uses_candidate_neutral_surface_tokens() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    table_header = re.search(r"\.table-preview th \{(?P<css>.*?)\n\s*\}", html, re.DOTALL)
    table_cell_blocks = re.findall(
        r"\.table-preview td \{(?P<css>.*?)\n\s*\}", html, re.DOTALL
    )
    table_hover = re.search(
        r"\.table-preview tbody tr:hover td \{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    decision_header = re.search(r"\.decision-table th \{(?P<css>.*?)\n\s*\}", html, re.DOTALL)

    assert table_header is not None
    assert table_cell_blocks
    assert table_hover is not None
    assert decision_header is not None
    assert "background: var(--surface-muted);" in table_header.group("css")
    assert "color: var(--ink);" in table_header.group("css")
    assert any("background: var(--surface);" in block for block in table_cell_blocks)
    assert "background: var(--surface-subtle);" in table_hover.group("css")
    assert "background: var(--surface-muted);" in decision_header.group("css")
    assert "color: var(--ink);" in decision_header.group("css")
    for legacy_color in ("#f4f7f3", "#334039", "#fbfdf9", "#fffefa"):
        assert legacy_color not in html


def test_candidate_brand_mark_uses_soft_orange_tile() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    brand_mark = re.search(
        r"\.candidate-brand-mark \{(?P<css>.*?)\n\s*\}", html, re.DOTALL
    )
    assert brand_mark is not None
    assert "width: 56px;" in brand_mark.group("css")
    assert "height: 56px;" in brand_mark.group("css")
    assert "background: var(--brand-soft);" in brand_mark.group("css")
    assert "border-radius: var(--radius-xl);" in brand_mark.group("css")


def test_candidate_visual_samples_follow_the_registered_solar_icon_contract() -> None:
    html = read_text(CANDIDATE_HTML_PATH)
    solar_icon_source = read_text(SOLAR_ICON_PATH)
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))

    registry = re.search(
        r"const solarIcons = \{(?P<body>.*?)\n\}", solar_icon_source, re.DOTALL
    )
    assert registry is not None
    registered_names = set(
        re.findall(r"^\s{2}(\w+):", registry.group("body"), re.MULTILINE)
    )

    svg_blocks = re.findall(
        r"<svg\b(?P<attrs>[^>]*)>(?P<body>.*?)</svg>", html, re.DOTALL
    )
    visible_icons = [
        (attrs, body)
        for attrs, body in svg_blocks
        if "solar-icon-sprite" not in attrs
    ]
    assert visible_icons

    symbol_ids = set(re.findall(r'<symbol\s+id="([^"]+)"', html))
    used_names: set[str] = set()
    for attrs, body in visible_icons:
        assert "solar-icon-sample" in attrs
        assert 'aria-hidden="true"' in attrs

        name_match = re.search(r'data-solar-icon="([^"]+)"', attrs)
        variant_match = re.search(r'data-icon-variant="([^"]+)"', attrs)
        use_match = re.fullmatch(
            r'\s*<use\s+href="#([^"]+)"\s*></use>\s*', body, re.DOTALL
        )
        assert name_match is not None
        assert variant_match is not None
        assert use_match is not None

        name = name_match.group(1)
        variant = variant_match.group(1)
        target = use_match.group(1)
        used_names.add(name)
        assert name in registered_names
        assert target == f"solar-icon-{name}"
        assert target in symbol_ids
        assert variant in {"linear", "bold-duotone"}
        if variant == "bold-duotone":
            assert name in {"admin", "brand", "chart", "clues"}

    icon_tokens = candidate["tokens"]["icon"]
    assert icon_tokens["previewContract"] == {
        "source": "SolarIcon.tsx registered semantic names",
        "rendering": "One hidden SVG symbol per registered semantic icon; every visible sample references it with <use>.",
        "requiredAttributes": [
            "data-solar-icon",
            "data-icon-variant",
            "aria-hidden",
        ],
        "forbiddenFallbacks": [
            "ad hoc inline paths",
            "text glyph icons",
            "CSS-drawn chevrons",
        ],
    }
    assert {"brand", "close", "eye", "copy", "filter", "chevronDown"} <= used_names
    assert '>×</button>' not in html
    assert 'content: "×";' not in html
    assert '<span class="select-indicator"' not in html

    icon_buttons = re.findall(
        r'<button\b(?P<attrs>[^>]*class="[^"]*icon-button-demo[^"]*"[^>]*)>'
        r"(?P<body>.*?)</button>",
        html,
        re.DOTALL,
    )
    assert icon_buttons
    for attrs, body in icon_buttons:
        assert 'aria-label="' in attrs
        assert "solar-icon-sample" in body


def test_active_visual_samples_do_not_bypass_the_solar_icon_contract() -> None:
    html = read_text(HTML_PATH)
    tokens = load_tokens()
    solar_icon_source = read_text(SOLAR_ICON_PATH)

    registry = re.search(
        r"const solarIcons = \{(?P<body>.*?)\n\}", solar_icon_source, re.DOTALL
    )
    assert registry is not None
    registered_names = set(
        re.findall(r"^\s{2}(\w+):", registry.group("body"), re.MULTILINE)
    )

    assert 'class="solar-icon-sprite"' in html
    assert '>×</button>' not in html
    assert 'content: "×";' not in html
    assert '<span class="select-indicator"' not in html
    assert tokens["tokens"]["icon"]["previewContract"]["source"] == (
        "SolarIcon.tsx registered semantic names"
    )

    svg_blocks = re.findall(
        r"<svg\b(?P<attrs>[^>]*)>(?P<body>.*?)</svg>", html, re.DOTALL
    )
    visible_icons = [
        (attrs, body)
        for attrs, body in svg_blocks
        if "solar-icon-sprite" not in attrs
    ]
    assert visible_icons
    symbol_ids = set(re.findall(r'<symbol\s+id="([^"]+)"', html))
    for attrs, body in visible_icons:
        assert "solar-icon-sample" in attrs
        assert 'aria-hidden="true"' in attrs

        name_match = re.search(r'data-solar-icon="([^"]+)"', attrs)
        variant_match = re.search(r'data-icon-variant="([^"]+)"', attrs)
        use_match = re.fullmatch(
            r'\s*<use\s+href="#([^"]+)"\s*></use>\s*',
            body,
            re.DOTALL,
        )
        assert name_match is not None
        assert variant_match is not None
        assert use_match is not None

        name = name_match.group(1)
        variant = variant_match.group(1)
        target = use_match.group(1)
        assert name in registered_names
        assert target == f"solar-icon-{name}"
        assert target in symbol_ids
        assert variant in {"linear", "bold-duotone"}
        if variant == "bold-duotone":
            assert name in {"admin", "brand", "chart", "clues"}

    icon_buttons = re.findall(
        r'<button\b(?P<attrs>[^>]*class="[^"]*(?:icon-button-demo|mobile-clue-detail-demo__icon)[^"]*"[^>]*)>'
        r"(?P<body>.*?)</button>",
        html,
        re.DOTALL,
    )
    assert icon_buttons
    for attrs, body in icon_buttons:
        assert 'aria-label="' in attrs
        assert "solar-icon-sample" in body


def test_candidate_component_navigation_and_elevation_samples_follow_tokens() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    mobile_navigation = re.search(
        r"(?m)^\s*\.mobile-nav-demo \{(?P<css>.*?)\n\s*\}", html, re.DOTALL
    )
    assert mobile_navigation is not None
    assert "box-shadow: var(--shadow-navigation);" in mobile_navigation.group("css")
    assert "min-height: 56px;" in html
    assert "--shadow-card:" in html
    assert "--shadow-popover:" in html
    assert "--shadow-dialog:" in html
    assert "--shadow-workbench:" in html
    assert "MetricCard / 指标卡" in html
    for label in ("标准指标", "重点指标", "语义指标", "加载指标"):
        assert label in html
    for label in ("Level 0", "Level 1", "Level 2", "Level 3", "Level 4"):
        assert label in html
    assert "NavigationItem / 导航项" in html
    assert html.count("数据表现") >= 2
    assert "box-shadow: var(--shadow-popover);" in html
    assert "box-shadow: var(--shadow-dialog);" in html
    assert "box-shadow: var(--shadow-workbench);" in html
    assert "var(--shadow-soft)" not in html
    assert "var(--shadow)" not in html
    assert "rgb(31 43 36" not in html
    assert "rgb(21 34 29" not in html


def test_candidate_tertiary_navigation_contract_is_route_based_and_responsive() -> None:
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))

    tertiary = candidate["components"]["navigation"]["tertiary"]
    assert tertiary == {
        "semanticRole": "local page navigation",
        "structure": "nav > a",
        "landmarkLabel": "required nav aria-label",
        "currentState": "aria-current=page",
        "focusVisible": "global focus ring",
        "desktopItemHeight": "38px",
        "mobileMinTarget": "44px",
        "activeText": "#d63b00",
        "activeIndicator": "2px solid #fe5205",
        "hoverBackground": "#fff4ef",
        "itemRange": "2-5",
        "mobileOverflow": "horizontal scroll with current item visible",
        "sticky": "not independently sticky",
        "forbiddenUses": [
            "filters",
            "transient display modes",
            "tablist",
        ],
    }

    template = candidate["pageTemplates"]["tertiaryNavigation"]
    assert template["desktopPlacement"] == "after page heading and before filters or content"
    assert template["detailPlacement"] == "after entity heading and summary"
    assert template["mobilePlacement"] == "after page heading and before content"
    assert template["routingRule"] == "Every item has a stable URL and supports refresh, deep links, and browser history."
    assert template["stickyRule"] == "Do not add an independent sticky layer or change table sticky offsets."


def test_candidate_tertiary_navigation_gallery_uses_links_and_complete_states() -> None:
    html = read_text(CANDIDATE_HTML_PATH)
    plan = read_text(TERTIARY_PLAN_PATH)

    assert "TertiaryNav / 三级导航" in html
    assert 'class="tertiary-nav-showcase"' in html
    assert 'aria-label="结算数据子页面"' in html
    assert 'aria-label="账号详情子页面"' in html
    assert 'class="tertiary-nav tertiary-nav--mobile"' in html
    route_examples = (
        "/settlement/ranking",
        "/settlement/stores",
        "/settlement/orders",
        "/admin/accounts/123/profile",
        "/admin/accounts/123/permissions",
        "/admin/accounts/123/activity",
    )
    for route in route_examples:
        assert f'href="{route}"' in html
        assert f'href="{route}"' in plan

    tertiary_hrefs = re.findall(
        r'<a class="tertiary-nav__item[^"]*" href="([^"]+)"', html
    )
    assert tertiary_hrefs
    assert all(href.startswith("/") for href in tertiary_hrefs)
    assert 'class="tertiary-nav__item is-hover"' in html
    assert 'class="tertiary-nav__item is-focus"' in html
    assert 'class="tertiary-nav__item is-disabled" aria-disabled="true"' in html
    assert 'role="tablist"' not in html

    container = re.search(
        r"\.tertiary-nav \{(?P<css>.*?)\n\s*\}", html, re.DOTALL
    )
    base = re.search(
        r"\.tertiary-nav__item \{(?P<css>.*?)\n\s*\}", html, re.DOTALL
    )
    hover = re.search(
        r"\.tertiary-nav__item:hover,\s*\n\s*"
        r"\.tertiary-nav__item\.is-hover \{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    focus = re.search(
        r"\.tertiary-nav__item:focus-visible,\s*\n\s*"
        r"\.tertiary-nav__item\.is-focus \{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    current = re.search(
        r"\.tertiary-nav__item\[aria-current=\"page\"\] \{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    mobile = re.search(
        r"@media \(max-width: 920px\).*?\.tertiary-nav__item \{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    mobile_sample = re.search(
        r'<nav class="tertiary-nav tertiary-nav--mobile" '
        r'aria-label="移动端结算数据子页面">(?P<html>.*?)</nav>',
        html,
        re.DOTALL,
    )
    assert container is not None
    assert "min-width: 0;" in container.group("css")
    assert "overflow-x: auto;" in container.group("css")
    assert "padding-block: 3px;" in container.group("css")
    assert base is not None
    assert "min-height: 38px;" in base.group("css")
    assert "flex: 0 0 auto;" in base.group("css")
    assert "border-bottom: 2px solid transparent;" in base.group("css")
    assert "white-space: nowrap;" in base.group("css")
    assert hover is not None
    assert "background: var(--brand-soft);" in hover.group("css")
    assert focus is not None
    assert "box-shadow: var(--focus-ring);" in focus.group("css")
    assert current is not None
    assert "border-bottom-color: var(--brand-accent);" in current.group("css")
    assert "color: var(--brand-primary);" in current.group("css")
    assert mobile is not None
    assert "min-height: var(--touch-target);" in mobile.group("css")
    assert mobile_sample is not None
    mobile_links = mobile_sample.group("html")
    assert mobile_links.count('<a class="tertiary-nav__item"') == 5
    assert (
        'href="/preview/tertiary/mobile/product-settlement">商品结算汇总</a>'
        in mobile_links
    )
    assert (
        'href="/preview/tertiary/mobile/account-reconciliation" '
        'aria-current="page">账号结算对账</a>' in mobile_links
    )


def test_candidate_tertiary_navigation_reveals_the_current_item_horizontally() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    initializer = re.search(
        r"const revealCurrentTertiaryItem = \(nav\) => \{(?P<script>.*?)\n\s*\};",
        html,
        re.DOTALL,
    )
    assert initializer is not None
    script = initializer.group("script")
    assert 'nav.querySelector(\'[aria-current="page"]\')' in script
    assert script.count("getBoundingClientRect()") == 2
    assert "currentRect.left < navRect.left" in script
    assert "currentRect.right > navRect.right" in script
    assert "nav.scrollTo({" in script
    assert "window.scrollTo" not in script
    assert "scrollIntoView" not in script
    assert (
        'document.querySelectorAll(".tertiary-nav")'
        ".forEach(revealCurrentTertiaryItem);" in html
    )

    mobile_sample = re.search(
        r'<nav class="tertiary-nav tertiary-nav--mobile" '
        r'aria-label="移动端结算数据子页面">(?P<html>.*?)</nav>',
        html,
        re.DOTALL,
    )
    assert mobile_sample is not None
    mobile_items = re.findall(r"<a\b(?P<attrs>[^>]*)>", mobile_sample.group("html"))
    assert len(mobile_items) == 5
    current_index = next(
        index for index, attrs in enumerate(mobile_items) if 'aria-current="page"' in attrs
    )
    assert current_index >= 3


def test_candidate_tertiary_current_hover_keeps_white_surface_contrast() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    current_hover = re.search(
        r'\.tertiary-nav__item\[aria-current="page"\]:hover,\s*\n\s*'
        r'\.tertiary-nav__item\[aria-current="page"\]\.is-hover '
        r"\{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    assert current_hover is not None
    css = current_hover.group("css")
    assert "background: var(--surface);" in css
    assert "color: var(--brand-primary);" in css
    assert "var(--brand-soft)" not in css


def test_candidate_metadata_uses_final_review_date() -> None:
    html = read_text(CANDIDATE_HTML_PATH)
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))

    assert candidate["meta"]["lastUpdated"] == "2026-07-13"
    assert '<span class="pill">更新：2026-07-13</span>' in html


def test_tertiary_plan_verifies_the_merge_base_range_and_records_completion() -> None:
    plan = read_text(TERTIARY_PLAN_PATH)

    assert "$base = (git merge-base main HEAD).Trim()" in plan
    assert "git diff --check $base HEAD" in plan
    assert "git diff --name-only $base HEAD -- apps/web/src" in plan
    assert "git diff --name-only -- apps/web/src" not in plan
    assert "## Execution Status" in plan
    for task in ("Task 1", "Task 2", "Task 3"):
        assert f"- [x] {task}" in plan


def test_candidate_polish_uses_natural_gallery_typography_and_restraint() -> None:
    html = read_text(CANDIDATE_HTML_PATH)
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))

    typography = candidate["tokens"]["typography"]["scale"]
    assert typography["pageTitle"]["fontWeight"] == 800
    assert typography["sectionTitle"]["fontWeight"] == 700
    assert typography["body"] == {
        "fontSize": "14px",
        "lineHeight": "1.55",
        "fontWeight": 500,
        "usage": "Default UI copy",
    }
    assert typography["table"]["fontWeight"] == 500
    assert typography["caption"]["fontWeight"] == 600
    assert typography["metricValue"]["fontWeight"] == 800

    assert "--font-body: 14px;" in html
    assert "--font-note: 13px;" in html
    assert "--font-meta: 12px;" in html
    assert "font-weight: 850" not in html
    assert "font-weight: 750" not in html
    assert 'class="component-gallery"' in html
    assert 'class="component-card component-card--wide"' in html

    gallery = re.search(
        r"\.component-gallery \{(?P<css>.*?)\n\s*\}", html, re.DOTALL
    )
    flat_surfaces = re.search(
        r"\.panel,\s*\n\s*\.component-card,\s*\n\s*\.token-card \{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    component_notes = re.search(
        r"\.component-card > p \{(?P<css>.*?)\n\s*\}", html, re.DOTALL
    )
    field_grid = re.search(r"\.field-grid \{(?P<css>.*?)\n\s*\}", html, re.DOTALL)

    assert gallery is not None
    assert "align-items: start;" in gallery.group("css")
    assert flat_surfaces is not None
    assert "box-shadow: var(--shadow-none);" in flat_surfaces.group("css")
    assert component_notes is not None
    assert "font-size: var(--font-note);" in component_notes.group("css")
    assert field_grid is not None
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in field_grid.group("css")
    assert "grid-auto-flow: dense;" in field_grid.group("css")
    assert ".field-grid > .field-group:first-child" in html
    assert ".field-grid > .field-group:last-child" in html
    assert "@media (max-width: 920px)" in html
    assert "@media (max-width: 640px)" in html
    assert html.count("box-shadow: var(--shadow-card);") <= 6


def test_candidate_polish_has_responsive_long_document_navigation() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    assert '<div class="spec-toc-wrap">' in html
    assert '<nav class="spec-toc" aria-label="规范章节">' in html
    for section_id in (
        "workflow",
        "color",
        "typography",
        "spacing-radius",
        "components",
        "iconography",
        "table-sticky",
        "mobile-card",
        "clue-followup-workbench",
        "page-templates",
        "decisions",
        "enforcement",
    ):
        assert f'href="#{section_id}"' in html

    toc_wrap = re.search(r"\.spec-toc-wrap \{(?P<css>.*?)\n\s*\}", html, re.DOTALL)
    toc = re.search(r"\.spec-toc \{(?P<css>.*?)\n\s*\}", html, re.DOTALL)
    assert toc_wrap is not None
    assert toc is not None
    assert "position: sticky;" in toc_wrap.group("css")
    assert "overflow" not in toc_wrap.group("css")
    assert "overflow-x: auto;" in toc.group("css")
    assert html.count("overflow-x: clip;") >= 2
    assert "overflow-x: hidden;" not in html
    assert "scroll-margin-top:" in html
    assert "link.scrollIntoView" not in html
    assert "link.parentElement.scrollTo" in html


def test_candidate_mobile_page_templates_replace_desktop_workspaces_on_narrow_screens() -> None:
    html = read_text(CANDIDATE_HTML_PATH)
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))
    page_templates = html.split('id="page-templates"', 1)[1].split(
        'id="decisions"', 1
    )[0]

    assert 'class="desktop-template-stack"' in page_templates
    assert 'class="mobile-template-stack"' in page_templates
    assert 'class="mobile-data-page mobile-data-page--clues"' in page_templates
    assert 'class="mobile-data-page mobile-data-page--orders"' in page_templates
    assert 'class="mobile-filter-panel is-expanded"' in page_templates
    assert page_templates.count('class="mobile-record-card') >= 4
    assert page_templates.count('class="mobile-data-pager"') == 2
    assert html.count('class="mobile-navigation-item') >= 12
    assert "桌面模板仅在 921px 以上展示" in page_templates
    assert 'aria-label="线索明细页码"' in page_templates
    assert 'aria-label="订单明细页码"' in page_templates

    narrow_media = html.split("@media (max-width: 920px)", 1)[1]
    assert ".desktop-template-stack" in narrow_media
    assert "display: none;" in narrow_media
    assert ".mobile-template-stack" in narrow_media

    mobile_template = candidate["pageTemplates"]["mobileDetailWorkspace"]
    assert "DYDATA-5" in candidate["meta"]["relatedIssues"]
    assert mobile_template["desktopOnlyBreakpoint"] == "920px"
    assert mobile_template["recordPresentation"] == "record-cards"
    assert mobile_template["pagerControls"] == ["previous", "page-input", "next"]
    assert mobile_template["bottomNavigation"] == ["数据表现", "结算", "线索", "后台"]


def test_formal_v02_keeps_current_runtime_semantic_tokens_bound_to_css() -> None:
    formal_tokens = load_tokens()["tokens"]["color"]
    runtime_tokens = read_text(DESIGN_TOKENS_CSS_PATH)

    assert formal_tokens["green"]["value"] == "#0f5b4b"
    assert formal_tokens["greenSoft"]["value"] == "#e1efe9"
    assert css_variable_value(runtime_tokens, "--green") == "#0f5b4b"
    assert css_variable_value(runtime_tokens, "--green-soft") == "#e1efe9"
    assert css_variable_value(runtime_tokens, "--brand-orange") == formal_tokens["brandOrange"]["value"]


def test_formal_v02_records_candidate_artifacts_as_immutable_history() -> None:
    html = read_text(HTML_PATH)
    formal = load_tokens()
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))

    assert candidate["meta"]["version"] == "0.2.0-candidate"
    assert candidate["meta"]["status"] == "pending-human-approval"
    assert candidate["meta"]["runtimeApplied"] is False
    assert formal["promotionRecord"] == {
        "sourceArtifacts": [
            "docs/design-system/tokens.v0.2-candidate.json",
            "docs/design-system/candidate-v0.2.html",
        ],
        "sourceIssue": "DYDATA-3",
        "promotedByIssue": "DYDATA-4",
        "historicalReviewConfirmation": "确认进入阶段 2",
        "reviewRuntimeFilesExcluded": [
            "apps/web/src/design-tokens.css",
            "apps/web/src",
        ],
        "outcome": "Approved V0.2 values are now the formal runtime design-system contract.",
    }
    assert "候选工件保留为不可变历史评审记录" in html


def test_formal_v02_labels_mobile_candidate_content_as_future_dydata5() -> None:
    tokens = load_tokens()
    html = read_text(HTML_PATH)

    assert tokens["components"]["navigation"]["implementationStatus"] == (
        "future-DYDATA-5-not-runtime-active"
    )
    assert tokens["components"]["clueFollowUpMobileDetail"]["implementationStatus"] == (
        "future-DYDATA-5-not-runtime-active"
    )
    assert tokens["pageTemplates"]["mobileShell"]["implementationStatus"] == (
        "future-DYDATA-5-not-runtime-active"
    )
    assert tokens["pageTemplates"]["mobileDetailWorkspace"]["implementationStatus"] == (
        "future-DYDATA-5-not-runtime-active"
    )
    assert tokens["pageTemplates"]["clueFollowUpMobileDetail"]["implementationStatus"] == (
        "future-DYDATA-5-not-runtime-active"
    )
    assert "DYDATA-5 未来范围" in html
    assert "不代表现有运行时行为" in html
