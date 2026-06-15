from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    AggStoreRanking,
    DataQualityIssue,
    DimAwemeAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    RawAwemeBinding,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementOrderDetail,
)
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
    match_source: str = "dim_aweme_accounts"


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
    ranking_count = _rebuild_store_ranking(session, details)
    monthly_count = _rebuild_monthly_settlement(session, details)
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
    order = session.get(RawDouyinOrder, coupon.order_id)
    if order is None:
        _record_issue(
            session,
            issue_type="missing_order",
            message="Coupon has no matching raw order.",
            order_id=coupon.order_id,
            coupon_id=coupon.coupon_id,
            source_run_id=source_run_id,
            severity="error",
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
    sku_rule = session.get(DimSkuProductRule, sku_id) if sku_id else None
    if sku_rule is None:
        _record_issue(
            session,
            issue_type="unmatched_sku",
            message="No SKU product rule matched the order or verify record.",
            order_id=order.order_id,
            coupon_id=coupon.coupon_id,
            source_run_id=source_run_id,
            raw_context={"sku_id": sku_id, "order_sku_id": order.sku_id, "verify_sku_id": verify.sku_id if verify else None},
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
    commission_rate = Decimal(sku_rule.commission_rate) if sku_rule else Decimal("0")
    is_service_product = bool(sku_rule.is_service_product) if sku_rule else False
    is_commissionable = (
        relation_type == "cross_store"
        and not refund_excluded
        and is_service_product
        and sku_rule is not None
        and sale_store is not None
        and verify_store is not None
    )
    commission_cent = _commission_cent(paid_amount_cent, commission_rate) if is_commissionable else 0

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
        verify_store_name=verify_store.store_name if verify_store else (verify.verify_store_name_raw if verify else None),
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
    dim_accounts = list(
        session.scalars(select(DimAwemeAccount).where(DimAwemeAccount.nickname == nickname))
    )
    for account in dim_accounts:
        if _is_active_binding_status(account.binding_status):
            matches[(account.account_id, account.store_id)] = OwnerAccountMatch(
                account_id=account.account_id,
                store_id=account.store_id,
                binding_status=account.binding_status,
            )

    raw_bindings = list(
        session.scalars(select(RawAwemeBinding).where(RawAwemeBinding.douyin_nickname == nickname))
    )
    for binding in raw_bindings:
        if not binding.account_id or not _is_active_binding_status(binding.binding_status):
            continue
        dim_account = session.get(DimAwemeAccount, binding.account_id)
        store_id = dim_account.store_id if dim_account and dim_account.store_id else binding.account_id
        matches[(binding.account_id, store_id)] = OwnerAccountMatch(
            account_id=binding.account_id,
            store_id=store_id,
            binding_status=binding.binding_status,
            match_source="raw_aweme_bindings",
        )
    return list(matches.values())


def _is_active_binding_status(status: str | None) -> bool:
    return _normalized(status) not in INACTIVE_BINDING_STATUSES


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


def _rebuild_store_ranking(session: Session, details: list[SettlementOrderDetail]) -> int:
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
        session.merge(AggStoreRanking(month=month, product_type=product_type, store_id=store_id, **row))
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


def _rebuild_monthly_settlement(session: Session, details: list[SettlementOrderDetail]) -> int:
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
        session.merge(
            AggStoreMonthlySettlement(
                month=month,
                store_id=store_id,
                product_type=product_type,
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
) -> None:
    issue_id = _issue_id(issue_type, order_id, coupon_id, source_run_id)
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


def _issue_id(issue_type: str, order_id: str | None, coupon_id: str | None, source_run_id: str) -> str:
    payload = json.dumps(
        {
            "issue_type": issue_type,
            "order_id": order_id,
            "coupon_id": coupon_id,
            "source_run_id": source_run_id,
        },
        sort_keys=True,
    )
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
