"""Bounded source observations for ranking reconciliation; never settlement truth.

Mutable source tables cannot reconstruct an immutable historical snapshot. The
cutoff limits event time, not the version of a row. Callers must retain this flag.
"""
import base64
import binascii
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, literal, or_, select, tuple_, union
from sqlalchemy.orm import Session

from dy_api.models import (
    ClueAssignmentRound, ClueCenterOrder, ClueFollowUpRecord, DimAwemeAccount,
    DimSkuProductRule, DimStore, DimStorePoiMapping, RawAwemeBinding,
    RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
)

DATASETS = frozenset({"orders", "cohort", "assignment_rounds", "follow_records",
    "bindings", "accounts", "poi_mappings", "coupons", "verifications", "sku_rules"})
DIMENSIONS = frozenset({"bindings", "accounts", "poi_mappings", "sku_rules"})
SCHEMA_VERSION = "ranking-source-observation-v1"


def _columns(model, names: str):
    return [getattr(model, name) for name in names.split()]


def _statement(dataset: str, start: datetime, end: datetime, cutoff: datetime):
    rules = select(DimSkuProductRule.sku_id).where(DimSkuProductRule.product_scope == "精诚养车")
    products = select(func.coalesce(DimSkuProductRule.product_id, DimSkuProductRule.sku_id)).where(
        DimSkuProductRule.product_scope == "精诚养车")
    # Preserve COALESCE(sale_time, pay_time) semantics without hiding date indexes.
    sale_window = or_(
        and_(RawDouyinOrder.sale_time >= start, RawDouyinOrder.sale_time < end,
             RawDouyinOrder.sale_time <= cutoff),
        and_(RawDouyinOrder.sale_time.is_(None), RawDouyinOrder.pay_time >= start,
             RawDouyinOrder.pay_time < end, RawDouyinOrder.pay_time <= cutoff),
    )
    sales = select(RawDouyinOrder.order_id).where(RawDouyinOrder.sku_id.in_(rules), sale_window)
    known_orders = select(RawDouyinOrder.order_id).where(RawDouyinOrder.sku_id.in_(rules))
    known_clues = select(ClueCenterOrder.order_id).where(or_(
        ClueCenterOrder.product_id.in_(products), ClueCenterOrder.product_id.in_(rules)))
    assigned = select(ClueAssignmentRound.order_id).where(
        ClueAssignmentRound.execution_mode == "formal", ClueAssignmentRound.assigned_at >= start,
        ClueAssignmentRound.assigned_at < end, ClueAssignmentRound.assigned_at <= cutoff,
        or_(ClueAssignmentRound.order_id.in_(known_orders), ClueAssignmentRound.order_id.in_(known_clues)))
    cohort = union(sales, assigned).cte("ranking_cohort")
    order_ids = select(cohort.c.order_id)
    if dataset == "cohort":
        return select(cohort.c.order_id), [cohort.c.order_id]
    if dataset == "orders":
        return select(*_columns(RawDouyinOrder, "order_id sku_id sale_time pay_time create_order_time owner_account_id owner_douyin_uid sale_role sale_channel sale_channel_normalized order_status order_status_normalized source_run_id source_observed_at updated_at")).where(
            RawDouyinOrder.order_id.in_(order_ids)), [RawDouyinOrder.order_id]
    if dataset == "assignment_rounds":
        return select(*_columns(ClueAssignmentRound, "assignment_round_id order_id lead_key round_no assigned_store_id assigned_at execution_mode")).where(
            ClueAssignmentRound.order_id.in_(order_ids), ClueAssignmentRound.execution_mode == "formal",
            ClueAssignmentRound.assigned_at <= cutoff), [ClueAssignmentRound.assignment_round_id]
    if dataset == "follow_records":
        formal_ids = select(ClueAssignmentRound.assignment_round_id).where(
            ClueAssignmentRound.order_id.in_(order_ids), ClueAssignmentRound.execution_mode == "formal",
            ClueAssignmentRound.assigned_at <= cutoff)
        return select(*_columns(ClueFollowUpRecord, "follow_up_record_id order_id assignment_round_id assigned_store_id created_at deleted_at follow_result")).where(
            ClueFollowUpRecord.assignment_round_id.in_(formal_ids),
            ClueFollowUpRecord.created_at <= cutoff), [ClueFollowUpRecord.follow_up_record_id]
    if dataset == "coupons":
        return select(*_columns(RawDouyinOrderCoupon, "coupon_id order_id raw_order_id coupon_status coupon_status_normalized coupon_updated_at latest_refund_at source_run_id source_observed_at")).where(
            RawDouyinOrderCoupon.order_id.in_(order_ids)), [RawDouyinOrderCoupon.coupon_id]
    if dataset == "verifications":
        coupon_ids = select(RawDouyinOrderCoupon.coupon_id).where(RawDouyinOrderCoupon.order_id.in_(order_ids))
        return select(*_columns(RawDouyinVerifyRecord, "verify_id coupon_id sku_id verify_status verify_time poi_id cancel_time source_run_id source_observed_at")).where(
            RawDouyinVerifyRecord.coupon_id.in_(coupon_ids), or_(RawDouyinVerifyRecord.verify_time <= cutoff,
            RawDouyinVerifyRecord.verify_time.is_(None))), [RawDouyinVerifyRecord.verify_id]
    if dataset == "bindings":
        return select(*_columns(RawAwemeBinding, "binding_key account_id douyin_id poi_id binding_status source_run_id updated_at"),
            RawAwemeBinding.raw_payload["craftsman_uid"].as_string().label("source_craftsman_uid"),
            RawAwemeBinding.raw_payload["account_id_for_settlement"].as_string().label("source_settlement_account_id")), [RawAwemeBinding.binding_key]
    if dataset == "accounts":
        return select(*_columns(DimAwemeAccount, "account_id store_id binding_status valid_from valid_to updated_at")), [DimAwemeAccount.account_id]
    if dataset == "poi_mappings":
        return select(*_columns(DimStorePoiMapping, "store_id poi_id mapping_source source_run_id source_observed_at"),
            getattr(DimStore, "service_store_code", literal(None)).label("service_store_code"), DimStore.is_active).outerjoin(
                DimStore, DimStore.store_id == DimStorePoiMapping.store_id), [DimStorePoiMapping.store_id, DimStorePoiMapping.poi_id]
    if dataset == "sku_rules":
        return select(*_columns(DimSkuProductRule, "sku_id product_id product_scope product_type")).where(
            DimSkuProductRule.product_scope == "精诚养车"), [DimSkuProductRule.sku_id]
    raise ValueError("Unsupported dataset")


def read_source_page(session: Session, *, dataset: str, period_start: date, period_end: date,
                     observed_through: datetime, page_size: int = 500, cursor: str | None = None) -> dict:
    """Read one keyset page, with no counts, autoflush, commits or source mutations."""
    now = datetime.now(timezone.utc)
    if dataset not in DATASETS or not 1 <= page_size <= 500:
        raise ValueError("Unsupported dataset or page size")
    if not 0 <= (period_end - period_start).days < 7:
        raise ValueError("Date range must contain 1 to 7 days")
    if observed_through.tzinfo is None or observed_through.utcoffset() is None:
        raise ValueError("Observation cutoff must include timezone")
    start = datetime.combine(period_start, time.min, ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    end = datetime.combine(period_end + timedelta(days=1), time.min, ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    cutoff = observed_through.astimezone(timezone.utc)
    if not start <= cutoff <= now:
        raise ValueError("Observation cutoff must be between period start and now")
    context = hashlib.sha256(json.dumps([SCHEMA_VERSION, dataset, start.isoformat(),
        end.isoformat(), cutoff.isoformat()]).encode()).hexdigest()
    statement, keys = _statement(dataset, start, end, cutoff)
    if cursor:
        try:
            if len(cursor) > 2048:
                raise ValueError("Cursor too long")
            token = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if not isinstance(token, dict) or token.get("context") != context:
                raise ValueError("Cursor does not belong to this query")
            after = token.get("after")
            if not isinstance(after, list) or len(after) != len(keys) or any(
                not isinstance(value, str) or not 0 < len(value) <= 512 for value in after):
                raise ValueError("Invalid cursor position")
        except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("Invalid cursor or query context") from exc
        statement = statement.where(tuple_(*keys) > tuple_(*after))
    with session.no_autoflush:
        rows = [dict(row) for row in session.execute(statement.order_by(*keys).limit(page_size + 1)).mappings()]
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    next_cursor = None
    if has_more:
        position = [str(rows[-1][key.key]) for key in keys]
        next_cursor = base64.urlsafe_b64encode(json.dumps({"context": context, "after": position}).encode()).decode()
    return {"data": {"rows": rows, "next_cursor": next_cursor, "has_more": has_more},
        "meta": {"schema_version": SCHEMA_VERSION, "query_fingerprint": context,
            "dataset": dataset, "period_start": start.isoformat(), "period_end_exclusive": end.isoformat(),
            "business_timezone": "Asia/Shanghai",
            "observed_through": cutoff.isoformat(), "generated_at": now.isoformat(),
            "read_only": True, "consistent_snapshot": False,
            "service_store_code_available": hasattr(DimStore, "service_store_code"),
            "scope": "current_dimensions" if dataset in DIMENSIONS else "sales_or_formal_assignments",
            "limitations": ["Current rows and current SKU whitelist; not historical row versions.",
                "Unknown product assignments and unlinked verification events need separate coverage audit.",
                "Event cutoff does not freeze mutable binding, deletion or cancellation state."]}}
