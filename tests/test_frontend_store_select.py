from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_store_select_does_not_cap_available_store_options() -> None:
    source = read_source("components/SearchableStoreSelect.tsx")

    assert ".slice(0, 80)" not in source


def test_searchable_select_shows_empty_label_and_full_option_names() -> None:
    source = read_source("components/SearchableStoreSelect.tsx")
    css = read_source("components/SearchableStoreSelect.css")

    display_value = source[
        source.index("function displayValue") : source.index("export function")
    ]
    select_option = source[
        source.index("const selectOption") : source.index("return (")
    ]

    assert 'unique.set("", { value: "", label: emptyLabel });' in source
    assert 'emptyMessage = "未找到门店"' in source
    assert "{emptyMessage}" in source
    assert "if (!value)" not in display_value
    assert "option.value ? option.label : \"\"" not in select_option
    assert "setInputValue(option.label);" in select_option

    assert "width: max(100%, min(420px, calc(100vw - 48px)));" in css
    assert "overflow-wrap: anywhere;" in css
    assert "white-space: normal;" in css
    assert "text-overflow: ellipsis;" not in css
