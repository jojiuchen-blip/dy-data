"""Synthetic evidence only: no private platform payloads or production writes."""
import copy
import hashlib
import json

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.models import AccountPermissionAuditLog, DimSkuProductRule, JobRun, SkuProductSyncHistory
from scripts import supplement_sku_catalog as module
from scripts.settlement_rule_patch import PatchError


@pytest.fixture()
def evidence():
    records, requests = [], []
    for index, (product_id, sku_ids) in enumerate(module.GROUPS.items()):
        records.append({"product": {"product_id": product_id, "owner_account_id": "synthetic-owner",
            "creator_account_id": "synthetic-creator", "account_name": "Synthetic merchant",
            "product_name": "Synthetic product", "update_time": 1792000000,
            "untouched_extra": {"original": [1, 2]}}, "online_status": 1, "sku": {}, "skus": []})
        requests.append({"product_id": product_id, "requested_sku_ids": sorted(sku_ids),
            "proven_product_owner_account_id": "synthetic-owner", "result": "RESPONSE_RECEIVED",
            "response": {"data": {"error_code": 0, "skus": [{"sku_id": sku_id, "sku_name": "Synthetic variant",
                "status": 1, "origin_amount": 20000, "actual_amount": 10000,
                "create_time": 1791000000, "update_time": 1792000001} for sku_id in sorted(sku_ids)]},
                "extra": {"error_code": 0, "now": 1792746255 + index}}})
    product = json.dumps({"source": {"data": {"error_code": 0, "product_onlines": records}}}).encode()
    sku = {"source_sha256": hashlib.sha256(product).hexdigest(), "endpoint": module.SKU_URL,
           "stopped_after_error": False, "requests": requests}
    return product, sku


def call(session, evidence, **kwargs):
    product, sku = evidence
    return module.supplement_catalog(session, product, json.dumps(sku).encode(),
        actor="ops:codex:synthetic-test", change_reason="reviewed synthetic evidence", idempotency_key="catalog-test", **kwargs)


def test_preview_create_history_audit_replay_and_no_job(db_session, evidence):
    preview = call(db_session, evidence)
    assert not preview["applied"] and all(row["action"] == "CREATE" for row in preview["diff"])
    assert db_session.scalar(select(func.count()).select_from(DimSkuProductRule)) == 0
    db_session.rollback()
    applied = call(db_session, evidence, apply=True, fingerprint=preview["fingerprint"], evidence_digest=preview["evidence_digest"])
    assert len(applied["created_sku_ids"]) == 6 and not applied["rebuild_queued"]
    catalog = list(db_session.scalars(select(DimSkuProductRule)))
    history = list(db_session.scalars(select(SkuProductSyncHistory)))
    assert len(catalog) == len(history) == 6
    assert all(row.owner_account_id == "synthetic-owner" and row.product_status_normalized == "ACTIVE" for row in catalog)
    assert all(row.product_scope == row.product_type == "" and row.is_service_product is False for row in catalog)
    assert {int(row.last_synced_at.replace(tzinfo=module.timezone.utc).timestamp()) for row in catalog} == {1792746255, 1792746256, 1792746257}
    audit = db_session.scalar(select(AccountPermissionAuditLog))
    assert audit.actor_username == "ops:codex:synthetic-test" and audit.actor_role == "ops" and audit.actor_user_id is None
    assert audit.after_json["original_product_document"] == json.loads(evidence[0])
    assert audit.after_json["original_sku_document"] == evidence[1]
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0
    db_session.rollback()
    replay = call(db_session, evidence, apply=True, fingerprint=preview["fingerprint"], evidence_digest=preview["evidence_digest"])
    assert replay["replayed"] and replay["created_sku_ids"] == applied["created_sku_ids"]
    changed = copy.deepcopy(evidence[1]); changed["requests"][0]["response"]["data"]["skus"][0]["sku_name"] = "Changed"
    with pytest.raises(PatchError, match="idempotency key reused"):
        call(db_session, (evidence[0], changed))


@pytest.mark.parametrize("case", ["missing", "extra", "duplicate", "wrong-request", "wrong-owner", "wrong-product", "nonzero-code", "sku-status", "float-cents", "source-digest", "observation"])
def test_incomplete_or_conflicting_evidence_fails_before_writes(db_session, evidence, case):
    product, sku = evidence
    sku = copy.deepcopy(sku)
    entry = sku["requests"][0]
    variants = entry["response"]["data"]["skus"]
    if case == "missing": variants.pop()
    elif case == "extra": variants.append({**variants[0], "sku_id": "unapproved"})
    elif case == "duplicate": variants[1] = copy.deepcopy(variants[0])
    elif case == "wrong-request": entry["product_id"] = "unapproved"
    elif case == "wrong-owner": entry["proven_product_owner_account_id"] = "sales-account-is-not-owner"
    elif case == "wrong-product": variants[0]["product_id"] = "different-product"
    elif case == "nonzero-code": entry["response"]["extra"]["error_code"] = 2190004
    elif case == "sku-status": variants[0]["status"] = -1
    elif case == "float-cents": variants[0]["actual_amount"] = 1.5
    elif case == "source-digest": sku["source_sha256"] = "0" * 64
    elif case == "observation": entry["response"]["extra"]["now"] = 1792746255000
    with pytest.raises(PatchError):
        call(db_session, (product, sku))
    assert db_session.scalar(select(func.count()).select_from(DimSkuProductRule)) == 0


def test_current_identity_conflict_blocks_entire_supplement(db_session, evidence):
    sku_id = next(iter(next(iter(module.GROUPS.values()))))
    db_session.add(DimSkuProductRule(sku_id=sku_id, product_id="different", owner_account_id="synthetic-owner"))
    db_session.commit()
    preview = call(db_session, evidence)
    assert not preview["can_apply"] and preview["conflicting_existing_skus"] == [sku_id]
    with pytest.raises(PatchError, match="identity conflicts"):
        call(db_session, evidence, apply=True, fingerprint=preview["fingerprint"], evidence_digest=preview["evidence_digest"])
    assert db_session.scalar(select(func.count()).select_from(DimSkuProductRule)) == 1
    assert db_session.scalar(select(func.count()).select_from(SkuProductSyncHistory)) == 0


def test_existing_matching_catalog_is_never_updated(db_session, evidence):
    product_id, sku_ids = next(iter(module.GROUPS.items()))
    sku_id = next(iter(sku_ids))
    db_session.add(DimSkuProductRule(sku_id=sku_id, product_id=product_id, owner_account_id="synthetic-owner",
        sku_name="Historical manual name", product_scope="Manual scope", product_type="Manual type", is_service_product=True))
    db_session.commit()
    preview = call(db_session, evidence)
    result = call(db_session, evidence, apply=True, fingerprint=preview["fingerprint"], evidence_digest=preview["evidence_digest"])
    assert len(result["created_sku_ids"]) == 5
    row = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == sku_id))
    assert (row.sku_name, row.product_scope, row.product_type, row.is_service_product) == ("Historical manual name", "Manual scope", "Manual type", True)
    assert db_session.scalar(select(func.count()).select_from(SkuProductSyncHistory)) == 5


def test_concurrent_catalog_insert_changes_fingerprint(db_session, evidence):
    preview = call(db_session, evidence)
    product_id, sku_ids = next(iter(module.GROUPS.items()))
    db_session.add(DimSkuProductRule(sku_id=next(iter(sku_ids)), product_id=product_id, owner_account_id="synthetic-owner"))
    db_session.commit()
    with pytest.raises(PatchError, match="fingerprint stale"):
        call(db_session, evidence, apply=True, fingerprint=preview["fingerprint"], evidence_digest=preview["evidence_digest"])


def test_failure_after_history_write_rolls_back_entire_transaction(db_session, evidence, monkeypatch):
    preview = call(db_session, evidence)
    original = module._update_current_snapshots
    def fail_after_catalog(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure after history and catalog writes")
    monkeypatch.setattr(module, "_update_current_snapshots", fail_after_catalog)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        call(db_session, evidence, apply=True, fingerprint=preview["fingerprint"], evidence_digest=preview["evidence_digest"])
    for model in (DimSkuProductRule, SkuProductSyncHistory, AccountPermissionAuditLog, JobRun):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0


def test_requires_reviewed_digest_and_preview_before_apply(db_session, evidence):
    with pytest.raises(PatchError, match="reviewed"):
        call(db_session, evidence, apply=True)


def test_audit_failure_rolls_back_history_and_all_created_catalog(db_session, evidence, monkeypatch):
    preview = call(db_session, evidence)
    original = db_session.flush
    def flush_then_fail_audit(*args, **kwargs):
        has_audit = any(isinstance(row, AccountPermissionAuditLog) for row in db_session.new)
        original(*args, **kwargs)
        if has_audit:
            raise RuntimeError("synthetic audit persistence failure")
    monkeypatch.setattr(db_session, "flush", flush_then_fail_audit)
    with pytest.raises(RuntimeError, match="audit persistence"):
        call(db_session, evidence, apply=True, fingerprint=preview["fingerprint"], evidence_digest=preview["evidence_digest"])
    monkeypatch.setattr(db_session, "flush", original)
    for model in (DimSkuProductRule, SkuProductSyncHistory, AccountPermissionAuditLog):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("case", ["missing-creator", "inactive-product"])
def test_normalizer_refusal_is_not_coerced_to_success(db_session, evidence, case):
    product = json.loads(evidence[0])
    if case == "missing-creator":
        product["source"]["data"]["product_onlines"][0]["product"].pop("creator_account_id")
    else:
        product["source"]["data"]["product_onlines"][0]["online_status"] = 2
    content = json.dumps(product).encode()
    sku = copy.deepcopy(evidence[1]); sku["source_sha256"] = hashlib.sha256(content).hexdigest()
    with pytest.raises(PatchError, match="normalizer"):
        call(db_session, (content, sku))
