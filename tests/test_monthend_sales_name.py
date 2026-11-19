"""Exact frozen sales names determine both fee directions' sales attribution."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import (
    AccountQualificationSnapshot, DimStorePoiMapping, RawDouyinOrder,
    RawDouyinVerifyRecord, SettlementFeeResult,
    DataQualityIssue, SettlementScopeRule,
    DimNonCommissionOwnerAccount, DimSkuProductRule,
)
from apps.api.dy_api.rule_utils import normalize_owner_account_name
from apps.worker import account_qualification as q, settlement
from apps.worker.monthly_close_scope import inspect_month_close_scope
from apps.worker.repositories import upsert_store, upsert_store_poi_mapping
from account_qualification_fixtures import binding, seed_month_qualification
from test_data_settlement import _add_scope_rule, _dual_time, _fee_result, _load_dual_fee_fixture


def sale_order(name="Owner Dual"):
    return SimpleNamespace(owner_account_id="unrelated-transfer", owner_douyin_uid=None,
                           owner_account_name=name, raw_payload={"order_sale_info": {"transfer_nickName": name}})


def stores(session):
    for suffix in ("sale", "other"):
        upsert_store(session, "store-" + suffix, suffix)
        upsert_store_poi_mapping(session, "store-" + suffix, "poi-" + suffix, mapping_source="test")
    session.flush()


@pytest.mark.parametrize("personal_status", ["已解绑", "认证成功", "审核中"])
def test_personal_role_does_not_override_same_account_store_merchant_role(db_session, personal_status):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(), binding(kind="个人号", status=personal_status)])
    match = q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert match.store_id == "store-sale"
    assert match.as_context()["policy"] == q.SALE_ACCOUNT_MATCH_POLICY


def test_personal_success_cannot_certify_failed_merchant_record(db_session):
    version = seed_month_qualification(db_session, records=[
        binding(status="审核中"), binding(kind="个人号", status="认证成功"),
    ])
    with pytest.raises(q.AccountQualificationError, match="not_qualified"):
        q.qualified_records(db_session, version=version, order=sale_order())


def test_contradictory_statuses_for_same_merchant_role_require_review(db_session):
    version = seed_month_qualification(db_session, records=[binding(), binding(status="已解绑")])
    with pytest.raises(q.AccountQualificationError, match="name_record_conflict"):
        q.qualified_records(db_session, version=version, order=sale_order())


def test_same_account_and_name_in_two_stores_is_ambiguous(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(), binding(poi="poi-other")])
    with pytest.raises(q.AccountQualificationError, match="multiple_stores"):
        q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert q.frozen_sale_candidate_stores(db_session, version=version, order=sale_order()) == frozenset({"store-sale", "store-other"})


@pytest.mark.parametrize("poi,reason", [(None, "store_missing"), ("unknown-poi", "store_unmapped")])
def test_unproven_store_is_explicit(db_session, poi, reason):
    version = seed_month_qualification(db_session, records=[binding(poi=poi)])
    with pytest.raises(q.AccountQualificationError, match=reason):
        q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert q.frozen_sale_candidate_stores(db_session, version=version, order=sale_order()) is None


def test_ambiguous_accounts_bound_one_store_without_becoming_qualified(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session, records=[binding(), binding(douyin="second-douyin")])
    assert q.frozen_sale_candidate_stores(db_session, version=version, order=sale_order()) == frozenset({"store-sale"})
    with pytest.raises(q.AccountQualificationError, match="multiple_accounts"):
        q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert q.frozen_sale_candidate_stores(db_session, version=version, order=sale_order("unmatched")) is None


def test_explicit_disabled_scope_is_excluded_before_missing_sales_name(db_session):
    _load_dual_fee_fixture(db_session)
    _add_scope_rule(db_session, "2026-10")
    db_session.flush()
    db_session.scalar(select(SettlementScopeRule).where(SettlementScopeRule.effective_month == "2026-10")).is_active = False
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    source_order = db_session.scalar(select(RawDouyinOrder))
    source_order.raw_payload = {"receipt_amount": 10001}
    source_order.owner_account_name = None
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="explicit-disabled-scope")
    issues = list(db_session.scalars(select(DataQualityIssue).where(DataQualityIssue.source_run_id == "explicit-disabled-scope")))
    assert len(issues) == 2
    assert all(issue.issue_type == "dual_fee_missing_scope_rule" and issue.raw_context_json["scope_state"] == "disabled" for issue in issues)


@pytest.mark.parametrize("sku", [None, "unknown-sku"])
def test_explicit_noncommission_sale_with_missing_sku_does_not_block_october_close(db_session, sku):
    _load_dual_fee_fixture(db_session)
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    source_order = db_session.scalar(select(RawDouyinOrder))
    source_order.sku_id = sku
    db_session.add(DimNonCommissionOwnerAccount(
        normalized_owner_account_name=normalize_owner_account_name("Owner Dual"),
        owner_account_name="Owner Dual", is_active=True,
    ))
    version = seed_month_qualification(db_session)
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="noncommission-missing-sku",
        coupon_ids=("coupon-dual",), accounting_month="2026-10")
    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.source_run_id == "noncommission-missing-sku")))
    assert len(issues) == 2
    assert all(issue.issue_type == "dual_fee_non_commission_owner" for issue in issues)
    scope = inspect_month_close_scope(db_session, month="2026-10",
        calculation_run_id="noncommission-missing-sku", qualification_version_id=version.version_id,
        coupon_ids=("coupon-dual",))
    assert scope.complete and not scope.blocked_store_ids and scope.unscoped_issue_count == 0
    assert db_session.scalar(select(q.func.count()).select_from(SettlementFeeResult)) == 0


def test_september_missing_sku_keeps_historical_diagnostic_even_if_noncommission(db_session):
    _load_dual_fee_fixture(db_session)
    source_order = db_session.scalar(select(RawDouyinOrder))
    source_order.sku_id = "unknown-sku"
    db_session.add(DimNonCommissionOwnerAccount(
        normalized_owner_account_name=normalize_owner_account_name("Owner Dual"),
        owner_account_name="Owner Dual", is_active=True,
    ))
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="september-missing-sku")
    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.source_run_id == "september-missing-sku")))
    assert len(issues) == 2
    assert all(issue.issue_type == "dual_fee_inactive_or_unknown_sku" for issue in issues)


def test_missing_product_without_explicit_exclusion_remains_a_month_close_issue(db_session):
    _load_dual_fee_fixture(db_session)
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    db_session.scalar(select(RawDouyinOrder)).sku_id = "unknown-sku"
    version = seed_month_qualification(db_session)
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="unknown-product",
        coupon_ids=("coupon-dual",), accounting_month="2026-10")
    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.source_run_id == "unknown-product")))
    assert len(issues) == 2
    assert all(issue.issue_type == "dual_fee_inactive_or_unknown_sku" for issue in issues)
    scope = inspect_month_close_scope(db_session, month="2026-10",
        calculation_run_id="unknown-product", qualification_version_id=version.version_id,
        coupon_ids=("coupon-dual",))
    assert not scope.complete


def test_explicit_disabled_scope_precedes_inactive_product_and_does_not_block_close(db_session):
    _load_dual_fee_fixture(db_session)
    _add_scope_rule(db_session, "2026-10")
    version = seed_month_qualification(db_session)
    db_session.flush()
    db_session.scalar(select(SettlementScopeRule).where(SettlementScopeRule.effective_month == "2026-10")).is_active = False
    db_session.scalar(select(DimSkuProductRule)).is_active_product = False
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="disabled-inactive-product",
        coupon_ids=("coupon-dual",), accounting_month="2026-10")
    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.source_run_id == "disabled-inactive-product")))
    assert len(issues) == 2
    assert all(issue.issue_type == "dual_fee_missing_scope_rule" and issue.raw_context_json["scope_state"] == "disabled" for issue in issues)
    scope = inspect_month_close_scope(db_session, month="2026-10",
        calculation_run_id="disabled-inactive-product", qualification_version_id=version.version_id,
        coupon_ids=("coupon-dual",))
    assert scope.complete and not scope.blocked_store_ids and scope.unscoped_issue_count == 0


def test_duplicate_rows_and_two_pois_of_one_store_remain_one_account_one_store(db_session):
    stores(db_session)
    upsert_store_poi_mapping(db_session, "store-sale", "second-poi", mapping_source="test")
    db_session.flush()
    row = binding()
    version = seed_month_qualification(db_session, records=[row, row, binding(poi="second-poi")])
    assert db_session.get(AccountQualificationSnapshot, version.content_sha256).record_count == 2
    match = q.qualified_sale_match(db_session, version=version, order=sale_order())
    assert match.store_id == "store-sale" and match.poi_ids == ("poi-sale", "second-poi")


def test_conflicting_roster_name_isolated_to_its_named_accounts(db_session):
    stores(db_session)
    conflict = binding(account="other-account", douyin="other-handle", nickname="Conflicting")
    version = seed_month_qualification(db_session, records=[binding(), conflict])
    # Model an older captured source containing conflicting aliases. Its digest
    # remains valid evidence and only its possible names become ambiguous.
    snapshot = db_session.get(AccountQualificationSnapshot, version.content_sha256)
    records = [dict(row) for row in snapshot.records_json]
    for row in records:
        if row["account_id"] == "other-account":
            row["raw_payload"] = {**row["raw_payload"], "抖音号昵称": "Other conflicting"}
    content = q.digest({"policy": version.policy_version, "records": records})
    db_session.add(AccountQualificationSnapshot(content_sha256=content, records_json=records,
        record_count=len(records), policy_version=version.policy_version))
    db_session.flush()
    isolated_version = SimpleNamespace(version_id=version.version_id, content_sha256=content, policy_version=version.policy_version)
    assert q.qualified_sale_match(db_session, version=isolated_version, order=sale_order()).store_id == "store-sale"
    with pytest.raises(q.AccountQualificationError, match="roster_name_source_conflict"):
        q.qualified_records(db_session, version=isolated_version, order=sale_order("Conflicting"))


def test_saved_attribution_does_not_follow_later_poi_mapping_changes(db_session):
    stores(db_session)
    version = seed_month_qualification(db_session)
    first = q.qualified_sale_match(db_session, version=version, order=sale_order())
    mapping = db_session.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == "poi-sale"))
    mapping.store_id = "store-other"
    db_session.flush()
    pinned = q.qualified_sale_match(db_session, version=version, order=sale_order(), pinned_context=first.as_context())
    assert pinned.store_id == "store-sale"


def test_fee_generation_replaces_unpublished_old_id_attribution_and_is_idempotent(db_session):
    _load_dual_fee_fixture(db_session)
    _add_scope_rule(db_session, "2026-10")
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    source_order = db_session.scalar(select(RawDouyinOrder))
    source_order.owner_account_id = "unmatched-encrypted-transfer"
    source_order.raw_payload = {**source_order.raw_payload, "order_sale_info": {
        "transfer_uid": "unmatched-encrypted-transfer", "transfer_nickName": "Owner Dual"}}
    del source_order.raw_payload["owner_account_name"]
    version = seed_month_qualification(db_session, records=[binding(poi="poi-verify")])
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="new-name-policy")
    rows = [_fee_result(db_session, "coupon-dual", direction) for direction in (1, 2)]
    assert all(row.sale_store_id == "store-verify" for row in rows)
    assert all(row.sale_account_match_json["source_field"] == "order_sale_info.transfer_nickName" for row in rows)
    assert all(row.sale_account_match_json["qualification_version_id"] == version.version_id for row in rows)
    identifiers = [row.fee_result_id for row in rows]
    rows[0].sale_account_match_json = None
    rows[0].input_fingerprint = "old-id-policy"
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="migrate-old-unpublished")
    replacement = _fee_result(db_session, "coupon-dual", 1)
    assert replacement.fee_result_id != identifiers[0]
    assert replacement.sale_account_match_json["policy"] == q.SALE_ACCOUNT_MATCH_POLICY
    after = db_session.scalar(select(q.func.count()).select_from(SettlementFeeResult))
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="retry-new-policy")
    assert db_session.scalar(select(q.func.count()).select_from(SettlementFeeResult)) == after
    db_session.expire_all()
    assert _fee_result(db_session, "coupon-dual", 1).sale_account_match_json["store_id"] == "store-verify"
