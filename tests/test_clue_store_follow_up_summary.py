from __future__ import annotations

import sys
import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import event
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueFollowUpRecord,
    ClueMasterLead,
    DimSkuProductRule,
    DimStore,
    ProductTypeVisibilitySetting,
    RawDouyinOrder,
)
from dy_api.routes._data import DashboardDataStore  # noqa: E402


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _bj(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=SHANGHAI).astimezone(timezone.utc)


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
    product_type: str | None = None,
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
                product_type=product_type,
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


def _manual_follow(session, order_id, store_id, at, *, result="appointment", suffix="manual", deleted_at=None):
    record = ClueFollowUpRecord(
        follow_up_record_id=f"{order_id}-{suffix}", order_id=order_id,
        assignment_round_id=f"{order_id}-round-1", round_no=1,
        assigned_store_id=store_id, follow_result=result,
        created_at=at, deleted_at=deleted_at,
    )
    session.add(record)
    return record


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
    _manual_follow(db_session, "alpha-effective", "store-alpha", _bj(1, 13))
    _manual_follow(db_session, "alpha-action-only", "store-alpha", _bj(2, 13), result="lost")
    db_session.commit()

    store = DashboardDataStore(db_session)
    rows = store.clue_store_follow_up_summary(
        store_ids=("store-zero", "store-bravo", "store-alpha"),
        assigned_date_start="2026-09-01",
        assigned_date_end="2026-09-02",
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
                "assigned_date_start": "2026-09-01",
                "assigned_date_end": "2026-09-02",
            }
        )
        assert row["system_follow_up_rate"] == overview["follow_success_rate"]
        assert row["action_follow_rate"] == overview["follow_rate"]


def test_clue_store_follow_up_summary_ignores_legacy_product_type_visibility(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            DimStore(store_id="store-visible", store_name="Visible Store", is_active=True),
            DimStore(store_id="store-zero", store_name="Zero Store", is_active=True),
            ProductTypeVisibilitySetting(
                setting_key="global",
                enabled=True,
                visible_product_scopes=[],
                visible_product_types=["Visible Product"],
                default_product_type="all",
            ),
        ]
    )
    _add_round(
        db_session,
        order_id="visible-product-round",
        store_id="store-visible",
        store_name="Visible Store",
        assigned_at=_bj(1, 10),
        lead_status="active",
        round_status="active_followed",
        follow_result="appointment",
        is_followed=True,
        is_follow_success=True,
        product_type="Visible Product",
    )
    _add_round(
        db_session,
        order_id="hidden-product-round",
        store_id="store-visible",
        store_name="Visible Store",
        assigned_at=_bj(1, 11),
        lead_status="active",
        round_status="active_unfollowed",
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        product_type="Hidden Product",
    )
    _manual_follow(db_session, "visible-product-round", "store-visible", _bj(1, 11))
    db_session.commit()

    store = DashboardDataStore(db_session)
    filters = {
        "assigned_store_id": "store-visible",
        "assigned_date_start": "2026-09-01",
        "assigned_date_end": "2026-09-01",
    }
    rows = store.clue_store_follow_up_summary(
        store_ids=("store-zero", "store-visible"),
        assigned_date_start=filters["assigned_date_start"],
        assigned_date_end=filters["assigned_date_end"],
    )

    visible, zero = rows
    assert visible["total_count"] == 2
    assert visible["system_follow_up_rate"] == 0.5
    assert visible["action_follow_rate"] == 0.5
    assert visible["system_follow_up_rate"] == store.clue_overview(filters)["follow_success_rate"]
    assert visible["action_follow_rate"] == store.clue_overview(filters)["follow_rate"]
    assert zero["total_count"] == 0

    visibility = db_session.get(ProductTypeVisibilitySetting, "global")
    assert visibility is not None
    visibility.visible_product_types = []
    db_session.commit()

    empty_visibility_rows = store.clue_store_follow_up_summary(
        store_ids=("store-zero", "store-visible"),
        assigned_date_start=filters["assigned_date_start"],
        assigned_date_end=filters["assigned_date_end"],
    )
    assert [row["total_count"] for row in empty_visibility_rows] == [2, 0]
    assert [row["system_follow_up_rate"] for row in empty_visibility_rows] == [0.5, 0]
    assert [row["action_follow_rate"] for row in empty_visibility_rows] == [0.5, 0]


def test_summary_requires_valid_manual_records_and_counts_each_received_task_once(db_session):
    db_session.add(DimStore(store_id="own", store_name="Own Store", is_active=True))
    for order_id in ("projection-only", "real-record", "deleted", "late", "wrong-store"):
        _add_round(db_session, order_id=order_id, store_id="own", store_name="Own Store",
            assigned_at=_bj(1, 10), lead_status="active", round_status="active_unfollowed",
            follow_result="pending", is_followed=order_id != "real-record", is_follow_success=False)
    _manual_follow(db_session, "real-record", "own", _bj(1, 11))
    _manual_follow(db_session, "real-record", "own", _bj(1, 12), suffix="repeat")
    _manual_follow(db_session, "deleted", "own", _bj(1, 11), deleted_at=_bj(1, 12))
    _manual_follow(db_session, "late", "own", _bj(1, 12))
    _manual_follow(db_session, "wrong-store", "elsewhere", _bj(1, 11))
    db_session.flush()
    late = db_session.get(ClueAssignmentRound, "late-round-1")
    late.round_status, late.closed_at = "closed_follow_lost", _bj(1, 11)
    db_session.commit()
    row = DashboardDataStore(db_session).clue_store_follow_up_summary(
        store_ids=("own",), assigned_date_start="2026-09-01", assigned_date_end="2026-09-01")[0]
    assert row["total_count"] == 5
    assert row["pending_count"] + row["followed_count"] + row["other_status_count"] == 5
    assert row["action_followed_count"] == 1
    assert row["action_follow_rate"] == 0.2
    assert row["effective_followed_count"] == 0 and row["system_follow_up_rate"] == 0


def test_summary_matches_records_to_each_task_window_across_store_handoff(db_session):
    db_session.add_all([DimStore(store_id="first", store_name="First", is_active=True),
                        DimStore(store_id="second", store_name="Second", is_active=True)])
    _add_round(db_session, order_id="handoff", store_id="first", store_name="First",
        assigned_at=_bj(1, 10), lead_status="active", round_status="closed_reassigned",
        follow_result="further_follow_up", is_followed=True, is_follow_success=False)
    db_session.add(ClueAssignmentRound(assignment_round_id="handoff-round-2", order_id="handoff",
        round_no=2, assigned_at=_bj(1, 12), assigned_store_id="second", assigned_store_name="Second",
        round_status="active_followed", execution_mode="formal", is_followed=True))
    _manual_follow(db_session, "handoff", "first", _bj(1, 11), result="further_follow_up")
    _manual_follow(db_session, "handoff", "first", _bj(1, 13), suffix="late", result="further_follow_up")
    db_session.add(ClueFollowUpRecord(follow_up_record_id="second-manual", order_id="handoff",
        assignment_round_id="handoff-round-2", round_no=2, assigned_store_id="second",
        follow_result="further_follow_up", created_at=_bj(1, 13)))
    db_session.flush()
    center = db_session.get(ClueCenterOrder, "handoff")
    center.current_assignment_round_id = "handoff-round-2"
    db_session.commit()
    rows = DashboardDataStore(db_session).clue_store_follow_up_summary(
        store_ids=("first", "second"), assigned_date_start="2026-09-01", assigned_date_end="2026-09-01")
    assert [(row["total_count"], row["action_followed_count"]) for row in rows] == [(1, 1), (1, 1)]
    first_record = db_session.get(ClueFollowUpRecord, "handoff-manual")
    first_record.deleted_at = _bj(1, 14)
    db_session.commit()
    first = DashboardDataStore(db_session).clue_store_follow_up_summary(
        store_ids=("first",), assigned_date_start="2026-09-01", assigned_date_end="2026-09-01")[0]
    assert first["action_followed_count"] == 0  # the late old-task record cannot replace it


def test_summary_loads_manual_evidence_in_bounded_batches_instead_of_per_store_or_task(db_session):
    store_ids = tuple(f"batch-{number}" for number in range(8))
    db_session.add_all(DimStore(store_id=key, store_name=key, is_active=True) for key in store_ids)
    for number in range(405):
        key = store_ids[number % len(store_ids)]
        _add_round(db_session, order_id=f"batch-order-{number:04}", store_id=key, store_name=key,
            assigned_at=_bj(1, 10), lead_status="active", round_status="active_unfollowed",
            follow_result="pending", is_followed=False, is_follow_success=False)
        _manual_follow(db_session, f"batch-order-{number:04}", key, _bj(1, 10) + timedelta(minutes=30),
                       result="further_follow_up")
    db_session.commit()
    queries = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM clue_follow_up_records" in statement:
            queries.append((statement, parameters))
    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        rows = DashboardDataStore(db_session).clue_store_follow_up_summary(
            store_ids=store_ids, assigned_date_start="2026-09-01", assigned_date_end="2026-09-01")
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)
    assert sum(row["total_count"] for row in rows) == 405
    assert sum(row["action_followed_count"] for row in rows) == 405
    assert 1 <= len(queries) <= 3
    assert all("WHERE" in sql.upper() and " IN (" in sql.upper() and len(params) <= 500
               for sql, params in queries)


def test_real_summary_and_export_share_authorized_tasks_products_and_headquarters_history(db_session, monkeypatch):
    from fastapi.testclient import TestClient
    from dy_api.auth import get_current_user
    from dy_api.cli_auth import get_current_cli_user
    from dy_api.routes._data import get_data_store
    from test_api_cli_readonly import _auth, _audited_app

    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    db_session.add_all([
        DimStore(store_id="own", store_name="Own Store", is_active=True),
        DimStore(store_id="outside", store_name="Outside Store", is_active=True),
        DimSkuProductRule(sku_id="jc-sku", product_id="jc-product", product_scope="精诚养车", product_type="Catalog JC"),
        DimSkuProductRule(sku_id="byd-sku", product_id="byd-product", product_scope="比亚迪本品", product_type="Catalog BYD"),
    ])
    for order_id, store_id, sku in (("ordinary", "own", "jc-sku"), ("new-hq", "own", "byd-sku"),
                                     ("legacy-hq", "own", "jc-sku"), ("other-scope", "outside", "byd-sku")):
        _add_round(db_session, order_id=order_id, store_id=store_id, store_name=store_id,
            assigned_at=_bj(1, 10), lead_status="active", round_status="active_followed",
            follow_result="appointment", is_followed=True, is_follow_success=True, product_type="Stale Type")
        db_session.add(RawDouyinOrder(order_id=order_id, sku_id=sku))
        _manual_follow(db_session, order_id, store_id, _bj(1, 11))
    for order_id, mode in (("new-hq", "flow"), ("legacy-hq", None)):
        lead = ClueMasterLead(lead_key=order_id, source_clue_row_key=order_id,
            source_identity_key=order_id, order_id=order_id, routing_mode=mode,
            lifecycle_status="active", normalized_order_status="active", pool_location="headquarters_pool",
            allocation_state="headquarters")
        db_session.add(lead)
        db_session.flush()
        row = db_session.get(ClueAssignmentRound, f"{order_id}-round-1")
        row.lead_key, row.round_status, row.closed_at = lead.lead_key, "closed_reassigned", _bj(1, 12)
    db_session.commit()
    store = DashboardDataStore(db_session)
    auth = _auth(store_ids=("own",))
    app = _audited_app()
    app.dependency_overrides[get_current_cli_user] = lambda: auth
    app.dependency_overrides[get_current_user] = lambda: auth
    app.dependency_overrides[get_data_store] = lambda: store
    dates = {"assigned_date_start": "2026-09-01", "assigned_date_end": "2026-09-01"}
    with TestClient(app) as client:
        response = client.get("/api/v1/clues/store-follow-up-summary", params=dates)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert [row["store_id"] for row in data["stores"]] == ["own"]
        assert data["totals"]["total_count"] == data["totals"]["action_followed_count"] == 2
        assert data["totals"]["pending_count"] + data["totals"]["followed_count"] + data["totals"]["other_status_count"] == 2
        assert client.get("/api/v1/clues/store-follow-up-summary", params={**dates, "store_id": "outside"}).status_code == 403
        listed = client.get("/api/v1/clues/assignment-rounds", params=dates)
        assert listed.status_code == 200, listed.text
        listed_rows = listed.json()["data"]["rows"]
        assert {row["order_id"] for row in listed_rows} == {"ordinary", "new-hq"}
        assert sum(row["follow_any_numerator"] for row in listed_rows) == data["totals"]["action_followed_count"]
        exported = client.get("/api/v1/clues/assignment-rounds/export", params=dates)
        assert exported.status_code == 200, exported.text
        records = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        assert {row["order_id"] for row in records} == {"ordinary", "new-hq"}
        assert {row["product_type"] for row in records} == {"Catalog JC", "Catalog BYD"}
        assert len(records) == data["totals"]["total_count"]
        assert all(row["phone_plain"] == "" for row in records)
