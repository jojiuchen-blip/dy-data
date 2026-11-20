"""Freeze internal fee trial facts independently of formal bill readiness."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Index, Integer, String, Table, Text, and_, case, func, insert, or_, select

from .schema import metadata
from .lifecycle import PublicationError


rows = Table(
    "dashboard_publication_fee_trial", metadata,
    Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("row_id", String(64), primary_key=True),
    Column("month", String(7), nullable=False),
    Column("fee_direction", Integer, nullable=False),
    Column("coupon_id", String(128), nullable=False),
    Column("order_id", String(128)),
    Column("store_id", String(128)), Column("store_name", String(255)),
    Column("product_type", String(128), nullable=False), Column("sku_id", String(128)),
    Column("fee_amount_cent", BigInteger), Column("base_amount_cent", BigInteger),
    Column("fee_rate", String(32)), Column("rule_version", String(128)),
    Column("record_status", String(16), nullable=False),
    Column("reason_code", String(128)), Column("reason", Text),
    Column("search_text", Text, nullable=False),
    CheckConstraint("fee_direction IN (1, 2)", name="ck_pub_fee_trial_direction"),
    CheckConstraint("record_status IN ('CALCULATED', 'PENDING', 'EXCLUDED')", name="ck_pub_fee_trial_status"),
    CheckConstraint("(record_status = 'CALCULATED' AND fee_amount_cent IS NOT NULL AND base_amount_cent IS NOT NULL) OR "
                    "(record_status <> 'CALCULATED' AND fee_amount_cent IS NULL AND base_amount_cent IS NULL)",
                    name="ck_pub_fee_trial_known_amount"),
)
Index("ix_pub_fee_trial_filter", rows.c.publication_id, rows.c.month, rows.c.fee_direction, rows.c.store_id)


def _identity(*parts):
    return sha256("\x1f".join(map(str, parts)).encode()).hexdigest()


def _stored_trial_basis(qualification_version_id):
    """Keep the already-calculated exact-name trial readable while mapping proof evolves.

    The formal close applies its current supplemental evidence contract. An
    internal trial may still display the prior calculation and its preserved
    name/qualification/store basis, with all pending diagnostics kept visible.
    """
    from ..models import AccountQualificationVersion, SettlementFeeResult
    from apps.worker.account_qualification import SALE_ACCOUNT_MATCH_POLICY, SALE_NAME_PATHS

    evidence = SettlementFeeResult.sale_account_match_json
    version_sha = select(AccountQualificationVersion.content_sha256).where(
        AccountQualificationVersion.version_id == qualification_version_id).scalar_subquery()
    return and_(SettlementFeeResult.result_status.in_((1, 2)),
        SettlementFeeResult.account_qualification_version_id == qualification_version_id,
        evidence["policy"].as_string() == SALE_ACCOUNT_MATCH_POLICY,
        evidence["qualification_version_id"].as_string() == qualification_version_id,
        evidence["content_sha256"].as_string() == version_sha,
        func.coalesce(evidence["account_name"].as_string(), "") != "",
        func.coalesce(evidence["account_id"].as_string(), "") != "",
        func.coalesce(evidence["douyin_id"].as_string(), "") != "",
        evidence["source_field"].as_string().in_(SALE_NAME_PATHS),
        SettlementFeeResult.sale_store_id.is_not(None),
        evidence["store_id"].as_string() == SettlementFeeResult.sale_store_id)


def build(session, publication_id, months, readiness):
    """Capture existing authority and exact monthly diagnostics in the builder transaction."""
    from ..models import DataQualityIssue, DimSkuProductRule, DimStore, RawDouyinOrder, RawDouyinOrderCoupon, SettlementFeeAdjustment, SettlementFeeResult, SettlementMonthClose, SettlementStatementEntry, StoreFinanceProfile
    from .finance import dimensions
    from apps.worker.monthly_close_scope import _is_confirmed_exclusion
    from apps.worker.settlement import _sparse_authority_source, select_coupon_ids_by_verify_business_month

    stores = {item.store_id: item for item in session.scalars(select(DimStore))}
    search_saps = defaultdict(list)
    for profile in session.scalars(select(StoreFinanceProfile).where(StoreFinanceProfile.is_current.is_(True), StoreFinanceProfile.is_tombstone.is_(False))):
        if profile.sap_code:
            search_saps[profile.store_id].append(profile.sap_code)
    count = 0
    for month in months:
        if month < "2026-10":
            continue
        close = session.get(SettlementMonthClose, month)
        if close is None:
            continue
        source = _sparse_authority_source((month,))
        result = SettlementFeeResult.__table__.alias("trial_result")
        adjustment = SettlementFeeAdjustment.__table__.alias("trial_adjustment")
        entry = SettlementStatementEntry.__table__.alias("trial_entry")
        sku = DimSkuProductRule.__table__.alias("trial_sku")
        joined = source.outerjoin(adjustment, and_(source.c.source_kind == "adjustment", adjustment.c.adjustment_id == source.c.source_id))
        joined = joined.outerjoin(entry, entry.c.statement_entry_id == source.c.frozen_entry_id)
        joined = joined.outerjoin(result, result.c.fee_result_id == func.coalesce(entry.c.original_fee_result_id,
            case((source.c.source_kind == "result", source.c.source_id), else_=adjustment.c.original_fee_result_id)))
        sku_id = func.coalesce(entry.c.sku_id_snapshot, result.c.sku_id)
        joined = joined.outerjoin(sku, sku.c.sku_id == sku_id)
        # A previous invalid current result must not reappear in a new trial.
        evidence_ids = select(SettlementFeeResult.fee_result_id).where(_stored_trial_basis(close.qualification_version_id))
        from .commission_types import JINGCHENG_PRODUCT_TYPE, OFFICIAL_PRODUCT_TYPE
        display_type = case(
            (or_(source.c.source_product_type == OFFICIAL_PRODUCT_TYPE, sku.c.product_type == OFFICIAL_PRODUCT_TYPE), OFFICIAL_PRODUCT_TYPE),
            (sku.c.product_type == JINGCHENG_PRODUCT_TYPE, JINGCHENG_PRODUCT_TYPE),
            else_=case((source.c.source_product_type == "all", "unknown"), else_=source.c.source_product_type))
        query = select(source, func.coalesce(entry.c.coupon_id, result.c.coupon_id).label("coupon_id"),
            sku_id.label("sku_id"), display_type.label("display_type"))
        query = query.select_from(joined).where(or_(source.c.frozen_entry_id.is_not(None), source.c.source_kind == "adjustment",
            result.c.fee_result_id.in_(evidence_ids)))
        batch = []
        calculated = set()
        for value in session.execute(query).mappings():
            if not value["coupon_id"]:
                continue
            store = stores.get(value["store_id"])
            record = dict(publication_id=publication_id, row_id=_identity(month, value["source_kind"], value["source_id"]),
                month=month, fee_direction=value["fee_direction"], coupon_id=value["coupon_id"], order_id=value["order_id"],
                store_id=value["store_id"], store_name=store.store_name if store else None,
                product_type=value["display_type"] or "unknown", sku_id=value["sku_id"],
                fee_amount_cent=value["fee_amount_cent"], base_amount_cent=value["base_amount_cent"],
                fee_rate=str(value["source_fee_rate"]) if value["source_fee_rate"] is not None else None,
                rule_version=value["source_rule_version"], record_status="CALCULATED", reason_code=None, reason=None)
            record["search_text"] = " ".join(str(item or "") for item in (
                record["coupon_id"], record["order_id"], record["store_id"], record["store_name"],
                *search_saps.get(record["store_id"], ())))
            batch.append(record)
            calculated.add((value["coupon_id"], value["fee_direction"]))
        diagnostics = defaultdict(list)
        for issue in session.scalars(select(DataQualityIssue).where(DataQualityIssue.source_run_id == close.source_job_id).order_by(DataQualityIssue.issue_id)):
            context = issue.raw_context_json or {}
            direction = context.get("fee_direction")
            for selected in ((direction,) if direction in (1, 2) else (1, 2)):
                if issue.coupon_id:
                    diagnostics[issue.coupon_id, selected].append(issue)
        candidates = set(select_coupon_ids_by_verify_business_month(session, month, monthly=True))
        # Include diagnosed event-month refunds and cancellation records too.
        candidates.update(coupon_id for coupon_id, _ in diagnostics)
        candidate_details = {}
        candidates = sorted(candidates)
        for offset in range(0, len(candidates), 500):
            subset = candidates[offset:offset + 500]
            details = session.execute(select(RawDouyinOrderCoupon.coupon_id, RawDouyinOrderCoupon.order_id,
                RawDouyinOrder.sku_id, DimSkuProductRule.product_type).join(RawDouyinOrder,
                RawDouyinOrder.id == RawDouyinOrderCoupon.raw_order_id).outerjoin(DimSkuProductRule,
                DimSkuProductRule.sku_id == RawDouyinOrder.sku_id).where(RawDouyinOrderCoupon.coupon_id.in_(subset))).mappings()
            candidate_details.update({item["coupon_id"]: item for item in details})
        for coupon_id in candidates:
            for direction in (1, 2):
                issues = diagnostics.get((coupon_id, direction), ())
                exclusions = [issue for issue in issues if _is_confirmed_exclusion(issue)]
                pending = [issue for issue in issues if issue.severity == "error" and issue not in exclusions]
                if (coupon_id, direction) in calculated and not pending:
                    continue
                selected = pending or exclusions or issues
                issue = selected[0] if selected else None
                coupon = candidate_details.get(coupon_id, {})
                context = (issue.raw_context_json or {}) if issue is not None else {}
                # A diagnostic's explicit direction store is usable for its
                # visibility only. Missing ownership remains global-only.
                store_id = context.get("sale_store_id" if direction == 1 else "verify_store_id")
                store = stores.get(store_id)
                if store is None:
                    store_id = None
                record = dict(publication_id=publication_id, row_id=_identity(month, coupon_id, direction, "diagnostic"),
                    month=month, fee_direction=direction, coupon_id=coupon_id,
                    order_id=issue.order_id if issue is not None else coupon.get("order_id"),
                    store_id=store_id, store_name=store.store_name if store else None,
                    product_type=coupon.get("product_type") or "unknown", sku_id=coupon.get("sku_id"),
                    fee_amount_cent=None, base_amount_cent=None, fee_rate=None, rule_version=None,
                    record_status="EXCLUDED" if exclusions and not pending else "PENDING",
                    reason_code=context.get("reason_code") or (issue.issue_type if issue else "monthly_trial_no_fee_result"),
                    reason="；".join(dict.fromkeys(item.message for item in selected)) if selected else "本次月结尚未形成可用费用记录")
                record["search_text"] = " ".join(str(item or "") for item in (
                    record["coupon_id"], record["order_id"], record["store_id"], record["store_name"], *search_saps.get(store_id, ())))
                batch.append(record)
        for offset in range(0, len(batch), 500):
            session.execute(insert(rows), batch[offset:offset + 500])
        facts = (readiness.get("months") or {}).get(month, {})
        session.execute(insert(dimensions).values(publication_id=publication_id, kind="fee_trial", key=month,
            value={"schema_version": 1, "source_input_sha256": close.source_input_sha256,
                "source_success_days": facts.get("success_days"), "source_total_days": facts.get("total_days"),
                "scope_unresolved": close.unscoped_issue_count > 0 or any(
                    item["record_status"] == "PENDING" and item["store_id"] is None for item in batch),
                "source_job_id": close.source_job_id}))
        count += len(batch) + 1
    return count


def conditions(publication_id, *, month, fee_direction, scope_store_ids=None, store_id=None, product_type="all", q=None, record_status=None):
    result = [rows.c.publication_id == publication_id, rows.c.month == month,
        rows.c.fee_direction == (1 if fee_direction == "PROMOTION" else 2)]
    if scope_store_ids is not None:
        result.append(rows.c.store_id.in_(scope_store_ids))
    if store_id is not None:
        result.append(rows.c.store_id == store_id)
    if product_type != "all":
        result.append(rows.c.product_type == product_type)
    if q:
        result.append(rows.c.search_text.ilike("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
    if record_status:
        result.append(rows.c.record_status == record_status)
    return result


def read(session, publication_id, *, page=1, page_size=50, export=False, **filters):
    """Aggregate and page the pinned facts, applying current scope to every query."""
    from .finance import dimensions
    marker = session.scalar(select(dimensions.c.value).where(dimensions.c.publication_id == publication_id,
        dimensions.c.kind == "fee_trial", dimensions.c.key == filters["month"]))
    if not marker or marker.get("schema_version") != 1:
        raise PublicationError("PUBLICATION_TRIAL_NOT_READY", "该账期尚无可读取的内部试算版本，请稍后读取最新结果。", 503)
    where = conditions(publication_id, **filters)
    totals = session.execute(select(
        func.count().label("total"),
        func.coalesce(func.sum(rows.c.fee_amount_cent), 0).label("amount"),
        *[func.count(func.distinct(case((rows.c.record_status == status, rows.c.coupon_id)))).label(status)
          for status in ("CALCULATED", "PENDING", "EXCLUDED")],
        func.count(func.distinct(rows.c.coupon_id)).label("candidates"),
    ).where(*where)).mappings().one()
    scoped = filters.get("scope_store_ids") is not None or filters.get("store_id") is not None or filters.get("product_type", "all") != "all" or bool(filters.get("q"))
    unresolved = marker.get("scope_unresolved", True)
    reason_rows = session.execute(select(rows.c.reason_code, rows.c.reason,
        func.count(func.distinct(rows.c.coupon_id))).where(*where, rows.c.record_status == "PENDING")
        .group_by(rows.c.reason_code, rows.c.reason).order_by(rows.c.reason_code, rows.c.reason))
    fields = [column for column in rows.c if column.name not in {"publication_id", "row_id", "search_text", "month", "fee_direction"}]
    query = select(*fields).where(*where).order_by(rows.c.coupon_id, rows.c.record_status, rows.c.row_id)
    query = query.limit(100001) if export else query.offset((page - 1) * page_size).limit(page_size)
    items = [dict(item) for item in session.execute(query).mappings()]
    known_amount = int(totals["amount"]) if totals["CALCULATED"] or (not unresolved and totals["PENDING"] == 0) else None
    summary = {"calculated_fee_cent": known_amount, "calculated_coupon_count": totals["CALCULATED"],
        "pending_coupon_count": totals["PENDING"], "excluded_coupon_count": totals["EXCLUDED"],
        "candidate_coupon_count": totals["candidates"],
        "coverage_complete": not unresolved and totals["PENDING"] == 0}
    coverage = {"scope_unresolved": unresolved,
        "source_success_days": marker.get("source_success_days"), "source_total_days": marker.get("source_total_days"),
        "reasons": [{"code": code, "label": label, "coupon_count": number} for code, label, number in reason_rows],
        "note": ("仅统计当前筛选和权限内可归属的记录；归属未定记录另待核实。" if scoped else
                 "包含本次月结已有费用与待核、明确排除的记录；待核金额尚无法确定。")}
    return {"month": filters["month"], "fee_direction": filters["fee_direction"], "status": "TRIAL",
        "summary": summary, "coverage": coverage, "list": items,
        "total": totals["total"], "page": page, "page_size": page_size}
