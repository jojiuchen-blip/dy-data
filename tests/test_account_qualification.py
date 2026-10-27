"""No current-state or nickname inference may become historical qualification."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.models import (
    AccountQualificationObservation as Observation, AccountQualificationSnapshot as Snapshot,
    AccountQualificationVersion as Version, DimAwemeAccount, RawDouyinOrder,
    RawDouyinVerifyRecord, SettlementFeeResult, SettlementFeeResultCurrent,
)
from apps.worker import account_qualification as q, month_close, settlement
from apps.worker.browser_exports import backend_aweme as backend
from account_qualification_fixtures import binding, observe, seed_month_qualification
from test_data_settlement import _load_dual_fee_fixture, _add_scope_rule, _dual_time, _fee_result
from test_data_settlement import _load_openapi_sale_binding_fixture
from apps.worker.repositories import upsert_aweme_binding, upsert_store


def order(account="owner-dual", uid=None):
    return SimpleNamespace(owner_account_id=account, owner_douyin_uid=uid, owner_account_name="same nickname")


@pytest.mark.parametrize("kind", ["子机构门店号", "子机构区域号"])
def test_same_source_row_qualifies_and_certification_text_is_unrestricted(db_session, kind):
    version = seed_month_qualification(db_session, records=[binding(kind=kind)])
    assert q.qualified_version(db_session, month="2026-10", order=order()).version_id == version.version_id


@pytest.mark.parametrize("kind,status", [("20", "认证成功"), ("子机构经营号", "认证成功"), ("", "认证成功"), ("子机构门店号", "active"), ("子机构门店号", "1")])
def test_unknown_source_contract_never_becomes_successful_snapshot(db_session, kind, status):
    identity = observe(db_session, [binding(kind=kind, status=status)])
    row = db_session.get(Observation, identity)
    assert row.state == "failed" and row.content_sha256 is None and not row.complete
    assert db_session.scalar(select(func.count()).select_from(Snapshot)) == 0
    with pytest.raises(q.AccountQualificationError):
        q.freeze_month(db_session, "2026-10", now=q.month_bounds("2026-10")[1])


def test_personal_row_cannot_supply_other_rows_success_or_override_exact_success(db_session):
    rows = [binding(kind="子机构区域号", status="审核中"), binding(kind="个人号", douyin="personal")]
    seed_month_qualification(db_session, records=rows)
    with pytest.raises(q.AccountQualificationError, match="not_qualified"):
        q.qualified_version(db_session, month="2026-10", order=order())


def test_personal_conflict_does_not_pollute_qualified_exact_identity(db_session):
    rows = [binding(), binding(kind="个人号", douyin="personal", status="已解绑", poi="different")]
    seed_month_qualification(db_session, records=rows)
    assert q.qualified_version(db_session, month="2026-10", order=order())


def test_handles_and_nicknames_never_bridge_uid_namespace(db_session):
    seed_month_qualification(db_session, records=[binding(douyin="uid-looks-same")])
    with pytest.raises(q.AccountQualificationError, match="not_qualified"):
        q.qualified_version(db_session, month="2026-10", order=order("different", "uid-looks-same"))


def test_source_content_deduplicates_while_every_attempt_is_preserved(db_session):
    observe(db_session, offset=90)
    observe(db_session, offset=60)
    assert db_session.scalar(select(func.count()).select_from(Snapshot)) == 1
    assert db_session.scalar(select(func.count()).select_from(Observation)) == 2


@pytest.mark.parametrize("offset,duration,complete", [(121, 10, True), (60, 60, True), (60, 61, True), (60, 10, False)])
def test_monthend_window_rejects_stale_cross_cutoff_and_partial(db_session, offset, duration, complete):
    observe(db_session, offset=offset, duration=duration, complete=complete)
    with pytest.raises(q.AccountQualificationError):
        q.freeze_month(db_session, "2026-10", now=q.month_bounds("2026-10")[1] + timedelta(hours=1))


def test_latest_failed_attempt_blocks_older_success_and_next_month_cannot_repair(db_session):
    observe(db_session, offset=90)
    observe(db_session, offset=30, complete=False)
    observe(db_session, month="2026-11")
    with pytest.raises(q.AccountQualificationError):
        q.freeze_month(db_session, "2026-10", now=q.month_bounds("2026-11")[1])


def test_running_attempt_blocks_month_even_if_another_succeeded(db_session):
    _, cutoff = q.month_bounds("2026-10")
    q.start_observation(db_session, source_run_id="killed", started_at=cutoff - timedelta(minutes=100))
    observe(db_session)
    with pytest.raises(q.AccountQualificationError):
        q.freeze_month(db_session, "2026-10", now=cutoff)


def test_october_27_and_early_freeze_cannot_manufacture_monthend(db_session):
    _, cutoff = q.month_bounds("2026-10")
    observe(db_session, offset=4 * 24 * 60)
    with pytest.raises(q.AccountQualificationError, match="not_finished"):
        q.freeze_month(db_session, "2026-10", now=cutoff - timedelta(days=4))
    with pytest.raises(q.AccountQualificationError, match="missing"):
        q.freeze_month(db_session, "2026-10", now=cutoff)


def test_later_current_observations_never_change_frozen_month(db_session):
    frozen = seed_month_qualification(db_session)
    fingerprint = (frozen.version_id, frozen.content_sha256, frozen.observation_id)
    observe(db_session, records=[binding(status="已解绑")], month="2026-11")
    again = q.freeze_month(db_session, "2026-10", now=q.month_bounds("2026-11")[1])
    assert (again.version_id, again.content_sha256, again.observation_id) == fingerprint
    assert q.qualified_version(db_session, month="2026-10", order=order()).version_id == frozen.version_id


def test_duplicate_source_identity_is_incomplete_not_success(db_session):
    row = binding()
    identity = observe(db_session, [row, row])
    assert db_session.get(Observation, identity).error_code == "duplicate_or_conflicting_binding_identity"


def test_api_partial_or_duplicate_page_fails_before_raw_ingestion(monkeypatch):
    monkeypatch.setattr(backend, "fetch_backend_aweme_bind_list_page", lambda *args: {"Total": 2, "integration_info": [{"id": "same"}, {"id": "same"}]})
    with pytest.raises(backend.BrowserExportError, match="partial|duplicate"):
        backend.fetch_backend_aweme_bind_list_records(object(), "https://example.test/bind/list")


@pytest.mark.parametrize("source_complete,same_identity,expected", [(True, True, True), (False, True, False), (True, False, False)])
def test_workbook_requires_independent_complete_list_identity_proof(source_complete, same_identity, expected):
    rows = q.BindingRecords([binding()], source_type="backend_workbook", proof={"file_complete": True, "complete": False, "record_count": 1})
    source = q.BindingRecords([binding(account="owner-dual" if same_identity else "different")],
        source_type="backend_bind_list_api", proof={"complete": source_complete, "expected_total": 1, "page_count": 1})
    result = backend.corroborate_backend_workbook(rows, source)
    assert result.proof["complete"] is expected


def test_filtered_api_list_cannot_prove_complete_export(monkeypatch):
    item = {"account_id": "owner-dual", "account_type": 20, "status": 1,
            "integration_content": {"user_info": {"aweme_id": "dy-owner"}}}
    monkeypatch.setattr(backend, "fetch_backend_aweme_bind_list_page", lambda *args: {"Total": 1, "integration_info": [item]})
    records = backend.fetch_backend_aweme_bind_list_records(object(), "https://example.test/bind/list?account_type=20")
    assert not records.proof["complete"]


def test_new_fee_uses_redemption_month_version_and_preserves_sale_date_and_fee_date(db_session):
    _load_dual_fee_fixture(db_session)
    _add_scope_rule(db_session, "2026-10")
    verify = db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual")
    verify.verify_time = _dual_time(10, 5)
    db_session.flush()
    version = seed_month_qualification(db_session)
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="new-month")
    for direction in (1, 2):
        result = _fee_result(db_session, "coupon-dual", direction)
        assert result.original_business_month == "2026-10"
        assert result.rule_match_date == _dual_time(10, 5).date()
        assert result.account_qualification_version_id == version.version_id
        assert result.sale_store_id == "store-sale"
    assert month_close._qualification_digest(db_session, "2026-10")
    # November current metadata cannot invalidate October's established basis.
    db_session.get(DimAwemeAccount, "owner-dual").binding_status = "已解绑"
    observe(db_session, [binding(status="已解绑")], month="2026-11")
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="late-current-change", force_recalculate=True)
    assert [_fee_result(db_session, "coupon-dual", direction).account_qualification_version_id for direction in (1, 2)] == [version.version_id] * 2
    assert all(_fee_result(db_session, "coupon-dual", direction).sale_store_id == "store-sale" for direction in (1, 2))


def test_month_close_watermark_requires_all_fees_pinned_and_version_freezes_without_fees(db_session, monkeypatch):
    _load_dual_fee_fixture(db_session)
    _add_scope_rule(db_session, "2026-10")
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    db_session.flush()
    version = seed_month_qualification(db_session)
    monkeypatch.setattr(month_close, "published_days_revisions", lambda *args: ["complete-days"])
    monkeypatch.setattr(month_close, "_active_rebuild_exists", lambda *args: False)
    assert month_close.month_close_preflight(db_session, "2026-10")[0] == month_close.NO_CURRENT_RESULTS
    assert version.version_id  # qualification publication has no fee dependency
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="all-pinned")
    state, watermark = month_close.month_close_preflight(db_session, "2026-10")
    assert state == month_close.READY and watermark
    assert month_close.month_source_watermark(db_session, "2026-10") == watermark
    result = _fee_result(db_session, "coupon-dual", 1)
    result.account_qualification_version_id = None
    db_session.flush()
    assert month_close.month_close_preflight(db_session, "2026-10")[0] == month_close.QUALIFICATION_NOT_READY
    assert month_close.month_source_watermark(db_session, "2026-10") is None


def test_missing_new_month_qualification_blocks_but_september_history_is_unchanged(db_session):
    _load_dual_fee_fixture(db_session)
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="old-september")
    old = _fee_result(db_session, "coupon-dual", 1)
    before = (old.fee_result_id, old.original_business_month, old.fee_amount_cent)
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="missing-october")
    assert (old.fee_result_id, old.original_business_month, old.fee_amount_cent) == before
    assert _fee_result(db_session, "coupon-dual", 1).fee_result_id == old.fee_result_id
    assert month_close.month_close_preflight(db_session, "2026-10")[0] == month_close.QUALIFICATION_NOT_READY


def test_monthend_poi_is_not_used_to_invent_historical_sale_store(db_session):
    _load_dual_fee_fixture(db_session)
    db_session.delete(db_session.get(DimAwemeAccount, "owner-dual"))
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    seed_month_qualification(db_session, records=[binding(poi="poi-verify")])
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="no-sale-history")
    assert _fee_result(db_session, "coupon-dual", 1) is None


@pytest.mark.parametrize("alias_type,should_resolve", [("个人号", True), ("unknown", False), ("子机构门店号", False)])
def test_exact_historical_uid_and_qualified_relation_survive_personal_nickname_alias(db_session, alias_type, should_resolve):
    source_order, _ = _load_openapi_sale_binding_fixture(db_session)
    upsert_store(db_session, "personal-store", "Personal store")
    upsert_aweme_binding(db_session, "personal-alias", account_id="personal-store",
        douyin_id="personal", douyin_nickname=source_order.owner_account_name,
        binding_status="认证成功", raw_payload={"账号类型": alias_type})
    _add_scope_rule(db_session, "2026-10")
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    seed_month_qualification(db_session, records=[binding(account="craftsman-exact")])
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="exact-uid-personal-alias")
    result = _fee_result(db_session, "coupon-dual", 1)
    if should_resolve:
        assert result.sale_store_id == "store-sale"
    else:
        assert result is None
