"""Preview/apply additive SKU rules without scheduling settlement rebuilds.

Input is a JSON list of sku_id, product_id, product_type, promotion_rate,
management_rate, effective_date. Rates are decimal fractions (0..1), with at
most six places. Use a fresh Session; this operation owns its transaction.
CLI input/report paths must be outside Git or explicitly ignored by Git.

AccountPermissionAuditLog is temporarily reused solely as an existing
structured audit carrier: action=SETTLEMENT_RULE_PATCH is a rule configuration
operation, never an account-permission mutation. Explicit ops identities are
recorded with actor_role=ops and no target/actor user ID. They do not impersonate
human administrators, create accounts, or grant permissions. The audit and all
rule/catalog mutations commit or roll back in the same transaction.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from apps.api.dy_api.db import make_engine
from apps.api.dy_api.models import AccountPermissionAuditLog, DimSkuProductRule, JobRun, SkuFeeRule, User
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY

OPERATION = "SETTLEMENT_RULE_PATCH"
SHANGHAI = timezone(timedelta(hours=8))


class PatchError(ValueError):
    """A fail-closed precondition rejected the whole patch."""


def _plain(value):
    if isinstance(value, Decimal):
        return format(value, ".6f")
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_plain).encode()).hexdigest()


def _row(row):
    return {column.key: _plain(getattr(row, column.key)) for column in inspect(type(row)).column_attrs}


def _normalize(rows):
    if not isinstance(rows, list) or not rows:
        raise PatchError("input must be a nonempty list")
    result, seen, types = [], set(), {}
    fields = {"sku_id", "product_id", "product_type", "promotion_rate", "management_rate", "effective_date"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields:
            raise PatchError("each row must contain exactly the six documented fields")
        item = dict(row)
        for field in ("sku_id", "product_id", "product_type"):
            if not isinstance(item[field], str) or not item[field].strip() or len(item[field]) > 128:
                raise PatchError(f"invalid {field}")
            item[field] = item[field].strip()
        if not isinstance(item["effective_date"], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", item["effective_date"]):
            raise PatchError("invalid effective_date")
        try:
            date.fromisoformat(item["effective_date"])
            for field in ("promotion_rate", "management_rate"):
                rate = Decimal(str(item[field]))
                if not rate.is_finite() or not 0 <= rate <= 1 or rate != rate.quantize(Decimal(".000001")):
                    raise PatchError(f"invalid {field}; use a fraction with at most six decimal places")
                item[field] = format(rate, ".6f")
        except (ValueError, InvalidOperation) as exc:
            raise PatchError("invalid date or rate") from exc
        identity = item["sku_id"], item["effective_date"]
        if identity in seen:
            raise PatchError("duplicate sku/date input")
        seen.add(identity)
        dimension = item["product_id"], item["product_type"]
        if item["sku_id"] in types and types[item["sku_id"]] != dimension:
            raise PatchError("inconsistent catalog identity/type for one SKU")
        types[item["sku_id"]] = dimension
        result.append(item)
    return sorted(result, key=lambda item: (item["sku_id"], item["effective_date"]))


def _fence(session):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text("SET LOCAL statement_timeout = '30s'"))
        if not session.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY))):
            raise PatchError("shared heavy claim lock busy")
        # API fee publication does not take the heavy claim lock. Fence rule
        # inserts too, including a concurrent different effective date which
        # would otherwise escape target-row locking and the date uniqueness.
        session.execute(text("LOCK TABLE sku_fee_rule IN SHARE ROW EXCLUSIVE MODE"))
    elif dialect != "sqlite":
        raise PatchError("unsupported database dialect")
    # A retrying multi-transaction writer still owns its source facts.
    busy = session.scalar(select(JobRun.job_id).where(
        JobRun.status.in_(("running", "retry_wait")),
        or_(JobRun.execution_slot == "heavy_sync",
            JobRun.job_kind.in_(("date_sync", "parent_sync", "finalize", "product_sync")),
            JobRun.job_name.in_(("collect_and_settle", "settlement_rebuild", "manual_backend_aweme_export",
                                "manual_sync", "collect_once", "settlement_compaction", "refund_evidence_replay"))),
    ).limit(1))
    if busy:
        raise PatchError("source writer running or awaiting retry")


def _actor_role(session, actor):
    if actor.startswith("ops:"):
        if not re.fullmatch(r"ops:[A-Za-z0-9][A-Za-z0-9:._-]*", actor):
            raise PatchError("invalid ops actor identity")
        return "ops", None
    user = session.scalar(select(User).where(User.username == actor).with_for_update())
    if user is None or user.status != "active" or user.role not in ("admin", "highest_admin") or user.store_scope_mode != "all":
        raise PatchError("actor must be an existing active global administrator or an explicit ops identity")
    return user.role, user.user_id


def patch_rules(session: Session, rows: list[dict], *, source_digest: str, actor: str,
                change_reason: str, idempotency_key: str, fingerprint: str | None = None,
                apply: bool = False) -> dict:
    """Return a reviewable diff, or atomically apply a matching reviewed diff.

    SQLite is supported only for isolated tests; the CLI requires PostgreSQL
    for apply because its advisory lock is the cross-process writer fence.
    All failures roll back; no queue, existing rule, or financial fact is changed.
    """
    rows = _normalize(rows)
    if apply and (not isinstance(fingerprint, str) or not re.fullmatch("[0-9a-f]{64}", fingerprint)):
        raise PatchError("preview fingerprint missing or stale")
    if not isinstance(source_digest, str) or not re.fullmatch("[0-9a-fA-F]{64}", source_digest):
        raise PatchError("source_digest must be the source SHA-256")
    for name, value, limit in (("actor", actor, 128), ("change_reason", change_reason, 512), ("idempotency_key", idempotency_key, 256)):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise PatchError(f"invalid {name}")
    if session.in_transaction():
        raise PatchError("use a fresh session without an existing transaction")
    payload = {"rows": rows, "source_digest": source_digest.lower(), "actor": actor,
               "change_reason": change_reason}
    payload_hash = _digest(payload)
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    with session.begin():
        _fence(session)
        actor_role, actor_user_id = _actor_role(session, actor)
        replay = session.get(AccountPermissionAuditLog, "rule-patch-" + key_hash)
        if replay is not None:
            if replay.action != OPERATION or replay.after_json.get("payload_hash") != payload_hash:
                raise PatchError("idempotency key reused with different payload")
            return {**replay.after_json, "replayed": True}
        sku_ids = sorted({item["sku_id"] for item in rows})
        skus = {row.sku_id: row for row in session.scalars(select(DimSkuProductRule).where(
            DimSkuProductRule.sku_id.in_(sku_ids)).order_by(DimSkuProductRule.sku_id).with_for_update())}
        rules = list(session.scalars(select(SkuFeeRule).where(SkuFeeRule.sku_id.in_(sku_ids))
                                    .order_by(SkuFeeRule.sku_id, SkuFeeRule.effective_date).with_for_update()))
        before = {"catalog": [_row(skus[key]) for key in sorted(skus)], "rules": [_row(rule) for rule in rules]}
        current_fingerprint = _digest({"request": payload_hash, "state": before})
        diff, errors = [], []
        existing = {(rule.sku_id, rule.effective_date.isoformat()): rule for rule in rules}
        for item in rows:
            sku = skus.get(item["sku_id"])
            rule = existing.get((item["sku_id"], item["effective_date"]))
            error = None
            if sku is None:
                error = "UNKNOWN_SKU"
            elif sku.product_id != item["product_id"]:
                error = "PRODUCT_ID_MISMATCH"
            elif rule is not None and (rule.rule_status != 1 or
                rule.promotion_service_fee_rate != Decimal(item["promotion_rate"]) or
                rule.management_service_fee_rate != Decimal(item["management_rate"])):
                error = "EXISTING_RULE_CONFLICT"
            entry = {**item, "rule_action": "BLOCKED" if error else "NOOP" if rule else "CREATE",
                     "preserved_product_scope": sku.product_scope if sku else None,
                     "preserved_is_service_product": sku.is_service_product if sku else None,
                     "catalog_type_before": sku.product_type if sku else None,
                     "catalog_type_after": item["product_type"],
                     "manual_modified_at": _plain(sku.manual_modified_at) if sku else None,
                     "existing_rule_version": rule.rule_version if rule else None, "error": error}
            diff.append(entry)
            if error:
                errors.append({"sku_id": item["sku_id"], "effective_date": item["effective_date"], "code": error})
        report = {"applied": False, "replayed": False, "fingerprint": current_fingerprint,
                  "payload_hash": payload_hash, "source_digest": source_digest.lower(),
                  "actor": actor, "actor_role": actor_role, "change_reason": change_reason,
                  "diff": diff, "errors": errors, "can_apply": not errors, "rebuild_queued": False}
        if not apply:
            return report
        if not fingerprint or fingerprint != current_fingerprint:
            raise PatchError("preview fingerprint missing or stale")
        if errors:
            raise PatchError("batch blocked: " + json.dumps(errors))
        now = datetime.now(timezone.utc)
        for item, entry in zip(rows, diff, strict=True):
            sku = skus[item["sku_id"]]
            if sku.product_type != item["product_type"]:
                sku.product_type = item["product_type"]
                sku.manual_modified_at, sku.manual_modified_by = now, actor
            if entry["rule_action"] == "NOOP":
                continue
            effective_date = date.fromisoformat(item["effective_date"])
            previous = [rule for rule in rules if rule.sku_id == sku.sku_id and rule.effective_date < effective_date]
            row_key = _digest({"key": key_hash, "sku": sku.sku_id, "date": item["effective_date"]})
            rule = SkuFeeRule(
                rule_version="srp-" + row_key[:48], idempotency_key_hash=row_key, request_payload_sha256=payload_hash,
                sku_id=sku.sku_id, sku_name_snapshot=sku.sku_name, product_scope_snapshot=sku.product_scope,
                product_type_snapshot=item["product_type"], promotion_service_fee_rate=Decimal(item["promotion_rate"]),
                management_service_fee_rate=Decimal(item["management_rate"]), effective_date=effective_date,
                effective_at=datetime.combine(effective_date, time.min, SHANGHAI), rule_status=1,
                previous_rule_version=max(previous, key=lambda rule: rule.effective_date).rule_version if previous else None,
                created_by=actor, change_reason=change_reason, published_at=now,
            )
            session.add(rule)
            rules.append(rule)
            entry["created_rule_version"] = rule.rule_version
        report["applied"] = True
        session.add(AccountPermissionAuditLog(
            audit_id="rule-patch-" + key_hash, action=OPERATION, result="success",
            actor_user_id=actor_user_id, actor_username=actor, actor_role=actor_role,
            target_user_id=None, target_username=None,
            before_json=before, after_json=report, created_at=now,
        ))
        session.flush()
        return report


def _private_path(path: Path) -> Path:
    path = path.resolve(strict=False)
    probe = path if path.is_dir() else path.parent
    result = subprocess.run(["git", "-C", str(probe), "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8")
    if result.returncode == 0:
        repo = Path(result.stdout.strip())
        relative = path.relative_to(repo)
        tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", str(relative)], capture_output=True)
        ignored = subprocess.run(["git", "-C", str(repo), "check-ignore", "--quiet", "--", str(relative)])
        if tracked.returncode == 0 or ignored.returncode != 0:
            raise PatchError("input/report must be outside Git or in an ignored, untracked path")
    return path


def main() -> int:
    """Run a dry preview by default; applying always needs its fingerprint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="New ignored/external file; never overwritten")
    parser.add_argument("--source-digest", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--change-reason", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--fingerprint")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        source_path, report_path = _private_path(args.input), _private_path(args.report)
        rows = json.loads(source_path.read_text(encoding="utf-8-sig"), parse_float=Decimal)
        engine = make_engine()
        if args.apply and engine.dialect.name != "postgresql":
            raise PatchError("CLI apply requires PostgreSQL shared advisory locking")
        # Reserve the exclusive output path before making any database change.
        with report_path.open("x", encoding="utf-8") as output:
            with Session(engine, autoflush=False) as session:
                report = patch_rules(session, rows, source_digest=args.source_digest, actor=args.actor,
                    change_reason=args.change_reason, idempotency_key=args.idempotency_key,
                    fingerprint=args.fingerprint, apply=args.apply)
            json.dump(report, output, ensure_ascii=False, indent=2, default=_plain)
        print(json.dumps({"applied": report["applied"], "can_apply": report["can_apply"], "fingerprint": report["fingerprint"]}))
        return 0 if report["can_apply"] else 2
    except SQLAlchemyError:
        print("database operation failed; no credential or SQL payload emitted", file=sys.stderr)
        return 2
    except (PatchError, OSError, ValueError) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
