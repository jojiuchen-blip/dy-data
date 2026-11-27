from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_SYSTEM_DIR = REPO_ROOT / "docs" / "design-system"
README_PATH = DESIGN_SYSTEM_DIR / "README.md"
TOKENS_PATH = DESIGN_SYSTEM_DIR / "tokens.json"
HTML_PATH = DESIGN_SYSTEM_DIR / "index.html"
WEB_SRC_DIR = REPO_ROOT / "apps" / "web" / "src"
SOLAR_ICON_PATH = WEB_SRC_DIR / "components" / "SolarIcon.tsx"
DATA_TABLE_PATH = WEB_SRC_DIR / "components" / "DataTable.tsx"
SHELL_PATH = WEB_SRC_DIR / "components" / "Shell.tsx"
RESOURCE_STATE_PATH = WEB_SRC_DIR / "components" / "ResourceState.tsx"
DIALOG_PATH = WEB_SRC_DIR / "components" / "Dialog.tsx"
CHARTS_DIR = WEB_SRC_DIR / "components" / "charts"
DESIGN_TOKENS_CSS_PATH = WEB_SRC_DIR / "design-tokens.css"
APP_STYLES_PATH = WEB_SRC_DIR / "styles.css"
SEARCHABLE_SELECT_PATH = WEB_SRC_DIR / "components" / "SearchableStoreSelect.tsx"
SEARCHABLE_SELECT_CSS_PATH = WEB_SRC_DIR / "components" / "SearchableStoreSelect.css"
CANDIDATE_TOKEN_FILENAME = "tokens.v0.2-candidate.json"
CANDIDATE_PREVIEW_FILENAME = "candidate-v0.2.html"
LEGACY_UI_CLASS_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?:status-chip|feedback-status-chip|filter-chip|metric-card)"
    r"(?:--[A-Za-z0-9_-]+)?"
    r"(?![A-Za-z0-9_-])"
)
NON_INTERACTIVE_CLICK_PATTERN = re.compile(r"<(?:div|span)\b[^>]*\bonClick=", re.DOTALL)
LEGACY_BUTTON_CLASS_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?:primary-button|ghost-button|secondary-button|link-button|ui-icon-button)"
    r"(?![A-Za-z0-9_-])"
)
COLOR_LITERAL_PATTERN = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)|hsla?\([^)]+\)|oklch\([^)]+\)"
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def iter_frontend_source_files() -> list[Path]:
    source_files: list[Path] = []
    for pattern in ("*.ts", "*.tsx", "*.js", "*.jsx"):
        source_files.extend(WEB_SRC_DIR.rglob(pattern))
    return sorted(source_files)


def test_design_system_readme_declares_the_workflow_contract() -> None:
    text = read_text(README_PATH)

    required_phrases = [
        "tokens.json",
        "index.html",
        "apps/web/src/design-tokens.css",
        "tests/test_design_system_docs.py",
        "tests/test_design_system_enforcement.py",
        "V0.2.1 是 V0.2 系列当前正式生效的浅色与深色设计系统",
        "状态为 `active`",
        "支持 `system | light | dark`",
        "dydata.theme.preference",
        "Powered by SPACE AI Native",
        "BrandAttribution",
        "SVG 字形蒙版",
        "仅用于 dy-data",
        "先更新 `tokens.json`",
        "同步更新 `index.html`",
        "同步更新 `apps/web/src/design-tokens.css` 和业务 UI",
        "不在业务代码里直接导入 `@iconify/react`",
        "apps/web/src/components/SolarIcon.tsx",
        "不绕过 `apps/web/src/design-tokens.css`",
        "明细工作台模板",
        "外层视口固定",
        "结果表格内部滚动",
        "分页保持可见",
        "npm --prefix apps/web run build",
        "tokens.v0.2-candidate.json",
        "candidate-v0.2.html",
        "历史评审工件",
        "DYDATA-5",
        "不新增现有运行时路由",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_tokens_declare_current_enforcement_scope() -> None:
    tokens = json.loads(read_text(TOKENS_PATH))
    current_rules = "\n".join(tokens["enforcement"]["current"])
    next_rules = "\n".join(tokens["enforcement"]["next"])
    layout_tokens = tokens["tokens"]["layout"]
    data_table_tokens = tokens["components"]["dataTable"]
    follow_up_workbench = tokens["components"]["clueFollowUpWorkbench"]
    follow_up_mobile_detail = tokens["components"]["clueFollowUpMobileDetail"]
    detail_workspace = tokens["pageTemplates"]["detailDataWorkspace"]
    follow_up_modal = tokens["pageTemplates"]["clueFollowUpWorkbenchModal"]
    follow_up_mobile_template = tokens["pageTemplates"]["clueFollowUpMobileDetail"]

    assert tokens["meta"]["colorMode"] == "light-dark-system"
    assert tokens["meta"]["darkModeStatus"] == "runtime-active"
    assert layout_tokens["workspacePageWidth"]["value"] == "100%"
    assert "authenticated workspace pages fill" in layout_tokens["workspacePageWidth"]["usage"]
    assert layout_tokens["dataWorkspaceWidth"]["value"] == "100%"
    assert (
        layout_tokens["dataWorkspaceHeight"]["value"]
        == "calc(100vh - var(--workspace-topbar-height))"
    )
    assert "page frame does not scroll" in data_table_tokens["workspaceRule"]
    assert "editable page number with a jump action" in data_table_tokens["paginationRule"]
    assert "Mobile keeps previous, editable page number and next" in data_table_tokens["paginationRule"]
    assert "positive integers from 1 to totalPages" in data_table_tokens["paginationValidation"]
    assert detail_workspace["appliesTo"] == ["/clues/details", "/details"]
    assert "fixed viewport workspace" in detail_workspace["desktopRule"]
    assert "natural page scroll" in detail_workspace["mobileRule"]
    assert follow_up_workbench["desktopWidth"] == "min(1440px, calc(100vw - 48px))"
    assert follow_up_workbench["desktopHeight"] == "min(920px, calc(100dvh - 32px))"
    assert follow_up_workbench["desktopColumns"] == "minmax(0, 1fr) 380px"
    assert "grouped round history" in follow_up_workbench["contentRegions"][-1]
    assert "source badge" not in "\n".join(follow_up_workbench["contentRegions"])
    assert "order time" in "\n".join(follow_up_workbench["contentRegions"])
    assert "not the default Dialog size" in follow_up_workbench["rule"]
    assert follow_up_mobile_detail["width"] == "min(390px, 100%)"
    assert follow_up_mobile_detail["touchTarget"] == "44px minimum for reveal, copy and save controls"
    assert follow_up_mobile_detail["contentOrder"][0] == "phone and lead status"
    assert follow_up_mobile_detail["contentOrder"][-1] == "round history and nested follow-up records"
    assert "not a squeezed desktop modal" in follow_up_mobile_detail["rule"]
    assert "data-origin labels" in follow_up_mobile_detail["rule"]
    assert "source badge" not in follow_up_mobile_detail["rule"]
    assert follow_up_modal["appliesTo"] == ["ClueCenterPage follow-up detail modal"]
    assert "large centered modal overlay" in follow_up_modal["desktopStructure"]
    assert "source badge" not in "\n".join(follow_up_modal["desktopStructure"])
    assert "order-time" in "\n".join(follow_up_modal["desktopStructure"])
    assert "follow-up action form" in follow_up_modal["mobileStructure"]
    assert "not a small detail dialog" in follow_up_modal["desktopRule"]
    assert "current active round" in follow_up_modal["permissionRule"]
    assert follow_up_mobile_template["appliesTo"] == ["ClueCenterPage mobile follow-up detail view"]
    assert "phone, reveal/copy actions, lead status and current round" in follow_up_mobile_template["structure"]
    assert "full-width save action" in "\n".join(follow_up_mobile_template["structure"])
    assert "one-column task flow" in follow_up_mobile_template["rule"]
    assert "disable full phone reveal/copy" in follow_up_mobile_template["permissionRule"]

    current_required = [
        "docs/design-system/README.md",
        "tests/test_design_system_docs.py",
        "tests/test_design_system_enforcement.py",
        "SolarIcon.tsx",
        "design-tokens.css",
        "page-frame--data-workspace",
        "unauthorized hex",
        "legacy status-chip",
        "div or span click handlers",
        "system, light and dark",
        "390, 768 and 1440",
    ]
    for phrase in current_required:
        assert phrase in current_rules

    next_required = [
        "visual regression screenshots",
        "PR checklist",
        "Generate apps/web/src/design-tokens.css",
    ]
    for phrase in next_required:
        assert phrase in next_rules


def test_design_system_preview_supports_explicit_light_dark_and_system_modes() -> None:
    html = read_text(HTML_PATH)

    assert "color-scheme: light dark;" in html
    assert 'html[data-theme="dark"]' in html
    assert 'data-color-theme-button="system"' in html
    assert 'data-color-theme-button="light"' in html
    assert 'data-color-theme-button="dark"' in html
    assert "window.matchMedia" in html


def test_iconify_imports_are_centralized_in_solar_icon_component() -> None:
    offenders: list[str] = []

    for path in iter_frontend_source_files():
        text = read_text(path)
        imports_iconify = "@iconify/react" in text or "@iconify-icons/solar" in text
        if imports_iconify and path.resolve() != SOLAR_ICON_PATH.resolve():
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_business_chart_runtime_is_centralized_and_pages_do_not_draw_private_charts() -> None:
    echarts_offenders: list[str] = []
    private_chart_offenders: list[str] = []

    for path in iter_frontend_source_files():
        text = read_text(path)
        imports_echarts = 'from "echarts' in text or "from 'echarts" in text
        if imports_echarts and not path.is_relative_to(CHARTS_DIR):
            echarts_offenders.append(path.relative_to(REPO_ROOT).as_posix())

    for path in (WEB_SRC_DIR / "pages").rglob("*.tsx"):
        text = read_text(path)
        if re.search(r"<(?:svg|canvas)\b", text):
            private_chart_offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert echarts_offenders == []
    assert private_chart_offenders == []


def test_business_tsx_does_not_render_native_select_controls() -> None:
    offenders: list[str] = []

    for path in WEB_SRC_DIR.rglob("*.tsx"):
        text = read_text(path)
        if "<select" in text or "</select>" in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_business_tables_use_the_shared_data_table_component() -> None:
    offenders: list[str] = []

    for path in WEB_SRC_DIR.rglob("*.tsx"):
        text = read_text(path)
        contains_table_markup = "<table" in text or "</table>" in text
        if contains_table_markup and path.resolve() != DATA_TABLE_PATH.resolve():
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_business_pages_do_not_use_legacy_visual_class_entries() -> None:
    offenders: list[str] = []

    for path in (WEB_SRC_DIR / "pages").rglob("*.tsx"):
        text = read_text(path)
        if LEGACY_UI_CLASS_PATTERN.search(text):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_business_pages_use_shared_button_components() -> None:
    offenders: list[str] = []

    for path in (WEB_SRC_DIR / "pages").rglob("*.tsx"):
        if LEGACY_BUTTON_CLASS_PATTERN.search(read_text(path)):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_business_pages_do_not_render_native_form_or_button_controls() -> None:
    offenders: list[str] = []
    native_control_pattern = re.compile(r"<(?:input|textarea|button)\b")

    for path in (WEB_SRC_DIR / "pages").rglob("*.tsx"):
        if native_control_pattern.search(read_text(path)):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_business_errors_use_the_shared_user_facing_presenter() -> None:
    page_offenders: list[str] = []
    raw_error_pattern = re.compile(
        r"(?:error|err|exception)\s+instanceof\s+Error|"
        r"(?:error|err|exception)\.message\b",
        re.IGNORECASE,
    )

    for path in (WEB_SRC_DIR / "pages").rglob("*.tsx"):
        if raw_error_pattern.search(read_text(path)):
            page_offenders.append(path.relative_to(REPO_ROOT).as_posix())

    resource_state = read_text(RESOURCE_STATE_PATH)
    presenter = read_text(WEB_SRC_DIR / "utils" / "userFacingError.ts")

    assert page_offenders == []
    assert 'userFacingError(error, "数据加载失败，请稍后重试。")' in resource_state
    assert "STATUS_MESSAGES" in presenter
    assert "Hidden internal error" in presenter


def test_runtime_typography_and_radii_use_design_tokens() -> None:
    offenders: list[str] = []
    literal_pattern = re.compile(
        r"font-size:\s*\d+(?:\.\d+)?px|"
        r"border-radius:\s*(?!50%\b)\d+(?:\.\d+)?px"
    )
    style_paths = [
        APP_STYLES_PATH,
        SEARCHABLE_SELECT_CSS_PATH,
        WEB_SRC_DIR / "design-system" / "catalog.css",
    ]

    for path in style_paths:
        if literal_pattern.search(read_text(path)):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_runtime_core_size_variables_match_the_design_token_source() -> None:
    tokens = json.loads(read_text(TOKENS_PATH))["tokens"]
    runtime_css = read_text(DESIGN_TOKENS_CSS_PATH)
    expected_variables: dict[str, str] = {}

    for role in tokens["typography"]["scale"].values():
        expected_variables[role["cssVariable"]] = role["fontSize"]
    for key, value in tokens["space"].items():
        expected_variables[tokens["spaceCssVariables"][key]] = value
    for role in tokens["radius"].values():
        expected_variables[role["cssVariable"]] = role["value"]
    for role in tokens["control"].values():
        expected_variables[role["cssVariable"]] = role["value"]

    for variable, value in expected_variables.items():
        assert re.search(
            rf"{re.escape(variable)}:\s*{re.escape(value)};",
            runtime_css,
        ), f"{variable} must equal {value}"


def test_runtime_styles_use_v02_button_typography_and_elevation_entries() -> None:
    styles = read_text(APP_STYLES_PATH)
    searchable_select_styles = read_text(SEARCHABLE_SELECT_CSS_PATH)

    for legacy_selector in (
        "primary-button",
        "secondary-button",
        "ghost-button",
        "link-button",
    ):
        assert re.search(
            rf"(?<![A-Za-z0-9_-]){legacy_selector}(?![A-Za-z0-9_-])",
            styles,
        ) is None

    assert "var(--shadow-soft)" not in styles
    assert "var(--shadow)" not in styles
    assert "--shadow-soft:" not in read_text(DESIGN_TOKENS_CSS_PATH)
    assert "--shadow:" not in read_text(DESIGN_TOKENS_CSS_PATH)
    assert ".ui-select__menu" in styles
    assert "box-shadow: var(--shadow-popover);" in styles
    assert "box-shadow: var(--shadow-dialog);" in styles
    assert "box-shadow: var(--shadow-workbench);" in styles
    assert "box-shadow: var(--shadow-popover);" in searchable_select_styles

    weights = {
        int(value)
        for value in re.findall(
            r"font-weight:\s*(\d+)",
            styles + searchable_select_styles,
        )
    }
    assert weights <= {500, 600, 700, 800}


def test_finance_pages_only_reference_registered_design_tokens() -> None:
    styles = read_text(APP_STYLES_PATH)
    design_tokens = read_text(DESIGN_TOKENS_CSS_PATH)
    finance_styles = styles.split(
        "/* DYDATA-19 settlement and finance production pages */", 1
    )[1].split('.segmented-control[role="tablist"]', 1)[0]
    defined_tokens = set(
        re.findall(r"(--[A-Za-z0-9_-]+)\s*:", design_tokens + finance_styles)
    )
    referenced_tokens = set(re.findall(r"var\((--[A-Za-z0-9_-]+)", finance_styles))

    assert sorted(referenced_tokens - defined_tokens) == []


def test_legacy_green_is_reserved_for_semantic_success_styles() -> None:
    styles = read_text(APP_STYLES_PATH)
    allowed_selector_fragments = {
        ".clue-allocation-version-status.is-published",
        ".clue-followup-toast",
        ".feedback-form__message--success",
        ".ui-chip--success",
    }
    offenders: list[str] = []

    for block in styles.split("}"):
        if "var(--green" not in block or "{" not in block:
            continue
        selector = block.rsplit("{", 1)[0].strip()
        if not any(fragment in selector for fragment in allowed_selector_fragments):
            offenders.append(selector)

    assert offenders == []


def test_searchable_select_uses_registered_solar_icons() -> None:
    component = read_text(SEARCHABLE_SELECT_PATH)
    styles = read_text(SEARCHABLE_SELECT_CSS_PATH)

    assert '<SolarIcon' in component
    assert 'name="chevronDown"' in component
    assert 'name="check"' in component
    assert "aria-activedescendant" in component
    assert 'role="combobox"' in component
    assert 'role="listbox"' in component
    assert 'role="option"' in component
    assert "useState(-1)" in component
    assert "return Math.min(current + 1, filteredOptions.length - 1)" in component
    assert ".searchable-store-select::after" not in styles


def test_business_tsx_does_not_use_div_or_span_as_buttons() -> None:
    offenders: list[str] = []

    for path in WEB_SRC_DIR.rglob("*.tsx"):
        text = read_text(path)
        if NON_INTERACTIVE_CLICK_PATTERN.search(text):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_runtime_ui_colors_are_centralized_in_design_tokens_css() -> None:
    offenders: list[str] = []

    for path in WEB_SRC_DIR.rglob("*"):
        if not path.is_file() or path.suffix not in {".css", ".ts", ".tsx"}:
            continue
        if path.resolve() == DESIGN_TOKENS_CSS_PATH.resolve():
            continue
        text = read_text(path)
        if COLOR_LITERAL_PATTERN.search(text):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_candidate_design_system_is_not_imported_by_runtime_source() -> None:
    offenders: list[str] = []

    for path in WEB_SRC_DIR.rglob("*"):
        if not path.is_file() or path.suffix not in {".css", ".ts", ".tsx", ".js", ".jsx"}:
            continue
        text = read_text(path)
        if CANDIDATE_TOKEN_FILENAME in text or CANDIDATE_PREVIEW_FILENAME in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_modal_dialog_semantics_are_centralized_in_dialog_component() -> None:
    offenders: list[str] = []

    for path in WEB_SRC_DIR.rglob("*.tsx"):
        text = read_text(path)
        contains_modal_dialog = 'aria-modal="true"' in text or 'role="dialog"' in text
        if contains_modal_dialog and path.resolve() != DIALOG_PATH.resolve():
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_shell_visual_title_does_not_create_global_h1() -> None:
    shell = read_text(SHELL_PATH)

    assert "<h1" not in shell
    assert "</h1>" not in shell


def test_status_and_dialog_components_keep_accessibility_contracts() -> None:
    resource_state = read_text(RESOURCE_STATE_PATH)
    dialog = read_text(DIALOG_PATH)

    for phrase in [
        'role={error ? "alert" : "status"}',
        'aria-live={error ? "assertive" : "polite"}',
        "aria-atomic=\"true\"",
    ]:
        assert phrase in resource_state

    for phrase in [
        'role="dialog"',
        'aria-modal="true"',
        "focusableElements",
        '"Tab"',
        '"Escape"',
        "const onCloseRef = useRef(onClose);",
        "onCloseRef.current = onClose;",
        "if (!closeDisabled)",
        "onCloseRef.current()",
        "[closeDisabled, initialFocusRef, open, returnFocusRef]",
        'setAttribute("inert"',
        "returnTarget?.focus",
    ]:
        assert phrase in dialog

    assert "[closeDisabled, initialFocusRef, onClose, open, returnFocusRef]" not in dialog


FROZEN_RUNTIME_CSS_ALLOWLIST = {
    "apps/web/src/components/AccountScopePicker.css",
    "apps/web/src/components/ClueStoreFilter.css",
    "apps/web/src/components/GuidedTour.css",
    "apps/web/src/components/SearchableStoreSelect.css",
    "apps/web/src/components/layout/layout-primitives.css",
    "apps/web/src/design-system/catalog.css",
    "apps/web/src/design-tokens.css",
    "apps/web/src/pages/AdminClueRoutingProductsPage.css",
    "apps/web/src/pages/ClueFollowUp.css",
    "apps/web/src/pages/ClueOnboarding.css",
    "apps/web/src/settlement.css",
    "apps/web/src/styles.css",
    "apps/web/src/uat/uat-preview.css",
}


def test_no_new_private_css_files_outside_frozen_legacy_allowlist() -> None:
    current_css_files = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in WEB_SRC_DIR.rglob("*.css")
    }
    unauthorized = sorted(current_css_files - FROZEN_RUNTIME_CSS_ALLOWLIST)
    assert unauthorized == [], (
        "禁止新增页面或组件私有 CSS 文件；请使用 apps/web/src/components/layout 原语并遵循 "
        f"docs/design-system/AI-UI-PLAYBOOK.md。违规文件: {unauthorized}"
    )


def test_governed_layout_css_uses_only_design_tokens() -> None:
    layout_css_path = WEB_SRC_DIR / "components" / "layout" / "layout-primitives.css"
    raw_css = read_text(layout_css_path)
    css = re.sub(r"/\*.*?\*/", "", raw_css, flags=re.DOTALL)

    assert COLOR_LITERAL_PATTERN.search(css) is None
    assert "!important" not in css

    non_media_lines = [
        line for line in css.splitlines() if not line.strip().startswith("@media")
    ]
    non_media_css = "\n".join(non_media_lines)
    raw_px_property_pattern = re.compile(
        r"(?:font-size|border-radius|padding(?:-[a-z]+)?|margin(?:-[a-z]+)?|gap):\s*[^;\n]*\b\d+(?:\.\d+)?px\b"
    )
    assert raw_px_property_pattern.search(non_media_css) is None


def test_business_pages_do_not_nest_section_cards() -> None:
    offenders: list[str] = []
    tag_pattern = re.compile(r"<(/?)SectionCard\b([^>]*)>")

    for path in (WEB_SRC_DIR / "pages").rglob("*.tsx"):
        text = read_text(path)
        depth = 0
        for match in tag_pattern.finditer(text):
            closing, attrs = match.group(1), match.group(2)
            self_closing = attrs.rstrip().endswith("/")
            if closing:
                depth = max(0, depth - 1)
                continue
            if depth > 0 and 'tone="recessed"' not in attrs:
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
                break
            if not self_closing:
                depth += 1

    assert offenders == []


def test_data_table_preserves_sticky_header_and_semantic_column_contract() -> None:
    table_source = read_text(DATA_TABLE_PATH)
    styles = read_text(APP_STYLES_PATH)

    for phrase in (
        'stickyHeader?: "container"',
        "table-wrap--contained-sticky",
        "is-sticky-column",
        "is-numeric",
        "is-nowrap",
        "is-mono",
    ):
        assert phrase in table_source

    for phrase in (
        "position: sticky;",
        "z-index: var(--z-table-header);",
        "z-index: var(--z-table-header-corner);",
        ".table-wrap--contained-sticky",
        "font-variant-numeric: tabular-nums;",
    ):
        assert phrase in styles


def test_ai_ui_playbook_and_repo_skill_are_wired_into_governance() -> None:
    playbook_path = DESIGN_SYSTEM_DIR / "AI-UI-PLAYBOOK.md"
    skill_path = REPO_ROOT / ".agent" / "skills" / "dy-data-ui-governance" / "SKILL.md"
    agents = read_text(REPO_ROOT / "AGENTS.md")
    frontend_rules = read_text(REPO_ROOT / "docs" / "rules" / "frontend-tasks.md")
    readme = read_text(README_PATH)

    assert playbook_path.is_file()
    assert skill_path.is_file()

    playbook = read_text(playbook_path)
    skill = read_text(skill_path)

    assert len(playbook.splitlines()) <= 150
    for phrase in (
        "SolarIcon",
        "DataTable",
        "表头锁定",
        "BrandAttribution",
        "EChartsFigure",
        "PageHeader",
        "SectionCard",
        "MetricStrip",
        "CalloutBanner",
        "SplitWorkspace",
        "KeyValueGrid",
        "FileDropzone",
        "SwitchField",
        "配方 1",
        "配方 2",
        "配方 3",
        "配方 4",
    ):
        assert phrase in playbook

    assert "docs/design-system/AI-UI-PLAYBOOK.md" in skill
    assert "docs/design-system/AI-UI-PLAYBOOK.md" in agents
    assert ".agent/skills/dy-data-ui-governance/SKILL.md" in agents
    assert "docs/design-system/AI-UI-PLAYBOOK.md" in frontend_rules
    assert ".agent/skills/dy-data-ui-governance/SKILL.md" in frontend_rules
    assert "docs/design-system/AI-UI-PLAYBOOK.md" in readme
    assert ".agent/skills/dy-data-ui-governance/SKILL.md" in readme


def test_layout_primitives_are_exported_and_registered_in_component_manifest() -> None:
    barrel = read_text(WEB_SRC_DIR / "components" / "layout" / "index.ts")
    manifest = json.loads(read_text(DESIGN_SYSTEM_DIR / "components.json"))
    manifest_ids = {component["id"] for component in manifest["components"]}
    manifest_exports = {component["exportName"] for component in manifest["components"]}

    expected_primitives = {
        "page-header": "PageHeader",
        "section-card": "SectionCard",
        "metric-strip": "MetricStrip",
        "callout-banner": "CalloutBanner",
        "split-workspace": "SplitWorkspace",
        "key-value-grid": "KeyValueGrid",
        "file-dropzone": "FileDropzone",
        "switch-field": "SwitchField",
    }

    for component_id, export_name in expected_primitives.items():
        assert export_name in barrel
        assert component_id in manifest_ids
        assert export_name in manifest_exports
