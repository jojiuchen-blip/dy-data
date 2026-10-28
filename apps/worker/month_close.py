"""Natural-month close planner (Asia/Shanghai), watermark-versioned.

Dispatch is keyed by a *verifiable* collection-completion watermark, not by a
raw impact counter: a month is only billable once every business date in that
month has a successful ``finalize`` job row (``job_runs.job_kind='finalize'``,
``status='success'``, ``business_date`` inside the month).  That is the same
durable signal the daily scheduler uses to call a day complete.

Consequences:

* the job id embeds the watermark fingerprint, so a month that gains late
  source after a successful close produces a *new* stable versioned job;
* an unchanged watermark is idempotent (the same id already exists);
* October onward dispatches calculation from complete frozen inputs, even
  before eligible fees exist; public publication readiness stays strict;
* an incomplete month is **fail-closed**: nothing is dispatched;
* a locked month (``statement_status = 4``) is refused outright.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, union
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api.rule_utils import normalize_owner_account_name
from apps.api.dy_api.models import (
    DataQualityIssue,
    JobRun,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementStatement,
    AccountQualificationVersion,
    DimAwemeAccount, DimNonCommissionOwnerAccount, DimSkuProductRule,
    DimStore, DimStorePoiMapping, DouyinRefundEvent, HistoricalSaleAttributionDecision,
    RawAwemeBinding, RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
    SettlementScopeRule, SkuFeeRule,
)
from apps.worker.historical_sale_attribution import month_decision_digest
from apps.worker.account_qualification import (
    FIRST_MONTH, AccountQualificationError, freeze_month, frozen_version,
    month_bounds,
)
from apps.worker.priority_scheduler import _day_state, _priority_rows_for_day
from apps.worker.repositories import queue_job_run, upsert_data_quality_issue
from apps.worker.settlement import FORMAL_SETTLEMENT_START, _canonical_fingerprint_value
from apps.worker.settlement_rebuild import (
    SETTLEMENT_REBUILD_JOB_NAME,
    settlement_month_scope_metadata,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
LOCKED_STATEMENT_STATUS = 4

# Automatic month close is enabled.  Every per-month guard stays in force:
# fail-closed completeness (every Shanghai business day published), lock
# refusal and serialization against other rebuilds. October qualification
# bootstraps calculation; positive/all-pinned current results gate publication.
MONTH_CLOSE_ENABLED = True

WATERMARK_INCOMPLETE = "watermark_incomplete"
NO_CURRENT_RESULTS = "no_current_results"
LOCKED = "locked"
ACTIVE_REBUILD = "active_rebuild"
READY = "ready"
QUALIFICATION_NOT_READY = "account_qualification_not_ready"
CALCULATION_READY = "calculation_ready"
CALCULATION_INPUT_PROTOCOL = "month-close-calculation-v1"

# Operator-visible readiness alert type.  One row per (business_month, state),
# removed again as soon as the month becomes dispatchable.
READINESS_ISSUE_TYPE = "month_close_source_not_ready"
_NOT_READY_STATES = (WATERMARK_INCOMPLETE, NO_CURRENT_RESULTS, LOCKED, QUALIFICATION_NOT_READY)

_logger = logging.getLogger("apps.worker.month_close")


def readiness_issue_id(business_month: str, state: str) -> str:
    """Stable dedupe key for a month's readiness alert."""

    return f"month-close-readiness:{business_month}:{state}"


def _in_formal_window(business_month: str) -> bool:
    return business_month >= FORMAL_SETTLEMENT_START.strftime("%Y-%m")


def previous_business_month(now: datetime | None = None) -> str:
    """The last fully completed Shanghai calendar month (``YYYY-MM``)."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(SHANGHAI)
    return (local.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def month_business_dates(business_month: str) -> tuple[date, ...]:
    """Every calendar date of one ``YYYY-MM`` month."""

    start = date.fromisoformat(f"{business_month}-01")
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return tuple(
        start + timedelta(days=offset)
        for offset in range((next_month - start).days)
    )


def month_current_results_fingerprint(
    session: Session, business_month: str
) -> tuple[str, int]:
    """Fingerprint of the month's *current* commission results.

    Ordered by ``(coupon_id, fee_direction, fee_result_id)`` so the value is
    stable for one result set and changes the moment late source adds or
    replaces a current result.
    """

    rows = session.execute(
        select(
            SettlementFeeResult.coupon_id,
            SettlementFeeResult.fee_direction,
            SettlementFeeResult.fee_result_id,
        )
        .join(
            SettlementFeeResultCurrent,
            SettlementFeeResultCurrent.fee_result_id
            == SettlementFeeResult.fee_result_id,
        )
        .where(SettlementFeeResult.original_business_month == business_month)
        .order_by(
            SettlementFeeResult.coupon_id,
            SettlementFeeResult.fee_direction,
            SettlementFeeResult.fee_result_id,
        )
        .execution_options(yield_per=500)
    )
    digest = hashlib.sha256()
    count = 0
    try:
        for coupon, direction, result in rows:
            if count:
                digest.update(b";")
            digest.update(f"{coupon}|{direction}|{result}".encode("utf-8"))
            count += 1
    finally:
        rows.close()
    return digest.hexdigest()[:12], count


def published_days_revisions(
    session: Session, business_month: str
) -> list[str] | None:
    """Per-day finalize revisions, or ``None`` when any day is unpublished."""

    revisions: list[str] = []
    for day in month_business_dates(business_month):
        state = _day_state(day, _priority_rows_for_day(session, day))
        if state.state != "success":
            return None
        finalize_rows = [row for row in state.rows if row.job_kind == "finalize"]
        if len(finalize_rows) != 1:
            return None
        revisions.append(f"{day.isoformat()}@{finalize_rows[0].job_id}")
    return revisions


def month_source_watermark(session: Session, business_month: str) -> str | None:
    """Fingerprint of the month's billable source, or ``None`` when not ready.

    Readiness requires **both**:

    1. every Shanghai business day of the month is *published* — the real
       priority-scheduler condition (``_day_state`` over
       ``_priority_rows_for_day``), because production does not write a per-day
       ``business_date`` on ``finalize`` rows; and
    2. at least one current commission result exists for the month, so a month
       whose rules/account mapping are not yet in place can never reach
       statement or projection generation.

    The revision per day is that day's finalize ``job_id`` and the result set is
    fingerprinted by ``(coupon, direction, fee_result_id)``, so late source
    advances the watermark while older or failed rows never do.  Anything
    unknown or missing returns ``None``: fail closed.
    """

    qualification = _qualification_digest(session, business_month)
    if business_month >= FIRST_MONTH and qualification is None:
        return None
    revisions = published_days_revisions(session, business_month)
    if revisions is None:
        return None
    results_fingerprint, result_count = month_current_results_fingerprint(
        session, business_month
    )
    if result_count == 0:
        # Zero commission results must never reach statement generation.
        return None
    return _watermark_from(revisions, results_fingerprint, month_decision_digest(session, business_month), qualification)


def _watermark_from(revisions: list[str], results_fingerprint: str, decision_digest: str | None = None, qualification_digest: str | None = None) -> str:
    payload = ",".join(revisions) + "||" + results_fingerprint
    if decision_digest is not None:
        payload += "||historical-sale-attribution:" + decision_digest
    if qualification_digest is not None:
        payload += "||account-qualification:" + qualification_digest
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def month_close_preflight(session: Session, business_month: str) -> tuple[str, str | None]:
    """Return ``(state, watermark)`` for one month without changing anything.

    The states are deliberately distinguishable so an operator alert can say
    *why* a month cannot close: unpublished days, no billable result, or a
    locked statement.
    """

    if not _in_formal_window(business_month):
        return WATERMARK_INCOMPLETE, None
    locked = session.scalar(
        select(SettlementStatement.statement_id)
        .where(
            SettlementStatement.statement_month == business_month,
            SettlementStatement.statement_status == LOCKED_STATEMENT_STATUS,
        )
        .limit(1)
    )
    if locked is not None:
        return LOCKED, None
    qualification = _qualification_digest(session, business_month)
    if business_month >= FIRST_MONTH and qualification is None:
        return QUALIFICATION_NOT_READY, None
    revisions = published_days_revisions(session, business_month)
    if revisions is None:
        return WATERMARK_INCOMPLETE, None
    results_fingerprint, result_count = month_current_results_fingerprint(
        session, business_month
    )
    if result_count == 0:
        return NO_CURRENT_RESULTS, None
    watermark = _watermark_from(revisions, results_fingerprint, month_decision_digest(session, business_month), qualification)
    if _active_rebuild_exists(session):
        return ACTIVE_REBUILD, watermark
    return READY, watermark


def _qualification_digest(session: Session, business_month: str) -> str | None:
    if business_month < FIRST_MONTH:
        return None
    try:
        version = require_current_month_qualification(session, business_month)
    except AccountQualificationError:
        return None
    return version.version_id + ":" + version.content_sha256


def require_current_month_qualification(session: Session, business_month: str) -> AccountQualificationVersion | None:
    """Require the frozen month version on every current fee, never change fees."""
    if business_month < FIRST_MONTH:
        return None
    version = frozen_version(session, business_month)
    # Existing old/unpinned results may not pass a month-end preflight merely
    # because at least one other result uses the new basis.
    mismatch = session.scalar(select(SettlementFeeResult.fee_result_id).join(
        SettlementFeeResultCurrent,
        SettlementFeeResultCurrent.fee_result_id == SettlementFeeResult.fee_result_id,
    ).where(
        SettlementFeeResult.original_business_month == business_month,
        (SettlementFeeResult.account_qualification_version_id.is_(None)
         | (SettlementFeeResult.account_qualification_version_id != version.version_id)),
    ).limit(1))
    if mismatch is not None:
        raise AccountQualificationError("current_fee_qualification_version_mismatch")
    return version


def _calculation_inputs_digest(session: Session, business_month: str, revisions: list[str]) -> str:
    """Stream only the month's source graph; fee outputs never advance this key."""
    version = frozen_version(session, business_month)
    _, end = month_bounds(business_month)
    start = datetime.fromisoformat(f"{business_month}-01").replace(tzinfo=SHANGHAI).astimezone(timezone.utc)
    # Historical fee keys are source addresses only. Keep them after a current
    # pointer retires, so calculation output cannot shrink its own input scope.
    historical_coupons = select(SettlementFeeResult.coupon_id).where(
        SettlementFeeResult.original_business_month == business_month)
    candidates = union(historical_coupons, select(RawDouyinVerifyRecord.coupon_id).where(
        RawDouyinVerifyRecord.verify_time >= start, RawDouyinVerifyRecord.verify_time < end,
    )).subquery("month_close_candidates")
    month_coupons = select(candidates.c.coupon_id)
    order_scope = union(select(RawDouyinOrderCoupon.order_id).where(RawDouyinOrderCoupon.coupon_id.in_(month_coupons)),
                   select(SettlementFeeResult.order_id).where(
                       SettlementFeeResult.original_business_month == business_month)).subquery("month_close_orders")
    orders = select(order_scope.c.order_id)
    all_coupons = union(month_coupons, select(RawDouyinOrderCoupon.coupon_id).where(RawDouyinOrderCoupon.order_id.in_(orders)))
    skus = union(select(RawDouyinOrder.sku_id).where(RawDouyinOrder.order_id.in_(orders)),
                 select(RawDouyinVerifyRecord.sku_id).where(RawDouyinVerifyRecord.coupon_id.in_(all_coupons)))
    owners = select(RawDouyinOrder.owner_account_id).where(RawDouyinOrder.order_id.in_(orders))
    names = select(RawDouyinOrder.owner_account_name).where(RawDouyinOrder.order_id.in_(orders))
    bindings = or_(RawAwemeBinding.account_id.in_(owners), RawAwemeBinding.douyin_nickname.in_(names))
    accounts = union(owners, select(RawAwemeBinding.account_id).where(bindings))
    pois = union(select(RawDouyinVerifyRecord.poi_id).where(RawDouyinVerifyRecord.coupon_id.in_(all_coupons)),
                 select(RawAwemeBinding.poi_id).where(bindings))
    stores = union(select(DimAwemeAccount.store_id).where(DimAwemeAccount.account_id.in_(accounts)),
                   select(RawAwemeBinding.account_id).where(bindings),
                   select(DimStorePoiMapping.store_id).where(DimStorePoiMapping.poi_id.in_(pois)),
                   select(HistoricalSaleAttributionDecision.store_id).where(HistoricalSaleAttributionDecision.business_month == business_month))
    digest = hashlib.sha256(json.dumps({"protocol": CALCULATION_INPUT_PROTOCOL, "month": business_month,
        "days": revisions, "qualification": [version.version_id, version.content_sha256],
        "decisions": month_decision_digest(session, business_month)}, sort_keys=True).encode())

    def feed(model, condition, fields, paths=(), extra=()):
        # JSON paths retain type/presence (missing != null != zero), while
        # excluding unrelated large payloads and collector processing times.
        columns = [getattr(model, field) for field in fields]
        columns.extend(extra)
        for path in paths:
            expression = model.raw_payload
            for key in path:
                expression = expression[key]
            kind = (func.jsonb_typeof(expression) if session.get_bind().dialect.name == "postgresql"
                    else func.json_type(model.raw_payload, "$." + ".".join(json.dumps(key, ensure_ascii=False) for key in path)))
            columns.extend((expression, kind))
        digest.update(model.__tablename__.encode())
        rows = session.execute(select(*columns).where(condition).order_by(*[getattr(model, field) for field in fields[:1]])
                               .execution_options(yield_per=500))
        try:
            for row in rows:
                digest.update(json.dumps(list(row), ensure_ascii=False, sort_keys=True,
                                         default=_canonical_fingerprint_value, separators=(",", ":")).encode())
                digest.update(b"\n")
        finally:
            rows.close()

    feed(RawDouyinOrder, RawDouyinOrder.order_id.in_(orders),
         ("order_id", "order_status", "order_status_normalized", "sku_id", "pay_time", "sale_time", "owner_account_id", "owner_douyin_uid", "owner_account_name", "sale_channel", "sale_channel_normalized"),
         (("receipt_amount",), ("sub_order_amount_infos",), ("count",), ("owner_account_id",), ("owner_douyin_uid",),
          ("sale_info", "transfer_uid"), ("sale_info", "account_id"), ("sale_info", "transfer_douyin_uid"),
          ("order_sale_info", "transfer_uid"), ("order_sale_info", "transfer_douyin_uid")))
    feed(RawDouyinOrderCoupon, RawDouyinOrderCoupon.order_id.in_(orders),
         ("coupon_id", "order_id", "raw_order_id", "order_item_id", "coupon_status", "coupon_status_normalized", "coupon_refunded_cent", "coupon_refunded_amount_cent", "coupon_refund_time", "latest_refund_at"), (("receipt_amount",),))
    feed(RawDouyinVerifyRecord, RawDouyinVerifyRecord.coupon_id.in_(all_coupons),
         ("verify_id", "coupon_id", "verify_status", "verify_time", "poi_id", "sku_id", "cancel_time"))
    feed(DouyinRefundEvent, DouyinRefundEvent.order_id.in_(orders),
         ("refund_event_id", "order_id", "coupon_id", "refund_type", "refund_status", "refund_amount_cent", "occurred_at"),
         extra=(func.coalesce(DouyinRefundEvent.successful_observed_at, DouyinRefundEvent.created_at),))
    feed(DimSkuProductRule, DimSkuProductRule.sku_id.in_(skus),
         ("sku_id", "product_scope", "product_type", "owner_account_id", "owner_account_name", "is_active_product", "product_status_normalized", "sync_status"))
    feed(SkuFeeRule, SkuFeeRule.sku_id.in_(skus) & (SkuFeeRule.effective_date <= end.date()),
         ("rule_version", "sku_id", "promotion_service_fee_rate", "management_service_fee_rate", "effective_date", "effective_at", "rule_status"))
    feed(SettlementScopeRule, SettlementScopeRule.owner_account_id.in_(select(DimSkuProductRule.owner_account_id).where(DimSkuProductRule.sku_id.in_(skus))) & (SettlementScopeRule.effective_month <= business_month),
         ("scope_rule_version", "effective_month", "owner_account_id", "sale_channel_normalized", "is_active"))
    feed(DimAwemeAccount, DimAwemeAccount.account_id.in_(accounts),
         ("account_id", "store_id", "binding_status", "valid_from", "valid_to"))
    feed(RawAwemeBinding, bindings,
         ("binding_key", "account_id", "douyin_id", "douyin_nickname", "poi_id", "binding_status"),
         tuple((key,) for key in ("账号类型", "account_type", "craftsman_uid", "account_id_for_settlement", "bind_status", "bind_start_time", "bind_end_time", "poi_id")))
    feed(DimStorePoiMapping, DimStorePoiMapping.poi_id.in_(pois), ("poi_id", "store_id"))
    feed(DimStore, DimStore.store_id.in_(stores), ("store_id", "is_active"))
    # The policy normalizes Unicode, whitespace and dash aliases. Evaluate
    # only distinct related names, then query their exact configuration keys.
    normalized_names = sorted({normalize_owner_account_name(name) for name in session.scalars(
        names.distinct().execution_options(yield_per=500)) if name})
    for offset in range(0, len(normalized_names), 500):
        feed(DimNonCommissionOwnerAccount,
             DimNonCommissionOwnerAccount.normalized_owner_account_name.in_(normalized_names[offset:offset + 500]),
             ("normalized_owner_account_name", "owner_account_name", "is_active"))
    return digest.hexdigest()


def _calculation_preflight(session: Session, business_month: str) -> tuple[str, str | None]:
    """A complete frozen source may start calculation before any fee is pinned."""
    if session.scalar(select(SettlementStatement.id).where(
        SettlementStatement.statement_month == business_month,
        SettlementStatement.statement_status == LOCKED_STATEMENT_STATUS,
    ).limit(1)) is not None:
        return LOCKED, None
    revisions = published_days_revisions(session, business_month)
    if revisions is None:
        return WATERMARK_INCOMPLETE, None
    watermark = _calculation_inputs_digest(session, business_month, revisions)
    return (ACTIVE_REBUILD if _active_rebuild_exists(session) else CALCULATION_READY), watermark


def _sync_readiness_issue(
    session: Session, business_month: str, state: str
) -> str | None:
    """Keep exactly one alert per (month, state); clear it once ready.

    Never touches commission results or statements.
    """

    rows = list(
        session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_type == READINESS_ISSUE_TYPE
            )
        )
    )
    mine = [
        row
        for row in rows
        if (row.raw_context_json or {}).get("business_month") == business_month
    ]
    if state not in _NOT_READY_STATES:
        for row in mine:
            session.delete(row)
        return None
    keep = readiness_issue_id(business_month, state)
    for row in mine:
        if row.issue_id != keep:
            session.delete(row)
    upsert_data_quality_issue(
        session,
        keep,
        issue_type=READINESS_ISSUE_TYPE,
        message=(
            f"{business_month} 月结未派发：{state}；来源未就绪前不会生成账单。"
        ),
        severity="warning",
        raw_context_json={"business_month": business_month, "state": state},
    )
    return keep


def month_close_job_id(business_month: str, watermark: str) -> str:
    """Stable idempotency key per (month, source watermark)."""

    return f"settlement-month-close-{business_month}-w{watermark}"


def ensure_month_close_job(
    factory: sessionmaker, *, now: datetime | None = None
) -> str | None:
    """Dispatch the previous month's close once per watermark.

    Returns the job id when a job exists or was created, ``None`` when the
    month is not verifiably complete, is locked, or another rebuild is active.
    """

    if factory is None:
        return None
    if not MONTH_CLOSE_ENABLED:
        # Fail closed: never dispatch an unverified automatic close.
        return None
    business_month = previous_business_month(now)
    with session_scope(factory) as session:
        if business_month >= FIRST_MONTH:
            try:
                freeze_month(session, business_month, now=now)
            except AccountQualificationError:
                _sync_readiness_issue(session, business_month, QUALIFICATION_NOT_READY)
                return None
        state, watermark = (_calculation_preflight(session, business_month) if business_month >= FIRST_MONTH
                            else month_close_preflight(session, business_month))
        if _in_formal_window(business_month):
            # Keep the operator-visible readiness alert in sync every tick.
            _sync_readiness_issue(session, business_month, state)
        if watermark is None:
            if state in _NOT_READY_STATES:
                _logger.warning(
                    "month_close_not_ready month=%s state=%s", business_month, state
                )
            return None
        # Keep downstream generation/bundle IDs within their existing 128-char
        # storage boundary; retain and compare the complete SHA in metadata.
        job_id = month_close_job_id(business_month, watermark[:32] if business_month >= FIRST_MONTH else watermark)
        existing = session.get(JobRun, job_id)
        if existing is not None:
            if business_month >= FIRST_MONTH and (existing.metadata_json or {}).get("calculation_input_sha256") != watermark:
                raise RuntimeError("month calculation input identity conflicts with existing job")
            return job_id
        if state == ACTIVE_REBUILD:
            return None
        queue_job_run(
            session,
            job_id,
            SETTLEMENT_REBUILD_JOB_NAME,
            metadata_json={
                **settlement_month_scope_metadata(business_month),
                "trigger": "month_close",
                "source_run_id": job_id,
                "source_watermark": watermark,
                **({"account_qualification_version_id": frozen_version(session, business_month).version_id}
                   if business_month >= FIRST_MONTH else {}),
                **({"calculation_input_protocol": CALCULATION_INPUT_PROTOCOL,
                    "calculation_input_sha256": watermark, "month_close_phase": "calculate"}
                   if business_month >= FIRST_MONTH else {}),
            },
        )
    return job_id


def _active_rebuild_exists(session: Session) -> bool:
    return (
        session.scalar(
            select(JobRun.job_id)
            .where(
                JobRun.job_name == SETTLEMENT_REBUILD_JOB_NAME,
                JobRun.status.in_(("queued", "running", "retry_wait")),
            )
            .limit(1)
        )
        is not None
    )


__all__ = [
    "ACTIVE_REBUILD",
    "LOCKED",
    "NO_CURRENT_RESULTS",
    "READINESS_ISSUE_TYPE",
    "READY",
    "SHANGHAI",
    "WATERMARK_INCOMPLETE",
    "ensure_month_close_job",
    "month_business_dates",
    "month_close_job_id",
    "month_close_preflight",
    "month_source_watermark",
    "previous_business_month",
    "published_days_revisions",
    "readiness_issue_id",
]
