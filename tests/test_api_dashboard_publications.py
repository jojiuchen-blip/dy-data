"""Actual HTTP contracts for immutable analytical reads and live authorization."""
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import sys
import re

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import event, func, select, update
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.dashboard_publications import clues, finance, ranking, sales
from apps.api.dy_api.dashboard_publications.lifecycle import publish_module
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.api.dy_api.models import ClueCenterOrder, ClueMasterLead, SettlementOrderDetail, SettlementStatement
from apps.api.dy_api.ranking_schema_v1 import metadata as ranking_metadata
from apps.worker.ranking_preview_fixture import AT, CUTOFF, seed_preview


BUILDERS = {"sales": sales.build, "clue-overview": clues.build,
    "douyin-ranking": ranking.build, "settlement": finance.build_settlement,
    "finance": finance.build_finance}
RANK_PARAMS = {"periodStart": "2026-09-01", "periodEnd": "2026-09-30", "level": "store"}
FINANCE_PARAMS = {"month": "2026-09", "feeDirection": "PROMOTION", "metricScope": "MONTH"}
READS = [
    ("sales", "/dashboard/sales", {"year": 2026}),
    ("clue-overview", "/clues/overview", {}),
    ("douyin-ranking", "/dashboard/douyin-ranking", RANK_PARAMS),
    ("settlement", "/dashboard/store-ranking", {"periodType": "MONTHLY", "periodKey": "2026-09"}),
    ("settlement", "/stores/A/monthly-settlement", {"month": "2026-09"}),
    ("finance", "/admin/finance/summary", FINANCE_PARAMS),
    ("finance", "/admin/finance/invoices", FINANCE_PARAMS),
]


@pytest.fixture
def analytical_client(db_session, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    ranking_metadata.create_all(db_session.bind)
    metadata.create_all(db_session.bind)
    seed_preview(db_session)
    for index, store_id in enumerate(("A", "B"), 1):
        db_session.add(SettlementOrderDetail(coupon_id=f"sale-{store_id}", order_id=f"sale-{store_id}",
            product_type="P", sale_store_id=store_id, sale_time=AT, verify_store_id=store_id,
            verify_time=AT + timedelta(days=1), is_verified=True, is_refund_excluded=False,
            paid_amount_cent=index * 100))
    for order_id, round_id in (("O1", "RA1"), ("O2", "RB1"), ("O3", "RB8")):
        db_session.add(ClueCenterOrder(order_id=order_id, lead_status="active",
            current_assignment_round_id=round_id, current_round_status="active_unfollowed",
            product_type="P", product_id="TEST-JC"))
    db_session.add(SettlementStatement(statement_id="statement-A", store_id="A",
        statement_month="2026-09", version_no=1, is_current=True, statement_status=2,
        promotion_original_fee_cent=200, promotion_net_fee_cent=200, store_name_snapshot="Frozen store A"))
    db_session.commit()
    identity = [AuthContext(user_id="reader", username="reader", display_name="Reader",
        role="highest_admin", store_ids=(), auth_type="test", page_keys=("FIN01", "FIN02"))]
    app = create_app()
    app.dependency_overrides[get_session_dependency] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: identity[0]
    factory = sessionmaker(db_session.get_bind(), expire_on_commit=False)
    with TestClient(app) as client:
        yield client, identity, factory


def freeze(factory, module):
    return publish_module(factory, module, BUILDERS[module], now=CUTOFF)


@pytest.mark.parametrize("module,path,params", READS)
def test_missing_and_expired_versions_never_build(analytical_client, db_session, module, path, params):
    client, _, _ = analytical_client
    before = db_session.scalar(select(func.count()).select_from(runs))
    missing = client.get("/api/v1" + path, params=params)
    assert missing.status_code == 503, missing.text
    assert missing.json()["detail"]["code"] == "PUBLICATION_NOT_READY"
    expired = client.get("/api/v1" + path, params={**params, "publication_id": "expired"})
    assert expired.status_code == 410, expired.text
    assert expired.json()["detail"]["code"] == "PUBLICATION_EXPIRED"
    assert db_session.scalar(select(func.count()).select_from(runs)) == before


def test_reads_filters_and_exports_pin_one_version_without_source_calculation(analytical_client, db_session, monkeypatch):
    client, _, factory = analytical_client
    publications = {module: freeze(factory, module) for module in BUILDERS}
    for implementation in (sales, clues, ranking):
        monkeypatch.setattr(implementation, "build", lambda *a, **kw: pytest.fail("GET invoked a builder"))
    for name in ("build_settlement", "build_finance"):
        monkeypatch.setattr(finance, name, lambda *a, **kw: pytest.fail("GET invoked a builder"))
    statements = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        for module, path, params in READS:
            response = client.get("/api/v1" + path,
                params={**params, "publication_id": publications[module].id})
            assert response.status_code == 200, (path, response.text)
            meta = response.json()["meta"]["publication"]
            assert meta["id"] == publications[module].id
            assert meta["module"] == module
            assert meta["dataAsOf"] is None
            assert meta["publishedAt"] == publications[module].published_at.isoformat()
        for module, publication in publications.items():
            response = client.get(f"/api/v1/dashboard/publications/{module}/filters",
                params={"publication_id": publication.id})
            assert response.status_code == 200, (module, response.text)
            assert response.json()["meta"]["publication"]["id"] == publication.id
        exported = client.get("/api/v1/dashboard/douyin-ranking/export",
            params={**RANK_PARAMS, "publication_id": publications["douyin-ranking"].id})
        assert exported.status_code == 200, exported.text[:200]
        assert exported.headers["X-Publication-ID"] == publications["douyin-ranking"].id
        book = load_workbook(BytesIO(exported.content))
        assert len(book.worksheets) == 3
        assert all(publications["douyin-ranking"].id in str(sheet["A3"].value) for sheet in book)
        assert all("版本发布时间" in sheet["A3"].value and "上游尚未提供完整截止时间" in sheet["A3"].value for sheet in book)
        exported = client.get("/api/v1/admin/finance/invoices/export",
            params={**FINANCE_PARAMS, "publication_id": publications["finance"].id})
        assert exported.status_code == 200, exported.text[:200]
        assert exported.headers["X-Publication-ID"] == publications["finance"].id
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
    assert statements
    assert all(sql.lstrip().upper().startswith(("SELECT", "WITH", "PRAGMA")) for sql in statements)
    assert not any(re.search(r"\b(INSERT INTO|UPDATE |DELETE FROM|CREATE TABLE|ALTER TABLE)\b", sql.upper()) for sql in statements)
    for table in ("raw_douyin_orders", "raw_douyin_verify_records", "settlement_order_details", "clue_assignment_rounds"):
        assert all(table not in sql for sql in statements), table


def test_sales_pin_survives_new_publication_and_access_changes(analytical_client, db_session):
    client, identity, factory = analytical_client
    first = freeze(factory, "sales")
    url = "/api/v1/dashboard/sales"
    params = {"year": 2026, "publication_id": first.id}
    original = client.get(url, params=params).json()["data"]
    db_session.execute(update(SettlementOrderDetail).values(paid_amount_cent=9999))
    db_session.commit()
    second = freeze(factory, "sales")
    assert second.id != first.id
    assert client.get(url, params=params).json()["data"] == original
    latest = client.get(url, params={"year": 2026}).json()
    assert latest["meta"]["publication"]["id"] == second.id
    assert latest["data"] != original
    identity[0] = replace(identity[0], role="store", store_scope_mode="specified", store_ids=("A",), page_keys=("C01",))
    scoped = client.get(url, params={**params, "store_id": "A"})
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["data"]["metrics"]["total_sales_order_count"] == 1
    assert client.get(url, params={**params, "store_id": "B"}).status_code == 403
    choices = client.get("/api/v1/dashboard/publications/sales/filters",
        params={"publication_id": first.id}).json()["data"]["stores"]
    assert [item["storeId"] for item in choices] == ["A"]


def test_clue_access_revoked_immediately_inside_existing_publication(analytical_client, db_session):
    client, identity, factory = analytical_client
    publication = freeze(factory, "clue-overview")
    identity[0] = replace(identity[0], role="store", store_scope_mode="specified", store_ids=("A",), page_keys=("A01",))
    params = {"publication_id": publication.id}
    before = client.get("/api/v1/clues/overview", params=params)
    assert before.status_code == 200, before.text
    db_session.execute(update(ClueMasterLead).where(ClueMasterLead.order_id == "O1").values(
        lifecycle_status="active", pool_location="headquarters_pool"))
    db_session.commit()
    after = client.get("/api/v1/clues/overview", params=params)
    assert after.status_code == 200, after.text
    assert after.json()["data"]["total_clues"] == before.json()["data"]["total_clues"] - 1
    assert after.json()["meta"]["publication"]["id"] == publication.id


def test_invalid_filter_is_422_and_failed_refresh_keeps_last_good_result(analytical_client, db_session):
    client, _, factory = analytical_client
    first = freeze(factory, "sales")
    assert client.get("/api/v1/dashboard/sales", params={"month": "all", "trend_months": "all"}).status_code == 422
    assert client.get("/api/v1/dashboard/douyin-ranking", params={"periodStart": "2026-09-30", "periodEnd": "2026-09-01"}).status_code == 422
    db_session.execute(runs.insert().values(id="failed", module="sales", status="failed",
        cutoff=CUTOFF + timedelta(seconds=1), created_at=CUTOFF + timedelta(seconds=1), stats_json={}))
    db_session.commit()
    response = client.get("/api/v1/dashboard/sales", params={"year": 2026})
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["publication"]["id"] == first.id
    assert response.json()["meta"]["publication"]["status"] == "failed"
