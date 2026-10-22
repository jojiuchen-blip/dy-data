"""Real API regressions for bounded export metadata and complete SAP exports."""

import csv
from io import StringIO
import json

import pytest

from test_api_finance_contract_g5 import client, _login, _seed_store_and_statement
from dy_api.auth import AuthContext
from dy_api.routes import dashboard
from apps.api.dy_api.models import DimStore


def test_finance_order_export_accepts_chinese_filter_in_headers(client, db_session) -> None:
    _seed_store_and_statement(db_session)
    _login(client)
    response = client.get(
        "/api/v1/admin/finance/order-details/export",
        params={"month": "2026-08", "feeDirection": "PROMOTION", "q": "中文门店"},
    )
    assert response.status_code == 200, response.text
    assert json.loads(response.headers["x-export-filters"])["q"] == "中文门店"
    assert len(response.headers["x-export-filters"].encode("ascii")) <= 1024
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert list(csv.DictReader(StringIO(response.content.decode("utf-8-sig")))) == []


def test_sap_export_rejects_over_limit_candidates_before_filtering_differences(
    client, db_session, monkeypatch
) -> None:
    db_session.add_all([
        DimStore(store_id="limit-store-1", store_name="one", is_active=True),
        DimStore(store_id="limit-store-2", store_name="two", is_active=True),
    ])
    db_session.commit()
    _login(client)
    monkeypatch.setattr(dashboard, "MAX_FINANCE_ORDER_EXPORT_ROWS", 1)
    filters = {"month": "2026-08", "feeDirection": "PROMOTION", "metricScope": "MONTH"}
    response = client.get("/api/v1/admin/finance/stores/sap-discrepancies/export", params=filters)
    assert response.status_code == 413, response.text
    assert "EXPORT_LIMIT_EXCEEDED" in response.text
    narrowed = client.get(
        "/api/v1/admin/finance/stores/sap-discrepancies/export",
        params={**filters, "q": "limit-store-1"},
    )
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.content.startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("role,scope,expected", [
    ("admin", "all", 3),
    ("admin", "specified", 2),
    ("highest_admin", "specified", 2),
    ("store", "specified", 1),
])
def test_finance_operator_level_tracks_effective_admin_scope(role, scope, expected) -> None:
    actor = AuthContext(
        user_id="synthetic-user", username="synthetic", display_name="Synthetic",
        role=role, store_ids=("store-1",), auth_type="user", store_scope_mode=scope,
    )
    assert dashboard._finance_operator_role(actor) == expected
