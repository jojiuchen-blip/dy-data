from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text
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
    RawAwemeBinding,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementOrderDetail,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementScopeRule,
    SettlementStatement,
    SettlementStatementEntry,
    SettlementStatementLine,
    SkuFeeRule,
    utcnow,
)
from apps.api.dy_api.rule_utils import normalize_owner_account_name
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
) -> DualFeeStats:
    """Materialize immutable promotion/management results and later adjustments.

    Expected data-quality failures are isolated per coupon and direction. Existing
    current results are left untouched during an ordinary repeat run; an explicit
    recalculation creates a new version and switches only an unlocked pointer.
    """

    before_results = _model_count(session, SettlementFeeResult)
    before_adjustments = _model_count(session, SettlementFeeAdjustment)
    blocked_count = 0
    coupons = list(
        session.scalars(
            select(RawDouyinOrderCoupon).order_by(RawDouyinOrderCoupon.coupon_id)
        )
    )
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
            if current is not None and not force_recalculate:
                continue
            if current is not None and _has_calculation_result(
                session, coupon.coupon_id, direction, calculation_run_id
            ):
                continue
            blocked_count += int(
                not _materialize_dual_fee_direction(
                    session,
                    order=order,
                    coupon=coupon,
                    direction=direction,
                    calculation_run_id=calculation_run_id,
                    current=current,
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
    return DualFeeStats(
        result_count=_model_count(session, SettlementFeeResult) - before_results,
        adjustment_count=(
            _model_count(session, SettlementFeeAdjustment) - before_adjustments
        ),
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
            posting_month = _business_month(event.occurred_at)
            _lock_settlement_slot(session, responsible_store_id, posting_month)
            if _is_fee_result_locked(
                session,
                store_id=responsible_store_id,
                month=posting_month,
            ):
                _record_issue(
                    session,
                    issue_type="dual_fee_locked_adjustment_posting_month",
                    message="调整入账月已锁定，缺少补充账单或顺延政策，退款调整已阻断。",
                    order_id=original.order_id,
                    coupon_id=original.coupon_id,
                    source_run_id=calculation_run_id,
                    severity="error",
                    raw_context={
                        "fee_direction": direction,
                        "refund_event_id": event.refund_event_id,
                        "store_id": responsible_store_id,
                        "posting_month": posting_month,
                    },
                    identity_suffix=f"{event.refund_event_id}:{direction}",
                )
                continue
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
                    adjustment_reason=(
                        "全额退款，按原规则版本将费用净额调整为零。"
                        if event.refund_type == 2
                        else "部分退款，按退款后净额和原规则版本同比例调减费用。"
                    ),
                    occurred_at=event.occurred_at,
                    created_by=f"settlement:{calculation_run_id}",
                )
            )
            session.flush()
            applied_base_adjustment += adjustment_base
            applied_fee_adjustment += adjustment_fee


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
        cancelled.cancel_time.isoformat(),
        original.fee_result_id,
    )
    if session.scalar(
        select(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.adjustment_id == adjustment_id
        )
    ):
        return
    posting_month = _business_month(cancelled.cancel_time)
    _lock_settlement_slot(session, original.verify_store_id, posting_month)
    if _is_fee_result_locked(
        session,
        store_id=original.verify_store_id,
        month=posting_month,
    ):
        _record_issue(
            session,
            issue_type="dual_fee_locked_adjustment_posting_month",
            message="调整入账月已锁定，缺少补充账单或顺延政策，取消核销调整已阻断。",
            order_id=original.order_id,
            coupon_id=original.coupon_id,
            source_run_id=calculation_run_id,
            severity="error",
            raw_context={
                "fee_direction": MANAGEMENT_FEE,
                "verify_id": cancelled.verify_id,
                "store_id": original.verify_store_id,
                "posting_month": posting_month,
            },
            identity_suffix=f"{cancelled.verify_id}:{MANAGEMENT_FEE}",
        )
        return
    existing_base = session.scalar(
        select(func.coalesce(func.sum(SettlementFeeAdjustment.adjustment_base_cent), 0)).where(
            SettlementFeeAdjustment.original_fee_result_id == original.fee_result_id
        )
    )
    existing_fee = session.scalar(
        select(func.coalesce(func.sum(SettlementFeeAdjustment.adjustment_fee_cent), 0)).where(
            SettlementFeeAdjustment.original_fee_result_id == original.fee_result_id
        )
    )
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
            adjustment_base_cent=-original.fee_base_cent - int(existing_base or 0),
            adjustment_fee_cent=-original.fee_amount_cent - int(existing_fee or 0),
            rule_version=original.rule_version,
            adjustment_reason="取消核销，仅将管理服务费按原规则版本调整为零。",
            occurred_at=cancelled.cancel_time,
            created_by=f"settlement:{calculation_run_id}",
        )
    )
    session.flush()


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
    return session.scalar(
        select(SkuFeeRule)
        .where(
            SkuFeeRule.sku_id == sku_id,
            SkuFeeRule.rule_status == ACTIVE_FEE_RULE,
            SkuFeeRule.effective_date <= business_date,
        )
        .order_by(SkuFeeRule.effective_date.desc(), SkuFeeRule.id.desc())
        .limit(1)
    )


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


def _has_calculation_result(
    session: Session, coupon_id: str, direction: int, calculation_run_id: str
) -> bool:
    return bool(
        session.scalar(
            select(SettlementFeeResult.id).where(
                SettlementFeeResult.coupon_id == coupon_id,
                SettlementFeeResult.fee_direction == direction,
                SettlementFeeResult.calculation_run_id == calculation_run_id,
            )
        )
    )


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
    locked_slot = session.scalar(
        select(SettlementStatement.id).where(
            SettlementStatement.store_id == store_id,
            SettlementStatement.statement_month == month,
            SettlementStatement.statement_status == 4,
        )
    )
    if locked_slot:
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
                )
                .with_for_update()
            )
            if statement is not None and statement.statement_status == 4:
                return statement
            if statement is None:
                statement = SettlementStatement(
                    statement_id=statement_id,
                    store_id=store_id,
                    statement_month=statement_month,
                    statement_status=1,
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
        select(SettlementFeeAdjustment.adjustment_posting_month).join(
            SettlementFeeResultCurrent,
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeAdjustment.original_fee_result_id,
        ),
        select(AggStoreMonthlySettlement.month),
        select(AggStoreRanking.period_key),
    )
    for query in month_queries:
        months.update(str(value) for value in session.scalars(query.distinct()))
    return sorted(month for month in months if month >= "2026-08")


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
            sources.append(_result_statement_source(result))
    adjustments = list(
        session.scalars(
            select(SettlementFeeAdjustment)
            .join(
                SettlementFeeResultCurrent,
                SettlementFeeResultCurrent.fee_result_id
                == SettlementFeeAdjustment.original_fee_result_id,
            )
            .where(
                SettlementFeeAdjustment.adjustment_posting_month == statement_month
            )
        )
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
            sources.append(_adjustment_statement_source(adjustment, original))
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
        source = _result_statement_source(result)
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
            SettlementFeeAdjustment.adjustment_posting_month == posting_month
        )
        .execution_options(yield_per=batch_size)
    )
    for adjustment, original in adjustments:
        source = _adjustment_statement_source(adjustment, original)
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


def _result_statement_source(result: SettlementFeeResult) -> StatementSource:
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
    )


def _adjustment_statement_source(
    adjustment: SettlementFeeAdjustment, original: SettlementFeeResult
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
    )


def _locked_statement(
    session: Session, store_id: str, month: str
) -> SettlementStatement | None:
    return session.scalar(
        select(SettlementStatement).where(
            SettlementStatement.store_id == store_id,
            SettlementStatement.statement_month == month,
            SettlementStatement.statement_status == 4,
        )
    )


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
) -> str:
    identity = {
        "issue_type": issue_type,
        "order_id": order_id,
        "coupon_id": coupon_id,
        "source_run_id": source_run_id,
    }
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


def _product_groups(product_type: str | None) -> tuple[str, str]:
    if product_type and product_type != "all":
        return ("all", product_type)
    return ("all",)
