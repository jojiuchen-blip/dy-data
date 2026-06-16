from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueReassignRuleSetting,
    DimSkuProductRule,
    RawDouyinClue,
    SettlementOrderDetail,
)
from apps.worker.clue_center import mask_phone, rebuild_clue_center


def _dt(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 6, day, hour, 0, tzinfo=timezone.utc)


def _assert_same_instant(actual: datetime | None, expected: datetime) -> None:
    assert actual is not None
    assert actual.replace(tzinfo=timezone.utc) == expected


def _raw_clue(
    key: str,
    *,
    order_id: str,
    clue_id: str,
    create_time: datetime,
    status: str = "履约中",
    telephone: str = "13812345678",
    store_id: str = "store-1",
    store_name: str = "Store One",
    product_id: str = "sku-1",
) -> RawDouyinClue:
    return RawDouyinClue(
        clue_row_key=key,
        clue_id=clue_id,
        create_time_detail=create_time,
        telephone=telephone,
        enc_telephone="encrypted",
        product_id=product_id,
        product_name="Service Product",
        order_id=order_id,
        order_status=status,
        follow_life_account_id=store_id,
        follow_life_account_name=store_name,
        auto_city_name="Shanghai",
        auto_province_name="Shanghai",
        author_nickname="Author",
        raw_payload={"clue_id": clue_id},
        imported_at=create_time,
        updated_at=create_time,
    )


def test_mask_phone_hides_middle_four_digits() -> None:
    assert mask_phone("13812345678") == "138****5678"
    assert mask_phone("not-a-phone") == ""
    assert mask_phone(None) == ""


def test_rebuild_materializes_eligible_order_level_clues(db_session: Session) -> None:
    db_session.add(
        DimSkuProductRule(
            sku_id="sku-1",
            product_type="Car Service",
            product_name="Service Product",
            commission_rate=Decimal("0"),
            is_service_product=True,
        )
    )
    db_session.add_all(
        [
            _raw_clue("row-1-late", order_id="order-1", clue_id="clue-late", create_time=_dt(1, 12)),
            _raw_clue("row-1-early", order_id="order-1", clue_id="clue-early", create_time=_dt(1, 9)),
            _raw_clue("row-closed", order_id="order-closed", clue_id="closed", create_time=_dt(1), status="交易关闭"),
            _raw_clue("row-zero", order_id="0", clue_id="zero", create_time=_dt(1)),
        ]
    )
    db_session.commit()

    stats = rebuild_clue_center(db_session, now=_dt(2))

    assert stats == {"eligible_orders": 1, "assignment_rounds": 1}
    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    assert order.canonical_clue_id == "clue-early"
    assert order.source_clue_count == 2
    assert order.source_clue_ids == ["clue-early", "clue-late"]
    _assert_same_instant(order.assigned_at, _dt(1, 9))
    assert order.assigned_at_source == "clue_create_time_detail"
    assert order.assigned_store_id == "store-1"
    assert order.product_type == "Car Service"
    assert order.phone_masked == "138****5678"
    assert order.lead_status == "active"
    assert order.current_round_status == "active_unfollowed"
    assert order.expires_at is None

    assert db_session.get(ClueCenterOrder, "order-closed") is None
    assert db_session.get(ClueCenterOrder, "0") is None


def test_sla_configuration_sets_expiration(db_session: Session) -> None:
    db_session.add(_raw_clue("row-1", order_id="order-1", clue_id="clue-1", create_time=_dt(1)))
    db_session.add(
        ClueReassignRuleSetting(
            setting_key="global",
            reassign_sla_hours=24,
            updated_by="admin",
            updated_at=_dt(1),
        )
    )
    db_session.commit()

    rebuild_clue_center(db_session, now=_dt(1, 12))

    order = db_session.get(ClueCenterOrder, "order-1")
    round_row = db_session.get(ClueAssignmentRound, "order-1-1")
    assert order is not None
    assert round_row is not None
    _assert_same_instant(order.expires_at, _dt(1) + timedelta(hours=24))
    _assert_same_instant(round_row.expires_at, _dt(1) + timedelta(hours=24))


def test_failed_and_unreachable_follow_results_have_distinct_meanings(db_session: Session) -> None:
    db_session.add_all(
        [
            _raw_clue("row-failed", order_id="order-failed", clue_id="clue-failed", create_time=_dt(1)),
            _raw_clue("row-unreachable", order_id="order-unreachable", clue_id="clue-unreachable", create_time=_dt(1)),
            ClueAssignmentRound(
                assignment_round_id="order-failed-1",
                order_id="order-failed",
                round_no=1,
                assigned_at=_dt(1),
                assigned_at_source="clue_create_time_detail",
                follow_result="failed",
                is_followed=True,
                is_follow_success=False,
                round_status="active_unfollowed",
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
            ClueAssignmentRound(
                assignment_round_id="order-unreachable-1",
                order_id="order-unreachable",
                round_no=1,
                assigned_at=_dt(1),
                assigned_at_source="clue_create_time_detail",
                follow_result="unreachable",
                is_followed=True,
                is_follow_success=False,
                round_status="active_unfollowed",
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
        ]
    )
    db_session.commit()

    rebuild_clue_center(db_session, now=_dt(2))

    failed = db_session.get(ClueCenterOrder, "order-failed")
    unreachable = db_session.get(ClueCenterOrder, "order-unreachable")
    assert failed is not None
    assert unreachable is not None
    assert failed.current_round_status == "failed_pending_reassign"
    assert failed.lead_status == "pending_reassign"
    assert unreachable.current_round_status == "active_followed"
    assert unreachable.is_followed is True
    assert unreachable.is_follow_success is False


def test_successful_follow_self_store_verification_counts_as_converted(db_session: Session) -> None:
    db_session.add(_raw_clue("row-1", order_id="order-1", clue_id="clue-1", create_time=_dt(1)))
    db_session.add(
        ClueAssignmentRound(
            assignment_round_id="order-1-1",
            order_id="order-1",
            round_no=1,
            assigned_at=_dt(1),
            assigned_at_source="clue_create_time_detail",
            followed_at=_dt(1, 12),
            follow_result="success",
            is_followed=True,
            is_follow_success=True,
            round_status="active_unfollowed",
            created_at=_dt(1),
            updated_at=_dt(1),
        )
    )
    db_session.add(
        SettlementOrderDetail(
            coupon_id="coupon-1",
            order_id="order-1",
            product_type="Car Service",
            sale_time=_dt(1),
            is_verified=True,
            verify_store_id="store-1",
            verify_store_name="Store One",
            verify_time=_dt(2),
            relation_type="same_store",
            is_commissionable=False,
            is_refund_excluded=False,
            paid_amount_cent=10000,
            commission_rate=Decimal("0"),
            receivable_commission_cent=0,
            payable_commission_cent=0,
            updated_at=_dt(2),
        )
    )
    db_session.commit()

    rebuild_clue_center(db_session, now=_dt(3))

    order = db_session.get(ClueCenterOrder, "order-1")
    round_row = db_session.get(ClueAssignmentRound, "order-1-1")
    assert order is not None
    assert round_row is not None
    assert order.lead_status == "converted"
    assert order.is_follow_success is True
    assert order.is_self_store_verified is True
    assert round_row.is_self_store_verified is True
    assert order.verified_store_id == "store-1"
    _assert_same_instant(order.verified_at, _dt(2))
