"""Settlement/finance parity and immutable publication reader contracts."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, event, func, insert, select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from dy_api.dashboard_publications import finance as publication
from dy_api.dashboard_publications.schema import metadata, runs
from dy_api.models import (
    AggStoreMonthlySettlement, AggStoreRanking, DimSkuProductRule, DimStore, InvoiceRecord,
    PromotionInvoice, PromotionInvoiceAllocation, SettlementProjectionActive,
    SettlementProjectionGeneration, SettlementProjectionPartitionManifest,
    SettlementMonthlyOverlay, SettlementRankingOverlay, SettlementStatement,
    SettlementStatementConfirmation, SettlementStatementLine, SettlementFeeResult,
    SettlementFeeResultCurrent, SettlementFeeAdjustment, StoreFinanceProfile,
    SettlementStatementEntry,
)
from dy_api.routes import dashboard as source
from dy_api.routes._data import DashboardDataStore
from publication_fixture_helpers import ready_periods_fixture


NOW = datetime(2026, 10, 19, 4, tzinfo=UTC)


@pytest.fixture(autouse=True)
def complete_projection_periods(monkeypatch):
    """Domain parity fixtures explicitly assume complete daily collection."""
    monkeypatch.setattr(publication.period_readiness, "capture", ready_periods_fixture)


def _run(session, publication_id, module, cutoff=NOW):
    metadata.create_all(session.get_bind())
    session.execute(insert(runs).values(id=publication_id, module=module,
        status="building", cutoff=cutoff, created_at=cutoff, stats_json={}))


def _fixture_line_entries(session, statement_id, store_id, month, line_id, direction, amounts, *, scope="all", product_type="all", add_line=True):
    """Protected fixture headers must have complete immutable line/source evidence."""
    original = sum(amount for amount in amounts if amount >= 0)
    adjustment = sum(amount for amount in amounts if amount < 0)
    original_count = sum(amount >= 0 for amount in amounts)
    adjustment_count = len(amounts) - original_count
    if add_line:
        session.add(SettlementStatementLine(
            statement_line_id=line_id, statement_id=statement_id, fee_direction=direction,
            product_scope=scope, product_type=product_type,
            original_entry_count=original_count, adjustment_entry_count=adjustment_count,
            original_base_cent=1000 * original_count,
            adjustment_base_cent=-1000 * adjustment_count,
            net_base_cent=1000 * (original_count - adjustment_count),
            original_fee_cent=original, adjustment_fee_cent=adjustment, net_fee_cent=sum(amounts),
        ))
    for index, amount in enumerate(amounts):
        identity = f"fixture-{line_id}-{index}"
        rate = str((index + 1) / 10)
        session.add(SettlementFeeResult(
            fee_result_id=identity, coupon_id=identity, order_id=f"order-{identity}", fee_direction=direction,
            original_business_month=month, rule_match_date=date.fromisoformat(month + "-01"),
            sale_store_id=store_id, verify_store_id=store_id, sku_id="frozen-sku",
            product_scope=scope, product_type=product_type, sale_channel_normalized="LIVE",
            source_amount_cent=1000, fee_base_cent=1000, fee_amount_cent=max(amount, 0),
            fee_rate=rate, rule_version=f"rule-{index}", scope_rule_version="scope-1",
            calculation_run_id=identity, calculated_at=NOW,
        ))
        if amount < 0:
            session.add(SettlementFeeAdjustment(
                adjustment_id=identity, original_fee_result_id=identity, coupon_id=identity,
                order_id=f"order-{identity}", fee_direction=direction,
                original_business_month=month, adjustment_posting_month=month,
                adjustment_type=1, adjustment_base_cent=-1000, adjustment_fee_cent=amount,
                rule_version=f"rule-{index}", adjustment_reason="Synthetic fixture refund",
                occurred_at=NOW, created_by="synthetic",
            ))
        session.add(SettlementStatementEntry(
            statement_entry_id=f"entry-{identity}", statement_id=statement_id, statement_line_id=line_id,
            source_type=1 if amount >= 0 else 2, source_record_id=identity,
            original_fee_result_id=identity, coupon_id=identity, order_id=f"order-{identity}",
            fee_direction=direction, original_business_month=month, statement_posting_month=month,
            product_scope=scope, product_type=product_type, base_amount_cent=1000 if amount >= 0 else -1000,
            fee_amount_cent=amount, rule_version=f"rule-{index}", received_amount_cent_snapshot=1000,
            fee_rate_snapshot=rate,
        ))


def _statement(session, store_id, month, amount, *, with_sources=True):
    statement_id = f"statement-{store_id}-{month}"
    session.add(SettlementStatement(statement_id=statement_id, store_id=store_id,
        statement_month=month, version_no=1, is_current=True, statement_status=4,
        promotion_original_fee_cent=max(amount, 0), promotion_adjustment_fee_cent=min(amount, 0),
        promotion_net_fee_cent=amount, management_original_fee_cent=max(amount, 0),
        management_adjustment_fee_cent=min(amount, 0), management_net_fee_cent=amount,
        store_name_snapshot=f"Historical {store_id}", sap_code_snapshot=f"HIST-{store_id}"))
    for direction in (1, 2):
        session.add(SettlementStatementConfirmation(confirmation_id=f"c-{statement_id}-{direction}",
            statement_id=statement_id, fee_direction=direction, confirmation_status=1,
            confirmed_amount_cent=amount, confirmed_by=store_id, confirmed_at=NOW))
        if with_sources:
            _fixture_line_entries(session, statement_id, store_id, month, f"line-{statement_id}-{direction}", direction, (amount,))
    return statement_id


def _seed_finance(session):
    for store_id in ("allowed", "other", "projected"):
        session.add(DimStore(store_id=store_id, store_name=f"Current {store_id}", is_active=True))
    session.add(StoreFinanceProfile(profile_id="profile-allowed", store_id="allowed",
        profile_type=1, version_no=1, sap_code="SAP-allowed", is_current=True,
        is_tombstone=False, store_name_snapshot="Current allowed", created_at=NOW))
    _statement(session, "allowed", "2026-07", 99999)
    _statement(session, "allowed", "2026-08", -101)
    _statement(session, "allowed", "2026-09", 1001)
    october = _statement(session, "allowed", "2026-10", 1203)
    _statement(session, "other", "2026-09", 5011)
    session.flush()
    session.add(PromotionInvoice(invoice_id="promotion-oct", physical_invoice_id="physical-oct",
        store_id="allowed", version_no=1, version_kind=1, is_current=True,
        invoice_number="12345678901234567890", invoice_date=date(2026, 10, 10),
        invoice_amount_cent=1203, buyer_name="Test buyer", tax_rate_percent=6,
        invoice_status=3, registered_by="test", registered_at=NOW))
    session.add(PromotionInvoiceAllocation(allocation_id="allocation-oct", invoice_id="promotion-oct",
        store_id="allowed", statement_id=october, statement_month="2026-10",
        settlement_batch_month="2026-10", allocated_amount_cent=1203, is_current=True))
    for current, version in ((False, 1), (True, 2)):
        session.add(InvoiceRecord(invoice_id=f"management-oct-{version}", store_id="allowed",
            statement_id=october, statement_month="2026-10", fee_direction=2,
            version_no=version, is_current=current, is_tombstone=False,
            invoice_number=f"2234567890123456789{version}", invoice_date=date(2026, 10, 10),
            invoice_amount_cent=1203, invoice_status=3, source_type=2,
            registered_by="test", registered_at=NOW))
    session.add(SettlementProjectionGeneration(generation_id="published", state="published",
        input_fingerprint="finance-published"))
    session.flush()
    session.add(SettlementProjectionActive(projection_name="settlement", generation_id="published"))
    session.add(SettlementProjectionPartitionManifest(generation_id="published", artifact="monthly",
        partition_key="2026-09", source_kind="overlay", data_generation_id="published"))
    session.add(SettlementMonthlyOverlay(generation_id="published", partition_key="2026-09",
        month="2026-09", store_id="projected", product_scope="all", product_type="all",
        promotion_net_fee_cent=211, management_net_fee_cent=107))
    session.commit()


def _legacy_summary(session, **filters):
    statement_ids = source._finance_summary_filtered_statement_ids(session, **filters)
    metrics = source._finance_summary_metrics(session, month=filters["month"],
        fee_direction=filters["fee_direction"], metric_scope=filters["metric_scope"],
        store_id=filters.get("store_id"), statement_ids=statement_ids)
    query = source._finance_unbilled_projection_query(DashboardDataStore(session),
        **{key: value for key, value in filters.items() if key != "fee_direction"})
    rows = session.execute(query).all()
    metrics["statement_total_cent"] += sum(int(getattr(row,
        f"{filters['fee_direction'].lower()}_net_fee_cent") or 0) for row in rows)
    return metrics


def _legacy_invoices(session, *, include_history=False, **filters):
    rows = session.execute(source._finance_unbilled_projection_query(DashboardDataStore(session),
        **{key: value for key, value in filters.items() if key != "fee_direction"})).all()
    items = [source._finance_unbilled_projection_item(session, row, filters["fee_direction"])
             for row in rows]
    if filters["fee_direction"] == "PROMOTION":
        query = source._promotion_finance_collection_query(
            **{key: value for key, value in filters.items() if key != "fee_direction"})
        items.extend(source._admin_promotion_invoice_item(session, *row) for row in session.execute(query))
    else:
        query = source._management_invoice_collection_query(include_history=include_history,
            **{key: value for key, value in filters.items() if key != "fee_direction"})
        items.extend(source._admin_management_invoice_item(session, *row) for row in session.execute(query))
    return publication._json_value(items)


@pytest.mark.parametrize("invoice_status,allocation_current,invoice_current,tombstone", [
    (2, True, True, False), (3, True, True, False),
    (3, False, True, False), (3, True, False, False),
    (3, True, True, True), (4, True, True, False),
])
def test_finance_retired_statement_allocation_keeps_period_totals_and_filter_parity(
    db_session, invoice_status, allocation_current, invoice_current, tombstone,
):
    _seed_finance(db_session)
    old_id = "statement-allowed-2026-10"
    db_session.execute(update(SettlementStatement).where(
        SettlementStatement.statement_id == old_id).values(is_current=False))
    db_session.add(SettlementStatement(statement_id="statement-allowed-oct-v2", store_id="allowed",
        statement_month="2026-10", version_no=2, is_current=True, statement_status=4,
        supersedes_statement_id=old_id, promotion_original_fee_cent=1203,
        promotion_net_fee_cent=1203, store_name_snapshot="Historical allowed",
        sap_code_snapshot="HIST-allowed"))
    db_session.add(SettlementStatementConfirmation(confirmation_id="oct-v2-confirmation",
        statement_id="statement-allowed-oct-v2", fee_direction=1, confirmation_status=1,
        confirmed_amount_cent=1203, confirmed_by="allowed", confirmed_at=NOW))
    db_session.execute(update(PromotionInvoice).values(invoice_status=invoice_status,
        is_current=invoice_current, is_tombstone=tombstone))
    db_session.execute(update(PromotionInvoiceAllocation).values(is_current=allocation_current))
    db_session.commit()
    _run(db_session, "finance-retired", "finance")
    publication.build_finance(db_session, "finance-retired", NOW)
    filters = dict(month="2026-10", metric_scope="MONTH", fee_direction="PROMOTION",
        store_id="allowed", q=None, invoice_status=None, scope_store_ids=None)
    issued = 1203 if allocation_current and invoice_current and not tombstone and invoice_status in (2, 3) else 0
    result = publication.read_finance_summary(db_session, "finance-retired", **filters)
    assert result["metrics"]["statement_total_cent"] == 1203
    assert result["metrics"]["confirmed_amount_cent"] == 1203
    assert result["metrics"]["issued_amount_cent"] == issued
    assert result["metrics"]["settled_or_deducted_amount_cent"] == (issued if invoice_status == 3 else 0)
    snapshots = []
    for metric_scope in ("MONTH", "CUMULATIVE"):
        for extra in ({}, {"q": "SAP-allowed"}, {"q": "12345678901234567890"},
                {"invoice_status": 1}, {"invoice_status": 2}, {"invoice_status": 3},
                {"scope_store_ids": ("allowed",)}, {"scope_store_ids": ()},
                {"scope_store_ids": ("other",)}):
            selected = filters | {"metric_scope": metric_scope} | extra
            metrics = publication.read_finance_summary(db_session, "finance-retired", **selected)
            assert metrics["metrics"] == _legacy_summary(db_session, **selected), selected
            exported = publication.export_finance_invoices(db_session, "finance-retired", **selected)
            assert exported == _legacy_invoices(db_session, **selected), selected
            assert publication.read_finance_invoices(db_session, "finance-retired", **selected)["list"] == exported
            snapshots.append((selected, metrics, exported))
    db_session.execute(update(PromotionInvoiceAllocation).values(is_current=False))
    db_session.execute(update(PromotionInvoice).values(invoice_status=4))
    db_session.commit()
    for selected, metrics, exported in snapshots:
        assert publication.read_finance_summary(db_session, "finance-retired", **selected) == metrics
        assert publication.export_finance_invoices(db_session, "finance-retired", **selected) == exported


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_finance_parity_scope_filters_export_and_frozen_source(db_session, direction, monkeypatch):
    _seed_finance(db_session)
    _run(db_session, "finance-v1", "finance")
    stats = publication.build_finance(db_session, "finance-v1", NOW)
    assert stats["invoice_rows"] > 0
    assert stats["data_as_of"] is None
    cases = []
    for month, metric_scope in (("2026-07", "MONTH"), ("2026-09", "MONTH"), ("2026-10", "MONTH"),
                                ("2026-10", "CUMULATIVE")):
        for extra in ({}, {"scope_store_ids": ("allowed",)}, {"scope_store_ids": ()},
                      {"q": "SAP-allowed"}, {"q": "Historical"}, {"q": "12345678901234567890"},
                      {"invoice_status": 1}, {"invoice_status": 3}, {"store_id": "other"}):
            filters = dict(month=month, metric_scope=metric_scope, fee_direction=direction,
                           store_id=None, q=None, invoice_status=None, scope_store_ids=None)
            filters.update(extra)
            expected_metrics = _legacy_summary(db_session, **filters)
            expected_items = _legacy_invoices(db_session, **filters)
            actual = publication.read_finance_summary(db_session, "finance-v1", **filters)
            assert actual["metrics"] == expected_metrics, filters
            assert publication.export_finance_invoices(db_session, "finance-v1", **filters) == expected_items, filters
            first = publication.read_finance_invoices(db_session, "finance-v1", page_size=1, **filters)
            pages = [publication.read_finance_invoices(db_session, "finance-v1", page=page,
                page_size=1, **filters)["list"] for page in range(1, first["total"] + 1)]
            assert [row for page in pages for row in page] == expected_items
            cases.append((filters, actual, expected_items))
    if direction == "MANAGEMENT":
        filters = dict(month="2026-10", metric_scope="MONTH", fee_direction=direction,
            store_id=None, q=None, invoice_status=None, scope_store_ids=None)
        history = publication.export_finance_invoices(db_session, "finance-v1", include_history=True, **filters)
        assert len(history) == 2
        assert history == _legacy_invoices(db_session, include_history=True, **filters)
    db_session.commit()
    # A subsequent invoice correction, current SAP/name edit and projection edit
    # cannot change the old published operating figures or its export.
    db_session.execute(update(DimStore).values(store_name="Changed"))
    db_session.execute(update(SettlementMonthlyOverlay).values(promotion_net_fee_cent=9999,
        management_net_fee_cent=8888))
    db_session.execute(update(PromotionInvoice).values(invoice_status=4))
    db_session.execute(update(StoreFinanceProfile).values(sap_code="CHANGED"))
    db_session.commit()
    monkeypatch.setattr(source, "_finance_summary_metrics", lambda *args, **kwargs: pytest.fail("source read"))
    monkeypatch.setattr(source, "_management_invoiceable_projection", lambda *args, **kwargs: pytest.fail("source read"))
    statements_seen = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements_seen.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", observe)
    try:
        for filters, expected_summary, expected_items in cases:
            assert publication.read_finance_summary(db_session, "finance-v1", **filters) == expected_summary
            assert publication.export_finance_invoices(db_session, "finance-v1", **filters) == expected_items
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", observe)
    assert statements_seen
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements_seen)
    assert all("FROM settlement_" not in statement and "FROM promotion_" not in statement
               and "FROM invoice_record" not in statement for statement in statements_seen)


def _seed_settlement(session, *, legacy_root=False):
    session.add_all([DimStore(store_id="allowed", store_name="Allowed"),
                     DimStore(store_id="other", store_name="Other")])
    session.add(SettlementProjectionGeneration(generation_id="published", state="published",
        generation_kind="legacy_root" if legacy_root else "lineage",
        input_fingerprint="settlement-published"))
    session.flush()
    session.add(SettlementProjectionActive(projection_name="settlement", generation_id="published"))
    if not legacy_root:
        for artifact, partition in (("monthly", "2026-08"), ("ranking", "monthly:2026-08"),
                                    ("ranking", "cumulative:2026-08")):
            session.add(SettlementProjectionPartitionManifest(generation_id="published", artifact=artifact,
                partition_key=partition, source_kind="overlay", data_generation_id="published"))
    for store_id, factor in (("allowed", 1), ("other", 3)):
        for product_scope, product_type in (("all", "all"), ("all", "tyre"), ("jingcheng", "tyre")):
            values = dict(month="2026-08", store_id=store_id, product_scope=product_scope,
                product_type=product_type, sales_order_count=2 * factor,
                sales_amount_cent=9007199254740993 * factor, verified_order_count=factor,
                verified_amount_cent=111 * factor, promotion_net_fee_cent=101 * factor,
                management_net_fee_cent=33 * factor)
            if legacy_root:
                session.add(AggStoreMonthlySettlement(**values))
            else:
                session.add(SettlementMonthlyOverlay(generation_id="published", partition_key="2026-08", **values))
            for period_type, prefix in ((1, "monthly"), (2, "cumulative")):
                rank_values = {**values, "period_type": period_type, "period_key": "2026-08",
                               "store_name": store_id, "net_settlement_reference_cent": 68 * factor}
                if legacy_root:
                    session.add(AggStoreRanking(projection_run_id="root", **rank_values))
                else:
                    session.add(SettlementRankingOverlay(generation_id="published",
                        partition_key=f"{prefix}:2026-08", **rank_values))
    session.commit()


@pytest.mark.parametrize("legacy_root", [False, True])
def test_settlement_parity_huge_integer_cent_scope_and_no_legacy_drift(db_session, legacy_root):
    _seed_settlement(db_session, legacy_root=legacy_root)
    _run(db_session, "settlement-v1", "settlement")
    publication.build_settlement(db_session, "settlement-v1", NOW)
    old = DashboardDataStore(db_session)
    cases = []
    for period_type, month in (("MONTHLY", "2026-08"), ("CUMULATIVE", "2026-08"),
                               ("CUMULATIVE", "2026-09"), ("CUMULATIVE", "2026-07")):
        for scope in (None, (), ("allowed",)):
            for basis in (None, "PROMOTION_FEE_MONTH", "SALES_AMOUNT_CUMULATIVE"):
                filters = dict(period_type=period_type, period_key=month, ranking_basis=basis,
                    scope_mode="AUTHORIZED", scope_store_ids=scope, product_scope="all",
                    product_type="all", sort_order="DESC", page=1, page_size=20)
                expected = old.store_ranking_report(filters)
                expected["period_availability"] = publication.period_readiness.availability(
                    ready_periods_fixture(db_session, NOW), month)
                actual = publication.read_store_ranking(db_session, "settlement-v1", filters)
                assert actual == expected, filters
                cases.append((filters, expected))
    for product_scope, product_type in (("all", "all"), ("jingcheng", "tyre")):
        filters = dict(store_id="allowed", month="2026-08", product_scope=product_scope,
                       product_type=product_type)
        # The legacy concrete-product line preview corrupts its own bind names
        # (":product_scope" -> ":r.product_scope"). These fixture product slots
        # have identical amounts and no lines, so use the working all/all
        # response as the baseline and assert concrete selection separately.
        expected = old.monthly_settlement_report({**filters, "product_scope": "all", "product_type": "all"})
        expected.update(product_scope="all", product_type=product_type)
        expected["period_availability"] = publication.period_readiness.availability(
            ready_periods_fixture(db_session, NOW), filters["month"])
        actual = publication.read_monthly_settlement(db_session, "settlement-v1", filters)
        assert actual.pop("publication_statement") == expected["statement"]
        assert actual == expected
    empty = publication.read_monthly_settlement(db_session, "settlement-v1", dict(
        store_id="allowed", month="2026-08", scope_store_ids=()))
    assert not any(empty["metrics"].values())
    assert empty["computed_cumulative"]["promotion_net_fee_cent"] == 0
    assert publication.read_filters(db_session, "settlement-v1", scope_store_ids=())["stores"] == []
    assert [row["store_id"] for row in publication.read_filters(db_session, "settlement-v1",
        scope_store_ids=("allowed",))["stores"]] == ["allowed"]
    global_label = publication.read_store_ranking(db_session, "settlement-v1", dict(
        period_type="MONTHLY", period_key="2026-08", scope_mode="GLOBAL",
        scope_store_ids=("allowed",)))
    assert [row["store_id"] for row in global_label["list"]] == ["allowed"]
    # The source generation may be a mutable legacy-root. Only the copied
    # projection, never a generation reference alone, provides immutability.
    model = AggStoreRanking if legacy_root else SettlementRankingOverlay
    db_session.execute(update(model).values(sales_amount_cent=0))
    db_session.commit()
    for filters, expected in cases:
        assert publication.read_store_ranking(db_session, "settlement-v1", filters) == expected


def test_failed_build_rolls_back_owned_projection_rows(db_session, monkeypatch):
    _seed_finance(db_session)
    _run(db_session, "finance-old", "finance")
    publication.build_finance(db_session, "finance-old", NOW)
    db_session.commit()
    filters = dict(month="2026-09", fee_direction="PROMOTION", metric_scope="MONTH")
    before = publication.read_finance_summary(db_session, "finance-old", **filters)
    _run(db_session, "finance-failed", "finance")
    monkeypatch.setattr(source, "_management_invoiceable_projection",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("build failed")))
    with pytest.raises(RuntimeError, match="build failed"):
        publication.build_finance(db_session, "finance-failed", NOW)
    db_session.rollback()
    assert publication.read_finance_summary(db_session, "finance-old", **filters) == before
    assert db_session.scalar(select(func.count()).select_from(publication.invoices).where(
        publication.invoices.c.publication_id == "finance-failed")) == 0


@pytest.mark.parametrize("locked", [False, True])
def test_monthly_frozen_lines_match_multicoupon_refund_and_locked_facts(db_session, locked):
    _seed_settlement(db_session)
    for index, amount in enumerate((100, 200)):
        fee_id = f"fee-{index}"
        db_session.add(SettlementFeeResult(fee_result_id=fee_id, coupon_id=f"coupon-{index}",
            order_id="multi-coupon-order", fee_direction=1, original_business_month="2026-08",
            rule_match_date=date(2026, 8, 10), sale_store_id="allowed", verify_store_id="other",
            sku_id="sku", product_scope="jingcheng", product_type="tyre",
            sale_channel_normalized="LIVE", source_amount_cent=1000, fee_base_cent=1000,
            fee_rate=str(amount / 1000), fee_amount_cent=amount, rule_version=f"rule-{index}",
            scope_rule_version="scope-1", calculation_run_id="test", calculated_at=NOW))
        db_session.add(SettlementFeeResultCurrent(coupon_id=f"coupon-{index}",
            fee_direction=1, fee_result_id=fee_id))
    db_session.add(SettlementFeeAdjustment(adjustment_id="cancel-september", original_fee_result_id="fee-0",
        coupon_id="coupon-0", order_id="multi-coupon-order", fee_direction=1,
        original_business_month="2026-08", adjustment_posting_month="2026-09", adjustment_type=3,
        adjustment_base_cent=-1000, adjustment_fee_cent=-100, rule_version="cancel-rule",
        adjustment_reason="verify cancelled", occurred_at=NOW, created_by="test"))
    if locked:
        _statement(db_session, "allowed", "2026-08", 177, with_sources=False)
        db_session.add(SettlementStatementLine(statement_line_id="locked-line",
            statement_id="statement-allowed-2026-08", fee_direction=1,
            product_scope="jingcheng", product_type="tyre", original_entry_count=2,
            original_base_cent=2000, net_base_cent=2000, original_fee_cent=177, net_fee_cent=177))
        _fixture_line_entries(db_session, "statement-allowed-2026-08", "allowed", "2026-08", "locked-line", 1, (77, 100), scope="jingcheng", product_type="tyre", add_line=False)
        _fixture_line_entries(db_session, "statement-allowed-2026-08", "allowed", "2026-08", "locked-management-line", 2, (177,))
    db_session.commit()
    _run(db_session, "settlement-lines", "settlement")
    publication.build_settlement(db_session, "settlement-lines", NOW)
    for month in ("2026-08", "2026-09"):
        filters = dict(store_id="allowed", month=month, product_scope="all", product_type="all")
        expected = DashboardDataStore(db_session).monthly_settlement_report(filters)
        expected["period_availability"] = publication.period_readiness.availability(
            ready_periods_fixture(db_session, NOW), month)
        actual = publication.read_monthly_settlement(db_session, "settlement-lines", filters)
        assert publication._json_value(actual.pop("publication_statement")) == publication._json_value(expected["statement"])
        expected["statement"] = None
        assert actual == publication._json_value(expected)
    specific = publication.read_monthly_settlement(db_session, "settlement-lines", dict(
        store_id="allowed", month="2026-08", product_scope="jingcheng", product_type="tyre"))
    assert len(specific["lines"]) == 1
    assert specific["lines"][0]["net_fee_cent"] == (177 if locked else 300)
    if locked:
        assert specific["metrics"]["promotion_net_fee_cent"] == 177


def test_catalog_classification_change_keeps_locked_financial_types_and_amounts(db_session):
    _seed_settlement(db_session)
    db_session.add(DimSkuProductRule(sku_id="reclassified-sku", product_scope="精诚养车",
        product_type="精诚养车"))
    statement_id = _statement(db_session, "allowed", "2026-08", 177, with_sources=False)
    db_session.add(SettlementStatementLine(statement_line_id="historical-type-line",
        statement_id=statement_id, fee_direction=1, product_scope="jingcheng", product_type="tyre",
        original_entry_count=2, original_base_cent=2000, net_base_cent=2000,
        original_fee_cent=177, net_fee_cent=177))
    _fixture_line_entries(db_session, statement_id, "allowed", "2026-08", "historical-type-line", 1, (77, 100), scope="jingcheng", product_type="tyre", add_line=False)
    _fixture_line_entries(db_session, statement_id, "allowed", "2026-08", "historical-management-line", 2, (177,))
    db_session.commit()
    _run(db_session, "catalog-changed", "settlement")
    publication.build_settlement(db_session, "catalog-changed", NOW)
    db_session.commit()
    selected = publication.read_monthly_settlement(db_session, "catalog-changed", {
        "store_id": "allowed", "month": "2026-08", "product_scope": "unrelated-old-scope",
        "product_type": "tyre"})
    assert selected["product_scope"] == "all"
    assert selected["metrics"]["promotion_net_fee_cent"] == 177
    assert [(line["statement_line_id"], line["product_type"], line["product_scope"])
        for line in selected["lines"]] == [("historical-type-line", "tyre", "jingcheng")]
    assert set(publication.read_filters(db_session, "catalog-changed")["product_types"]) == {
        "all", "tyre", "精诚养车"}
    frozen_line = db_session.scalar(select(SettlementStatementLine).where(
        SettlementStatementLine.statement_line_id == "historical-type-line"))
    assert (frozen_line.product_type, frozen_line.product_scope, frozen_line.net_fee_cent) == ("tyre", "jingcheng", 177)
    db_session.execute(update(DimSkuProductRule).values(product_type="下一版分类"))
    db_session.commit()
    assert "下一版分类" not in publication.read_filters(db_session, "catalog-changed")["product_types"]
    assert publication.read_monthly_settlement(db_session, "catalog-changed", {
        "store_id": "allowed", "month": "2026-08", "product_type": "tyre"})["lines"] == selected["lines"]


def test_cleanup_cascades_only_analysis_projection(db_session):
    _seed_finance(db_session)
    _run(db_session, "finance-v1", "finance")
    publication.build_finance(db_session, "finance-v1", NOW)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 5
    # SQLite fixture disables FK enforcement; execute the same explicit child
    # deletion locally. The PostgreSQL gate exercises actual ON DELETE CASCADE.
    for table in (publication.pending_members, publication.pending, publication.invoices,
                  publication.statements, publication.dimensions):
        db_session.execute(delete(table).where(table.c.publication_id == "finance-v1"))
    db_session.execute(delete(runs).where(runs.c.id == "finance-v1"))
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 5
    assert db_session.scalar(select(func.count()).select_from(PromotionInvoice)) == 1


@pytest.mark.parametrize("module", ["settlement", "finance"])
def test_selector_months_follow_cutoff_without_empty_current_month(db_session, module):
    _seed_settlement(db_session)
    builder = publication.build_settlement if module == "settlement" else publication.build_finance
    cutoffs = (
        ("october", datetime(2026, 10, 19, tzinfo=UTC), ["2026-09", "2026-08"]),
        ("before", datetime(2026, 10, 31, 15, 59, 59, tzinfo=UTC), ["2026-09", "2026-08"]),
        ("after", datetime(2026, 10, 31, 16, tzinfo=UTC), ["2026-10", "2026-08"]),
    )
    for publication_id, cutoff, expected in cutoffs:
        _run(db_session, publication_id, module, cutoff)
        builder(db_session, publication_id, cutoff)
        db_session.commit()
        assert publication.read_filters(db_session, publication_id, module)["statement_months"] == expected
        # Calculation may cover the unfinished month without advertising it as
        # the period the operator should see first on the billing page.
        horizon = publication._months_through(["2026-08"], cutoff)
        assert horizon[-1] == ("2026-11" if publication_id == "after" else "2026-10")
    assert publication.read_filters(db_session, "before", module)["statement_months"] == ["2026-09", "2026-08"]


@pytest.mark.parametrize("module", ["settlement", "finance"])
@pytest.mark.parametrize("source_kind", ["projection", "statement"])
def test_selector_keeps_real_current_month_period(db_session, module, source_kind):
    _seed_settlement(db_session)
    if source_kind == "projection":
        db_session.add(SettlementProjectionPartitionManifest(generation_id="published", artifact="monthly",
            partition_key="2026-10", source_kind="overlay", data_generation_id="published"))
        db_session.add(SettlementMonthlyOverlay(generation_id="published", partition_key="2026-10",
            month="2026-10", store_id="allowed", product_scope="all", product_type="all"))
    else:
        _statement(db_session, "allowed", "2026-10", 101)
    db_session.commit()
    _run(db_session, "actual-current", module)
    builder = publication.build_settlement if module == "settlement" else publication.build_finance
    builder(db_session, "actual-current", NOW)
    assert publication.read_filters(db_session, "actual-current", module)["statement_months"] == [
        "2026-10", "2026-09", "2026-08"]
