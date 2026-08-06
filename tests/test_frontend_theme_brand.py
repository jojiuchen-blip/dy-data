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


def test_brand_attribution_uses_formal_assets_and_project_tokens() -> None:
    signature = read_text(WEB_SRC / "components" / "BrandAttribution.tsx")
    masks = read_text(WEB_SRC / "components" / "brand-attribution-masks.ts")
    tokens = read_text(WEB_SRC / "design-tokens.css")
    styles = read_text(WEB_SRC / "styles.css")

    assert not (WEB_SRC / "components" / "SpaceAiSignature.tsx").exists()
    assert 'export type BrandAttributionVariant = "standard-stacked" | "compact-horizontal"' in signature
    assert 'export type BrandAttributionPlacement =' in signature
    assert 'role="img"' in signature
    assert 'aria-label="Powered by SPACE AI Native"' in signature
    assert '"mark"' not in signature
    assert "SPACE_ORBIT_BACK_MASK" in signature
    assert "SPACE_WORDMARK_MASK" in signature
    assert "SPACE_FOCUS_MASK" in signature
    assert "SPACE_ORBIT_FRONT_MASK" in signature
    assert "ATTRIBUTION_STANDARD_POWERED_BY_MASK" in masks
    assert "ATTRIBUTION_COMPACT_NATIVE_MASK" in masks

    assert "--brand-attribution-accent: var(--brand-orange);" in tokens
    assert "--brand-attribution-ai: var(--brand-orange);" in tokens
    assert "--brand-attribution-neutral: var(--muted);" in tokens
    assert "@font-face" not in styles
    assert 'font-family: "Ethnocentric Regular"' not in styles
    assert ".dc-brand-attribution--standard-stacked" in styles
    assert ".dc-brand-attribution--compact-horizontal" in styles
    assert '.dc-brand-attribution[data-placement="rail-footer"]' in styles
    assert "--brand-attribution-mark-width: 70px;" in styles
    assert ".dc-brand-attribution--accent-orbit-only" in styles


def test_brand_attribution_covers_every_approved_surface() -> None:
    shell = read_text(WEB_SRC / "components" / "Shell.tsx")
    auth = read_text(WEB_SRC / "pages" / "AuthPage.tsx")
    home = read_text(WEB_SRC / "pages" / "HomePage.tsx")
    cli = read_text(WEB_SRC / "pages" / "CliAuthorizePage.tsx")
    mcp = read_text(WEB_SRC / "pages" / "McpAuthorizePage.tsx")

    assert shell.count("<BrandAttribution") >= 2
    assert 'placement="rail-footer"' in shell
    assert 'placement="account-surface-footer"' in shell
    assert '<BrandAttribution className="auth-brand-attribution" placement="auth-panel-footer" />' in auth
    assert '<BrandAttribution className="home-brand-attribution" placement="home-footer" />' in home
    assert 'placement="authorization-panel-footer"' in cli
    assert 'placement="authorization-panel-footer"' in mcp

    for source in [shell, auth, home, cli, mcp]:
        assert "SpaceAiSignature" not in source
        assert "variant=" not in "\n".join(
            line for line in source.splitlines() if "BrandAttribution" in line
        )
