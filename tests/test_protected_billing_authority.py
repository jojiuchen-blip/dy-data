"""Protected current bills, not replacement pointers, define publication money."""
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import (
    Base, DimStore, SettlementFeeAdjustment, SettlementFeeResult,
    SettlementFeeResultCurrent, SettlementStatement, SettlementStatementConfirmation,
    SettlementStatementEntry,
    SettlementCarryforwardSource, SettlementCarryforwardApplication,
)
from apps.worker.billing_source_capture import collect_billing_sources
from apps.worker.billing_statements import _protected, _write_sources
from apps.worker.protected_billing_authority import ProtectedBillingAuthorityError, validate_protected_authority
from apps.worker.settlement import StatementSource, _apply_and_validate_statement_totals, _sparse_monthly_query

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _result(session, identity, *, coupon="coupon", direction=1, amount=1000, base=10000, version=1, store="store-a", month="2026-08", anchor=None):
    result = SettlementFeeResult(
        fee_result_id=identity, coupon_id=coupon, order_id=f"order-{coupon}",
        fee_direction=direction, result_version=version, original_business_month=month,
        rule_match_date=date(2026, 8, 1), sale_store_id=store, verify_store_id=store,
        sku_id="sku-old", product_scope="scope", product_type="type-old",
        sale_channel_normalized="store", source_amount_cent=base, fee_base_cent=base,
        fee_rate=Decimal("0.1"), fee_amount_cent=amount, rule_version="rule-old",
        scope_rule_version="scope-old", result_status=1, calculation_run_id=identity,
        qualifying_verify_id=f"verify-{identity}", qualifying_verify_time=NOW,
        reverification_anchor_id=anchor, calculated_at=NOW,
    )
    session.add(result)
    session.flush()
    return result


def _source(result, *, receipt=10000):
    return StatementSource(
        source_type=1, source_record_id=result.fee_result_id, original_fee_result_id=result.fee_result_id,
        coupon_id=result.coupon_id, order_id=result.order_id, fee_direction=result.fee_direction,
        original_business_month=result.original_business_month, posting_month=result.original_business_month,
        store_id=result.sale_store_id, product_scope="scope", product_type="type-old",
        base_amount_cent=result.fee_base_cent, fee_amount_cent=result.fee_amount_cent,
        source_amount_cent=result.source_amount_cent, rule_version=result.rule_version,
        product_name="Frozen Product", sku_id="frozen-sku", sku_name=None,
        sale_store_id="store-a", sale_store="Frozen Store", verify_store_id="store-a",
        verify_store="Frozen Verification Store", received_amount_cent=receipt, fee_rate=None,
    )


def _seed(session, *, move_store="store-b", move_month="2026-09", receipt=10000, frozen_management=True):
    session.add_all([DimStore(store_id="store-a", store_name="Live Store A"), DimStore(store_id="store-b", store_name="Live Store B")])
    old_promotion = _result(session, "old-promotion")
    old_management = _result(session, "old-management", direction=2, amount=500)
    old_promotion.result_status = old_management.result_status = 2
    session.add(SettlementFeeAdjustment(
        adjustment_id="frozen-negative", original_fee_result_id="old-promotion", coupon_id="coupon", order_id="order-coupon",
        fee_direction=1, original_business_month="2026-08", adjustment_posting_month="2026-08",
        adjustment_type=1, adjustment_base_cent=-2000, adjustment_fee_cent=-200,
        rule_version="rule-old", adjustment_reason="Frozen synthetic refund", occurred_at=NOW, created_by="synthetic",
    ))
    sources = [_source(old_promotion, receipt=receipt)]
    if frozen_management:
        sources.append(_source(old_management, receipt=receipt))
    sources.append(replace(sources[0], source_type=2, source_record_id="frozen-negative", base_amount_cent=-2000,
                           fee_amount_cent=-200, source_amount_cent=0, adjustment_type=1, refund_at=NOW))
    bill = SettlementStatement(statement_id="frozen-bill", store_id="store-a", statement_month="2026-08", statement_status=2,
                               is_current=True, version_no=1, store_name_snapshot="Frozen Store")
    session.add(bill)
    session.flush()
    _write_sources(session, bill, sources)
    session.flush()
    _apply_and_validate_statement_totals(session, bill)
    session.add(SettlementStatementConfirmation(
        confirmation_id="only-promotion-confirmed", statement_id=bill.statement_id, fee_direction=1,
        confirmed_amount_cent=800, confirmation_status=1, confirmed_by="synthetic",
    ))
    for direction in (1, 2):
        current = _result(session, f"replacement-{direction}", direction=direction, amount=2000,
                          base=20000, version=2, store=move_store, month=move_month)
        session.add(SettlementFeeResultCurrent(coupon_id="coupon", fee_direction=direction, fee_result_id=current.fee_result_id))
    normal = _result(session, "normal", coupon="normal-coupon", amount=300, base=3000, store="store-b", month="2026-09")
    session.add(SettlementFeeResultCurrent(coupon_id=normal.coupon_id, fee_direction=1, fee_result_id=normal.fee_result_id))
    session.commit()
    return bill


def _facts(session):
    session.expire_all()
    return {table.name: sorted(repr(tuple(row)) for row in session.execute(select(table)))
            for table in Base.metadata.sorted_tables if table.name.startswith(("settlement_fee", "settlement_statement", "invoice", "promotion_invoice"))}


@pytest.mark.parametrize("move_store,move_month", (("store-a", "2026-08"), ("store-b", "2026-08"), ("store-b", "2026-09")))
def test_whole_confirmed_status_two_bill_and_negative_entry_override_current_chain(db_session, move_store, move_month):
    bill = _seed(db_session, move_store=move_store, move_month=move_month)
    before = _facts(db_session)
    assert _protected(db_session, bill)
    sources = collect_billing_sources(db_session, months=("2026-08", "2026-09"))
    frozen = [row for row in sources if row.store_id == "store-a"]
    assert {(row.source_type, row.source_record_id) for row in frozen} == {(1, "old-promotion"), (1, "old-management"), (2, "frozen-negative")}
    assert sum(row.fee_amount_cent for row in frozen if row.fee_direction == 1) == 800
    assert sum(row.fee_amount_cent for row in frozen if row.fee_direction == 2) == 500
    assert all(row.product_name == "Frozen Product" and row.sku_id == "frozen-sku" and row.fee_rate is None for row in frozen)
    assert {row.source_record_id for row in sources if row.store_id == "store-b"} == {"normal"}
    august = db_session.execute(_sparse_monthly_query("2026-08")).mappings().all()
    september = db_session.execute(_sparse_monthly_query("2026-09")).mappings().all()
    all_august = next(row for row in august if (row["store_id"], row["product_scope"], row["product_type"]) == ("store-a", "all", "all"))
    assert (all_august["promotion_original_fee_cent"], all_august["promotion_adjustment_fee_cent"], all_august["management_original_fee_cent"]) == (1000, -200, 500)
    assert {(row["store_id"], row["promotion_original_fee_cent"]) for row in september} == {("store-b", 300)}
    assert _facts(db_session) == before


def test_null_display_snapshots_stay_unknown_with_exact_immutable_receipt_fallback(db_session):
    _seed(db_session, receipt=None)
    sources = collect_billing_sources(db_session, months=("2026-08",))
    assert all(row.received_amount_cent is None and row.fee_rate is None for row in sources)
    assert {row.source_amount_cent for row in sources if row.source_type == 1} == {10000}
    original = db_session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == "old-promotion"))
    original.fee_base_cent = 9999
    db_session.commit()
    with pytest.raises(ProtectedBillingAuthorityError, match="exact immutable basis"):
        collect_billing_sources(db_session, months=("2026-08",))


def test_source_amount_is_exact_original_economics_not_received_display_snapshot(db_session):
    _seed(db_session, receipt=9000)
    sources = collect_billing_sources(db_session, months=("2026-08",))
    assert {row.source_amount_cent for row in sources if row.source_type == 1} == {10000}
    assert {row.received_amount_cent for row in sources} == {9000}


def test_moved_primary_chain_closes_both_publication_months(db_session):
    from apps.worker.settlement import _sparse_expand_affected_months

    _seed(db_session)
    assert _sparse_expand_affected_months(db_session, ("2026-08",)) == ("2026-08", "2026-09")
    assert _sparse_expand_affected_months(db_session, ("2026-09",)) == ("2026-08", "2026-09")


def test_protected_header_without_complete_entries_fails_closed(db_session):
    _seed(db_session)
    entry = db_session.scalar(select(SettlementStatementEntry).where(SettlementStatementEntry.source_record_id == "old-management"))
    db_session.delete(entry)
    db_session.commit()
    before = _facts(db_session)
    with pytest.raises(ProtectedBillingAuthorityError, match="immutable header"):
        collect_billing_sources(db_session, months=("2026-08",))
    assert _facts(db_session) == before


@pytest.mark.parametrize("locked_destination", (False, True))
def test_normal_month_refresh_capture_and_build_use_same_frozen_chain_closure(db_session, monkeypatch, locked_destination):
    from sqlalchemy.orm import sessionmaker
    from apps.api.dy_api.models import SettlementProjectionActive, SettlementProjectionGeneration
    from apps.worker import settlement_rebuild as rebuild

    _seed(db_session)
    db_session.add(SettlementProjectionGeneration(generation_id="base", state="published", input_fingerprint="f" * 64))
    db_session.flush()
    db_session.add(SettlementProjectionActive(projection_name="settlement", generation_id="base"))
    if locked_destination:
        db_session.add(SettlementStatement(statement_id="locked-destination", store_id="store-b", statement_month="2026-09", statement_status=4))
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    if locked_destination:
        with pytest.raises(rebuild.SettlementMonthLockedError, match="closure is locked"):
            rebuild._lineage_refresh_plan(factory, job_id="closure-job", months=("2026-08",))
        return
    plan = rebuild._lineage_refresh_plan(factory, job_id="closure-job", months=("2026-08",))
    assert plan.affected_months == ("2026-08", "2026-09")
    captured = []
    original_collect = rebuild.collect_billing_sources
    def collect(session, *, months, slots):
        captured.append(months)
        return original_collect(session, months=months, slots=slots)
    class ReachedBuild(Exception):
        pass
    def build(*args, **kwargs):
        assert captured == [kwargs["affected_months"]] == [("2026-08", "2026-09")]
        raise ReachedBuild()
    monkeypatch.setattr(rebuild, "collect_billing_sources", collect)
    monkeypatch.setattr(rebuild, "freeze_billing_sources", lambda *args, **kwargs: None)
    monkeypatch.setattr(rebuild, "_supersede_obsolete_settlement_generations", lambda *args, **kwargs: None)
    monkeypatch.setattr(rebuild, "_fence_settlement_rebuild_commit", lambda *args, **kwargs: None)
    monkeypatch.setattr(rebuild, "build_settlement_sparse_overlay", build)
    before = _facts(db_session)
    with pytest.raises(ReachedBuild):
        rebuild.refresh_active_settlement_lineage(factory, job_id="closure-job", claim_id="synthetic", months=("2026-08",))
    assert _facts(db_session) == before


@pytest.mark.parametrize("basis,allowed", (("old-promotion", True), ("replacement-1", False)))
def test_adjustments_use_exact_frozen_basis_instead_of_pointer_reanchoring(db_session, basis, allowed):
    _seed(db_session)
    db_session.add(SettlementFeeAdjustment(
        adjustment_id="later-refund", original_fee_result_id=basis, coupon_id="coupon", order_id="order-coupon",
        fee_direction=1, original_business_month="2026-08" if allowed else "2026-09", adjustment_posting_month="2026-09",
        adjustment_type=1, adjustment_base_cent=-1000, adjustment_fee_cent=-100,
        rule_version="rule-old", adjustment_reason="Synthetic refund", occurred_at=NOW, created_by="synthetic",
    ))
    db_session.commit()
    before = _facts(db_session)
    if not allowed:
        with pytest.raises(ProtectedBillingAuthorityError, match="unapproved replacement"):
            collect_billing_sources(db_session, months=("2026-08", "2026-09"))
    else:
        sources = collect_billing_sources(db_session, months=("2026-08", "2026-09"))
        adjustment = next(row for row in sources if row.source_record_id == "later-refund")
        assert adjustment.original_fee_result_id == "old-promotion"
        assert adjustment.product_name == "Frozen Product" and adjustment.fee_rate is None
        assert adjustment.fee_amount_cent == -100 and adjustment.posting_month == "2026-09"
    assert _facts(db_session) == before


def test_nested_monthly_lines_match_authority_when_replacement_and_normal_share_a_group(db_session):
    from apps.api.dy_api.dashboard_publications.finance import _monthly_lines
    from apps.api.dy_api.routes._data import DashboardDataStore

    _seed(db_session)
    before = _facts(db_session)
    _, august = _monthly_lines(db_session, DashboardDataStore(db_session), "2026-08")
    _, september = _monthly_lines(db_session, DashboardDataStore(db_session), "2026-09")
    assert {row["fee_direction"]: row["net_fee_cent"] for row in august["store-a"]} == {"PROMOTION": 800, "MANAGEMENT": 500}
    assert all(row["fee_rates"] == [] and row["min_fee_rate"] is None for row in august["store-a"])
    assert len(september["store-b"]) == 1 and september["store-b"][0]["net_fee_cent"] == 300
    assert _facts(db_session) == before


def _adjustment(session, identity, basis, *, amount=-100, base=-1000, direction=1, kind=1, month="2026-09", original_month="2026-08"):
    row = SettlementFeeAdjustment(
        adjustment_id=identity, original_fee_result_id=basis, coupon_id="coupon", order_id="order-coupon",
        fee_direction=direction, original_business_month=original_month, adjustment_posting_month=month,
        adjustment_type=kind, adjustment_base_cent=base, adjustment_fee_cent=amount,
        rule_version="rule-old", adjustment_reason="Synthetic event", occurred_at=NOW, created_by="synthetic",
    )
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("restoration_evidence", (False, True))
def test_reverification_anchor_requires_cancellation_and_explicit_restoration(db_session, restoration_evidence):
    _seed(db_session)
    _adjustment(db_session, "old-verification-cancel", "old-promotion", amount=-800, base=-8000, kind=3)
    basis = _result(db_session, "new-verification", amount=1200, base=12000, version=3, month="2026-09", anchor="old-promotion")
    basis.result_status = 2
    if restoration_evidence:
        _adjustment(db_session, "new-verification-restore", basis.fee_result_id, amount=1200, base=12000, kind=4, original_month="2026-09")
    _adjustment(db_session, "new-verification-refund", basis.fee_result_id, amount=-50, base=-500, original_month="2026-09")
    db_session.commit()
    before = _facts(db_session)
    if restoration_evidence:
        sources = collect_billing_sources(db_session, months=("2026-08", "2026-09"))
        events = {row.source_record_id: row for row in sources}
        assert events["old-verification-cancel"].original_fee_result_id == "old-promotion"
        assert events["new-verification-restore"].original_fee_result_id == "new-verification"
        assert events["new-verification-refund"].original_fee_result_id == "new-verification"
        assert events["new-verification-restore"].fee_amount_cent == 1200
    else:
        with pytest.raises(ProtectedBillingAuthorityError, match="unapproved replacement"):
            collect_billing_sources(db_session, months=("2026-08", "2026-09"))
    assert _facts(db_session) == before


def test_exact_frozen_carryforward_keeps_only_active_application_without_losing_other_direction(db_session):
    _seed(db_session, frozen_management=False)
    for index, active in ((1, False), (2, True)):
        identity = f"carryforward-{index}"
        _adjustment(db_session, identity, "old-promotion")
        if index == 1:
            db_session.add(SettlementCarryforwardSource(
                carryforward_source_id="carryforward-source", source_event_type=1, source_event_key="refund:event",
                original_fee_result_id="old-promotion", refund_event_id="synthetic-refund", coupon_id="coupon",
                order_id="order-coupon", store_id="store-a", fee_direction=1, original_business_month="2026-08",
                event_month="2026-08", adjustment_type=1, adjustment_base_cent=-1000, adjustment_fee_cent=-100,
                rule_version="rule-old", carryforward_reason="Frozen basis event", occurred_at=NOW, created_by="synthetic",
            ))
        db_session.add(SettlementCarryforwardApplication(
            carryforward_application_id=f"application-{index}", carryforward_source_id="carryforward-source",
            target_statement_id="future-bill", target_statement_version=1, target_posting_month="2026-09",
            target_adjustment_id=identity, application_version=index, is_current=active, applied_by="synthetic", applied_at=NOW,
        ))
    other = _result(db_session, "other-direction-basis", direction=2, amount=500, base=5000, version=3, store="store-b", month="2026-09")
    other.result_status = 2
    pointer = db_session.scalar(select(SettlementFeeResultCurrent).where(SettlementFeeResultCurrent.fee_direction == 2, SettlementFeeResultCurrent.coupon_id == "coupon"))
    pointer.fee_result_id = other.fee_result_id
    _adjustment(db_session, "other-direction-refund", other.fee_result_id, amount=-50, base=-500, direction=2, original_month="2026-09")
    db_session.commit()
    sources = collect_billing_sources(db_session, months=("2026-08", "2026-09"))
    identities = {row.source_record_id for row in sources}
    assert "carryforward-2" in identities and "carryforward-1" not in identities
    assert "other-direction-refund" in identities and "other-direction-basis" in identities
