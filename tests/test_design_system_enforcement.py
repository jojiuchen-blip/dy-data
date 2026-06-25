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
DESIGN_TOKENS_CSS_PATH = WEB_SRC_DIR / "design-tokens.css"
LEGACY_UI_CLASS_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?:status-chip|feedback-status-chip|filter-chip|metric-card)"
    r"(?:--[A-Za-z0-9_-]+)?"
    r"(?![A-Za-z0-9_-])"
)
NON_INTERACTIVE_CLICK_PATTERN = re.compile(r"<(?:div|span)\b[^>]*\bonClick=", re.DOTALL)
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
        "V0.1 只承诺浅色模式",
        "先改 `tokens.json`",
        "同步更新 `index.html`",
        "同步更新 `apps/web/src/design-tokens.css`",
        "不在业务代码里直接导入 `@iconify/react`",
        "apps/web/src/components/SolarIcon.tsx",
        "不绕过 `apps/web/src/design-tokens.css`",
        "npm --prefix apps/web run build",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_tokens_declare_current_enforcement_scope() -> None:
    tokens = json.loads(read_text(TOKENS_PATH))
    current_rules = "\n".join(tokens["enforcement"]["current"])
    next_rules = "\n".join(tokens["enforcement"]["next"])

    assert tokens["meta"]["colorMode"] == "light-only"
    assert tokens["meta"]["darkModeStatus"] == "not-supported-in-v0.1"

    current_required = [
        "docs/design-system/README.md",
        "tests/test_design_system_docs.py",
        "tests/test_design_system_enforcement.py",
        "SolarIcon.tsx",
        "design-tokens.css",
        "unauthorized hex",
        "legacy status-chip",
        "div or span click handlers",
        "light-only",
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


def test_design_system_preview_is_light_only() -> None:
    html = read_text(HTML_PATH)

    assert "color-scheme: light;" in html
    assert "color-scheme: light dark" not in html
    assert "prefers-color-scheme" not in html
    assert "data-theme=\"dark\"" not in html


def test_iconify_imports_are_centralized_in_solar_icon_component() -> None:
    offenders: list[str] = []

    for path in iter_frontend_source_files():
        text = read_text(path)
        imports_iconify = "@iconify/react" in text or "@iconify-icons/solar" in text
        if imports_iconify and path.resolve() != SOLAR_ICON_PATH.resolve():
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


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
        'setAttribute("inert"',
        "returnTarget?.focus",
    ]:
        assert phrase in dialog
