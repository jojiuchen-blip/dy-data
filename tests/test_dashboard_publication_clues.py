"""Clue overview parity across rounds, dates and live access restrictions."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import event, insert, select, update

from apps.api.dy_api.dashboard_publications import clues
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.api.dy_api.models import ClueAssignmentRound, ClueCenterOrder, ClueMasterLead, DimSkuProductRule, DimStore, DimStoreOrgAssignment
from apps.api.dy_api.routes._data import DashboardDataStore

CUTOFF = datetime(2026, 10, 19, tzinfo=timezone.utc)


def prepare_clues(session):
    """Seed overlapping assignment rounds and a non-formal excluded round."""
    metadata.create_all(session.get_bind())
    session.execute(insert(runs), [{"id": value, "module": "clues", "status": "building", "cutoff": CUTOFF,
                                   "created_at": CUTOFF} for value in ("c1", "c2")])
    session.add(DimSkuProductRule(sku_id="sku", product_id="product", product_scope="精诚养车", product_type="P"))
    session.add_all([DimStore(store_id="A", store_name="Alpha", service_store_code="code-A"),
        DimStore(store_id="B", store_name="Beta", service_store_code="code-B"),
        DimStoreOrgAssignment(service_store_code="code-A", group_name="Group", service_center_name="Center-A", district_name="District", area_name="Area"),
        DimStoreOrgAssignment(service_store_code="code-B", group_name="Group", service_center_name="Center-B", district_name="District", area_name="Area")])
    for number in (1, 2, 3):
        session.add(ClueCenterOrder(order_id=f"o{number}", lead_status="active" if number != 2 else "pending_reassign",
            current_assignment_round_id=f"r{number}", current_round_status="active_followed", product_type="P" if number == 1 else None,
            product_id="product" if number == 1 else None, assigned_store_name="Alpha", assigned_province="Zhejiang", assigned_city="Hangzhou"))
        session.add(ClueAssignmentRound(assignment_round_id=f"r{number}", order_id=f"o{number}", round_no=1,
            assigned_at=datetime(2026, 9, number, 3, tzinfo=timezone.utc), assigned_store_id="A" if number != 3 else "B",
            assigned_store_name="Alpha" if number != 3 else "Beta", round_status="active_followed" if number != 2 else "failed_pending_reassign",
            is_followed=True, is_follow_success=number == 1, is_self_store_verified=number == 1,
            verified_at=CUTOFF if number == 1 else None, execution_mode="formal"))
    session.add(ClueAssignmentRound(assignment_round_id="old", order_id="o1", round_no=2,
        assigned_at=datetime(2026, 9, 4, 3, tzinfo=timezone.utc), assigned_store_id="B", assigned_store_name="Beta",
        round_status="expired_pending_reassign", execution_mode="formal"))
    session.add(ClueAssignmentRound(assignment_round_id="simulation", order_id="o3", round_no=2,
        assigned_at=CUTOFF, assigned_store_id="A", round_status="active_unfollowed", execution_mode="shadow"))
    session.flush()
    assert clues.build(session, "c1", CUTOFF)["row_count"] == 4
    session.commit()


def assert_clue_parity(session):
    """Check SQL order de-duplication against the original overview."""
    old = DashboardDataStore(session)
    cases = [{}, {"scope_store_ids": ["A"]}, {"scope_store_ids": []}, {"organization_store_ids": ["B"]},
        {"assigned_date_start": "2026-09-02", "assigned_date_end": "2026-09-03"},
        {"assigned_date_start": "2026-09-01", "assigned_date_end": "2026-09-01"},
        {"product_type": "jingcheng"}, {"product_type": "byd"}, {"round_status": "expired_pending_reassign"},
        {"verification_status": "self_store_verified"}, {"store_display_status": "待跟进"}, {"q": "Alpha"}]
    for filters in cases:
        assert clues.read(session, "c1", filters, current_headquarters_order_ids=[]) == old.clue_overview(filters)
    assert clues.read(session, "c1", {})["total_clues"] == 3
    assert clues.read(session, "c1", {"scope_store_ids": ["A"]}, current_headquarters_order_ids=["o1"])["total_clues"] == 1
    assert clues.read(session, "c1", {}, visible_product_types=[])["total_clues"] == 0
    with pytest.raises(ValueError, match="current_headquarters"):
        clues.read(session, "c1", {"scope_store_ids": ["A"]})


def test_clue_parity_and_scope(db_session):
    prepare_clues(db_session)
    assert_clue_parity(db_session)


def test_clue_version_and_read_only(db_session, monkeypatch):
    prepare_clues(db_session)
    before = clues.read(db_session, "c1", {})
    db_session.execute(update(ClueAssignmentRound).values(is_followed=False, is_follow_success=False))
    clues.build(db_session, "c2", CUTOFF)
    db_session.commit()
    assert clues.read(db_session, "c1", {}) == before
    assert clues.read(db_session, "c2", {})["follow_rate"] == 0
    monkeypatch.setattr(clues, "build", lambda *args: pytest.fail("read called builder"))
    statements = []
    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        clues.read(db_session, "c1", {})
        options = clues.read_filters(db_session, "c1", ["A"], current_headquarters_order_ids=[])
        assert clues.read_store_options(db_session, "c1", q="be", scope_store_ids=["A"], current_headquarters_order_ids=[])["stores"] == []
        assert clues.read_store_options(db_session, "c1", q="be", selected_store_id="A")["stores"] == [
            {"store_id": "A", "store_name": "Alpha"}, {"store_id": "B", "store_name": "Beta"}]
        assert clues.read_organization_options(db_session, "c1", ["A"], level="area") == [
            {"value": '["Center-A","District","Area"]', "label": "Center-A / District / Area"}]
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)
    assert options["assigned_stores"] == [{"store_id": "A", "store_name": "Alpha"}]
    assert options["assigned_provinces"] == ["Zhejiang"]
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert all("clue_assignment_rounds" not in statement and "clue_center_orders" not in statement for statement in statements)


def test_organization_catalog_is_versioned_but_account_scope_is_current(db_session):
    prepare_clues(db_session)
    key = '["Center-A","District","Area"]'
    assert clues.organization_scope_store_ids(db_session, "c1", level="area", key=key) == ("A",)
    db_session.execute(update(DimStoreOrgAssignment).where(DimStoreOrgAssignment.service_store_code == "code-A").values(service_center_name="Changed"))
    clues.build(db_session, "c2", CUTOFF)
    assert clues.organization_scope_store_ids(db_session, "c1", level="area", key=key) == ("A",)
    assert clues.organization_scope_store_ids(db_session, "c2", level="area", key=key) == ()
    assert clues.organization_scope_store_ids(db_session, "c1", ["B"], level="area", key=key) == ()
    assert clues.read_organization_options(db_session, "c1", [], level="area") == []
    with pytest.raises(ValueError):
        clues.organization_scope_store_ids(db_session, "c1", level="area", key='["Area"]')


def test_current_headquarters_move_revokes_old_publication_immediately(db_session):
    prepare_clues(db_session)
    current_headquarters = select(ClueMasterLead.order_id).where(ClueMasterLead.lifecycle_status == "active",
        ClueMasterLead.pool_location == "headquarters_pool", ClueMasterLead.order_id.is_not(None))
    assert clues.read(db_session, "c1", {"scope_store_ids": ["A"]}, current_headquarters_order_ids=current_headquarters)["total_clues"] == 2
    db_session.add(ClueMasterLead(lead_key="moved", source_clue_row_key="moved", source_identity_key="moved",
        order_id="o1", lifecycle_status="active", pool_location="headquarters_pool"))
    db_session.flush()
    assert clues.read(db_session, "c1", {"scope_store_ids": ["A"]}, current_headquarters_order_ids=current_headquarters)["total_clues"] == 1


def test_clue_freeze_prefers_raw_sku_and_preserves_ambiguous_source_type(db_session):
    from apps.api.dy_api.models import RawDouyinOrder

    prepare_clues(db_session)
    db_session.add_all([
        DimSkuProductRule(sku_id="alternative", product_id="product", product_scope="other", product_type="精诚养车"),
        DimSkuProductRule(sku_id="unique-a", product_id="unique", product_scope="a", product_type="比亚迪本品"),
        DimSkuProductRule(sku_id="unique-b", product_id="unique", product_scope="b", product_type="比亚迪本品"),
        RawDouyinOrder(order_id="o1", sku_id="alternative"),
    ])
    db_session.get(ClueCenterOrder, "o2").product_id = "product"
    db_session.get(ClueCenterOrder, "o2").product_type = "Historical"
    db_session.get(ClueCenterOrder, "o3").product_id = "unique"
    db_session.flush()
    assert clues.build(db_session, "c2", CUTOFF)["row_count"] == 4
    db_session.commit()
    assert clues.read_filters(db_session, "c2")["product_types"] == ["Historical", "比亚迪本品", "精诚养车"]
    for product in ("Historical", "精诚养车", "比亚迪本品"):
        assert clues.read(db_session, "c2", {"product_type": product})["total_clues"] == 1
    assert clues.read(db_session, "c2", {"product_type": "jingcheng"})["total_clues"] == 0
    before = clues.read_filters(db_session, "c2")
    db_session.execute(update(DimSkuProductRule).values(product_type="Changed"))
    db_session.commit()
    assert clues.read_filters(db_session, "c2") == before
    assert clues.read(db_session, "c2", {"product_type": "精诚养车"})["total_clues"] == 1
    assert db_session.get(ClueCenterOrder, "o1").product_type == "P"


@pytest.mark.parametrize("other_type", ["", "unknown", "all", "keep", "Another type"])
def test_clue_shared_product_id_requires_all_candidates_to_have_one_type(db_session, other_type):
    prepare_clues(db_session)
    db_session.get(ClueCenterOrder, "o1").product_type = "Historical"
    db_session.add(DimSkuProductRule(sku_id="ambiguous", product_id="product", product_type=other_type))
    db_session.flush()
    clues.build(db_session, "c2", CUTOFF)
    frozen = db_session.scalar(select(clues.rounds.c.product_type).where(
        clues.rounds.c.publication_id == "c2", clues.rounds.c.assignment_round_id == "r1"))
    assert frozen == "Historical"
