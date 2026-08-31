from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    and_,
    case,
    delete,
    func,
    insert,
    literal,
    or_,
    select,
    text,
    true,
    union,
    union_all,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    AggStoreRanking,
    DataQualityIssue,
    DimAwemeAccount,
    DimNonCommissionOwnerAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    DouyinRefundEvent,
    InvoiceRecord,
    JobImpact,
    PromotionInvoiceAllocation,
    RawAwemeBinding,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementOrderDetail,
    SettlementCarryforwardApplication,
    SettlementCarryforwardSource,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementMonthlyOverlay,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementRankingOverlay,
    SettlementScopeRule,
    SettlementStatement,
    SettlementStatementEntry,
    SettlementStatementLine,
    SkuFeeRule,
    StoreFinanceProfile,
    utcnow,
)
from apps.api.dy_api.rule_utils import normalize_owner_account_name
from apps.worker.projection_lineage import resolve_projection_partitions
from apps.worker.repositories import finish_job_run, start_job_run, upsert_data_quality_issue


VALID_VERIFY_STATUSES = {"1", "valid", "verified", "success", "fulfilled", "used"}
CANCELLED_VERIFY_STATUSES = {"2", "cancelled", "canceled", "revoked", "reversed", "refunded"}
INACTIVE_BINDING_STATUSES = {
    "inactive",
    "unbound",
    "unbind",
    "failed",
    "rejected",
    "已解绑",
    "绑定失效",
    "审核失败",
    "绑定已拒绝",
}
REFUND_EXCLUDED_STATUSES = {
    "cancelled",
    "canceled",
    "closed",
    "refund",
    "refunded",
    "refunding",
    "reversed",
}
FORMAL_SETTLEMENT_START = date(2026, 8, 1)
PROMOTION_FEE = 1
MANAGEMENT_FEE = 2
ACTIVE_FEE_RULE = 1
ACTIVE_FEE_RESULT = 1
SUPERSEDED_FEE_RESULT = 2
SUCCESSFUL_REFUND = 2
SHANGHAI = ZoneInfo("Asia/Shanghai")
# Keep each captured closure and SQL page bounded independently.
MAX_SETTLEMENT_CLOSURE_VALUES = 64
MAX_SETTLEMENT_IMPACT_BATCH_SIZE = 64
MAX_SETTLEMENT_COUPON_BATCH_SIZE = 100
MAX_SETTLEMENT_PAGE_CARDINALITY = 8192
SETTLEMENT_SPARSE_PROTOCOL = "t343-settlement-sparse-v1"
MAX_SETTLEMENT_SPARSE_MONTHS = 120
_MONTH_KEY_RE = re.compile(r"\d{4}-\d{2}\Z")


@dataclass(frozen=True)
class SettlementStats:
    detail_count: int
    issue_count: int
    ranking_count: int
    monthly_count: int


@dataclass(frozen=True)
class OwnerAccountMatch:
    account_id: str
    store_id: str | None
    binding_status: str | None = None
    match_source: str = "raw_aweme_bindings"


@dataclass(frozen=True)
class DualFeeStats:
    result_count: int
    adjustment_count: int
    blocked_count: int


@dataclass(frozen=True)
class StatementProjectionStats:
    monthly_count: int
    ranking_count: int
    processed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


@dataclass(frozen=True)
class ProjectionManifestSet:
    generation_id: str
    base_generation_id: str
    monthly_partitions: tuple[str, ...]
    ranking_partitions: tuple[str, ...]
    manifest_count: int
    row_count: int
    manifest_checksum: str
    resumed: bool


class LockedSettlementConflict(RuntimeError):
    """An immutable locked statement would be replaced by a sparse rebuild."""


@dataclass
class _SparsePartitionDigest:
    artifact: str
    partition_key: str
    row_count: int = 0
    amount_total_cent: int = 0
    status_counts: dict[str, int] | None = None
    digest: str = ""
    last_key: str | None = None

    @classmethod
    def fresh(cls, artifact: str, partition_key: str) -> "_SparsePartitionDigest":
        return cls(
            artifact=artifact,
            partition_key=partition_key,
            status_counts={},
            digest=hashlib.sha256(_sparse_json({"rows": []})).hexdigest(),
        )

    def add(
        self,
        envelope: Mapping[str, Any],
        *,
        amount: int,
        status: int | None = None,
        last_key: str,
    ) -> None:
        payload = _sparse_json(dict(envelope))
        self.digest = hashlib.sha256(bytes.fromhex(self.digest) + payload).hexdigest()
        self.row_count += 1
        self.amount_total_cent += int(amount)
        if status is not None:
            key = str(status)
            assert self.status_counts is not None
            self.status_counts[key] = self.status_counts.get(key, 0) + 1
        self.last_key = last_key


@dataclass(frozen=True)
class StatementSource:
    source_type: int
    source_record_id: str
    original_fee_result_id: str
    coupon_id: str
    order_id: str
    fee_direction: int
    original_business_month: str
    posting_month: str
    store_id: str
    product_scope: str
    product_type: str
    base_amount_cent: int
    fee_amount_cent: int
    source_amount_cent: int
    rule_version: str
    order_status: str | None = None
    coupon_status: str | None = None
    product_name: str | None = None
    sku_id: str | None = None
    sku_name: str | None = None
    sale_channel: str | None = None
    sale_store_id: str | None = None
    sale_store: str | None = None
    verify_store_id: str | None = None
    verify_store: str | None = None
    sale_time: datetime | None = None
    verify_time: datetime | None = None
    received_amount_cent: int | None = None
    fee_rate: Decimal | None = None
    refund_at: datetime | None = None
    adjustment_type: int | None = None


class LocalSettlementResult(dict[str, Any]):
    """Stable, deterministic result returned by the one-coupon kernel."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - normal AttributeError contract
            raise AttributeError(name) from exc


def _sparse_json(value: Any) -> bytes:
    """Return stable UTF-8 JSON for sparse row and checkpoint identities."""

    def normalize(item: Any) -> Any:
        if isinstance(item, datetime):
            if item.tzinfo is not None and item.utcoffset() is not None:
                item = item.astimezone(timezone.utc)
                return item.isoformat().replace("+00:00", "Z")
            return item.isoformat()
        if isinstance(item, date):
            return item.isoformat()
        if isinstance(item, Decimal):
            rendered = format(item, "f")
            return "0" if not rendered or item == 0 else rendered
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        return item

    try:
        return json.dumps(
            normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("sparse projection metadata is not canonical JSON") from exc


def _sparse_identity(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{label} must be a non-empty canonical string")
    return value


def _sparse_month(value: Any, *, label: str = "month") -> str:
    if not isinstance(value, str) or _MONTH_KEY_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must use YYYY-MM")
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM") from exc
    if parsed.strftime("%Y-%m") != value:
        raise ValueError(f"{label} must use canonical YYYY-MM")
    return value


def _sparse_month_range(start: str, end: str) -> tuple[str, ...]:
    start_value = date.fromisoformat(f"{_sparse_month(start)}-01")
    end_value = date.fromisoformat(f"{_sparse_month(end)}-01")
    if start_value > end_value:
        return ()
    values: list[str] = []
    current = start_value
    while current <= end_value:
        values.append(current.strftime("%Y-%m"))
        if len(values) > MAX_SETTLEMENT_SPARSE_MONTHS:
            raise ValueError("settlement sparse cumulative suffix is too large")
        current = date(
            current.year + (1 if current.month == 12 else 0),
            1 if current.month == 12 else current.month + 1,
            1,
        )
    return tuple(values)


def _sparse_cursor(artifact: str, partition_key: str, values: Mapping[str, Any]) -> str:
    return _sparse_json(
        {
            "artifact": artifact,
            "partition_key": partition_key,
            "cursor": dict(values),
        }
    ).decode("utf-8")


def _sparse_generation_manifest_checksum(
    manifests: list[Mapping[str, Any]],
) -> str:
    # Manifest checksums are a shared protocol across legacy roots, sparse
    # generations, and compact heads.  Import lazily so settlement's normal
    # worker import path does not load the bootstrap coordinator.
    from apps.worker.legacy_projection_bootstrap import _manifest_checksum

    return _manifest_checksum(manifests)


def _sparse_base_chain(
    session: Session, base_generation_id: str
) -> tuple[SettlementProjectionGeneration, tuple[str, ...]]:
    base = session.get(SettlementProjectionGeneration, base_generation_id)
    if base is None:
        raise ValueError("base settlement generation does not exist")
    if base.projection_name != "settlement" or base.state != "published":
        raise ValueError("base settlement generation is not published")
    try:
        depth = int(base.lineage_depth)
    except (TypeError, ValueError) as exc:
        raise ValueError("base settlement lineage depth is invalid") from exc
    if depth < 0 or depth >= 64:
        raise ValueError("base settlement lineage depth exceeds the sparse limit")

    generation_ids: list[str] = []
    visited: set[str] = set()
    current: SettlementProjectionGeneration | None = base
    while current is not None:
        if current.generation_id in visited:
            raise ValueError("base settlement lineage contains a cycle")
        visited.add(current.generation_id)
        generation_ids.append(current.generation_id)
        if len(generation_ids) > 65:
            raise ValueError("base settlement lineage exceeds the sparse limit")
        if current.generation_kind == "compact":
            if current.generation_id != base_generation_id:
                raise ValueError("ordinary lineage cannot contain a compact base")
            if current.base_generation_id is not None or current.lineage_depth != 0:
                raise ValueError("compact base settlement metadata is malformed")
            break
        next_id = current.base_generation_id
        if next_id is None:
            break
        current = session.get(SettlementProjectionGeneration, next_id)
        if current is None:
            raise ValueError("base settlement lineage references a missing generation")
        if current.state not in {"published", "superseded"}:
            raise ValueError("base settlement lineage contains an unpublished generation")
    if current is None or current.base_generation_id is not None:
        raise ValueError("base settlement lineage is incomplete")
    if base.generation_kind != "compact" and len(generation_ids) != depth + 1:
        raise ValueError("base settlement lineage depth is inconsistent")
    return base, tuple(generation_ids)


def _sparse_expand_affected_months(
    session: Session, affected_months: Iterable[str]
) -> tuple[str, ...]:
    values = {_sparse_month(value, label="affected month") for value in affected_months}
    if not values:
        raise ValueError("affected_months must not be empty")
    if len(values) > MAX_SETTLEMENT_SPARSE_MONTHS:
        raise ValueError("too many affected settlement months")
    while True:
        rows = session.execute(
            select(
                SettlementFeeAdjustment.original_business_month,
                SettlementFeeAdjustment.adjustment_posting_month,
            )
            .where(
                or_(
                    SettlementFeeAdjustment.original_business_month.in_(values),
                    SettlementFeeAdjustment.adjustment_posting_month.in_(values),
                )
            )
            .distinct()
            .limit(MAX_SETTLEMENT_SPARSE_MONTHS + 1)
        ).all()
        expanded = set(values)
        for original_month, posting_month in rows:
            expanded.add(
                _sparse_month(original_month, label="adjustment original month")
            )
            expanded.add(
                _sparse_month(posting_month, label="adjustment posting month")
            )
        if len(expanded) > MAX_SETTLEMENT_SPARSE_MONTHS:
            raise ValueError("adjustment month closure exceeds sparse limit")
        if expanded == values:
            return tuple(sorted(values))
        values = expanded


def _sparse_latest_authoritative_month(
    session: Session,
    *,
    affected_months: tuple[str, ...],
    base_lineage_ids: tuple[str, ...],
) -> str:
    candidates = set(affected_months)
    scalar_queries = (
        select(func.max(SettlementFeeResult.original_business_month)).join(
            SettlementFeeResultCurrent,
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeResult.fee_result_id,
        ),
        select(func.max(SettlementFeeAdjustment.original_business_month)),
        select(func.max(SettlementFeeAdjustment.adjustment_posting_month)),
        select(func.max(SettlementStatement.statement_month)),
        select(func.max(AggStoreMonthlySettlement.month)),
        select(func.max(AggStoreRanking.period_key)),
    )
    for statement in scalar_queries:
        value = session.scalar(statement)
        if value is not None:
            candidates.add(_sparse_month(value, label="authoritative month"))
    manifest_keys = session.scalars(
        select(SettlementProjectionPartitionManifest.partition_key).where(
            SettlementProjectionPartitionManifest.generation_id.in_(base_lineage_ids),
            SettlementProjectionPartitionManifest.artifact.in_(("monthly", "ranking")),
        )
    )
    for partition_key in manifest_keys:
        value = str(partition_key)
        if value.startswith("monthly:") or value.startswith("cumulative:"):
            value = value.split(":", 1)[1]
        candidates.add(_sparse_month(value, label="base manifest month"))
    return max(candidates)


def _sparse_preflight(
    session: Session,
    *,
    generation_id: str,
    base_generation_id: str,
    affected_months: Iterable[str],
    batch_size: int,
    input_fingerprint: str,
) -> tuple[
    SettlementProjectionGeneration,
    tuple[str, ...],
    tuple[str, ...],
    SettlementProjectionGeneration | None,
]:
    generation_id = _sparse_identity(generation_id, label="generation_id")
    base_generation_id = _sparse_identity(
        base_generation_id, label="base_generation_id"
    )
    if generation_id == base_generation_id:
        raise ValueError("sparse generation cannot reference itself as base")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 400:
        raise ValueError("batch_size must be an integer between 1 and 400")
    if (
        not isinstance(input_fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", input_fingerprint) is None
    ):
        raise ValueError("input_fingerprint must be 64 lowercase hexadecimal characters")
    active = session.get(SettlementProjectionActive, "settlement")
    if active is None or active.generation_id != base_generation_id:
        raise ValueError("active settlement pointer does not match sparse base")
    base, lineage_ids = _sparse_base_chain(session, base_generation_id)
    expanded = _sparse_expand_affected_months(session, affected_months)
    locked = session.scalar(
        select(SettlementStatement.statement_id)
        .where(
            SettlementStatement.statement_status == 4,
            SettlementStatement.statement_month.in_(expanded),
        )
        .order_by(SettlementStatement.statement_month, SettlementStatement.statement_id)
        .limit(1)
    )
    if locked is not None:
        raise LockedSettlementConflict(
            f"affected settlement month contains locked statement: {locked}"
        )
    latest = _sparse_latest_authoritative_month(
        session,
        affected_months=expanded,
        base_lineage_ids=lineage_ids,
    )
    cumulative_start = max(min(expanded), FORMAL_SETTLEMENT_START.strftime("%Y-%m"))
    cumulative_months = _sparse_month_range(cumulative_start, max(latest, cumulative_start))
    existing = session.get(SettlementProjectionGeneration, generation_id)
    duplicate_fingerprint = session.scalar(
        select(SettlementProjectionGeneration.generation_id).where(
            SettlementProjectionGeneration.input_fingerprint == input_fingerprint,
            SettlementProjectionGeneration.generation_id != generation_id,
        )
    )
    if duplicate_fingerprint is not None:
        raise ValueError("input_fingerprint already belongs to another generation")
    if existing is not None:
        if (
            existing.projection_name != "settlement"
            or existing.generation_kind != "lineage"
            or existing.base_generation_id != base_generation_id
            or existing.input_fingerprint != input_fingerprint
            or existing.lineage_depth != int(base.lineage_depth) + 1
            or existing.state not in {"staging", "ready", "published"}
        ):
            raise ValueError("existing sparse generation metadata conflicts")
    return base, expanded, cumulative_months, existing


def _active_adjustment_condition() -> Any:
    """Keep only ordinary adjustments and the current carryforward version."""

    is_versioned = select(SettlementCarryforwardApplication.id).where(
        SettlementCarryforwardApplication.target_adjustment_id
        == SettlementFeeAdjustment.adjustment_id
    ).exists()
    is_current = select(SettlementCarryforwardApplication.id).where(
        SettlementCarryforwardApplication.target_adjustment_id
        == SettlementFeeAdjustment.adjustment_id,
        SettlementCarryforwardApplication.is_current.is_(True),
    ).exists()
    return or_(~is_versioned, is_current)


def _sparse_authority_relation(months: tuple[str, ...]) -> Any:
    result_store = case(
        (SettlementFeeResult.fee_direction == PROMOTION_FEE, SettlementFeeResult.sale_store_id),
        else_=SettlementFeeResult.verify_store_id,
    )
    result_rows = (
        select(
            literal("result").label("source_kind"),
            SettlementFeeResult.fee_result_id.label("source_id"),
            SettlementFeeResult.original_business_month.label("month"),
            result_store.label("store_id"),
            func.coalesce(func.nullif(SettlementFeeResult.product_scope, ""), "all").label(
                "source_product_scope"
            ),
            func.coalesce(func.nullif(SettlementFeeResult.product_type, ""), "all").label(
                "source_product_type"
            ),
            SettlementFeeResult.fee_direction.label("fee_direction"),
            SettlementFeeResult.order_id.label("order_id"),
            SettlementFeeResult.source_amount_cent.label("source_amount_cent"),
            SettlementFeeResult.fee_base_cent.label("base_amount_cent"),
            SettlementFeeResult.fee_amount_cent.label("fee_amount_cent"),
        )
        .join(
            SettlementFeeResultCurrent,
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeResult.fee_result_id,
        )
        .where(SettlementFeeResult.original_business_month.in_(months))
    )
    original_store = case(
        (SettlementFeeAdjustment.fee_direction == PROMOTION_FEE, SettlementFeeResult.sale_store_id),
        else_=SettlementFeeResult.verify_store_id,
    )
    adjustment_rows = (
        select(
            literal("adjustment").label("source_kind"),
            SettlementFeeAdjustment.adjustment_id.label("source_id"),
            SettlementFeeAdjustment.adjustment_posting_month.label("month"),
            original_store.label("store_id"),
            func.coalesce(func.nullif(SettlementFeeResult.product_scope, ""), "all").label(
                "source_product_scope"
            ),
            func.coalesce(func.nullif(SettlementFeeResult.product_type, ""), "all").label(
                "source_product_type"
            ),
            SettlementFeeAdjustment.fee_direction.label("fee_direction"),
            SettlementFeeAdjustment.order_id.label("order_id"),
            literal(0).label("source_amount_cent"),
            SettlementFeeAdjustment.adjustment_base_cent.label("base_amount_cent"),
            SettlementFeeAdjustment.adjustment_fee_cent.label("fee_amount_cent"),
        )
        .join(
            SettlementFeeResult,
            SettlementFeeResult.fee_result_id
            == SettlementFeeAdjustment.original_fee_result_id,
        )
        .where(
            SettlementFeeAdjustment.adjustment_posting_month.in_(months),
            _active_adjustment_condition(),
        )
    )
    source = union_all(result_rows, adjustment_rows).subquery("sparse_authority")

    common = (
        source.c.source_kind,
        source.c.source_id,
        source.c.month,
        source.c.store_id,
        source.c.fee_direction,
        source.c.order_id,
        source.c.source_amount_cent,
        source.c.base_amount_cent,
        source.c.fee_amount_cent,
    )
    expanded = union(
        select(*common, literal("all").label("product_scope"), literal("all").label("product_type")),
        select(
            *common,
            literal("all").label("product_scope"),
            source.c.source_product_type.label("product_type"),
        ),
        select(
            *common,
            source.c.source_product_scope.label("product_scope"),
            literal("all").label("product_type"),
        ),
        select(
            *common,
            source.c.source_product_scope.label("product_scope"),
            source.c.source_product_type.label("product_type"),
        ),
    ).subquery("sparse_authority_dimensions")
    return expanded


def _sparse_monthly_query(month: str) -> Any:
    source = _sparse_authority_relation((month,))
    original_promotion = and_(
        source.c.source_kind == "result", source.c.fee_direction == PROMOTION_FEE
    )
    original_management = and_(
        source.c.source_kind == "result", source.c.fee_direction == MANAGEMENT_FEE
    )
    adjustment_promotion = and_(
        source.c.source_kind == "adjustment",
        source.c.fee_direction == PROMOTION_FEE,
    )
    adjustment_management = and_(
        source.c.source_kind == "adjustment",
        source.c.fee_direction == MANAGEMENT_FEE,
    )
    statement_status = func.coalesce(
        select(SettlementStatement.statement_status)
        .where(
            SettlementStatement.store_id == source.c.store_id,
            SettlementStatement.statement_month == source.c.month,
        )
        .limit(1)
        .scalar_subquery(),
        1,
    )
    return (
        select(
            source.c.month,
            source.c.store_id,
            source.c.product_scope,
            source.c.product_type,
            func.count(
                func.distinct(case((original_promotion, source.c.order_id), else_=None))
            ).label("sales_order_count"),
            func.coalesce(
                func.sum(case((original_promotion, source.c.source_amount_cent), else_=0)),
                0,
            ).label("sales_amount_cent"),
            func.count(
                func.distinct(case((original_management, source.c.order_id), else_=None))
            ).label("verified_order_count"),
            func.coalesce(
                func.sum(case((original_management, source.c.source_amount_cent), else_=0)),
                0,
            ).label("verified_amount_cent"),
            func.coalesce(
                func.sum(
                    case(
                        (source.c.fee_direction == PROMOTION_FEE, source.c.base_amount_cent),
                        else_=0,
                    )
                ),
                0,
            ).label("promotion_base_cent"),
            func.coalesce(
                func.sum(case((original_promotion, source.c.fee_amount_cent), else_=0)),
                0,
            ).label("promotion_original_fee_cent"),
            func.coalesce(
                func.sum(case((adjustment_promotion, source.c.fee_amount_cent), else_=0)),
                0,
            ).label("promotion_adjustment_fee_cent"),
            func.coalesce(
                func.sum(
                    case(
                        (source.c.fee_direction == MANAGEMENT_FEE, source.c.base_amount_cent),
                        else_=0,
                    )
                ),
                0,
            ).label("management_base_cent"),
            func.coalesce(
                func.sum(case((original_management, source.c.fee_amount_cent), else_=0)),
                0,
            ).label("management_original_fee_cent"),
            func.coalesce(
                func.sum(case((adjustment_management, source.c.fee_amount_cent), else_=0)),
                0,
            ).label("management_adjustment_fee_cent"),
            statement_status.label("statement_status"),
        )
        .group_by(
            source.c.month,
            source.c.store_id,
            source.c.product_scope,
            source.c.product_type,
        )
        .order_by(
            source.c.store_id,
            source.c.product_scope,
            source.c.product_type,
        )
    )


def _sparse_monthly_values(
    row: Mapping[str, Any], *, generation_id: str, base_generation_id: str
) -> dict[str, Any]:
    month = _sparse_month(row.get("month"), label="monthly source month")
    store_id = _sparse_identity(row.get("store_id"), label="monthly source store_id")
    product_scope = _sparse_identity(
        row.get("product_scope"), label="monthly product_scope"
    )
    product_type = _sparse_identity(
        row.get("product_type"), label="monthly product_type"
    )
    status = int(row.get("statement_status") or 1)
    if status not in {1, 2, 3, 4}:
        raise ValueError("monthly statement status is invalid")
    promotion_original = int(row.get("promotion_original_fee_cent") or 0)
    promotion_adjustment = int(row.get("promotion_adjustment_fee_cent") or 0)
    management_original = int(row.get("management_original_fee_cent") or 0)
    management_adjustment = int(row.get("management_adjustment_fee_cent") or 0)
    values: dict[str, Any] = {
        "generation_id": generation_id,
        "base_generation_id": base_generation_id,
        "month": month,
        "store_id": store_id,
        "product_scope": product_scope,
        "product_type": product_type,
        "partition_key": month,
        "sales_order_count": int(row.get("sales_order_count") or 0),
        "sales_amount_cent": int(row.get("sales_amount_cent") or 0),
        "verified_order_count": int(row.get("verified_order_count") or 0),
        "verified_amount_cent": int(row.get("verified_amount_cent") or 0),
        "promotion_base_cent": int(row.get("promotion_base_cent") or 0),
        "promotion_original_fee_cent": promotion_original,
        "promotion_adjustment_fee_cent": promotion_adjustment,
        "promotion_net_fee_cent": promotion_original + promotion_adjustment,
        "management_base_cent": int(row.get("management_base_cent") or 0),
        "management_original_fee_cent": management_original,
        "management_adjustment_fee_cent": management_adjustment,
        "management_net_fee_cent": management_original + management_adjustment,
        "statement_status": status,
        "projection_run_id": generation_id,
        "estimated_receivable_commission_cent": promotion_original
        + promotion_adjustment,
        "commissionable_total_cent": int(row.get("promotion_base_cent") or 0),
        "estimated_payable_commission_cent": management_original
        + management_adjustment,
        "tombstone": False,
    }
    values["checksum"] = hashlib.sha256(_sparse_json(values)).hexdigest()
    return values


def _sparse_monthly_envelope(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: values[key]
        for key in (
            "month",
            "store_id",
            "product_scope",
            "product_type",
            "sales_order_count",
            "sales_amount_cent",
            "verified_order_count",
            "verified_amount_cent",
            "promotion_base_cent",
            "promotion_original_fee_cent",
            "promotion_adjustment_fee_cent",
            "promotion_net_fee_cent",
            "management_base_cent",
            "management_original_fee_cent",
            "management_adjustment_fee_cent",
            "management_net_fee_cent",
            "statement_status",
            "projection_run_id",
        )
    }


def _sparse_manifest_values(
    *,
    generation_id: str,
    base_generation_id: str,
    artifact: str,
    partition_key: str,
    digest: _SparsePartitionDigest,
) -> dict[str, Any]:
    owned = digest.row_count > 0
    return {
        "generation_id": generation_id,
        "artifact": artifact,
        "partition_key": partition_key,
        "owner_state": "owned" if owned else "tombstone",
        "source_kind": "overlay" if owned else "tombstone",
        "data_generation_id": generation_id if owned else None,
        "reference_head_generation_id": None,
        "base_generation_id": base_generation_id,
        "row_count": digest.row_count,
        "amount_total_cent": digest.amount_total_cent,
        "status_counts_json": {
            key: digest.status_counts[key]
            for key in sorted(digest.status_counts or {})
        },
        "checksum": digest.digest,
        "last_key": digest.last_key,
    }


def _sparse_assert_writable(
    session: Session, *, generation_id: str, base_generation_id: str
) -> SettlementProjectionGeneration:
    generation = session.get(SettlementProjectionGeneration, generation_id)
    if generation is None or generation.state != "staging":
        raise ValueError("sparse settlement generation is not writable")
    active = session.get(SettlementProjectionActive, "settlement")
    if active is None or active.generation_id != base_generation_id:
        raise ValueError("active settlement pointer changed during sparse build")
    return generation


def _sparse_write_monthly_partition(
    session_factory: Callable[[], Session],
    *,
    generation_id: str,
    base_generation_id: str,
    month: str,
    batch_size: int,
) -> None:
    with session_factory() as session:
        _sparse_assert_writable(
            session,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
        )
        session.execute(
            delete(SettlementMonthlyOverlay).where(
                SettlementMonthlyOverlay.generation_id == generation_id,
                SettlementMonthlyOverlay.partition_key == month,
            )
        )
        session.execute(
            delete(SettlementProjectionPartitionManifest).where(
                SettlementProjectionPartitionManifest.generation_id == generation_id,
                SettlementProjectionPartitionManifest.artifact == "monthly",
                SettlementProjectionPartitionManifest.partition_key == month,
            )
        )
        digest = _SparsePartitionDigest.fresh("monthly", month)
        pending: list[dict[str, Any]] = []
        result = session.execute(
            _sparse_monthly_query(month).execution_options(yield_per=batch_size)
        ).mappings()
        for raw in result:
            values = _sparse_monthly_values(
                raw,
                generation_id=generation_id,
                base_generation_id=base_generation_id,
            )
            cursor = _sparse_cursor(
                "monthly",
                month,
                {
                    "month": month,
                    "store_id": values["store_id"],
                    "product_scope": values["product_scope"],
                    "product_type": values["product_type"],
                },
            )
            digest.add(
                _sparse_monthly_envelope(values),
                amount=int(values["promotion_net_fee_cent"])
                - int(values["management_net_fee_cent"]),
                status=int(values["statement_status"]),
                last_key=cursor,
            )
            if digest.row_count > MAX_SETTLEMENT_PAGE_CARDINALITY:
                raise ValueError("monthly sparse partition exceeds row limit")
            pending.append(values)
            if len(pending) == batch_size:
                session.execute(insert(SettlementMonthlyOverlay), pending)
                pending.clear()
        if pending:
            session.execute(insert(SettlementMonthlyOverlay), pending)
        session.execute(
            insert(SettlementProjectionPartitionManifest),
            [_sparse_manifest_values(
                generation_id=generation_id,
                base_generation_id=base_generation_id,
                artifact="monthly",
                partition_key=month,
                digest=digest,
            )],
        )
        session.commit()


def _sparse_monthly_ranking_query(generation_id: str, month: str) -> Any:
    return (
        select(
            SettlementMonthlyOverlay.store_id,
            func.coalesce(DimStore.store_name, SettlementMonthlyOverlay.store_id).label(
                "store_name"
            ),
            SettlementMonthlyOverlay.product_scope,
            SettlementMonthlyOverlay.product_type,
            SettlementMonthlyOverlay.sales_order_count,
            SettlementMonthlyOverlay.sales_amount_cent,
            SettlementMonthlyOverlay.verified_order_count,
            SettlementMonthlyOverlay.verified_amount_cent,
            SettlementMonthlyOverlay.promotion_net_fee_cent,
            SettlementMonthlyOverlay.management_net_fee_cent,
        )
        .outerjoin(DimStore, DimStore.store_id == SettlementMonthlyOverlay.store_id)
        .where(
            SettlementMonthlyOverlay.generation_id == generation_id,
            SettlementMonthlyOverlay.partition_key == month,
            or_(
                SettlementMonthlyOverlay.tombstone.is_(False),
                SettlementMonthlyOverlay.tombstone.is_(None),
            ),
        )
        .order_by(
            SettlementMonthlyOverlay.store_id,
            SettlementMonthlyOverlay.product_scope,
            SettlementMonthlyOverlay.product_type,
        )
    )


def _sparse_effective_monthly_relation(
    session: Session,
    *,
    generation_id: str,
    base_generation_id: str,
    affected_months: tuple[str, ...],
    months: tuple[str, ...],
) -> Any | None:
    requested = set(months)
    affected = sorted(requested.intersection(affected_months))
    inherited = sorted(requested.difference(affected_months))
    statements: list[Any] = []

    def overlay_select(source_generation_id: str, source_months: list[str]) -> Any:
        return select(
            SettlementMonthlyOverlay.month.label("month"),
            SettlementMonthlyOverlay.store_id.label("store_id"),
            SettlementMonthlyOverlay.product_scope.label("product_scope"),
            SettlementMonthlyOverlay.product_type.label("product_type"),
            SettlementMonthlyOverlay.sales_order_count.label("sales_order_count"),
            SettlementMonthlyOverlay.sales_amount_cent.label("sales_amount_cent"),
            SettlementMonthlyOverlay.verified_order_count.label("verified_order_count"),
            SettlementMonthlyOverlay.verified_amount_cent.label("verified_amount_cent"),
            SettlementMonthlyOverlay.promotion_net_fee_cent.label(
                "promotion_net_fee_cent"
            ),
            SettlementMonthlyOverlay.management_net_fee_cent.label(
                "management_net_fee_cent"
            ),
        ).where(
            SettlementMonthlyOverlay.generation_id == source_generation_id,
            SettlementMonthlyOverlay.partition_key.in_(source_months),
            or_(
                SettlementMonthlyOverlay.tombstone.is_(False),
                SettlementMonthlyOverlay.tombstone.is_(None),
            ),
        )

    def legacy_select(source_months: list[str]) -> Any:
        return select(
            AggStoreMonthlySettlement.month.label("month"),
            AggStoreMonthlySettlement.store_id.label("store_id"),
            AggStoreMonthlySettlement.product_scope.label("product_scope"),
            AggStoreMonthlySettlement.product_type.label("product_type"),
            AggStoreMonthlySettlement.sales_order_count.label("sales_order_count"),
            AggStoreMonthlySettlement.sales_amount_cent.label("sales_amount_cent"),
            AggStoreMonthlySettlement.verified_order_count.label("verified_order_count"),
            AggStoreMonthlySettlement.verified_amount_cent.label("verified_amount_cent"),
            AggStoreMonthlySettlement.promotion_net_fee_cent.label(
                "promotion_net_fee_cent"
            ),
            AggStoreMonthlySettlement.management_net_fee_cent.label(
                "management_net_fee_cent"
            ),
        ).where(AggStoreMonthlySettlement.month.in_(source_months))

    if affected:
        statements.append(overlay_select(generation_id, affected))
    if inherited:
        resolutions = resolve_projection_partitions(
            session,
            artifact="monthly",
            partition_keys=inherited,
            pinned_generation_id=base_generation_id,
        )
        overlay_groups: dict[str, list[str]] = defaultdict(list)
        legacy_months: list[str] = []
        for month in inherited:
            resolution = resolutions[month]
            if resolution.source_kind == "tombstone":
                continue
            if resolution.source_kind == "legacy_root":
                legacy_months.append(month)
                continue
            if not resolution.actual_data_generation_id:
                raise ValueError("base monthly overlay has no data generation")
            overlay_groups[resolution.actual_data_generation_id].append(month)
        if legacy_months:
            statements.append(legacy_select(legacy_months))
        for source_generation_id, source_months in sorted(overlay_groups.items()):
            statements.append(overlay_select(source_generation_id, source_months))
    if not statements:
        return None
    return union_all(*statements).subquery("effective_sparse_monthly")


def _sparse_cumulative_ranking_query(
    session: Session,
    *,
    generation_id: str,
    base_generation_id: str,
    affected_months: tuple[str, ...],
    cutoff: str,
) -> Any | None:
    formal_month = FORMAL_SETTLEMENT_START.strftime("%Y-%m")
    months = _sparse_month_range(formal_month, cutoff)
    source = _sparse_effective_monthly_relation(
        session,
        generation_id=generation_id,
        base_generation_id=base_generation_id,
        affected_months=affected_months,
        months=months,
    )
    if source is None:
        return None
    return (
        select(
            source.c.store_id,
            func.coalesce(func.max(DimStore.store_name), source.c.store_id).label(
                "store_name"
            ),
            source.c.product_scope,
            source.c.product_type,
            func.sum(source.c.sales_order_count).label("sales_order_count"),
            func.sum(source.c.sales_amount_cent).label("sales_amount_cent"),
            func.sum(source.c.verified_order_count).label("verified_order_count"),
            func.sum(source.c.verified_amount_cent).label("verified_amount_cent"),
            func.sum(source.c.promotion_net_fee_cent).label(
                "promotion_net_fee_cent"
            ),
            func.sum(source.c.management_net_fee_cent).label(
                "management_net_fee_cent"
            ),
        )
        .outerjoin(DimStore, DimStore.store_id == source.c.store_id)
        .group_by(source.c.store_id, source.c.product_scope, source.c.product_type)
        .order_by(source.c.store_id, source.c.product_scope, source.c.product_type)
    )


def _sparse_ranking_values(
    row: Mapping[str, Any],
    *,
    generation_id: str,
    base_generation_id: str,
    period_type: int,
    period_key: str,
) -> dict[str, Any]:
    if period_type not in {1, 2}:
        raise ValueError("ranking period type is invalid")
    period_key = _sparse_month(period_key, label="ranking period key")
    store_id = _sparse_identity(row.get("store_id"), label="ranking store_id")
    product_scope = _sparse_identity(
        row.get("product_scope"), label="ranking product_scope"
    )
    product_type = _sparse_identity(
        row.get("product_type"), label="ranking product_type"
    )
    promotion = int(row.get("promotion_net_fee_cent") or 0)
    management = int(row.get("management_net_fee_cent") or 0)
    prefix = "monthly" if period_type == 1 else "cumulative"
    values: dict[str, Any] = {
        "generation_id": generation_id,
        "base_generation_id": base_generation_id,
        "period_type": period_type,
        "period_key": period_key,
        "store_id": store_id,
        "store_name": str(row.get("store_name") or store_id),
        "product_scope": product_scope,
        "product_type": product_type,
        "partition_key": f"{prefix}:{period_key}",
        "sales_order_count": int(row.get("sales_order_count") or 0),
        "sales_amount_cent": int(row.get("sales_amount_cent") or 0),
        "verified_order_count": int(row.get("verified_order_count") or 0),
        "verified_amount_cent": int(row.get("verified_amount_cent") or 0),
        "promotion_net_fee_cent": promotion,
        "management_net_fee_cent": management,
        "net_settlement_reference_cent": promotion - management,
        "projection_run_id": generation_id,
        "month": period_key,
        "self_sold_self_verified_count": 0,
        "self_sold_other_verified_count": 0,
        "other_sold_self_verified_count": 0,
        "self_verify_income_cent": int(row.get("verified_amount_cent") or 0),
        "effective_commission_income_cent": promotion,
        "tombstone": False,
    }
    values["checksum"] = hashlib.sha256(_sparse_json(values)).hexdigest()
    return values


def _sparse_ranking_envelope(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: values[key]
        for key in (
            "period_type",
            "period_key",
            "store_id",
            "store_name",
            "product_scope",
            "product_type",
            "sales_order_count",
            "sales_amount_cent",
            "verified_order_count",
            "verified_amount_cent",
            "promotion_net_fee_cent",
            "management_net_fee_cent",
            "net_settlement_reference_cent",
            "projection_run_id",
            "month",
        )
    }


def _sparse_write_ranking_partition(
    session_factory: Callable[[], Session],
    *,
    generation_id: str,
    base_generation_id: str,
    affected_months: tuple[str, ...],
    period_type: int,
    period_key: str,
    batch_size: int,
) -> None:
    prefix = "monthly" if period_type == 1 else "cumulative"
    partition_key = f"{prefix}:{period_key}"
    with session_factory() as session:
        _sparse_assert_writable(
            session,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
        )
        session.execute(
            delete(SettlementRankingOverlay).where(
                SettlementRankingOverlay.generation_id == generation_id,
                SettlementRankingOverlay.partition_key == partition_key,
            )
        )
        session.execute(
            delete(SettlementProjectionPartitionManifest).where(
                SettlementProjectionPartitionManifest.generation_id == generation_id,
                SettlementProjectionPartitionManifest.artifact == "ranking",
                SettlementProjectionPartitionManifest.partition_key == partition_key,
            )
        )
        query = (
            _sparse_monthly_ranking_query(generation_id, period_key)
            if period_type == 1
            else _sparse_cumulative_ranking_query(
                session,
                generation_id=generation_id,
                base_generation_id=base_generation_id,
                affected_months=affected_months,
                cutoff=period_key,
            )
        )
        digest = _SparsePartitionDigest.fresh("ranking", partition_key)
        pending: list[dict[str, Any]] = []
        rows = () if query is None else session.execute(
            query.execution_options(yield_per=batch_size)
        ).mappings()
        for raw in rows:
            values = _sparse_ranking_values(
                raw,
                generation_id=generation_id,
                base_generation_id=base_generation_id,
                period_type=period_type,
                period_key=period_key,
            )
            cursor = _sparse_cursor(
                "ranking",
                partition_key,
                {
                    "period_type": period_type,
                    "period_key": period_key,
                    "store_id": values["store_id"],
                    "product_scope": values["product_scope"],
                    "product_type": values["product_type"],
                },
            )
            digest.add(
                _sparse_ranking_envelope(values),
                amount=int(values["net_settlement_reference_cent"]),
                last_key=cursor,
            )
            if digest.row_count > MAX_SETTLEMENT_PAGE_CARDINALITY:
                raise ValueError("ranking sparse partition exceeds row limit")
            pending.append(values)
            if len(pending) == batch_size:
                session.execute(insert(SettlementRankingOverlay), pending)
                pending.clear()
        if pending:
            session.execute(insert(SettlementRankingOverlay), pending)
        session.execute(
            insert(SettlementProjectionPartitionManifest),
            [_sparse_manifest_values(
                generation_id=generation_id,
                base_generation_id=base_generation_id,
                artifact="ranking",
                partition_key=partition_key,
                digest=digest,
            )],
        )
        session.commit()


def _sparse_source_input(
    *,
    base_generation_id: str,
    affected_months: tuple[str, ...],
    cumulative_months: tuple[str, ...],
    batch_size: int,
) -> dict[str, Any]:
    return {
        "protocol": SETTLEMENT_SPARSE_PROTOCOL,
        "projection": "settlement",
        "operation": "build_settlement_sparse_overlay",
        "base_generation_id": base_generation_id,
        "affected_months": list(affected_months),
        "cumulative_months": list(cumulative_months),
        "batch_size": batch_size,
    }


def _sparse_result(
    session: Session,
    *,
    generation_id: str,
    base_generation_id: str,
    resumed: bool,
) -> ProjectionManifestSet:
    generation = session.get(SettlementProjectionGeneration, generation_id)
    if generation is None:
        raise ValueError("sparse settlement generation disappeared")
    manifests = list(
        session.scalars(
            select(SettlementProjectionPartitionManifest)
            .where(
                SettlementProjectionPartitionManifest.generation_id == generation_id,
                SettlementProjectionPartitionManifest.artifact.in_(("monthly", "ranking")),
            )
            .order_by(
                SettlementProjectionPartitionManifest.artifact,
                SettlementProjectionPartitionManifest.partition_key,
            )
        )
    )
    monthly = tuple(
        row.partition_key for row in manifests if row.artifact == "monthly"
    )
    ranking = tuple(
        sorted(
            (row.partition_key for row in manifests if row.artifact == "ranking"),
            key=lambda value: (
                0 if value.startswith("monthly:") else 1,
                value.split(":", 1)[1],
            ),
        )
    )
    checksum = generation.manifest_checksum
    if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
        raise ValueError("sparse settlement generation has no canonical manifest checksum")
    return ProjectionManifestSet(
        generation_id=generation_id,
        base_generation_id=base_generation_id,
        monthly_partitions=monthly,
        ranking_partitions=ranking,
        manifest_count=len(manifests),
        row_count=sum(int(row.row_count) for row in manifests),
        manifest_checksum=checksum,
        resumed=resumed,
    )


def _sparse_finalize_generation(
    session_factory: Callable[[], Session],
    *,
    generation_id: str,
    base_generation_id: str,
    affected_months: tuple[str, ...],
    cumulative_months: tuple[str, ...],
    batch_size: int,
    resumed: bool,
) -> ProjectionManifestSet:
    with session_factory() as session:
        generation = _sparse_assert_writable(
            session,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
        )
        manifest_rows = [
            dict(row)
            for row in session.execute(
                select(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                    SettlementProjectionPartitionManifest.owner_state,
                    SettlementProjectionPartitionManifest.source_kind,
                    SettlementProjectionPartitionManifest.data_generation_id,
                    SettlementProjectionPartitionManifest.base_generation_id,
                    SettlementProjectionPartitionManifest.row_count,
                    SettlementProjectionPartitionManifest.amount_total_cent,
                    SettlementProjectionPartitionManifest.status_counts_json,
                    SettlementProjectionPartitionManifest.checksum,
                )
                .where(
                    SettlementProjectionPartitionManifest.generation_id == generation_id
                )
                .order_by(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
            ).mappings()
        ]
        manifest_checksum = _sparse_generation_manifest_checksum(manifest_rows)
        manifest_count = len(manifest_rows)
        data_rows = sum(int(row["row_count"]) for row in manifest_rows)
        write_rows = 1 + manifest_count + data_rows
        write_bytes = 16_384 + 4_096 * (manifest_count + data_rows)
        wal_bytes = 2 * write_bytes
        terminal = (
            _sparse_cursor(
                str(manifest_rows[-1]["artifact"]),
                str(manifest_rows[-1]["partition_key"]),
                {"partition_key": str(manifest_rows[-1]["partition_key"])},
            )
            if manifest_rows
            else None
        )
        source_input = _sparse_source_input(
            base_generation_id=base_generation_id,
            affected_months=affected_months,
            cumulative_months=cumulative_months,
            batch_size=batch_size,
        )
        generation.estimated_write_rows = write_rows
        generation.estimated_write_bytes = write_bytes
        generation.estimated_wal_bytes = wal_bytes
        generation.estimated_disk_headroom_bytes = 0
        generation.checkpoint_json = {
            **source_input,
            "phase": "settlement_ready",
            "expected_active_pointer": base_generation_id,
            "manifest_count": manifest_count,
            "row_count": data_rows,
            "last_key": terminal,
        }
        generation.last_key = terminal
        generation.manifest_checksum = manifest_checksum
        generation.source_input_json = source_input
        session.commit()
        return _sparse_result(
            session,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            resumed=resumed,
        )


def build_settlement_sparse_overlay(
    session_factory: Callable[[], Session],
    *,
    generation_id: str,
    base_generation_id: str,
    affected_months: Iterable[str],
    batch_size: int,
    input_fingerprint: str,
) -> ProjectionManifestSet:
    """Build only claimed monthly/ranking partitions over a pinned base.

    Each partition is committed independently to keep transactions and memory
    bounded.  A retry rebuilds only this generation's claimed partitions; the
    legacy aggregate and active pointer are never mutated here.
    """

    if not callable(session_factory):
        raise TypeError("session_factory must be callable")
    with session_factory() as preflight_session:
        base, affected, cumulative_months, existing = _sparse_preflight(
            preflight_session,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            affected_months=affected_months,
            batch_size=batch_size,
            input_fingerprint=input_fingerprint,
        )
        base_depth = int(base.lineage_depth)
        has_existing_generation = existing is not None
        resumed = bool(
            existing is not None
            and preflight_session.scalar(
                select(func.count())
                .select_from(SettlementProjectionPartitionManifest)
                .where(
                    SettlementProjectionPartitionManifest.generation_id
                    == generation_id
                )
            )
        )
        existing_state = existing.state if existing is not None else None

    if existing_state in {"ready", "published"}:
        with session_factory() as session:
            return _sparse_result(
                session,
                generation_id=generation_id,
                base_generation_id=base_generation_id,
                resumed=True,
            )

    source_input = _sparse_source_input(
        base_generation_id=base_generation_id,
        affected_months=affected,
        cumulative_months=cumulative_months,
        batch_size=batch_size,
    )
    if not has_existing_generation:
        with session_factory() as session:
            active = session.get(SettlementProjectionActive, "settlement")
            if active is None or active.generation_id != base_generation_id:
                raise ValueError("active settlement pointer changed before sparse claim")
            session.add(
                SettlementProjectionGeneration(
                    generation_id=generation_id,
                    base_generation_id=base_generation_id,
                    generation_kind="lineage",
                    compaction_base_generation_id=None,
                    projection_name="settlement",
                    state="staging",
                    input_fingerprint=input_fingerprint,
                    lineage_depth=base_depth + 1,
                    estimated_write_rows=0,
                    estimated_write_bytes=0,
                    estimated_wal_bytes=0,
                    estimated_disk_headroom_bytes=0,
                    checkpoint_json={
                        **source_input,
                        "phase": "settlement_build",
                        "expected_active_pointer": base_generation_id,
                        "manifest_count": 0,
                        "row_count": 0,
                        "last_key": None,
                    },
                    last_key=None,
                    manifest_checksum=None,
                    source_input_json=source_input,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                peer = session.get(SettlementProjectionGeneration, generation_id)
                if (
                    peer is None
                    or peer.base_generation_id != base_generation_id
                    or peer.input_fingerprint != input_fingerprint
                    or peer.state != "staging"
                ):
                    raise
                resumed = True

    for month in affected:
        _sparse_write_monthly_partition(
            session_factory,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            month=month,
            batch_size=batch_size,
        )
    for month in affected:
        _sparse_write_ranking_partition(
            session_factory,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            affected_months=affected,
            period_type=1,
            period_key=month,
            batch_size=batch_size,
        )
    for month in cumulative_months:
        _sparse_write_ranking_partition(
            session_factory,
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            affected_months=affected,
            period_type=2,
            period_key=month,
            batch_size=batch_size,
        )
    return _sparse_finalize_generation(
        session_factory,
        generation_id=generation_id,
        base_generation_id=base_generation_id,
        affected_months=affected,
        cumulative_months=cumulative_months,
        batch_size=batch_size,
        resumed=resumed,
    )


def settle_coupon_local(
    session: Session,
    coupon: RawDouyinOrderCoupon | str,
    calculation_run_id: str,
) -> LocalSettlementResult:
    """Lock and rebuild one coupon's local settlement facts.

    This is intentionally a coupon-level primitive.  It never discovers or
    iterates other coupons, monthly/ranking projections, or a global DQI set;
    the caller owns batching and impact closure in a later slice.
    """

    coupon_id = coupon.coupon_id if isinstance(coupon, RawDouyinOrderCoupon) else str(coupon)
    locked_coupon = session.scalar(
        select(RawDouyinOrderCoupon)
        .where(RawDouyinOrderCoupon.coupon_id == coupon_id)
        .with_for_update()
    )
    if locked_coupon is None:
        raise ValueError(f"unknown settlement coupon: {coupon_id}")

    previous = _capture_local_coupon_state(session, coupon_id)
    session.info["incremental_dqi_identity"] = True
    invalid = False
    locked = False
    try:
        order = _raw_order_for_coupon(session, locked_coupon)
        invalid = _is_invalid_or_closed_coupon(locked_coupon, order)
        if invalid:
            locked = _local_coupon_settlement_locked(session, previous)
            session.execute(
                delete(SettlementOrderDetail).where(
                    SettlementOrderDetail.coupon_id == coupon_id
                )
            )
            if not locked:
                session.execute(
                    delete(SettlementFeeResultCurrent).where(
                        SettlementFeeResultCurrent.coupon_id == coupon_id
                    )
                )
            _record_issue(
                session,
                issue_type="incremental_invalid_coupon",
                message="券已失效或关闭，局部结算事实已按锁账状态处理。",
                order_id=locked_coupon.order_id,
                coupon_id=coupon_id,
                source_run_id=calculation_run_id,
                severity="warning",
                raw_context={
                    "coupon_status": locked_coupon.coupon_status_normalized
                    or locked_coupon.coupon_status,
                    "locked": locked,
                },
                identity_suffix="invalid-or-closed",
            )
        else:
            session.execute(
                delete(SettlementOrderDetail).where(
                    SettlementOrderDetail.coupon_id == coupon_id
                )
            )
            _materialize_coupon(session, locked_coupon, source_run_id=calculation_run_id)
            rebuild_dual_fee_results(
                session,
                calculation_run_id=calculation_run_id,
                coupon_ids=(coupon_id,),
            )
        session.flush()
    finally:
        session.info.pop("incremental_dqi_identity", None)

    current = _capture_local_coupon_state(session, coupon_id)
    months: set[str] = set()
    stores: set[str] = set()
    _collect_local_affected_checkpoint(previous, months, stores)
    _collect_local_affected_checkpoint(current, months, stores)
    return LocalSettlementResult(
        coupon_id=coupon_id,
        invalid=invalid,
        locked=locked,
        detail_count=int(current["detail"] is not None),
        result_count=max(0, len(current["results"]) - len(previous["results"])),
        adjustment_count=max(
            0, len(current["adjustments"]) - len(previous["adjustments"])
        ),
        affected_months=sorted(months),
        affected_store_ids=sorted(stores),
        completed=True,
    )


# Names retained for the next slice's integration adapter without making that
# adapter part of this local-kernel task.
settle_coupon_incremental = settle_coupon_local
settle_one_coupon = settle_coupon_local


def settle_impacted_coupons(
    session_factory: Any,
    source_run_id: str,
    page_fence: Any,
    impact_batch_size: int,
    coupon_batch_size: int,
) -> dict[str, Any]:
    """Settle only coupons selected by one source run's impact stream.

    Impacts are consumed with an ``id`` keyset page (never ``offset`` or an
    unbounded ``all()``).  Each selected coupon page is settled in an
    independent short transaction.  The fence is checked immediately before
    that transaction commits; a false fence rolls back only the current page
    and returns ``completed=False`` while preserving earlier commits.  A
    caller may safely retry from the impact stream head: the coupon kernel's
    input fingerprint and revision fences turn already committed coupons into
    no-ops.

    ``impact_count`` counts impact rows consumed (including safe-to-skip rows),
    ``coupon_count`` counts coupon rows handed to the kernel, and the three
    projection counts sum the corresponding kernel deltas after a successful
    commit.  ``last_impact_id`` advances only after an entire impact page has
    been consumed.  ``affected_months`` and ``affected_store_ids`` are sorted
    de-duplicated checkpoint dimensions gathered from both impact closures and
    committed coupon results.
    """

    if not callable(session_factory):
        raise TypeError("session_factory must be callable")
    if page_fence is not None and not callable(page_fence):
        raise TypeError("page_fence must be callable or None")
    safe_impact_batch_size = min(
        _positive_batch_size(impact_batch_size, "impact_batch_size"),
        MAX_SETTLEMENT_IMPACT_BATCH_SIZE,
    )
    safe_coupon_batch_size = min(
        _positive_batch_size(coupon_batch_size, "coupon_batch_size"),
        MAX_SETTLEMENT_COUPON_BATCH_SIZE,
    )

    summary: dict[str, Any] = {
        "impact_count": 0,
        "coupon_count": 0,
        "detail_count": 0,
        "result_count": 0,
        "adjustment_count": 0,
        "last_impact_id": 0,
        "affected_months": [],
        "affected_store_ids": [],
        "completed": False,
    }
    affected_months: set[str] = set()
    affected_store_ids: set[str] = set()
    last_impact_id = 0

    while True:
        impact_page = _read_settlement_impact_page(
            session_factory,
            source_run_id=str(source_run_id),
            after_impact_id=last_impact_id,
            limit=safe_impact_batch_size,
        )
        if not impact_page:
            if not _settlement_fence_only(session_factory, page_fence):
                summary["last_impact_id"] = last_impact_id
                summary["affected_months"] = sorted(affected_months)
                summary["affected_store_ids"] = sorted(affected_store_ids)
                return summary
            summary["last_impact_id"] = last_impact_id
            summary["affected_months"] = sorted(affected_months)
            summary["affected_store_ids"] = sorted(affected_store_ids)
            summary["completed"] = True
            return summary

        summary["impact_count"] += len(impact_page)
        page_months: set[str] = set()
        page_store_ids: set[str] = set()
        page_coupon_ids: set[str] = set()
        page_order_ids: set[str] = set()
        page_verify_ids: set[str] = set()
        page_poi_ids: set[str] = set()
        page_selector_store_ids: set[str] = set()
        for impact in impact_page:
            selectors = _settlement_coupon_selectors(impact)
            if not selectors.has_sources:
                continue
            _collect_settlement_impact_dimensions(
                impact,
                affected_months=page_months,
                affected_store_ids=page_store_ids,
            )
            page_coupon_ids.update(selectors.direct_coupon_ids)
            page_order_ids.update(selectors.order_ids)
            page_verify_ids.update(selectors.verify_ids)
            page_poi_ids.update(selectors.poi_ids)
            page_selector_store_ids.update(selectors.store_ids)
            _enforce_settlement_page_cardinality(
                page_coupon_ids=page_coupon_ids,
                page_order_ids=page_order_ids,
                page_verify_ids=page_verify_ids,
                page_poi_ids=page_poi_ids,
                page_selector_store_ids=page_selector_store_ids,
                page_months=page_months,
                page_store_ids=page_store_ids,
            )
        selectors = _SettlementCouponSelectors(
            direct_coupon_ids=tuple(sorted(page_coupon_ids)),
            order_ids=tuple(sorted(page_order_ids)),
            verify_ids=tuple(sorted(page_verify_ids)),
            poi_ids=tuple(sorted(page_poi_ids)),
            store_ids=tuple(sorted(page_selector_store_ids)),
        )
        coupon_cursor: str | None = None
        committed_any = False
        while selectors.has_sources:
            coupon_ids = _read_settlement_coupon_page(
                session_factory,
                selectors,
                after_coupon_id=coupon_cursor,
                limit=safe_coupon_batch_size,
            )
            if not coupon_ids:
                break
            batch_result = _settle_coupon_batch(
                session_factory,
                coupon_ids=coupon_ids,
                source_run_id=str(source_run_id),
                page_fence=page_fence,
            )
            if batch_result is None:
                # Once any batch from this impact page committed, report the
                # page's closure dimensions conservatively even though the
                # current batch was fenced out.  Do not expose rolled-back
                # page dimensions when the first batch itself failed.
                if committed_any:
                    affected_months.update(page_months)
                    affected_store_ids.update(page_store_ids)
                summary["last_impact_id"] = last_impact_id
                summary["affected_months"] = sorted(affected_months)
                summary["affected_store_ids"] = sorted(affected_store_ids)
                return summary
            committed_any = True
            summary["coupon_count"] += len(coupon_ids)
            summary["detail_count"] += batch_result["detail_count"]
            summary["result_count"] += batch_result["result_count"]
            summary["adjustment_count"] += batch_result["adjustment_count"]
            affected_months.update(batch_result["affected_months"])
            affected_store_ids.update(batch_result["affected_store_ids"])
            coupon_cursor = coupon_ids[-1]
        if not selectors.has_sources:
            # Unknown/irrelevant impacts are intentionally skipped, but a
            # short fenced transaction still proves ownership before the
            # impact page can advance.
            if not _settlement_fence_only(session_factory, page_fence):
                summary["last_impact_id"] = last_impact_id
                summary["affected_months"] = sorted(affected_months)
                summary["affected_store_ids"] = sorted(affected_store_ids)
                return summary
        elif not committed_any:
            # A valid selector can point at a row deleted between capture and
            # settlement. Keep this page bounded and fence the no-op.
            if not _settlement_fence_only(session_factory, page_fence):
                summary["last_impact_id"] = last_impact_id
                summary["affected_months"] = sorted(affected_months)
                summary["affected_store_ids"] = sorted(affected_store_ids)
                return summary
        if selectors.has_sources:
            affected_months.update(page_months)
            affected_store_ids.update(page_store_ids)

        last_impact_id = int(impact_page[-1]["id"])
        summary["last_impact_id"] = last_impact_id


def _positive_batch_size(value: int, name: str) -> int:
    try:
        bounded = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if bounded <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return bounded


def _enforce_settlement_page_cardinality(
    *,
    page_coupon_ids: set[str],
    page_order_ids: set[str],
    page_verify_ids: set[str],
    page_poi_ids: set[str],
    page_selector_store_ids: set[str],
    page_months: set[str],
    page_store_ids: set[str],
) -> None:
    cardinality = sum(
        len(values)
        for values in (
            page_coupon_ids,
            page_order_ids,
            page_verify_ids,
            page_poi_ids,
            page_selector_store_ids,
            page_months,
            page_store_ids,
        )
    )
    if cardinality > MAX_SETTLEMENT_PAGE_CARDINALITY:
        raise ValueError("settlement impact page exceeds maximum cardinality")


def _read_settlement_impact_page(
    session_factory: Any,
    *,
    source_run_id: str,
    after_impact_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    session = session_factory()
    try:
        session.begin()
        rows = list(
            session.scalars(
                select(JobImpact)
                .where(
                    JobImpact.source_run_id == source_run_id,
                    JobImpact.id > int(after_impact_id),
                )
                .order_by(JobImpact.id)
                .limit(limit)
            )
        )
        return [_snapshot_settlement_impact(row) for row in rows]
    finally:
        try:
            session.rollback()
        finally:
            session.close()


def _snapshot_settlement_impact(impact: JobImpact) -> dict[str, Any]:
    return {
        "id": int(impact.id),
        "entity_type": str(impact.entity_type or "").strip().lower(),
        "entity_key": str(impact.entity_key or ""),
        "old_values_json": dict(impact.old_values_json or {}),
        "new_values_json": dict(impact.new_values_json or {}),
        "affected_closure_json": dict(impact.affected_closure_json or {}),
    }


@dataclass(frozen=True)
class _SettlementCouponSelectors:
    direct_coupon_ids: tuple[str, ...] = ()
    order_ids: tuple[str, ...] = ()
    verify_ids: tuple[str, ...] = ()
    poi_ids: tuple[str, ...] = ()
    store_ids: tuple[str, ...] = ()

    @property
    def has_sources(self) -> bool:
        return bool(
            self.direct_coupon_ids
            or self.order_ids
            or self.verify_ids
            or self.poi_ids
            or self.store_ids
        )


def _settlement_values(payload: Mapping[str, Any] | None, key: str) -> tuple[str, ...]:
    if not isinstance(payload, Mapping) or not payload:
        return ()
    value = payload.get(key)
    if value in (None, ""):
        return ()
    if isinstance(value, (list, tuple, set)) and len(value) > MAX_SETTLEMENT_CLOSURE_VALUES:
        raise ValueError(
            "settlement impact closure field exceeds maximum cardinality"
        )
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    return tuple(str(item) for item in values if item not in (None, ""))


def _settlement_values_with_old_new(
    payload: Mapping[str, Any] | None, key: str
) -> tuple[str, ...]:
    values = set(_settlement_values(payload, key))
    values.update(_settlement_values(payload, f"old_{key}"))
    values.update(_settlement_values(payload, f"new_{key}"))
    return tuple(sorted(values))


def _settlement_payloads(impact: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    closure = impact.get("affected_closure_json") or {}
    payloads: list[Mapping[str, Any]] = [closure]
    for key in (
        "old",
        "new",
        "old_values",
        "new_values",
        "old_values_json",
        "new_values_json",
    ):
        nested = closure.get(key) if isinstance(closure, Mapping) else None
        if isinstance(nested, Mapping):
            payloads.append(nested)
    payloads.extend(
        (
            impact.get("old_values_json") or {},
            impact.get("new_values_json") or {},
        )
    )
    return tuple(payloads)


def _collect_settlement_impact_dimensions(
    impact: Mapping[str, Any],
    *,
    affected_months: set[str],
    affected_store_ids: set[str],
) -> None:
    for payload in _settlement_payloads(impact):
        for field_name in (
            "affected_months",
            "sale_months",
            "verify_months",
            "refund_months",
            "clue_months",
            "months",
            "original_business_month",
            "posting_month",
            "adjustment_posting_month",
        ):
            affected_months.update(
                _settlement_values_with_old_new(payload, field_name)
            )
        affected_store_ids.update(
            _settlement_values_with_old_new(payload, "store_ids")
        )
        affected_store_ids.update(
            _settlement_values_with_old_new(payload, "affected_store_ids")
        )
        for field_name in ("sale_store_ids", "verify_store_ids"):
            affected_store_ids.update(
                _settlement_values_with_old_new(payload, field_name)
            )
        for field_name in (
            "sale_store_id",
            "verify_store_id",
            "old_store_id",
            "new_store_id",
        ):
            affected_store_ids.update(
                _settlement_values_with_old_new(payload, field_name)
            )
        for field_name in (
            "sale_time",
            "pay_time",
            "create_order_time",
            "verify_time",
            "cancel_time",
            "occurred_at",
            "coupon_refund_time",
            "latest_refund_at",
            "create_time_detail",
            "month",
        ):
            for value in _settlement_values_with_old_new(payload, field_name):
                affected_months.update(_settlement_months(value))


def _settlement_month(value: str) -> str | None:
    raw = str(value).strip()
    if len(raw) >= 7 and raw[4] == "-":
        candidate = raw[:7]
        if candidate[:4].isdigit() and candidate[5:7].isdigit():
            return candidate
    return None


def _settlement_months(value: Any) -> set[str]:
    """Return raw and Shanghai business months for timestamp-like values.

    Aware timestamps are interpreted in their own timezone; naive datetime
    objects and timestamp strings follow the project convention of UTC before
    Shanghai business-month conversion.  Both forms retain the raw ``YYYY-MM``
    prefix and add the derived Shanghai month.  Date-only values and plain
    ``YYYY-MM`` values remain raw-month-only.
    """

    raw = str(value).strip()
    months: set[str] = set()
    raw_month = _settlement_month(raw)
    if raw_month:
        months.add(raw_month)
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif "T" in raw or " " in raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        months.add(parsed.astimezone(SHANGHAI).strftime("%Y-%m"))
    return months


def _settlement_coupon_selectors(impact: Mapping[str, Any]) -> _SettlementCouponSelectors:
    entity_type = str(impact.get("entity_type") or "").strip().lower()
    entity_key = str(impact.get("entity_key") or "").strip()
    coupon_types = {"coupon"}
    order_types = {"order"}
    refund_types = {"refund", "refund_event", "douyin_refund_event", "refund_record"}
    verify_types = {"verify", "verify_record", "douyin_verify_record"}
    mapping_types = {"store_poi_mapping", "store-poi-mapping", "poi_mapping"}
    if entity_type not in coupon_types | order_types | refund_types | verify_types | mapping_types:
        return _SettlementCouponSelectors()

    def typed_values(
        payload: Mapping[str, Any] | None,
        plural_names: tuple[str, ...],
        scalar_names: tuple[str, ...],
    ) -> set[str]:
        values: set[str] = set()
        for name in plural_names:
            values.update(_settlement_values_with_old_new(payload, name))
        for name in scalar_names:
            values.update(_settlement_values_with_old_new(payload, name))
        return values

    payloads = _settlement_payloads(impact)
    coupon_ids: set[str] = set()
    order_ids: set[str] = set()
    verify_ids: set[str] = set()
    poi_ids: set[str] = set()
    store_ids: set[str] = set()
    if entity_type in coupon_types:
        for payload in payloads:
            coupon_ids.update(
                typed_values(payload, ("coupon_ids",), ("coupon_id",))
            )
        if entity_key:
            coupon_ids.add(entity_key)
    elif entity_type in order_types:
        for payload in payloads:
            order_ids.update(
                typed_values(payload, ("order_ids",), ("order_id",))
            )
        if entity_key:
            order_ids.add(entity_key)
    elif entity_type in verify_types:
        for payload in payloads:
            coupon_ids.update(
                typed_values(payload, ("coupon_ids",), ("coupon_id",))
            )
            verify_ids.update(
                typed_values(payload, ("verify_ids",), ("verify_id",))
            )
            for field_names in (
                ("poi_ids",),
                ("verify_poi_ids",),
                ("intention_poi_ids",),
            ):
                poi_ids.update(typed_values(payload, field_names, ()))
            poi_ids.update(typed_values(payload, (), ("poi_id",)))
        if entity_key:
            verify_ids.add(entity_key)
    elif entity_type in mapping_types:
        for payload in payloads:
            for field_names in (
                ("poi_ids",),
                ("verify_poi_ids",),
                ("intention_poi_ids",),
            ):
                poi_ids.update(typed_values(payload, field_names, ()))
            poi_ids.update(typed_values(payload, (), ("poi_id",)))
            store_ids.update(
                typed_values(payload, ("store_ids",), ("store_id",))
            )
            store_ids.update(
                typed_values(payload, ("sale_store_ids",), ()))
            store_ids.update(
                typed_values(payload, ("verify_store_ids",), ()))
        # Capture entity_key is the POI.  Never guess it is a store id.
        if entity_key:
            poi_ids.add(entity_key)
    else:  # refund_types
        old_values = impact.get("old_values_json")
        new_values = impact.get("new_values_json")
        typed_side = False
        for payload in (old_values, new_values):
            side_coupons = typed_values(payload, ("coupon_ids",), ("coupon_id",))
            side_orders = typed_values(payload, ("order_ids",), ("order_id",))
            if side_coupons:
                coupon_ids.update(side_coupons)
                typed_side = True
            elif side_orders:
                order_ids.update(side_orders)
                typed_side = True
        if not typed_side:
            closure = impact.get("affected_closure_json")
            closure_coupons = typed_values(
                closure, ("coupon_ids",), ("coupon_id",)
            )
            closure_orders = typed_values(closure, ("order_ids",), ("order_id",))
            if closure_coupons:
                coupon_ids.update(closure_coupons)
            else:
                order_ids.update(closure_orders)
    return _SettlementCouponSelectors(
        direct_coupon_ids=tuple(sorted(coupon_ids)),
        order_ids=tuple(sorted(order_ids)),
        verify_ids=tuple(sorted(verify_ids)),
        poi_ids=tuple(sorted(poi_ids)),
        store_ids=tuple(sorted(store_ids)),
    )


def _read_settlement_coupon_page(
    session_factory: Any,
    selectors: _SettlementCouponSelectors,
    *,
    after_coupon_id: str | None,
    limit: int,
) -> list[str]:
    session = session_factory()
    try:
        session.begin()
        predicates = []
        if selectors.direct_coupon_ids:
            predicates.append(
                RawDouyinOrderCoupon.coupon_id.in_(selectors.direct_coupon_ids)
            )
        if selectors.order_ids:
            predicates.append(RawDouyinOrderCoupon.order_id.in_(selectors.order_ids))
        if selectors.verify_ids:
            predicates.append(
                RawDouyinOrderCoupon.coupon_id.in_(
                    select(RawDouyinVerifyRecord.coupon_id).where(
                        RawDouyinVerifyRecord.verify_id.in_(selectors.verify_ids),
                        RawDouyinVerifyRecord.coupon_id.is_not(None),
                    )
                )
            )
        if selectors.poi_ids:
            predicates.append(
                RawDouyinOrderCoupon.coupon_id.in_(
                    select(RawDouyinVerifyRecord.coupon_id).where(
                        RawDouyinVerifyRecord.poi_id.in_(selectors.poi_ids),
                        RawDouyinVerifyRecord.coupon_id.is_not(None),
                    )
                )
            )
            predicates.append(
                RawDouyinOrderCoupon.order_id.in_(
                    select(RawDouyinOrder.order_id).where(
                        RawDouyinOrder.intention_poi_id.in_(selectors.poi_ids)
                    )
                )
            )
        if selectors.store_ids:
            mapping_pois = select(DimStorePoiMapping.poi_id).where(
                DimStorePoiMapping.store_id.in_(selectors.store_ids)
            )
            predicates.append(
                RawDouyinOrderCoupon.coupon_id.in_(
                    select(RawDouyinVerifyRecord.coupon_id).where(
                        RawDouyinVerifyRecord.poi_id.in_(mapping_pois),
                        RawDouyinVerifyRecord.coupon_id.is_not(None),
                    )
                )
            )
            predicates.append(
                RawDouyinOrderCoupon.order_id.in_(
                    select(RawDouyinOrder.order_id).where(
                        RawDouyinOrder.intention_poi_id.in_(mapping_pois)
                    )
                )
            )
        if not predicates:
            return []
        statement = select(RawDouyinOrderCoupon.coupon_id).where(or_(*predicates))
        if after_coupon_id is not None:
            statement = statement.where(RawDouyinOrderCoupon.coupon_id > after_coupon_id)
        statement = statement.order_by(RawDouyinOrderCoupon.coupon_id).limit(limit)
        return [str(value) for value in session.scalars(statement)]
    finally:
        try:
            session.rollback()
        finally:
            session.close()


def _settle_coupon_batch(
    session_factory: Any,
    *,
    coupon_ids: list[str],
    source_run_id: str,
    page_fence: Any,
) -> dict[str, Any] | None:
    session = session_factory()
    batch_totals = {
        "detail_count": 0,
        "result_count": 0,
        "adjustment_count": 0,
        "affected_months": set(),
        "affected_store_ids": set(),
    }
    try:
        session.begin()
        for coupon_id in coupon_ids:
            result = settle_coupon_local(session, coupon_id, source_run_id)
            batch_totals["detail_count"] += int(result.get("detail_count", 0) or 0)
            batch_totals["result_count"] += int(result.get("result_count", 0) or 0)
            batch_totals["adjustment_count"] += int(result.get("adjustment_count", 0) or 0)
            batch_totals["affected_months"].update(
                str(value)
                for value in result.get("affected_months", []) or []
                if value not in (None, "")
            )
            batch_totals["affected_store_ids"].update(
                str(value)
                for value in result.get("affected_store_ids", []) or []
                if value not in (None, "")
            )
        if page_fence is not None and not bool(page_fence(session)):
            session.rollback()
            return None
        session.commit()
        return {
            "detail_count": int(batch_totals["detail_count"]),
            "result_count": int(batch_totals["result_count"]),
            "adjustment_count": int(batch_totals["adjustment_count"]),
            "affected_months": sorted(batch_totals["affected_months"]),
            "affected_store_ids": sorted(batch_totals["affected_store_ids"]),
        }
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _settlement_fence_only(session_factory: Any, page_fence: Any) -> bool:
    session = session_factory()
    try:
        session.begin()
        if page_fence is not None and not bool(page_fence(session)):
            session.rollback()
            return False
        session.commit()
        return True
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def _capture_local_coupon_state(session: Session, coupon_id: str) -> dict[str, Any]:
    detail = session.scalar(
        select(SettlementOrderDetail).where(
            SettlementOrderDetail.coupon_id == coupon_id
        )
    )
    current = list(
        session.scalars(
            select(SettlementFeeResultCurrent)
            .where(SettlementFeeResultCurrent.coupon_id == coupon_id)
            .order_by(SettlementFeeResultCurrent.fee_direction)
        )
    )
    results = list(
        session.scalars(
            select(SettlementFeeResult)
            .where(SettlementFeeResult.coupon_id == coupon_id)
            .order_by(SettlementFeeResult.fee_direction, SettlementFeeResult.result_version)
        )
    )
    adjustments = list(
        session.scalars(
            select(SettlementFeeAdjustment)
            .where(SettlementFeeAdjustment.coupon_id == coupon_id)
            .order_by(
                SettlementFeeAdjustment.occurred_at,
                SettlementFeeAdjustment.adjustment_id,
            )
        )
    )
    return {
        "detail": detail,
        "current": current,
        "results": results,
        "adjustments": adjustments,
    }


def _collect_local_affected_checkpoint(
    state: dict[str, Any], months: set[str], stores: set[str]
) -> None:
    detail = state.get("detail")
    if detail is not None:
        for value in (detail.sale_time, detail.verify_time):
            month = _month(value)
            if month:
                months.add(month)
            month = _local_business_month(value)
            if month:
                months.add(month)
        for value in (detail.sale_store_id, detail.verify_store_id):
            if value:
                stores.add(str(value))
    results = state.get("results", [])
    for result in results:
        if result.original_business_month:
            months.add(str(result.original_business_month))
        for value in (result.sale_store_id, result.verify_store_id):
            if value:
                stores.add(str(value))
    for adjustment in state.get("adjustments", []):
        for value in (
            adjustment.original_business_month,
            adjustment.adjustment_posting_month,
        ):
            if value:
                months.add(str(value))
        original = next(
            (
                result
                for result in results
                if result.fee_result_id == adjustment.original_fee_result_id
            ),
            None,
        )
        if original is not None:
            store_id = (
                original.sale_store_id
                if adjustment.fee_direction == PROMOTION_FEE
                else original.verify_store_id
            )
            if store_id:
                stores.add(str(store_id))


def _is_invalid_or_closed_coupon(
    coupon: RawDouyinOrderCoupon, order: RawDouyinOrder | None
) -> bool:
    status = _normalized(coupon.coupon_status_normalized or coupon.coupon_status)
    return status in {
        "invalid",
        "closed",
        "cancelled",
        "canceled",
        "void",
        "unavailable",
    } or (order is not None and _dual_order_status(order) == "closed")


def _local_coupon_settlement_locked(
    session: Session, state: dict[str, Any]
) -> bool:
    results = {
        result.fee_result_id: result for result in state.get("results", [])
    }
    for current in state.get("current", []):
        result = results.get(current.fee_result_id)
        if result is None:
            continue
        store_id = (
            result.sale_store_id
            if current.fee_direction == PROMOTION_FEE
            else result.verify_store_id
        )
        if store_id and _is_fee_result_locked(
            session,
            store_id=store_id,
            month=result.original_business_month,
            current_fee_result_id=current.fee_result_id,
        ):
            return True
    detail = state.get("detail")
    if detail is not None:
        for store_id, value in (
            (detail.sale_store_id, detail.sale_time),
            (detail.verify_store_id, detail.verify_time),
        ):
            month = _local_business_month(value)
            if store_id and month and _is_fee_result_locked(
                session, store_id=str(store_id), month=month
            ):
                return True
    return False



def run_settlement_job(session: Session, *, job_id: str, source_run_id: str) -> SettlementStats:
    start_job_run(session, job_id, "settlement_rebuild", metadata_json={"source_run_id": source_run_id})
    try:
        stats = rebuild_settlement(session, source_run_id=source_run_id)
    except Exception as exc:
        finish_job_run(session, job_id, status="failed", failed_count=1, error_message=str(exc))
        raise
    finish_job_run(session, job_id, status="success", success_count=stats.detail_count)
    return stats


def rebuild_settlement(session: Session, *, source_run_id: str) -> SettlementStats:
    session.execute(delete(SettlementOrderDetail))
    session.execute(delete(AggStoreRanking))
    session.execute(delete(AggStoreMonthlySettlement))
    session.execute(delete(DataQualityIssue))
    session.flush()

    coupons = session.scalars(select(RawDouyinOrderCoupon).order_by(RawDouyinOrderCoupon.coupon_id)).all()
    for coupon in coupons:
        _materialize_coupon(session, coupon, source_run_id=source_run_id)
    session.flush()

    details = session.scalars(select(SettlementOrderDetail)).all()
    ranking_count = _rebuild_store_ranking(
        session, details, source_run_id=source_run_id
    )
    monthly_count = _rebuild_monthly_settlement(
        session, details, source_run_id=source_run_id
    )
    rebuild_dual_fee_results(session, calculation_run_id=source_run_id)
    rebuild_dual_fee_projections(session, projection_run_id=source_run_id)
    ranking_count = _model_count(session, AggStoreRanking)
    monthly_count = _model_count(session, AggStoreMonthlySettlement)
    issue_count = session.scalar(
        select(func.count()).select_from(DataQualityIssue).where(DataQualityIssue.source_run_id == source_run_id)
    )
    if issue_count is None:
        issue_count = 0
    return SettlementStats(
        detail_count=len(details),
        issue_count=issue_count,
        ranking_count=ranking_count,
        monthly_count=monthly_count,
    )


def _materialize_coupon(session: Session, coupon: RawDouyinOrderCoupon, *, source_run_id: str) -> None:
    order = _raw_order_for_coupon(session, coupon)
    if order is None:
        _record_issue(
            session,
            issue_type="raw_order_internal_reference_mismatch",
            message="券的内部订单引用不存在，或与平台订单 ID 不一致。",
            order_id=coupon.order_id,
            coupon_id=coupon.coupon_id,
            source_run_id=source_run_id,
            severity="error",
            raw_context={
                "raw_order_id": coupon.raw_order_id,
                "referenced_order_id": _referenced_order_business_id(session, coupon),
            },
        )
        return

    verify = _select_valid_verify_record(session, coupon.coupon_id)
    owner_account = _match_owner(session, order, coupon, source_run_id=source_run_id)
    sale_store = session.get(DimStore, owner_account.store_id) if owner_account and owner_account.store_id else None
    if owner_account and owner_account.store_id and sale_store is None:
        _record_issue(
            session,
            issue_type="unmatched_owner",
            message="Owner matched an account without a valid store.",
            order_id=order.order_id,
            coupon_id=coupon.coupon_id,
            source_run_id=source_run_id,
            raw_context={"owner_account_id": owner_account.account_id, "store_id": owner_account.store_id},
        )

    sku_id = _first_text(order.sku_id, verify.sku_id if verify else None)
    sku_rule = (
        session.scalar(
            select(DimSkuProductRule).where(DimSkuProductRule.sku_id == sku_id)
        )
        if sku_id
        else None
    )
    if sku_rule is None:
        _record_issue(
            session,
            issue_type="unmatched_sku",
            message="No SKU product rule matched the order or verify record.",
            order_id=order.order_id,
            coupon_id=coupon.coupon_id,
            source_run_id=source_run_id,
            raw_context={
                "sku_id": sku_id,
                "order_sku_id": order.sku_id,
                "verify_sku_id": verify.sku_id if verify else None,
            },
        )

    verify_store = None
    poi_mapping = None
    if verify is not None:
        poi_mapping = _find_poi_mapping(session, verify.poi_id)
        if poi_mapping is None:
            _record_issue(
                session,
                issue_type="unmatched_poi",
                message="Verified coupon has no POI to store mapping.",
                order_id=order.order_id,
                coupon_id=coupon.coupon_id,
                source_run_id=source_run_id,
                raw_context={"poi_id": verify.poi_id, "verify_id": verify.verify_id},
            )
        else:
            verify_store = session.get(DimStore, poi_mapping.store_id)

    relation_type = _relation_type(sale_store, verify_store, verify is not None)
    refund_excluded = _is_refund_excluded(order, coupon)
    paid_amount_cent = _paid_amount_cent(order, verify)
    configured_commission_rate = (
        Decimal(sku_rule.commission_rate) if sku_rule else Decimal("0")
    )
    is_service_product = bool(sku_rule.is_service_product) if sku_rule else False
    forced_non_commission = _is_non_commission_owner_account(
        session, order.owner_account_name
    )
    is_commissionable = (
        relation_type == "cross_store"
        and not refund_excluded
        and not forced_non_commission
        and is_service_product
        and sku_rule is not None
        and sale_store is not None
        and verify_store is not None
    )
    commission_rate = (
        configured_commission_rate if is_commissionable else Decimal("0")
    )
    commission_cent = (
        _commission_cent(paid_amount_cent, commission_rate)
        if is_commissionable
        else 0
    )

    detail = SettlementOrderDetail(
        coupon_id=coupon.coupon_id,
        order_id=order.order_id,
        verify_id=verify.verify_id if verify else None,
        sku_id=sku_id,
        owner_account_id=order.owner_account_id,
        owner_account_name=order.owner_account_name,
        product_type=sku_rule.product_type if sku_rule else "unknown",
        sale_store_id=sale_store.store_id if sale_store else None,
        sale_store_name=sale_store.store_name if sale_store else None,
        sale_time=order.pay_time or order.create_order_time,
        is_verified=verify is not None,
        verify_store_id=verify_store.store_id if verify_store else None,
        verify_store_name=(
            verify_store.store_name
            if verify_store
            else (verify.verify_store_name_raw if verify else None)
        ),
        verify_time=verify.verify_time if verify else None,
        relation_type=relation_type,
        is_commissionable=is_commissionable,
        is_refund_excluded=refund_excluded,
        paid_amount_cent=paid_amount_cent,
        commission_rate=commission_rate,
        receivable_commission_cent=commission_cent,
        payable_commission_cent=commission_cent,
        source_run_id=source_run_id,
    )
    session.merge(detail)


def rebuild_dual_fee_results(
    session: Session,
    *,
    calculation_run_id: str,
    force_recalculate: bool = False,
    coupon_ids: Iterable[str] | None = None,
) -> DualFeeStats:
    """Materialize immutable promotion/management results and later adjustments.

    Expected data-quality failures are isolated per coupon and direction. Existing
    current results are left untouched during an ordinary repeat run; an explicit
    recalculation creates a new version and switches only an unlocked pointer.
    """

    bounded_coupon_ids: tuple[str, ...] | None = None
    if coupon_ids is not None:
        bounded_coupon_ids = tuple(sorted({str(value) for value in coupon_ids}))
        if not bounded_coupon_ids:
            return DualFeeStats(result_count=0, adjustment_count=0, blocked_count=0)
    if bounded_coupon_ids is None:
        before_results = _model_count(session, SettlementFeeResult)
        before_adjustments = _model_count(session, SettlementFeeAdjustment)
    else:
        before_results = _scoped_model_count(
            session, SettlementFeeResult, bounded_coupon_ids
        )
        before_adjustments = _scoped_model_count(
            session, SettlementFeeAdjustment, bounded_coupon_ids
        )
    blocked_count = 0
    coupon_query = select(RawDouyinOrderCoupon).order_by(RawDouyinOrderCoupon.coupon_id)
    if bounded_coupon_ids is not None:
        coupon_query = coupon_query.where(
            RawDouyinOrderCoupon.coupon_id.in_(bounded_coupon_ids)
        )
    coupons = list(session.scalars(coupon_query))
    for coupon in coupons:
        # The coupon row is the stable serialization key for both fee directions.
        # PostgreSQL therefore cannot race on max(version)+1/current-pointer updates.
        locked_coupon = session.scalar(
            select(RawDouyinOrderCoupon)
            .where(RawDouyinOrderCoupon.coupon_id == coupon.coupon_id)
            .with_for_update()
        )
        if locked_coupon is not None:
            coupon = locked_coupon
        order = _raw_order_for_coupon(session, coupon)
        if order is None:
            blocked_count += _block_dual_fee(
                session,
                calculation_run_id,
                coupon,
                None,
                "raw_order_internal_reference_mismatch",
                "券的内部订单引用不存在，或与平台订单 ID 不一致。",
                directions=(PROMOTION_FEE, MANAGEMENT_FEE),
                context={
                    "raw_order_id": coupon.raw_order_id,
                    "referenced_order_id": _referenced_order_business_id(
                        session, coupon
                    ),
                },
            )
            continue
        order_status = _dual_order_status(order)
        if order_status == "closed":
            continue
        if order_status == "unknown":
            blocked_count += _block_dual_fee(
                session,
                calculation_run_id,
                coupon,
                order,
                "dual_fee_unknown_order_status",
                "订单状态无法标准化，双费用方向均已阻断。",
                directions=(PROMOTION_FEE, MANAGEMENT_FEE),
            )
            continue

        for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
            current = _current_fee_result(session, coupon.coupon_id, direction)
            run_result = _calculation_run_result(
                session, coupon.coupon_id, direction, calculation_run_id
            )
            if run_result is not None:
                if current is None and run_result.result_status == ACTIVE_FEE_RESULT:
                    _reattach_active_calculation_result(session, run_result)
                continue
            blocked_count += int(
                not _materialize_dual_fee_direction(
                    session,
                    order=order,
                    coupon=coupon,
                    direction=direction,
                    calculation_run_id=calculation_run_id,
                    current=current,
                    force_recalculate=force_recalculate,
                )
            )

        _materialize_refund_adjustments(
            session,
            coupon=coupon,
            calculation_run_id=calculation_run_id,
        )
        _materialize_verify_cancellation_adjustment(
            session,
            coupon=coupon,
            calculation_run_id=calculation_run_id,
        )

    session.flush()
    if bounded_coupon_ids is None:
        result_count = _model_count(session, SettlementFeeResult) - before_results
        adjustment_count = _model_count(session, SettlementFeeAdjustment) - before_adjustments
    else:
        result_count = (
            _scoped_model_count(session, SettlementFeeResult, bounded_coupon_ids)
            - before_results
        )
        adjustment_count = (
            _scoped_model_count(session, SettlementFeeAdjustment, bounded_coupon_ids)
            - before_adjustments
        )
    return DualFeeStats(
        result_count=result_count,
        adjustment_count=adjustment_count,
        blocked_count=blocked_count,
    )


def _materialize_dual_fee_direction(
    session: Session,
    *,
    order: RawDouyinOrder,
    coupon: RawDouyinOrderCoupon,
    direction: int,
    calculation_run_id: str,
    current: SettlementFeeResult | None,
    force_recalculate: bool = False,
) -> bool:
    direction_name = "promotion" if direction == PROMOTION_FEE else "management"
    product = (
        session.scalar(
            select(DimSkuProductRule).where(DimSkuProductRule.sku_id == order.sku_id)
        )
        if order.sku_id
        else None
    )
    if product is None or not product.is_active_product:
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            "dual_fee_inactive_or_unknown_sku",
            "SKU 不存在或不是有效商品，费用方向已阻断。",
            directions=(direction,),
            context={"direction": direction_name, "sku_id": order.sku_id},
        )
        return False

    product_owner_account_id = _first_text(product.owner_account_id)
    if not product_owner_account_id:
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            "dual_fee_unstable_owner_account",
            "商品主数据缺少稳定归属账号 ID，费用方向已阻断。",
            directions=(direction,),
            context={
                "direction": direction_name,
                "product_owner_account_id": product.owner_account_id,
            },
        )
        return False

    sale_owner_account_id = _first_text(order.owner_account_id)
    sale_account = (
        session.get(DimAwemeAccount, sale_owner_account_id)
        if sale_owner_account_id
        else None
    )
    if (
        sale_account is None
        or not sale_account.store_id
        or not _is_active_binding_status(sale_account.binding_status)
        or session.get(DimStore, sale_account.store_id) is None
    ):
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            "dual_fee_missing_sale_store",
            "稳定归属账号未映射到有效销售门店，费用方向已阻断。",
            directions=(direction,),
            context={
                "direction": direction_name,
                "sale_owner_account_id": sale_owner_account_id,
            },
        )
        return False

    channel = _dual_sale_channel(order)
    if channel not in {"live", "short_video"}:
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            "dual_fee_unknown_or_out_of_scope_channel",
            "销售渠道不是已确认的直播或短视频，费用方向已阻断。",
            directions=(direction,),
            context={"direction": direction_name, "sale_channel": channel},
        )
        return False

    sale_time = _first_datetime(order.sale_time, order.pay_time)
    sale_business_date = _business_date(sale_time)
    if sale_business_date is None:
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            "dual_fee_missing_business_time",
            "订单缺少销售业务时间，费用方向已阻断。",
            directions=(direction,),
            context={"direction": direction_name},
        )
        return False
    if sale_business_date < FORMAL_SETTLEMENT_START:
        # Management also requires the corresponding sale to be in the formal window.
        return True
    verify: RawDouyinVerifyRecord | None = None
    verify_store_id: str | None = None
    if direction == PROMOTION_FEE:
        business_time = sale_time
        responsible_store_id = sale_account.store_id
    else:
        verify = _select_valid_verify_record(session, coupon.coupon_id)
        if verify is None or verify.verify_time is None:
            _block_dual_fee(
                session,
                calculation_run_id,
                coupon,
                order,
                "dual_fee_missing_valid_verify",
                "管理服务费缺少有效核销记录，费用方向已阻断。",
                directions=(direction,),
                context={"direction": direction_name},
            )
            return False
        poi_mapping = _find_poi_mapping(session, verify.poi_id)
        if poi_mapping is None or session.get(DimStore, poi_mapping.store_id) is None:
            _block_dual_fee(
                session,
                calculation_run_id,
                coupon,
                order,
                "dual_fee_missing_verify_store",
                "管理服务费核销 POI 未映射到有效门店，费用方向已阻断。",
                directions=(direction,),
                context={"direction": direction_name, "verify_id": verify.verify_id},
            )
            return False
        verify_store_id = poi_mapping.store_id
        business_time = verify.verify_time
        responsible_store_id = verify_store_id

    business_date = _business_date(business_time)
    if business_date is None or business_date < FORMAL_SETTLEMENT_START:
        if business_date is None:
            _block_dual_fee(
                session,
                calculation_run_id,
                coupon,
                order,
                "dual_fee_missing_business_time",
                "费用方向缺少业务时间，已阻断。",
                directions=(direction,),
                context={"direction": direction_name},
            )
            return False
        return True
    business_month = business_date.strftime("%Y-%m")

    scope_rule = _match_scope_rule(
        session,
        business_month=business_month,
        owner_account_id=product_owner_account_id,
        channel=channel,
    )
    if scope_rule is None:
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            "dual_fee_missing_scope_rule",
            "业务月份、归属账号与渠道未命中有效结算范围，费用方向已阻断。",
            directions=(direction,),
            context={"direction": direction_name, "business_month": business_month},
        )
        return False

    fee_rule = _match_fee_rule(session, product.sku_id, business_date)
    if fee_rule is None:
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            "dual_fee_missing_fee_rule",
            "业务日未命中有效 SKU 双费率版本，费用方向已阻断。",
            directions=(direction,),
            context={"direction": direction_name, "rule_match_date": str(business_date)},
        )
        return False

    source_amount = _direction_source_amount(session, order, coupon, verify)
    if source_amount is None:
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            "dual_fee_missing_coupon_amount",
            "多券订单缺少单券实付金额，禁止重复使用整单金额。",
            directions=(direction,),
            context={"direction": direction_name},
        )
        return False
    if current is None:
        event_refunded_amount = 0
        for refund_event in _resolved_refund_events(session, coupon=coupon):
            if refund_event.refund_type == 2:
                event_refunded_amount = source_amount
                break
            event_refunded_amount = min(
                source_amount,
                event_refunded_amount + refund_event.refund_amount_cent,
            )
        refunded_amount = min(
            source_amount,
            max(_coupon_refunded_amount(coupon), event_refunded_amount),
        )
        if _dual_order_status(order) == "refunded" or _normalized(
            coupon.coupon_status_normalized or coupon.coupon_status
        ) == "refunded":
            refunded_amount = source_amount
    else:
        # Recalculation changes rules/version, never the historical refund cutoff.
        # Events observed after the prior result remain event-month adjustments.
        refunded_amount = min(source_amount, current.refunded_amount_cent)
    fee_base = max(source_amount - refunded_amount, 0)
    fee_rate = Decimal(
        fee_rule.promotion_service_fee_rate
        if direction == PROMOTION_FEE
        else fee_rule.management_service_fee_rate
    )
    fee_amount = _commission_cent(fee_base, fee_rate)

    input_fingerprint = _fee_result_input_fingerprint(
        coupon_id=coupon.coupon_id,
        order_id=order.order_id,
        fee_direction=direction,
        original_business_month=business_month,
        rule_match_date=business_date,
        sale_store_id=sale_account.store_id,
        verify_store_id=verify_store_id,
        sku_id=product.sku_id,
        product_scope=product.product_scope,
        product_type=product.product_type,
        sale_channel_normalized=channel,
        source_amount_cent=source_amount,
        refunded_amount_cent=refunded_amount,
        fee_base_cent=fee_base,
        fee_rate=fee_rate,
        fee_amount_cent=fee_amount,
        rule_version=fee_rule.rule_version,
        scope_rule_version=scope_rule.scope_rule_version,
        result_status=ACTIVE_FEE_RESULT,
    )
    if (
        current is not None
        and current.input_fingerprint == input_fingerprint
        and not force_recalculate
    ):
        return True

    _lock_settlement_slot(session, responsible_store_id, business_month)
    if _is_fee_result_locked(
        session,
        store_id=responsible_store_id,
        month=business_month,
        current_fee_result_id=current.fee_result_id if current else None,
    ):
        issue_type = (
            "dual_fee_locked_recalculation"
            if current is not None
            else "dual_fee_locked_slot_materialization"
        )
        message = (
            "账单已锁定，禁止重算切换当前费用结果。"
            if current is not None
            else "账期已锁定，迟到券不得新增到已冻结账单之外。"
        )
        _block_dual_fee(
            session,
            calculation_run_id,
            coupon,
            order,
            issue_type,
            message,
            directions=(direction,),
            context={"direction": direction_name, "business_month": business_month},
        )
        return False

    version = _next_fee_result_version(session, coupon.coupon_id, direction)
    fee_result_id = _stable_business_id(
        "fee-result", coupon.coupon_id, str(direction), str(version)
    )
    if current is None:
        # An invalid-unlocked pass may have removed the pointer while leaving
        # historical ACTIVE rows.  Collapse every such anomaly before the new
        # pointer is created; the predicate also makes convergence deterministic
        # if multiple ACTIVE rows predate this repair.
        session.execute(
            update(SettlementFeeResult)
            .where(
                SettlementFeeResult.coupon_id == coupon.coupon_id,
                SettlementFeeResult.fee_direction == direction,
                SettlementFeeResult.result_status == ACTIVE_FEE_RESULT,
            )
            .values(result_status=SUPERSEDED_FEE_RESULT)
        )
    result = SettlementFeeResult(
        fee_result_id=fee_result_id,
        coupon_id=coupon.coupon_id,
        order_id=order.order_id,
        fee_direction=direction,
        result_version=version,
        original_business_month=business_month,
        rule_match_date=business_date,
        sale_store_id=sale_account.store_id,
        verify_store_id=verify_store_id,
        sku_id=product.sku_id,
        product_scope=product.product_scope,
        product_type=product.product_type,
        sale_channel_normalized=channel,
        source_amount_cent=source_amount,
        refunded_amount_cent=refunded_amount,
        fee_base_cent=fee_base,
        fee_rate=fee_rate,
        fee_amount_cent=fee_amount,
        rule_version=fee_rule.rule_version,
        scope_rule_version=scope_rule.scope_rule_version,
        result_status=ACTIVE_FEE_RESULT,
        calculation_run_id=calculation_run_id,
        input_fingerprint=input_fingerprint,
        calculated_at=utcnow(),
    )
    session.add(result)
    session.flush()
    if current is None:
        session.add(
            SettlementFeeResultCurrent(
                coupon_id=coupon.coupon_id,
                fee_direction=direction,
                fee_result_id=fee_result_id,
            )
        )
    else:
        current.result_status = SUPERSEDED_FEE_RESULT
        pointer = session.scalar(
            select(SettlementFeeResultCurrent).where(
                SettlementFeeResultCurrent.coupon_id == coupon.coupon_id,
                SettlementFeeResultCurrent.fee_direction == direction,
            )
        )
        assert pointer is not None
        pointer.fee_result_id = fee_result_id
    session.flush()
    return True


def _materialize_refund_adjustments(
    session: Session,
    *,
    coupon: RawDouyinOrderCoupon,
    calculation_run_id: str,
) -> None:
    events = _resolved_refund_events(
        session,
        coupon=coupon,
        calculation_run_id=calculation_run_id,
        record_ambiguous=True,
    )
    if not events:
        return
    for direction in (PROMOTION_FEE, MANAGEMENT_FEE):
        original = _current_fee_result(session, coupon.coupon_id, direction)
        if original is None:
            continue
        if direction == MANAGEMENT_FEE and session.scalar(
            select(SettlementFeeAdjustment.id).where(
                SettlementFeeAdjustment.original_fee_result_id
                == original.fee_result_id,
                SettlementFeeAdjustment.fee_direction == MANAGEMENT_FEE,
                SettlementFeeAdjustment.adjustment_type == 3,
            )
        ):
            # Cancellation already zeroed the management fee. A later refund
            # must not append another reduction and make the net amount negative.
            continue
        cumulative_refund = original.refunded_amount_cent
        event_refund_total = 0
        applied_base_adjustment = 0
        applied_fee_adjustment = 0
        for event in events:
            if event.refund_type == 2:
                event_refund_total = original.source_amount_cent
            else:
                event_refund_total = min(
                    original.source_amount_cent,
                    event_refund_total + event.refund_amount_cent,
                )
            snapshot_covers_event = (
                _refund_event_observed_at(event)
                <= _as_utc(original.calculated_at)
                and original.refunded_amount_cent >= event_refund_total
            )
            if snapshot_covers_event:
                # Timestamp equality is possible on coarse clocks; the amount
                # snapshot proves whether this event was actually included.
                continue
            source_event_key = f"refund:{event.refund_event_id}"
            existing_source = _carryforward_source(
                session,
                source_event_key=source_event_key,
                original_fee_result_id=original.fee_result_id,
                fee_direction=direction,
            )
            if existing_source is not None:
                if event.refund_type == 2:
                    cumulative_refund = original.source_amount_cent
                else:
                    cumulative_refund = min(
                        original.source_amount_cent,
                        cumulative_refund + event.refund_amount_cent,
                    )
                applied_base_adjustment += existing_source.adjustment_base_cent
                applied_fee_adjustment += existing_source.adjustment_fee_cent
                _record_issue(
                    session,
                    issue_type="dual_fee_carryforward_source_idempotent",
                    message="顺延来源已存在，重复任务幂等命中。",
                    order_id=original.order_id,
                    coupon_id=original.coupon_id,
                    source_run_id=calculation_run_id,
                    raw_context={
                        "carryforward_source_id": existing_source.carryforward_source_id,
                        "fee_direction": direction,
                    },
                    identity_suffix=existing_source.carryforward_source_id,
                )
                continue
            adjustment_id = _stable_business_id(
                "refund-adjustment",
                event.refund_event_id,
                original.fee_result_id,
                str(direction),
            )
            existing = session.scalar(
                select(SettlementFeeAdjustment).where(
                    SettlementFeeAdjustment.adjustment_id == adjustment_id
                )
            )
            if existing is not None:
                if event.refund_type == 2:
                    cumulative_refund = original.source_amount_cent
                else:
                    cumulative_refund = min(
                        original.source_amount_cent,
                        cumulative_refund + event.refund_amount_cent,
                    )
                applied_base_adjustment += existing.adjustment_base_cent
                applied_fee_adjustment += existing.adjustment_fee_cent
                continue
            responsible_store_id = (
                original.sale_store_id
                if direction == PROMOTION_FEE
                else original.verify_store_id
            )
            if not responsible_store_id:
                raise ValueError(
                    f"refund adjustment has no responsible store: {original.fee_result_id}"
                )
            if event.refund_type == 2:
                cumulative_refund = original.source_amount_cent
            else:
                cumulative_refund = min(
                    original.source_amount_cent,
                    cumulative_refund + event.refund_amount_cent,
                )
            target_base = max(original.source_amount_cent - cumulative_refund, 0)
            target_fee = _commission_cent(target_base, Decimal(original.fee_rate))
            adjustment_base = (
                target_base - original.fee_base_cent - applied_base_adjustment
            )
            adjustment_fee = (
                target_fee - original.fee_amount_cent - applied_fee_adjustment
            )
            adjustment_reason = (
                "全额退款，按原规则版本将费用净额调整为零。"
                if event.refund_type == 2
                else "部分退款，按退款后净额和原规则版本同比例调减费用。"
            )
            posting_month = _business_month(event.occurred_at)
            _lock_settlement_slot(session, responsible_store_id, posting_month)
            if _is_fee_result_locked(
                session,
                store_id=responsible_store_id,
                month=posting_month,
            ):
                source = _create_carryforward_source(
                    session,
                    source_event_type=1,
                    source_event_key=source_event_key,
                    original=original,
                    refund_event_id=event.refund_event_id,
                    verify_id=None,
                    store_id=responsible_store_id,
                    event_month=posting_month,
                    adjustment_type=event.refund_type,
                    adjustment_base_cent=adjustment_base,
                    adjustment_fee_cent=adjustment_fee,
                    carryforward_reason=adjustment_reason,
                    occurred_at=event.occurred_at,
                    calculation_run_id=calculation_run_id,
                )
                _record_issue(
                    session,
                    issue_type="dual_fee_locked_adjustment_posting_month",
                    message="调整事件月已锁定，退款差额已保存并等待顺延。",
                    order_id=original.order_id,
                    coupon_id=original.coupon_id,
                    source_run_id=calculation_run_id,
                    raw_context={
                        "fee_direction": direction,
                        "refund_event_id": event.refund_event_id,
                        "store_id": responsible_store_id,
                        "posting_month": posting_month,
                        "carryforward_source_id": source.carryforward_source_id,
                    },
                    identity_suffix=f"{event.refund_event_id}:{direction}",
                )
                applied_base_adjustment += source.adjustment_base_cent
                applied_fee_adjustment += source.adjustment_fee_cent
                continue
            session.add(
                SettlementFeeAdjustment(
                    adjustment_id=adjustment_id,
                    original_fee_result_id=original.fee_result_id,
                    refund_event_id=event.refund_event_id,
                    coupon_id=original.coupon_id,
                    order_id=original.order_id,
                    fee_direction=direction,
                    original_business_month=original.original_business_month,
                    adjustment_posting_month=_business_month(event.occurred_at),
                    adjustment_type=event.refund_type,
                    adjustment_base_cent=adjustment_base,
                    adjustment_fee_cent=adjustment_fee,
                    rule_version=original.rule_version,
                    adjustment_reason=adjustment_reason,
                    occurred_at=event.occurred_at,
                    created_by=f"settlement:{calculation_run_id}",
                )
            )
            session.flush()
            applied_base_adjustment += adjustment_base
            applied_fee_adjustment += adjustment_fee


def _persist_adjustment_idempotently(
    session: Session, adjustment: SettlementFeeAdjustment
) -> tuple[SettlementFeeAdjustment, bool]:
    """Insert one append-only adjustment and converge on a unique race."""

    try:
        with session.begin_nested():
            session.add(adjustment)
            session.flush()
    except IntegrityError:
        if adjustment.refund_event_id is None:
            existing = session.scalar(
                select(SettlementFeeAdjustment).where(
                    SettlementFeeAdjustment.adjustment_id == adjustment.adjustment_id
                )
            )
        else:
            existing = session.scalar(
                select(SettlementFeeAdjustment).where(
                    SettlementFeeAdjustment.refund_event_id
                    == adjustment.refund_event_id,
                    SettlementFeeAdjustment.original_fee_result_id
                    == adjustment.original_fee_result_id,
                    SettlementFeeAdjustment.fee_direction == adjustment.fee_direction,
                )
            )
        if existing is None:
            raise
        return existing, False
    return adjustment, True


def _resolved_refund_events(
    session: Session,
    *,
    coupon: RawDouyinOrderCoupon,
    calculation_run_id: str | None = None,
    record_ambiguous: bool = False,
) -> list[DouyinRefundEvent]:
    direct_events = list(
        session.scalars(
            select(DouyinRefundEvent).where(
                DouyinRefundEvent.coupon_id == coupon.coupon_id,
                DouyinRefundEvent.order_id == coupon.order_id,
                DouyinRefundEvent.refund_status == SUCCESSFUL_REFUND,
            )
        )
    )
    order_events = list(
        session.scalars(
            select(DouyinRefundEvent).where(
                DouyinRefundEvent.order_id == coupon.order_id,
                DouyinRefundEvent.coupon_id.is_(None),
                DouyinRefundEvent.refund_status == SUCCESSFUL_REFUND,
            )
        )
    )
    if order_events:
        coupon_count = int(
            session.scalar(
                select(func.count())
                .select_from(RawDouyinOrderCoupon)
                .where(RawDouyinOrderCoupon.raw_order_id == coupon.raw_order_id)
            )
            or 0
        )
        if coupon_count == 1:
            direct_events.extend(order_events)
        elif record_ambiguous and calculation_run_id:
            for event in order_events:
                _record_issue(
                    session,
                    issue_type="dual_fee_ambiguous_order_level_refund",
                    message="多券订单的退款事件缺少券 ID，禁止猜测分摊到具体券。",
                    order_id=coupon.order_id,
                    coupon_id=None,
                    source_run_id=calculation_run_id,
                    severity="error",
                    raw_context={
                        "refund_event_id": event.refund_event_id,
                        "coupon_count": coupon_count,
                    },
                    identity_suffix=event.refund_event_id,
                )
    return sorted(
        direct_events,
        key=lambda event: (event.occurred_at, event.refund_event_id),
    )


def _refund_event_observed_at(event: DouyinRefundEvent) -> datetime:
    observed_at = event.successful_observed_at or event.created_at
    return _as_utc(observed_at or event.occurred_at)


def _materialize_verify_cancellation_adjustment(
    session: Session,
    *,
    coupon: RawDouyinOrderCoupon,
    calculation_run_id: str,
) -> None:
    cancelled = session.scalar(
        select(RawDouyinVerifyRecord)
        .where(
            RawDouyinVerifyRecord.coupon_id == coupon.coupon_id,
            RawDouyinVerifyRecord.cancel_time.is_not(None),
        )
        .order_by(RawDouyinVerifyRecord.cancel_time.desc())
    )
    if cancelled is None or cancelled.cancel_time is None:
        return
    original = _current_fee_result(session, coupon.coupon_id, MANAGEMENT_FEE)
    if original is None:
        return
    if not original.verify_store_id:
        raise ValueError(
            f"verification cancellation has no responsible store: {original.fee_result_id}"
        )
    adjustment_id = _stable_business_id(
        "verify-cancellation",
        cancelled.verify_id,
        _as_utc(cancelled.cancel_time).isoformat(timespec="microseconds"),
        original.fee_result_id,
    )
    if session.scalar(
        select(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.adjustment_id == adjustment_id
        )
    ):
        return
    source_event_key = (
        "verify-cancellation:"
        f"{cancelled.verify_id}:"
        f"{_as_utc(cancelled.cancel_time).isoformat(timespec='microseconds')}"
    )
    existing_source = _carryforward_source(
        session,
        source_event_key=source_event_key,
        original_fee_result_id=original.fee_result_id,
        fee_direction=MANAGEMENT_FEE,
    )
    if existing_source is not None:
        _record_issue(
            session,
            issue_type="dual_fee_carryforward_source_idempotent",
            message="顺延来源已存在，重复任务幂等命中。",
            order_id=original.order_id,
            coupon_id=original.coupon_id,
            source_run_id=calculation_run_id,
            raw_context={
                "carryforward_source_id": existing_source.carryforward_source_id,
                "fee_direction": MANAGEMENT_FEE,
            },
            identity_suffix=existing_source.carryforward_source_id,
        )
        return
    existing_base, existing_fee = _effective_adjustment_totals(
        session,
        original_fee_result_id=original.fee_result_id,
    )
    adjustment_base = -original.fee_base_cent - existing_base
    adjustment_fee = -original.fee_amount_cent - existing_fee
    adjustment_reason = "取消核销，仅将管理服务费按原规则版本调整为零。"
    posting_month = _business_month(cancelled.cancel_time)
    _lock_settlement_slot(session, original.verify_store_id, posting_month)
    if _is_fee_result_locked(
        session,
        store_id=original.verify_store_id,
        month=posting_month,
    ):
        source = _create_carryforward_source(
            session,
            source_event_type=2,
            source_event_key=source_event_key,
            original=original,
            refund_event_id=None,
            verify_id=cancelled.verify_id,
            store_id=original.verify_store_id,
            event_month=posting_month,
            adjustment_type=3,
            adjustment_base_cent=adjustment_base,
            adjustment_fee_cent=adjustment_fee,
            carryforward_reason=adjustment_reason,
            occurred_at=cancelled.cancel_time,
            calculation_run_id=calculation_run_id,
        )
        _record_issue(
            session,
            issue_type="dual_fee_locked_adjustment_posting_month",
            message="调整事件月已锁定，取消核销差额已保存并等待顺延。",
            order_id=original.order_id,
            coupon_id=original.coupon_id,
            source_run_id=calculation_run_id,
            raw_context={
                "fee_direction": MANAGEMENT_FEE,
                "verify_id": cancelled.verify_id,
                "store_id": original.verify_store_id,
                "posting_month": posting_month,
                "carryforward_source_id": source.carryforward_source_id,
            },
            identity_suffix=f"{cancelled.verify_id}:{MANAGEMENT_FEE}",
        )
        return
    session.add(
        SettlementFeeAdjustment(
            adjustment_id=adjustment_id,
            original_fee_result_id=original.fee_result_id,
            refund_event_id=None,
            coupon_id=original.coupon_id,
            order_id=original.order_id,
            fee_direction=MANAGEMENT_FEE,
            original_business_month=original.original_business_month,
            adjustment_posting_month=_business_month(cancelled.cancel_time),
            adjustment_type=3,
            adjustment_base_cent=adjustment_base,
            adjustment_fee_cent=adjustment_fee,
            rule_version=original.rule_version,
            adjustment_reason=adjustment_reason,
            occurred_at=cancelled.cancel_time,
            created_by=f"settlement:{calculation_run_id}",
        )
    )
    session.flush()


def _carryforward_source(
    session: Session,
    *,
    source_event_key: str,
    original_fee_result_id: str,
    fee_direction: int,
) -> SettlementCarryforwardSource | None:
    return session.scalar(
        select(SettlementCarryforwardSource).where(
            SettlementCarryforwardSource.source_event_key == source_event_key,
            SettlementCarryforwardSource.original_fee_result_id
            == original_fee_result_id,
            SettlementCarryforwardSource.fee_direction == fee_direction,
        )
    )

def _effective_adjustment_totals(
    session: Session,
    *,
    original_fee_result_id: str,
) -> tuple[int, int]:
    """Count every business delta once, whether pending or already applied."""

    sources = list(
        session.scalars(
            select(SettlementCarryforwardSource).where(
                SettlementCarryforwardSource.original_fee_result_id
                == original_fee_result_id
            )
        )
    )
    source_ids = {source.carryforward_source_id for source in sources}
    materialized_adjustment_ids = (
        set(
            session.scalars(
                select(SettlementCarryforwardApplication.target_adjustment_id).where(
                    SettlementCarryforwardApplication.carryforward_source_id.in_(
                        source_ids
                    )
                )
            )
        )
        if source_ids
        else set()
    )
    ordinary_adjustments = [
        adjustment
        for adjustment in session.scalars(
            select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.original_fee_result_id
                == original_fee_result_id
            )
        )
        if adjustment.adjustment_id not in materialized_adjustment_ids
    ]
    return (
        sum(row.adjustment_base_cent for row in sources)
        + sum(row.adjustment_base_cent for row in ordinary_adjustments),
        sum(row.adjustment_fee_cent for row in sources)
        + sum(row.adjustment_fee_cent for row in ordinary_adjustments),
    )

def _create_carryforward_source(
    session: Session,
    *,
    source_event_type: int,
    source_event_key: str,
    original: SettlementFeeResult,
    refund_event_id: str | None,
    verify_id: str | None,
    store_id: str,
    event_month: str,
    adjustment_type: int,
    adjustment_base_cent: int,
    adjustment_fee_cent: int,
    carryforward_reason: str,
    occurred_at: datetime,
    calculation_run_id: str,
) -> SettlementCarryforwardSource:
    existing = _carryforward_source(
        session,
        source_event_key=source_event_key,
        original_fee_result_id=original.fee_result_id,
        fee_direction=original.fee_direction,
    )
    if existing is not None:
        return existing
    source = SettlementCarryforwardSource(
        carryforward_source_id=_stable_business_id(
            "carryforward-source",
            source_event_key,
            original.fee_result_id,
            str(original.fee_direction),
        ),
        source_event_type=source_event_type,
        source_event_key=source_event_key,
        original_fee_result_id=original.fee_result_id,
        refund_event_id=refund_event_id,
        verify_id=verify_id,
        coupon_id=original.coupon_id,
        order_id=original.order_id,
        store_id=store_id,
        fee_direction=original.fee_direction,
        original_business_month=original.original_business_month,
        event_month=event_month,
        adjustment_type=adjustment_type,
        adjustment_base_cent=adjustment_base_cent,
        adjustment_fee_cent=adjustment_fee_cent,
        rule_version=original.rule_version,
        carryforward_reason=carryforward_reason,
        occurred_at=occurred_at,
        created_by=f"settlement:{calculation_run_id}",
    )
    session.add(source)
    session.flush()
    return source


def _match_scope_rule(
    session: Session,
    *,
    business_month: str,
    owner_account_id: str,
    channel: str,
) -> SettlementScopeRule | None:
    return session.scalar(
        select(SettlementScopeRule).where(
            SettlementScopeRule.effective_month == business_month,
            SettlementScopeRule.owner_account_id == owner_account_id,
            SettlementScopeRule.sale_channel_normalized == channel,
            SettlementScopeRule.is_active.is_(True),
        )
    )


def _match_fee_rule(
    session: Session, sku_id: str, business_date: date
) -> SkuFeeRule | None:
    latest_rule = session.scalar(
        select(SkuFeeRule)
        .where(
            SkuFeeRule.sku_id == sku_id,
            SkuFeeRule.effective_date <= business_date,
        )
        .order_by(SkuFeeRule.effective_date.desc(), SkuFeeRule.id.desc())
        .limit(1)
    )
    if latest_rule is None or latest_rule.rule_status != ACTIVE_FEE_RULE:
        return None
    return latest_rule


def _direction_source_amount(
    session: Session,
    order: RawDouyinOrder,
    coupon: RawDouyinOrderCoupon,
    verify: RawDouyinVerifyRecord | None,
) -> int | None:
    if verify is not None and verify.paid_amount_cent is not None:
        return max(verify.paid_amount_cent, 0)
    if coupon.coupon_paid_amount_cent is not None:
        return max(coupon.coupon_paid_amount_cent, 0)
    coupon_count = session.scalar(
        select(func.count()).select_from(RawDouyinOrderCoupon).where(
            RawDouyinOrderCoupon.raw_order_id == order.id
        )
    )
    if int(coupon_count or 0) != 1:
        return None
    amount = order.order_paid_amount_cent
    if amount == 0 and order.paid_amount_cent is not None:
        amount = order.paid_amount_cent
    return max(amount, 0)


def _coupon_refunded_amount(coupon: RawDouyinOrderCoupon) -> int:
    amount = coupon.coupon_refunded_amount_cent
    if amount == 0 and coupon.coupon_refunded_cent is not None:
        amount = coupon.coupon_refunded_cent
    return max(amount, 0)


def _raw_order_for_coupon(
    session: Session, coupon: RawDouyinOrderCoupon
) -> RawDouyinOrder | None:
    """Resolve the internal order link without guessing from a business ID."""

    order = session.get(RawDouyinOrder, coupon.raw_order_id)
    if order is None or order.order_id != coupon.order_id:
        return None
    return order


def _referenced_order_business_id(
    session: Session, coupon: RawDouyinOrderCoupon
) -> str | None:
    """Return the business ID behind a coupon's internal order reference."""

    order = session.get(RawDouyinOrder, coupon.raw_order_id)
    return order.order_id if order is not None else None


def _current_fee_result(
    session: Session, coupon_id: str, direction: int
) -> SettlementFeeResult | None:
    pointer = session.scalar(
        select(SettlementFeeResultCurrent).where(
            SettlementFeeResultCurrent.coupon_id == coupon_id,
            SettlementFeeResultCurrent.fee_direction == direction,
        )
    )
    if pointer is None:
        return None
    return session.scalar(
        select(SettlementFeeResult).where(
            SettlementFeeResult.fee_result_id == pointer.fee_result_id
        )
    )


def _calculation_run_result(
    session: Session, coupon_id: str, direction: int, calculation_run_id: str
) -> SettlementFeeResult | None:
    return session.scalar(
        select(SettlementFeeResult).where(
            SettlementFeeResult.coupon_id == coupon_id,
            SettlementFeeResult.fee_direction == direction,
            SettlementFeeResult.calculation_run_id == calculation_run_id,
        )
    )


def _reattach_active_calculation_result(
    session: Session, result: SettlementFeeResult
) -> None:
    pointer = session.scalar(
        select(SettlementFeeResultCurrent).where(
            SettlementFeeResultCurrent.coupon_id == result.coupon_id,
            SettlementFeeResultCurrent.fee_direction == result.fee_direction,
        )
    )
    if pointer is None:
        session.add(
            SettlementFeeResultCurrent(
                coupon_id=result.coupon_id,
                fee_direction=result.fee_direction,
                fee_result_id=result.fee_result_id,
            )
        )
        session.flush()


def _has_calculation_result(
    session: Session, coupon_id: str, direction: int, calculation_run_id: str
) -> bool:
    return _calculation_run_result(
        session, coupon_id, direction, calculation_run_id
    ) is not None


def _next_fee_result_version(
    session: Session, coupon_id: str, direction: int
) -> int:
    latest = session.scalar(
        select(func.max(SettlementFeeResult.result_version)).where(
            SettlementFeeResult.coupon_id == coupon_id,
            SettlementFeeResult.fee_direction == direction,
        )
    )
    return int(latest or 0) + 1


def _is_fee_result_locked(
    session: Session,
    *,
    store_id: str,
    month: str,
    current_fee_result_id: str | None = None,
) -> bool:
    if _is_settlement_period_immutable(session, store_id=store_id, month=month):
        return True
    if not current_fee_result_id:
        return False
    locked_source = session.scalar(
        select(SettlementStatementEntry.id)
        .join(
            SettlementStatement,
            SettlementStatement.statement_id == SettlementStatementEntry.statement_id,
        )
        .where(
            SettlementStatementEntry.source_type == 1,
            SettlementStatementEntry.source_record_id == current_fee_result_id,
            SettlementStatement.statement_status == 4,
        )
    )
    return bool(locked_source)


def _block_dual_fee(
    session: Session,
    calculation_run_id: str,
    coupon: RawDouyinOrderCoupon,
    order: RawDouyinOrder | None,
    issue_type: str,
    message: str,
    *,
    directions: tuple[int, ...],
    context: dict[str, Any] | None = None,
) -> int:
    for direction in directions:
        _record_issue(
            session,
            issue_type=issue_type,
            message=message,
            order_id=order.order_id if order else coupon.order_id,
            coupon_id=coupon.coupon_id,
            source_run_id=calculation_run_id,
            severity="error",
            raw_context={"fee_direction": direction, **(context or {})},
            identity_suffix=f"fee_direction:{direction}",
        )
    return len(directions)


def _dual_order_status(order: RawDouyinOrder) -> str:
    status = _normalized(order.order_status_normalized or order.order_status)
    if status in {"closed", "cancelled", "canceled", "unpaid_closed"}:
        return "closed"
    if status in {"paid", "success", "completed", "fulfilled"}:
        return "paid"
    if status in {"refunded", "refund", "fully_refunded"}:
        return "refunded"
    return "unknown"


def _dual_sale_channel(order: RawDouyinOrder) -> str:
    channel = _normalized(order.sale_channel_normalized or order.sale_channel)
    channel = channel.replace("-", "_")
    if channel in {"live", "live_stream", "livestream", "直播"}:
        return "live"
    if channel in {"short_video", "shortvideo", "video", "短视频"}:
        return "short_video"
    return channel or "unknown"


def _business_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI).date()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _business_month(value: datetime) -> str:
    business_date = _business_date(value)
    assert business_date is not None
    return business_date.strftime("%Y-%m")


def _first_datetime(*values: datetime | None) -> datetime | None:
    for value in values:
        if value is not None:
            return value
    return None


def _stable_business_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join((prefix, *parts))
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:40]}"


def _fee_result_input_fingerprint(
    *,
    coupon_id: str,
    order_id: str,
    fee_direction: int,
    original_business_month: str | None,
    rule_match_date: date | None,
    sale_store_id: str | None,
    verify_store_id: str | None,
    sku_id: str | None,
    product_scope: str | None,
    product_type: str | None,
    sale_channel_normalized: str | None,
    source_amount_cent: int,
    refunded_amount_cent: int,
    fee_base_cent: int,
    fee_rate: Decimal,
    fee_amount_cent: int,
    rule_version: str | None,
    scope_rule_version: str | None,
    result_status: int,
) -> str:
    """Return a deterministic SHA-256 over business inputs and result fields."""

    payload = {
        "coupon_id": coupon_id,
        "order_id": order_id,
        "fee_direction": fee_direction,
        "original_business_month": original_business_month,
        "rule_match_date": rule_match_date,
        "sale_store_id": sale_store_id,
        "verify_store_id": verify_store_id,
        "sku_id": sku_id,
        "product_scope": product_scope,
        "product_type": product_type,
        "sale_channel_normalized": sale_channel_normalized,
        "source_amount_cent": source_amount_cent,
        "refunded_amount_cent": refunded_amount_cent,
        "fee_base_cent": fee_base_cent,
        "fee_rate": fee_rate,
        "fee_amount_cent": fee_amount_cent,
        "rule_version": rule_version,
        "scope_rule_version": scope_rule_version,
        "result_status": result_status,
    }
    normalized = {
        key: _canonical_fingerprint_value(value)
        for key, value in payload.items()
    }
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_fingerprint_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, datetime):
        return _as_utc(value).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value
    return str(value)


def _lock_settlement_slot(
    session: Session, store_id: str, statement_month: str
) -> None:
    """Serialize calculation/adjustment and statement capture on one slot."""

    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        lock_key = f"settlement-slot:{store_id}:{statement_month}"
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )
        return
    session.scalar(
        select(DimStore.store_id)
        .where(DimStore.store_id == store_id)
        .with_for_update()
    )


def _model_count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _scoped_model_count(
    session: Session, model: type[Any], coupon_ids: tuple[str, ...]
) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.coupon_id.in_(coupon_ids))
        )
        or 0
    )


def lock_settlement_statement(
    session: Session,
    *,
    store_id: str,
    statement_month: str,
    lock_run_id: str,
) -> SettlementStatement:
    if statement_month < "2026-08":
        raise ValueError("formal settlement statements start at 2026-08")
    store = session.get(DimStore, store_id)
    if store is None:
        raise ValueError(f"unknown settlement store: {store_id}")

    statement: SettlementStatement | None = None
    statement_id = _stable_business_id("statement", store_id, statement_month)
    try:
        with session.begin_nested():
            # Shared with result/adjustment writers, including the absent statement case.
            _lock_settlement_slot(session, store_id, statement_month)
            statement = session.scalar(
                select(SettlementStatement)
                .where(
                    SettlementStatement.store_id == store_id,
                    SettlementStatement.statement_month == statement_month,
                    SettlementStatement.is_current.is_(True),
                )
                .with_for_update()
            )
            if statement is not None and statement.statement_status == 4:
                return statement
            if statement is None:
                basic_profile = session.scalar(
                    select(StoreFinanceProfile)
                    .where(
                        StoreFinanceProfile.store_id == store_id,
                        StoreFinanceProfile.profile_type == 1,
                        StoreFinanceProfile.is_current.is_(True),
                        StoreFinanceProfile.is_tombstone.is_(False),
                    )
                    .order_by(
                        StoreFinanceProfile.version_no.desc(),
                        StoreFinanceProfile.profile_id.desc(),
                    )
                    .limit(1)
                )
                statement = SettlementStatement(
                    statement_id=statement_id,
                    store_id=store_id,
                    statement_month=statement_month,
                    statement_status=1,
                    store_name_snapshot=store.store_name,
                    sap_code_snapshot=(
                        basic_profile.sap_code if basic_profile is not None else None
                    ),
                    store_snapshot_status="LIVE_CAPTURED",
                    store_snapshot_profile_id=(
                        basic_profile.profile_id if basic_profile is not None else None
                    ),
                )
                session.add(statement)
                session.flush()
            else:
                statement.statement_status = 1
                statement.locked_by = None
                statement.locked_at = None
                statement.lock_version = None
                session.execute(
                    delete(SettlementStatementEntry).where(
                        SettlementStatementEntry.statement_id == statement.statement_id
                    )
                )
                session.execute(
                    delete(SettlementStatementLine).where(
                        SettlementStatementLine.statement_id == statement.statement_id
                    )
                )
                session.flush()

            _apply_carryforward_sources(
                session,
                statement=statement,
                application_run_id=lock_run_id,
            )
            sources = _statement_sources(
                session, store_id=store_id, statement_month=statement_month
            )
            _assert_sources_unassigned(session, statement.statement_id, sources)
            grouped: dict[tuple[int, str, str], list[StatementSource]] = defaultdict(list)
            for source in sources:
                grouped[
                    (source.fee_direction, source.product_scope, source.product_type)
                ].append(source)

            for (direction, product_scope, product_type), line_sources in sorted(
                grouped.items()
            ):
                line_id = _stable_business_id(
                    "statement-line",
                    statement.statement_id,
                    str(direction),
                    product_scope,
                    product_type,
                )
                original_sources = [row for row in line_sources if row.source_type == 1]
                adjustment_sources = [row for row in line_sources if row.source_type == 2]
                original_base = sum(row.base_amount_cent for row in original_sources)
                adjustment_base = sum(
                    row.base_amount_cent for row in adjustment_sources
                )
                original_fee = sum(row.fee_amount_cent for row in original_sources)
                adjustment_fee = sum(
                    row.fee_amount_cent for row in adjustment_sources
                )
                session.add(
                    SettlementStatementLine(
                        statement_line_id=line_id,
                        statement_id=statement.statement_id,
                        fee_direction=direction,
                        product_scope=product_scope,
                        product_type=product_type,
                        original_entry_count=len(original_sources),
                        adjustment_entry_count=len(adjustment_sources),
                        original_base_cent=original_base,
                        adjustment_base_cent=adjustment_base,
                        net_base_cent=original_base + adjustment_base,
                        original_fee_cent=original_fee,
                        adjustment_fee_cent=adjustment_fee,
                        net_fee_cent=original_fee + adjustment_fee,
                    )
                )
                for source in line_sources:
                    session.add(
                        SettlementStatementEntry(
                            statement_entry_id=_stable_business_id(
                                "statement-entry",
                                str(source.source_type),
                                source.source_record_id,
                            ),
                            statement_id=statement.statement_id,
                            statement_line_id=line_id,
                            source_type=source.source_type,
                            source_record_id=source.source_record_id,
                            original_fee_result_id=source.original_fee_result_id,
                            coupon_id=source.coupon_id,
                            order_id=source.order_id,
                            fee_direction=source.fee_direction,
                            original_business_month=source.original_business_month,
                            statement_posting_month=source.posting_month,
                            product_scope=source.product_scope,
                            product_type=source.product_type,
                            base_amount_cent=source.base_amount_cent,
                            fee_amount_cent=source.fee_amount_cent,
                            rule_version=source.rule_version,
                            order_status_snapshot=source.order_status,
                            coupon_status_snapshot=source.coupon_status,
                            product_name_snapshot=source.product_name,
                            sku_id_snapshot=source.sku_id,
                            sku_name_snapshot=source.sku_name,
                            sale_channel_snapshot=source.sale_channel,
                            sale_store_id_snapshot=source.sale_store_id,
                            sale_store_snapshot=source.sale_store,
                            verify_store_id_snapshot=source.verify_store_id,
                            verify_store_snapshot=source.verify_store,
                            sale_time_snapshot=source.sale_time,
                            verify_time_snapshot=source.verify_time,
                            received_amount_cent_snapshot=source.received_amount_cent,
                            fee_rate_snapshot=source.fee_rate,
                            refund_at_snapshot=source.refund_at,
                            adjustment_type_snapshot=source.adjustment_type,
                        )
                    )
            session.flush()
            _apply_and_validate_statement_totals(session, statement)
            source_fingerprint = json.dumps(
                [
                    statement.statement_id,
                    [
                        [
                            row.source_type,
                            row.source_record_id,
                            row.base_amount_cent,
                            row.fee_amount_cent,
                        ]
                        for row in sources
                    ]
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            statement.statement_status = 4
            statement.locked_by = lock_run_id
            statement.locked_at = utcnow()
            statement.lock_version = (
                "lock-" + hashlib.sha256(source_fingerprint.encode("utf-8")).hexdigest()[:40]
            )
            session.flush()
    except Exception:
        _record_failure_issue(
            session,
            issue_type="settlement_statement_lock_failed",
            message="账单来源、汇总行与账单头一致性校验失败，未进入锁账状态。",
            order_id=None,
            coupon_id=None,
            source_run_id=lock_run_id,
            severity="error",
            raw_context={"store_id": store_id, "statement_month": statement_month},
        )
        raise
    assert statement is not None
    return statement


def _apply_carryforward_sources(
    session: Session,
    *,
    statement: SettlementStatement,
    application_run_id: str,
) -> None:
    candidates = list(
        session.scalars(
            select(SettlementCarryforwardSource)
            .where(
                SettlementCarryforwardSource.store_id == statement.store_id,
                SettlementCarryforwardSource.event_month < statement.statement_month,
            )
            .order_by(
                SettlementCarryforwardSource.occurred_at,
                SettlementCarryforwardSource.carryforward_source_id,
            )
            .with_for_update()
        )
    )
    for source in candidates:
        current_application = session.scalar(
            select(SettlementCarryforwardApplication).where(
                SettlementCarryforwardApplication.carryforward_source_id
                == source.carryforward_source_id,
                SettlementCarryforwardApplication.is_current.is_(True),
            )
        )
        if current_application is not None:
            _record_issue(
                session,
                issue_type="dual_fee_carryforward_application_idempotent",
                message="顺延来源已有当前有效应用，重复任务未再次入账。",
                order_id=source.order_id,
                coupon_id=source.coupon_id,
                source_run_id=application_run_id,
                raw_context={
                    "carryforward_source_id": source.carryforward_source_id,
                    "carryforward_application_id": (
                        current_application.carryforward_application_id
                    ),
                },
                identity_suffix=source.carryforward_source_id,
            )
            continue
        earlier_month = _first_unlocked_month_between(
            session,
            store_id=source.store_id,
            event_month=source.event_month,
            target_month=statement.statement_month,
        )
        if earlier_month is not None:
            _record_issue(
                session,
                issue_type="dual_fee_carryforward_waiting",
                message="顺延来源仍等待更早的可处理账期。",
                order_id=source.order_id,
                coupon_id=source.coupon_id,
                source_run_id=application_run_id,
                raw_context={
                    "carryforward_source_id": source.carryforward_source_id,
                    "earlier_unlocked_month": earlier_month,
                    "requested_month": statement.statement_month,
                },
                identity_suffix=source.carryforward_source_id,
            )
            continue
        original = session.scalar(
            select(SettlementFeeResult).where(
                SettlementFeeResult.fee_result_id == source.original_fee_result_id
            )
        )
        if original is None:
            _record_failure_issue(
                session,
                issue_type="dual_fee_carryforward_application_conflict",
                message="顺延来源缺少原始费用结果，禁止应用。",
                order_id=source.order_id,
                coupon_id=source.coupon_id,
                source_run_id=application_run_id,
                severity="error",
                raw_context={
                    "carryforward_source_id": source.carryforward_source_id,
                    "original_fee_result_id": source.original_fee_result_id,
                },
                identity_suffix=source.carryforward_source_id,
            )
            raise ValueError(
                "carryforward source has no original fee result: "
                f"{source.carryforward_source_id}"
            )
        latest_version = int(
            session.scalar(
                select(
                    func.coalesce(
                        func.max(
                            SettlementCarryforwardApplication.application_version
                        ),
                        0,
                    )
                ).where(
                    SettlementCarryforwardApplication.carryforward_source_id
                    == source.carryforward_source_id
                )
            )
            or 0
        )
        application_version = latest_version + 1
        adjustment_id = _stable_business_id(
            "carryforward-adjustment",
            source.carryforward_source_id,
            str(application_version),
        )
        session.add(
            SettlementFeeAdjustment(
                adjustment_id=adjustment_id,
                original_fee_result_id=source.original_fee_result_id,
                refund_event_id=source.refund_event_id,
                coupon_id=source.coupon_id,
                order_id=source.order_id,
                fee_direction=source.fee_direction,
                original_business_month=source.original_business_month,
                adjustment_posting_month=statement.statement_month,
                adjustment_type=source.adjustment_type,
                adjustment_base_cent=source.adjustment_base_cent,
                adjustment_fee_cent=source.adjustment_fee_cent,
                rule_version=source.rule_version,
                adjustment_reason=source.carryforward_reason,
                occurred_at=source.occurred_at,
                created_by=f"settlement:{application_run_id}",
            )
        )
        session.flush()
        application = SettlementCarryforwardApplication(
            carryforward_application_id=_stable_business_id(
                "carryforward-application",
                source.carryforward_source_id,
                str(application_version),
            ),
            carryforward_source_id=source.carryforward_source_id,
            target_statement_id=statement.statement_id,
            target_statement_version=statement.version_no,
            target_adjustment_id=adjustment_id,
            target_posting_month=statement.statement_month,
            application_version=application_version,
            is_current=True,
            applied_by=f"settlement:{application_run_id}",
            applied_at=utcnow(),
        )
        session.add(application)
        session.flush()
        _record_issue(
            session,
            issue_type="dual_fee_carryforward_applied",
            message="顺延来源已完整应用到下一可处理账期。",
            order_id=source.order_id,
            coupon_id=source.coupon_id,
            source_run_id=application_run_id,
            raw_context={
                "carryforward_source_id": source.carryforward_source_id,
                "carryforward_application_id": application.carryforward_application_id,
                "target_statement_id": statement.statement_id,
                "target_posting_month": statement.statement_month,
            },
            identity_suffix=source.carryforward_source_id,
        )


def _first_unlocked_month_between(
    session: Session,
    *,
    store_id: str,
    event_month: str,
    target_month: str,
) -> str | None:
    month = _next_month_key(event_month)
    while month < target_month:
        if not _is_settlement_period_immutable(
            session,
            store_id=store_id,
            month=month,
        ):
            return month
        month = _next_month_key(month)
    return None


def _next_month_key(month: str) -> str:
    year, month_number = (int(part) for part in month.split("-", 1))
    if month_number == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month_number + 1:02d}"


def rebuild_dual_fee_projections(
    session: Session, *, projection_run_id: str, batch_size: int = 1000
) -> StatementProjectionStats:
    if batch_size < 1 or batch_size > 10000:
        raise ValueError("batch_size must be between 1 and 10000")
    source_counts = {"processed": 0, "skipped": 0, "failed": 0}
    try:
        with session.begin_nested():
            return _rebuild_dual_fee_projections(
                session,
                projection_run_id=projection_run_id,
                batch_size=batch_size,
                source_counts=source_counts,
            )
    except Exception:
        source_counts["failed"] += 1
        _record_failure_issue(
            session,
            issue_type="dual_fee_projection_rebuild_failed",
            message="双费用投影重建失败，正式账期投影已回滚。",
            order_id=None,
            coupon_id=None,
            source_run_id=projection_run_id,
            severity="error",
            raw_context={"batch_size": batch_size, **source_counts},
        )
        raise


def _rebuild_dual_fee_projections(
    session: Session,
    *,
    projection_run_id: str,
    batch_size: int,
    source_counts: dict[str, int],
) -> StatementProjectionStats:
    projection_months = _projection_months(session)
    monthly_count = 0
    ranking_count = 0
    cumulative: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: {
            "sales_order_count": 0,
            "sales_amount_cent": 0,
            "verified_order_count": 0,
            "verified_amount_cent": 0,
            "promotion_net_fee_cent": 0,
            "management_net_fee_cent": 0,
        }
    )
    for month in projection_months:
        # Delete and rebuild one indexed month at a time. The nested transaction
        # keeps the public projection atomic while bounding locks and memory.
        session.execute(
            delete(AggStoreMonthlySettlement).where(
                AggStoreMonthlySettlement.month == month
            )
        )
        session.execute(
            delete(AggStoreRanking).where(AggStoreRanking.period_key == month)
        )
        monthly_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        for source in _projection_sources(
            session,
            posting_month=month,
            batch_size=batch_size,
            source_counts=source_counts,
        ):
            for product_scope, product_type in _projection_dimensions(
                source.product_scope, source.product_type
            ):
                key = (source.store_id, product_scope, product_type)
                row = monthly_rows.setdefault(key, _empty_monthly_projection())
                if source.source_type == 1 and source.fee_direction == PROMOTION_FEE:
                    row["sales_order_ids"].add(source.order_id)
                    row["sales_amount_cent"] += source.source_amount_cent
                    row["promotion_original_fee_cent"] += source.fee_amount_cent
                elif source.source_type == 1:
                    row["verified_order_ids"].add(source.order_id)
                    row["verified_amount_cent"] += source.source_amount_cent
                    row["management_original_fee_cent"] += source.fee_amount_cent
                elif source.fee_direction == PROMOTION_FEE:
                    row["promotion_adjustment_fee_cent"] += source.fee_amount_cent
                else:
                    row["management_adjustment_fee_cent"] += source.fee_amount_cent
                if source.fee_direction == PROMOTION_FEE:
                    row["promotion_base_cent"] += source.base_amount_cent
                else:
                    row["management_base_cent"] += source.base_amount_cent

        created_rows: list[AggStoreMonthlySettlement] = []
        for (store_id, product_scope, product_type), values in sorted(
            monthly_rows.items()
        ):
            statement = _locked_statement(session, store_id, month)
            promotion_original = values["promotion_original_fee_cent"]
            promotion_adjustment = values["promotion_adjustment_fee_cent"]
            management_original = values["management_original_fee_cent"]
            management_adjustment = values["management_adjustment_fee_cent"]
            row = AggStoreMonthlySettlement(
                month=month,
                store_id=store_id,
                product_scope=product_scope,
                product_type=product_type,
                sales_order_count=len(values["sales_order_ids"]),
                sales_amount_cent=values["sales_amount_cent"],
                verified_order_count=len(values["verified_order_ids"]),
                verified_amount_cent=values["verified_amount_cent"],
                promotion_base_cent=values["promotion_base_cent"],
                promotion_original_fee_cent=promotion_original,
                promotion_adjustment_fee_cent=promotion_adjustment,
                promotion_net_fee_cent=promotion_original + promotion_adjustment,
                management_base_cent=values["management_base_cent"],
                management_original_fee_cent=management_original,
                management_adjustment_fee_cent=management_adjustment,
                management_net_fee_cent=management_original + management_adjustment,
                statement_status=statement.statement_status if statement else 1,
                projection_run_id=projection_run_id,
                estimated_receivable_commission_cent=(
                    promotion_original + promotion_adjustment
                ),
                commissionable_total_cent=values["promotion_base_cent"],
                estimated_payable_commission_cent=(
                    management_original + management_adjustment
                ),
            )
            session.add(row)
            created_rows.append(row)
        session.flush()
        monthly_count += len(created_rows)
        if not created_rows:
            continue
        for row in created_rows:
            _add_target_ranking_row(
                session,
                period_type=1,
                period_key=month,
                store_id=row.store_id,
                product_scope=row.product_scope,
                product_type=row.product_type,
                sales_order_count=row.sales_order_count,
                sales_amount_cent=row.sales_amount_cent,
                verified_order_count=row.verified_order_count,
                verified_amount_cent=row.verified_amount_cent,
                promotion_net_fee_cent=row.promotion_net_fee_cent,
                management_net_fee_cent=row.management_net_fee_cent,
                projection_run_id=projection_run_id,
            )
            ranking_count += 1
            values = cumulative[(row.store_id, row.product_scope, row.product_type)]
            for field_name in values:
                values[field_name] += int(getattr(row, field_name))
        for (store_id, product_scope, product_type), values in sorted(
            cumulative.items()
        ):
            _add_target_ranking_row(
                session,
                period_type=2,
                period_key=month,
                store_id=store_id,
                product_scope=product_scope,
                product_type=product_type,
                projection_run_id=projection_run_id,
                **values,
            )
            ranking_count += 1
        session.flush()
    return StatementProjectionStats(
        monthly_count=monthly_count,
        ranking_count=ranking_count,
        processed_count=source_counts["processed"],
        skipped_count=source_counts["skipped"],
        failed_count=source_counts["failed"],
    )


def _projection_months(session: Session) -> list[str]:
    months: set[str] = set()
    month_queries = (
        select(SettlementStatement.statement_month).where(
            SettlementStatement.statement_status == 4
        ),
        select(SettlementFeeResult.original_business_month)
        .join(
            SettlementFeeResultCurrent,
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeResult.fee_result_id,
        ),
        select(AggStoreMonthlySettlement.month),
        select(AggStoreRanking.period_key),
    )
    for query in month_queries:
        months.update(str(value) for value in session.scalars(query.distinct()))
    months.update(
        adjustment.adjustment_posting_month
        for adjustment in _active_fee_adjustments(session)
    )
    return sorted(month for month in months if month >= "2026-08")


def _active_fee_adjustments(
    session: Session,
    *,
    posting_month: str | None = None,
) -> list[SettlementFeeAdjustment]:
    """Return ordinary adjustments plus only the current version per carryforward."""

    applications = list(session.scalars(select(SettlementCarryforwardApplication)))
    versioned_adjustment_ids = {
        row.target_adjustment_id for row in applications
    }
    current_adjustment_ids = {
        row.target_adjustment_id for row in applications if row.is_current
    }
    query = select(SettlementFeeAdjustment)
    if posting_month is not None:
        query = query.where(
            SettlementFeeAdjustment.adjustment_posting_month == posting_month
        )
    return [
        adjustment
        for adjustment in session.scalars(query)
        if adjustment.adjustment_id not in versioned_adjustment_ids
        or adjustment.adjustment_id in current_adjustment_ids
    ]


def _statement_sources(
    session: Session, *, store_id: str, statement_month: str
) -> list[StatementSource]:
    sources: list[StatementSource] = []
    current_results = list(
        session.scalars(
            select(SettlementFeeResult)
            .join(
                SettlementFeeResultCurrent,
                SettlementFeeResultCurrent.fee_result_id
                == SettlementFeeResult.fee_result_id,
            )
            .where(
                SettlementFeeResult.original_business_month == statement_month
            )
        )
    )
    for result in current_results:
        result_store = (
            result.sale_store_id
            if result.fee_direction == PROMOTION_FEE
            else result.verify_store_id
        )
        if result_store == store_id:
            sources.append(_result_statement_source(session, result))
    adjustments = _active_fee_adjustments(
        session,
        posting_month=statement_month,
    )
    for adjustment in adjustments:
        original = session.scalar(
            select(SettlementFeeResult).where(
                SettlementFeeResult.fee_result_id
                == adjustment.original_fee_result_id
            )
        )
        if original is None:
            raise ValueError(
                f"adjustment has no original result: {adjustment.adjustment_id}"
            )
        result_store = (
            original.sale_store_id
            if adjustment.fee_direction == PROMOTION_FEE
            else original.verify_store_id
        )
        if result_store == store_id:
            sources.append(_adjustment_statement_source(session, adjustment, original))
    sources.sort(key=lambda row: (row.source_type, row.source_record_id))
    return sources


def _assert_sources_unassigned(
    session: Session, statement_id: str, sources: list[StatementSource]
) -> None:
    for source in sources:
        existing = session.scalar(
            select(SettlementStatementEntry).where(
                SettlementStatementEntry.source_type == source.source_type,
                SettlementStatementEntry.source_record_id == source.source_record_id,
            )
        )
        if existing is not None and existing.statement_id != statement_id:
            raise ValueError(
                "settlement source already belongs to another statement: "
                f"{source.source_type}/{source.source_record_id}"
            )


def _apply_and_validate_statement_totals(
    session: Session, statement: SettlementStatement
) -> None:
    lines = list(
        session.scalars(
            select(SettlementStatementLine).where(
                SettlementStatementLine.statement_id == statement.statement_id
            )
        )
    )
    entries = list(
        session.scalars(
            select(SettlementStatementEntry).where(
                SettlementStatementEntry.statement_id == statement.statement_id
            )
        )
    )
    line_by_id = {line.statement_line_id: line for line in lines}
    for line in lines:
        line_entries = [
            entry for entry in entries if entry.statement_line_id == line.statement_line_id
        ]
        original_entries = [entry for entry in line_entries if entry.source_type == 1]
        adjustment_entries = [entry for entry in line_entries if entry.source_type == 2]
        expected = (
            len(original_entries),
            len(adjustment_entries),
            sum(entry.base_amount_cent for entry in original_entries),
            sum(entry.base_amount_cent for entry in adjustment_entries),
            sum(entry.fee_amount_cent for entry in original_entries),
            sum(entry.fee_amount_cent for entry in adjustment_entries),
        )
        actual = (
            line.original_entry_count,
            line.adjustment_entry_count,
            line.original_base_cent,
            line.adjustment_base_cent,
            line.original_fee_cent,
            line.adjustment_fee_cent,
        )
        if actual != expected:
            raise ValueError(f"statement line source totals mismatch: {line.statement_line_id}")
        if line.net_base_cent != line.original_base_cent + line.adjustment_base_cent:
            raise ValueError(f"statement line base equation mismatch: {line.statement_line_id}")
        if line.net_fee_cent != line.original_fee_cent + line.adjustment_fee_cent:
            raise ValueError(f"statement line fee equation mismatch: {line.statement_line_id}")
    if any(entry.statement_line_id not in line_by_id for entry in entries):
        raise ValueError("statement entry has no matching line")

    promotion_lines = [line for line in lines if line.fee_direction == PROMOTION_FEE]
    management_lines = [line for line in lines if line.fee_direction == MANAGEMENT_FEE]
    statement.promotion_original_fee_cent = sum(
        line.original_fee_cent for line in promotion_lines
    )
    statement.promotion_adjustment_fee_cent = sum(
        line.adjustment_fee_cent for line in promotion_lines
    )
    statement.promotion_net_fee_cent = sum(line.net_fee_cent for line in promotion_lines)
    statement.management_original_fee_cent = sum(
        line.original_fee_cent for line in management_lines
    )
    statement.management_adjustment_fee_cent = sum(
        line.adjustment_fee_cent for line in management_lines
    )
    statement.management_net_fee_cent = sum(line.net_fee_cent for line in management_lines)
    if (
        statement.promotion_net_fee_cent
        != statement.promotion_original_fee_cent
        + statement.promotion_adjustment_fee_cent
        or statement.management_net_fee_cent
        != statement.management_original_fee_cent
        + statement.management_adjustment_fee_cent
    ):
        raise ValueError("statement head fee equation mismatch")


def _projection_sources(
    session: Session,
    *,
    posting_month: str,
    batch_size: int,
    source_counts: dict[str, int],
) -> Iterator[StatementSource]:
    locked_entries = session.execute(
        select(
            SettlementStatementEntry,
            SettlementStatement.store_id,
            SettlementFeeResult.source_amount_cent,
        )
        .join(
            SettlementStatement,
            SettlementStatement.statement_id
            == SettlementStatementEntry.statement_id,
        )
        .join(
            SettlementFeeResult,
            SettlementFeeResult.fee_result_id
            == SettlementStatementEntry.original_fee_result_id,
        )
        .where(
            SettlementStatement.statement_status == 4,
            SettlementStatement.is_current.is_(True),
            SettlementStatement.statement_month == posting_month,
        )
        .execution_options(yield_per=batch_size)
    )
    for entry, store_id, source_amount_cent in locked_entries:
        source_counts["processed"] += 1
        yield StatementSource(
            source_type=entry.source_type,
            source_record_id=entry.source_record_id,
            original_fee_result_id=entry.original_fee_result_id,
            coupon_id=entry.coupon_id,
            order_id=entry.order_id,
            fee_direction=entry.fee_direction,
            original_business_month=entry.original_business_month,
            posting_month=entry.statement_posting_month,
            store_id=store_id,
            product_scope=entry.product_scope,
            product_type=entry.product_type,
            base_amount_cent=entry.base_amount_cent,
            fee_amount_cent=entry.fee_amount_cent,
            source_amount_cent=source_amount_cent,
            rule_version=entry.rule_version,
            order_status=entry.order_status_snapshot,
            coupon_status=entry.coupon_status_snapshot,
            product_name=entry.product_name_snapshot,
            sku_id=entry.sku_id_snapshot,
            sku_name=entry.sku_name_snapshot,
            sale_channel=entry.sale_channel_snapshot,
            sale_store_id=entry.sale_store_id_snapshot,
            sale_store=entry.sale_store_snapshot,
            verify_store_id=entry.verify_store_id_snapshot,
            verify_store=entry.verify_store_snapshot,
            sale_time=entry.sale_time_snapshot,
            verify_time=entry.verify_time_snapshot,
            received_amount_cent=entry.received_amount_cent_snapshot,
            fee_rate=entry.fee_rate_snapshot,
            refund_at=entry.refund_at_snapshot,
            adjustment_type=entry.adjustment_type_snapshot,
        )

    current_results = session.scalars(
        select(SettlementFeeResult)
        .join(
                SettlementFeeResultCurrent,
                SettlementFeeResultCurrent.fee_result_id
                == SettlementFeeResult.fee_result_id,
            )
        .where(SettlementFeeResult.original_business_month == posting_month)
        .execution_options(yield_per=batch_size)
    )
    locked_slot_cache: dict[str, bool] = {}
    for result in current_results:
        source = _result_statement_source(session, result)
        if source.store_id not in locked_slot_cache:
            locked_slot_cache[source.store_id] = (
                _locked_statement(session, source.store_id, posting_month) is not None
            )
        is_locked = locked_slot_cache[source.store_id]
        if is_locked:
            source_counts["skipped"] += 1
            continue
        source_counts["processed"] += 1
        yield source
    adjustments = session.execute(
        select(SettlementFeeAdjustment, SettlementFeeResult)
        .join(
            SettlementFeeResultCurrent,
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeAdjustment.original_fee_result_id,
        )
        .join(
            SettlementFeeResult,
            SettlementFeeResult.fee_result_id
            == SettlementFeeAdjustment.original_fee_result_id,
        )
        .where(
            SettlementFeeAdjustment.adjustment_posting_month == posting_month,
            _active_adjustment_condition(),
        )
        .execution_options(yield_per=batch_size)
    )
    for adjustment, original in adjustments:
        source = _adjustment_statement_source(session, adjustment, original)
        if source.store_id not in locked_slot_cache:
            locked_slot_cache[source.store_id] = (
                _locked_statement(session, source.store_id, posting_month) is not None
            )
        is_locked = locked_slot_cache[source.store_id]
        if is_locked:
            source_counts["skipped"] += 1
            continue
        source_counts["processed"] += 1
        yield source


def _result_statement_source(session: Session, result: SettlementFeeResult) -> StatementSource:
    store_id = (
        result.sale_store_id
        if result.fee_direction == PROMOTION_FEE
        else result.verify_store_id
    )
    if not store_id:
        raise ValueError(f"fee result has no responsible store: {result.fee_result_id}")
    return StatementSource(
        source_type=1,
        source_record_id=result.fee_result_id,
        original_fee_result_id=result.fee_result_id,
        coupon_id=result.coupon_id,
        order_id=result.order_id,
        fee_direction=result.fee_direction,
        original_business_month=result.original_business_month,
        posting_month=result.original_business_month,
        store_id=store_id,
        product_scope=result.product_scope,
        product_type=result.product_type,
        base_amount_cent=result.fee_base_cent,
        fee_amount_cent=result.fee_amount_cent,
        source_amount_cent=result.source_amount_cent,
        rule_version=result.rule_version,
        **_statement_source_snapshots(session, result=result),
    )


def _adjustment_statement_source(
    session: Session, adjustment: SettlementFeeAdjustment, original: SettlementFeeResult
) -> StatementSource:
    store_id = (
        original.sale_store_id
        if adjustment.fee_direction == PROMOTION_FEE
        else original.verify_store_id
    )
    if not store_id:
        raise ValueError(
            f"adjustment original result has no responsible store: {adjustment.adjustment_id}"
        )
    return StatementSource(
        source_type=2,
        source_record_id=adjustment.adjustment_id,
        original_fee_result_id=adjustment.original_fee_result_id,
        coupon_id=adjustment.coupon_id,
        order_id=adjustment.order_id,
        fee_direction=adjustment.fee_direction,
        original_business_month=adjustment.original_business_month,
        posting_month=adjustment.adjustment_posting_month,
        store_id=store_id,
        product_scope=original.product_scope,
        product_type=original.product_type,
        base_amount_cent=adjustment.adjustment_base_cent,
        fee_amount_cent=adjustment.adjustment_fee_cent,
        source_amount_cent=0,
        rule_version=adjustment.rule_version,
        **_statement_source_snapshots(
            session,
            result=original,
            adjustment=adjustment,
        ),
    )


def _statement_source_snapshots(
    session: Session,
    *,
    result: SettlementFeeResult,
    adjustment: SettlementFeeAdjustment | None = None,
) -> dict[str, Any]:
    """Capture display facts once while assembling an immutable statement entry."""
    order = session.scalar(
        select(RawDouyinOrder).where(RawDouyinOrder.order_id == result.order_id)
    )
    product = session.scalar(
        select(DimSkuProductRule).where(DimSkuProductRule.sku_id == result.sku_id)
    )
    verify = _select_valid_verify_record(session, result.coupon_id)
    coupon = session.scalar(
        select(RawDouyinOrderCoupon).where(
            RawDouyinOrderCoupon.coupon_id == result.coupon_id
        )
    )
    sale_store = (
        session.get(DimStore, result.sale_store_id)
        if result.sale_store_id is not None
        else None
    )
    verify_mapping = (
        _find_poi_mapping(session, verify.poi_id) if verify is not None else None
    )
    verify_store_id = result.verify_store_id or (
        verify_mapping.store_id if verify_mapping is not None else None
    )
    verify_store = (
        session.get(DimStore, verify_store_id)
        if verify_store_id is not None
        else None
    )
    return {
        "order_status": order.order_status_normalized if order is not None else None,
        "coupon_status": (
            coupon.coupon_status_normalized
            if coupon is not None
            else None
        ),
        "product_name": (
            product.product_name
            if product is not None
            else (order.product_name if order is not None else None)
        ),
        "sku_id": result.sku_id,
        "sku_name": product.sku_name if product is not None else None,
        "sale_channel": result.sale_channel_normalized,
        "sale_store_id": result.sale_store_id,
        "sale_store": sale_store.store_name if sale_store is not None else None,
        "verify_store_id": verify_store_id,
        "verify_store": verify_store.store_name if verify_store is not None else None,
        "sale_time": order.sale_time if order is not None else None,
        "verify_time": verify.verify_time if verify is not None else None,
        "received_amount_cent": result.source_amount_cent,
        "fee_rate": result.fee_rate,
        "refund_at": (
            adjustment.occurred_at
            if adjustment is not None
            else (coupon.coupon_refund_time if coupon is not None else None)
        ),
        "adjustment_type": adjustment.adjustment_type if adjustment is not None else None,
    }


def _locked_statement(
    session: Session, store_id: str, month: str
) -> SettlementStatement | None:
    return session.scalar(
        select(SettlementStatement).where(
            SettlementStatement.store_id == store_id,
            SettlementStatement.statement_month == month,
            SettlementStatement.statement_status == 4,
            SettlementStatement.is_current.is_(True),
        )
    )


def _is_settlement_period_immutable(
    session: Session,
    *,
    store_id: str,
    month: str,
) -> bool:
    if _locked_statement(session, store_id, month) is not None:
        return True
    promotion_invoice_fact = session.scalar(
        select(PromotionInvoiceAllocation.id).where(
            PromotionInvoiceAllocation.store_id == store_id,
            PromotionInvoiceAllocation.statement_month == month,
            PromotionInvoiceAllocation.is_current.is_(True),
        )
    )
    if promotion_invoice_fact is not None:
        return True
    management_invoice_fact = session.scalar(
        select(InvoiceRecord.id).where(
            InvoiceRecord.store_id == store_id,
            InvoiceRecord.statement_month == month,
            InvoiceRecord.is_current.is_(True),
        )
    )
    return management_invoice_fact is not None


def _projection_dimensions(
    product_scope: str, product_type: str
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                ("all", "all"),
                ("all", product_type or "all"),
                (product_scope or "all", "all"),
                (product_scope or "all", product_type or "all"),
            }
        )
    )


def _empty_monthly_projection() -> dict[str, Any]:
    return {
        "sales_order_ids": set(),
        "sales_amount_cent": 0,
        "verified_order_ids": set(),
        "verified_amount_cent": 0,
        "promotion_base_cent": 0,
        "promotion_original_fee_cent": 0,
        "promotion_adjustment_fee_cent": 0,
        "management_base_cent": 0,
        "management_original_fee_cent": 0,
        "management_adjustment_fee_cent": 0,
    }


def _materialize_target_rankings(
    session: Session,
    monthly_rows: list[AggStoreMonthlySettlement],
    *,
    projection_run_id: str,
) -> int:
    ranking_count = 0
    for row in monthly_rows:
        _add_target_ranking_row(
            session,
            period_type=1,
            period_key=row.month,
            store_id=row.store_id,
            product_scope=row.product_scope,
            product_type=row.product_type,
            sales_order_count=row.sales_order_count,
            sales_amount_cent=row.sales_amount_cent,
            verified_order_count=row.verified_order_count,
            verified_amount_cent=row.verified_amount_cent,
            promotion_net_fee_cent=row.promotion_net_fee_cent,
            management_net_fee_cent=row.management_net_fee_cent,
            projection_run_id=projection_run_id,
        )
        ranking_count += 1

    cutoffs = sorted({row.month for row in monthly_rows if row.month >= "2026-08"})
    for cutoff in cutoffs:
        grouped: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
            lambda: {
                "sales_order_count": 0,
                "sales_amount_cent": 0,
                "verified_order_count": 0,
                "verified_amount_cent": 0,
                "promotion_net_fee_cent": 0,
                "management_net_fee_cent": 0,
            }
        )
        for row in monthly_rows:
            if row.month < "2026-08" or row.month > cutoff:
                continue
            values = grouped[(row.store_id, row.product_scope, row.product_type)]
            for field_name in values:
                values[field_name] += int(getattr(row, field_name))
        for (store_id, product_scope, product_type), values in sorted(grouped.items()):
            _add_target_ranking_row(
                session,
                period_type=2,
                period_key=cutoff,
                store_id=store_id,
                product_scope=product_scope,
                product_type=product_type,
                projection_run_id=projection_run_id,
                **values,
            )
            ranking_count += 1
    session.flush()
    return ranking_count


def _add_target_ranking_row(
    session: Session,
    *,
    period_type: int,
    period_key: str,
    store_id: str,
    product_scope: str,
    product_type: str,
    sales_order_count: int,
    sales_amount_cent: int,
    verified_order_count: int,
    verified_amount_cent: int,
    promotion_net_fee_cent: int,
    management_net_fee_cent: int,
    projection_run_id: str,
) -> None:
    store = session.get(DimStore, store_id)
    session.add(
        AggStoreRanking(
            period_type=period_type,
            period_key=period_key,
            store_id=store_id,
            store_name=store.store_name if store else store_id,
            product_scope=product_scope,
            product_type=product_type,
            sales_order_count=sales_order_count,
            sales_amount_cent=sales_amount_cent,
            verified_order_count=verified_order_count,
            verified_amount_cent=verified_amount_cent,
            promotion_net_fee_cent=promotion_net_fee_cent,
            management_net_fee_cent=management_net_fee_cent,
            net_settlement_reference_cent=(
                promotion_net_fee_cent - management_net_fee_cent
            ),
            projection_run_id=projection_run_id,
            month=period_key,
            self_verify_income_cent=verified_amount_cent,
            effective_commission_income_cent=promotion_net_fee_cent,
        )
    )


def _match_owner(
    session: Session,
    order: RawDouyinOrder,
    coupon: RawDouyinOrderCoupon,
    *,
    source_run_id: str,
) -> OwnerAccountMatch | None:
    id_match = session.get(DimAwemeAccount, order.owner_account_id) if order.owner_account_id else None
    nickname_matches = _nickname_matches(session, order.owner_account_name)

    nickname_store_ids = sorted({account.store_id for account in nickname_matches if account.store_id})
    if len(nickname_store_ids) == 1:
        for account in nickname_matches:
            if account.store_id == nickname_store_ids[0]:
                return account

    if len(nickname_store_ids) > 1:
        _record_issue(
            session,
            issue_type="conflicting_owner_match",
            message="Owner nickname matched multiple accounts.",
            order_id=order.order_id,
            coupon_id=coupon.coupon_id,
            source_run_id=source_run_id,
            raw_context={
                "owner_account_name": order.owner_account_name,
                "account_ids": [account.account_id for account in nickname_matches],
                "store_ids": nickname_store_ids,
                "match_sources": sorted({account.match_source for account in nickname_matches}),
            },
        )
    else:
        _record_issue(
            session,
            issue_type="unmatched_owner",
            message="No owner account matched by owner nickname.",
            order_id=order.order_id,
            coupon_id=coupon.coupon_id,
            source_run_id=source_run_id,
            raw_context={
                "owner_account_id": order.owner_account_id,
                "owner_account_name": order.owner_account_name,
                "id_store_id": id_match.store_id if id_match else None,
            },
        )
    return None


def _nickname_matches(session: Session, nickname: str | None) -> list[OwnerAccountMatch]:
    if not nickname:
        return []
    matches: dict[tuple[str, str | None], OwnerAccountMatch] = {}
    raw_bindings = list(
        session.scalars(select(RawAwemeBinding).where(RawAwemeBinding.douyin_nickname == nickname))
    )
    for binding in raw_bindings:
        if not binding.account_id or not _is_active_binding_status(binding.binding_status):
            continue
        matches[(binding.account_id, binding.account_id)] = OwnerAccountMatch(
            account_id=binding.account_id,
            store_id=binding.account_id,
            binding_status=binding.binding_status,
        )
    return list(matches.values())


def _is_active_binding_status(status: str | None) -> bool:
    return _normalized(status) not in INACTIVE_BINDING_STATUSES


def _is_non_commission_owner_account(session: Session, owner_account_name: str | None) -> bool:
    normalized = normalize_owner_account_name(owner_account_name)
    if not normalized:
        return False
    rule = session.get(DimNonCommissionOwnerAccount, normalized)
    return bool(rule and rule.is_active)


def _select_valid_verify_record(session: Session, coupon_id: str) -> RawDouyinVerifyRecord | None:
    records = list(
        session.scalars(
            select(RawDouyinVerifyRecord)
            .where(RawDouyinVerifyRecord.coupon_id == coupon_id)
        )
    )
    records.sort(key=lambda record: (record.verify_time or datetime.min, record.verify_id), reverse=True)
    valid_records = [
        record
        for record in records
        if _normalized(record.verify_status) in VALID_VERIFY_STATUSES and record.cancel_time is None
    ]
    if valid_records:
        return valid_records[0]
    if records and _normalized(records[0].verify_status) not in CANCELLED_VERIFY_STATUSES:
        return records[0]
    return None


def _find_poi_mapping(session: Session, poi_id: str | None) -> DimStorePoiMapping | None:
    if not poi_id:
        return None
    return session.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == poi_id).limit(1))


def _relation_type(sale_store: DimStore | None, verify_store: DimStore | None, is_verified: bool) -> str:
    if not is_verified:
        return "unverified"
    if sale_store is None or verify_store is None:
        return "unknown"
    if sale_store.store_id == verify_store.store_id:
        return "same_store"
    return "cross_store"


def _is_refund_excluded(order: RawDouyinOrder, coupon: RawDouyinOrderCoupon) -> bool:
    if coupon.coupon_refunded_cent and coupon.coupon_refunded_cent > 0:
        return True
    if coupon.coupon_refund_time is not None:
        return True
    return (
        _normalized(order.order_status) in REFUND_EXCLUDED_STATUSES
        or _normalized(coupon.coupon_status) in REFUND_EXCLUDED_STATUSES
    )


def _paid_amount_cent(order: RawDouyinOrder, verify: RawDouyinVerifyRecord | None) -> int:
    if verify and verify.paid_amount_cent is not None:
        return verify.paid_amount_cent
    return order.paid_amount_cent or 0


def _commission_cent(paid_amount_cent: int, commission_rate: Decimal) -> int:
    amount = Decimal(paid_amount_cent) * Decimal(commission_rate)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _rebuild_store_ranking(
    session: Session,
    details: list[SettlementOrderDetail],
    *,
    source_run_id: str,
) -> int:
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    sales_orders: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    for detail in details:
        if detail.is_refund_excluded:
            continue
        sale_month = _month(detail.sale_time)
        if not sale_month:
            continue

        product_types = _product_groups(detail.product_type)
        for product_type in product_types:
            if detail.sale_store_id:
                key = (sale_month, product_type, detail.sale_store_id)
                row = _ranking_row(rows, key, detail.sale_store_name)
                sales_orders[key].add(detail.order_id)
                if detail.is_verified and detail.relation_type == "same_store":
                    row["self_sold_self_verified_count"] += 1
                if detail.is_verified and detail.relation_type == "cross_store":
                    row["self_sold_other_verified_count"] += 1
                    row["effective_commission_income_cent"] += detail.receivable_commission_cent

            if detail.is_verified and detail.verify_store_id:
                key = (sale_month, product_type, detail.verify_store_id)
                row = _ranking_row(rows, key, detail.verify_store_name)
                row["self_verify_income_cent"] += detail.paid_amount_cent
                if detail.relation_type == "cross_store":
                    row["other_sold_self_verified_count"] += 1

    for key, row in rows.items():
        row["sales_order_count"] = len(sales_orders.get(key, set()))
        month, product_type, store_id = key
        session.add(
            AggStoreRanking(
                period_type=1,
                period_key=month,
                month=month,
                product_scope="all",
                product_type=product_type,
                store_id=store_id,
                projection_run_id=source_run_id,
                **row,
            )
        )
    session.flush()
    return len(rows)


def _ranking_row(
    rows: dict[tuple[str, str, str], dict[str, Any]],
    key: tuple[str, str, str],
    store_name: str | None,
) -> dict[str, Any]:
    if key not in rows:
        rows[key] = {
            "store_name": store_name,
            "sales_order_count": 0,
            "self_sold_self_verified_count": 0,
            "self_sold_other_verified_count": 0,
            "other_sold_self_verified_count": 0,
            "self_verify_income_cent": 0,
            "effective_commission_income_cent": 0,
        }
    elif not rows[key]["store_name"] and store_name:
        rows[key]["store_name"] = store_name
    return rows[key]


def _rebuild_monthly_settlement(
    session: Session,
    details: list[SettlementOrderDetail],
    *,
    source_run_id: str,
) -> int:
    rows: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: {
            "estimated_receivable_commission_cent": 0,
            "commissionable_total_cent": 0,
            "estimated_payable_commission_cent": 0,
        }
    )

    for detail in details:
        if detail.is_refund_excluded or not detail.is_commissionable:
            continue
        verify_month = _month(detail.verify_time)
        if not verify_month:
            continue

        for product_type in _product_groups(detail.product_type):
            if detail.sale_store_id:
                key = (verify_month, detail.sale_store_id, product_type)
                rows[key]["estimated_receivable_commission_cent"] += detail.receivable_commission_cent
                rows[key]["commissionable_total_cent"] += detail.paid_amount_cent
            if detail.verify_store_id:
                key = (verify_month, detail.verify_store_id, product_type)
                rows[key]["estimated_payable_commission_cent"] += detail.payable_commission_cent

    for key, values in rows.items():
        month, store_id, product_type = key
        session.add(
            AggStoreMonthlySettlement(
                month=month,
                store_id=store_id,
                product_scope="all",
                product_type=product_type,
                projection_run_id=source_run_id,
                **values,
            )
        )
    session.flush()
    return len(rows)


def _record_issue(
    session: Session,
    *,
    issue_type: str,
    message: str,
    order_id: str | None,
    coupon_id: str | None,
    source_run_id: str,
    severity: str = "warning",
    raw_context: dict[str, Any] | None = None,
    identity_suffix: str | None = None,
) -> None:
    issue_id = _issue_id(
        issue_type,
        order_id,
        coupon_id,
        source_run_id,
        identity_suffix=identity_suffix,
        include_source_run=not session.info.get("incremental_dqi_identity", False),
    )
    upsert_data_quality_issue(
        session,
        issue_id,
        issue_type=issue_type,
        order_id=order_id,
        coupon_id=coupon_id,
        severity=severity,
        message=message,
        raw_context_json=raw_context or {},
        source_run_id=source_run_id,
    )


def _record_failure_issue(session: Session, **issue: Any) -> None:
    """Record now and register a replay after a production session rollback."""

    issue_snapshot = dict(issue)

    def replay(audit_session: Session) -> None:
        _record_issue(audit_session, **issue_snapshot)
        audit_session.flush()

    session.info.setdefault("post_rollback_callbacks", []).append(replay)
    _record_issue(session, **issue_snapshot)
    session.flush()


def _issue_id(
    issue_type: str,
    order_id: str | None,
    coupon_id: str | None,
    source_run_id: str,
    *,
    identity_suffix: str | None = None,
    include_source_run: bool = True,
) -> str:
    identity = {
        "issue_type": issue_type,
        "order_id": order_id,
        "coupon_id": coupon_id,
    }
    if include_source_run:
        identity["source_run_id"] = source_run_id
    if identity_suffix is not None:
        identity["identity_suffix"] = identity_suffix
    payload = json.dumps(identity, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized(value: str | None) -> str:
    return (value or "").strip().lower()


def _first_text(*values: str | None) -> str | None:
    for value in values:
        if value:
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _month(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m")


def _local_business_month(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _business_month(value)


def _product_groups(product_type: str | None) -> tuple[str, str]:
    if product_type and product_type != "all":
        return ("all", product_type)
    return ("all",)
