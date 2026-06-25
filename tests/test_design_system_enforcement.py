from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_SYSTEM_DIR = REPO_ROOT / "docs" / "design-system"
README_PATH = DESIGN_SYSTEM_DIR / "README.md"
TOKENS_PATH = DESIGN_SYSTEM_DIR / "tokens.json"
HTML_PATH = DESIGN_SYSTEM_DIR / "index.html"
WEB_SRC_DIR = REPO_ROOT / "apps" / "web" / "src"
SOLAR_ICON_PATH = WEB_SRC_DIR / "components" / "SolarIcon.tsx"


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
        "tests/test_design_system_docs.py",
        "tests/test_design_system_enforcement.py",
        "V0.1 只承诺浅色模式",
        "先改 `tokens.json`",
        "同步更新 `index.html`",
        "不在业务代码里直接导入 `@iconify/react`",
        "apps/web/src/components/SolarIcon.tsx",
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
        "light-only",
    ]
    for phrase in current_required:
        assert phrase in current_rules

    next_required = [
        "generated or shared token file",
        "visual regression screenshots",
        "PR checklist",
        "unauthorized hex colors",
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
