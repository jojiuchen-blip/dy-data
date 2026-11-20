"""Read-only internal trial survives zero official bills and retains pinned exports."""
from dataclasses import replace
from decimal import Decimal
from datetime import UTC, datetime, timedelta
from io import StringIO
from csv import DictReader
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, insert, select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.dashboard_publications import fee_trial, finance
from apps.api.dy_api.dashboard_publications.lifecycle import publish_module
from apps.api.dy_api.dashboard_publications.schema import heads, metadata, runs
from apps.api.dy_api.dashboard_publications.sources import MODULE_CONTRACT_VERSIONS
from apps.api.dy_api.models import DimStore, RawDouyinOrder, SettlementFeeResult, SettlementStatement
from test_month_close_auto_bootstrap import MONTH, NOW, _quiet_sqlite_progress, _seed
from test_month_close_auto_bootstrap import bootstrap_session  # noqa: F401
from test_certified_month_close import _close


AT = datetime(2026, 11, 20, tzinfo=UTC)
PARAMS = {"month": "2026-10", "feeDirection": "PROMOTION"}


def seed_trial(session, publication_id="trial-a", amount=12345):
    metadata.create_all(session.bind)
    session.execute(insert(runs).values(id=publication_id, module="settlement", status="success",
        cutoff=AT, created_at=AT, published_at=AT, stats_json={"contract_version": MODULE_CONTRACT_VERSIONS["settlement"]}))
    if publication_id == "trial-a":
        session.execute(insert(heads).values(module="settlement", publication_id=publication_id))
        session.add_all([DimStore(store_id="A", store_name="门店甲"), DimStore(store_id="B", store_name="门店乙")])
    session.execute(insert(finance.dimensions).values(publication_id=publication_id, kind="fee_trial", key="2026-10",
        value={"schema_version": 1, "source_success_days": 31, "source_total_days": 31, "scope_unresolved": True}))
    for position, (store_id, record_status, direction, fee) in enumerate([
        ("A", "CALCULATED", 1, amount), ("A", "CALCULATED", 1, -45),
        ("B", "CALCULATED", 1, 99999), (None, "PENDING", 1, None),
        ("A", "PENDING", 1, None), (None, "EXCLUDED", 1, None),
        ("A", "CALCULATED", 2, 678),
    ]):
        session.execute(insert(fee_trial.rows).values(publication_id=publication_id, row_id=str(position),
            month="2026-10", fee_direction=direction, coupon_id=f"券-{position}", order_id=f"订单-{position}",
            store_id=store_id, store_name="门店甲" if store_id == "A" else "门店乙" if store_id else None,
            product_type="精诚养车", sku_id="99999999999999999999", fee_amount_cent=fee,
            base_amount_cent=None if fee is None else fee * 10, fee_rate="0.1" if fee is not None else None,
            rule_version="费率一" if fee is not None else None, record_status=record_status,
            reason_code="needs_source" if fee is None else None, reason="缺少销售门店资料" if fee is None else None,
            search_text=f"{store_id or ''} 门店甲 SAP001 订单-{position} 券-{position}"))
    session.commit()


@pytest.fixture
def trial_client(db_session, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    seed_trial(db_session)
    identities = [AuthContext(user_id="reader", username="reader", display_name="财务",
        role="highest_admin", store_ids=(), auth_type="test", page_keys=("FIN01", "FIN02"))]
    app = create_app()
    app.dependency_overrides[get_session_dependency] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: identities[0]
    with TestClient(app) as client:
        yield client, identities


def test_trial_zero_formal_bills_amounts_nullable_read_only(trial_client, db_session, monkeypatch):
    client, _ = trial_client
    monkeypatch.setattr(fee_trial, "build", lambda *a: pytest.fail("GET must not build"))
    sql = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        sql.append(statement)
    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        response = client.get("/api/v1/admin/finance/trial", params=PARAMS)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "TRIAL"
        assert data["summary"] == {"calculatedFeeCent": 112299, "calculatedCouponCount": 3,
            "pendingCouponCount": 2, "excludedCouponCount": 1, "candidateCouponCount": 6, "coverageComplete": False}
        assert data["coverage"]["sourceSuccessDays"] == data["coverage"]["sourceTotalDays"] == 31
        assert data["coverage"]["reasons"][0]["couponCount"] == 2
        pending = [row for row in data["list"] if row["recordStatus"] != "CALCULATED"]
        assert pending and all(row["feeAmountCent"] is None for row in pending)
        empty = client.get("/api/v1/admin/finance/trial", params=PARAMS | {"q": "找不到"})
        assert empty.json()["data"]["summary"]["calculatedFeeCent"] is None
        assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 0
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in sql)


def test_scopes_direction_and_permissions_are_rechecked(trial_client):
    client, identities = trial_client
    identities[0] = replace(identities[0], role="admin", store_scope_mode="selected", store_ids=("A",), page_keys=("FIN01",))
    response = client.get("/api/v1/admin/finance/trial", params=PARAMS | {"publication_id": "trial-a"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert {row["storeId"] for row in data["list"]} == {"A"}
    assert data["summary"]["calculatedFeeCent"] == 12300
    assert data["summary"]["pendingCouponCount"] == 1
    assert client.get("/api/v1/admin/finance/trial", params=PARAMS | {"storeId": "B"}).status_code == 403
    assert client.get("/api/v1/admin/finance/trial", params=PARAMS | {"feeDirection": "MANAGEMENT"}).status_code == 403
    identities[0] = replace(identities[0], role="store")
    assert client.get("/api/v1/admin/finance/trial", params=PARAMS).status_code == 403
    assert client.get("/api/v1/admin/finance/trial/export", params=PARAMS | {"publication_id": "trial-a"}).status_code == 403


def test_export_keeps_exact_pin_filters_and_chinese_nullable_bytes(trial_client, db_session):
    client, _ = trial_client
    page = client.get("/api/v1/admin/finance/trial", params=PARAMS | {"pageSize": 1, "q": "SAP001"})
    assert page.status_code == 200
    identifier = page.json()["meta"]["publication"]["id"]
    seed_trial(db_session, "trial-b", amount=999)
    db_session.execute(update(heads).where(heads.c.module == "settlement").values(publication_id="trial-b"))
    db_session.commit()
    result = client.get("/api/v1/admin/finance/trial/export", params=PARAMS | {"publication_id": identifier, "q": "SAP001"})
    assert result.status_code == 200, result.text
    assert result.content.startswith(b"\xef\xbb\xbf")
    assert result.headers["x-publication-id"] == "trial-a"
    records = list(DictReader(StringIO(result.content.decode("utf-8-sig"))))
    assert len(records) == 6
    assert {row["试算版本"] for row in records} == {"trial-a"}
    assert {row["数据状态"] for row in records} == {"试算／待核验"}
    assert any(row["试算费用（元）"] == "123.45" for row in records)
    assert any(row["试算费用（元）"] == "-0.45" for row in records)
    assert all(row["试算费用（元）"] == "" for row in records if row["核对状态"] != "已算费用（试算）")
    assert "筛选内已算费用小计（元）" not in records[0]
    assert sum(Decimal(row["试算费用（元）"] or "0") for row in records) == Decimal("1122.99")
    assert client.get("/api/v1/admin/finance/trial/export", params=PARAMS).status_code == 422


@pytest.mark.parametrize("extra", [{"month": "2026-11"}, {"month": "bad"}, {"recordStatus": "oops"}])
def test_invalid_or_unbuilt_period_never_falls_back(trial_client, extra):
    client, _ = trial_client
    result = client.get("/api/v1/admin/finance/trial", params=PARAMS | extra)
    assert result.status_code in (422, 503), result.text


def test_real_month_builder_preserves_calculated_trial_with_zero_official_bills(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    with factory.begin() as writer:
        order = writer.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
        order.owner_account_name = "待补证的账号"
        order.raw_payload = {**order.raw_payload, "owner_account_name": "待补证的账号"}
    _close(factory)
    with factory() as reader:
        assert reader.scalar(select(func.count()).select_from(SettlementStatement)) == 0
    with factory.begin() as writer:
        # Existing production trial calculations precede supplemental mapping
        # snapshots. Strengthening formal eligibility must keep those amounts
        # readable for internal verification while the proof is prepared.
        for result in writer.scalars(select(SettlementFeeResult)):
            evidence = dict(result.sale_account_match_json or {})
            evidence.pop("store_evidence", None)
            result.sale_account_match_json = evidence
    metadata.create_all(bootstrap_session.bind)
    publication = publish_module(factory, "settlement", finance.build_settlement, now=NOW + timedelta(days=1))
    with factory() as reader:
        trial = fee_trial.read(reader, publication.id, month=MONTH, fee_direction="PROMOTION")
        assert trial["summary"]["calculated_fee_cent"] == 3000
        assert trial["summary"]["calculated_coupon_count"] == 1
        assert trial["summary"]["pending_coupon_count"] == 1
        assert trial["summary"]["candidate_coupon_count"] == 2
        assert {row["record_status"] for row in trial["list"]} == {"CALCULATED", "PENDING"}
        assert all(row["fee_amount_cent"] is None for row in trial["list"] if row["record_status"] == "PENDING")


def test_pending_display_uses_unique_frozen_account_store_and_preserves_conflicts(db_session):
    from account_qualification_fixtures import seed_month_qualification
    from apps.worker.monthly_store_evidence import freeze_store_evidence

    version = seed_month_qualification(db_session)
    db_session.add_all([DimStore(store_id="A", store_name="门店甲", created_at=datetime(2026, 9, 1, tzinfo=UTC)),
                       DimStore(store_id="B", store_name="门店乙", created_at=datetime(2026, 9, 1, tzinfo=UTC))])
    db_session.flush()
    base = {"kind": "account", "key": "owner-dual", "store_id": "A",
        "source_reference": "synthetic-October-verified-map", "source_sha256": "a" * 64,
        "observed_at": "2026-10-31T15:00:00+00:00", "valid_from": "2026-10-01", "valid_to": "2026-10-31"}
    first = freeze_store_evidence(db_session, qualification_version=version, facts=[base])
    candidates = {"coupon": {"owner_account_name": "Owner Dual", "raw_payload": {"owner_account_name": "Owner Dual"}}}
    close = SimpleNamespace(qualification_version_id=version.version_id)
    matched, provenance = fee_trial._pending_sale_stores(db_session, close, candidates)
    assert matched == {"coupon": "A"}
    assert provenance["version_id"] == first.version_id
    assert "monthly_store_evidence_version_id" not in db_session.info
    freeze_store_evidence(db_session, qualification_version=version,
        facts=[base, {**base, "kind": "poi", "key": "poi-sale", "store_id": "B"}])
    matched, provenance = fee_trial._pending_sale_stores(db_session, close, candidates)
    assert matched == {}
    assert provenance["version_id"] != first.version_id


def test_store_summary_same_pin_filters_unknown_bucket_and_independent_dedup(trial_client, db_session):
    client, _ = trial_client
    db_session.execute(insert(fee_trial.rows).values(publication_id="trial-a", row_id="moved-adjustment",
        month="2026-10", fee_direction=1, coupon_id="券-0", order_id="订单-0", store_id="B", store_name="门店乙",
        product_type="精诚养车", fee_amount_cent=-90, base_amount_cent=-900, record_status="CALCULATED", search_text="B 门店乙 订单-0 券-0"))
    db_session.commit()
    params = PARAMS | {"publication_id": "trial-a"}
    response = client.get("/api/v1/admin/finance/trial/stores", params=params)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert response.json()["meta"]["publication"]["id"] == "trial-a"
    stores = {row["storeId"]: row for row in data["list"]}
    assert data["total"] == 3
    assert stores["A"]["calculatedFeeCent"] == 12300
    assert stores["A"]["pendingCouponCount"] == 1
    assert stores[None]["storeName"] == "归属待核验"
    assert stores[None]["calculatedFeeCent"] is None
    assert stores[None]["pendingCouponCount"] == stores[None]["excludedCouponCount"] == 1
    assert data["summary"]["calculatedFeeCent"] == 112209
    assert data["summary"]["candidateCouponCount"] == 6
    assert sum(row["candidateCouponCount"] for row in stores.values()) == 7
    assert sum(row["calculatedFeeCent"] or 0 for row in stores.values()) == data["summary"]["calculatedFeeCent"]
    page = client.get("/api/v1/admin/finance/trial/stores", params=params | {"pageSize": 1})
    assert len(page.json()["data"]["list"]) == 1
    assert page.json()["data"]["summary"] == data["summary"]
    pending = client.get("/api/v1/admin/finance/trial/stores", params=params | {"recordStatus": "PENDING"})
    assert pending.json()["data"]["summary"]["calculatedFeeCent"] is None
    assert all(row["calculatedFeeCent"] is None for row in pending.json()["data"]["list"])
    searched = client.get("/api/v1/admin/finance/trial/stores", params=params | {"q": "订单-0"})
    assert searched.json()["data"]["summary"]["calculatedFeeCent"] == 12255


def test_store_summary_scope_and_both_direction_permissions(trial_client):
    client, identities = trial_client
    identities[0] = replace(identities[0], role="admin", store_scope_mode="selected", store_ids=("A",), page_keys=("FIN01", "FIN02"))
    for direction, amount in (("PROMOTION", 12300), ("MANAGEMENT", 678)):
        params = PARAMS | {"feeDirection": direction, "publication_id": "trial-a"}
        response = client.get("/api/v1/admin/finance/trial/stores", params=params)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert {item["storeId"] for item in data["list"]} == {"A"}
        assert data["summary"]["calculatedFeeCent"] == amount
        downloaded = client.get("/api/v1/admin/finance/trial/stores/export", params=params)
        assert downloaded.status_code == 200, downloaded.text
        records = list(DictReader(StringIO(downloaded.content.decode("utf-8-sig"))))
        assert [item["汇总层级"] for item in records] == ["门店", "总计"]
        assert records[0]["门店ID"] == "A"
    identities[0] = replace(identities[0], role="store")
    assert client.get("/api/v1/admin/finance/trial/stores", params=PARAMS).status_code == 403
    assert client.get("/api/v1/admin/finance/trial/stores/export", params=PARAMS | {"publication_id": "trial-a"}).status_code == 403


@pytest.mark.parametrize("q", (None, "没有任何命中"))
def test_store_summary_chinese_csv_total_even_empty_same_version(trial_client, db_session, q):
    client, _ = trial_client
    params = PARAMS | {"publication_id": "trial-a"}
    if q:
        params["q"] = q
    page = client.get("/api/v1/admin/finance/trial/stores", params=params)
    assert page.status_code == 200, page.text
    seed_trial(db_session, "trial-b", amount=1)
    db_session.execute(update(heads).where(heads.c.module == "settlement").values(publication_id="trial-b"))
    db_session.commit()
    response = client.get("/api/v1/admin/finance/trial/stores/export", params=params)
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["x-publication-id"] == "trial-a"
    assert response.headers["x-export-result"] == "SUCCESS"
    records = list(DictReader(StringIO(response.content.decode("utf-8-sig"))))
    assert records[-1]["汇总层级"] == "总计"
    assert {item["试算版本"] for item in records} == {"trial-a"}
    assert sum(item["汇总层级"] == "总计" for item in records) == 1
    if q:
        assert len(records) == 1
        assert records[0]["候选券数"] == "0"
        assert records[0]["已算费用（元）"] == ""
    else:
        assert len(records) == 4
        assert records[-1]["已算费用（元）"] == "1122.99"
        assert records[-1]["候选券数"] == "6"
        unknown = next(item for item in records if item["门店名称"] == "归属待核验")
        assert unknown["汇总层级"] == "门店" and unknown["已算费用（元）"] == ""


def test_store_summary_preserves_true_calculated_zero_and_exclusion_zero(trial_client, db_session):
    client, _ = trial_client
    db_session.execute(update(fee_trial.rows).where(fee_trial.rows.c.store_id == "B").values(fee_amount_cent=0))
    db_session.commit()
    result = client.get("/api/v1/admin/finance/trial/stores", params=PARAMS)
    store = next(item for item in result.json()["data"]["list"] if item["storeId"] == "B")
    assert store["calculatedFeeCent"] == 0 and store["calculatedCouponCount"] == 1
    excluded = client.get("/api/v1/admin/finance/trial/stores", params=PARAMS | {"recordStatus": "EXCLUDED"})
    assert excluded.json()["data"]["summary"]["calculatedFeeCent"] == 0
    assert excluded.json()["data"]["list"][0]["calculatedFeeCent"] is None
