from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from apps.api.dy_api.models import ClueCenterOrder, ClueMasterLead, RawDouyinClue
from apps.worker.clue_allocation import _bounded_center_order_ids, materialize_clue_master_leads
from apps.worker.clue_center import refresh_clue_center_projection


@pytest.mark.parametrize("raw_status", ["201", "待使用", "履约中", "200", "支付成功"])
def test_incremental_candidates_do_not_drop_supported_raw_statuses(db_session: Session, raw_status: str) -> None:
    db_session.add(RawDouyinClue(clue_row_key="raw", clue_id="clue", order_id="order", order_status=raw_status))
    db_session.commit()
    assert _bounded_center_order_ids(
        db_session, raw_clue_row_keys={"raw"}, clue_ids=set(), order_ids=set(), poi_ids=set()
    ) == ["order"]


@pytest.mark.parametrize("has_available_coupon", [False, True])
def test_paid_clue_materialization_requires_waiting_use_before_projection(
    db_session: Session, has_available_coupon: bool
) -> None:
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    payload = {"certificate": [{"item_status": 400}]} if has_available_coupon else {}
    db_session.add(RawDouyinClue(
        clue_row_key="raw", clue_id="clue", order_id="order", order_status="支付成功",
        create_time_detail=now, modify_time=now, fetched_at=now, raw_payload=payload,
    ))
    db_session.commit()
    materialize_clue_master_leads(db_session, now=now)
    refresh_clue_center_projection(db_session, now=now)
    db_session.commit()
    lead = db_session.query(ClueMasterLead).filter_by(order_id="order").one()
    assert lead.normalized_order_status == ("active" if has_available_coupon else "unknown")
    assert (db_session.get(ClueCenterOrder, "order") is not None) == has_available_coupon

