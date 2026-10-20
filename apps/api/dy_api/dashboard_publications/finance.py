"""Immutable settlement and finance display projections.

Builders alone consult business facts and the request-pinned settlement lineage.
Readers only select publication tables. Confirmation, dispute and invoice write
eligibility must continue to be checked against current facts by the routes.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    JSON, BigInteger, Boolean, Column, ForeignKey, Index, Integer, String,
    Table, Text, and_, case, func, insert, or_, select, text,
)
from sqlalchemy.orm import Session

from .schema import metadata
from . import period_readiness


FORMAL_START = "2026-08"
RANK_METRICS = (
    "sales_order_count", "sales_amount_cent", "verified_order_count",
    "verified_amount_cent", "promotion_net_fee_cent", "management_net_fee_cent",
    "net_settlement_reference_cent",
)
MONTH_METRICS = RANK_METRICS[:-3] + (
    "promotion_base_cent", "promotion_original_fee_cent",
    "promotion_adjustment_fee_cent", "promotion_net_fee_cent",
    "management_base_cent", "management_original_fee_cent",
    "management_adjustment_fee_cent", "management_net_fee_cent",
    "net_settlement_reference_cent",
)
SUMMARY_METRICS = (
    "statement_total_cent", "confirmed_amount_cent", "pending_invoice_amount_cent",
    "issued_amount_cent", "settled_or_deducted_amount_cent",
)
COMMON_SOURCE_TABLES = frozenset({
    "dim_stores", "dim_sku_product_rules", "clue_center_orders", "raw_douyin_orders",
    "raw_douyin_verify_records", "settlement_order_details", "agg_store_ranking",
    "agg_store_monthly_settlement", "settlement_ranking_overlay", "settlement_monthly_overlay",
    "settlement_projection_active", "settlement_projection_generation",
    "settlement_projection_partition_manifest", "settlement_projection_compaction_closure",
    "settlement_statement",
})
SETTLEMENT_SOURCE_TABLES = COMMON_SOURCE_TABLES | {
    "settlement_statement_line", "settlement_statement_entry", "settlement_fee_result",
    "settlement_fee_result_current", "settlement_fee_adjustment",
}
FINANCE_SOURCE_TABLES = COMMON_SOURCE_TABLES | {
    "settlement_statement_confirmation", "promotion_invoice", "promotion_invoice_allocation",
    "invoice_record", "invoice_status_event", "store_finance_profile",
    "management_carryforward_application", "sap_suggestion", "finance_operation_audit",
    "finance_import_batch",
}


def _publication_column():
    return Column("publication_id", String(64), ForeignKey(
        "dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True)


ranking = Table(
    "dashboard_publication_settlement_ranking", metadata,
    _publication_column(), Column("period_type", Integer, primary_key=True),
    Column("period_key", String(7), primary_key=True),
    Column("store_id", String(128), primary_key=True),
    Column("product_scope", String(128), primary_key=True),
    Column("product_type", String(128), primary_key=True),
    Column("store_name", String(255), nullable=False),
    *(Column(key, BigInteger, nullable=False) for key in RANK_METRICS),
)
monthly = Table(
    "dashboard_publication_settlement_monthly", metadata,
    _publication_column(), Column("month", String(7), primary_key=True),
    Column("store_id", String(128), primary_key=True),
    Column("product_scope", String(128), primary_key=True),
    Column("product_type", String(128), primary_key=True),
    *(Column(key, BigInteger, nullable=False) for key in MONTH_METRICS),
    Column("statement", JSON), Column("lines", JSON, nullable=False),
)
dimensions = Table(
    "dashboard_publication_finance_dimensions", metadata,
    _publication_column(), Column("kind", String(32), primary_key=True),
    Column("key", String(128), primary_key=True), Column("value", JSON, nullable=False),
)
statements = Table(
    "dashboard_publication_finance_statements", metadata,
    _publication_column(), Column("statement_id", String(128), primary_key=True),
    Column("fee_direction", String(16), primary_key=True),
    Column("store_id", String(128), nullable=False),
    Column("month", String(7), nullable=False),
    Column("amount_cent", BigInteger, nullable=False),
    Column("confirmed_cent", BigInteger, nullable=False),
    Column("issued_cent", BigInteger, nullable=False),
    Column("settled_cent", BigInteger, nullable=False),
)
invoices = Table(
    "dashboard_publication_finance_invoices", metadata,
    _publication_column(), Column("position", Integer, primary_key=True),
    Column("fee_direction", String(16), nullable=False),
    Column("store_id", String(128), nullable=False),
    Column("month", String(7), nullable=False),
    Column("statement_id", String(128)),
    Column("status_code", Integer), Column("confirmed", Boolean, nullable=False),
    Column("is_history", Boolean, nullable=False),
    Column("is_projection", Boolean, nullable=False),
    Column("search_text", Text, nullable=False),
    Column("amount_cent", BigInteger, nullable=False),
    Column("item", JSON, nullable=False),
)
pending = Table(
    "dashboard_publication_finance_pending", metadata,
    _publication_column(), Column("position", Integer, primary_key=True),
    Column("fee_direction", String(16), nullable=False),
    Column("store_id", String(128), nullable=False),
    Column("as_of_month", String(7), nullable=False),
    Column("month", String(7)), Column("amount_cent", BigInteger, nullable=False),
)
pending_members = Table(
    "dashboard_publication_finance_pending_members", metadata,
    _publication_column(), Column("position", Integer, primary_key=True),
    Column("statement_id", String(128), primary_key=True),
)
Index("ix_pub_finance_invoice_filter", invoices.c.publication_id,
      invoices.c.fee_direction, invoices.c.month, invoices.c.store_id)
Index("ix_pub_finance_statement_filter", statements.c.publication_id,
      statements.c.fee_direction, statements.c.month, statements.c.store_id)
Index("ix_pub_finance_pending_filter", pending.c.publication_id,
      pending.c.fee_direction, pending.c.as_of_month, pending.c.month)


def _json_value(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _write(session, table, rows):
    for offset in range(0, len(rows), 500):
        session.execute(insert(table), rows[offset:offset + 500])


def _months_through(months, cutoff):
    # Include empty months through publication time so carry-forward can be
    # selected for an empty display month without a source read at request time.
    last = max([cutoff.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m"), *months])
    first = min([FORMAL_START, *months])
    start_year, start_month = map(int, first.split("-"))
    end_year, end_month = map(int, last.split("-"))
    return [f"{number // 12:04d}-{number % 12 + 1:02d}" for number in range(
        start_year * 12 + start_month - 1, end_year * 12 + end_month)]


def _source_context(session, cutoff):
    # Deferred imports avoid the route -> publication -> route import cycle.
    from ..routes._data import DashboardDataStore

    store = DashboardDataStore(session)
    store._pinned_aggregate_generation()
    # Formal statements may already exist for a month with no computed rows.
    # Ranking-only partitions must also survive independently of monthly data.
    from ..models import SettlementStatement, AggStoreRanking, SettlementRankingOverlay
    from apps.worker.month_close import previous_business_month

    source_months = set(store.list_statement_months())
    month_keys = set(source_months)
    selectable_months = source_months | {previous_business_month(cutoff)}
    for month, is_current in session.execute(select(
        SettlementStatement.statement_month, SettlementStatement.is_current)):
        month_keys.add(month)
        if is_current:
            selectable_months.add(month)
    month_keys.update(session.scalars(select(AggStoreRanking.period_key)))
    month_keys.update(session.scalars(select(SettlementRankingOverlay.period_key)))
    months = _months_through({key for key in month_keys if key}, cutoff)
    return store, months, sorted(selectable_months, reverse=True)


def _build_dimensions(session, publication_id, store, statement_months, cutoff):
    rows = [{"publication_id": publication_id, "kind": "store",
             "key": item["store_id"], "value": item}
            for item in store.list_stores(scope_store_ids=None)]
    values = {
        "product_scopes": store.list_product_scopes(),
        "product_scope_type_map": store.product_scope_type_map(),
        "product_types": store.list_product_types(),
        "default_product_type": store.default_product_type(),
        "sale_months": store.list_sale_months(),
        "verify_months": store.list_verify_months(),
        # The internal carry-forward horizon includes the unfinished current
        # month. Selectors retain actual source periods plus the last completed
        # Shanghai month, so an empty current month cannot become the default.
        "statement_months": sorted(statement_months, reverse=True),
        "period_types": ["MONTHLY", "CUMULATIVE"],
        "fee_directions": ["PROMOTION", "MANAGEMENT"],
        "formal_period_start_month": FORMAL_START, "timezone": "Asia/Shanghai",
    }
    rows.append({"publication_id": publication_id, "kind": "filters", "key": "all",
                 "value": values})
    rows.append({"publication_id": publication_id, "kind": "source", "key": "settlement",
                 "value": {"has_generation": store._pinned_aggregate_generation() is not None}})
    readiness = period_readiness.capture(session, cutoff)
    rows.append({"publication_id": publication_id, "kind": "period_readiness", "key": "v1",
                 "value": readiness})
    _write(session, dimensions, rows)
    ready = sum(item["ready"] is True for item in readiness["months"].values())
    return len(rows), {"ready_periods": ready, "incomplete_periods": len(readiness["months"]) - ready}


def _monthly_lines(session, store, month):
    """Batch freeze statement headers, preview lines and rate/version summaries."""
    from ..models import SettlementStatement, SettlementStatementLine

    formal = list(session.scalars(select(SettlementStatement).where(
        SettlementStatement.is_current.is_(True), SettlementStatement.statement_month == month)))
    headers = {row.store_id: {
        "statement_id": row.statement_id,
        "statement_status": {1: "GENERATING", 2: "PENDING_CONFIRMATION", 3: "CONFIRMED", 4: "LOCKED"}[row.statement_status],
        "confirmed_at": row.confirmed_at, "locked_at": row.locked_at, "lock_version": row.lock_version,
    } for row in formal}
    locked = {row.statement_id: row.store_id for row in formal if row.statement_status == 4}
    # Business interpretation remains here in the builder. SQL groups current
    # fee facts once per month instead of re-reading them for every store.
    preview_sql = """
        SELECT CASE WHEN r.fee_direction = 1 THEN r.sale_store_id ELSE r.verify_store_id END AS store_id,
               NULL AS statement_line_id, r.fee_direction, r.product_scope, r.product_type,
               SUM(CASE WHEN r.original_business_month = :month THEN 1 ELSE 0 END) AS original_entry_count,
               SUM(COALESCE(a.entry_count, 0)) AS adjustment_entry_count,
               SUM(CASE WHEN r.original_business_month = :month THEN r.fee_base_cent ELSE 0 END) AS original_base_cent,
               SUM(COALESCE(a.base_cent, 0)) AS adjustment_base_cent,
               SUM(CASE WHEN r.original_business_month = :month THEN r.fee_base_cent ELSE 0 END)
                   + SUM(COALESCE(a.base_cent, 0)) AS net_base_cent,
               SUM(CASE WHEN r.original_business_month = :month THEN r.fee_amount_cent ELSE 0 END) AS original_fee_cent,
               SUM(COALESCE(a.fee_cent, 0)) AS adjustment_fee_cent,
               SUM(CASE WHEN r.original_business_month = :month THEN r.fee_amount_cent ELSE 0 END)
                   + SUM(COALESCE(a.fee_cent, 0)) AS net_fee_cent
        FROM settlement_fee_result_current c
        JOIN settlement_fee_result r ON r.fee_result_id = c.fee_result_id
        LEFT JOIN (
            SELECT original_fee_result_id, COUNT(*) AS entry_count,
                   SUM(adjustment_base_cent) AS base_cent, SUM(adjustment_fee_cent) AS fee_cent
            FROM settlement_fee_adjustment WHERE adjustment_posting_month = :month
            GROUP BY original_fee_result_id
        ) a ON a.original_fee_result_id = r.fee_result_id
        WHERE r.original_business_month = :month OR COALESCE(a.entry_count, 0) > 0
        GROUP BY CASE WHEN r.fee_direction = 1 THEN r.sale_store_id ELSE r.verify_store_id END,
                 r.fee_direction, r.product_scope, r.product_type
    """
    preview = [dict(row) for row in session.execute(text(preview_sql), {"month": month}).mappings()]
    locked_rows = []
    if locked:
        fields = ("statement_line_id", "fee_direction", "product_scope", "product_type",
                  "original_entry_count", "adjustment_entry_count", "original_base_cent",
                  "adjustment_base_cent", "net_base_cent", "original_fee_cent", "adjustment_fee_cent", "net_fee_cent")
        locked_rows = [dict(row) for row in session.execute(select(
            SettlementStatementLine.statement_id, *(getattr(SettlementStatementLine, key) for key in fields)
        ).where(SettlementStatementLine.statement_id.in_(locked))).mappings()]
    rate_sql = """
        SELECT DISTINCT CASE WHEN r.fee_direction = 1 THEN r.sale_store_id ELSE r.verify_store_id END AS store_id,
               r.fee_direction, r.product_scope, r.product_type, r.fee_rate, r.rule_version,
               NULL AS statement_line_id
        FROM settlement_fee_result_current c
        JOIN settlement_fee_result r ON r.fee_result_id = c.fee_result_id
        WHERE r.original_business_month = :month OR EXISTS (
            SELECT 1 FROM settlement_fee_adjustment a
            WHERE a.original_fee_result_id = r.fee_result_id AND a.adjustment_posting_month = :month)
        UNION
        SELECT DISTINCT CASE WHEN r.fee_direction = 1 THEN r.sale_store_id ELSE r.verify_store_id END AS store_id,
               r.fee_direction, r.product_scope, r.product_type, r.fee_rate, r.rule_version,
               e.statement_line_id
        FROM settlement_statement s
        JOIN settlement_statement_line line ON line.statement_id = s.statement_id
        JOIN settlement_statement_entry e ON e.statement_line_id = line.statement_line_id
        JOIN settlement_fee_result r ON r.fee_result_id = e.original_fee_result_id
        WHERE s.is_current = TRUE AND s.statement_status = 4 AND s.statement_month = :month
          AND line.fee_direction = r.fee_direction
          AND line.product_scope = r.product_scope AND line.product_type = r.product_type
    """
    rate_groups = {}
    for row in session.execute(text(rate_sql), {"month": month}).mappings():
        key = (row["store_id"], row["fee_direction"], row["product_scope"], row["product_type"], row["statement_line_id"])
        rates, versions = rate_groups.setdefault(key, (set(), set()))
        rates.add(store._format_rate(row["fee_rate"]))
        if row["rule_version"]:
            versions.add(str(row["rule_version"]))
    lines_by_store = {}
    locked_stores = set(locked.values())
    for row in preview:
        if not row["store_id"] or row["store_id"] in locked_stores:
            continue
        lines_by_store.setdefault(row["store_id"], []).append(row)
    for row in locked_rows:
        row["store_id"] = locked[row.pop("statement_id")]
        lines_by_store.setdefault(row["store_id"], []).append(row)
    for store_id, lines in lines_by_store.items():
        for line in lines:
            key = (store_id, line["fee_direction"], line["product_scope"], line["product_type"], line["statement_line_id"])
            rates, versions = rate_groups.get(key, (set(), set()))
            line.update(min_fee_rate=min(rates) if rates else None, max_fee_rate=max(rates) if rates else None,
                rule_version_count=len(versions), fee_rates=sorted(rates), rule_versions=sorted(versions))
            line["fee_direction"] = "PROMOTION" if line["fee_direction"] == 1 else "MANAGEMENT"
            line.pop("store_id", None)
        lines.sort(key=lambda line: (line["fee_direction"] == "MANAGEMENT", line["product_scope"], line["product_type"]))
    return headers, lines_by_store


def build_settlement(session: Session, publication_id: str, cutoff: datetime) -> dict:
    """Freeze resolved ranking partitions and monthly display facts; never commit."""
    store, months, selectable_months = _source_context(session, cutoff)
    ranking_count = monthly_count = 0
    for month in months:
        for period_type in (1, 2):
            if store._pinned_aggregate_generation() is None:
                source, condition, params = ("agg_store_ranking AS source",
                    "source.period_type = :type AND source.period_key = :month",
                    {"type": period_type, "month": month})
            else:
                source, condition, params = store._ranking_source_spec(
                    period_type=period_type, period_key=month)
            if source is None:
                continue
            columns = ("store_id", "store_name", "product_scope", "product_type", *RANK_METRICS)
            rows = session.execute(text(
                f"SELECT {', '.join('source.' + key for key in columns)} "
                f"FROM {source} WHERE {condition}"), params).mappings()
            batch = []
            for row in rows:
                batch.append({"publication_id": publication_id, "period_type": period_type,
                              "period_key": month, **dict(row)})
                if len(batch) == 500:
                    _write(session, ranking, batch)
                    ranking_count += len(batch)
                    batch = []
            _write(session, ranking, batch)
            ranking_count += len(batch)
        if store._pinned_aggregate_generation() is None:
            source, condition, params = ("agg_store_monthly_settlement AS source",
                "source.month = :month", {"month": month})
        else:
            source, condition, params = store._monthly_source_spec(month=month)
        source_rows = {} if source is None else {
            (row["store_id"], row["product_scope"], row["product_type"]): dict(row)
            for row in session.execute(text("SELECT source.* "
                f"FROM {source} WHERE {condition}"), params).mappings()}
        keys = set(source_rows)
        headers, lines_by_store = _monthly_lines(session, store, month)
        keys.update((store_id, "all", "all") for store_id in headers)
        for store_id, lines in lines_by_store.items():
            for line in lines:
                keys.update((store_id, scope, product_type)
                    for scope in {"all", line["product_scope"]}
                    for product_type in {"all", line["product_type"]})
        batch = []
        for store_id, product_scope, product_type in sorted(keys):
            statement = headers.get(store_id)
            lines = [line for line in lines_by_store.get(store_id, [])
                if (product_scope == "all" or line["product_scope"] == product_scope)
                and (product_type == "all" or line["product_type"] == product_type)]
            values = source_rows.get((store_id, product_scope, product_type), {})
            metrics = {key: int(values.get(key) or 0) for key in MONTH_METRICS}
            if statement and statement["statement_status"] == "LOCKED":
                for direction in ("PROMOTION", "MANAGEMENT"):
                    selected = [line for line in lines if line["fee_direction"] == direction]
                    for target, field in (("base_cent", "net_base_cent"),
                            ("original_fee_cent", "original_fee_cent"),
                            ("adjustment_fee_cent", "adjustment_fee_cent"),
                            ("net_fee_cent", "net_fee_cent")):
                        metrics[f"{direction.lower()}_{target}"] = sum(line[field] for line in selected)
            metrics["net_settlement_reference_cent"] = metrics["promotion_net_fee_cent"] - metrics["management_net_fee_cent"]
            batch.append({"publication_id": publication_id, "month": month,
                "store_id": store_id, "product_scope": product_scope,
                "product_type": product_type,
                **metrics,
                "statement": _json_value(statement),
                "lines": _json_value(lines)})
        _write(session, monthly, batch)
        monthly_count += len(batch)
    dimension_count, period_stats = _build_dimensions(session, publication_id, store, selectable_months, cutoff)
    return {"row_count": ranking_count + monthly_count + dimension_count,
            "ranking_rows": ranking_count, "monthly_rows": monthly_count,
            "source_generation_id": store._pinned_aggregate_generation(), "data_as_of": None, **period_stats}


def _finance_display_context(session):
    from ..models import DimStore, InvoiceStatusEvent, StoreFinanceProfile

    names = dict(session.execute(select(DimStore.store_id, DimStore.store_name)).all())
    profiles = list(session.scalars(select(StoreFinanceProfile).where(StoreFinanceProfile.is_current.is_(True))))
    saps, effective, candidates = {}, {}, {}
    for profile in profiles:
        if not profile.is_tombstone:
            saps.setdefault(profile.store_id, []).append(profile.sap_code)
        if profile.profile_type == 1:
            effective[profile.store_id] = None if profile.is_tombstone else profile.sap_code
        elif not profile.is_tombstone and profile.sap_code is not None:
            candidates.setdefault(profile.store_id, []).append(profile)
    for store_id, rows in candidates.items():
        if store_id not in effective:
            effective[store_id] = max(rows, key=lambda row: (row.version_no, row.updated_at)).sap_code
    rejection_reasons = {}
    for row in session.execute(select(InvoiceStatusEvent.invoice_id, InvoiceStatusEvent.result_reason).where(
        InvoiceStatusEvent.to_status == 4).order_by(InvoiceStatusEvent.occurred_at.desc(), InvoiceStatusEvent.event_id.desc())):
        rejection_reasons.setdefault(row.invoice_id, row.result_reason)
    return {"names": names, "search_saps": saps, "effective_saps": effective, "rejections": rejection_reasons}


def _search_text(context, statement, item):
    return "\n".join(str(value or "").lower() for value in (
        statement.store_id, statement.store_name_snapshot, statement.sap_code_snapshot,
        item.get("invoice_number"), context["names"].get(statement.store_id),
        *context["search_saps"].get(statement.store_id, [])))


def _formal_invoice_item(source, direction, invoice, allocation, statement, confirmations, context):
    code = 1 if direction == "PROMOTION" else 2
    confirmation = confirmations.get((statement.statement_id, code))
    confirmed = confirmation is not None
    if invoice is not None:
        item = source._promotion_invoice_item(invoice, allocation) if code == 1 else {
            **source._management_invoice_item(invoice), "status": "APPROVED_SETTLED"}
    else:
        item = {"invoice_id": None, "store_id": statement.store_id,
            "statement_id": statement.statement_id, "statement_month": statement.statement_month,
            "fee_direction": direction, "version_no": None, "is_current": None,
            "invoice_number": None, "invoice_date": None, "invoice_amount_cent": None,
            "status": "PENDING_INVOICE", "registered_at": None}
        item.update({"settlement_batch_month": None, "allocated_amount_cent": 0} if code == 1 else {
            "source_type": None, "import_batch_id": None, "factory_deduction_date": None,
            "factory_deduction_amount_cent": None, "settled_at": None})
    item.update(processing_status="SUBMITTED" if invoice is not None else
        "PENDING_SUBMISSION" if confirmed else "PENDING_CONFIRMATION",
        store_name=statement.store_name_snapshot,
        effective_sap_code=context["effective_saps"].get(statement.store_id),
        statement_amount_cent=getattr(statement, f"{direction.lower()}_net_fee_cent"),
        confirmed_amount_cent=confirmation.confirmed_amount_cent if confirmed else None)
    if code == 1:
        item["rejection_reason"] = context["rejections"].get(invoice.invoice_id) if invoice else None
    return item


def build_finance(session: Session, publication_id: str, cutoff: datetime) -> dict:
    """Freeze finance display rows and pre-evaluated carry-forward amounts."""
    from ..models import (
        InvoiceRecord, PromotionInvoice, PromotionInvoiceAllocation,
        SettlementStatement, SettlementStatementConfirmation,
    )
    from ..routes import dashboard as source

    store, months, selectable_months = _source_context(session, cutoff)
    final_month = months[-1]
    statement_rows = list(session.scalars(select(SettlementStatement).where(
        SettlementStatement.is_current.is_(True))))
    confirmations = {(row.statement_id, row.fee_direction): row for row in session.scalars(
        select(SettlementStatementConfirmation).where(
            SettlementStatementConfirmation.confirmation_status == 1))}
    display_context = _finance_display_context(session)
    totals = {}
    for statement in statement_rows:
        for direction, code in (("PROMOTION", 1), ("MANAGEMENT", 2)):
            confirmation = confirmations.get((statement.statement_id, code))
            totals[statement.statement_id, direction] = {
                "publication_id": publication_id, "statement_id": statement.statement_id,
                "fee_direction": direction, "store_id": statement.store_id,
                "month": statement.statement_month,
                "amount_cent": int(getattr(statement, f"{direction.lower()}_net_fee_cent") or 0),
                "confirmed_cent": int(confirmation.confirmed_amount_cent or 0) if confirmation else 0,
                "issued_cent": 0, "settled_cent": 0,
            }
    allocations = session.execute(select(PromotionInvoiceAllocation, PromotionInvoice).join(
        PromotionInvoice, PromotionInvoice.invoice_id == PromotionInvoiceAllocation.invoice_id
    ).where(PromotionInvoiceAllocation.is_current.is_(True),
            PromotionInvoice.is_current.is_(True), PromotionInvoice.is_tombstone.is_(False)))
    for allocation, invoice in allocations:
        if invoice.invoice_status in (2, 3):
            # An effective store/month allocation can outlive the statement
            # version it references. Retain that identity for row-filter parity,
            # while current statements alone contribute statement/confirmed fees.
            values = totals.setdefault((allocation.statement_id, "PROMOTION"), {
                "publication_id": publication_id, "statement_id": allocation.statement_id,
                "fee_direction": "PROMOTION", "store_id": allocation.store_id,
                "month": allocation.statement_month, "amount_cent": 0, "confirmed_cent": 0,
                "issued_cent": 0, "settled_cent": 0,
            })
            values["issued_cent"] += int(allocation.allocated_amount_cent)
            if invoice.invoice_status == 3:
                values["settled_cent"] += int(allocation.allocated_amount_cent)
    for invoice in session.scalars(select(InvoiceRecord).where(
        InvoiceRecord.is_current.is_(True), InvoiceRecord.is_tombstone.is_(False),
        InvoiceRecord.fee_direction == 2, InvoiceRecord.invoice_status == 3)):
        values = totals.get((invoice.statement_id, "MANAGEMENT"))
        if values is not None:
            values["issued_cent"] += int(invoice.invoice_amount_cent)
            values["settled_cent"] += int(invoice.invoice_amount_cent)
    _write(session, statements, list(totals.values()))
    collection_rows = []
    position = 0
    for direction in ("PROMOTION", "MANAGEMENT"):
        query = source._finance_unbilled_projection_query(store, month=final_month,
            metric_scope="CUMULATIVE", store_id=None, q=None,
            invoice_status=None, scope_store_ids=None)
        for row in session.execute(query):
            item = {"invoice_id": None, "statement_id": None, "store_id": row.store_id,
                "store_name": row.store_name or row.store_id, "statement_month": row.month,
                "fee_direction": direction, "processing_status": "PENDING_STATEMENT",
                "status": "PENDING_INVOICE", "invoice_number": None, "invoice_date": None,
                "invoice_amount_cent": None, "confirmed_amount_cent": None, "registered_at": None,
                "settlement_batch_month": None, "rejection_reason": None,
                "effective_sap_code": display_context["effective_saps"].get(row.store_id),
                "statement_amount_cent": int(getattr(row, f"{direction.lower()}_net_fee_cent") or 0)}
            position += 1
            collection_rows.append({"publication_id": publication_id, "position": position,
                "fee_direction": direction, "store_id": row.store_id, "month": row.month,
                "statement_id": None, "status_code": None, "confirmed": False,
                "is_history": False, "is_projection": True,
                "search_text": "\n".join(str(value or "").lower() for value in (
                    row.store_id, row.store_name, *display_context["search_saps"].get(row.store_id, []))),
                "amount_cent": item["statement_amount_cent"], "item": _json_value(item)})
        # Cumulative excludes test history, while an explicit monthly lookup
        # retains its existing pre-formal statement contract.
        periods = [("CUMULATIVE", final_month), *[("MONTH", month) for month in months if month < FORMAL_START]]
        queries = [(False, source._promotion_finance_collection_query(month=month,
            metric_scope=metric_scope, store_id=None, q=None, invoice_status=None))
            for metric_scope, month in periods] if direction == "PROMOTION" else [
                (history, source._management_invoice_collection_query(month=month,
                    metric_scope=metric_scope, store_id=None, q=None, invoice_status=None,
                    include_history=history)) for history in (False, True) for metric_scope, month in periods]
        for history, query in queries:
            for row in session.execute(query):
                if direction == "PROMOTION":
                    invoice, allocation, statement = row
                else:
                    invoice, statement = row
                    allocation = None
                item = _formal_invoice_item(source, direction, invoice, allocation, statement,
                    confirmations, display_context)
                position += 1
                collection_rows.append({"publication_id": publication_id, "position": position,
                    "fee_direction": direction, "store_id": statement.store_id,
                    "month": statement.statement_month, "statement_id": statement.statement_id,
                    "status_code": invoice.invoice_status if invoice else None,
                    "confirmed": (statement.statement_id, 1 if direction == "PROMOTION" else 2) in confirmations,
                    "is_history": history, "is_projection": False,
                    "search_text": _search_text(display_context, statement, item),
                    "amount_cent": item["statement_amount_cent"], "item": _json_value(item)})
    _write(session, invoices, collection_rows)
    pending_rows, member_rows = [], []
    _, groups = source._promotion_invoice_carryforward_projection(session)
    for group in groups:
        position += 1
        pending_rows.append({"publication_id": publication_id, "position": position,
            "fee_direction": "PROMOTION", "store_id": group["store_id"],
            "as_of_month": "", "month": group["closing_month"],
            "amount_cent": int(group["invoiceable_amount_cent"])})
        member_rows.extend({"publication_id": publication_id, "position": position,
            "statement_id": statement_id} for statement_id in group["required_statement_ids"])
    for month in months:
        periods, _ = source._management_invoiceable_projection(session, through_month=month)
        for period in periods:
            position += 1
            pending_rows.append({"publication_id": publication_id, "position": position,
                "fee_direction": "MANAGEMENT", "store_id": period["store_id"],
                "as_of_month": month, "month": period["statement_month"],
                "amount_cent": int(period["invoiceable_amount_cent"])})
            member_rows.append({"publication_id": publication_id, "position": position,
                "statement_id": period["statement_id"]})
    _write(session, pending, pending_rows)
    _write(session, pending_members, member_rows)
    dimension_count, period_stats = _build_dimensions(session, publication_id, store, selectable_months, cutoff)
    return {"row_count": len(totals) + len(collection_rows) + len(pending_rows) + dimension_count,
            "invoice_rows": len(collection_rows), "statement_rows": len(totals),
            "pending_rows": len(pending_rows), "data_as_of": None, **period_stats}


def build(session: Session, publication_id: str, cutoff: datetime) -> dict:
    """Compatibility alias for settlement; modules have separate publication IDs."""
    return build_settlement(session, publication_id, cutoff)


def _scope(table, scope_store_ids):
    return [] if scope_store_ids is None else [table.c.store_id.in_(tuple(scope_store_ids))]


def _require_period(session, publication_id, month, *, cumulative=False):
    snapshot = session.scalar(select(dimensions.c.value).where(
        dimensions.c.publication_id == publication_id,
        dimensions.c.kind == "period_readiness", dimensions.c.key == "v1"))
    period_readiness.require(snapshot, month, cumulative=cumulative)


def read_filters(session: Session, publication_id: str, module: str = "settlement",
                 *, scope_store_ids: tuple[str, ...] | None = None) -> dict:
    """Read frozen selector dimensions, filtered by current store authorization."""
    values = session.scalar(select(dimensions.c.value).where(
        dimensions.c.publication_id == publication_id,
        dimensions.c.kind == "filters", dimensions.c.key == "all")) or {}
    conditions = [dimensions.c.publication_id == publication_id, dimensions.c.kind == "store"]
    if scope_store_ids is not None:
        conditions.append(dimensions.c.key.in_(scope_store_ids))
    stores = list(session.scalars(select(dimensions.c.value).where(*conditions)))
    readiness = session.scalar(select(dimensions.c.value).where(
        dimensions.c.publication_id == publication_id,
        dimensions.c.kind == "period_readiness", dimensions.c.key == "v1"))
    return {**values, "period_readiness": readiness,
        "stores": sorted(stores, key=lambda item: (item["store_name"], item["store_id"]))}


def _ranking_conditions(publication_id, filters):
    conditions = [ranking.c.publication_id == publication_id,
        ranking.c.product_scope == (filters.get("product_scope") or "all"),
        ranking.c.product_type == (filters.get("product_type") or "all")]
    # Scope applies even if a caller accidentally labels this GLOBAL.
    conditions += _scope(ranking, filters.get("scope_store_ids"))
    if (filters.get("q") or "").strip():
        conditions.append(func.lower(ranking.c.store_name).contains(filters["q"].strip().lower()))
    return conditions


def _has_source_generation(session, publication_id):
    value = session.scalar(select(dimensions.c.value).where(
        dimensions.c.publication_id == publication_id,
        dimensions.c.kind == "source", dimensions.c.key == "settlement")) or {}
    return value.get("has_generation", False)


def read_store_ranking(session: Session, publication_id: str, filters: dict[str, Any]) -> dict:
    """Filter, sum and sort frozen ranking rows within the caller's current scope."""
    period_type = filters.get("period_type", "MONTHLY")
    month = filters["period_key"]
    _require_period(session, publication_id, month,
        cumulative=period_type == "CUMULATIVE" or bool(filters.get("ranking_basis")))
    basis = filters.get("ranking_basis")
    conditions = _ranking_conditions(publication_id, filters)
    page, page_size = filters.get("page", 1), filters.get("page_size", 20)
    extra = {}
    metric_columns = {key: func.coalesce(func.sum(ranking.c[key]), 0).label(key)
                      for key in RANK_METRICS}
    if basis:
        extra = {"ranking_basis": basis}
        conditions += [ranking.c.period_key == month, month >= FORMAL_START]
        specs = {
            "sales_order_count_cumulative": (2, "sales_order_count"),
            "sales_amount_cumulative_cent": (2, "sales_amount_cent"),
            "verified_order_count_cumulative": (2, "verified_order_count"),
            "verified_amount_cumulative_cent": (2, "verified_amount_cent"),
            "promotion_month_fee_cent": (1, "promotion_net_fee_cent"),
            "promotion_cumulative_fee_cent": (2, "promotion_net_fee_cent"),
            "management_month_fee_cent": (1, "management_net_fee_cent"),
            "management_cumulative_fee_cent": (2, "management_net_fee_cent"),
            "net_settlement_reference_month_cent": (1, "net_settlement_reference_cent"),
            "net_settlement_reference_cumulative_cent": (2, "net_settlement_reference_cent"),
        }
        metric_columns = {key: func.coalesce(func.sum(case(
            (ranking.c.period_type == period, ranking.c[column]), else_=0)), 0).label(key)
            for key, (period, column) in specs.items()}
        aliases = {
            "sales_order_count": "sales_order_count_cumulative",
            "sales_amount_cent": "sales_amount_cumulative_cent",
            "verified_order_count": "verified_order_count_cumulative",
            "verified_amount_cent": "verified_amount_cumulative_cent",
            **{key: prefix + ("cumulative" if period_type == "CUMULATIVE" else "month") + suffix
               for key, prefix, suffix in (
                   ("promotion_net_fee_cent", "promotion_", "_fee_cent"),
                   ("management_net_fee_cent", "management_", "_fee_cent"),
                   ("net_settlement_reference_cent", "net_settlement_reference_", "_cent"))},
        }
        metric_columns.update({key: metric_columns[value].label(key) for key, value in aliases.items()})
        sort_key = {"SALES_AMOUNT_CUMULATIVE": "sales_amount_cumulative_cent",
            "VERIFIED_AMOUNT_CUMULATIVE": "verified_amount_cumulative_cent",
            "PROMOTION_FEE_MONTH": "promotion_month_fee_cent",
            "PROMOTION_FEE_CUMULATIVE": "promotion_cumulative_fee_cent"}[basis]
    else:
        conditions.append(ranking.c.period_type == (2 if period_type == "CUMULATIVE" else 1))
        read_month = month
        if period_type == "CUMULATIVE" and _has_source_generation(session, publication_id):
            read_month = session.scalar(select(func.max(ranking.c.period_key)).where(
                *conditions, ranking.c.period_key >= FORMAL_START, ranking.c.period_key <= month))
        conditions.append(ranking.c.period_key == read_month)
        sort_key = {"SALES_AMOUNT": "sales_amount_cent", "VERIFIED_AMOUNT": "verified_amount_cent",
            "PROMOTION_FEE": "promotion_net_fee_cent", "MANAGEMENT_FEE": "management_net_fee_cent",
            "NET_SETTLEMENT_REFERENCE": "net_settlement_reference_cent"}[filters.get("sort_by", "NET_SETTLEMENT_REFERENCE")]
    grouped = select(ranking.c.store_id, func.max(ranking.c.store_name).label("store_name"),
        *metric_columns.values()).where(*conditions).group_by(ranking.c.store_id).subquery()
    totals = session.execute(select(func.count().label("total"), *(
        func.coalesce(func.sum(grouped.c[key]), 0).label(key) for key in metric_columns
    )).select_from(grouped)).mappings().one()
    order = grouped.c[sort_key].asc() if filters.get("sort_order") == "ASC" else grouped.c[sort_key].desc()
    rows = session.execute(select(grouped).order_by(order, grouped.c.store_id).offset(
        (page - 1) * page_size).limit(page_size)).mappings()
    return {"period_type": period_type, "period_key": month, **extra,
        "product_scope": filters.get("product_scope") or "all",
        "product_type": filters.get("product_type") or "all",
        "formal_period_start_month": FORMAL_START,
        "scope_mode": filters.get("scope_mode", "AUTHORIZED"),
        "totals": {key: int(totals[key]) for key in metric_columns},
        "list": [{"rank": (page - 1) * page_size + index + 1,
                  "store_id": row["store_id"], "store_name": row["store_name"],
                  **{key: int(row[key]) for key in metric_columns}}
                 for index, row in enumerate(rows)],
        "total": totals["total"], "page": page, "page_size": page_size}


def read_monthly_settlement(session: Session, publication_id: str, filters: dict[str, Any]) -> dict:
    """Return frozen operating amounts; routes populate the live statement head."""
    store_id, month = filters["store_id"], filters["month"]
    _require_period(session, publication_id, month, cumulative=True)
    scope = filters.get("scope_store_ids")
    allowed = scope is None or store_id in scope
    row = session.execute(select(monthly).where(monthly.c.publication_id == publication_id,
        monthly.c.store_id == store_id, monthly.c.month == month,
        monthly.c.product_scope == (filters.get("product_scope") or "all"),
        monthly.c.product_type == (filters.get("product_type") or "all"), allowed)).mappings().first()
    store = session.scalar(select(dimensions.c.value).where(
        dimensions.c.publication_id == publication_id, dimensions.c.kind == "store",
        dimensions.c.key == store_id, allowed)) or {"store_id": store_id, "store_name": store_id}
    cumulative = read_store_ranking(session, publication_id, {**filters,
        "period_type": "CUMULATIVE", "period_key": month, "scope_store_ids": (store_id,) if allowed else ()})
    has_generation = _has_source_generation(session, publication_id)
    return {"store": store, "month": month,
        "product_scope": filters.get("product_scope") or "all",
        "product_type": filters.get("product_type") or "all",
        "is_formal_period": month >= FORMAL_START, "statement": None,
        "publication_statement": row["statement"] if row else None,
        "metrics": {key: int(row[key]) if row else 0 for key in MONTH_METRICS},
        "computed_cumulative": {key: cumulative["totals"][key] if has_generation else 0
            for key in ("promotion_net_fee_cent", "management_net_fee_cent")},
        "lines": row["lines"] if row else []}


def _period(column, month, metric_scope):
    return and_(column >= FORMAL_START, column <= month) if metric_scope == "CUMULATIVE" else column == month


def _invoice_conditions(publication_id, *, month, fee_direction, metric_scope="MONTH",
                        store_id=None, q=None, invoice_status=None,
                        include_history=False, scope_store_ids=None):
    conditions = [invoices.c.publication_id == publication_id,
        invoices.c.fee_direction == fee_direction, _period(invoices.c.month, month, metric_scope),
        or_(invoices.c.is_projection.is_(True), invoices.c.is_history.is_(
            include_history if fee_direction == "MANAGEMENT" else False)),
        *_scope(invoices, scope_store_ids)]
    if store_id is not None:
        conditions.append(invoices.c.store_id == store_id)
    if (q or "").strip():
        conditions.append(invoices.c.search_text.contains(q.strip().lower()))
    if invoice_status is not None:
        conditions.append(invoices.c.is_projection.is_(False))
        if fee_direction == "PROMOTION":
            conditions.append(or_(invoices.c.status_code.is_(None), invoices.c.status_code.in_((1, 4)))
                if invoice_status == 1 else invoices.c.status_code == invoice_status)
        else:
            conditions.append(and_(invoices.c.status_code.is_(None), invoices.c.confirmed.is_(True))
                if invoice_status == 1 else invoices.c.status_code.is_not(None))
    return conditions


def read_finance_invoices(session: Session, publication_id: str, *, page: int = 1,
                          page_size: int = 20, **filters: Any) -> dict:
    """Return a page from precisely the same frozen row set used by export."""
    _require_period(session, publication_id, filters["month"],
        cumulative=filters.get("metric_scope", "MONTH") == "CUMULATIVE")
    conditions = _invoice_conditions(publication_id, **filters)
    total = session.scalar(select(func.count()).select_from(invoices).where(*conditions)) or 0
    items = list(session.scalars(select(invoices.c.item).where(*conditions).order_by(
        invoices.c.position).offset((page - 1) * page_size).limit(page_size)))
    return {"list": items, "total": total, "page": page, "page_size": page_size}


def export_finance_invoices(session: Session, publication_id: str, *,
                            limit: int | None = None, **filters: Any) -> list[dict]:
    """Materialize the list's frozen rows; callers retain export size/audit policy."""
    _require_period(session, publication_id, filters["month"],
        cumulative=filters.get("metric_scope", "MONTH") == "CUMULATIVE")
    query = select(invoices.c.item).where(*_invoice_conditions(publication_id, **filters)).order_by(
        invoices.c.position)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


def read_finance_summary(session: Session, publication_id: str, *, month: str,
                         fee_direction: str, metric_scope: str,
                         store_id: str | None = None, q: str | None = None,
                         invoice_status: int | None = None,
                         scope_store_ids: tuple[str, ...] | None = None) -> dict:
    """Sum frozen statement facts and pre-evaluated balances after row filtering."""
    _require_period(session, publication_id, month, cumulative=metric_scope == "CUMULATIVE")
    row_filters = bool((q or "").strip()) or invoice_status is not None or scope_store_ids is not None
    filters = dict(month=month, fee_direction=fee_direction, metric_scope=metric_scope,
        store_id=store_id, q=q, invoice_status=invoice_status, scope_store_ids=scope_store_ids)
    matching = select(invoices.c.statement_id).where(*_invoice_conditions(publication_id, **filters),
        invoices.c.statement_id.is_not(None)).distinct()
    conditions = [statements.c.publication_id == publication_id,
        statements.c.fee_direction == fee_direction, *_scope(statements, scope_store_ids)]
    if store_id is not None:
        conditions.append(statements.c.store_id == store_id)
    if row_filters:
        conditions.append(statements.c.statement_id.in_(matching))
    amounts = session.execute(select(
        func.coalesce(func.sum(case((_period(statements.c.month, month, metric_scope),
            statements.c.amount_cent), else_=0)), 0).label("statement_total_cent"),
        func.coalesce(func.sum(case((statements.c.month == month,
            statements.c.confirmed_cent), else_=0)), 0).label("confirmed_amount_cent"),
        func.coalesce(func.sum(case((_period(statements.c.month, month, metric_scope),
            statements.c.issued_cent), else_=0)), 0).label("issued_amount_cent"),
        func.coalesce(func.sum(case((_period(statements.c.month, month, metric_scope),
            statements.c.settled_cent), else_=0)), 0).label("settled_or_deducted_amount_cent"),
    ).where(*conditions)).mappings().one()
    metrics = {key: int(value) for key, value in amounts.items()}
    metrics["statement_total_cent"] += int(session.scalar(select(func.coalesce(func.sum(
        invoices.c.amount_cent), 0)).where(*_invoice_conditions(publication_id, **filters),
        invoices.c.is_projection.is_(True))) or 0)
    pending_conditions = [pending.c.publication_id == publication_id,
        pending.c.fee_direction == fee_direction, *_scope(pending, scope_store_ids)]
    if store_id is not None:
        pending_conditions.append(pending.c.store_id == store_id)
    if fee_direction == "PROMOTION":
        pending_conditions.append(_period(pending.c.month, month, metric_scope))
    else:
        available_month = session.scalar(select(func.max(pending.c.as_of_month)).where(
            pending.c.publication_id == publication_id,
            pending.c.fee_direction == fee_direction, pending.c.as_of_month <= month))
        pending_conditions.extend([pending.c.as_of_month == available_month,
            _period(pending.c.month, month, metric_scope)])
    if row_filters:
        pending_conditions.append(select(pending_members.c.position).where(
            pending_members.c.publication_id == publication_id,
            pending_members.c.position == pending.c.position,
            pending_members.c.statement_id.in_(matching)).exists())
    pending_total = int(session.scalar(select(func.coalesce(func.sum(pending.c.amount_cent), 0)).where(
        *pending_conditions)) or 0)
    metrics["pending_invoice_amount_cent"] = pending_total if fee_direction == "PROMOTION" else max(pending_total, 0)
    return {"month": month, "store_id": store_id, "fee_direction": fee_direction,
            "metric_scope": metric_scope, "metrics": metrics}
