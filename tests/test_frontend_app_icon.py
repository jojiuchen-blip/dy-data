from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "apps" / "web"


def read_web_file(relative_path: str) -> str:
    return (WEB_ROOT / relative_path).read_text(encoding="utf-8")


def test_app_uses_svg_favicon_icon() -> None:
    index_source = read_web_file("index.html")
    icon_source = read_web_file("public/business-engine-icon.svg")

    assert (
        '<link rel="icon" type="image/svg+xml" sizes="any" '
        'href="/business-engine-icon.svg" />'
    ) in index_source
    assert "business-loop-icon.svg" not in index_source
    assert "Douyin business data engine brand icon" in icon_source
    assert "Business loop operations hub icon" not in icon_source
    assert 'width="64"' in icon_source
    assert 'height="64"' in icon_source
    assert "<rect" not in icon_source
    assert 'fill="#E1EFE9"' not in icon_source
    assert 'fill="currentColor"' in icon_source
    assert "prefers-color-scheme: dark" in icon_source
    assert "color: #0F5B4B" in icon_source
    assert "color: #8AD8C6" in icon_source
    assert 'transform="translate(-1 -1) scale(2.75)"' in icon_source
    assert "M2 12c0-4.714" in icon_source
    assert "M22 5a3 3 0 1 1-6 0" in icon_source
