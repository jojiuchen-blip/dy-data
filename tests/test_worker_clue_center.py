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
    assert order.phone_plain == "13812345678"
    assert order.phone_masked == "138****5678"
    assert order.lead_status == "active"
    assert order.current_round_status == "active_unfollowed"
    assert order.expires_at is None

    assert db_session.get(ClueCenterOrder, "order-closed") is None
    assert db_session.get(ClueCenterOrder, "0") is None


def test_rebuild_masks_phone_from_raw_payload_when_telephone_column_is_empty(
    db_session: Session,
) -> None:
    clue = _raw_clue(
        "row-1",
        order_id="order-1",
        clue_id="clue-1",
        create_time=_dt(1),
        telephone="",
    )
    clue.raw_payload = {"clue_id": "clue-1", "tel_addr": "13812345678"}
    db_session.add(clue)
    db_session.commit()

    rebuild_clue_center(db_session, now=_dt(2))

    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    assert order.phone_plain == "13812345678"
    assert order.phone_masked == "138****5678"
    assert order.phone_source == "raw_payload"


def test_rebuild_masks_phone_from_encrypted_telephone_resolver(
    db_session: Session,
) -> None:
    clue = _raw_clue(
        "row-1",
        order_id="order-1",
        clue_id="clue-1",
        create_time=_dt(1),
        telephone="",
    )
    clue.enc_telephone = "Enc.phone-1"
    clue.raw_payload = {"clue_id": "clue-1"}
    db_session.add(clue)
    db_session.commit()
    calls: list[list[str]] = []

    def resolver(cipher_texts: list[str]) -> dict[str, str]:
        calls.append(cipher_texts)
        return {"Enc.phone-1": "13812345678"}

    rebuild_clue_center(db_session, now=_dt(2), phone_plain_resolver=resolver)

    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    assert calls == [["Enc.phone-1"]]
    assert order.phone_plain == "13812345678"
    assert order.phone_masked == "138****5678"
    assert order.phone_source == "enc_telephone"


def test_rebuild_keeps_existing_encrypted_phone_mask_without_resolving_again(
    db_session: Session,
) -> None:
    clue = _raw_clue(
        "row-1",
        order_id="order-1",
        clue_id="clue-1",
        create_time=_dt(1),
        telephone="",
    )
    clue.enc_telephone = "Enc.phone-1"
    clue.raw_payload = {"clue_id": "clue-1"}
    db_session.add_all(
        [
            clue,
            ClueCenterOrder(
                order_id="order-1",
                lead_status="active",
                current_round_status="active_unfollowed",
                phone_plain="13812345678",
                phone_masked="138****5678",
                phone_source="enc_telephone",
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
        ]
    )
    db_session.commit()

    def resolver(cipher_texts: list[str]) -> dict[str, str]:
        raise AssertionError(f"resolver should not be called for existing phones: {cipher_texts!r}")

    rebuild_clue_center(db_session, now=_dt(2), phone_plain_resolver=resolver)

    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    assert order.phone_plain == "13812345678"
    assert order.phone_masked == "138****5678"
    assert order.phone_source == "enc_telephone"


def test_rebuild_uses_phone_from_any_source_clue_for_same_order(
    db_session: Session,
) -> None:
    early = _raw_clue(
        "row-early",
        order_id="order-1",
        clue_id="clue-early",
        create_time=_dt(1, 9),
        telephone="",
    )
    early.raw_payload = {"clue_id": "clue-early"}
    late = _raw_clue(
        "row-late",
        order_id="order-1",
        clue_id="clue-late",
        create_time=_dt(1, 12),
        telephone="",
    )
    late.raw_payload = {"clue_id": "clue-late", "tel_addr": "13912345678"}
    db_session.add_all([early, late])
    db_session.commit()

    rebuild_clue_center(db_session, now=_dt(2))

    order = db_session.get(ClueCenterOrder, "order-1")
    assert order is not None
    assert order.canonical_clue_id == "clue-early"
    assert order.phone_plain == "13912345678"
    assert order.phone_masked == "139****5678"
    assert order.phone_source == "raw_payload"


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
            _raw_clue("row-lost", order_id="order-lost", clue_id="clue-lost", create_time=_dt(1)),
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
                assignment_round_id="order-lost-1",
                order_id="order-lost",
                round_no=1,
                assigned_at=_dt(1),
                assigned_at_source="clue_create_time_detail",
                follow_result="lost",
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
    lost = db_session.get(ClueCenterOrder, "order-lost")
    unreachable = db_session.get(ClueCenterOrder, "order-unreachable")
    assert failed is not None
    assert lost is not None
    assert unreachable is not None
    assert failed.current_round_status == "failed_pending_reassign"
    assert failed.lead_status == "pending_reassign"
    assert lost.follow_result == "lost"
    assert lost.current_round_status == "failed_pending_reassign"
    assert lost.lead_status == "pending_reassign"
    assert lost.reassign_reason == "follow_lost"
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


def test_legacy_rebuild_preserves_current_self_owned_projection_while_refreshing_source_data(
    db_session: Session,
) -> None:
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
            _raw_clue(
                "raw-1",
                order_id="order-1",
                clue_id="clue-1",
                create_time=_dt(1),
                store_id="douyin-store",
                store_name="Douyin Store",
            ),
            ClueAssignmentRound(
                assignment_round_id="formal-order-1-1",
                order_id="order-1",
                lead_key="lead-1",
                round_no=1,
                assigned_at=_dt(1),
                assigned_at_source="clue_allocation_engine",
                assigned_store_id="self-owned-store",
                assigned_store_name="Self Owned Store",
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                round_status="active_unfollowed",
                execution_mode="formal",
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
            ClueCenterOrder(
                order_id="order-1",
                lead_status="active",
                current_assignment_round_id="formal-order-1-1",
                current_round_no=1,
                current_round_status="active_unfollowed",
                assigned_at=_dt(1),
                assigned_at_source="clue_allocation_engine",
                assigned_store_id="self-owned-store",
                assigned_store_name="Self Owned Store",
                assigned_city="Self City",
                assigned_province="Self Province",
                phone_plain="13812345678",
                phone_masked="138****5678",
                phone_source="telephone",
                product_id="old-sku",
                product_name="Old Product",
                product_type="Old Type",
                author_nickname="Old Author",
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
        ]
    )
    db_session.commit()

    rebuild_clue_center(db_session, now=_dt(2))

    formal = db_session.get(ClueAssignmentRound, "formal-order-1-1")
    legacy = db_session.get(ClueAssignmentRound, "order-1-1")
    order = db_session.get(ClueCenterOrder, "order-1")
    assert formal is not None
    assert formal.execution_mode == "formal"
    assert formal.assigned_store_id == "self-owned-store"
    assert legacy is not None
    assert legacy.execution_mode == "legacy"
    assert legacy.assigned_store_id == "douyin-store"
    assert order is not None
    assert order.current_assignment_round_id == "formal-order-1-1"
    assert order.assigned_store_id == "self-owned-store"
    assert order.assigned_store_name == "Self Owned Store"
    assert order.assigned_city == "Self City"
    assert order.phone_plain == "13812345678"
    assert order.product_id == "sku-1"
    assert order.product_type == "Car Service"
