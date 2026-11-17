"""Determine the store scope that can be certified in a monthly close."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DataQualityIssue, DimStore, RawDouyinOrderCoupon, RawDouyinVerifyRecord, SettlementFeeResult,
    SettlementFeeResultCurrent, SettlementMonthClose, SettlementStatement, utcnow,
)
from apps.worker.historical_sale_attribution import HistoricalAttributionError, resolve_historical_sale_attribution
from apps.worker.settlement import (
    MANAGEMENT_FEE, PROMOTION_FEE, _exact_monthly_sale_match, _diagnose_dual_fee_sale_account,
    _find_poi_mapping, _raw_order_for_coupon, _select_valid_verify_record,
)


@dataclass(frozen=True)
class MonthlyCloseScope:
    month: str
    qualification_version_id: str
    blocked_store_ids: frozenset[str]
    unscoped_issue_count: int
    preceding_scope_unresolved: bool = False

    @property
    def complete(self) -> bool:
        return not (self.blocked_store_ids or self.unscoped_issue_count or self.preceding_scope_unresolved)


def _is_confirmed_exclusion(issue: DataQualityIssue) -> bool:
    context = issue.raw_context_json or {}
    return (
        issue.issue_type == "dual_fee_non_commission_owner"
        or (issue.issue_type == "dual_fee_missing_scope_rule" and context.get("scope_state") == "disabled")
        or (issue.issue_type == "dual_fee_monthend_account_qualification"
            and context.get("reason_code") == "account_not_qualified_in_frozen_month")
    )


def _exact_issue_store(session: Session, coupon_id: str, direction: int, *, verify_id: str | None) -> str | None:
    coupon = session.scalar(select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.coupon_id == coupon_id))
    if coupon is None:
        return None
    verify = (session.get(RawDouyinVerifyRecord, verify_id) if verify_id
              else _select_valid_verify_record(session, coupon_id))
    if verify is not None and verify.coupon_id != coupon_id:
        return None
    if direction == MANAGEMENT_FEE:
        mapping = _find_poi_mapping(session, verify.poi_id) if verify is not None else None
        return mapping.store_id if mapping is not None and session.get(DimStore, mapping.store_id) is not None else None
    if direction != PROMOTION_FEE:
        return None
    order = _raw_order_for_coupon(session, coupon)
    if order is None:
        return None
    try:
        decision = resolve_historical_sale_attribution(session, order=order, coupon=coupon,
                                                       verify=verify, current_result=None)
    except HistoricalAttributionError:
        return None
    if decision is not None:
        return decision.store_id
    diagnostic = _diagnose_dual_fee_sale_account(session, order, ignore_proven_personal_aliases=True)
    match = _exact_monthly_sale_match(session, order, diagnostic)
    return match.store_id if match is not None else None


def inspect_month_close_scope(
    session: Session, *, month: str, calculation_run_id: str, qualification_version_id: str,
    coupon_ids: tuple[str, ...],
) -> MonthlyCloseScope:
    """Find affected stores from evidence; leave unbounded amounts unpublished."""
    issues = list(session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.source_run_id == calculation_run_id, DataQualityIssue.severity == "error",
    )))
    candidate_ids = set(coupon_ids)
    existing_candidates = set(session.scalars(select(RawDouyinOrderCoupon.coupon_id).where(
        RawDouyinOrderCoupon.coupon_id.in_(coupon_ids),
    ))) if coupon_ids else set()
    keys = defaultdict(set)
    for result in session.scalars(select(SettlementFeeResult).join(
        SettlementFeeResultCurrent, SettlementFeeResultCurrent.fee_result_id == SettlementFeeResult.fee_result_id,
    ).where(
        SettlementFeeResult.original_business_month == month,
        or_(SettlementFeeResult.account_qualification_version_id.is_(None),
            SettlementFeeResult.account_qualification_version_id != qualification_version_id),
    )):
        store_id = result.sale_store_id if result.fee_direction == PROMOTION_FEE else result.verify_store_id
        keys[result.coupon_id, result.fee_direction].add(store_id)

    blocked = set()
    unscoped = {(coupon_id, 0) for coupon_id in candidate_ids - existing_candidates}
    exclusions = set()
    diagnosed = set()
    for issue in issues:
        context = issue.raw_context_json or {}
        direction = context.get("fee_direction")
        key = (issue.coupon_id, direction)
        if _is_confirmed_exclusion(issue):
            exclusions.add(key)
            continue
        diagnosed.add(key)
        store_id = (_exact_issue_store(session, *key, verify_id=context.get("verify_id"))
                    if issue.coupon_id and direction in (1, 2) else None)
        if store_id is None:
            unscoped.add(key)
        else:
            blocked.add(store_id)
        blocked.update(filter(None, keys.get(key, ())))

    for key, prior_stores in keys.items():
        if key not in diagnosed and key not in exclusions:
            # A stale result outside the recomputed cohort could have moved or
            # lost its source. Its previous store alone is not an impact proof.
            unscoped.add(key)
            blocked.update(filter(None, prior_stores))
    return MonthlyCloseScope(month, qualification_version_id, frozenset(blocked), len(unscoped))


def current_frozen_stores(session: Session, month: str) -> set[str]:
    return set(session.scalars(select(SettlementStatement.store_id).where(
        SettlementStatement.statement_month == month, SettlementStatement.is_current.is_(True),
        SettlementStatement.monthly_close_input_sha256.is_not(None),
    )))


def preceding_period_has_no_statement(session: Session, *, store_id: str, month: str) -> bool:
    from apps.worker.monthly_statement_balances import previous_month

    prior = session.get(SettlementMonthClose, previous_month(month))
    return prior is not None and (prior.is_complete or (
        prior.unscoped_issue_count == 0 and store_id not in prior.blocked_store_ids
    ))


def record_month_close(session: Session, scope: MonthlyCloseScope, *, job_id: str, input_sha256: str) -> None:
    """Record the certified scope in the transaction that publishes its bills."""
    prior = session.get(SettlementMonthClose, scope.month, with_for_update=True)
    if prior is not None and prior.is_complete:
        raise ValueError("completed month cannot be published again")
    session.merge(SettlementMonthClose(
        business_month=scope.month, source_input_sha256=input_sha256, source_job_id=job_id,
        qualification_version_id=scope.qualification_version_id, is_complete=scope.complete,
        blocked_store_ids=sorted(scope.blocked_store_ids),
        unscoped_issue_count=scope.unscoped_issue_count + int(scope.preceding_scope_unresolved),
        updated_at=utcnow(),
    ))
