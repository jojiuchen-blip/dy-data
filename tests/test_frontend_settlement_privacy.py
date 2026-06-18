from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_national_ranking_does_not_render_store_account_id() -> None:
    source = read_source("pages/StoreRankingPage.tsx")

    assert "<small>{row.store_id}</small>" not in source


def test_store_select_does_not_render_or_prompt_for_account_ids() -> None:
    source = read_source("components/SearchableStoreSelect.tsx")

    assert "<small>{option.value}</small>" not in source
    assert "${option.label} ${option.value}" not in source
    assert "?.label ?? value" not in source
    assert "ID" not in source


def test_settlement_pages_do_not_fallback_to_raw_store_or_account_ids() -> None:
    settlement_source = read_source("pages/StoreSettlementPage.tsx")
    details_source = read_source("pages/OrderDetailsPage.tsx")

    assert "store_name: activeStoreId" not in settlement_source
    assert "?.store_name ??\n    storeId" not in details_source
    assert "row.owner_account_name || row.owner_account_id" not in details_source
