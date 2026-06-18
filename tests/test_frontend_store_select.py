from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_store_select_does_not_cap_available_store_options() -> None:
    source = read_source("components/SearchableStoreSelect.tsx")

    assert ".slice(0, 80)" not in source
