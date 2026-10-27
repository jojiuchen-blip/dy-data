"""No current-state or nickname inference may become historical qualification."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from apps.api.dy_api.models import (
    AccountQualificationObservation as Observation, AccountQualificationSnapshot as Snapshot,
    AccountQualificationVersion as Version, DimAwemeAccount, RawDouyinOrder,
    RawDouyinVerifyRecord, SettlementFeeResult, SettlementFeeResultCurrent, DataQualityIssue,
)
from apps.worker import account_qualification as q, month_close, settlement
from apps.worker.browser_exports import backend_aweme as backend
from apps.worker.browser_exports.backend_aweme_parser import parse_backend_aweme_workbook
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


@pytest.mark.parametrize("kind,status", [("20", "认证成功"), ("", "认证成功"), ("子机构门店号", "1")])
def test_unknown_source_contract_never_becomes_successful_snapshot(db_session, kind, status):
    identity = observe(db_session, [binding(kind=kind, status=status)])
    row = db_session.get(Observation, identity)
    assert row.state == "failed" and row.content_sha256 is None and not row.complete
    assert db_session.scalar(select(func.count()).select_from(Snapshot)) == 0
    with pytest.raises(q.AccountQualificationError):
        q.freeze_month(db_session, "2026-10", now=q.month_bounds("2026-10")[1])


@pytest.mark.parametrize("kind,status,reason", [
    ("子机构门店号", "绑定已拒绝", "certification_not_successful"),
    ("子机构门店号", "未知状态", "certification_not_successful"),
    ("子机构号", "认证成功", "account_type_not_eligible"),
    ("子机构经营号", "认证成功", "account_type_not_eligible"),
    ("个人号", "认证成功", "account_type_not_eligible"),
    ("总部垂直号", "认证成功", "account_type_not_eligible"),
    ("子机构门店号", "active", "certification_not_successful"),
])
def test_explicit_negative_text_rows_preserve_complete_positive_set(db_session, kind, status, reason):
    rows = [binding(), binding(account="negative-account", kind=kind, status=status, douyin="negative-handle")]
    version = seed_month_qualification(db_session, records=rows)
    source = db_session.get(Snapshot, version.content_sha256)
    negative = next(row for row in source.records_json if row["account_id"] == "negative-account")
    assert negative["qualification_status"] == "ineligible" and reason in negative["reason_codes"]
    assert q.qualified_version(db_session, month="2026-10", order=order()).version_id == version.version_id
    with pytest.raises(q.AccountQualificationError, match="not_qualified"):
        q.qualified_version(db_session, month="2026-10", order=order("negative-account"))


def test_anonymous_excluded_personal_records_do_not_destroy_qualified_set(db_session):
    anonymous = binding(account=None, kind="个人号", status="未知状态", poi=None, douyin=None)
    version = seed_month_qualification(db_session, records=[binding(), anonymous, anonymous])
    source = db_session.get(Snapshot, version.content_sha256)
    assert source.record_count == 3
    negatives = [row for row in source.records_json if row["account_id"] is None]
    assert len(negatives) == 2
    assert all("nonqualifying_record_without_account_id" in row["reason_codes"] for row in negatives)
    assert q.qualified_version(db_session, month="2026-10", order=order())


def test_workbook_parser_preserves_identityless_negative_source_row(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["账号类型", "抖音号绑定状态", "所属账户id", "抖音id"])
    sheet.append(["子机构门店号", "认证成功", "backend-child", "child-handle"])
    sheet.append(["个人号", "未知状态", None, None])
    path = tmp_path / "negative-anonymous.xlsx"
    workbook.save(path)
    records = parse_backend_aweme_workbook(path)
    assert len(records) == 2 and records.proof["file_complete"]
    normalized = q.canonical_records(records)
    assert sum(row["qualification_status"] == "eligible" for row in normalized) == 1
    assert sum("nonqualifying_record_without_account_id" in row["reason_codes"] for row in normalized) == 1


def test_freeze_uses_observed_policy_and_old_v1_evidence_is_still_readable(db_session):
    _, cutoff = q.month_bounds("2026-10")
    old_row = {"account_id": "owner-dual", "douyin_id": "dy-owner", "douyin_uid": None,
               "poi_id": "poi-sale", "account_type": "子机构门店号", "binding_status": "认证成功",
               "raw_payload": binding()["raw_payload"]}
    policy = "settlement-monthend-cn-v1"
    content_hash = q.digest({"policy": policy, "records": [old_row]})
    db_session.add(Snapshot(content_sha256=content_hash, records_json=[old_row], record_count=1, policy_version=policy))
    observation_id = q.start_observation(db_session, source_run_id="prior-v1-source", started_at=cutoff-timedelta(minutes=60))
    observation = db_session.get(Observation, observation_id)
    observation.state, observation.complete = "success", True
    observation.content_sha256, observation.ended_at = content_hash, cutoff-timedelta(minutes=50)
    db_session.flush()
    frozen = q.freeze_month(db_session, "2026-10", now=cutoff)
    assert frozen.policy_version == policy
    assert q.qualified_version(db_session, month="2026-10", order=order()).version_id == frozen.version_id


@pytest.mark.parametrize("case", ["missing_positive_id", "conflicting_negative_id", "missing_status_column"])
def test_real_identity_or_field_corruption_still_fails_batch(db_session, case):
    row = binding()
    if case == "missing_positive_id":
        row = binding(account=None)
    elif case == "conflicting_negative_id":
        row = binding(kind="个人号")
        row["account_id"] = "conflicting"
    else:
        del row["raw_payload"]["抖音号绑定状态"]
    identity = observe(db_session, [binding(account="known-good"), row])
    assert db_session.get(Observation, identity).state == "failed"
    assert db_session.scalar(select(func.count()).select_from(Snapshot)) == 0


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
    with pytest.raises(q.AccountQualificationError, match="qualification_identity_unresolved"):
        q.qualified_version(db_session, month="2026-10", order=order("different", "uid-looks-same"))


def test_encrypted_transfer_uid_is_not_a_backend_account_even_when_text_matches(db_session):
    seed_month_qualification(db_session)
    opaque = order()
    opaque.raw_payload = {"sale_info": {"transfer_uid": "owner-dual"}}
    with pytest.raises(q.AccountQualificationError, match="qualification_identity_unresolved"):
        q.qualified_version(db_session, month="2026-10", order=opaque)
    # Collector priority means an explicit owner_account_id is a different
    # origin than a nested transfer_uid value that it never selected.
    opaque.raw_payload["owner_account_id"] = "owner-dual"
    assert q.qualified_version(db_session, month="2026-10", order=opaque)


@pytest.mark.parametrize("source", ["sale_info", "order_sale_info"])
def test_official_selected_transfer_douyin_uid_is_short_handle_not_uid(db_session, source):
    version = seed_month_qualification(db_session)
    subject = order("encrypted-transfer-value", "dy-owner")
    subject.raw_payload = {source: {"transfer_uid": subject.owner_account_id, "transfer_douyin_uid": "dy-owner"}}
    assert q.qualified_version(db_session, month="2026-10", order=subject).version_id == version.version_id


def test_source_short_priority_ignores_unselected_lower_priority_field(db_session):
    version = seed_month_qualification(db_session)
    subject = order("encrypted-transfer", "dy-owner")
    subject.raw_payload = {
        "sale_info": {"transfer_uid": "encrypted-transfer", "transfer_douyin_uid": "dy-owner"},
        "order_sale_info": {"transfer_uid": "lower-priority-value", "transfer_douyin_uid": "unselected-short"},
    }
    assert q.qualified_version(db_session, month="2026-10", order=subject).version_id == version.version_id


def test_generic_uid_origin_takes_priority_and_is_not_silently_a_short_handle(db_session):
    seed_month_qualification(db_session, records=[binding(douyin="generic-uid")])
    subject = order("encrypted-transfer", "generic-uid")
    subject.raw_payload = {"owner_douyin_uid": "generic-uid", "sale_info": {
        "transfer_uid": "encrypted-transfer", "transfer_douyin_uid": "generic-uid"}}
    with pytest.raises(q.AccountQualificationError, match="qualification_identity_unresolved"):
        q.qualified_version(db_session, month="2026-10", order=subject)


def test_source_short_value_must_agree_with_normalized_selected_value(db_session):
    seed_month_qualification(db_session)
    subject = order("encrypted-transfer", "dy-owner")
    subject.raw_payload = {"sale_info": {"transfer_uid": "encrypted-transfer", "transfer_douyin_uid": "different-short"}}
    with pytest.raises(q.AccountQualificationError, match="qualification_identity_source_conflict"):
        q.qualified_version(db_session, month="2026-10", order=subject)


@pytest.mark.parametrize("other_kind,other_status,expected", [
    ("个人号", "认证成功", None), ("子机构门店号", "认证成功", "qualification_identity_ambiguous"),
])
def test_source_short_excludes_personal_alias_but_keeps_real_multiple_account_conflict(db_session, other_kind, other_status, expected):
    seed_month_qualification(db_session, records=[binding(), binding(account="other-account", douyin="dy-owner", kind=other_kind, status=other_status)])
    subject = order("encrypted-transfer", "dy-owner")
    subject.raw_payload = {"sale_info": {"transfer_uid": "encrypted-transfer", "transfer_douyin_uid": "dy-owner"}}
    if expected:
        with pytest.raises(q.AccountQualificationError, match=expected):
            q.qualified_version(db_session, month="2026-10", order=subject)
    else:
        assert q.qualified_version(db_session, month="2026-10", order=subject)


def test_explicit_backend_account_and_selected_short_cannot_point_to_different_accounts(db_session):
    seed_month_qualification(db_session, records=[binding(), binding(account="other-account", douyin="other-short")])
    subject = order("owner-dual", "other-short")
    subject.raw_payload = {"owner_account_id": "owner-dual", "sale_info": {"transfer_douyin_uid": "other-short"}}
    with pytest.raises(q.AccountQualificationError, match="qualification_identity_ambiguous"):
        q.qualified_version(db_session, month="2026-10", order=subject)


def test_unresolved_transfer_identity_has_separate_settlement_failure_reason(db_session):
    _load_dual_fee_fixture(db_session)
    source_order = db_session.scalar(select(RawDouyinOrder))
    source_order.raw_payload = {**source_order.raw_payload, "sale_info": {"transfer_uid": source_order.owner_account_id}}
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    seed_month_qualification(db_session)
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="opaque-identity-unresolved")
    failures = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "dual_fee_monthend_account_qualification")))
    assert len(failures) == 2
    assert all(issue.raw_context_json["reason_code"] == "qualification_identity_unresolved" for issue in failures)
    assert _fee_result(db_session, "coupon-dual", 1) is None


def test_source_content_deduplicates_while_every_attempt_is_preserved(db_session):
    observe(db_session, offset=90)
    observe(db_session, offset=60)
    assert db_session.scalar(select(func.count()).select_from(Snapshot)) == 1
    assert db_session.scalar(select(func.count()).select_from(Observation)) == 2


@pytest.mark.parametrize("moment,expected", [
    ("2026-10-27T23:00:00+08:00", False), ("2026-10-31T21:59:59+08:00", False),
    ("2026-10-31T22:00:00+08:00", True), ("2026-10-31T23:59:59+08:00", True),
    ("2026-11-01T00:00:00+08:00", False), ("2026-12-31T22:00:00+08:00", True),
])
def test_automatic_permanent_capture_is_only_actual_monthend_window(moment, expected):
    assert q.in_automatic_capture_window(q.datetime.fromisoformat(moment)) is expected


def test_automatic_evidence_budget_is_bounded_and_exhaustion_blocks_month(db_session):
    _, cutoff = q.month_bounds("2026-10")
    for index in range(q.MAX_AUTOMATIC_MONTH_ATTEMPTS):
        at = cutoff-timedelta(minutes=100-index)
        admission = q.begin_automatic_observation(db_session, source_run_id=f"auto-{index}", started_at=at)
        assert admission.observation_id and admission.blocked_reason is None
        row = binding()
        row["raw_payload"]["version"] = index
        q.complete_observation(db_session, admission.observation_id,
            q.BindingRecords([row], proof={"complete": True, "record_count": 1}), ended_at=at+timedelta(seconds=1))
    for index in range(5):
        admission = q.begin_automatic_observation(db_session, source_run_id=f"budget-{index}",
            started_at=cutoff-timedelta(minutes=30-index))
        assert admission.observation_id is None and admission.blocked_reason == "monthend_capture_budget_exhausted"
    assert db_session.scalar(select(func.count()).select_from(Observation)) == q.MAX_AUTOMATIC_MONTH_ATTEMPTS+1
    assert db_session.scalar(select(func.count()).select_from(Snapshot)) == q.MAX_AUTOMATIC_MONTH_ATTEMPTS
    with pytest.raises(q.AccountQualificationError):
        q.freeze_month(db_session, "2026-10", now=cutoff)


def test_oversize_snapshot_fails_without_truncating_or_persisting_content(db_session, monkeypatch):
    monkeypatch.setattr(q, "MAX_SNAPSHOT_BYTES", 10)
    identity = observe(db_session)
    observation = db_session.get(Observation, identity)
    assert observation.state == "failed" and observation.error_code == "qualification_snapshot_size_limit"
    assert observation.content_sha256 is None
    assert db_session.scalar(select(func.count()).select_from(Snapshot)) == 0


def test_normal_collection_outside_window_keeps_source_proof_without_permanent_qualification(db_session, monkeypatch, caplog):
    from unittest.mock import Mock
    from types import SimpleNamespace
    from datetime import datetime
    at = datetime.fromisoformat("2026-10-27T13:00:00+08:00")
    monkeypatch.setattr(backend, "datetime", SimpleNamespace(now=lambda _: at))
    rows = q.BindingRecords([binding()], proof={"complete": True, "record_count": 1, "workbook_sha256": "synthetic-hash"})
    monkeypatch.setattr(backend, "export_backend_aweme_records_via_browser", lambda **kwargs: rows)
    with caplog.at_level("INFO"):
        result = backend.run_backend_aweme_export(db_session, source_run_id="normal-day")
    assert result.fetched == 1
    assert "synthetic-hash" in caplog.text
    assert db_session.scalar(select(func.count()).select_from(Observation)) == 0
    assert db_session.scalar(select(func.count()).select_from(Snapshot)) == 0


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


def test_workbook_requires_exact_export_task_proof(tmp_path):
    from apps.worker.browser_exports.backend_aweme_proof import apply_export_task_proof
    rows = q.BindingRecords([binding()], source_type="backend_workbook", proof={"file_complete": True, "complete": False, "record_count": 1})
    result = apply_export_task_proof(rows, tmp_path / "unproven.xlsx")
    assert not result.proof["complete"]
    assert result.proof["corroboration_error"] == "exact_export_task_proof_missing"


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
