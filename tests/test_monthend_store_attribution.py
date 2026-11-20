"""Resolve monthly sales stores using immutable, period-specific evidence."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimStore, DimStorePoiMapping, RawDouyinOrder, RawDouyinVerifyRecord
from apps.worker import account_qualification as q, month_close
from apps.worker.monthly_store_evidence import freeze_store_evidence
from apps.worker.repositories import upsert_aweme_account, upsert_store, upsert_store_poi_mapping
from account_qualification_fixtures import binding, seed_month_qualification
from test_certified_month_close import _bills, _close
from test_month_close_auto_bootstrap import MONTH, NOW, _quiet_sqlite_progress, _seed
from test_month_close_auto_bootstrap import bootstrap_session  # noqa: F401
from test_monthend_sales_name import sale_order, stores
from test_protected_billing_authority_postgres import postgres_engine  # noqa: F401


def store_evidence(session, version, *, accounts=(), pois=(), aliases=(), alias_valid_to=None):
    facts = []
    month = version.business_month
    for store in session.scalars(select(DimStore)):
        store.created_at = q.month_bounds(month)[1] - timedelta(days=32)
    session.flush()
    for kind, relationships in (("account", accounts), ("poi", pois)):
        for key, store_id in relationships:
            facts.append({
                "kind": kind, "key": key, "store_id": store_id,
                "source_reference": f"synthetic/{month}/{kind}/{key}/{store_id}",
                "source_sha256": q.digest([month, kind, key, store_id]),
                "observed_at": (q.month_bounds(month)[1] - timedelta(hours=1)).isoformat(),
                "valid_from": month + "-01", "valid_to": None,
            })
    for name, account_id, douyin_id in aliases:
        facts.append({
            "kind": "alias", "key": name, "account_id": account_id, "douyin_id": douyin_id,
            "source_reference": f"synthetic/{month}/alias/{name}/{account_id}/{douyin_id}",
            "source_sha256": q.digest([month, name, account_id, douyin_id]),
            "observed_at": (q.month_bounds(month)[1] - timedelta(hours=1)).isoformat(),
            "valid_from": month + "-01", "valid_to": alias_valid_to,
        })
    return freeze_store_evidence(session, qualification_version=version, facts=facts)


def dated_sale_order(name, day=5):
    order = sale_order(name)
    order.sale_time = datetime(2026, 10, day, 12, tzinfo=q.SHANGHAI)
    return order


@pytest.mark.parametrize("poi", [None, "unmapped-poi"])
def test_proven_unique_store_does_not_require_poi_match(db_session, poi):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(poi=poi)])
    frozen = store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")])
    match = q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert match.store_id == "store-sale"
    assert match.as_context()["store_evidence"] == frozen.as_context()


def test_unique_period_poi_is_fallback_when_account_store_is_unproven(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session)
    store_evidence(db_session, version, pois=[("poi-sale", "store-sale")])
    assert q.qualified_sale_match(db_session, version=version, order=sale_order()).store_id == "store-sale"


@pytest.mark.parametrize("case,reason", [
    ("account_multiple", "multiple_stores"), ("poi_multiple", "multiple_stores"),
    ("paths_conflict", "store_conflict"),
])
def test_conflicting_evidence_blocks_fee_and_bounds_both_candidate_stores(db_session, case, reason):
    stores(db_session)
    version = seed_month_qualification(db_session)
    accounts = [("owner-dual", "store-sale")]
    pois = []
    if case == "account_multiple":
        accounts.append(("owner-dual", "store-other"))
    elif case == "poi_multiple":
        accounts = []
        pois = [("poi-sale", "store-sale"), ("poi-sale", "store-other")]
    else:
        pois = [("poi-sale", "store-other")]
    store_evidence(db_session, version, accounts=accounts, pois=pois)
    with pytest.raises(q.AccountQualificationError, match=reason) as caught:
        q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert caught.value.candidate_store_ids == {"store-sale", "store-other"}
    assert q.frozen_sale_candidate_stores(db_session, version=version, order=sale_order()) == {
        "store-sale", "store-other",
    }


def test_partially_unproven_name_candidates_keep_unbounded_impact(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(), binding(account="unknown", douyin="other")])
    store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")])
    assert q.frozen_sale_candidate_stores(db_session, version=version, order=sale_order()) is None
    with pytest.raises(q.AccountQualificationError, match="multiple_accounts"):
        q.qualified_sale_match(db_session, version=version, order=sale_order())


def test_personal_record_cannot_supply_another_sales_poi(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(), binding(kind="个人号", poi="poi-other")])
    store_evidence(db_session, version, pois=[("poi-sale", "store-sale"), ("poi-other", "store-other")])
    match = q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert match.store_id == "store-sale" and match.poi_ids == ("poi-sale",)


def test_current_mapping_changes_do_not_move_a_frozen_sales_store(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session)
    store_evidence(db_session, version, pois=[("poi-sale", "store-sale")])
    first = q.qualified_sale_match(db_session, version=version, order=sale_order())
    mapping = db_session.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == "poi-sale"))
    mapping.store_id = "store-other"
    db_session.flush()
    retried = q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert retried.as_context() == first.as_context()


def test_new_mapping_changes_new_execution_while_retry_keeps_its_selected_version(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(poi="unmapped-poi")])
    first = store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")])
    original = q.qualified_sale_match(db_session, version=version, order=sale_order())
    latest = store_evidence(db_session, version, accounts=[("owner-dual", "store-other")])
    assert latest.version_id != first.version_id
    repaired = q.qualified_sale_match(db_session, version=version, order=sale_order(), pinned_context=original.as_context())
    assert repaired.store_id == "store-other"
    assert repaired.store_evidence == latest.as_context()
    db_session.info["monthly_store_evidence_version_id"] = first.version_id
    retried = q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert retried.as_context() == original.as_context()


def test_frozen_evidence_cannot_be_overridden_by_old_fee_context(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session)
    store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")])
    first = q.qualified_sale_match(db_session, version=version, order=sale_order())
    forged = {**first.as_context(), "store_id": "store-other"}
    assert q.qualified_sale_match(db_session, version=version, order=sale_order(), pinned_context=forged).store_id == "store-sale"


def test_exact_proven_old_name_keeps_original_name_and_records_renamed_roster_identity(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(nickname="Current Literal")])
    frozen = store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")],
                            aliases=[("Old Literal", "owner-dual", "dy-owner")])
    match = q.qualified_sale_match(db_session, version=version, order=dated_sale_order("Old Literal"))
    context = match.as_context()
    assert match.store_id == "store-sale"
    assert context["account_name"] == "Old Literal"
    assert context["name_match_source"] == "frozen_historical_alias"
    assert context["matched_roster_names"] == ["Current Literal"]
    assert context["store_evidence"] == frozen.as_context()
    with pytest.raises(q.AccountQualificationError, match="sale_name_unmatched"):
        q.qualified_sale_match(db_session, version=version, order=dated_sale_order("old literal"))


def test_historical_alias_cannot_overrule_another_exact_frozen_identity(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[
        binding(nickname="Current Literal"),
        binding(account="other", douyin="other-handle", nickname="Old Literal", poi="poi-other"),
    ])
    store_evidence(db_session, version,
        accounts=[("owner-dual", "store-sale"), ("other", "store-other")],
        aliases=[("Old Literal", "owner-dual", "dy-owner")])
    with pytest.raises(q.AccountQualificationError, match="multiple_accounts"):
        q.qualified_sale_match(db_session, version=version, order=dated_sale_order("Old Literal"))
    assert q.frozen_sale_candidate_stores(db_session, version=version, order=sale_order("Old Literal")) == {
        "store-sale", "store-other",
    }


def test_proven_old_name_cannot_certify_a_personal_account(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(kind="个人号", nickname="Current Literal")])
    store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")],
                   aliases=[("Old Literal", "owner-dual", "dy-owner")])
    with pytest.raises(q.AccountQualificationError, match="account_not_qualified"):
        q.qualified_sale_match(db_session, version=version, order=dated_sale_order("Old Literal"))


def test_historical_name_interval_is_checked_at_original_sale_not_month_end(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(nickname="Current Literal")])
    store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")],
                   aliases=[("Old Literal", "owner-dual", "dy-owner")], alias_valid_to="2026-10-10")
    assert q.qualified_sale_match(db_session, version=version, order=dated_sale_order("Old Literal", 5)).store_id == "store-sale"
    with pytest.raises(q.AccountQualificationError, match="sale_name_unmatched"):
        q.qualified_sale_match(db_session, version=version, order=dated_sale_order("Old Literal", 20))
    with pytest.raises(q.AccountQualificationError, match="alias_sale_time_missing"):
        q.qualified_sale_match(db_session, version=version, order=sale_order("Old Literal"))


def test_month_input_ignores_later_sales_relationships_and_tracks_new_evidence(db_session):
    _seed(db_session)
    version = q.freeze_month(db_session, MONTH, now=NOW)
    first_evidence = store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")])
    revisions = month_close.published_days_revisions(db_session, MONTH)
    original = month_close._calculation_inputs_digest(db_session, MONTH, revisions, monthly=True)
    upsert_store(db_session, "other", "Later Store")
    upsert_aweme_account(db_session, "owner-dual", store_id="other", binding_status="later")
    mapping = db_session.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == "poi-sale"))
    mapping.store_id = "other"
    db_session.flush()
    assert month_close._calculation_inputs_digest(db_session, MONTH, revisions, monthly=True) == original
    store_evidence(db_session, version, accounts=[("owner-dual", "other")])
    assert month_close._calculation_inputs_digest(db_session, MONTH, revisions, monthly=True) != original
    db_session.info["monthly_store_evidence_version_id"] = first_evidence.version_id
    assert month_close._calculation_inputs_digest(db_session, MONTH, revisions, monthly=True) == original


def test_old_literal_name_keeps_its_proven_store_in_the_month_input_graph(db_session):
    _seed(db_session, records=[binding(nickname="Current Literal")], days=False)
    for order in db_session.scalars(select(RawDouyinOrder)):
        order.owner_account_name = "Old Literal"
        order.sale_time = datetime(2026, 10, 5, 12, tzinfo=q.SHANGHAI)
        order.raw_payload = {**order.raw_payload, "owner_account_name": "Old Literal"}
    version = q.freeze_month(db_session, MONTH, now=NOW)
    store_evidence(db_session, version, accounts=[("owner-dual", "store-sale")],
                   aliases=[("Old Literal", "owner-dual", "dy-owner")])
    original = month_close._calculation_inputs_digest(db_session, MONTH, [], monthly=True)
    db_session.get(DimStore, "store-sale").is_active = False
    db_session.flush()
    assert month_close._calculation_inputs_digest(db_session, MONTH, [], monthly=True) != original


def test_new_peer_evidence_keeps_both_directions_of_prior_formal_bills(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session, records=[binding(), binding(
        account="other", poi="poi-other", douyin="other-handle", nickname="Other Literal",
    )])
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    with factory.begin() as session:
        upsert_store(session, "other", "Other Store")
        upsert_store_poi_mapping(session, "other", "poi-other", mapping_source="synthetic")
        order = session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
        order.owner_account_name = "Other Literal"
        order.raw_payload = {"owner_account_name": "Other Literal"}
        session.get(RawDouyinVerifyRecord, "verify-middle").poi_id = "poi-other"
        version = q.freeze_month(session, MONTH, now=NOW)
        first = store_evidence(session, version, accounts=[("owner-dual", "store-sale"), ("other", "other")])
    first_job = _close(factory)
    with factory() as session:
        first_bills = _bills(session)
        assert set(first_bills) == {"store-sale", "store-verify"}
    with factory.begin() as session:
        order = session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
        order.raw_payload = {**order.raw_payload, "receipt_amount": 10001}
        version = q.frozen_version(session, MONTH)
        later = store_evidence(session, version,
            accounts=[("owner-dual", "store-sale"), ("other", "other")], pois=[("poi-sale", "store-sale")])
        assert later.version_id != first.version_id
    assert _close(factory) != first_job
    with factory() as session:
        later_bills = _bills(session)
        assert set(later_bills) == {"store-sale", "store-verify", "other"}
        assert {key: later_bills[key] for key in first_bills} == first_bills
        assert month_close.require_current_month_qualification(session, MONTH).version_id == version.version_id


def test_postgres_conflict_scope_and_evidence_retry(postgres_engine):
    with Session(postgres_engine, autoflush=False) as session:
        test_new_mapping_changes_new_execution_while_retry_keeps_its_selected_version(session)


def test_postgres_peer_evidence_preserves_formal_bills(postgres_engine, monkeypatch):
    with Session(postgres_engine, autoflush=False) as session:
        test_new_peer_evidence_keeps_both_directions_of_prior_formal_bills(session, monkeypatch)
