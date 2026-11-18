"""Real publication/API/export parity for the DYDATA-115 task contract."""
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import sys
import importlib.util

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import event, select, update
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

from apps.api.dy_api.dashboard_publications import clues, ranking
from apps.api.dy_api.dashboard_publications.lifecycle import PublicationError, publish_module, resolve_publication
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.api.dy_api.models import (
    ClueAssignmentRound, ClueFollowUpRecord, DimStore, DimStorePoiMapping,
    RawDouyinOrder, RawDouyinVerifyRecord,
)
from apps.api.dy_api.ranking_schema_v1 import eligibility, metadata as ranking_metadata, org_history
from test_clue_task_metrics import AT, CUTOFF, _close_lead, _follow, _order, _task, _verify


def seed_dimensions(session):
    ranking_metadata.create_all(session.bind)
    metadata.create_all(session.bind)
    for store in "ABC":
        session.add(DimStore(store_id=store, store_name="Store " + store, service_store_code="SVC-" + store,
                             standard_province="Province", standard_city="City"))
        session.add(DimStorePoiMapping(poi_id="poi-" + store, store_id=store))
    session.execute(org_history.insert(), [dict(mapping_version="org", store_id=store,
        service_store_code="SVC-" + store, store_name="Store " + store, effective_from=AT - timedelta(days=30),
        group_key="group", group_name="Group", service_center_key="center", service_center_name="Center",
        district_key="district-" + store, district_name="District " + store,
        area_key="area-" + store, area_name="Area " + store, source_hash="synthetic") for store in "ABC"])
    session.execute(eligibility.insert(), [dict(eligibility_version="list", service_store_code="SVC-" + store,
        product_scope="精诚养车", effective_from=AT - timedelta(days=30), source_hash="synthetic") for store in "ABC"])
    session.flush()


def seed_tasks(session):
    seed_dimensions(session)
    for order_id in ("late", "self", "cross", "closed", "pre", "refund", "no-clue", "trial"):
        _order(session, order_id)
    _order(session, "byd", scope="比亚迪本品", product_type="比亚迪本品")
    _task(session, "late-task", order_id="late")
    _follow(session, "late-follow", task="late-task", order_id="late", hour=30)
    _task(session, "self-task", order_id="self")
    _verify(session, "self-verify", order_id="self")
    _task(session, "cross-a", order_id="cross", status="expired_pending_reassign", handoff=24)
    _task(session, "cross-b", order_id="cross", store="B", hour=24)
    _verify(session, "cross-verify", order_id="cross", hour=25)
    _task(session, "closed-task", order_id="closed", status="closed_no_candidate", handoff=10)
    _close_lead(session, order_id="closed", hour=10, reason="lost")
    _verify(session, "closed-verify", order_id="closed", hour=15)
    _task(session, "pre-task", order_id="pre", hour=20)
    _verify(session, "pre-verify", order_id="pre", hour=1)
    _task(session, "refund-task", order_id="refund")
    refunded = session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "refund"))
    refunded.order_status_normalized = "refunded"
    refunded.raw_payload = {"refund_completed_at": (AT + timedelta(hours=4)).isoformat()}
    _task(session, "byd-task", order_id="byd", store="B")
    _follow(session, "byd-follow", task="byd-task", order_id="byd", store="B")
    _verify(session, "byd-verify", order_id="byd", store="B")
    _verify(session, "no-clue-first", order_id="no-clue", store="C", hour=1)
    _verify(session, "no-clue-later", order_id="no-clue", store="C", hour=25)
    _task(session, "trial-task", order_id="trial", mode="trial")
    _task(session, "unassigned", order_id="trial", store=None)
    session.commit()


def freeze_both(session):
    factory = sessionmaker(session.bind, expire_on_commit=False)
    return {module: publish_module(factory, module, builder, now=CUTOFF)
        for module, builder in (("clue-overview", clues.build), ("douyin-ranking", ranking.build))}


def legacy_module(name):
    path = Path(__file__).parent / "fixtures/dydata_115_legacy" / (name + ".py")
    spec = importlib.util.spec_from_file_location("apps.api.dy_api.dashboard_publications._legacy_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_publication_remains_readable_by_frozen_old_resolver_and_sql(db_session):
    seed_tasks(db_session)
    old_marked = db_session.get(ClueAssignmentRound, "self-task")
    old_marked.is_followed = old_marked.is_follow_success = old_marked.is_self_store_verified = True
    old_marked.verified_at = AT + timedelta(hours=2)
    db_session.commit()
    publications = freeze_both(db_session)
    old_clue = legacy_module("clue_reader")
    clue_id = publications["clue-overview"].id
    # This is 678429d6's real resolver and SELECT, including the old hard
    # product-type-v2 check, against the freshly published candidate head.
    assert old_clue.resolve_publication(db_session, "clue-overview").id == clue_id
    header = db_session.scalar(select(runs.c.stats_json).where(runs.c.id == clue_id))
    assert header["contract_version"] == "product-type-v2" and header["task_metrics_contract"] == "clue-task-v3"
    old_view = old_clue.read(db_session, clue_id, {})
    assert old_view["total_clues"] == 7 and old_view["verified_count"] == 1
    assert old_view["follow_rate"] == 0.1429
    assert clues.read(db_session, clue_id, {})["follow_any_numerator"] == 2

    # Freeze 678429d6's builder as the control, then run its exact reader
    # against both publications. New task counters cannot overwrite old cells.
    old_builder, old_reader = legacy_module("ranking_build"), legacy_module("ranking_read")
    db_session.execute(runs.insert().values(id="legacy-control", module="douyin-ranking", status="building",
        cutoff=CUTOFF, created_at=CUTOFF, stats_json={}))
    old_builder.build(db_session, "legacy-control", CUTOFF)
    expected = old_reader.read_report(db_session, "legacy-control", period_start=AT, period_end=CUTOFF,
        product_scope="all", level="store")
    actual = old_reader.read_report(db_session, publications["douyin-ranking"].id,
        period_start=AT, period_end=CUTOFF, product_scope="all", level="store")
    assert actual["rows"] == expected["rows"]
    assert actual["totals"] == expected["totals"]


@pytest.fixture
def board_client(db_session, monkeypatch):
    from dy_api.auth import AuthContext, get_current_user
    from dy_api.main import create_app
    from dy_api.routes._data import get_session_dependency

    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    seed_tasks(db_session)
    publications = freeze_both(db_session)
    identity = [AuthContext(user_id="reader", username="reader", display_name="Reader", role="highest_admin",
                            store_ids=(), auth_type="test", page_keys=("A01", "A03"))]
    app = create_app()
    app.dependency_overrides[get_session_dependency] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: identity[0]
    with TestClient(app) as client:
        yield client, identity, publications


@pytest.mark.parametrize("scope,follow_den,any_num,fast_num,verify_den,verify_num,volume", [
    ("all", 7, 2, 1, 8, 3, 6), ("jingcheng", 6, 1, 0, 7, 2, 5), ("byd", 1, 1, 1, 1, 1, 1),
])
def test_normal_api_boards_share_task_counts_for_all_three_scopes(
    board_client, scope, follow_den, any_num, fast_num, verify_den, verify_num, volume,
):
    client, _, publications = board_client
    clue = client.get("/api/v1/clues/overview", params={"product_scope": scope,
        "publication_id": publications["clue-overview"].id})
    report = client.get("/api/v1/dashboard/douyin-ranking", params={"productScope": scope,
        "periodStart": "2026-11-17", "periodEnd": "2026-11-26", "level": "store",
        "publication_id": publications["douyin-ranking"].id})
    assert clue.status_code == report.status_code == 200, (clue.text, report.text)
    overview, totals = clue.json()["data"], report.json()["data"]["totals"]
    for left, right, expected in (("follow_denominator", "followDenominator", follow_den),
        ("follow_any_numerator", "followAnyNumerator", any_num), ("follow_24h_numerator", "followNumerator", fast_num),
        ("verification_denominator", "verificationDenominator", verify_den),
        ("verification_numerator", "verificationNumerator", verify_num),
        ("self_store_verification_count", "selfStoreVerificationCount", volume)):
        assert overview[left] == totals[right] == expected
    assert overview["follow_24h_rate"] == totals["follow24hRate"] == round(fast_num / follow_den, 6)
    assert overview["follow_any_rate"] == totals["followAnyRate"] == round(any_num / follow_den, 6)
    assert overview["verification_rate"] == totals["verificationRate"] == round(verify_num / verify_den, 6)
    if scope == "all":
        # 1/7 is recomputed from combined counts, never averaged from 0/6 and 1/1.
        assert totals["follow24hRate"] == 0.142857


def test_store_scope_org_and_actual_verification_store_do_not_expand_access(board_client, db_session):
    client, identity, publications = board_client
    identity[0] = replace(identity[0], role="store", store_scope_mode="specified", store_ids=("A",), page_keys=("A01",))
    response = client.get("/api/v1/clues/overview", params={"product_scope": "all"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["verification_denominator"] == 6
    assert data["self_store_verification_count"] == 4
    denied = client.get("/api/v1/clues/overview", params={"assigned_store_id": "C"})
    assert denied.status_code == 200 and denied.json()["data"]["self_store_verification_count"] == 0
    scoped = ranking.read_report(db_session, publications["douyin-ranking"].id,
        period_start=AT, period_end=CUTOFF, product_scope="all", scope_store_ids=("A",), level="group")
    assert scoped["totals"]["verification_denominator"] == 6
    assert scoped["totals"]["self_store_verification_count"] == 4
    org_scope = clues.organization_scope_store_ids(db_session, publications["clue-overview"].id,
        level="district", key='["Center","District C"]')
    assert org_scope == ("C",)
    assert clues.read(db_session, publications["clue-overview"].id,
        {"organization_store_ids": org_scope})["self_store_verification_count"] == 1


@pytest.mark.parametrize("scope", ["all", "jingcheng", "byd"])
def test_diagnostic_and_published_counts_share_the_same_fact_contract(board_client, db_session, scope):
    from apps.api.dy_api.douyin_ranking import build_douyin_ranking_report

    _, _, publications = board_client
    live = build_douyin_ranking_report(db_session, period_start=AT, period_end=CUTOFF,
        product_scope=scope)["totals"]
    frozen = ranking.read_report(db_session, publications["douyin-ranking"].id,
        period_start=AT, period_end=CUTOFF, product_scope=scope)["totals"]
    for field in ("follow_numerator", "follow_denominator", "follow_any_numerator", "follow_any_denominator",
                  "verification_numerator", "verification_denominator", "self_store_verification_count"):
        assert live[field] == frozen[field], field


def test_readiness_requires_self_store_projection_without_running_builder(board_client, db_session, monkeypatch):
    from apps.api.dy_api.dashboard_publications.verifications import self_store_verifications
    from apps.worker.dashboard_publications import check_ready

    factory = sessionmaker(db_session.bind, expire_on_commit=False)
    assert check_ready(factory, ("douyin-ranking", "clue-overview"))
    monkeypatch.setattr(ranking, "build", lambda *a, **kw: pytest.fail("readiness ran builder"))
    monkeypatch.setattr(clues, "build", lambda *a, **kw: pytest.fail("readiness ran builder"))
    self_store_verifications.drop(db_session.bind)
    assert not check_ready(factory, ("douyin-ranking", "clue-overview"))


@pytest.mark.parametrize("day,expected", [("2026-11-17", 1), ("2026-11-18", 0)])
def test_first_verification_date_before_date_filter_includes_no_clue_order(board_client, day, expected):
    client, _, _ = board_client
    overview = client.get("/api/v1/clues/overview", params={"assigned_store_id": "C",
        "assigned_date_start": day, "assigned_date_end": day}).json()["data"]
    report = client.get("/api/v1/dashboard/douyin-ranking", params={"productScope": "all", "storeId": "C",
        "periodStart": day, "periodEnd": day, "level": "store"}).json()["data"]
    assert overview["self_store_verification_count"] == report["totals"]["selfStoreVerificationCount"] == expected
    assert overview["received_task_count"] == report["totals"]["verificationDenominator"] == 0


def test_get_and_export_are_pinned_read_only_and_export_new_metrics(board_client, db_session, monkeypatch):
    from apps.api.dy_api import clue_task_metrics

    client, _, publications = board_client
    ids = {key: value.id for key, value in publications.items()}
    _follow(db_session, "newer-follow", task="self-task", order_id="self", hour=1)
    db_session.commit()
    for module in (clues, ranking):
        monkeypatch.setattr(module, "build", lambda *a, **kw: pytest.fail("GET invoked builder"))
    monkeypatch.setattr(clue_task_metrics, "load_clue_task_facts", lambda *a, **kw: pytest.fail("GET evaluated tasks"))
    monkeypatch.setattr(clue_task_metrics, "load_self_store_verifications", lambda *a, **kw: pytest.fail("GET evaluated verifications"))
    statements = []

    def guard(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert statement.lstrip().upper().startswith(("SELECT", "WITH", "PRAGMA"))
        assert not any(source in statement.lower() for source in (
            "raw_douyin", "clue_assignment_rounds", "clue_follow_up_records", "settlement_order_details"))

    event.listen(db_session.bind, "before_cursor_execute", guard)
    try:
        overview = client.get("/api/v1/clues/overview", params={"publication_id": ids["clue-overview"]})
        assert overview.status_code == 200 and overview.json()["data"]["follow_any_numerator"] == 2
        exported = client.get("/api/v1/dashboard/douyin-ranking/export", params={"productScope": "all",
            "periodStart": "2026-11-17", "periodEnd": "2026-11-26", "levels": "store",
            "metrics": "verification_rate,follow_any_rate,self_store_verification_count",
            "publication_id": ids["douyin-ranking"]})
        assert exported.status_code == 200, exported.text[:200]
        assert exported.headers["X-Publication-ID"] == ids["douyin-ranking"]
        workbook = load_workbook(BytesIO(exported.content))
        assert len(workbook.worksheets) == 3
        assert all(ids["douyin-ranking"] in sheet["A3"].value for sheet in workbook)
        assert any("自店核销量" in str(cell.value) for row in workbook.worksheets[0] for cell in row)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", guard)
    assert statements


@pytest.mark.parametrize("module,legacy_contract", [("clue-overview", "product-type-v2"), ("douyin-ranking", None)])
def test_legacy_http_view_has_unavailable_metrics_and_worker_readiness_is_strict(board_client, db_session, module, legacy_contract):
    client, _, publications = board_client
    publication_id = publications[module].id
    db_session.execute(update(runs).where(runs.c.id == publication_id).values(
        stats_json={"contract_version": legacy_contract} if legacy_contract else {}))
    db_session.commit()
    with pytest.raises(PublicationError):
        resolve_publication(db_session, module)
    assert resolve_publication(db_session, module, publication_id, allow_previous_deployment=True).status == "refreshing"
    path, params, key = ("/api/v1/clues/overview", {}, "self_store_verification_count") if module == "clue-overview" else (
        "/api/v1/dashboard/douyin-ranking", {"periodStart": "2026-11-17", "periodEnd": "2026-11-26"}, "selfStoreVerificationCount")
    response = client.get(path, params={**params, "publication_id": publication_id})
    assert response.status_code == 200, response.text
    payload = response.json()
    data = payload["data"] if module == "clue-overview" else payload["data"]["totals"]
    assert data[key] is None
    assert payload["meta"]["publication"]["status"] == "refreshing"
    assert payload["meta"]["publication"]["contractVersion"] == legacy_contract
