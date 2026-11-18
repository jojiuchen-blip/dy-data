"""Real PostgreSQL -> FastAPI JSON -> existing frontend formatter contracts."""
from __future__ import annotations

import json
from datetime import timedelta
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
from test_dashboard_publication_ranking_postgres import AT, seed_frozen
from test_dashboard_publication_sales import prepare_sales
from test_dashboard_publication_clues import CUTOFF as CLUE_CUTOFF, prepare_clues
from test_dashboard_publication_finance import _seed_finance, _seed_settlement, _run, NOW
from publication_fixture_helpers import ready_periods_fixture
from apps.api.dy_api.dashboard_publications import clues, finance
from apps.api.dy_api.dashboard_publications import ranking_schema as frozen_ranking
from apps.api.dy_api.dashboard_publications.verifications import self_store_verifications
from apps.api.dy_api.dashboard_publications.lifecycle import pin_publication
from apps.api.dy_api.dashboard_publications.schema import metadata, runs, heads
from apps.api.dy_api.dashboard_publications.sources import MODULE_CONTRACT_VERSIONS, TASK_METRICS_CONTRACT_VERSIONS
from apps.api.dy_api.access_control import ALL_PAGE_KEYS
from apps.api.dy_api.models import ClueAssignmentRound, ClueFollowUpRecord
from apps.worker.dashboard_publications import check_ready
from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency


def _publish(session, publication_id, module, *, task_metrics=False):
    stats = dict(session.scalar(select(runs.c.stats_json).where(runs.c.id == publication_id)) or {})
    if module in MODULE_CONTRACT_VERSIONS:
        stats["contract_version"] = MODULE_CONTRACT_VERSIONS[module]
    if task_metrics:
        stats["task_metrics_contract"] = TASK_METRICS_CONTRACT_VERSIONS[module]
    else:
        stats.pop("task_metrics_contract", None)
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
    _prepare_ranking_wire(publication_postgres_session)
    return _ranking_response(http_client)


def _prepare_ranking_wire(session, *, task_metrics=True, zero=False):
    """Populate both physical contracts; the marker selects task interpretation."""
    metadata.create_all(session.get_bind())
    seed_frozen(session, 3)
    session.execute(frozen_ranking.rounds.update().where(
        frozen_ranking.rounds.c.publication_id == "pub",
    ).values(
        task_follow_24h_numerator=0 if zero else frozen_ranking.rounds.c.follow_24h,
        task_follow_any_numerator=0 if zero else frozen_ranking.rounds.c.follow_any,
        task_verification_numerator=0 if zero else frozen_ranking.rounds.c.self_verified,
        follow_denominator=1, verification_denominator=1,
    ))
    if not zero:
        session.execute(self_store_verifications.insert(), [dict(
            publication_id="pub", order_id=order_id, store_id="A", verify_id="wire-" + order_id,
            verified_at=AT, business_date=AT.date(), is_jingcheng=True,
        ) for order_id in ("0", "2")])
    _publish(session, "pub", "douyin-ranking", task_metrics=task_metrics)


def _ranking_response(http_client, **params):
    response = http_client.get("/api/v1/dashboard/douyin-ranking", params={
        "periodStart": "2026-09-01", "periodEnd": "2026-09-30", "level": "group", **params})
    assert response.status_code == 200, response.text
    return response


def test_postgres_ranking_http_counts_and_ratios_are_json_numbers(ranking_http, http_client):
    data = ranking_http.json()["data"]
    counts = ("storeCount", "orderCount", "followNumerator", "followDenominator",
        "followAnyNumerator", "followAnyDenominator", "followActionNumerator",
        "followActionDenominator", "verificationNumerator", "verificationDenominator", "selfStoreVerificationCount")
    ratios = ("orderAverage", "followRate", "followAnyRate", "followActionRate", "follow24hRate", "verificationRate")
    assert ranking_http.json()["meta"]["publication"]["taskMetricsContract"] == TASK_METRICS_CONTRACT_VERSIONS["douyin-ranking"]
    for row in [*data["rows"], data["totals"]]:
        for key in counts:
            assert type(row[key]) is int, (key, row[key], type(row[key]).__name__)
        for key in ratios:
            assert type(row[key]) in (int, float), (key, row[key], type(row[key]).__name__)
        assert row["orderAverage"] == 1.5
        assert row["follow24hRate"] == .333333
        assert row["followNumerator"] == 1 and row["followDenominator"] == 3
        assert row["followAnyNumerator"] == 3 and row["followAnyRate"] == 1
        assert row["verificationNumerator"] == row["verificationDenominator"] == 3
        assert row["selfStoreVerificationCount"] == 2
    empty = http_client.get("/api/v1/dashboard/douyin-ranking", params={
        "periodStart": "2026-09-01", "periodEnd": "2026-09-30", "groupName": "absent"})
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"]["totals"]["follow24hRate"] is None


def test_postgres_ranking_current_marker_preserves_legitimate_zero_metrics(publication_postgres_session, http_client):
    _prepare_ranking_wire(publication_postgres_session, zero=True)
    response = _ranking_response(http_client)
    for row in [*response.json()["data"]["rows"], response.json()["data"]["totals"]]:
        assert row["followDenominator"] == row["followAnyDenominator"] == row["verificationDenominator"] == 3
        for key in ("followNumerator", "followAnyNumerator", "verificationNumerator", "selfStoreVerificationCount"):
            assert type(row[key]) is int and row[key] == 0, (key, row[key])
        for key in ("follow24hRate", "followAnyRate", "verificationRate"):
            assert type(row[key]) in (int, float) and row[key] == 0, (key, row[key])


def test_postgres_ranking_prior_marker_keeps_new_task_fields_null(publication_postgres_session, http_client):
    _prepare_ranking_wire(publication_postgres_session, task_metrics=False, zero=True)
    response = _ranking_response(http_client)
    publication = response.json()["meta"]["publication"]
    assert publication["status"] == "refreshing" and publication["taskMetricsContract"] is None
    for row in [*response.json()["data"]["rows"], response.json()["data"]["totals"]]:
        # Old frozen cells still carry a 1/3 fast-follow sample and 3/3
        # cumulative follow, independently from the new zero-valued columns.
        assert row["storeCount"] == 2 and row["orderCount"] == 3 and row["orderAverage"] == 1.5
        assert row["followActionNumerator"] == row["followActionDenominator"] == 3
        assert row["followRate"] == row["followActionRate"] == 1
        for key in ("followNumerator", "followDenominator", "followAnyNumerator", "followAnyDenominator",
                    "verificationNumerator", "verificationDenominator", "follow24hRate", "followAnyRate",
                    "verificationRate", "selfStoreVerificationCount"):
            assert row[key] is None, (key, row[key])


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
    _prepare_clue_wire(publication_postgres_session)
    response = http_client.get("/api/v1/clues/overview")
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["publication"]["taskMetricsContract"] == TASK_METRICS_CONTRACT_VERSIONS["clue-overview"]
    for key, value in response.json()["data"].items():
        assert type(value) in (int, float), (key, value)
    data = response.json()["data"]
    assert data["total_clues"] == 3 and data["received_task_count"] == 4
    assert data["follow_denominator"] == data["verification_denominator"] == 4
    assert data["follow_24h_numerator"] == data["follow_any_numerator"] == 1
    assert data["follow_24h_rate"] == data["follow_any_rate"] == .25
    assert data["verification_numerator"] == data["self_store_verification_count"] == 0
    assert data["verification_rate"] == 0

    zero = http_client.get("/api/v1/clues/overview", params={"assigned_store_id": "B"})
    assert zero.status_code == 200, zero.text
    zero_data = zero.json()["data"]
    assert zero_data["received_task_count"] == zero_data["follow_denominator"] == 2
    for key in ("follow_24h_numerator", "follow_any_numerator", "verification_numerator", "self_store_verification_count"):
        assert type(zero_data[key]) is int and zero_data[key] == 0, (key, zero_data[key])
    for key in ("follow_24h_rate", "follow_any_rate", "verification_rate"):
        assert type(zero_data[key]) in (int, float) and zero_data[key] == 0, (key, zero_data[key])


def _prepare_clue_wire(session, *, task_metrics=True):
    """Use the real clue builder and a timed manual record for a 1/4 rate."""
    prepare_clues(session)
    assigned_at = session.scalar(select(ClueAssignmentRound.assigned_at).where(
        ClueAssignmentRound.assignment_round_id == "r1"))
    session.add(ClueFollowUpRecord(follow_up_record_id="wire-follow", order_id="o1", assignment_round_id="r1",
        assigned_store_id="A", round_no=1, follow_result="further_follow_up", created_at=assigned_at + timedelta(hours=1)))
    session.flush()
    clues.build(session, "c2", CLUE_CUTOFF)
    _publish(session, "c2", "clue-overview", task_metrics=task_metrics)


def test_postgres_clue_prior_marker_preserves_legacy_numbers_and_new_nulls(publication_postgres_session, http_client):
    _prepare_clue_wire(publication_postgres_session, task_metrics=False)
    response = http_client.get("/api/v1/clues/overview")
    assert response.status_code == 200, response.text
    publication = response.json()["meta"]["publication"]
    assert publication["status"] == "refreshing" and publication["taskMetricsContract"] is None
    data = response.json()["data"]
    for key in ("total_clues", "active_clues", "follow_rate", "follow_success_rate", "verified_count",
                "self_store_verify_rate", "pending_reassign_count"):
        assert type(data[key]) in (int, float), (key, data[key])
    assert data["total_clues"] == 3 and data["follow_rate"] == 1
    assert data["verified_count"] == 1 and data["self_store_verify_rate"] == .3333
    for key in (*clues.TASK_FIELDS, "received_task_count", "follow_24h_rate", "follow_any_rate",
                "verification_rate", "self_store_verification_count"):
        assert data[key] is None, (key, data[key])


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
