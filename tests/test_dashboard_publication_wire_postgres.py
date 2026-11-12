"""Real PostgreSQL -> FastAPI JSON -> existing frontend formatter contracts."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from test_dashboard_publication_sales_postgres import publication_postgres_session
from test_dashboard_publication_ranking_postgres import seed_frozen
from test_dashboard_publication_sales import prepare_sales
from test_dashboard_publication_clues import prepare_clues
from test_dashboard_publication_finance import _seed_finance, _seed_settlement, _run, NOW
from publication_fixture_helpers import ready_periods_fixture
from apps.api.dy_api.dashboard_publications import finance
from apps.api.dy_api.dashboard_publications.lifecycle import pin_publication
from apps.api.dy_api.dashboard_publications.schema import metadata, runs, heads
from apps.api.dy_api.dashboard_publications.sources import MODULE_CONTRACT_VERSIONS
from apps.api.dy_api.access_control import ALL_PAGE_KEYS
from apps.worker.dashboard_publications import check_ready
from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency


def _publish(session, publication_id, module):
    stats = dict(session.scalar(select(runs.c.stats_json).where(runs.c.id == publication_id)) or {})
    if module in MODULE_CONTRACT_VERSIONS:
        stats["contract_version"] = MODULE_CONTRACT_VERSIONS[module]
    session.execute(runs.update().where(runs.c.id == publication_id).values(
        module=module, status="success", published_at=NOW, stats_json=stats))
    session.execute(heads.insert().values(module=module, publication_id=publication_id))
    session.commit()


@pytest.fixture
def http_client(publication_postgres_session, monkeypatch):
    monkeypatch.setenv("DY_AGENT_ENVIRONMENT", "production")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=None, username="wire-test", display_name="wire-test", role="highest_admin",
        store_ids=(), auth_type="env_admin", page_keys=ALL_PAGE_KEYS)
    app.dependency_overrides[get_session_dependency] = lambda: publication_postgres_session
    with TestClient(app) as client:
        yield client


@pytest.fixture
def ranking_http(publication_postgres_session, http_client):
    metadata.create_all(publication_postgres_session.get_bind())
    seed_frozen(publication_postgres_session, 3)
    _publish(publication_postgres_session, "pub", "douyin-ranking")
    response = http_client.get("/api/v1/dashboard/douyin-ranking", params={
        "periodStart": "2026-09-01", "periodEnd": "2026-09-30", "level": "group"})
    assert response.status_code == 200, response.text
    return response


def test_postgres_ranking_http_counts_and_ratios_are_json_numbers(ranking_http, http_client):
    data = ranking_http.json()["data"]
    counts = ("storeCount", "orderCount", "followNumerator", "followDenominator",
        "followAnyNumerator", "followAnyDenominator", "followActionNumerator",
        "followActionDenominator", "verificationNumerator", "verificationDenominator")
    ratios = ("orderAverage", "followRate", "followActionRate", "follow24hRate", "verificationRate")
    for row in [*data["rows"], data["totals"]]:
        for key in counts:
            assert type(row[key]) is int, (key, row[key], type(row[key]).__name__)
        for key in ratios:
            assert type(row[key]) in (int, float), (key, row[key], type(row[key]).__name__)
        assert row["orderAverage"] == 1.5
        assert row["follow24hRate"] == .333333
    empty = http_client.get("/api/v1/dashboard/douyin-ranking", params={
        "periodStart": "2026-09-01", "periodEnd": "2026-09-30", "groupName": "absent"})
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"]["totals"]["follow24hRate"] is None


def test_postgres_ranking_http_payload_runs_actual_frontend_average_formatter(ranking_http):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute the frontend formatter")
    page = Path(__file__).resolve().parents[1] / "apps/web/src/pages/DouyinRankingPage.tsx"
    source = page.read_text(encoding="utf-8")
    formatter = re.search(r"function displayAverage\([^)]*\) \{.*?\n\}", source, re.S).group()
    # Erase only the TS parameter annotation; execute the shipped function body.
    formatter = re.sub(r"\(value: [^)]*\)", "(value)", formatter, count=1)
    script = formatter + """
const payload = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const rows = [...payload.data.rows, payload.data.totals];
process.stdout.write(JSON.stringify(rows.map(row => displayAverage(row.orderAverage))));
"""
    result = subprocess.run([node, "-e", script], input=ranking_http.text,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["1.50", "1.50"]


def test_postgres_sales_http_cycle_statistics_are_json_numbers(publication_postgres_session, http_client):
    prepare_sales(publication_postgres_session)
    _publish(publication_postgres_session, "s1", "sales")
    response = http_client.get("/api/v1/dashboard/sales", params={"month": "2026-02"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    for key, value in data["metrics"].items():
        assert value is None or type(value) in (int, float), (key, value)
    assert data["cycle_rows"]
    for row in data["cycle_rows"]:
        for key in ("count", "min_days", "max_days", "avg_days", "q1_days", "median_days", "q3_days"):
            assert type(row[key]) in (int, float), (key, row[key])


def test_postgres_clue_http_metrics_are_json_numbers(publication_postgres_session, http_client):
    prepare_clues(publication_postgres_session)
    _publish(publication_postgres_session, "c1", "clue-overview")
    response = http_client.get("/api/v1/clues/overview")
    assert response.status_code == 200, response.text
    for key, value in response.json()["data"].items():
        assert type(value) in (int, float), (key, value)


@pytest.mark.parametrize("module", ["settlement", "finance"])
def test_postgres_financial_http_preserves_integer_cents(publication_postgres_session, http_client, monkeypatch, module):
    session = publication_postgres_session
    monkeypatch.setattr(finance.period_readiness, "capture", ready_periods_fixture)
    if module == "settlement":
        _seed_settlement(session)
        _run(session, "wire", module)
        finance.build_settlement(session, "wire", NOW)
        path, params = "/api/v1/dashboard/store-ranking", {"periodKey": "2026-08"}
    else:
        _seed_finance(session)
        _run(session, "wire", module)
        finance.build_finance(session, "wire", NOW)
        path, params = "/api/v1/admin/finance/summary", {
            "month": "2026-09", "feeDirection": "PROMOTION", "metricScope": "MONTH"}
    _publish(session, "wire", module)
    response = http_client.get(path, params=params)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    metrics = data["totals"] if module == "settlement" else data["metrics"]
    for key, value in metrics.items():
        assert type(value) is int, (key, value)
    if module == "settlement":
        assert metrics["salesAmountCent"] == 9007199254740993 * 4
    assert session.scalar(select(runs.c.status).where(runs.c.id == "wire")) == "success"


def test_postgres_settlement_http_keeps_compatible_pinned_snapshot_during_cutover(
    publication_postgres_session, http_client, monkeypatch, caplog,
):
    session = publication_postgres_session
    monkeypatch.setattr(finance.period_readiness, "capture", ready_periods_fixture)
    _seed_settlement(session)
    module = "settlement"
    old_contract = "product-type-v2"
    new_contract = "commission-product-type-v3"
    cutover_pin = "deployment-previous-contract:commission-product-type-v3"
    monkeypatch.setitem(MODULE_CONTRACT_VERSIONS, module, old_contract)
    path, params = "/api/v1/dashboard/store-ranking", {"periodKey": "2026-08"}
    factory = sessionmaker(bind=session.get_bind())
    http_client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="bridge-test", username="bridge-test", display_name="bridge-test", role="store",
        store_ids=("allowed",), store_scope_mode="specified", auth_type="test", page_keys=ALL_PAGE_KEYS)

    def publish(identifier, contract):
        with monkeypatch.context() as patch:
            patch.setitem(MODULE_CONTRACT_VERSIONS, module, contract)
            _run(session, identifier, module)
            finance.build_settlement(session, identifier, NOW)
            session.execute(heads.delete().where(heads.c.module == module))
            _publish(session, identifier, module)

    publish("previous-complete", old_contract)
    active = http_client.get(path, params=params)
    assert active.status_code == 200, active.text
    baseline = active.json()
    assert baseline["meta"]["publication"]["id"] == "previous-complete"
    assert [row["storeId"] for row in baseline["data"]["list"]] == ["allowed"]
    session.rollback()

    publish("unrelated-pin", old_contract)
    publish("wrong-contract", "product-type-v1")
    pin_publication(session, "unrelated-pin", reason="monthly-report-archive", actor="bridge-test")
    pin_publication(session, "wrong-contract", reason=cutover_pin, actor="bridge-test")
    session.commit()
    publish("incoming-complete", new_contract)
    # HTTP and domain imports can register more sidecar tables than the
    # settlement fixture alone. Exercise the real readiness gate's schema check.
    metadata.create_all(session.get_bind())
    with monkeypatch.context() as patch:
        patch.setitem(MODULE_CONTRACT_VERSIONS, module, old_contract)
        unavailable = http_client.get(path, params=params)
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "PUBLICATION_NOT_READY"
        session.rollback()

        pin_publication(session, "previous-complete", reason=cutover_pin, actor="bridge-test")
        session.commit()
        rows = session.execute(select(runs).order_by(runs.c.id)).all()
        assert not check_ready(factory, (module,))
        assert "publication_ready code=PUBLICATION_NOT_READY" in caplog.text
        fallback = http_client.get(path, params=params)
        assert fallback.status_code == 200, fallback.text
        assert fallback.json()["meta"]["publication"] == {
            **baseline["meta"]["publication"], "status": "stale",
        }
        assert fallback.json()["data"] == baseline["data"]
        expired = http_client.get(path, params={**params, "publication_id": "incoming-complete"})
        assert expired.status_code == 410
        assert expired.json()["detail"]["code"] == "PUBLICATION_EXPIRED"
        assert session.scalar(select(heads.c.publication_id).where(heads.c.module == module)) == "incoming-complete"
        assert session.execute(select(runs).order_by(runs.c.id)).all() == rows
        with factory() as other, pytest.raises(DBAPIError) as locked:
            other.scalar(select(runs.c.id).where(runs.c.id == "previous-complete").with_for_update(nowait=True))
        assert locked.value.orig.sqlstate == "55P03"
        session.rollback()

    with monkeypatch.context() as patch:
        patch.setitem(MODULE_CONTRACT_VERSIONS, module, new_contract)
        assert check_ready(factory, (module,))
        new = http_client.get(path, params=params)
        assert new.status_code == 200, new.text
        assert new.json()["meta"]["publication"]["id"] == "incoming-complete"
