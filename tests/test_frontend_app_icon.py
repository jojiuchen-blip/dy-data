from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "apps" / "web"


def read_web_file(relative_path: str) -> str:
    return (WEB_ROOT / relative_path).read_text(encoding="utf-8")


def test_app_uses_svg_favicon_icon() -> None:
    index_source = read_web_file("index.html")
    icon_source = read_web_file("public/business-engine-icon-v2.svg")

    assert (
        '<link rel="icon" type="image/svg+xml" sizes="any" '
        'href="/business-engine-icon-v2.svg" />'
    ) in index_source
    assert 'href="/business-engine-icon.svg"' not in index_source
    assert "business-loop-icon.svg" not in index_source
    assert "Douyin business data engine orange brand icon" in icon_source
    assert "Business loop operations hub icon" not in icon_source
    assert 'width="64"' in icon_source
    assert 'height="64"' in icon_source
    assert "<rect" not in icon_source
    assert 'fill="#E1EFE9"' not in icon_source
    assert 'fill="currentColor"' in icon_source
    assert "prefers-color-scheme: dark" in icon_source
    assert "color: #D63B00" in icon_source
    assert "color: #FE5205" in icon_source
    assert "#0F5B4B" not in icon_source
    assert "#8AD8C6" not in icon_source
    assert 'transform="translate(-14 5) scale(3.4)"' in icon_source
    assert "M2 12c0-4.714" not in icon_source
    assert "opacity=" not in icon_source
    assert icon_source.count("<path") == 1
    assert "M22 5a3 3 0 1 1-6 0" in icon_source
