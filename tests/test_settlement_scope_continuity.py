"""Owner/channel scope changes apply from their month, preserving frozen bills."""
from __future__ import annotations

from hashlib import sha256
import json

import pytest
from sqlalchemy import delete, func, select

from apps.api.dy_api.models import (
    DataQualityIssue, DimStore, JobRun, SettlementFeeResult, SettlementScopeRule, SettlementStatement,
    SettlementStatementConfirmation, SettlementStatementEntry, SettlementStatementLine,
    UserStoreScope,
)
from apps.worker import settlement
from test_api_fee_admin import client, _login, _login_rule_operator, _seed_sku
from test_data_settlement import _fee_result, _load_dual_fee_fixture


SCOPE_URL = "/api/v1/admin/settlement-scope-rules"


def _rule(session, month, *, owner="scope-owner", channel="short_video", active=True):
    version = f"{owner}-{channel}-{month}"
    row = SettlementScopeRule(scope_rule_version=version,
        idempotency_key_hash=sha256(version.encode()).hexdigest(),
        request_payload_sha256="a" * 64, effective_month=month,
        owner_account_id=owner, sale_channel_normalized=channel, is_active=active,
        created_by="scope-test", change_reason="synthetic timeline")
    session.add(row)
    session.flush()
    return row


def _match(session, month, owner="scope-owner", channel="short_video"):
    return settlement._match_scope_rule(session, business_month=month,
        owner_account_id=owner, channel=channel)


def _payload(month="2026-08", **changes):
    return {"effectiveMonth": month, "ownerAccountId": "owner-stable-1",
            "allowedSaleChannels": ["SHORT_VIDEO"], "changeReason": "scope timeline", **changes}


def _publish(client, payload, key):
    return client.post(SCOPE_URL, json=payload, headers={"Idempotency-Key": key})


@pytest.mark.parametrize("month", ["2026-08", "2026-09", "2026-10", "2026-12", "2027-01"])
def test_rule_continues_through_unconfigured_months_and_year_boundary(db_session, month):
    august = _rule(db_session, "2026-08")
    assert _match(db_session, month) is august
    assert _match(db_session, "2026-07") is None


def test_latest_change_isolated_by_owner_channel_and_not_applied_early(db_session):
    august = _rule(db_session, "2026-08")
    october = _rule(db_session, "2026-10")
    live = _rule(db_session, "2026-09", channel="live")
    other = _rule(db_session, "2026-09", owner="other-owner")
    assert _match(db_session, "2026-08") is august
    assert _match(db_session, "2026-09") is august
    assert _match(db_session, "2026-10") is october
    assert _match(db_session, "2027-01") is october
    assert _match(db_session, "2026-08", channel="live") is None
    assert _match(db_session, "2026-10", channel="live") is live
    assert _match(db_session, "2026-10", owner="other-owner") is other
    assert _match(db_session, "2026-10", owner="unknown-owner") is None


def test_inactive_latest_does_not_fall_back_and_can_resume_later(db_session):
    from apps.api.dy_api.settlement_scope import resolve_settlement_scope_rule

    august = _rule(db_session, "2026-08")
    stopped = _rule(db_session, "2026-09", active=False)
    resumed = _rule(db_session, "2026-12")
    assert _match(db_session, "2026-08") is august
    for month in ("2026-09", "2026-10", "2026-11"):
        assert _match(db_session, month) is None
        assert resolve_settlement_scope_rule(db_session, business_month=month,
            owner_account_id="scope-owner", channel="short_video") is stopped
    assert _match(db_session, "2026-12") is resumed
    assert _match(db_session, "2027-01") is resumed


@pytest.mark.parametrize("retry_active", [None, True])
def test_existing_legacy_request_hash_and_retry_stay_compatible(client, db_session, retry_active):
    _seed_sku(db_session, "scope-sku", "scope sku")
    payload = _payload()
    key = "legacy-scope-key-0001"
    old_hash = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode()).hexdigest()
    # A row written by the former API, not merely two calls to the new encoder.
    row = _rule(db_session, "2026-08", owner="owner-stable-1")
    row.idempotency_key_hash = sha256(key.encode()).hexdigest()
    row.request_payload_sha256 = old_hash
    row.change_reason = payload["changeReason"]
    db_session.commit()
    _login(client)
    retry = _publish(client, payload if retry_active is None else {**payload, "isActive": retry_active}, key)
    assert retry.status_code == 200, retry.text
    assert retry.json()["data"]["scopeRuleVersions"] == [row.scope_rule_version]
    assert retry.json()["data"]["isActive"] is True
    assert db_session.scalar(select(func.count()).select_from(SettlementScopeRule)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 1
    assert row.request_payload_sha256 == old_hash
    changed = _publish(client, {**payload, "isActive": False}, key)
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_scope_api_stop_retry_slot_conflict_and_channel_independence(client, db_session):
    _seed_sku(db_session, "scope-sku", "scope sku")
    db_session.commit()
    _login(client)
    august = _publish(client, _payload(allowedSaleChannels=["LIVE", "SHORT_VIDEO"]), "scope-august-key-0001")
    assert august.status_code == 200
    assert august.json()["data"]["isActive"] is True
    stopped_payload = _payload("2026-09", isActive=False)
    stopped = _publish(client, stopped_payload, "scope-stop-key-00001")
    retried = _publish(client, stopped_payload, "scope-stop-key-00001")
    assert stopped.status_code == retried.status_code == 200, stopped.text
    assert stopped.json()["data"] == retried.json()["data"]
    assert stopped.json()["data"]["isActive"] is False
    assert _match(db_session, "2026-10", "owner-stable-1") is None
    assert _match(db_session, "2026-10", "owner-stable-1", "live").effective_month == "2026-08"
    assert _publish(client, _payload("2026-09"), "scope-stop-key-00001").status_code == 409
    for payload in (stopped_payload, _payload("2026-09")):
        conflict = _publish(client, payload, "different-scope-key-001")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "SETTLEMENT_SCOPE_SLOT_CONFLICT"
    resumed = _publish(client, _payload("2026-10"), "scope-resume-key-001")
    assert resumed.status_code == 200
    assert _match(db_session, "2026-10", "owner-stable-1").effective_month == "2026-10"
    # List filtering describes records' effective month, never implied carry-forward.
    listing = client.get(SCOPE_URL, params={"effectiveMonth": "2026-09"})
    assert listing.status_code == 200
    assert [(row["effectiveMonth"], row["saleChannel"], row["isActive"])
            for row in listing.json()["data"]["list"]] == [("2026-09", "SHORT_VIDEO", False)]
    assert db_session.scalar(select(func.count()).select_from(SettlementScopeRule)) == 4
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 3


@pytest.mark.parametrize("active", [None, "false", 0, 1, "invalid"])
def test_scope_api_rejects_non_boolean_active(client, db_session, active):
    _login(client)
    response = _publish(client, _payload(isActive=active), "invalid-scope-key-0001")
    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(SettlementScopeRule)) == 0


@pytest.mark.parametrize("role", ["anonymous", "scoped_admin", "store"])
def test_scope_api_requires_global_admin_scope(client, db_session, role):
    if role != "anonymous":
        operator = _login_rule_operator(client, db_session, "admin" if role == "scoped_admin" else role)
        if role == "scoped_admin":
            operator.store_scope_mode = "specified"
            db_session.add(DimStore(store_id="scope-only-store", store_name="Scope test store", is_active=True))
            db_session.flush()
            db_session.add(UserStoreScope(user_id=operator.user_id, store_id="scope-only-store"))
            db_session.commit()
            client.cookies.clear()
            assert client.post("/api/v1/auth/login", json={
                "username": operator.username, "password": "isolated-password",
            }).status_code == 200
    response = _publish(client, _payload(isActive=False), "role-scope-key-00001")
    assert response.status_code == (401 if role == "anonymous" else 403)
    assert db_session.scalar(select(func.count()).select_from(SettlementScopeRule)) == 0
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_global_admin_can_publish_scope_stop_idempotently(client, db_session):
    _seed_sku(db_session, "scope-sku", "scope sku")
    operator = _login_rule_operator(client, db_session, "admin")
    payload = _payload(isActive=False)
    first = _publish(client, payload, "global-admin-stop-0001")
    retry = _publish(client, payload, "global-admin-stop-0001")
    assert first.status_code == retry.status_code == 200, first.text
    assert first.json()["data"] == retry.json()["data"]
    rules = list(db_session.scalars(select(SettlementScopeRule)))
    assert len(rules) == 1
    assert rules[0].is_active is False
    assert rules[0].created_by == operator.username
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 1


def test_scope_stop_still_requires_real_owner_source(client, db_session):
    _login(client)
    response = _publish(client, _payload(isActive=False), "missing-owner-key-001")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "OWNER_ACCOUNT_NOT_FOUND"
    assert db_session.scalar(select(func.count()).select_from(SettlementScopeRule)) == 0


@pytest.mark.parametrize("state", ["unconfigured", "disabled"])
def test_scope_diagnostics_distinguish_missing_configuration_and_explicit_stop(db_session, state):
    _load_dual_fee_fixture(db_session)
    db_session.execute(delete(SettlementScopeRule))
    stopped = _rule(db_session, "2026-08", owner="owner-dual", active=False) if state == "disabled" else None
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id=f"scope-{state}")
    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "dual_fee_missing_scope_rule")))
    assert len(issues) == 2
    for issue in issues:
        context = issue.raw_context_json
        assert context["scope_state"] == state
        assert context["owner_account_id"] == "owner-dual"
        assert context["sale_channel"] == "short_video"
        assert context["scope_rule_version"] == (stopped.scope_rule_version if stopped else None)
        assert ("停用" if stopped else "未配置") in issue.message
    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None


def test_explicit_stop_retires_unprotected_current_fees_without_deleting_history(db_session):
    _load_dual_fee_fixture(db_session)
    db_session.execute(delete(SettlementScopeRule).where(SettlementScopeRule.effective_month == "2026-09"))
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="scope-before-stop")
    originals = tuple(_fee_result(db_session, "coupon-dual", direction) for direction in (1, 2))
    assert all(original is not None for original in originals)
    amounts = tuple(original.fee_amount_cent for original in originals)
    _rule(db_session, "2026-09", owner="owner-dual", active=False)
    outcome = settlement.rebuild_dual_fee_results(db_session,
        calculation_run_id="scope-after-stop", force_recalculate=True)
    assert outcome.blocked_count == 2
    assert _fee_result(db_session, "coupon-dual", 1) is None
    assert _fee_result(db_session, "coupon-dual", 2) is None
    assert tuple(original.fee_amount_cent for original in originals) == amounts
    assert all(original.result_status == 2 for original in originals)
    assert db_session.scalar(select(func.count()).select_from(SettlementFeeResult)) == 2


@pytest.mark.parametrize("is_current", [True, False])
def test_rule_stop_preserves_confirmed_bill_and_fee_pointer_during_real_recalculation(db_session, is_current):
    _load_dual_fee_fixture(db_session)
    # September's verified business event must inherit the August scope.
    db_session.execute(delete(SettlementScopeRule).where(SettlementScopeRule.effective_month == "2026-09"))
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="scope-inherit")
    original = _fee_result(db_session, "coupon-dual", 1)
    assert original is not None
    assert original.scope_rule_version == "scope-2026-08-short_video"
    bill = SettlementStatement(statement_id="scope-confirmed-bill", store_id="store-sale",
        statement_month="2026-09", statement_status=2, is_current=is_current,
        promotion_original_fee_cent=original.fee_amount_cent,
        promotion_net_fee_cent=original.fee_amount_cent, store_name_snapshot="Frozen store")
    db_session.add(bill)
    db_session.flush()
    confirmation = SettlementStatementConfirmation(confirmation_id="scope-confirmation",
        statement_id=bill.statement_id, fee_direction=1, confirmed_by="synthetic-store",
        confirmed_amount_cent=original.fee_amount_cent)
    db_session.add(confirmation)
    line = SettlementStatementLine(statement_line_id="scope-line", statement_id=bill.statement_id,
        fee_direction=1, product_scope="scope", product_type="type")
    db_session.add(line)
    db_session.flush()
    entry = SettlementStatementEntry(statement_entry_id="scope-entry", statement_id=bill.statement_id,
        statement_line_id=line.statement_line_id, source_type=1, source_record_id=original.fee_result_id,
        original_fee_result_id=original.fee_result_id, coupon_id="coupon-dual", order_id=original.order_id,
        fee_direction=1, original_business_month="2026-09", statement_posting_month="2026-09",
        fee_amount_cent=original.fee_amount_cent, rule_version=original.rule_version)
    db_session.add(entry)
    db_session.commit()
    # Both backdated stop and future resume are append-only configuration changes.
    _rule(db_session, "2026-09", owner="owner-dual", active=False)
    _rule(db_session, "2026-10", owner="owner-dual", active=True)
    frozen_rows = (bill, confirmation, line, entry, original)
    before = tuple(tuple(getattr(row, field.key) for field in row.__mapper__.column_attrs)
                   for row in frozen_rows)
    for attempt in range(2):
        settlement.rebuild_dual_fee_results(db_session,
            calculation_run_id=f"scope-protected-{attempt}", force_recalculate=True)
        db_session.flush()
    db_session.expire_all()
    after = tuple(tuple(getattr(row, field.key) for field in row.__mapper__.column_attrs)
                  for row in frozen_rows)
    assert after == before
    assert _fee_result(db_session, "coupon-dual", 1).fee_result_id == original.fee_result_id
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 1
    assert db_session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 1
    assert db_session.scalar(select(func.count()).select_from(SettlementStatementEntry)) == 1
    assert db_session.scalar(select(func.count()).select_from(SettlementFeeResult).where(
        SettlementFeeResult.fee_direction == 1)) == 1
