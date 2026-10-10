"""DYDATA-102: the month-scoped rebuild must touch exactly one business month."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import (
    RawDouyinVerifyRecord,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
)
from apps.worker import settlement as settlement_mod
from apps.worker.settlement import (
    rebuild_dual_fee_results,
    select_coupon_ids_by_verify_business_month,
)
from apps.worker.settlement_rebuild import (
    SETTLEMENT_SCOPE_BUSINESS_MONTH,
    SETTLEMENT_SCOPE_KEY,
    SETTLEMENT_SCOPE_MONTH_KEY,
    scoped_business_month,
    settlement_month_scope_metadata,
)

UTC = timezone.utc


def _verify(db, verify_id, coupon_id, status, when, *, cancelled=None):
    db.add(
        RawDouyinVerifyRecord(
            verify_id=verify_id,
            coupon_id=coupon_id,
            verify_status=status,
            verify_time=when,
            cancel_time=cancelled,
        )
    )


def _seed_fee_result(db, result_id, coupon_id, *, version=1, fee=1000):
    db.add(
        SettlementFeeResult(
            fee_result_id=result_id,
            coupon_id=coupon_id,
            order_id=f"order-{result_id}",
            fee_direction=1,
            result_version=version,
            original_business_month="2026-10",
            rule_match_date=date(2026, 10, 1),
            sku_id="sku-service",
            sale_channel_normalized="direct",
            source_amount_cent=fee * 10,
            refunded_amount_cent=0,
            fee_base_cent=fee * 10,
            fee_rate=Decimal("0.100000"),
            fee_amount_cent=fee,
            rule_version="rule-v1",
            scope_rule_version="scope-v1",
            result_status=1,
            calculation_run_id=f"run-{result_id}",
            calculated_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    db.add(
        SettlementFeeResultCurrent(
            coupon_id=coupon_id, fee_direction=1, fee_result_id=result_id
        )
    )


def test_coupon_selection_is_limited_to_the_requested_business_month(db_session):
    # September: newest valid record wins.
    _verify(db_session, "v-sep", "coupon-sep", "valid",
            datetime(2026, 9, 12, 3, 0, tzinfo=UTC))
    # October verify beats an earlier September one -> must NOT be selected.
    _verify(db_session, "v-moved-1", "coupon-moved", "valid",
            datetime(2026, 9, 20, 3, 0, tzinfo=UTC))
    _verify(db_session, "v-moved-2", "coupon-moved", "valid",
            datetime(2026, 10, 2, 3, 0, tzinfo=UTC))
    # October-only coupon.
    _verify(db_session, "v-oct", "coupon-oct", "1",
            datetime(2026, 10, 5, 3, 0, tzinfo=UTC))
    # Cancelled newest September record falls back to an earlier valid one.
    _verify(db_session, "v-cancel-ok", "coupon-cancel", "used",
            datetime(2026, 9, 8, 3, 0, tzinfo=UTC))
    _verify(db_session, "v-cancel-bad", "coupon-cancel", "used",
            datetime(2026, 9, 28, 3, 0, tzinfo=UTC),
            cancelled=datetime(2026, 9, 29, tzinfo=UTC))
    # Shanghai boundary: 16:30Z 08-31 is 2026-09-01 00:30+08.
    _verify(db_session, "v-edge", "coupon-edge", "success",
            datetime(2026, 8, 31, 16, 30, tzinfo=UTC))
    db_session.commit()

    september = select_coupon_ids_by_verify_business_month(db_session, "2026-09")
    october = select_coupon_ids_by_verify_business_month(db_session, "2026-10")

    assert set(september) == {"coupon-sep", "coupon-cancel", "coupon-edge"}
    assert set(october) == {"coupon-moved", "coupon-oct"}


def test_bound_fee_rebuild_leaves_other_months_untouched(db_session):
    _seed_fee_result(db_session, "oct-result", "coupon-oct", fee=700)
    db_session.commit()

    before = [
        (r.fee_result_id, r.fee_amount_cent, r.result_status)
        for r in db_session.scalars(
            select(SettlementFeeResult).order_by(SettlementFeeResult.fee_result_id)
        )
    ]

    # A bounded rebuild over an unrelated (September) coupon set.
    stats = rebuild_dual_fee_results(
        db_session, calculation_run_id="scoped-run", coupon_ids=("coupon-sep",)
    )
    db_session.commit()

    after = [
        (r.fee_result_id, r.fee_amount_cent, r.result_status)
        for r in db_session.scalars(
            select(SettlementFeeResult).order_by(SettlementFeeResult.fee_result_id)
        )
    ]
    assert after == before
    assert stats.result_count == 0
    current = list(db_session.scalars(select(SettlementFeeResultCurrent)))
    assert [(c.coupon_id, c.fee_result_id) for c in current] == [
        ("coupon-oct", "oct-result")
    ]


def test_scope_metadata_round_trip(db_session):
    metadata = settlement_month_scope_metadata("2026-09")

    assert metadata == {
        SETTLEMENT_SCOPE_KEY: SETTLEMENT_SCOPE_BUSINESS_MONTH,
        SETTLEMENT_SCOPE_MONTH_KEY: "2026-09",
    }
    assert scoped_business_month(metadata) == "2026-09"
    # Unscoped / malformed jobs keep the historical full-window behaviour.
    assert scoped_business_month({"source_run_id": "x"}) is None
    assert scoped_business_month(None) is None
    assert scoped_business_month({SETTLEMENT_SCOPE_KEY: "business_month"}) is None
    assert scoped_business_month(
        {SETTLEMENT_SCOPE_KEY: SETTLEMENT_SCOPE_BUSINESS_MONTH,
         SETTLEMENT_SCOPE_MONTH_KEY: "2026-9"}
    ) is None


@pytest.mark.parametrize("value", ["2026-9", "202609", "", "2026-09-01", "sept"])
def test_scope_metadata_rejects_malformed_months(value):
    with pytest.raises(ValueError):
        settlement_month_scope_metadata(value)


def test_month_scoped_plan_rejects_a_locked_month(db_session):
    from apps.api.dy_api.models import (
        SettlementProjectionActive,
        SettlementProjectionGeneration,
        SettlementStatement,
    )
    from apps.worker.settlement_rebuild import (
        SettlementMonthLockedError,
        _lineage_refresh_plan,
    )
    from sqlalchemy.orm import sessionmaker

    db_session.add(
        SettlementProjectionGeneration(
            generation_id="gen-1",
            projection_name="settlement",
            generation_kind="lineage",
            base_generation_id=None,
            input_fingerprint="f" * 64,
            lineage_depth=0,
            state="published",
        )
    )
    db_session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id="gen-1"
        )
    )
    db_session.add(
        SettlementStatement(
            statement_id="locked-sep",
            store_id="store-1",
            statement_month="2026-09",
            version_no=1,
            is_current=True,
            statement_status=4,
        )
    )
    db_session.commit()

    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True
    )
    with pytest.raises(SettlementMonthLockedError):
        _lineage_refresh_plan(factory, job_id="scoped-job", months=("2026-09",))


def test_month_scoped_plan_rejects_a_month_outside_the_formal_window(db_session):
    from apps.api.dy_api.models import (
        SettlementProjectionActive,
        SettlementProjectionGeneration,
    )
    from apps.worker.settlement_rebuild import _lineage_refresh_plan
    from sqlalchemy.orm import sessionmaker

    db_session.add(
        SettlementProjectionGeneration(
            generation_id="gen-1",
            projection_name="settlement",
            generation_kind="lineage",
            base_generation_id=None,
            input_fingerprint="f" * 64,
            lineage_depth=0,
            state="published",
        )
    )
    db_session.add(
        SettlementProjectionActive(
            projection_name="settlement", generation_id="gen-1"
        )
    )
    db_session.commit()

    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True
    )
    with pytest.raises(ValueError):
        _lineage_refresh_plan(factory, job_id="scoped-job", months=("2026-07",))
