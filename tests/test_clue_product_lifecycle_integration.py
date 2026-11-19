"""Exercise the product switch, intake, both schedulers, and the collection API together."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    ClueAssignmentRound, ClueHeadquartersPoolEntry, ClueMasterLead,
    DimSkuProductRule, DimStorePoiMapping, RawDouyinClue,
)
from apps.worker.clue_allocation import materialize_clue_master_leads
from apps.worker.clue_center import refresh_clue_center_projection
from apps.worker.clue_follow_up_state import run_product_follow_up_batch
from apps.worker.formal_allocation_runtime import run_formal_allocation_batch
from test_api_clue_allocation_m3 import client, _login
from test_clue_allocation_engine import _store


PRODUCT = "product-lifecycle"
BATCH = "/api/v1/admin/clue-routing/products/batch"
POOL = "/api/v1/admin/clue-allocation/headquarters-pool"


def configure_stores(session):
    session.add_all([
        DimSkuProductRule(sku_id="sku-lifecycle", product_id=PRODUCT, product_name="试点商品",
                          product_scope="本品"),
        _store("original"), _store("nearby", longitude="121.48"), _store("far", longitude="122.1"),
        DimStorePoiMapping(poi_id="original-poi", store_id="original"),
    ])
    session.commit()


def change_product(client, action, **fields):
    body = {"product_ids": [PRODUCT], "action": action, **fields}
    preview = client.post(BATCH, json={**body, "preview": True})
    assert preview.status_code == 200, preview.text
    item = preview.json()["data"]["results"][0]
    assert item["status"] == "preview"
    if action == "enable":
        body["expected_list_versions"] = {PRODUCT: item["before"]["list_version"]}
    result = client.post(BATCH, json={**body, "preview": False}, headers={"Idempotency-Key": uuid4().hex})
    assert result.status_code == 200, result.text
    assert result.json()["data"]["failed"] == 0, result.json()


def ingest(session, order_id, now, poi="original-poi"):
    raw = RawDouyinClue(clue_row_key=f"row-{order_id}", clue_id=f"clue-{order_id}",
                        order_id=order_id, product_id=PRODUCT, order_status="201",
                        follow_poi_id=poi, create_time_detail=now, fetched_at=now, raw_payload={})
    session.add(raw)
    session.flush()
    materialize_clue_master_leads(session, raw_clues=[raw], now=now)
    refresh_clue_center_projection(session, order_ids={order_id}, now=now)
    session.commit()


def rounds(session, order_id):
    session.expire_all()
    return list(session.scalars(select(ClueAssignmentRound).where(
        ClueAssignmentRound.order_id == order_id, ClueAssignmentRound.execution_mode == "formal",
    ).order_by(ClueAssignmentRound.assigned_at, ClueAssignmentRound.round_no)))


def test_switch_and_expiry_keep_the_original_assignment_contract(client, db_session):
    configure_stores(db_session)
    _login(client)
    start = datetime.now(timezone.utc) - timedelta(days=3)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)

    ingest(db_session, "before-list", start)
    change_product(client, "publish_list", store_ids=["nearby", "far"])
    ingest(db_session, "before-enable", start + timedelta(minutes=1))
    change_product(client, "enable", authorization_note="测试业务负责人已确认适用门店名单")
    ingest(db_session, "enabled", start + timedelta(minutes=2))
    change_product(client, "disable")
    ingest(db_session, "after-disable", start + timedelta(minutes=3))

    first_time = start + timedelta(minutes=4)
    first = run_formal_allocation_batch(factory, now=first_time)
    assert first["assigned"] == 4, first
    for order_id in ("before-list", "before-enable", "after-disable"):
        direct, = rounds(db_session, order_id)
        assert direct.assigned_store_id == "original"
        assert direct.auto_expiry_enabled is False

    initial, = rounds(db_session, "enabled")
    assert (initial.round_no, initial.assigned_store_id) == (1, "nearby")
    old_task = initial.assignment_round_id
    due_at = first_time + timedelta(hours=24, seconds=1)
    run_product_follow_up_batch(factory, now=due_at)
    run_product_follow_up_batch(factory, now=due_at)
    first_round, second_round = rounds(db_session, "enabled")
    assert first_round.closed_at is not None
    assert (second_round.round_no, second_round.assigned_store_id) == (2, "far")
    for order_id in ("before-list", "before-enable", "after-disable"):
        assert len(rounds(db_session, order_id)) == 1

    endpoint = "/api/v1/clues/orders/enabled/follow-up"
    assert client.post(endpoint, json={"assignment_round_id": old_task, "follow_result": "lost"}).status_code == 409
    response = client.post(endpoint, json={
        "assignment_round_id": second_round.assignment_round_id, "follow_result": "request_store_change",
    })
    assert response.status_code == 200, response.text
    db_session.expire_all()
    lead = db_session.scalar(select(ClueMasterLead).where(ClueMasterLead.order_id == "enabled"))
    assert lead.closed_at is not None and lead.current_assignment_round_id is None
    assert len(rounds(db_session, "enabled")) == 2


@pytest.mark.parametrize(("mode", "expected_round", "expected_store"), [
    ("direct", 0, "original"), ("flow", 1, "nearby"),
])
def test_headquarters_resume_after_mapping_repair_creates_one_task(
    client, db_session, mode, expected_round, expected_store,
):
    configure_stores(db_session)
    _login(client)
    if mode == "flow":
        change_product(client, "publish_list", store_ids=["nearby", "far"])
        change_product(client, "enable", authorization_note="测试业务负责人已确认适用门店名单")
    now = datetime.now(timezone.utc)
    ingest(db_session, "missing-anchor", now, poi="repaired-poi")
    inventory = client.get(POOL).json()["data"]["rows"]
    entry, = [row for row in inventory if row["order_id"] == "missing-anchor"]
    assert (entry["routing_product_id"], entry["pending_round_no"], entry["can_resume"]) == (PRODUCT, 0, True)
    assert not rounds(db_session, "missing-anchor")
    db_session.add(DimStorePoiMapping(poi_id="repaired-poi", store_id="original"))
    db_session.flush()
    db_session.commit()

    url = f"{POOL}/{entry['headquarters_pool_entry_id']}/resume"
    resumed = client.post(url)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["data"]["status"] == "assigned"
    assert client.post(url).status_code == 409
    only_round, = rounds(db_session, "missing-anchor")
    assert (only_round.round_no, only_round.assigned_store_id) == (expected_round, expected_store)
    assert db_session.get(ClueHeadquartersPoolEntry, entry["headquarters_pool_entry_id"]).status != "active"
