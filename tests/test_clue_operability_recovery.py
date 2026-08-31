from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueFollowUpRecord,
    ClueMasterLead,
)
from apps.worker.clue_operability_recovery import parse_args, recover_legacy_batch


def _dt(day: int = 1) -> datetime:
    return datetime(2026, 7, day, 9, tzinfo=timezone.utc)


def _legacy_fixture() -> tuple[ClueMasterLead, ClueAssignmentRound, ClueCenterOrder]:
    lead = ClueMasterLead(
        lead_key="legacy-lead",
        source_clue_row_key="legacy-raw",
        source_identity_key="legacy-identity",
        canonical_clue_id="legacy-clue",
        order_id="legacy-order",
        normalized_order_status="active",
        status_source="test",
        lifecycle_status="active",
        pool_location="store_follow_up_pool",
        allocation_state="assigned",
        current_assignment_round_id="legacy-round",
        first_seen_at=_dt(),
        last_seen_at=_dt(),
        created_at=_dt(),
        updated_at=_dt(),
    )
    round_row = ClueAssignmentRound(
        assignment_round_id="legacy-round",
        order_id="legacy-order",
        lead_key=lead.lead_key,
        round_no=1,
        assigned_at=_dt(),
        assigned_store_id="store-1",
        assigned_store_name="Store 1",
        follow_result="pending",
        round_status="active_unfollowed",
        execution_mode="legacy",
        auto_expiry_enabled=True,
        first_follow_up_sla_hours=24,
        first_sla_expires_at=_dt(2),
        expires_at=_dt(2),
        created_at=_dt(),
        updated_at=_dt(),
    )
    center = ClueCenterOrder(
        order_id="legacy-order",
        lead_status="active",
        current_assignment_round_id=round_row.assignment_round_id,
        current_round_no=1,
        current_round_status="active_unfollowed",
        assigned_store_id="store-1",
        assigned_store_name="Store 1",
        expires_at=_dt(2),
        created_at=_dt(),
        updated_at=_dt(),
    )
    return lead, round_row, center


def test_legacy_preflight_reports_ready_without_mutating(db_session: Session) -> None:
    lead, round_row, center = _legacy_fixture()
    db_session.add_all([lead, round_row, center])
    db_session.commit()

    result = recover_legacy_batch(db_session, dry_run=True)

    assert result["scanned"] == 1
    assert result["ready"] == 1
    assert result.get("blocked", 0) == 0
    assert result["read_only"] is True
    assert round_row.execution_mode == "legacy"
    assert round_row.auto_expiry_enabled is True


def test_legacy_preflight_reports_pointer_and_state_blockers(db_session: Session) -> None:
    lead, round_row, center = _legacy_fixture()
    lead.current_assignment_round_id = None
    lead.order_id = "another-order"
    lead.allocation_state = "pending_allocation"
    center.current_assignment_round_id = None
    db_session.add_all([lead, round_row, center])
    db_session.commit()

    result = recover_legacy_batch(db_session, dry_run=True)

    assert result["blocked"] == 1
    assert result["active_master_pointer_mismatch"] == 1
    assert result["active_master_order_mismatch"] == 1
    assert result["active_master_state_mismatch"] == 1
    assert result["active_center_pointer_mismatch"] == 1
    assert result["samples"]["active_master_pointer_mismatch"] == ["legacy-round"]


def test_legacy_preflight_reports_every_global_migration_guard(db_session: Session) -> None:
    lead, round_row, center = _legacy_fixture()
    duplicate_round = ClueAssignmentRound(
        assignment_round_id="legacy-round-duplicate",
        order_id=round_row.order_id,
        lead_key=lead.lead_key,
        round_no=2,
        assigned_at=_dt(),
        assigned_store_id="store-2",
        round_status="active_unfollowed",
        execution_mode="legacy",
        created_at=_dt(),
        updated_at=_dt(),
    )
    unknown_round = ClueAssignmentRound(
        assignment_round_id="unknown-mode-round",
        order_id="unknown-mode-order",
        round_no=1,
        round_status="closed_reassigned",
        execution_mode="experimental",
        created_at=_dt(),
        updated_at=_dt(),
    )
    dangling_record = ClueFollowUpRecord(
        follow_up_record_id="dangling-follow-record",
        order_id="missing-order",
        assignment_round_id="missing-round",
        round_no=1,
        follow_result="unreachable",
        created_at=_dt(),
    )
    mismatched_record = ClueFollowUpRecord(
        follow_up_record_id="mismatched-follow-record",
        order_id="another-order",
        assignment_round_id=round_row.assignment_round_id,
        round_no=round_row.round_no,
        assigned_store_id=round_row.assigned_store_id,
        follow_result="unreachable",
        created_at=_dt(),
    )
    db_session.add_all(
        [
            lead,
            round_row,
            center,
            duplicate_round,
            unknown_round,
            dangling_record,
            mismatched_record,
        ]
    )
    db_session.commit()

    result = recover_legacy_batch(db_session, dry_run=True)

    assert result["migration_blocked"] is True
    assert result["global_blocked"] == 4
    assert result["samples"]["unknown_execution_mode"] == ["unknown-mode-round"]
    assert result["samples"]["duplicate_active_legacy_round"] == ["legacy-round"]
    assert result["samples"]["inconsistent_follow_up_record"] == [
        "dangling-follow-record",
        "mismatched-follow-record",
    ]
    assert unknown_round.execution_mode == "experimental"
    assert dangling_record.deleted_at is None


def test_legacy_write_recovery_is_disabled(db_session: Session) -> None:
    lead, round_row, center = _legacy_fixture()
    db_session.add_all([lead, round_row, center])
    db_session.commit()

    with pytest.raises(RuntimeError, match="write recovery is retired"):
        recover_legacy_batch(db_session, dry_run=False)

    assert round_row.execution_mode == "legacy"


def test_recovery_cli_has_no_write_or_pending_mode() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--apply"])
    with pytest.raises(SystemExit):
        parse_args(["--mode", "pending"])


def test_new_round_model_defaults_to_formal(db_session: Session) -> None:
    round_row = ClueAssignmentRound(
        assignment_round_id="default-formal",
        order_id="order-default",
        round_no=1,
        round_status="active_unfollowed",
    )
    db_session.add(round_row)
    db_session.flush()

    assert round_row.execution_mode == "formal"
