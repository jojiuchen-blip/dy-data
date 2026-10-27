"""Run live verification/phone SQL against a disposable real PostgreSQL schema."""
import csv
import io

from sqlalchemy.orm import Session

from test_clue_projection_postgres import postgres_engine  # noqa: F401
from test_api_clues import _seed_clue_center, _dt
from test_clue_verification_facts import add_verification
from apps.api.dy_api.models import ClueAssignmentRound, RawDouyinClue
from dy_api.routes._data import DashboardDataStore


def test_raw_verification_and_phone_filters_on_postgres(postgres_engine, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    with Session(postgres_engine) as session:
        _seed_clue_center(session)
        row = session.get(ClueAssignmentRound, "order-1-1")
        row.verified_at = row.verified_store_id = None
        row.is_follow_success = row.is_self_store_verified = False
        add_verification(session)
        add_verification(session, order_id="order-2", suffix="cancelled", cancel=_dt(3))
        session.add(RawDouyinClue(clue_row_key="synthetic-phone", order_id="order-1",
            order_status="201", raw_payload={"mobile": "13812345678"}))
        session.add(ClueAssignmentRound(assignment_round_id="repeated", order_id="order-1",
            assigned_at=_dt(1, 11), assigned_store_id="store-1", round_no=2,
            execution_mode="formal", round_status="closed_order_verified",
            created_at=_dt(1), updated_at=_dt(2)))
        session.commit()
        store = DashboardDataStore(session)
        filters = {"verification_status": "self_store_verified", "phone": "13812345678",
            "assigned_date_start": "2026-09-01", "assigned_date_end": "2026-09-07",
            "scope_store_ids": ("store-1",)}
        actor = {"role": "admin", "store_scope_mode": "specified", "store_ids": ["store-1"]}
        result = store.clue_assignment_rounds(filters, actor)
        exported = store.clue_assignment_rounds_export_csv(filters, actor)
        records = list(csv.DictReader(io.StringIO(exported.lstrip("\ufeff"))))
        assert result["pagination"]["total"] == len(records) == 1
        assert result["rows"][0]["verified_store_id"] == "store-1"
        assert result["rows"][0]["is_self_store_verified"] is False
        assert store.clue_assignment_rounds({**filters, "scope_store_ids": ("store-2",)}, actor)["pagination"]["total"] == 0
