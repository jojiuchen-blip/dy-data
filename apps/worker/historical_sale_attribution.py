"""Import and resolve exact, immutable historical sale-store decisions.

This ledger is settlement evidence, never a current account binding. The CLI
defaults to validation only and does not schedule or run a calculation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DimStore, HistoricalSaleAttributionDecision, JobEvent, JobRun,
    RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
    SettlementFeeResult,
)
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY

TABLE_NAME = "historical_sale_attribution_decisions"
_MONTH = re.compile(r"20\d{2}-(?:0[1-9]|1[0-2])\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_REBUILD_LOCK = 0x4459444154410087


class HistoricalAttributionError(ValueError):
    """The reviewed scope conflicts with current source identity or another decision."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise HistoricalAttributionError(f"invalid {field}")
    return value


def _positive_id(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HistoricalAttributionError(f"invalid {field}")
    return value


def _instant(value: Any, *, from_manifest: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HistoricalAttributionError("invalid source timestamp") from exc
    if not isinstance(value, datetime) or (from_manifest and value.tzinfo is None):
        raise HistoricalAttributionError("source timestamp must carry a timezone")
    # SQLite returns UTC timestamptz values without an offset.
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _manifest_identity(row: dict[str, Any]) -> dict[str, Any]:
    identity = {field: _text(row.get(field), field) for field in (
        "order_id", "coupon_id", "source_account_id", "store_id", "verify_id", "business_month",
    )}
    for field in ("raw_order_id", "raw_coupon_id"):
        identity[field] = _positive_id(row.get(field), field)
    month = identity["business_month"]
    if not _MONTH.fullmatch(month) or month < "2026-08":
        raise HistoricalAttributionError("business month is outside the formal scope")
    approved_months = row.get("approved_business_months")
    if (not isinstance(approved_months, list) or not approved_months
            or not all(isinstance(value, str) and _MONTH.fullmatch(value) for value in approved_months)
            or month not in approved_months):
        raise HistoricalAttributionError("business month is not explicitly approved")
    for field in ("sale_time", "pay_time", "verify_time"):
        identity[field] = _instant(row.get(field), from_manifest=True)
    if identity["verify_time"] is None:
        raise HistoricalAttributionError("verify_time is required")
    if datetime.fromisoformat(identity["verify_time"]).astimezone(_SHANGHAI).strftime("%Y-%m") != month:
        raise HistoricalAttributionError("verification month does not match the approved scope")
    for field in ("order_payload_fingerprint", "coupon_payload_fingerprint", "verify_payload_fingerprint"):
        value = row.get(field)
        if value is not None and (not isinstance(value, str) or not _SHA.fullmatch(value)):
            raise HistoricalAttributionError(f"invalid {field}")
        identity[field] = value
    return identity


def _live_identity(
    order: RawDouyinOrder, coupon: RawDouyinOrderCoupon,
    verify: RawDouyinVerifyRecord | None, store_id: str,
) -> dict[str, Any]:
    if (verify is None or verify.verify_time is None or verify.coupon_id != coupon.coupon_id
            or coupon.raw_order_id != order.id or coupon.order_id != order.order_id):
        raise HistoricalAttributionError("historical attribution source identity changed")
    verify_time = _instant(verify.verify_time)
    return {
        "raw_order_id": order.id, "order_id": order.order_id,
        "raw_coupon_id": coupon.id, "coupon_id": coupon.coupon_id,
        "source_account_id": order.owner_account_id, "store_id": store_id,
        "verify_id": verify.verify_id, "verify_time": verify_time,
        "business_month": datetime.fromisoformat(verify_time).astimezone(_SHANGHAI).strftime("%Y-%m"),
        "sale_time": _instant(order.sale_time), "pay_time": _instant(order.pay_time),
        "order_payload_fingerprint": order.payload_fingerprint,
        "coupon_payload_fingerprint": coupon.payload_fingerprint,
        "verify_payload_fingerprint": verify.payload_fingerprint,
    }


def resolve_historical_sale_attribution(
    session: Session, *, order: RawDouyinOrder, coupon: RawDouyinOrderCoupon,
    verify: RawDouyinVerifyRecord | None,
    current_result: SettlementFeeResult | None = None,
) -> HistoricalSaleAttributionDecision | None:
    """Validate stable approved identity while retaining ordinary financial events."""
    decisions = list(session.scalars(select(HistoricalSaleAttributionDecision).where(
        HistoricalSaleAttributionDecision.coupon_id == coupon.coupon_id,
    )))
    if not decisions:
        return None
    if len(decisions) != 1:
        raise HistoricalAttributionError("ambiguous historical attribution decisions")
    decision = decisions[0]
    basis_verify = verify
    if basis_verify is None and current_result is not None and (
        current_result.sale_attribution_decision_id == decision.decision_id
        and current_result.coupon_id == decision.coupon_id
        and current_result.order_id == decision.order_id
        and current_result.sale_store_id == decision.store_id
        and current_result.original_business_month == decision.business_month
        and current_result.qualifying_verify_id == decision.verify_id
        and _instant(current_result.qualifying_verify_time) == _instant(decision.verify_time)
    ):
        cancelled = session.get(RawDouyinVerifyRecord, decision.verify_id)
        if cancelled is not None and cancelled.cancel_time is not None:
            # Validate the frozen original identity only. The caller keeps its
            # actual verify=None and follows the existing cancellation path;
            # this never grants new fee eligibility or a new verification.
            basis_verify = cancelled
    current = _live_identity(order, coupon, basis_verify, decision.store_id)
    stored_columns = {
        field: getattr(decision, field) for field in (
            "raw_order_id", "order_id", "raw_coupon_id", "coupon_id", "source_account_id",
            "store_id", "verify_id", "business_month",
        )
    }
    stored_columns["verify_time"] = _instant(decision.verify_time)
    # Payload digests freeze the reviewed import observation. Later refunds or
    # cancellation legitimately change those observations; stable attribution
    # identity stays exact and the original financial gates still run.
    stable_fields = set(current) - {
        "order_payload_fingerprint", "coupon_payload_fingerprint", "verify_payload_fingerprint",
    }
    if (_digest(decision.source_identity_json) != decision.source_identity_sha256
            or any(current[field] != decision.source_identity_json.get(field) for field in stable_fields)
            or any(current[field] != value for field, value in stored_columns.items())):
        raise HistoricalAttributionError("historical attribution source identity changed")
    store = session.get(DimStore, decision.store_id)
    if store is None or not store.is_active:
        raise HistoricalAttributionError("historical attribution target store is not active")
    return decision


def month_decision_digest(session: Session, business_month: str) -> str | None:
    """Return a stable input revision only for months that contain decisions."""
    rows = session.execute(select(
        HistoricalSaleAttributionDecision.decision_id,
        HistoricalSaleAttributionDecision.source_identity_sha256,
        HistoricalSaleAttributionDecision.evidence_sha256,
    ).where(HistoricalSaleAttributionDecision.business_month == business_month)
      .order_by(HistoricalSaleAttributionDecision.decision_id)).all()
    return _digest([tuple(row) for row in rows]) if rows else None


def _import_lock(session: Session) -> None:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        for key in sorted((HEAVY_SYNC_CLAIM_LOCK_KEY, _REBUILD_LOCK)):
            if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}):
                raise HistoricalAttributionError("source writer claim lock is busy")
        # Fence source rows and newly inserted verification records throughout
        # the short validation+append transaction, including API-side writers.
        session.execute(text(
            "LOCK TABLE dim_stores, raw_douyin_orders, raw_douyin_order_coupons, "
            "raw_douyin_verify_records IN SHARE MODE NOWAIT"
        ))
    elif dialect != "sqlite":
        raise HistoricalAttributionError("unsupported database dialect")
    active = session.scalar(select(JobRun.job_id).where(
        JobRun.status.in_(("running", "retry_wait")),
        (JobRun.execution_slot == "heavy_sync") | JobRun.job_name.in_((
            "collect_and_settle", "settlement_rebuild", "manual_backend_aweme_export",
            "manual_sync", "collect_once", "settlement_compaction", "refund_evidence_replay",
        ))
        | JobRun.job_kind.in_(("date_sync", "parent_sync", "finalize", "product_sync")),
    ).limit(1))
    if active is not None:
        raise HistoricalAttributionError("a source writer is running")


def import_decisions(session: Session, manifest: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
    """Validate a whole reviewed manifest, then append it atomically if requested.

    The caller owns commit/rollback. No source binding or financial fact is
    changed; no rebuild is scheduled. A different decision for a coupon conflicts.
    """
    from apps.worker.settlement import _select_valid_verify_record  # Avoid import cycle.

    if not isinstance(manifest, dict):
        raise HistoricalAttributionError("manifest must be an object")
    batch_id = _text(manifest.get("batch_id"), "batch_id")
    actor = _text(manifest.get("actor"), "actor")
    if len(batch_id) > 128 or len(actor) > 128:
        raise HistoricalAttributionError("batch_id or actor is too long")
    evidence = manifest.get("evidence_sha256")
    approval = manifest.get("approval_evidence")
    if not isinstance(evidence, str) or not _SHA.fullmatch(evidence):
        raise HistoricalAttributionError("evidence_sha256 must be a SHA-256 digest")
    if not isinstance(approval, dict) or not approval or len(json.dumps(approval)) > 16384:
        raise HistoricalAttributionError("explicit approval evidence is required")
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000 or not all(isinstance(row, dict) for row in rows):
        raise HistoricalAttributionError("manifest must contain 1 to 5000 exact rows")
    identities = sorted((_manifest_identity(row) for row in rows), key=lambda row: row["coupon_id"])
    if len({row["coupon_id"] for row in identities}) != len(identities):
        raise HistoricalAttributionError("duplicate or ambiguous coupon scope in manifest")
    payload_digest = _digest({"batch_id": batch_id, "actor": actor, "evidence": evidence,
                              "approval": approval, "identities": identities})
    job_id = "historical-attribution-import-" + _digest(batch_id)[:32]
    if apply:
        _import_lock(session)
    previous_job = session.get(JobRun, job_id)
    if previous_job is not None and (
        previous_job.job_name != "historical_sale_attribution_import"
        or (previous_job.metadata_json or {}).get("manifest_sha256") != payload_digest
    ):
        raise HistoricalAttributionError("batch key is already bound to a different manifest")
    pending = []
    existing_count = 0
    for identity in identities:
        coupon_query = select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.id == identity["raw_coupon_id"])
        if apply:
            coupon_query = coupon_query.with_for_update()
        coupon = session.scalar(coupon_query.execution_options(populate_existing=True))
        order = session.get(RawDouyinOrder, identity["raw_order_id"], populate_existing=True)
        if coupon is None or order is None:
            raise HistoricalAttributionError("reviewed raw order or coupon no longer exists")
        verify = _select_valid_verify_record(session, coupon.coupon_id, refresh_source=True)
        current = _live_identity(order, coupon, verify, identity["store_id"])
        store = session.get(DimStore, identity["store_id"], populate_existing=True)
        if current != identity or store is None or not store.is_active:
            raise HistoricalAttributionError("reviewed source or target-store identity changed")
        source_digest = _digest(identity)
        decision_id = "historical-sale-" + _digest({"batch": batch_id, "source": source_digest,
                                                    "evidence": evidence})[:48]
        existing = session.scalar(select(HistoricalSaleAttributionDecision).where(
            HistoricalSaleAttributionDecision.coupon_id == identity["coupon_id"],
        ))
        if existing is not None:
            if (existing.decision_id != decision_id or existing.source_identity_sha256 != source_digest
                    or existing.evidence_sha256 != evidence or existing.source_identity_json != identity):
                raise HistoricalAttributionError("coupon already has a different historical decision")
            existing_count += 1
            continue
        pending.append(HistoricalSaleAttributionDecision(
            decision_id=decision_id, batch_id=batch_id,
            raw_order_id=identity["raw_order_id"], order_id=identity["order_id"],
            raw_coupon_id=identity["raw_coupon_id"], coupon_id=identity["coupon_id"],
            verify_id=identity["verify_id"], verify_time=datetime.fromisoformat(identity["verify_time"]),
            business_month=identity["business_month"], source_account_id=identity["source_account_id"],
            store_id=identity["store_id"], source_identity_sha256=source_digest,
            source_identity_json=identity, evidence_sha256=evidence,
            approval_evidence_json=approval, actor=actor,
        ))
    if previous_job is not None and pending:
        raise HistoricalAttributionError("previous import audit exists but its decisions are missing")
    if apply and previous_job is None:
        now = datetime.now(timezone.utc)
        session.add_all(pending)
        session.add(JobRun(job_id=job_id, job_name="historical_sale_attribution_import",
                           status="success", started_at=now, finished_at=now,
                           metadata_json={"batch_id": batch_id, "manifest_sha256": payload_digest,
                                          "evidence_sha256": evidence, "decision_count": len(identities)}))
        session.flush()
        session.add(JobEvent(event_id=job_id + "-applied", job_id=job_id,
                             event_type="historical_sale_attribution_imported", actor_type="ops_agent",
                             actor_id=actor, idempotency_key=payload_digest, occurred_at=now,
                             payload_json={"manifest_sha256": payload_digest, "decision_count": len(identities)}))
        session.flush()
    return {"mode": "apply" if apply else "dry-run", "row_count": len(identities),
            "new_count": len(pending), "existing_count": existing_count,
            "manifest_sha256": payload_digest, "batch_id": batch_id,
            "months": sorted({row["business_month"] for row in identities})}


def main() -> None:
    """Validate by default; apply only the exact file whose hash was reviewed."""
    from apps.api.dy_api.db import get_session_factory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    raw = Path(args.manifest).read_bytes()
    file_digest = hashlib.sha256(raw).hexdigest()
    if args.apply and args.expected_sha256 != file_digest:
        parser.error("--apply requires the exact reviewed --expected-sha256")
    factory = get_session_factory()
    if factory is None:
        parser.error("a configured database is required")
    with factory() as session:
        if not args.apply and session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        result = import_decisions(session, json.loads(raw.decode("utf-8-sig")), apply=args.apply)
        if args.apply:
            session.commit()
            # Read back the actual durable batch after commit, in a fresh transaction.
            session.expire_all()
            durable = list(session.scalars(select(HistoricalSaleAttributionDecision).where(
                HistoricalSaleAttributionDecision.batch_id == result["batch_id"],
            )))
            result["readback_count"] = len(durable)
            if result["readback_count"] != result["row_count"]:
                raise HistoricalAttributionError("durable import readback did not match the reviewed batch")
            # Revalidate persisted identities, evidence and import audit after
            # commit; a row count alone is not proof of the accepted payload.
            replay = import_decisions(session, json.loads(raw.decode("utf-8-sig")))
            if replay["existing_count"] != result["row_count"] or replay["manifest_sha256"] != result["manifest_sha256"]:
                raise HistoricalAttributionError("durable import identity readback did not match")
            result["readback_verified"] = True
        else:
            session.rollback()
    print(json.dumps({**result, "file_sha256": file_digest}, sort_keys=True))


if __name__ == "__main__":
    main()
