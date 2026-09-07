from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    ClueSourceRecordLink,
    RawDouyinClue,
)
from apps.worker.clue_center import refresh_clue_center_projection
from apps.worker.clue_follow_up_state import apply_follow_up_action
from src.dy_data.phones import (
    is_online_cipher,
    mask_phone,
    normalize_phone,
    phone_source_fingerprint,
)


def _dt(day: int) -> datetime:
    return datetime(2026, 9, day, 10, tzinfo=timezone.utc)


def _raw(
    key: str,
    *,
    order_id: str,
    status: str,
    telephone: str = "",
    enc_telephone: str | None = None,
) -> RawDouyinClue:
    return RawDouyinClue(
        clue_row_key=key,
        clue_id=key,
        create_time_detail=_dt(1),
        telephone=telephone,
        enc_telephone=enc_telephone,
        product_id="sku-1",
        product_name="Service",
        order_id=order_id,
        order_status=status,
        raw_payload={"clue_id": key},
        imported_at=_dt(1),
        updated_at=_dt(1),
    )


def _lead(raw: RawDouyinClue) -> ClueMasterLead:
    return ClueMasterLead(
        lead_key=f"lead-{raw.clue_row_key}",
        source_clue_row_key=raw.clue_row_key,
        source_identity_key=f"identity-{raw.clue_row_key}",
        canonical_clue_id=raw.clue_id,
        order_id=raw.order_id,
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        allocation_state="pending_allocation",
        first_seen_at=_dt(1),
        last_seen_at=_dt(1),
        created_at=_dt(1),
        updated_at=_dt(1),
    )


def test_normalize_phone_rejects_cipher_and_arbitrary_digit_text() -> None:
    assert normalize_phone("+86 138-1234-5678") == "13812345678"
    assert normalize_phone("138 1234 5678") == "13812345678"
    assert normalize_phone("Enc.A1B3C8D0E0F0G0H0I0J0K1") == ""
    assert normalize_phone("订单号13812345678") == ""
    assert normalize_phone("138****5678") == ""
    assert mask_phone("+86 138-1234-5678") == "138****5678"
    assert is_online_cipher(" Enc.phone-1 ") is True
    assert is_online_cipher("13812345678") is False


def test_phone_source_fingerprint_is_stable_and_non_reversible() -> None:
    assert phone_source_fingerprint(plain_phone="+86 138-1234-5678") == phone_source_fingerprint(
        plain_phone="13812345678"
    )
    assert phone_source_fingerprint(cipher_text="Enc.phone-1") != phone_source_fingerprint(
        cipher_text="Enc.phone-2"
    )
    assert phone_source_fingerprint(plain_phone="138****5678") is None
    assert phone_source_fingerprint(cipher_text="not-encrypted") is None


def test_projection_uses_alias_source_link_for_terminal_master(
    db_session: Session,
) -> None:
    original = _raw("raw-original", order_id="order-alias", status="履约中")
    lead = _lead(original)
    db_session.add_all([original, lead])
    db_session.commit()
    refresh_clue_center_projection(db_session, now=_dt(2))

    original.order_status = "已核销"
    lead.lifecycle_status = "closed_verified"
    lead.normalized_order_status = "verified"
    lead.pool_location = "closed"
    lead.allocation_state = "closed"
    alias = _raw("raw-alias", order_id="order-alias", status="履约中")
    db_session.add(
        ClueSourceRecordLink(
            source_table="raw_douyin_clues",
            source_record_key=alias.clue_row_key,
            source_clue_id=alias.clue_id,
            source_order_id=alias.order_id,
            lead_key=lead.lead_key,
            order_id=alias.order_id,
            link_status=1,
            link_method=1,
            linked_at=_dt(2),
            created_at=_dt(2),
            updated_at=_dt(2),
        )
    )
    db_session.add(alias)
    db_session.commit()

    refresh_clue_center_projection(db_session, now=_dt(3))

    center = db_session.get(ClueCenterOrder, "order-alias")
    assert center is not None
    assert center.lead_status == "converted"
    assert center.current_round_status == "converted"


def test_projection_invalidates_changed_cipher_and_reuses_same_source(
    db_session: Session,
) -> None:
    raw = _raw(
        "raw-phone",
        order_id="order-phone",
        status="履约中",
        enc_telephone="Enc.phone-1",
    )
    lead = _lead(raw)
    db_session.add_all([raw, lead])
    db_session.commit()
    calls: list[list[str]] = []

    def resolver(values: list[str]) -> dict[str, str]:
        calls.append(values)
        return {"Enc.phone-1": "13912345678", "Enc.phone-2": "13712345678"}

    refresh_clue_center_projection(db_session, now=_dt(2), phone_plain_resolver=resolver)
    center = db_session.get(ClueCenterOrder, "order-phone")
    assert center is not None
    assert center.phone_plain == "13912345678"
    assert center.phone_source_fingerprint == phone_source_fingerprint(cipher_text="Enc.phone-1")
    assert calls == [["Enc.phone-1"]]

    raw.enc_telephone = "Enc.phone-2"
    db_session.commit()
    refresh_clue_center_projection(db_session, now=_dt(3), phone_plain_resolver=resolver)
    assert center.phone_plain == "13712345678"
    assert center.phone_source_fingerprint == phone_source_fingerprint(cipher_text="Enc.phone-2")
    assert calls[-1] == ["Enc.phone-2"]

    refresh_clue_center_projection(db_session, now=_dt(4), phone_plain_resolver=resolver)
    assert len(calls) == 2


def test_projection_does_not_trust_legacy_phone_without_fingerprint(
    db_session: Session,
) -> None:
    raw = _raw(
        "raw-phone-legacy",
        order_id="order-phone-legacy",
        status="履约中",
        enc_telephone="Enc.phone-legacy",
    )
    lead = _lead(raw)
    center = ClueCenterOrder(
        order_id=raw.order_id,
        lead_status="pending_allocation",
        current_round_no=0,
        current_round_status="pending_allocation",
        phone_plain="13912345678",
        phone_masked="139****5678",
        phone_source="enc_telephone",
        phone_source_fingerprint=None,
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([raw, lead, center])
    db_session.commit()
    calls: list[list[str]] = []

    def resolver(values: list[str]) -> dict[str, str]:
        calls.append(values)
        return {"Enc.phone-legacy": "13612345678"}

    refresh_clue_center_projection(db_session, now=_dt(2), phone_plain_resolver=resolver)

    assert calls == [["Enc.phone-legacy"]]
    assert center.phone_plain == "13612345678"
    assert center.phone_source_fingerprint == phone_source_fingerprint(
        cipher_text="Enc.phone-legacy"
    )


def test_projection_refreshes_stale_followup_state_before_writing(
    db_session: Session,
) -> None:
    raw = _raw("raw-stale", order_id="order-stale", status="履约中")
    lead = _lead(raw)
    lead.pool_location = "store_follow_up_pool"
    lead.allocation_state = "assigned"
    lead.current_assignment_round_id = "round-stale"
    round_row = ClueAssignmentRound(
        assignment_round_id="round-stale",
        order_id=raw.order_id,
        lead_key=lead.lead_key,
        round_no=1,
        assigned_at=_dt(1),
        assigned_store_id="store-1",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        round_status="active_unfollowed",
        execution_mode="formal",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    older_round = ClueAssignmentRound(
        assignment_round_id="round-older",
        order_id=raw.order_id,
        lead_key=lead.lead_key,
        round_no=0,
        assigned_at=_dt(1),
        assigned_store_id="store-1",
        follow_result="lost",
        is_followed=True,
        is_follow_success=False,
        round_status="closed_reassigned",
        execution_mode="formal",
        terminal_reason="prior_lost",
        reassign_reason="prior_lost",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    center = ClueCenterOrder(
        order_id=raw.order_id,
        lead_status="active",
        current_assignment_round_id=round_row.assignment_round_id,
        current_round_no=1,
        current_round_status="active_unfollowed",
        assigned_store_id="store-1",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([raw, lead, round_row, older_round, center])
    db_session.commit()

    # Prime this session's identity map with the pre-loss values.
    assert db_session.get(ClueMasterLead, lead.lead_key).current_assignment_round_id == "round-stale"
    assert db_session.get(ClueAssignmentRound, round_row.assignment_round_id).round_status == "active_unfollowed"
    assert db_session.get(ClueAssignmentRound, older_round.assignment_round_id).round_status == "closed_reassigned"
    assert db_session.get(ClueCenterOrder, raw.order_id).current_assignment_round_id == "round-stale"

    other_session = sessionmaker(bind=db_session.get_bind(), future=True)()
    try:
        result = apply_follow_up_action(
            other_session,
            order_id=raw.order_id,
            assignment_round_id=round_row.assignment_round_id,
            follow_result="lost",
            actor={
                "username": "system-admin",
                "role": "admin",
                "auth_type": "env_admin",
                "is_highest_admin": True,
            },
            now=_dt(2),
        )
        assert result.status == "ok"
        other_session.commit()
    finally:
        other_session.close()

    # The projection session still holds the old historical row.  Make the
    # stale status dirty so a later flush would resurrect it without a lock
    # refresh.
    round_row.round_status = "active_followed"
    older_round.round_status = "active_followed"

    refresh_clue_center_projection(db_session, now=_dt(3))
    db_session.commit()

    verification_session = sessionmaker(bind=db_session.get_bind(), future=True)()
    try:
        committed_lead = verification_session.get(ClueMasterLead, lead.lead_key)
        committed_round = verification_session.get(
            ClueAssignmentRound, round_row.assignment_round_id
        )
        committed_center = verification_session.get(ClueCenterOrder, raw.order_id)
        assert committed_lead is not None
        assert committed_round is not None
        assert committed_center is not None
        assert committed_lead.current_assignment_round_id is None
        assert committed_round.round_status == "closed_reassigned"
        committed_older_round = verification_session.get(
            ClueAssignmentRound, older_round.assignment_round_id
        )
        assert committed_older_round is not None
        assert committed_older_round.round_status == "closed_reassigned"
        assert committed_center.current_assignment_round_id is None
        assert committed_center.current_round_status == "pending_reassign"
        assert committed_center.lead_status == "pending_reassign"
    finally:
        verification_session.close()


def test_projection_refreshes_dirty_rows_after_followup_commit(
    db_session: Session,
) -> None:
    raw = _raw("raw-dirty-stale", order_id="order-dirty-stale", status="履约中")
    lead = _lead(raw)
    lead.pool_location = "store_follow_up_pool"
    lead.allocation_state = "assigned"
    lead.current_assignment_round_id = "round-dirty-stale"
    round_row = ClueAssignmentRound(
        assignment_round_id="round-dirty-stale",
        order_id=raw.order_id,
        lead_key=lead.lead_key,
        round_no=1,
        assigned_at=_dt(1),
        assigned_store_id="store-1",
        follow_result="appointment",
        is_followed=True,
        is_follow_success=False,
        round_status="active_followed",
        execution_mode="formal",
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    center = ClueCenterOrder(
        order_id=raw.order_id,
        lead_status="active",
        current_assignment_round_id=round_row.assignment_round_id,
        current_round_no=1,
        current_round_status="active_followed",
        assigned_store_id="store-1",
        follow_result="appointment",
        is_followed=True,
        is_follow_success=False,
        created_at=_dt(1),
        updated_at=_dt(1),
    )
    db_session.add_all([raw, lead, round_row, center])
    db_session.commit()

    # Prime the identity map and make all three rows dirty with abandoned
    # local values before the follow-up writer commits its terminal state.
    assert db_session.get(ClueMasterLead, lead.lead_key) is lead
    assert db_session.get(ClueAssignmentRound, round_row.assignment_round_id) is round_row
    assert db_session.get(ClueCenterOrder, raw.order_id) is center
    lead.allocation_state = "stale-local-state"
    round_row.round_status = "active_unfollowed"
    center.current_round_status = "active_unfollowed"

    other_session = sessionmaker(bind=db_session.get_bind(), future=True)()
    try:
        committed_lead = other_session.get(ClueMasterLead, lead.lead_key)
        committed_round = other_session.get(ClueAssignmentRound, round_row.assignment_round_id)
        committed_center = other_session.get(ClueCenterOrder, raw.order_id)
        assert committed_lead is not None
        assert committed_round is not None
        assert committed_center is not None
        # Keep the master round pointer for this commit so projection must lock
        # and refresh the master, round, and center identity-map entries.
        committed_lead.allocation_state = "pending_reassign"
        committed_round.round_status = "closed_reassigned"
        committed_round.terminal_reason = "follow_lost"
        committed_center.current_assignment_round_id = None
        committed_center.current_round_status = "pending_reassign"
        committed_center.lead_status = "pending_reassign"
        other_session.commit()
    finally:
        other_session.close()

    refresh_clue_center_projection(db_session, now=_dt(3))

    db_session.expire_all()
    assert lead.allocation_state == "pending_reassign"
    assert round_row.round_status == "closed_reassigned"
    assert center.current_assignment_round_id is None
    assert center.current_round_status == "pending_reassign"
    assert center.lead_status == "pending_reassign"


def test_projection_uses_explicitly_flushed_master_state(
    db_session: Session,
) -> None:
    raw = _raw("raw-flushed", order_id="order-flushed", status="履约中")
    lead = _lead(raw)
    db_session.add_all([raw, lead])
    db_session.commit()

    # A caller-owned state change must be flushed before projection.  The
    # projection lock then refreshes the identity map from the committed row.
    lead.allocation_state = "pending_reassign"
    db_session.flush()

    refresh_clue_center_projection(db_session, now=_dt(2))

    center = db_session.get(ClueCenterOrder, raw.order_id)
    assert center is not None
    assert lead.allocation_state == "pending_reassign"
    assert center.lead_status == "pending_reassign"
