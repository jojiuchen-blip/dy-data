"""Preview/apply the exact legacy Jingcheng catalog classification conversion.

Only current catalog product_type and its manual audit stamp change. Historical
fees, rule snapshots, bills, internal scope and ranking membership stay intact.
The existing structured audit carrier records this catalog operation with no
account-permission mutation. Use a fresh session: this operation owns its
transaction. CLI reports must be ignored/untracked or outside Git.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dy_api.db import make_engine
from apps.api.dy_api.commission_classification import maintained_type, participation_rules
from apps.api.dy_api.models import AccountPermissionAuditLog, DimSkuProductRule, JobRun, User
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
from dy_data.product_classification import JINGCHENG_PRODUCT_SCOPE, JINGCHENG_PRODUCT_TYPE

OPERATION = "CATALOG_JINGCHENG_TYPE_CONVERSION"
PARTICIPATING_OPERATION = "CATALOG_COMMISSION_TYPE_CONVERSION"


class ConversionError(ValueError):
    """The reviewed target set no longer meets conversion preconditions."""


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), default=_plain).encode("utf-8")).hexdigest()


def _catalog_snapshot(row: DimSkuProductRule) -> dict[str, Any]:
    return {column.key: _plain(getattr(row, column.key)) for column in inspect(type(row)).column_attrs}


def _actor(session: Session, actor: str, *, lock: bool = False) -> tuple[str, str | None]:
    if actor.startswith("ops:"):
        if not re.fullmatch(r"ops:[A-Za-z0-9][A-Za-z0-9:._-]*", actor):
            raise ConversionError("invalid ops actor identity")
        return "ops", None
    query = select(User).where(User.username == actor)
    user = session.scalar(query.with_for_update() if lock else query)
    if user is None or user.status != "active" or user.role not in {"admin", "highest_admin"} or user.store_scope_mode != "all":
        raise ConversionError("actor must be an active global administrator or explicit ops identity")
    return user.role, user.user_id


def _fence(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        # Each read after the predicate fence must see the latest committed
        # target set, even if the server's configured default is repeatable read.
        session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text("SET LOCAL statement_timeout = '30s'"))
        if not session.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY))):
            raise ConversionError("source writer claim lock busy")
        # Target-row locks alone cannot detect a concurrent insert or a
        # non-target row entering the scope. Fence all catalog DML, then reread
        # the complete exact target set under that fence before checking hash.
        session.execute(text("LOCK TABLE dim_sku_product_rules IN SHARE ROW EXCLUSIVE MODE"))
    elif session.get_bind().dialect.name != "sqlite":
        raise ConversionError("unsupported database dialect")
    busy = session.scalar(select(JobRun.job_id).where(
        JobRun.status.in_(("running", "retry_wait")),
        or_(JobRun.execution_slot == "heavy_sync",
            JobRun.job_kind.in_(("date_sync", "parent_sync", "finalize", "product_sync")),
            JobRun.job_name.in_(("product_sync", "collect_and_settle", "settlement_rebuild", "manual_sync",
                                "collect_once", "manual_backend_aweme_export", "settlement_compaction", "refund_evidence_replay"))),
    ).limit(1))
    if busy:
        raise ConversionError("source writer running or awaiting retry")


def convert_product_types(
    session: Session, *, actor: str, change_reason: str, idempotency_key: str,
    apply: bool = False, preview_hash: str | None = None,
    participating_only: bool = False,
) -> dict[str, Any]:
    """Review exact legacy-scope or evidenced participating SKUs, then apply.

    The hash binds request identity and full current catalog snapshots, including
    no-op targets. SQLite is for isolated tests; production CLI apply requires
    PostgreSQL's table/advisory locks. No settlement rebuild is ever scheduled.
    """
    for name, value, limit in (("actor", actor, 128), ("change_reason", change_reason, 512),
                               ("idempotency_key", idempotency_key, 256)):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ConversionError(f"invalid {name}")
    if apply and (not isinstance(preview_hash, str) or not re.fullmatch("[0-9a-f]{64}", preview_hash)):
        raise ConversionError("apply requires the exact preview hash")
    if session.in_transaction():
        raise ConversionError("use a fresh session without an existing transaction")
    operation = PARTICIPATING_OPERATION if participating_only else OPERATION
    request_hash = _digest({"operation": operation, "actor": actor, "change_reason": change_reason,
                            "scope": None if participating_only else JINGCHENG_PRODUCT_SCOPE, "type": JINGCHENG_PRODUCT_TYPE})
    audit_id = "catalog-type-" + sha256(idempotency_key.encode("utf-8")).hexdigest()
    with session.begin():
        if apply:
            _fence(session)
            if participating_only and session.get_bind().dialect.name == "postgresql":
                session.execute(text("LOCK TABLE sku_fee_rule IN SHARE ROW EXCLUSIVE MODE"))
        actor_role, actor_user_id = _actor(session, actor, lock=apply)
        replay = session.get(AccountPermissionAuditLog, audit_id)
        if replay is not None:
            stored = replay.after_json
            if replay.action != operation or stored.get("request_hash") != request_hash:
                raise ConversionError("idempotency key reused with different request")
            if apply and stored.get("preview_hash") != preview_hash:
                raise ConversionError("idempotency replay requires the original preview hash")
            return {**stored, "replayed": True}
        evidence_as_of = datetime.now(timezone.utc)
        rules = participation_rules(session, as_of=evidence_as_of) if participating_only else {}
        query = select(DimSkuProductRule).where(
            DimSkuProductRule.sku_id.in_(tuple(rules)) if participating_only else
            DimSkuProductRule.product_scope == JINGCHENG_PRODUCT_SCOPE,
        ).order_by(DimSkuProductRule.sku_id)
        if apply:
            query = query.with_for_update()
        targets = list(session.scalars(query))
        before = [_catalog_snapshot(row) for row in targets]
        rule_evidence = [{column.key: _plain(getattr(rule, column.key))
                         for column in inspect(type(rule)).column_attrs}
                        for sku_rules in rules.values() for rule in sku_rules]
        fingerprint_input = {"request_hash": request_hash, "targets": before}
        if participating_only:
            fingerprint_input["participation_rules"] = rule_evidence
        fingerprint = _digest(fingerprint_input)
        groups = Counter(row.product_type for row in targets)
        diff = [{"sku_id": row.sku_id, "product_id": row.product_id,
                 "product_scope": row.product_scope, "product_type_before": row.product_type,
                 "product_type_after": maintained_type(row, row.product_type, rules)
                    if participating_only else JINGCHENG_PRODUCT_TYPE,
                 "changed": row.product_type != (maintained_type(row, row.product_type, rules)
                    if participating_only else JINGCHENG_PRODUCT_TYPE)} for row in targets]
        changed_count = sum(item["changed"] for item in diff)
        report = {
            "operation": operation, "scope": None if participating_only else JINGCHENG_PRODUCT_SCOPE,
            "product_type": None if participating_only else JINGCHENG_PRODUCT_TYPE, "preview_hash": fingerprint,
            "request_hash": request_hash, "actor": actor, "actor_role": actor_role,
            "change_reason": change_reason, "target_count": len(targets),
            "changed_count": changed_count, "unchanged_count": len(targets) - changed_count,
            "before_groups": [{"product_type": key, "count": count} for key, count in sorted(groups.items())],
            "after_groups": [{"product_type": key, "count": count} for key, count in sorted(
                Counter(item["product_type_after"] for item in diff).items())],
            "diff": diff, "applied": False, "replayed": False, "rebuild_queued": False,
        }
        if participating_only:
            known = {row.sku_id for row in targets}
            unproven = list(session.scalars(select(DimSkuProductRule).where(
                DimSkuProductRule.sku_id.not_in(tuple(rules))).order_by(DimSkuProductRule.sku_id)))
            report.update(selection="published-positive-rule-sku", evidence_as_of=evidence_as_of.isoformat(),
                product_types=["售后官方", JINGCHENG_PRODUCT_TYPE], participation_rules=rule_evidence,
                official_count=sum(item["product_type_after"] == "售后官方" for item in diff),
                official_unchanged_count=sum(item["product_type_before"] == item["product_type_after"] == "售后官方" for item in diff),
                converted_to_jingcheng_count=sum(item["changed"] and item["product_type_after"] == JINGCHENG_PRODUCT_TYPE for item in diff),
                converted_to_official_count=sum(item["changed"] and item["product_type_after"] == "售后官方" for item in diff),
                missing_catalog_sku_ids=sorted(set(rules) - known),
                unproven_skus=[{"sku_id": row.sku_id, "product_id": row.product_id,
                    "product_scope": row.product_scope, "product_type": row.product_type,
                    "reason": "NO_PUBLISHED_EFFECTIVE_POSITIVE_RULE"} for row in unproven])
        if not apply:
            return report
        if preview_hash != fingerprint:
            raise ConversionError("preview hash stale: exact target set or catalog changed")
        now = datetime.now(timezone.utc)
        expected_types = {item["sku_id"]: item["product_type_after"] for item in diff}
        for row in targets:
            if row.product_type != expected_types[row.sku_id]:
                row.product_type = expected_types[row.sku_id]
                row.manual_modified_at, row.manual_modified_by = now, actor
        report["applied"] = True
        session.add(AccountPermissionAuditLog(
            audit_id=audit_id, action=operation, result="success", actor_user_id=actor_user_id,
            actor_username=actor, actor_role=actor_role, target_user_id=None, target_username=None,
            before_json={"catalog": before}, after_json=report, created_at=now,
        ))
        session.flush()
        # Verify persisted classification before committing; the audit shares
        # this transaction, so a flush/readback/audit failure rolls it all back.
        session.expire_all()
        after = list(session.scalars(query.execution_options(populate_existing=True)))
        if [row.sku_id for row in after] != [item["sku_id"] for item in diff] or any(
            row.product_type != expected_types[row.sku_id] for row in after
        ):
            raise ConversionError("catalog readback differs from the reviewed conversion")
        return report


def _require_report_outside_git(path: Path) -> None:
    """Without Git, reject any physical repository boundary or unknown metadata."""
    error = "Git unavailable: cannot verify report is outside Git"
    if any(name in os.environ for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")):
        raise ConversionError(error)

    def present(marker: Path) -> bool:
        try:
            marker.lstat()  # A .git file or dangling link is also a repository hint.
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ConversionError(error) from exc
        return True

    for directory in path.parents:
        if present(directory / ".git") or all(
            present(directory / name) for name in ("HEAD", "objects", "refs")
        ):
            raise ConversionError(error)


def _private_report_path(path: Path) -> Path:
    path = path.resolve(strict=False)
    probe = path.parent
    try:
        result = subprocess.run(["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        _require_report_outside_git(path)
        return path
    if result.returncode == 0:
        repository = Path(result.stdout.strip())
        relative = path.relative_to(repository)
        tracked = subprocess.run(["git", "-C", str(repository), "ls-files", "--error-unmatch", "--", str(relative)], capture_output=True)
        ignored = subprocess.run(["git", "-C", str(repository), "check-ignore", "--quiet", "--", str(relative)])
        if tracked.returncode == 0 or ignored.returncode != 0:
            raise ConversionError("report must be outside Git or in an ignored, untracked path")
    return path


def main() -> int:
    """Write a private preview by default; apply needs its exact hash."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="New private JSON report; never overwritten")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--change-reason", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--preview-hash")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--participating-skus", action="store_true",
        help="DYDATA-104 Oct30: select exact SKUs with formal published participation rules; preserve official types")
    args = parser.parse_args()
    try:
        report_path = _private_report_path(args.report)
        engine = make_engine()
        if args.apply and engine.dialect.name != "postgresql":
            raise ConversionError("CLI apply requires PostgreSQL locking")
        with report_path.open("x", encoding="utf-8") as output:
            with Session(engine, autoflush=False) as session:
                report = convert_product_types(
                    session, actor=args.actor, change_reason=args.change_reason,
                    idempotency_key=args.idempotency_key, apply=args.apply, preview_hash=args.preview_hash,
                    participating_only=args.participating_skus,
                )
            json.dump(report, output, ensure_ascii=False, indent=2)
        print(json.dumps({key: report[key] for key in (
            "applied", "replayed", "target_count", "changed_count", "preview_hash",
        )}))
        return 0
    except (ConversionError, SQLAlchemyError, OSError) as exc:
        # Database diagnostics can contain connection strings and parameters.
        print(str(exc) if isinstance(exc, ConversionError) else f"conversion failed ({type(exc).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
