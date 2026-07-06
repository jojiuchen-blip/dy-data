from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_sales_dashboard_uses_backend_aggregate_endpoint() -> None:
    client_source = read_source("api/client.ts")

    assert 'requestJson<SalesDashboardData>("/dashboard/sales"' in client_source
    assert "requestAllOrderDetails" not in client_source
    assert 'page_size: 500' not in client_source


def test_sales_dashboard_fallback_trend_uses_actual_verify_store() -> None:
    settlement_source = read_source("utils/settlement.ts")

    assert "row.is_verified && row.verify_store_id === storeId" in settlement_source
    assert "row.sale_store_id !== storeId ||" not in settlement_source
