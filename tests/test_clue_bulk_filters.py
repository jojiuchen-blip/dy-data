"""Real HTTP and database regressions for bounded clue-store selections."""
import csv
import io

import pytest
from sqlalchemy import event

from apps.api.dy_api.clue_store_filters import parse_store_identifiers, resolve_store_identifiers
from apps.api.dy_api.models import ClueAssignmentRound, ClueFollowUpRecord, DimAwemeAccount, DimStore, DimStorePoiMapping, RawAwemeBinding
from test_api_clues import client, _seed_clue_center, _seed_store_two_clue  # noqa: F401
from dy_api.auth import AuthContext, get_current_user
from test_api_clues import _dt


@pytest.fixture()
def bulk_client(client, db_session):
    _seed_clue_center(db_session)
    _seed_store_two_clue(db_session)
    db_session.add_all([
        DimStore(store_id="store-3", store_name="隐藏门店"),
        DimAwemeAccount(account_id="00000000000000000123", store_id="store-1"),
        DimAwemeAccount(account_id="222", store_id="store-1"),
        DimAwemeAccount(account_id="hidden-account", store_id="store-3"),
        DimStorePoiMapping(store_id="store-1", poi_id="111"),
        DimStorePoiMapping(store_id="store-1", poi_id="112"),
        DimStorePoiMapping(store_id="store-2", poi_id="222"),
        RawAwemeBinding(binding_key="old", account_id="historical-only", poi_id="111"),
    ])
    db_session.commit()
    actor = AuthContext(user_id="bulk-admin", username="bulk-admin", display_name="批量测试", role="admin",
                        auth_type="user", store_scope_mode="specified", store_ids=("store-1", "store-2"), page_keys=("A02",))
    client.app.dependency_overrides[get_current_user] = lambda: actor
    return client, actor


def test_resolver_exact_namespaces_normalization_union_and_privacy(bulk_client):
    client, _actor = bulk_client
    response = client.post("/api/v1/clues/filter-options/stores/resolve", json={
        "raw_input": "０００００００００００００００００１２３　；111/112\n222\t222；hidden-account / missing / store-1 / historical-only",
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["input_count"] == 9
    assert data["duplicate_count"] == 1
    assert data["matched_identifier_count"] == 4
    assert data["matched_store_count"] == 2
    assert data["unmatched_identifiers"] == ["hidden-account", "missing", "store-1", "historical-only"]
    stores = {row["store_id"]: row for row in data["stores"]}
    assert {m["identifier"] for m in stores["store-1"]["matches"]} == {"00000000000000000123", "111", "112", "222"}
    assert next(m for m in stores["store-1"]["matches"] if m["identifier"] == "222")["sources"] == ["account"]
    assert stores["store-2"]["matches"] == [{"identifier": "222", "sources": ["poi"]}]
    assert "隐藏门店" not in response.text


@pytest.mark.parametrize("selection", [None, [], ["store-1"], ["store-1", "store-2"], ["store-3"]])
def test_post_list_total_pages_and_full_export_share_scope(bulk_client, selection):
    client, _actor = bulk_client
    filters = {"assigned_store_ids": selection, "product_type": "all"}
    response = client.post("/api/v1/clues/assignment-rounds", json={"filters": filters, "page_size": 1})
    assert response.status_code == 200
    data = response.json()["data"]
    rows = list(data["rows"])
    for page in range(2, data["pagination"]["total_pages"] + 1):
        rows.extend(client.post("/api/v1/clues/assignment-rounds", json={"filters": filters, "page_size": 1, "page": page}).json()["data"]["rows"])
    exported = client.post("/api/v1/clues/assignment-rounds/export", json={"filters": filters})
    assert exported.status_code == 200
    csv_rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert [row["assignment_round_id"] for row in rows] == [row["assignment_round_id"] for row in csv_rows]
    assert data["pagination"]["total"] == len(csv_rows)
    assert all(row["assigned_store_id"] in {"store-1", "store-2"} for row in csv_rows)
    if selection in ([], ["store-3"]):
        assert rows == []


def test_dates_status_verification_and_permission_rechecked(bulk_client):
    client, actor = bulk_client
    filters = {"assigned_store_ids": ["store-1", "store-2"], "assigned_date_start": "2099-01-01", "verification_status": "self_store_verified"}
    assert client.post("/api/v1/clues/assignment-rounds", json={"filters": filters}).json()["data"]["pagination"]["total"] == 0
    narrowed = AuthContext(user_id=actor.user_id, username=actor.username, display_name=actor.display_name, role="admin",
                          auth_type="user", store_scope_mode="specified", store_ids=(), page_keys=("A02",))
    client.app.dependency_overrides[get_current_user] = lambda: narrowed
    assert client.post("/api/v1/clues/assignment-rounds", json={"filters": {"assigned_store_ids": ["store-1"]}}).json()["data"]["rows"] == []
    assert client.post("/api/v1/clues/filter-options/stores/resolve", json={"raw_input": "111"}).json()["data"]["unmatched_identifiers"] == ["111"]


@pytest.mark.parametrize("payload", [
    {"filters": {"scope_store_ids": ["store-3"]}},
    {"filters": {"organization_store_ids": ["store-3"]}},
    {"filters": {"assigned_store_ids": [123]}},
    {"filters": {"assigned_store_ids": ["x"] * 1001}},
    {"filters": {"assigned_store_ids": ["x" * 129]}},
])
def test_query_rejects_untrusted_scope_and_invalid_capacity(bulk_client, payload):
    client, _actor = bulk_client
    assert client.post("/api/v1/clues/assignment-rounds", json=payload).status_code == 422
    assert client.post("/api/v1/clues/assignment-rounds/export", json=payload).status_code == 422


def test_resolver_rejects_limits_without_truncating(bulk_client):
    client, _actor = bulk_client
    for raw in ("x" * 129, " ".join(str(i) for i in range(1001)), " " * 128001):
        assert client.post("/api/v1/clues/filter-options/stores/resolve", json={"raw_input": raw}).status_code == 422
    assert parse_store_identifiers("；／　\n\t") == ([], 0)
    assert parse_store_identifiers("0/00/000") == (["0", "00", "000"], 3)


def test_1000_ids_resolve_in_bounded_queries_and_travel_as_json(bulk_client, db_session):
    client, _actor = bulk_client
    ids = [str(10**18 + i) for i in range(1000)]
    db_session.add_all([DimAwemeAccount(account_id=identifier, store_id="store-1") for identifier in ids])
    db_session.commit()
    queries = []
    def record(_conn, _cursor, statement, _params, _context, _many):
        queries.append(statement)
    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        data = resolve_store_identifiers(db_session, "\n".join(ids), ("store-1",))
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)
    assert data["matched_identifier_count"] == 1000
    assert data["matched_store_count"] == 1
    assert len(queries) == 6
    resolved = client.post("/api/v1/clues/filter-options/stores/resolve", json={"raw_input": "\n".join(ids)})
    assert resolved.status_code == 200
    assert resolved.json()["data"]["matched_identifier_count"] == 1000
    response = client.post("/api/v1/clues/assignment-rounds", json={"filters": {"assigned_store_ids": ids}})
    assert response.status_code == 200
    assert response.json()["data"]["rows"] == []
    assert len(str(response.request.url)) < 100
    exported = client.post("/api/v1/clues/assignment-rounds/export", json={"filters": {"assigned_store_ids": ids}})
    assert exported.status_code == 200
    assert list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")))) == []


def test_resolver_expansion_over_1000_rejects_entire_batch(bulk_client, db_session):
    client, _actor = bulk_client
    for i in range(501):
        db_session.add_all([DimStore(store_id=f"left-{i}", store_name="L"), DimStore(store_id=f"right-{i}", store_name="R")])
        db_session.flush()
        db_session.add_all([DimAwemeAccount(account_id=f"dual-{i}", store_id=f"left-{i}"),
                            DimStorePoiMapping(poi_id=f"dual-{i}", store_id=f"right-{i}")])
    db_session.commit()
    with pytest.raises(ValueError, match="1000"):
        resolve_store_identifiers(db_session, " ".join(f"dual-{i}" for i in range(501)), None)


def test_deleted_history_is_visible_only_in_current_admin_store_scope(bulk_client, db_session):
    client, actor = bulk_client
    db_session.add(ClueAssignmentRound(assignment_round_id="outside-history-round", order_id="order-2", round_no=2,
        assigned_store_id="store-2", assigned_at=_dt(1), execution_mode="formal", round_status="closed_reassigned"))
    db_session.flush()
    for suffix, round_id, store_id in (("inside", "order-2-1", "store-1"), ("outside", "outside-history-round", "store-2")):
        # Both records belong to one visible order; the outside record points to
        # another store's authoritative round and must not leak through that order.
        db_session.add(ClueFollowUpRecord(follow_up_record_id=suffix, order_id="order-2",
            assignment_round_id=round_id, round_no=1, assigned_store_id=store_id,
            follow_result="unreachable", deleted_at=_dt(2), created_at=_dt(1)))
    db_session.commit()
    narrowed = AuthContext(user_id=actor.user_id, username=actor.username, display_name=actor.display_name, role="admin",
                          auth_type="user", store_scope_mode="specified", store_ids=("store-1",), page_keys=("A02",))
    client.app.dependency_overrides[get_current_user] = lambda: narrowed
    response = client.get("/api/v1/clues/orders/order-2")
    assert response.status_code == 200
    ids = {record["follow_up_record_id"] for record in response.json()["data"]["follow_up_records"]}
    assert "inside" in ids
    assert "outside" not in ids
    for record in ("outside", "missing"):
        assert client.delete(f"/api/v1/clues/follow-up-records/{record}").status_code == 404
