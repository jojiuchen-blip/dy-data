from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import ClueAssignmentRound, ClueCenterOrder, DimStore  # noqa: E402
from dy_api.routes._data import DashboardDataStore  # noqa: E402


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _bj(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 6, day, hour, 0, tzinfo=SHANGHAI)


def _add_round(
    session: Session,
    *,
    order_id: str,
    store_id: str,
    store_name: str,
    assigned_at: datetime,
    lead_status: str,
    round_status: str,
    follow_result: str,
    is_followed: bool,
    is_follow_success: bool,
) -> None:
    session.add_all(
        [
            ClueCenterOrder(
                order_id=order_id,
                source_clue_ids=[f"clue-{order_id}"],
                source_clue_count=1,
                canonical_clue_id=f"clue-{order_id}",
                lead_status=lead_status,
                current_assignment_round_id=f"{order_id}-round-1",
                current_round_no=1,
                current_round_status=round_status,
                assigned_at=assigned_at,
                assigned_store_id=store_id,
                assigned_store_name=store_name,
                follow_result=follow_result,
                is_followed=is_followed,
                is_follow_success=is_follow_success,
                created_at=assigned_at,
                updated_at=assigned_at,
            ),
            ClueAssignmentRound(
                assignment_round_id=f"{order_id}-round-1",
                order_id=order_id,
                round_no=1,
                assigned_at=assigned_at,
                assigned_store_id=store_id,
                assigned_store_name=store_name,
                follow_result=follow_result,
                is_followed=is_followed,
                is_follow_success=is_follow_success,
                round_status=round_status,
                created_at=assigned_at,
                updated_at=assigned_at,
            ),
        ]
    )


def test_clue_store_follow_up_summary_partitions_rounds_and_matches_overview(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            DimStore(store_id="store-alpha", store_name="Alpha Store", is_active=True),
            DimStore(store_id="store-bravo", store_name="Bravo Store", is_active=True),
            DimStore(store_id="store-zero", store_name="Zero Store", is_active=True),
        ]
    )
    _add_round(
        db_session,
        order_id="alpha-pending-boundary",
        store_id="store-alpha",
        store_name="Alpha Store",
        assigned_at=_bj(1, 0),
        lead_status="active",
        round_status="active_unfollowed",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
    )
    _add_round(
        db_session,
        order_id="alpha-effective",
        store_id="store-alpha",
        store_name="Alpha Store",
        assigned_at=_bj(1, 12),
        lead_status="active",
        round_status="active_followed",
        follow_result="appointment",
        is_followed=True,
        is_follow_success=True,
    )
    _add_round(
        db_session,
        order_id="alpha-action-only",
        store_id="store-alpha",
        store_name="Alpha Store",
        assigned_at=_bj(2, 12),
        lead_status="pending_reassign",
        round_status="failed_pending_reassign",
        follow_result="lost",
        is_followed=True,
        is_follow_success=False,
    )
    _add_round(
        db_session,
        order_id="alpha-other-status",
        store_id="store-alpha",
        store_name="Alpha Store",
        assigned_at=_bj(2, 23),
        lead_status="converted",
        round_status="active_followed",
        follow_result="success",
        is_followed=False,
        is_follow_success=False,
    )
    _add_round(
        db_session,
        order_id="bravo-pending",
        store_id="store-bravo",
        store_name="Bravo Store",
        assigned_at=_bj(2, 8),
        lead_status="active",
        round_status="active_unfollowed",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
    )
    _add_round(
        db_session,
        order_id="alpha-next-day-excluded",
        store_id="store-alpha",
        store_name="Alpha Store",
        assigned_at=_bj(3, 0),
        lead_status="active",
        round_status="active_unfollowed",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
    )
    db_session.commit()

    store = DashboardDataStore(db_session)
    rows = store.clue_store_follow_up_summary(
        store_ids=("store-zero", "store-bravo", "store-alpha"),
        assigned_date_start="2026-06-01",
        assigned_date_end="2026-06-02",
    )

    assert [row["store_id"] for row in rows] == [
        "store-alpha",
        "store-bravo",
        "store-zero",
    ]
    alpha, bravo, zero = rows
    assert alpha == {
        "store_id": "store-alpha",
        "store_name": "Alpha Store",
        "total_count": 4,
        "pending_count": 1,
        "followed_count": 1,
        "other_status_count": 2,
        "action_followed_count": 2,
        "effective_followed_count": 1,
        "system_follow_up_rate": 0.25,
        "action_follow_rate": 0.5,
    }
    assert bravo["total_count"] == 1
    assert bravo["pending_count"] == 1
    assert zero["total_count"] == 0
    assert zero["system_follow_up_rate"] == 0
    assert zero["action_follow_rate"] == 0

    for row in rows:
        assert row["pending_count"] + row["followed_count"] + row["other_status_count"] == row["total_count"]
        assert row["system_follow_up_rate"] == (
            round(row["effective_followed_count"] / row["total_count"], 4)
            if row["total_count"]
            else 0
        )
        assert row["action_follow_rate"] == (
            round(row["action_followed_count"] / row["total_count"], 4)
            if row["total_count"]
            else 0
        )
        overview = store.clue_overview(
            {
                "assigned_store_id": row["store_id"],
                "assigned_date_start": "2026-06-01",
                "assigned_date_end": "2026-06-02",
            }
        )
        assert row["system_follow_up_rate"] == overview["follow_success_rate"]
        assert row["action_follow_rate"] == overview["follow_rate"]
