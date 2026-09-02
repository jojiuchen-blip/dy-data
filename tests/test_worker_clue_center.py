from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    DimSkuProductRule,
    RawDouyinClue,
    SettlementOrderDetail,
)
from apps.worker.clue_center import mask_phone, refresh_clue_center_projection


def _dt(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=timezone.utc)


def _raw_clue(
    key: str,
    *,
    order_id: str = "order-1",
    clue_id: str = "clue-1",
    telephone: str = "13812345678",
    status: str = "履约中",
) -> RawDouyinClue:
    return RawDouyinClue(
        clue_row_key=key,
        clue_id=clue_id,
        create_time_detail=_dt(1),
        telephone=telephone,
        enc_telephone=None,
        product_id="sku-1",
        product_name="Service Product",
        order_id=order_id,
        order_status=status,
        follow_life_account_id="douyin-store",
        follow_life_account_name="Douyin Store",
        author_nickname="Author",
        raw_payload={"clue_id": clue_id},
        imported_at=_dt(1),
        updated_at=_dt(1),
    )


def _lead(raw: RawDouyinClue, *, current_round_id: str | None = None) -> ClueMasterLead:
    return ClueMasterLead(
        lead_key=f"lead-{raw.clue_row_key}",
        source_clue_row_key=raw.clue_row_key,
        source_identity_key=f"identity-{raw.clue_row_key}",
        canonical_clue_id=raw.clue_id,
        order_id=raw.order_id,
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        pool_location="store_follow_up_pool" if current_round_id else None,
        allocation_state="assigned" if current_round_id else "pending_allocation",
        current_assignment_round_id=current_round_id,
        first_seen_at=_dt(1),
        last_seen_at=_dt(1),
        created_at=_dt(1),
        updated_at=_dt(1),
    )


def test_mask_phone_hides_middle_four_digits() -> None:
    assert mask_phone("13812345678") == "138****5678"
    assert mask_phone("not-a-phone") == ""
    assert mask_phone(None) == ""


def test_projection_materializes_source_fields_without_creating_assignment_round(
    db_session: Session,
) -> None:
    raw = _raw_clue("raw-1")
    db_session.add_all(
        [
            raw,
            _lead(raw),
            DimSkuProductRule(
                sku_id="sku-1",
                product_type="Car Service",
                product_name="Service Product",
                commission_rate=Decimal("0"),
                is_service_product=True,
            ),
        ]
    )
    db_session.commit()

    result = refresh_clue_center_projection(db_session, now=_dt(2))

    assert result == {"eligible_orders": 1, "projected_orders": 1}
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    center = db_session.get(ClueCenterOrder, "order-1")
    assert center is not None
    assert center.current_assignment_round_id is None
    assert center.current_round_no == 0
    assert center.current_round_status == "pending_allocation"
    assert center.assigned_store_id is None
    assert center.phone_plain == "13812345678"
    assert center.phone_masked == "138****5678"
    assert center.product_type == "Car Service"
    assert center.canonical_clue_id == "clue-1"


def test_projection_uses_only_authoritative_formal_assignment(
    db_session: Session,
) -> None:
    raw = _raw_clue("raw-1")
    lead = _lead(raw, current_round_id="formal-round")
    formal_round = ClueAssignmentRound(
        assignment_round_id="formal-round",
        order_id="order-1",
        lead_key=lead.lead_key,
        round_no=2,
        assigned_at=_dt(1),
        assigned_at_source="clue_allocation_engine",
        assigned_store_id="formal-store",
        assigned_store_name="Formal Store",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        round_status="active_unfollowed",
        execution_mode="formal",
        auto_expiry_enabled=False,
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([raw, lead, formal_round])
    db_session.commit()

    refresh_clue_center_projection(db_session, now=_dt(2))

    center = db_session.get(ClueCenterOrder, "order-1")
    assert center is not None
    assert center.current_assignment_round_id == "formal-round"
    assert center.current_round_no == 2
    assert center.assigned_store_id == "formal-store"
    assert center.assigned_store_name == "Formal Store"
    assert center.assigned_store_id != raw.follow_life_account_id
    assert db_session.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 1


def test_projection_never_uses_legacy_round_as_current_assignment(db_session: Session) -> None:
    raw = _raw_clue("raw-1")
    lead = _lead(raw)
    legacy_round = ClueAssignmentRound(
        assignment_round_id="legacy-round",
        order_id="order-1",
        lead_key=lead.lead_key,
        round_no=1,
        assigned_store_id="old-store",
        round_status="active_unfollowed",
        execution_mode="legacy",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    center = ClueCenterOrder(
        order_id="order-1",
        lead_status="active",
        current_assignment_round_id="legacy-round",
        current_round_no=1,
        current_round_status="active_unfollowed",
        assigned_store_id="old-store",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([raw, lead, legacy_round, center])
    db_session.commit()

    refresh_clue_center_projection(db_session, now=_dt(2))

    assert center.current_assignment_round_id is None
    assert center.assigned_store_id is None
    assert center.current_round_status == "pending_allocation"
    assert db_session.get(ClueAssignmentRound, "legacy-round") is legacy_round


def test_projection_does_not_resurrect_stale_formal_center_pointer(
    db_session: Session,
) -> None:
    raw = _raw_clue("raw-1")
    lead = _lead(raw)
    stale_round = ClueAssignmentRound(
        assignment_round_id="stale-formal-round",
        order_id="order-1",
        lead_key=lead.lead_key,
        round_no=1,
        assigned_store_id="old-store",
        round_status="active_unfollowed",
        execution_mode="formal",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    center = ClueCenterOrder(
        order_id="order-1",
        lead_status="active",
        current_assignment_round_id="stale-formal-round",
        current_round_no=1,
        current_round_status="active_unfollowed",
        assigned_store_id="old-store",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([raw, lead, stale_round, center])
    db_session.commit()

    refresh_clue_center_projection(db_session, now=_dt(2))

    assert center.current_assignment_round_id is None
    assert center.assigned_store_id is None
    assert center.current_round_status == "pending_allocation"
    assert stale_round.round_status == "active_unfollowed"


def test_projection_rejects_closed_current_pointer_and_preserves_closed_summary(
    db_session: Session,
) -> None:
    raw = _raw_clue("raw-1")
    lead = _lead(raw, current_round_id="closed-formal-round")
    lead.pool_location = None
    lead.allocation_state = "pending_reassign"
    closed_round = ClueAssignmentRound(
        assignment_round_id="closed-formal-round",
        order_id=raw.order_id,
        lead_key=lead.lead_key,
        round_no=1,
        assigned_at=_dt(1),
        assigned_store_id="old-store",
        follow_result="lost",
        is_followed=True,
        is_follow_success=False,
        round_status="closed_reassigned",
        terminal_reason="follow_lost",
        reassign_reason="follow_lost",
        execution_mode="formal",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([raw, lead, closed_round])
    db_session.commit()

    refresh_clue_center_projection(db_session, now=_dt(2))

    center = db_session.get(ClueCenterOrder, raw.order_id)
    assert center is not None
    assert center.lead_status == "pending_reassign"
    assert center.current_assignment_round_id is None
    assert center.current_round_status == "pending_reassign"
    assert center.assigned_store_id is None
    assert center.follow_result == "lost"
    assert center.is_followed is True
    assert center.is_follow_success is False
    assert center.reassign_reason == "follow_lost"


def test_projection_rejects_current_round_owned_by_another_order(
    db_session: Session,
) -> None:
    raw = _raw_clue("raw-1")
    lead = _lead(raw, current_round_id="wrong-order-round")
    wrong_round = ClueAssignmentRound(
        assignment_round_id="wrong-order-round",
        order_id="another-order",
        lead_key=lead.lead_key,
        round_no=1,
        assigned_store_id="wrong-store",
        round_status="active_unfollowed",
        execution_mode="formal",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([raw, lead, wrong_round])
    db_session.commit()

    refresh_clue_center_projection(db_session, now=_dt(2))

    center = db_session.get(ClueCenterOrder, raw.order_id)
    assert center is not None
    assert center.current_assignment_round_id is None
    assert center.assigned_store_id is None
    assert center.current_round_status == "pending_allocation"


def test_projection_does_not_resurrect_terminal_master(db_session: Session) -> None:
    raw = _raw_clue("raw-terminal", order_id="terminal-order")
    lead = _lead(raw)
    lead.normalized_order_status = "verified"
    lead.lifecycle_status = "closed_verified"
    lead.pool_location = "closed"
    lead.allocation_state = "closed"
    db_session.add_all([raw, lead])
    db_session.commit()

    result = refresh_clue_center_projection(db_session, now=_dt(2))

    assert result == {"eligible_orders": 0, "projected_orders": 0}
    assert db_session.get(ClueCenterOrder, "terminal-order") is None


def test_projection_resolves_encrypted_phone_once(db_session: Session) -> None:
    raw = _raw_clue("raw-1", telephone="")
    raw.enc_telephone = "Enc.phone-1"
    lead = _lead(raw)
    db_session.add_all([raw, lead])
    db_session.commit()
    calls: list[list[str]] = []

    def resolver(values: list[str]) -> dict[str, str]:
        calls.append(values)
        return {"Enc.phone-1": "13912345678"}

    refresh_clue_center_projection(db_session, now=_dt(2), phone_plain_resolver=resolver)

    center = db_session.get(ClueCenterOrder, "order-1")
    assert center is not None
    assert calls == [["Enc.phone-1"]]
    assert center.phone_plain == "13912345678"
    assert center.phone_masked == "139****5678"


def test_projection_includes_paid_clue_and_resolves_encrypted_phone(
    db_session: Session,
) -> None:
    raw = _raw_clue("raw-paid", telephone="", status="支付成功")
    raw.enc_telephone = "Enc.paid-phone"
    lead = _lead(raw)
    db_session.add_all([raw, lead])
    db_session.commit()

    result = refresh_clue_center_projection(
        db_session,
        now=_dt(2),
        phone_plain_resolver=lambda values: {
            value: "13712345678" for value in values
        },
    )

    assert result == {"eligible_orders": 1, "projected_orders": 1}
    center = db_session.get(ClueCenterOrder, raw.order_id)
    assert center is not None
    assert center.lead_status == "pending_allocation"
    assert center.phone_plain == "13712345678"
    assert center.phone_masked == "137****5678"


def test_projection_updates_verification_on_formal_round(db_session: Session) -> None:
    raw = _raw_clue("raw-1")
    lead = _lead(raw, current_round_id="formal-round")
    round_row = ClueAssignmentRound(
        assignment_round_id="formal-round",
        order_id="order-1",
        lead_key=lead.lead_key,
        round_no=1,
        assigned_store_id="store-1",
        follow_result="appointment",
        is_followed=True,
        is_follow_success=True,
        round_status="active_followed",
        execution_mode="formal",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    verification = SettlementOrderDetail(
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
    db_session.add_all([raw, lead, round_row, verification])
    db_session.commit()

    refresh_clue_center_projection(db_session, now=_dt(3))

    center = db_session.get(ClueCenterOrder, "order-1")
    assert center is not None
    assert round_row.is_self_store_verified is True
    assert center.is_self_store_verified is True
    assert center.lead_status == "converted"
