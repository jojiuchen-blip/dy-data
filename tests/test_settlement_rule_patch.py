"""Additive settlement rule configuration never starts financial recomputation."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.models import AccountPermissionAuditLog, DimSkuProductRule, JobRun, SkuFeeRule, User
from scripts.settlement_rule_patch import PatchError, _private_path, patch_rules


@pytest.fixture()
def context(db_session):
    db_session.add(User(user_id="operator-id", username="real-admin", display_name="Operator", role="admin", store_scope_mode="all", status="active"))
    db_session.add(DimSkuProductRule(sku_id="sku", product_id="product", sku_name="Original", product_scope="existing-scope",
        product_type="old-type", is_service_product=False, is_active_product=False, owner_account_id="existing-owner",
        product_status_raw="platform-status", manual_modified_by="previous-actor"))
    db_session.commit()
    return {"source_digest": "a" * 64, "actor": "real-admin", "change_reason": "confirmed attachment mapping", "idempotency_key": "patch-test-1"}


def rows(**overrides):
    return [{"sku_id": "sku", "product_id": "product", "product_type": "new-type",
             "promotion_rate": "0.06", "management_rate": "0.03", "effective_date": "2026-08-01", **overrides}]


def preview(session, context, items=None):
    return patch_rules(session, items or rows(), **context)


def test_preview_is_readonly_then_apply_is_additive_and_replayable(db_session, context):
    first = preview(db_session, context)
    assert first["can_apply"] and not first["applied"]
    assert first["diff"][0]["rule_action"] == "CREATE"
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 0
    db_session.rollback()
    applied = patch_rules(db_session, rows(), **context, apply=True, fingerprint=first["fingerprint"])
    assert applied["applied"] and not applied["rebuild_queued"]
    rule = db_session.scalar(select(SkuFeeRule))
    assert rule.product_type_snapshot == "new-type" and rule.product_scope_snapshot == "existing-scope"
    assert rule.created_by == "real-admin" and rule.promotion_service_fee_rate == Decimal(".06")
    sku = db_session.scalar(select(DimSkuProductRule))
    assert (sku.product_scope, sku.is_service_product, sku.owner_account_id, sku.product_status_raw, sku.is_active_product) == ("existing-scope", False, "existing-owner", "platform-status", False)
    assert sku.manual_modified_by == "real-admin"
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0
    assert db_session.scalar(select(func.count()).select_from(AccountPermissionAuditLog)) == 1
    db_session.rollback()
    replay = patch_rules(db_session, rows(), **context, apply=True, fingerprint=first["fingerprint"])
    assert replay["replayed"]
    changed = {**context, "change_reason": "different payload"}
    with pytest.raises(PatchError, match="idempotency key reused"):
        patch_rules(db_session, rows(), **changed, apply=True, fingerprint=first["fingerprint"])


def test_identical_active_rule_is_noop_and_keeps_all_snapshots(db_session, context):
    stamp = datetime(2026, 7, 1, tzinfo=timezone.utc)
    db_session.add(SkuFeeRule(rule_version="legacy", idempotency_key_hash="legacy-key", request_payload_sha256="legacy-payload",
        sku_id="sku", sku_name_snapshot="Historical name", product_scope_snapshot="historical-scope", product_type_snapshot="historical-type",
        promotion_service_fee_rate=Decimal(".06"), management_service_fee_rate=Decimal(".03"), effective_date=date(2026, 8, 1),
        effective_at=stamp, rule_status=1, created_by="historic-actor", change_reason="historic-reason", published_at=stamp))
    db_session.commit()
    before = preview(db_session, context)
    assert before["diff"][0]["rule_action"] == "NOOP"
    patch_rules(db_session, rows(), **context, apply=True, fingerprint=before["fingerprint"])
    rule = db_session.scalar(select(SkuFeeRule))
    assert (rule.rule_version, rule.sku_name_snapshot, rule.product_scope_snapshot, rule.product_type_snapshot, rule.created_by) == ("legacy", "Historical name", "historical-scope", "historical-type", "historic-actor")
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 1
    db_session.rollback()
    repeated_context = {**context, "idempotency_key": "second-key"}
    second = preview(db_session, repeated_context)
    assert second["diff"][0]["rule_action"] == "NOOP"
    patch_rules(db_session, rows(), **repeated_context, apply=True, fingerprint=second["fingerprint"])
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 1


@pytest.mark.parametrize(("overrides", "code"), [({"sku_id": "unknown"}, "UNKNOWN_SKU"), ({"product_id": "wrong"}, "PRODUCT_ID_MISMATCH")])
def test_missing_or_mismatching_catalog_blocks_entire_batch(db_session, context, overrides, code):
    items = rows(**overrides)
    report = preview(db_session, context, items)
    assert not report["can_apply"] and report["errors"][0]["code"] == code
    with pytest.raises(PatchError, match="batch blocked"):
        patch_rules(db_session, items, **context, apply=True, fingerprint=report["fingerprint"])
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 0


def test_existing_rate_conflict_rejects_new_rules_and_classification_atomically(db_session, context):
    first = preview(db_session, context)
    patch_rules(db_session, rows(), **context, apply=True, fingerprint=first["fingerprint"])
    altered = rows(promotion_rate=".07") + rows(effective_date="2026-09-01")
    next_context = {**context, "idempotency_key": "conflict-key"}
    report = preview(db_session, next_context, altered)
    assert report["errors"][0]["code"] == "EXISTING_RULE_CONFLICT"
    with pytest.raises(PatchError):
        patch_rules(db_session, altered, **next_context, apply=True, fingerprint=report["fingerprint"])
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 1


@pytest.mark.parametrize("mutation", ["catalog", "manual_timestamp", "rule"])
def test_stale_preview_rejected_after_catalog_or_rule_change(db_session, context, mutation):
    first = preview(db_session, context)
    sku = db_session.scalar(select(DimSkuProductRule))
    if mutation == "catalog":
        sku.product_scope = "changed-concurrently"
    elif mutation == "manual_timestamp":
        sku.manual_modified_at = datetime.now(timezone.utc)
    else:
        db_session.add(SkuFeeRule(rule_version="concurrent", idempotency_key_hash="concurrent", request_payload_sha256="c",
            sku_id="sku", effective_date=date(2026, 7, 1), effective_at=datetime.now(timezone.utc),
            promotion_service_fee_rate=Decimal(".01"), management_service_fee_rate=Decimal(".01"), created_by="real-admin", change_reason="concurrent", published_at=datetime.now(timezone.utc)))
    db_session.commit()
    with pytest.raises(PatchError, match="stale"):
        patch_rules(db_session, rows(), **context, apply=True, fingerprint=first["fingerprint"])


def test_failure_rolls_back_catalog_rules_and_audit(db_session, context, monkeypatch):
    first = preview(db_session, context)
    original = db_session.flush
    def fail_flush(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("forced write failure")
    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(RuntimeError, match="forced"):
        patch_rules(db_session, rows(), **context, apply=True, fingerprint=first["fingerprint"])
    monkeypatch.setattr(db_session, "flush", original)
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 0
    assert db_session.scalar(select(func.count()).select_from(AccountPermissionAuditLog)) == 0
    assert db_session.scalar(select(DimSkuProductRule)).product_type == "old-type"


@pytest.mark.parametrize("status", ["running", "retry_wait"])
def test_writer_fence_refuses_busy_writer(db_session, context, status):
    db_session.add(JobRun(job_id="busy", job_name="settlement_rebuild", status=status))
    db_session.commit()
    with pytest.raises(PatchError, match="writer"):
        preview(db_session, context)


def test_actor_must_be_real_active_global_admin(db_session, context):
    with pytest.raises(PatchError, match="administrator"):
        preview(db_session, {**context, "actor": "invented"})


def test_cli_private_path_refuses_tracked_or_unignored_repo_paths():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root / "README.md", root / "unignored-raw.json"):
        with pytest.raises(PatchError, match="outside Git"):
            _private_path(path)
    assert _private_path(root / "tmp" / "synthetic.json").name == "synthetic.json"


def test_multiple_dates_for_same_sku_have_distinct_row_keys(db_session, context):
    items = rows() + rows(effective_date="2026-09-01")
    report = preview(db_session, context, items)
    patch_rules(db_session, items, **context, apply=True, fingerprint=report["fingerprint"])
    rules = list(db_session.scalars(select(SkuFeeRule).order_by(SkuFeeRule.effective_date)))
    assert len({rule.idempotency_key_hash for rule in rules}) == 2
    assert rules[1].previous_rule_version == rules[0].rule_version


def test_unknown_sku_blocks_other_valid_rows_without_partial_apply(db_session, context):
    items = rows() + rows(sku_id="unknown")
    report = preview(db_session, context, items)
    assert report["diff"][0]["rule_action"] == "CREATE"
    assert not report["can_apply"]
    with pytest.raises(PatchError, match="batch blocked"):
        patch_rules(db_session, items, **context, apply=True, fingerprint=report["fingerprint"])
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 0
    assert db_session.scalar(select(DimSkuProductRule)).product_type == "old-type"


@pytest.mark.parametrize("overrides", [{"promotion_rate": "0.0000001"}, {"management_rate": "NaN"}, {"effective_date": "2026-02-30"}, {"promotion_rate": "1.1"}])
def test_invalid_input_cannot_be_applied(db_session, context, overrides):
    with pytest.raises(PatchError):
        preview(db_session, context, rows(**overrides))


def test_apply_requires_explicit_matching_fingerprint(db_session, context):
    with pytest.raises(PatchError, match="missing or stale"):
        patch_rules(db_session, rows(), **context, apply=True)


@pytest.mark.parametrize("actor", ["ops:", "ops:has spaces", "ops:../../x", "ops:bad\\path"])
def test_ops_actor_format_rejects_unsafe_identity(db_session, context, actor):
    with pytest.raises(PatchError, match="ops actor"):
        preview(db_session, {**context, "actor": actor})


def test_ops_identity_is_recorded_as_automation_without_creating_a_user(db_session, context):
    context = {**context, "actor": "ops:codex:DYDATA-104"}
    report = preview(db_session, context)
    assert report["actor_role"] == "ops"
    assert report["diff"][0]["preserved_product_scope"] == "existing-scope"
    patch_rules(db_session, rows(), **context, apply=True, fingerprint=report["fingerprint"])
    audit = db_session.scalar(select(AccountPermissionAuditLog))
    assert audit.actor_username == "ops:codex:DYDATA-104"
    assert audit.actor_role == "ops" and audit.actor_user_id is None
    assert audit.after_json["source_digest"] == context["source_digest"]
    assert audit.after_json["change_reason"] == context["change_reason"]
    assert audit.after_json["diff"][0]["catalog_type_before"] == "old-type"
    assert audit.after_json["diff"][0]["catalog_type_after"] == "new-type"
    assert db_session.scalar(select(SkuFeeRule)).created_by == "ops:codex:DYDATA-104"
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


def test_existing_inactive_rule_is_conflict_even_with_identical_rates(db_session, context):
    first = preview(db_session, context)
    patch_rules(db_session, rows(), **context, apply=True, fingerprint=first["fingerprint"])
    db_session.scalar(select(SkuFeeRule)).rule_status = 2
    db_session.commit()
    context = {**context, "idempotency_key": "inactive-conflict"}
    report = preview(db_session, context)
    assert not report["can_apply"]
    assert report["errors"][0]["code"] == "EXISTING_RULE_CONFLICT"
    with pytest.raises(PatchError, match="batch blocked"):
        patch_rules(db_session, rows(), **context, apply=True, fingerprint=report["fingerprint"])
