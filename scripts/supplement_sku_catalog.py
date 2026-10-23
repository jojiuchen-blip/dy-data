"""Create only missing six reviewed SKU catalog records from paired API evidence.

No network calls, fee configuration, financial writes or rebuild jobs. Product
online/get and scoped SKU/get responses remain unchanged in the same-transaction
structured audit carrier (AccountPermissionAuditLog, not a permission change).
Normal product_sync normalization/upsert/history supply all platform fields.
Human classification defaults remain those of normal product sync; no scope,
service eligibility, owner, historical ACTIVE state or external SUCCESS is invented.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dy_api.db import make_engine
from apps.api.dy_api.models import AccountPermissionAuditLog, DimSkuProductRule, SkuProductSyncHistory
from apps.worker.product_sync import (
    _normalize_douyin_online_rows, parse_normalized_product_page,
    _update_current_snapshots, _write_history_snapshots,
)
from scripts.settlement_rule_patch import PatchError, _actor_role, _digest, _fence, _private_path, _row

GROUPS = {
    "1833075506383931": {"1833075751534649", "1833075751536649"},
    "1869850636737587": {"1869850964088851", "1869850964088867"},
    "1869771684880395": {"1869771819977786", "1869771819979786"},
}
SKU_URL = "https://open.douyin.com/goodlife/v1/goods/sku/get/"
OPERATION = "SKU_CATALOG_EVIDENCE_SUPPLEMENT"


def _success(response):
    if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
        raise PatchError("API evidence has no data object")
    found = False
    for container, key in ((response, "error_code"), (response.get("data", {}), "error_code"),
                           (response.get("extra", {}), "error_code"), (response.get("BaseResp", {}), "StatusCode")):
        if key in container:
            found = True
            if container[key] not in (0, "0"):
                raise PatchError("API evidence contains a nonzero error code")
    if not found:
        raise PatchError("API evidence lacks success codes")


def parse_evidence(product_bytes: bytes, sku_bytes: bytes):
    """Verify exact target identity before feeding existing normalization."""
    product_document = json.loads(product_bytes.decode("utf-8-sig"))
    sku_document = json.loads(sku_bytes.decode("utf-8-sig"))
    product_digest = hashlib.sha256(product_bytes).hexdigest()
    sku_digest = hashlib.sha256(sku_bytes).hexdigest()
    if sku_document.get("source_sha256") != product_digest or sku_document.get("endpoint") != SKU_URL or sku_document.get("stopped_after_error") is not False:
        raise PatchError("SKU evidence is not bound to the original product source")
    response = product_document.get("source", {})
    _success(response)
    products = {}
    for record in response["data"].get("product_onlines", []):
        product_id = str(record.get("product", {}).get("product_id", ""))
        if product_id in GROUPS:
            if product_id in products:
                raise PatchError("duplicate product evidence")
            products[product_id] = record
    requests = sku_document.get("requests", [])
    if set(products) != set(GROUPS) or len(requests) != 3:
        raise PatchError("evidence must contain exactly the three reviewed product requests")
    groups, seen = [], set()
    for request in requests:
        product_id = str(request.get("product_id", ""))
        if product_id not in GROUPS or product_id in seen or request.get("result") != "RESPONSE_RECEIVED":
            raise PatchError("unexpected or duplicate SKU request")
        seen.add(product_id)
        requested = request.get("requested_sku_ids", [])
        if len(requested) != 2 or set(requested) != GROUPS[product_id]:
            raise PatchError("requested SKU pairs differ from approved scope")
        body = request.get("response", {})
        _success(body)
        returned = body["data"].get("skus", [])
        if len(returned) != 2 or {str(row.get("sku_id", "")) for row in returned} != GROUPS[product_id]:
            raise PatchError("returned SKU pairs incomplete, duplicate or out of scope")
        product = products[product_id]["product"]
        owner = str(product.get("owner_account_id", ""))
        if owner in ("", "0", "None") or str(request.get("proven_product_owner_account_id", "")) != owner:
            raise PatchError("product owner proof is absent or inconsistent")
        for sku in returned:
            if sku.get("product_id") not in (None, "", product_id):
                raise PatchError("SKU response product ID mismatch")
            # This bounded repair is reviewed only for the six observed status=1
            # records. Other states need a new review, never coercion to ACTIVE.
            if isinstance(sku.get("status"), bool) or sku.get("status") != 1:
                raise PatchError("SKU raw status differs from reviewed evidence")
            for field in ("origin_amount", "actual_amount"):
                value = sku.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise PatchError("SKU amount must retain its raw nonnegative integer value")
        observed = body.get("extra", {}).get("now")
        if isinstance(observed, bool) or not isinstance(observed, int) or not 946684800 <= observed <= 4102444800:
            raise PatchError("missing valid seconds-based platform observation time")
        # Compose a new adapter view; neither original response is modified.
        combined = {**products[product_id], "sku": {}, "skus": returned}
        normalized, skipped = _normalize_douyin_online_rows([combined])
        page = parse_normalized_product_page({"items": normalized, "hasMore": False, "nextCursor": None, "skippedCount": skipped})
        if skipped or page.invalid_items or len(page.items) != 2:
            raise PatchError("normal product sync rejected the composed evidence")
        if any(item.sync_status != "SUCCESS" or item.product_status_normalized != "ACTIVE" for item in page.items):
            raise PatchError("normalizer did not verify complete reviewed platform metadata")
        groups.append((page.items, datetime.fromtimestamp(observed, timezone.utc), returned))
    evidence_digest = _digest({"product_sha256": product_digest, "sku_sha256": sku_digest})
    return product_document, sku_document, groups, evidence_digest


def supplement_catalog(session: Session, product_bytes: bytes, sku_bytes: bytes, *, actor: str,
                       change_reason: str, idempotency_key: str, apply=False,
                       fingerprint=None, evidence_digest=None):
    """Preview or atomically create missing catalog + normal history + audit."""
    product_document, sku_document, groups, actual_digest = parse_evidence(product_bytes, sku_bytes)
    for name, value, limit in (("actor", actor, 128), ("change_reason", change_reason, 512), ("idempotency_key", idempotency_key, 256)):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise PatchError("invalid " + name)
    if evidence_digest is not None and evidence_digest != actual_digest:
        raise PatchError("evidence digest mismatch")
    if apply and (evidence_digest != actual_digest or not isinstance(fingerprint, str) or not re.fullmatch("[0-9a-f]{64}", fingerprint)):
        raise PatchError("apply requires reviewed evidence digest and fingerprint")
    if session.in_transaction():
        raise PatchError("use a fresh session")
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    audit_id = "catalog-supplement-" + key_hash
    payload_hash = _digest({"evidence_digest": actual_digest, "actor": actor, "reason": change_reason})
    with session.begin():
        _fence(session)
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("LOCK TABLE dim_sku_product_rules IN SHARE ROW EXCLUSIVE MODE"))
        role, user_id = _actor_role(session, actor)
        replay = session.get(AccountPermissionAuditLog, audit_id)
        if replay:
            if replay.action != OPERATION or replay.after_json.get("payload_hash") != payload_hash:
                raise PatchError("idempotency key reused with different payload")
            return {**replay.after_json["report"], "replayed": True}
        all_items = [item for items, _, _ in groups for item in items]
        sku_ids = sorted(item.sku_id for item in all_items)
        current = {row.sku_id: row for row in session.scalars(select(DimSkuProductRule).where(
            DimSkuProductRule.sku_id.in_(sku_ids)).order_by(DimSkuProductRule.sku_id).with_for_update())}
        history = list(session.scalars(select(SkuProductSyncHistory).where(SkuProductSyncHistory.sku_id.in_(sku_ids))
            .order_by(SkuProductSyncHistory.snapshot_id).with_for_update()))
        before = {"catalog": [_row(current[key]) for key in sorted(current)], "history": [_row(row) for row in history]}
        state_hash = _digest({"payload": payload_hash, "state": before})
        diff, conflicts = [], []
        for item in all_items:
            existing = current.get(item.sku_id)
            if existing is not None and (existing.product_id != item.product_id or existing.owner_account_id != item.owner_account_id):
                conflicts.append(item.sku_id)
            diff.append({"sku_id": item.sku_id, "product_id": item.product_id, "owner_account_id": item.owner_account_id,
                "product_status_raw": item.product_status_raw, "product_status_normalized": item.product_status_normalized,
                "internal_sync_status": item.sync_status, "action": "EXISTING_NOOP" if existing else "CREATE"})
        report = {"applied": False, "replayed": False, "evidence_digest": actual_digest, "fingerprint": state_hash,
            "payload_hash": payload_hash, "diff": diff, "conflicting_existing_skus": conflicts,
            "can_apply": not conflicts, "rebuild_queued": False}
        if not apply:
            return report
        if fingerprint != state_hash:
            raise PatchError("preview fingerprint stale")
        if conflicts:
            raise PatchError("existing catalog identity conflicts; no overwrite allowed")
        run_id = "catalog-evidence-" + key_hash[:40]
        created = []
        for items, observed_at, _ in groups:
            missing = [item for item in items if item.sku_id not in current]
            if not missing:
                continue
            _write_history_snapshots(session, job_id=run_id, items=missing, observed_at=observed_at)
            inserted, updated, unchanged = _update_current_snapshots(session, job_id=run_id, items=missing, observed_at=observed_at)
            if inserted != len(missing) or updated or unchanged:
                raise PatchError("catalog changed concurrently; refusing updates")
            created.extend(item.sku_id for item in missing)
        report.update(applied=True, created_sku_ids=sorted(created), sync_run_id=run_id)
        session.add(AccountPermissionAuditLog(audit_id=audit_id, action=OPERATION, result="success",
            actor_user_id=user_id, actor_username=actor, actor_role=role,
            target_user_id=None, target_username=None, before_json=before,
            after_json={"payload_hash": payload_hash, "report": report, "change_reason": change_reason,
                "original_product_document": product_document, "original_sku_document": sku_document},
            created_at=datetime.now(timezone.utc)))
        session.flush()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-source", required=True, type=Path)
    parser.add_argument("--sku-source", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--change-reason", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--evidence-digest")
    parser.add_argument("--fingerprint")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        product_source, sku_source, report_path = map(_private_path, (args.product_source, args.sku_source, args.report))
        product_bytes, sku_bytes = product_source.read_bytes(), sku_source.read_bytes()
        engine = make_engine()
        if args.apply and engine.dialect.name != "postgresql":
            raise PatchError("CLI apply requires PostgreSQL locking")
        with report_path.open("x", encoding="utf-8") as output:
            with Session(engine, autoflush=False) as session:
                report = supplement_catalog(session, product_bytes, sku_bytes, actor=args.actor, change_reason=args.change_reason,
                    idempotency_key=args.idempotency_key, apply=args.apply, fingerprint=args.fingerprint, evidence_digest=args.evidence_digest)
            json.dump(report, output, ensure_ascii=False, indent=2)
        print(json.dumps({"applied": report["applied"], "can_apply": report["can_apply"], "evidence_digest": report["evidence_digest"], "fingerprint": report["fingerprint"]}))
        return 0 if report["can_apply"] else 2
    except (PatchError, ValueError, OSError, SQLAlchemyError) as exc:
        print(json.dumps({"error_type": type(exc).__name__, "message": "supplement aborted; no exception payload emitted"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
