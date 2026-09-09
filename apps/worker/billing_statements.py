"""Create pending bills from an explicit frozen publication source bundle.

This module never reconstructs published sources from mutable raw/current tables.
The caller owns the transaction and must supply the bundle captured for this
generation. Durable capture/recovery belongs to the publication coordinator.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DimStore, FinanceOperationAudit, InvoiceRecord, PromotionInvoiceAllocation,
    SettlementDispute, StoreFinanceProfile,
    SettlementMonthlyOverlay, SettlementProjectionActive,
    SettlementProjectionGeneration, SettlementStatement,
    SettlementStatementConfirmation, SettlementStatementEntry, SettlementStatementLine,
)
from apps.worker.projection_lineage import resolve_projection_partitions
from apps.worker.settlement import (
    StatementSource, _apply_and_validate_statement_totals, _lock_settlement_slot,
    _projection_dimensions, _stable_business_id,
)


def generate_pending_statements(
    session: Session, *, generation_id: str, source_job_id: str | None = None,
    sources: Sequence[StatementSource] | None = None,
    slots: Sequence[tuple[str, str]] = (),
) -> dict[str, int]:
    """Generate immutable pending bills, without commits or automatic confirmations.

    The confirmation API and this writer lock the same statement row before
    checking current version/financial facts. Missing frozen input fails closed.
    """
    stats = {"generated": 0, "skipped": 0, "blocked": 0, "created": 0,
             "unchanged": 0, "protected": 0}
    with session.begin_nested():
        active = session.scalar(select(SettlementProjectionActive).where(
            SettlementProjectionActive.projection_name == "settlement",
        ).with_for_update().execution_options(populate_existing=True))
        generation = session.get(SettlementProjectionGeneration, generation_id, populate_existing=True)
        if (active is None or active.generation_id != generation_id or generation is None
                or generation.state != "published"
                or (source_job_id is not None and generation.source_job_id != source_job_id)):
            raise ValueError("billing requires the current published generation and source job")
        if sources is None:
            stats["blocked"] = 1
            _audit_outcome(session, generation_id, source_job_id, generation_id, "FROZEN_SOURCES_MISSING")
            session.flush()
            return stats
        grouped: dict[tuple[str, str], list[StatementSource]] = defaultdict(list)
        for store_id, month in slots:
            if not store_id or month < "2026-08":
                raise ValueError("invalid frozen billing slot")
            grouped[(store_id, month)] = []
        identities: set[tuple[int, str]] = set()
        for source in sources:
            identity = (source.source_type, source.source_record_id)
            if (source.posting_month < "2026-08" or source.fee_direction not in (1, 2)
                    or source.source_type not in (1, 2) or identity in identities):
                raise ValueError("invalid or duplicate frozen billing source")
            identities.add(identity)
            grouped[(source.store_id, source.posting_month)].append(source)
        resolutions = resolve_projection_partitions(
            session, artifact="monthly", partition_keys=sorted({key[1] for key in grouped}),
            pinned_generation_id=generation_id,
        )
        retained_originals = {
            row.source_record_id if row.source_type == 1 else row.original_fee_result_id
            for row in sources
        }
        for (store_id, month), rows in sorted(grouped.items()):
            _lock_settlement_slot(session, store_id, month)
            current = session.scalar(select(SettlementStatement).where(
                SettlementStatement.store_id == store_id,
                SettlementStatement.statement_month == month,
                SettlementStatement.is_current.is_(True),
            ).with_for_update().execution_options(populate_existing=True))
            if current is None and session.scalar(select(SettlementStatement.id).where(
                SettlementStatement.store_id == store_id,
                SettlementStatement.statement_month == month,
            ).limit(1)) is not None:
                stats["blocked"] += 1
                _audit_outcome(session, generation_id, source_job_id, f"{store_id}:{month}", "CURRENT_STATEMENT_MISSING")
                continue
            if current is not None and _protected(session, current):
                original_ids = set(session.scalars(select(SettlementStatementEntry.source_record_id).where(
                    SettlementStatementEntry.statement_id == current.statement_id,
                    SettlementStatementEntry.source_type == 1,
                )))
                if not original_ids.issubset(retained_originals):
                    # A user may confirm after calculation committed but before
                    # publication. Retaining that bill plus migrated sources in
                    # a new bill would duplicate the same economic amount.
                    stats["blocked"] += 1
                    _audit_outcome(session, generation_id, source_job_id, current.statement_id,
                                   "PROTECTED_BILLING_SOURCE_DRIFT")
                stats["protected"] += 1
                stats["skipped"] += 1
                _audit_outcome(session, generation_id, source_job_id, current.statement_id, "FINANCIAL_FACTS_PROTECTED")
                continue
            resolution = resolutions[month]
            if resolution.source_kind == "tombstone" and not rows:
                projected = []
            elif resolution.source_kind != "overlay":
                raise ValueError("immutable monthly projection required for billing")
            else:
                projected = list(session.scalars(select(SettlementMonthlyOverlay).where(
                    SettlementMonthlyOverlay.generation_id == resolution.actual_data_generation_id,
                    SettlementMonthlyOverlay.month == month,
                    SettlementMonthlyOverlay.store_id == store_id,
                    SettlementMonthlyOverlay.tombstone.is_(False),
                )))
            _validate_projection(rows, projected)
            payload_hash = hashlib.sha256(json.dumps(
                [asdict(row) for row in sorted(rows, key=lambda row: (row.source_type, row.source_record_id))],
                sort_keys=True, default=str, separators=(",", ":"),
            ).encode()).hexdigest()
            if current is not None:
                audit = session.scalar(select(FinanceOperationAudit).where(
                    FinanceOperationAudit.target_id == current.statement_id,
                    FinanceOperationAudit.operation_type == "GENERATE_PENDING_STATEMENT",
                    FinanceOperationAudit.request_payload_sha256 == payload_hash,
                ))
                if audit is not None:
                    stats["unchanged"] += 1
                    stats["skipped"] += 1
                    continue
            store = session.get(DimStore, store_id)
            if store is None:
                raise ValueError("billing source has no store")
            basic_profile = session.scalar(select(StoreFinanceProfile).where(
                StoreFinanceProfile.store_id == store_id,
                StoreFinanceProfile.profile_type == 1,
                StoreFinanceProfile.is_current.is_(True),
                StoreFinanceProfile.is_tombstone.is_(False),
            ).order_by(StoreFinanceProfile.version_no.desc(), StoreFinanceProfile.profile_id.desc()).limit(1))
            statement = SettlementStatement(
                statement_id=_stable_business_id("pending-bill", generation_id, store_id, month),
                store_id=store_id, statement_month=month,
                version_no=current.version_no + 1 if current is not None else 1,
                supersedes_statement_id=current.statement_id if current is not None else None,
                is_current=False, statement_status=2,
                store_name_snapshot=current.store_name_snapshot if current is not None else store.store_name,
                sap_code_snapshot=current.sap_code_snapshot if current is not None else basic_profile.sap_code if basic_profile else None,
                store_snapshot_status=current.store_snapshot_status if current is not None else "LIVE_CAPTURED",
                store_snapshot_profile_id=current.store_snapshot_profile_id if current is not None else basic_profile.profile_id if basic_profile else None,
            )
            session.add(statement)
            session.flush()
            _write_sources(session, statement, rows)
            session.flush()
            _apply_and_validate_statement_totals(session, statement)
            if current is not None:
                current.is_current = False
                session.flush()
            statement.is_current = True
            session.add(FinanceOperationAudit(
                audit_id=_stable_business_id("pending-bill-audit", statement.statement_id),
                operation_type="GENERATE_PENDING_STATEMENT", target_type="SETTLEMENT_STATEMENT",
                target_id=statement.statement_id, operator_id="settlement-worker", operator_role=1,
                after_snapshot={"generationId": generation_id, "sourceJobId": source_job_id,
                                "status": "COMPUTED", "versionNo": statement.version_no,
                                "previousStatementId": statement.supersedes_statement_id,
                                "sourceCount": len(rows)},
                result_status=1, request_id=source_job_id or generation_id,
                request_payload_sha256=payload_hash,
            ))
            stats["generated"] += 1
            stats["created"] += 1
        session.flush()
    return stats


def _audit_outcome(session: Session, generation_id: str, source_job_id: str | None,
                   target_id: str, reason: str) -> None:
    audit_id = _stable_business_id("pending-bill-outcome", generation_id, target_id, reason)
    if session.scalar(select(FinanceOperationAudit.id).where(FinanceOperationAudit.audit_id == audit_id)) is not None:
        return
    session.add(FinanceOperationAudit(
        audit_id=audit_id, operation_type="PENDING_STATEMENT_GENERATION_BLOCKED",
        target_type="SETTLEMENT_STATEMENT", target_id=target_id,
        operator_id="settlement-worker", operator_role=1, result_status=2,
        request_id=source_job_id or generation_id,
        after_snapshot={"generationId": generation_id, "sourceJobId": source_job_id, "reason": reason},
    ))


def _protected(session: Session, statement: SettlementStatement) -> bool:
    if statement.statement_status in (3, 4) or statement.confirmed_at or statement.locked_at:
        return True
    checks = (
        select(SettlementDispute.id).where(
            SettlementDispute.store_id == statement.store_id,
            SettlementDispute.statement_month == statement.statement_month,
            (SettlementDispute.status.in_((1, 2, 3, 4))) | SettlementDispute.result_statement_id.is_not(None),
        ),
        select(SettlementStatementConfirmation.id).where(SettlementStatementConfirmation.statement_id == statement.statement_id),
        select(PromotionInvoiceAllocation.id).where(PromotionInvoiceAllocation.store_id == statement.store_id,
                                                  PromotionInvoiceAllocation.statement_month == statement.statement_month),
        select(InvoiceRecord.id).where(InvoiceRecord.store_id == statement.store_id,
                                      InvoiceRecord.statement_month == statement.statement_month),
    )
    return any(session.scalar(query.limit(1)) is not None for query in checks)


def _validate_projection(rows: Sequence[StatementSource], projected: Sequence[SettlementMonthlyOverlay]) -> None:
    expected = {}
    for row in projected:
        for direction, prefix in ((1, "promotion"), (2, "management")):
            expected[(direction, row.product_scope, row.product_type)] = (
                getattr(row, f"{prefix}_base_cent"), getattr(row, f"{prefix}_original_fee_cent"),
                getattr(row, f"{prefix}_adjustment_fee_cent"),
            )
    actual = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        for scope, product_type in _projection_dimensions(row.product_scope, row.product_type):
            amounts = actual[(row.fee_direction, scope, product_type)]
            amounts[0] += row.base_amount_cent
            amounts[row.source_type] += row.fee_amount_cent
    keys = set(expected) | set(actual)
    if any(tuple(actual.get(key, (0, 0, 0))) != expected.get(key, (0, 0, 0)) for key in keys):
        raise ValueError("billing sources do not match published projection")


def _write_sources(session: Session, statement: SettlementStatement, rows: Sequence[StatementSource]) -> None:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.fee_direction, row.product_scope, row.product_type)].append(row)
    snapshot_fields = (
        "order_status", "coupon_status", "product_name", "sku_id", "sku_name",
        "sale_channel", "sale_store_id", "sale_store", "verify_store_id", "verify_store",
        "sale_time", "verify_time", "received_amount_cent", "fee_rate", "refund_at", "adjustment_type",
    )
    for (direction, scope, product_type), line_rows in sorted(grouped.items()):
        line_id = _stable_business_id("pending-bill-line", statement.statement_id, str(direction), scope, product_type)
        originals = [row for row in line_rows if row.source_type == 1]
        adjustments = [row for row in line_rows if row.source_type == 2]
        session.add(SettlementStatementLine(
            statement_line_id=line_id, statement_id=statement.statement_id,
            fee_direction=direction, product_scope=scope, product_type=product_type,
            original_entry_count=len(originals), adjustment_entry_count=len(adjustments),
            original_base_cent=sum(row.base_amount_cent for row in originals),
            adjustment_base_cent=sum(row.base_amount_cent for row in adjustments),
            net_base_cent=sum(row.base_amount_cent for row in line_rows),
            original_fee_cent=sum(row.fee_amount_cent for row in originals),
            adjustment_fee_cent=sum(row.fee_amount_cent for row in adjustments),
            net_fee_cent=sum(row.fee_amount_cent for row in line_rows),
        ))
        for row in line_rows:
            session.add(SettlementStatementEntry(
                statement_entry_id=_stable_business_id("pending-bill-entry", statement.statement_id, str(row.source_type), row.source_record_id),
                statement_id=statement.statement_id, statement_line_id=line_id,
                source_type=row.source_type, source_record_id=row.source_record_id,
                original_fee_result_id=row.original_fee_result_id, coupon_id=row.coupon_id,
                order_id=row.order_id, fee_direction=row.fee_direction,
                original_business_month=row.original_business_month, statement_posting_month=row.posting_month,
                product_scope=row.product_scope, product_type=row.product_type,
                base_amount_cent=row.base_amount_cent, fee_amount_cent=row.fee_amount_cent,
                rule_version=row.rule_version,
                **{f"{field}_snapshot": getattr(row, field) for field in snapshot_fields},
            ))
