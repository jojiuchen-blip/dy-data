"""DYDATA-102 read-only settlement audit: layer semantics and identifier safety."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event

from apps.api.dy_api.models import (
    RawDouyinVerifyRecord,
    SettlementCarryforwardApplication,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementStatement,
    SettlementStatementEntry,
)
from apps.api.dy_api.settlement_audit_readonly import (
    AUDIT_MONTHS,
    SettlementMonthAudit,
    parse_audit_months,
    read_settlement_month_audit,
)

UTC = timezone.utc


def _verify(db, verify_id, coupon_id, status, when, *, cancelled=None, paid=None):
    db.add(
        RawDouyinVerifyRecord(
            verify_id=verify_id,
            coupon_id=coupon_id,
            verify_status=status,
            verify_time=when,
            cancel_time=cancelled,
            paid_amount_cent=paid,
        )
    )


def _fee_result(db, result_id, coupon_id, *, month="2026-09", direction=1, status=1,
                source=10000, refunded=0, base=10000, fee=1000, anchor=None, version=1):
    db.add(
        SettlementFeeResult(
            fee_result_id=result_id,
            coupon_id=coupon_id,
            order_id=f"order-{result_id}",
            fee_direction=direction,
            result_version=version,
            original_business_month=month,
            rule_match_date=date(2026, 9, 1),
            sku_id="sku-service",
            sale_channel_normalized="direct",
            source_amount_cent=source,
            refunded_amount_cent=refunded,
            fee_base_cent=base,
            fee_rate=Decimal("0.100000"),
            fee_amount_cent=fee,
            rule_version="rule-v1",
            scope_rule_version="scope-v1",
            result_status=status,
            calculation_run_id=f"run-{result_id}",
            reverification_anchor_id=anchor,
            calculated_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )


def _current(db, coupon_id, fee_result_id, *, direction=1):
    db.add(
        SettlementFeeResultCurrent(
            coupon_id=coupon_id, fee_direction=direction, fee_result_id=fee_result_id
        )
    )


def _adjustment(db, adjustment_id, original_fee_result_id, *, month="2026-09", direction=1,
                type_code=1, base=-1000, fee=-100):
    db.add(
        SettlementFeeAdjustment(
            adjustment_id=adjustment_id,
            original_fee_result_id=original_fee_result_id,
            coupon_id=f"coupon-{adjustment_id}",
            order_id=f"order-{adjustment_id}",
            fee_direction=direction,
            original_business_month="2026-09",
            adjustment_posting_month=month,
            adjustment_type=type_code,
            adjustment_base_cent=base,
            adjustment_fee_cent=fee,
            rule_version="rule-v1",
            adjustment_reason="synthetic",
            occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
            created_by="synthetic",
        )
    )


def _carryforward(db, application_id, adjustment_id, *, is_current):
    db.add(
        SettlementCarryforwardApplication(
            carryforward_application_id=application_id,
            carryforward_source_id=f"source-{application_id}",
            target_statement_id="statement-superseded",
            target_statement_version=1,
            target_adjustment_id=adjustment_id,
            target_posting_month="2026-10",
            is_current=is_current,
            applied_by="synthetic",
            applied_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )


def _statement(db, statement_id, *, month="2026-09", current=True, status=1, version=1):
    db.add(
        SettlementStatement(
            statement_id=statement_id,
            store_id=f"store-{statement_id}",
            statement_month=month,
            version_no=version,
            is_current=current,
            statement_status=status,
        )
    )


def _entry(db, entry_id, statement_id, *, month="2026-09", posting="2026-09",
           direction=1, source_type=1, base=10000, fee=1000):
    db.add(
        SettlementStatementEntry(
            statement_entry_id=entry_id,
            statement_id=statement_id,
            statement_line_id=f"line-{entry_id}",
            source_type=source_type,
            source_record_id=f"source-{entry_id}",
            original_fee_result_id=f"result-{entry_id}",
            coupon_id=f"coupon-{entry_id}",
            order_id=f"order-{entry_id}",
            fee_direction=direction,
            original_business_month=month,
            statement_posting_month=posting,
            base_amount_cent=base,
            fee_amount_cent=fee,
            rule_version="rule-v1",
        )
    )


@pytest.mark.parametrize("value,expected", [
    (None, AUDIT_MONTHS),
    ("2026-09", ("2026-09",)),
    ("2026-10,2026-09", AUDIT_MONTHS),
    (" 2026-09 , 2026-10 ", AUDIT_MONTHS),
])
def test_parse_audit_months_accepts_only_fixed_window(value, expected):
    assert parse_audit_months(value) == expected


@pytest.mark.parametrize("value", [
    "", "2026-08", "2026-11", "2026-09,2026-11", "2026-09,2026-09", "2026-09,", ",2026-10", "2026-09;2026-10",
])
def test_parse_audit_months_rejects_anything_else(value):
    with pytest.raises(ValueError):
        parse_audit_months(value)


def test_worker_and_audit_share_the_valid_verify_status_set():
    from apps.worker.settlement import VALID_VERIFY_STATUSES as worker_statuses

    from apps.api.dy_api.settlement_audit_readonly import VALID_VERIFY_STATUSES

    assert VALID_VERIFY_STATUSES == worker_statuses


def test_verify_sources_follow_latest_valid_uncancelled_record_per_coupon(db_session):
    # coupon-a: latest valid verify moved to 2026-10, so it is not a 2026-09 source.
    _verify(db_session, "v-a1", "coupon-a", "valid",
            datetime(2026, 9, 10, 3, 0, tzinfo=UTC), paid=5000)
    _verify(db_session, "v-a2", "coupon-a", "1",
            datetime(2026, 10, 2, 3, 0, tzinfo=UTC), paid=5000)
    # coupon-b: only verify is cancelled, so it never qualifies.
    _verify(db_session, "v-b1", "coupon-b", "verified",
            datetime(2026, 9, 11, 3, 0, tzinfo=UTC), paid=7000,
            cancelled=datetime(2026, 9, 12, tzinfo=UTC))
    # coupon-c: unknown status is ignored, the valid 2026-09 row wins.
    _verify(db_session, "v-c1", "coupon-c", "refunded",
            datetime(2026, 9, 20, 3, 0, tzinfo=UTC), paid=9000)
    _verify(db_session, "v-c2", "coupon-c", " Valid ",
            datetime(2026, 9, 12, 3, 0, tzinfo=UTC), paid=1000)
    # coupon-d: newest record is cancelled, so the earlier valid one still counts.
    _verify(db_session, "v-d1", "coupon-d", "used",
            datetime(2026, 9, 15, 3, 0, tzinfo=UTC), paid=2000)
    _verify(db_session, "v-d2", "coupon-d", "used",
            datetime(2026, 9, 25, 3, 0, tzinfo=UTC), paid=2000,
            cancelled=datetime(2026, 9, 26, tzinfo=UTC))
    # Shanghai boundary: 16:30Z on 08-31 is 2026-09-01 00:30 +08; 16:00Z on 09-30 is 2026-10-01.
    _verify(db_session, "v-e1", "coupon-e", "success",
            datetime(2026, 8, 31, 16, 30, tzinfo=UTC), paid=300)
    _verify(db_session, "v-f1", "coupon-f", "fulfilled",
            datetime(2026, 9, 30, 16, 0, tzinfo=UTC), paid=400)
    _verify(db_session, "v-g1", "coupon-g", "valid", None, paid=500)
    db_session.commit()

    audit = read_settlement_month_audit(db_session)
    rows = {(row.business_month, row.verify_status): row for row in audit.verify_sources}

    assert set(rows) == {("2026-09", "valid"), ("2026-09", "used"), ("2026-09", "success"),
                         ("2026-10", "1"), ("2026-10", "fulfilled")}
    assert rows[("2026-09", "valid")].source_rows == 1          # coupon-c only
    assert rows[("2026-09", "valid")].paid_amount_cent == 1000
    assert rows[("2026-09", "used")].source_rows == 1           # coupon-d, not the cancelled one
    assert rows[("2026-09", "success")].paid_amount_cent == 300  # coupon-e
    assert rows[("2026-10", "1")].source_rows == 1              # coupon-a, re-attributed
    assert rows[("2026-10", "fulfilled")].paid_amount_cent == 400  # coupon-f
    total_coupons = sum(row.source_rows for row in audit.verify_sources)
    assert total_coupons == 5  # coupon-b and coupon-g excluded


def test_current_pointer_excludes_superseded_result_versions(db_session):
    _fee_result(db_session, "result-old", "coupon-1", status=2, fee=999, version=1)
    _fee_result(db_session, "result-new", "coupon-1", status=1, fee=1000, version=2)
    _current(db_session, "coupon-1", "result-new")
    _fee_result(db_session, "result-other", "coupon-2", month="2026-10", status=1, fee=250)
    _current(db_session, "coupon-2", "result-other")
    db_session.commit()

    audit = read_settlement_month_audit(db_session)
    rows = {(r.business_month, r.result_status): r for r in audit.current_fee_results}

    assert set(rows) == {("2026-09", 1), ("2026-10", 1)}
    assert rows[("2026-09", 1)].result_rows == 1
    assert rows[("2026-09", 1)].fee_amount_cent == 1000   # the 999 superseded version is gone
    assert rows[("2026-10", 1)].fee_amount_cent == 250


def test_current_adjustments_keep_ordinary_and_only_current_carryforward(db_session):
    _fee_result(db_session, "result-1", "coupon-1")
    _current(db_session, "coupon-1", "result-1")
    _adjustment(db_session, "adj-ordinary", "result-1", base=-1000, fee=-100)
    _adjustment(db_session, "adj-cf-current", "result-1", base=-2000, fee=-200)
    _adjustment(db_session, "adj-cf-stale", "result-1", base=-4000, fee=-400)
    _adjustment(db_session, "adj-orphan", "result-missing", base=-8000, fee=-800)
    _carryforward(db_session, "cf-app-1", "adj-cf-current", is_current=True)
    _carryforward(db_session, "cf-app-2", "adj-cf-stale", is_current=False)
    db_session.commit()

    audit = read_settlement_month_audit(db_session)
    assert len(audit.current_adjustments) == 1
    row = audit.current_adjustments[0]
    assert (row.posting_month, row.fee_direction) == ("2026-09", 1)
    assert row.adjustment_rows == 2                        # ordinary + current carryforward
    assert row.adjustment_base_cent == -3000
    assert row.adjustment_fee_cent == -300
    assert row.anchor_matched_rows == 0


def test_anchor_reachable_basis_is_counted_and_reported(db_session):
    _fee_result(db_session, "result-anchor", "coupon-1", status=2, version=1)
    _fee_result(db_session, "result-base", "coupon-1", status=1, anchor="result-anchor", version=2)
    _current(db_session, "coupon-1", "result-anchor")
    _adjustment(db_session, "adj-anchor", "result-base", base=-500, fee=-50)
    db_session.commit()

    audit = read_settlement_month_audit(db_session)
    row = audit.current_adjustments[0]
    assert row.adjustment_rows == 1
    assert row.anchor_matched_rows == 1


def test_statement_entries_use_current_header_and_posting_month(db_session):
    _statement(db_session, "stmt-current", month="2026-09", current=True, status=2, version=2)
    _statement(db_session, "stmt-superseded", month="2026-09", current=False, version=1)
    _statement(db_session, "stmt-october", month="2026-10", current=True, status=1)
    _entry(db_session, "e-current", "stmt-current", posting="2026-09")
    _entry(db_session, "e-history", "stmt-superseded", posting="2026-09")
    _entry(db_session, "e-october", "stmt-october", month="2026-10", posting="2026-10",
           direction=2, source_type=2, base=-100, fee=-10)
    db_session.commit()

    audit = read_settlement_month_audit(db_session)
    rows = {(r.posting_month, r.fee_direction): r for r in audit.current_statement_entries}

    assert set(rows) == {("2026-09", 1), ("2026-10", 2)}
    assert rows[("2026-09", 1)].entry_rows == 1            # superseded header not counted
    assert rows[("2026-09", 1)].statement_status == 2
    assert rows[("2026-09", 1)].original_entries == 1
    assert rows[("2026-09", 1)].fee_amount_cent == 1000
    assert rows[("2026-10", 2)].adjustment_entries == 1
    assert audit.guards.superseded_statement_entry_rows == 1
    assert audit.guards.posting_month_mismatch_rows == 0


def test_guard_flags_posting_month_mismatch(db_session):
    _statement(db_session, "stmt-mixed", month="2026-10", current=True)
    _entry(db_session, "e-mixed", "stmt-mixed", month="2026-09", posting="2026-09")
    db_session.commit()

    audit = read_settlement_month_audit(db_session)
    assert audit.guards.posting_month_mismatch_rows == 1


def test_audit_issues_no_write_statements(db_session):
    _fee_result(db_session, "result-1", "coupon-1")
    _current(db_session, "coupon-1", "result-1")
    db_session.commit()

    statements: list[str] = []
    listener = lambda conn, cursor, statement, parameters, context, many: statements.append(statement)
    event.listen(db_session.get_bind(), "before_cursor_execute", listener)
    try:
        read_settlement_month_audit(db_session)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)

    assert statements
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"))
        for statement in statements
    )


def test_response_contract_exposes_no_identifiers():
    schema = SettlementMonthAudit.model_json_schema()

    names: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    names.extend(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    assert names
    # Identifier-shaped names would end in _id (e.g. "paid_amount_cent" must not trip this).
    assert [name for name in names if name == "id" or name.endswith("_id")] == []
    assert [name for name in names if "store" in name.lower() or "order" in name.lower()
            or "coupon" in name.lower()] == []


def test_route_is_registered_for_the_fixed_window(monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "1")
    from dy_api.main import create_app

    paths = create_app().openapi()["paths"]
    assert "/api/v1/admin/settlement-month-audit" in paths
    assert "/api/v1/admin/pdca-source-evidence" in paths
