from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "apps" / "web"
WEB_SRC = WEB_ROOT / "src"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_theme_bootstrap_runs_before_react_entrypoint() -> None:
    html = read_text(WEB_ROOT / "index.html")

    assert 'name="theme-color"' in html
    assert "dydata.theme.preference" in html
    assert 'data-theme-preference' in html
    assert "window.matchMedia" in html
    assert 'document.documentElement.dataset.theme = resolved' in html
    assert html.index("dydata.theme.preference") < html.index('/src/main.tsx')


def test_theme_provider_owns_runtime_preference_and_resolution() -> None:
    theme = read_text(WEB_SRC / "theme" / "ThemeProvider.tsx")
    main = read_text(WEB_SRC / "main.tsx")

    for phrase in [
        'export type ThemePreference = "system" | "light" | "dark"',
        'const THEME_STORAGE_KEY = "dydata.theme.preference"',
        'window.matchMedia("(prefers-color-scheme: dark)")',
        "document.documentElement.dataset.theme = resolvedTheme",
        "document.documentElement.dataset.themePreference = preference",
        "window.localStorage.setItem(THEME_STORAGE_KEY, nextPreference)",
        "export function useTheme()",
    ]:
        assert phrase in theme

    assert "<ThemeProvider>" in main
    assert "</ThemeProvider>" in main


def test_theme_picker_uses_registered_solar_icons_and_accessible_state() -> None:
    picker = read_text(WEB_SRC / "components" / "ThemePicker.tsx")
    icons = read_text(WEB_SRC / "components" / "SolarIcon.tsx")

    assert 'aria-label="界面主题"' in picker
    assert 'aria-pressed={preference === option.value}' in picker
    assert '<SolarIcon name={option.icon}' in picker
    assert 'label: "跟随系统"' in picker
    assert 'label: "浅色"' in picker
    assert 'label: "深色"' in picker
    assert "monitor:" in icons
    assert "sun:" in icons
    assert "moon:" in icons


def test_runtime_tokens_define_one_global_dark_theme_contract() -> None:
    tokens = read_text(WEB_SRC / "design-tokens.css")
    styles = read_text(WEB_SRC / "styles.css")

    assert ':root[data-theme="dark"]' in tokens
    for phrase in [
        "--bg: #10110f",
        "--surface: #181a17",
        "--surface-muted: #22241f",
        "--ink: #f3f4ef",
        "--muted: #b7b9b1",
        "--brand-orange: #fe5205",
        "--green: #74cdb0",
        "--blue: #8fbae8",
        "--amber: #e9b66d",
        "--danger: #f49a91",
    ]:
        assert phrase in tokens

    assert "@media (prefers-color-scheme: dark)" not in styles
    assert ':root[data-theme="dark"] .auth-shell' in styles


def test_space_ai_signature_is_a_shared_dual_theme_component() -> None:
    signature = read_text(WEB_SRC / "components" / "SpaceAiSignature.tsx")
    styles = read_text(WEB_SRC / "styles.css")
    light_mark = WEB_SRC / "assets" / "brand" / "space-ai-native" / "space-mark-parametric-orbit-accent.svg"
    dark_mark = WEB_SRC / "assets" / "brand" / "space-ai-native" / "space-mark-parametric-orbit-accent-dark.svg"
    font = WEB_SRC / "assets" / "brand" / "space-ai-native" / "Ethnocentric-Regular.otf"

    assert light_mark.is_file()
    assert dark_mark.is_file()
    assert font.is_file()
    assert 'export type SpaceAiSignatureVariant = "horizontal" | "stacked" | "mark"' in signature
    assert 'aria-label="Powered by SPACE AI Native"' in signature
    assert '>\n          POWERED BY\n        </span>' in signature
    assert '>\n          AI NATIVE\n        </span>' in signature
    assert signature.count("space-ai-signature__mark-wrap") == 1
    assert "space-ai-signature__space" not in signature
    assert "space-ai-signature__mark--light" in signature
    assert "space-ai-signature__mark--dark" in signature
    assert '.space-ai-signature__copy,\n.space-ai-signature__native {' in styles
    assert 'font-family: "Ethnocentric Regular", sans-serif;' in styles
    assert ".space-ai-signature__mark {\n  display: block;\n  width: 84px;" in styles
    assert ".rail-space-signature .space-ai-signature__mark {\n  width: 70px;" in styles
    assert "color: var(--brand-orange);" not in styles[
        styles.index(".space-ai-signature__copy") : styles.index(".space-ai-signature--mark")
    ]
    assert ':root[data-theme="dark"] .space-ai-signature__mark--light' in styles


def test_space_ai_signature_covers_every_approved_surface() -> None:
    shell = read_text(WEB_SRC / "components" / "Shell.tsx")
    auth = read_text(WEB_SRC / "pages" / "AuthPage.tsx")
    home = read_text(WEB_SRC / "pages" / "HomePage.tsx")
    cli = read_text(WEB_SRC / "pages" / "CliAuthorizePage.tsx")
    mcp = read_text(WEB_SRC / "pages" / "McpAuthorizePage.tsx")

    assert shell.count("<SpaceAiSignature") >= 2
    assert 'variant="stacked"' in shell
    assert '<SpaceAiSignature className="auth-space-signature" />' in auth
    assert '<SpaceAiSignature className="home-space-signature" />' in home
    assert "<SpaceAiSignature" in cli
    assert "<SpaceAiSignature" in mcp
