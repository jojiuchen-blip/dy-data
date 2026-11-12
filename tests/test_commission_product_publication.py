"""Current commission display types do not rewrite frozen financial facts."""

import csv
from datetime import date
from io import StringIO

from sqlalchemy import select, update

from apps.api.dy_api.dashboard_publications import commission_types, finance
from apps.api.dy_api.models import (
    AggStoreMonthlySettlement, AggStoreRanking, DimSkuProductRule, DimStore,
    SettlementFeeResult, SettlementFeeResultCurrent, SettlementOrderDetail,
    SettlementMonthlyOverlay, SettlementRankingOverlay, SettlementStatementEntry, SettlementStatementLine,
)
from apps.api.dy_api.routes._data import DashboardDataStore
from test_dashboard_publication_finance import (
    NOW, _fixture_line_entries, _run, _seed_settlement, _statement,
)
from publication_fixture_helpers import ready_periods_fixture


def _seed(session):
    session.add(DimStore(store_id="store", store_name="Synthetic Store"))
    for identity, fee, display_type, snapshot in (
        ("one", 100, "精诚养车", "168保养"), ("two", 150, "精诚养车", "268保养"),
        ("official", 200, "售后官方", "unknown"),
    ):
        session.add(DimSkuProductRule(sku_id=identity, product_id="shared-product",
            product_scope="原scope", product_type=display_type))
        session.add(SettlementFeeResult(fee_result_id=identity, coupon_id=identity,
            order_id="same-order", fee_direction=1, original_business_month="2026-08",
            rule_match_date=date(2026, 8, 1), sale_store_id="store", verify_store_id="store",
            sku_id=identity, product_scope="原scope", product_type=snapshot,
            sale_channel_normalized="LIVE", source_amount_cent=1000, fee_base_cent=1000,
            fee_rate="0.1", fee_amount_cent=fee, rule_version="synthetic-rule",
            scope_rule_version="synthetic-scope", calculation_run_id="synthetic", calculated_at=NOW))
        session.add(SettlementFeeResultCurrent(coupon_id=identity, fee_direction=1, fee_result_id=identity))
        session.add(SettlementOrderDetail(order_id="same-order", coupon_id=identity,
            sku_id=identity, product_type=snapshot,
            sale_store_id="store", verify_store_id="store", sale_time=NOW,
            is_commissionable=True, paid_amount_cent=1000))
    for scope, product_type in (("all", "all"), ("原scope", "all"), ("all", "unknown")):
        values = dict(store_id="store", product_scope=scope, product_type=product_type,
            sales_order_count=1, sales_amount_cent=3000, promotion_net_fee_cent=450,
            management_net_fee_cent=0)
        session.add(AggStoreMonthlySettlement(month="2026-08", promotion_base_cent=3000,
            promotion_original_fee_cent=450, **values))
        for period in (1, 2):
            session.add(AggStoreRanking(period_type=period, period_key="2026-08", month="2026-08",
                store_name="Synthetic Store", net_settlement_reference_cent=450, **values))
    session.commit()


def _set_store_aggregate_totals(session, *, store_id, count, amount, fee):
    values = dict(sales_order_count=count, sales_amount_cent=amount, promotion_net_fee_cent=fee)
    session.execute(update(AggStoreMonthlySettlement).where(
        AggStoreMonthlySettlement.store_id == store_id).values(
            promotion_base_cent=amount, promotion_original_fee_cent=fee, **values))
    session.execute(update(AggStoreRanking).where(AggStoreRanking.store_id == store_id).values(
        net_settlement_reference_cent=fee, **values))


def test_analysis_reclassifies_exact_skus_and_reaggregates_distinct_orders(db_session, monkeypatch):
    monkeypatch.setattr(finance.period_readiness, "capture", ready_periods_fixture)
    _seed(db_session)
    before = list(db_session.execute(select(SettlementFeeResult.fee_result_id,
        SettlementFeeResult.product_type, SettlementFeeResult.fee_amount_cent)))
    _run(db_session, "commission-types", "settlement")
    stats = finance.build_settlement(db_session, "commission-types", NOW)
    assert stats["commission_types_reclassified"]
    db_session.commit()
    assert finance.read_filters(db_session, "commission-types")["product_types"] == ["all", "售后官方", "精诚养车"]
    for period in ("MONTHLY", "CUMULATIVE"):
        for product_type, amount in (("all", 450), ("精诚养车", 250), ("售后官方", 200)):
            result = finance.read_store_ranking(db_session, "commission-types", {
                "period_type": period, "period_key": "2026-08", "product_type": product_type})
            assert result["totals"]["promotion_net_fee_cent"] == amount
            assert result["totals"]["sales_order_count"] == 1
            assert result["total"] == 1
    for product_type, amount, line_count in (("all", 450, 3), ("精诚养车", 250, 2), ("售后官方", 200, 1)):
        result = finance.read_monthly_settlement(db_session, "commission-types", {
            "store_id": "store", "month": "2026-08", "product_type": product_type})
        assert result["metrics"]["promotion_net_fee_cent"] == amount
        assert sum(row["net_fee_cent"] for row in result["lines"]) == amount
        assert len(result["lines"]) == line_count
        assert {row["snapshot_product_type"] for row in result["lines"]} <= {"168保养", "268保养", "unknown"}
    assert list(db_session.execute(select(SettlementFeeResult.fee_result_id,
        SettlementFeeResult.product_type, SettlementFeeResult.fee_amount_cent))) == before
    # The older published analysis is immutable after another catalog edit.
    db_session.execute(update(DimSkuProductRule).values(product_type="next-type"))
    db_session.commit()
    assert finance.read_filters(db_session, "commission-types")["product_types"] == ["all", "售后官方", "精诚养车"]


def test_order_list_pagination_and_full_export_use_the_same_exact_sku_types(db_session):
    _seed(db_session)
    store = DashboardDataStore(db_session)
    filters = {"product_type": "精诚养车", "page": 1, "page_size": 1}
    first = store.order_details(filters)
    second = store.order_details({**filters, "page": 2})
    assert first["pagination"]["total"] == second["pagination"]["total"] == 2
    assert {first["rows"][0]["sku_id"], second["rows"][0]["sku_id"]} == {"one", "two"}
    assert all(row["product_type"] == "精诚养车" for row in first["rows"] + second["rows"])
    exported = list(csv.DictReader(StringIO(store.order_details_export_csv(filters).lstrip("\ufeff"))))
    assert {row["sku_id"] for row in exported} == {"one", "two"}
    assert {row["product_type"] for row in exported} == {"精诚养车"}
    assert store.order_details({**filters, "scope_store_ids": ()})["pagination"]["total"] == 0
    assert store.order_details({**filters, "product_type": "售后官方"})["rows"][0]["sku_id"] == "official"
    fee_details = store.order_fee_details({"fee_direction": "PROMOTION", "month": "2026-08",
        "product_type": "精诚养车", "page": 1, "page_size": 1})
    assert fee_details["total"] == 2
    assert fee_details["list"][0]["product_type"] == "精诚养车"
    assert fee_details["list"][0]["snapshot_product_type"] in {"168保养", "268保养"}


def test_frozen_protected_entries_reclassify_only_the_new_analysis(db_session, monkeypatch):
    monkeypatch.setattr(finance.period_readiness, "capture", ready_periods_fixture)
    _seed_settlement(db_session)
    statement_id = _statement(db_session, "allowed", "2026-08", 177, with_sources=False)
    for direction in (1, 2):
        _fixture_line_entries(db_session, statement_id, "allowed", "2026-08", f"protected-{direction}",
            direction, (77, 100), scope="历史scope", product_type="268保养")
    rank_values = dict(sales_order_count=2, sales_amount_cent=2000, verified_order_count=2,
        verified_amount_cent=2000, promotion_net_fee_cent=177, management_net_fee_cent=177)
    db_session.execute(update(SettlementMonthlyOverlay).where(SettlementMonthlyOverlay.store_id == "allowed")
        .values(promotion_base_cent=2000, promotion_original_fee_cent=177,
            management_base_cent=2000, management_original_fee_cent=177, **rank_values))
    db_session.execute(update(SettlementRankingOverlay).where(SettlementRankingOverlay.store_id == "allowed")
        .values(net_settlement_reference_cent=0, **rank_values))
    db_session.add(DimSkuProductRule(sku_id="frozen-sku", product_scope="其他", product_type="精诚养车"))
    db_session.commit()
    before_lines = list(db_session.execute(select(SettlementStatementLine.statement_line_id,
        SettlementStatementLine.product_type, SettlementStatementLine.net_fee_cent)))
    before_entries = list(db_session.execute(select(SettlementStatementEntry.statement_entry_id,
        SettlementStatementEntry.product_type, SettlementStatementEntry.fee_amount_cent)))
    _run(db_session, "protected-types", "settlement")
    finance.build_settlement(db_session, "protected-types", NOW)
    for product_type in ("all", "精诚养车"):
        result = finance.read_monthly_settlement(db_session, "protected-types", {
            "store_id": "allowed", "month": "2026-08", "product_type": product_type})
        assert result["metrics"]["promotion_net_fee_cent"] == 177
        assert result["metrics"]["management_net_fee_cent"] == 177
        assert {row["snapshot_product_type"] for row in result["lines"]} == {"268保养"}
        assert {row["statement_line_id"] for row in result["lines"]} == {"protected-1", "protected-2"}
    from apps.api.dy_api.routes.dashboard import _finance_order_details_query, _finance_order_detail_item
    finance_rows = list(db_session.execute(_finance_order_details_query({
        "feeDirection": "PROMOTION", "month": "2026-08"})))
    assert len(finance_rows) == 2
    assert {_finance_order_detail_item(row, "PROMOTION")["product_type"] for row in finance_rows} == {"精诚养车"}
    assert {_finance_order_detail_item(row, "PROMOTION")["snapshot_product_type"] for row in finance_rows} == {"268保养"}
    assert list(db_session.execute(select(SettlementStatementLine.statement_line_id,
        SettlementStatementLine.product_type, SettlementStatementLine.net_fee_cent))) == before_lines
    assert list(db_session.execute(select(SettlementStatementEntry.statement_entry_id,
        SettlementStatementEntry.product_type, SettlementStatementEntry.fee_amount_cent))) == before_entries


def test_unresolved_and_uncovered_history_are_counted_and_remain_visible(db_session, monkeypatch):
    monkeypatch.setattr(finance.period_readiness, "capture", ready_periods_fixture)
    _seed(db_session)
    db_session.add(SettlementFeeResult(fee_result_id="missing-catalog", coupon_id="missing-catalog",
        order_id="other-order", fee_direction=1, original_business_month="2026-08",
        rule_match_date=date(2026, 8, 1), sale_store_id="store", sku_id="missing-catalog",
        product_scope="原scope", product_type="unknown", sale_channel_normalized="LIVE",
        source_amount_cent=1000, fee_base_cent=1000, fee_rate="0.25", fee_amount_cent=250,
        rule_version="historic", scope_rule_version="historic", calculation_run_id="historic", calculated_at=NOW))
    db_session.add(SettlementFeeResultCurrent(coupon_id="missing-catalog", fee_direction=1,
        fee_result_id="missing-catalog"))
    _set_store_aggregate_totals(db_session, store_id="store", count=2, amount=4000, fee=700)
    db_session.add(DimStore(store_id="legacy-store", store_name="Legacy Store"))
    for product_type in ("all", "历史类型"):
        db_session.add(AggStoreMonthlySettlement(month="2026-08", store_id="legacy-store",
            product_scope="all", product_type=product_type, promotion_net_fee_cent=90))
        for period in (1, 2):
            db_session.add(AggStoreRanking(period_type=period, period_key="2026-08", month="2026-08",
                store_id="legacy-store", store_name="Legacy Store", product_scope="all",
                product_type=product_type, promotion_net_fee_cent=90, net_settlement_reference_cent=90))
    db_session.commit()
    _run(db_session, "unresolved-types", "settlement")
    stats = finance.build_settlement(db_session, "unresolved-types", NOW)
    assert sum(row["fact_count"] for row in stats["commission_type_coverage"]
        if row["classification_reason"] == "CLASSIFIED") == 3
    assert sum(row["fact_count"] for row in stats["commission_type_coverage"]
        if row["classification_reason"] == "CATALOG_MISSING") == 1
    assert stats["legacy_uncovered_monthly_rows"] == 2
    assert stats["legacy_uncovered_ranking_rows"] == 4
    choices = finance.read_filters(db_session, "unresolved-types")["product_types"]
    assert set(choices) == {"all", "精诚养车", "售后官方", "unknown", "历史类型"}
    assert finance.read_monthly_settlement(db_session, "unresolved-types", {
        "store_id": "store", "month": "2026-08", "product_type": "unknown"})["metrics"]["promotion_net_fee_cent"] == 250
    assert finance.read_monthly_settlement(db_session, "unresolved-types", {
        "store_id": "store", "month": "2026-08", "product_type": "all"})["metrics"]["promotion_net_fee_cent"] == 700
    assert finance.read_monthly_settlement(db_session, "unresolved-types", {
        "store_id": "legacy-store", "month": "2026-08", "product_type": "历史类型"})["metrics"]["promotion_net_fee_cent"] == 90


def test_cumulative_reclassification_counts_same_order_once_in_each_month(db_session, monkeypatch):
    monkeypatch.setattr(finance.period_readiness, "capture", ready_periods_fixture)
    _seed(db_session)
    db_session.add(SettlementFeeResult(fee_result_id="september", coupon_id="september",
        order_id="same-order", fee_direction=1, original_business_month="2026-09",
        rule_match_date=date(2026, 9, 1), sale_store_id="store", sku_id="one",
        product_scope="原scope", product_type="168保养", sale_channel_normalized="LIVE",
        source_amount_cent=1000, fee_base_cent=1000, fee_rate="0.12", fee_amount_cent=120,
        rule_version="synthetic-rule", scope_rule_version="synthetic-scope",
        calculation_run_id="synthetic", calculated_at=NOW))
    db_session.add(SettlementFeeResultCurrent(coupon_id="september", fee_direction=1, fee_result_id="september"))
    db_session.add(AggStoreMonthlySettlement(month="2026-09", store_id="store", product_scope="all",
        product_type="all", sales_order_count=1, sales_amount_cent=1000, promotion_base_cent=1000,
        promotion_original_fee_cent=120, promotion_net_fee_cent=120))
    for period, count, amount, fee in ((1, 1, 1000, 120), (2, 2, 4000, 570)):
        db_session.add(AggStoreRanking(period_type=period, period_key="2026-09", month="2026-09",
            store_id="store", store_name="Synthetic Store", product_scope="all", product_type="all",
            sales_order_count=count, sales_amount_cent=amount, promotion_net_fee_cent=fee,
            net_settlement_reference_cent=fee))
    db_session.commit()
    _run(db_session, "cross-month-types", "settlement")
    stats = finance.build_settlement(db_session, "cross-month-types", NOW)
    assert stats["commission_type_preserved_store_months"] == 0

    for period, product_type, count, fee in (
        ("MONTHLY", "all", 1, 120), ("MONTHLY", "精诚养车", 1, 120),
        ("CUMULATIVE", "all", 2, 570), ("CUMULATIVE", "精诚养车", 2, 370),
    ):
        totals = finance.read_store_ranking(db_session, "cross-month-types", {
            "period_type": period, "period_key": "2026-09", "product_type": product_type})["totals"]
        assert (totals["sales_order_count"], totals["promotion_net_fee_cent"]) == (count, fee)


def test_partial_store_coverage_keeps_aggregate_and_old_types(db_session, monkeypatch):
    monkeypatch.setattr(finance.period_readiness, "capture", ready_periods_fixture)
    _seed(db_session)
    # A legacy store partition also accounts for a fee without exact source evidence.
    _set_store_aggregate_totals(db_session, store_id="store", count=2, amount=4000, fee=700)
    db_session.add(AggStoreMonthlySettlement(month="2026-08", store_id="store", product_scope="all",
        product_type="legacy-only", sales_order_count=1, sales_amount_cent=1000,
        promotion_base_cent=1000, promotion_original_fee_cent=250, promotion_net_fee_cent=250))
    for period in (1, 2):
        db_session.add(AggStoreRanking(period_type=period, period_key="2026-08", month="2026-08",
            store_id="store", store_name="Synthetic Store", product_scope="all", product_type="legacy-only",
            sales_order_count=1, sales_amount_cent=1000, promotion_net_fee_cent=250,
            net_settlement_reference_cent=250))
    db_session.commit()
    _run(db_session, "partial-types", "settlement")
    stats = finance.build_settlement(db_session, "partial-types", NOW)
    assert stats["commission_type_preserved_store_months"] == 1

    for product_type, count, fee in (("all", 2, 700), ("legacy-only", 1, 250), ("精诚养车", 0, 0)):
        monthly = finance.read_monthly_settlement(db_session, "partial-types", {
            "store_id": "store", "month": "2026-08", "product_type": product_type})
        assert (monthly["metrics"]["sales_order_count"], monthly["metrics"]["promotion_net_fee_cent"]) == (count, fee)
        assert all(line["product_type"] != "精诚养车" for line in monthly["lines"])
        for period in ("MONTHLY", "CUMULATIVE"):
            totals = finance.read_store_ranking(db_session, "partial-types", {
                "period_type": period, "period_key": "2026-08", "product_type": product_type})["totals"]
            assert (totals["sales_order_count"], totals["promotion_net_fee_cent"]) == (count, fee)
