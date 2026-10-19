"""Parity and isolation contracts for frozen arbitrary-date ranking reports."""
from datetime import timedelta

import pytest
from sqlalchemy import delete, event, func, select

from apps.api.dy_api.dashboard_publications import ranking
from apps.api.dy_api.dashboard_publications import ranking_schema as frozen
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.api.dy_api.models import ClueAssignmentRound, ClueFollowUpRecord, RawDouyinOrder, RawDouyinVerifyRecord
from apps.api.dy_api.ranking_schema_v1 import eligibility, lead_bindings, metadata as old_metadata, org_history
from apps.api.dy_api.ranking_snapshots import calculate_snapshot, read_snapshot_report
from apps.worker.ranking_preview_fixture import AT, CUTOFF, ELIGIBILITY_VERSION, END, START, seed_preview


def add_publication(session, publication_id="pub", cutoff=CUTOFF):
    session.execute(runs.insert().values(id=publication_id, module="douyin_ranking", status="building",
        cutoff=cutoff, created_at=cutoff, stats_json={}))


@pytest.fixture
def source(db_session):
    old_metadata.create_all(db_session.bind)
    metadata.create_all(db_session.bind)
    seed_preview(db_session)
    db_session.commit()
    return db_session


def freeze(session, publication_id="pub", cutoff=CUTOFF):
    add_publication(session, publication_id, cutoff)
    result = ranking.build(session, publication_id, cutoff)
    session.commit()
    return result


def compare(session, *, start=START, end=END, **filters):
    old_id = "old-" + str(session.scalar(select(func.count()).select_from(runs))) + str(start.timestamp()) + str(filters)
    calculate_snapshot(session, run_id=old_id, period_start=start, period_end=end, observed_through=CUTOFF,
        roster_at=start, eligibility_version=ELIGIBILITY_VERSION, data_mode="business",
        product_scope=filters.get("product_scope", "jingcheng"))
    old = read_snapshot_report(session, run_id=old_id, period_start=start, period_end=end, **filters)
    new = ranking.read_report(session, "pub", period_start=start, period_end=end, **filters)
    for field in ("rows", "totals", "total", "quality_json", "metric_definitions", "eligibility_version"):
        assert new[field] == old[field], (field, new[field], old[field])
    return new


@pytest.mark.parametrize("level", ["store", "area", "district", "service_center", "group"])
@pytest.mark.parametrize("product_scope", ["jingcheng", "byd", "all"])
def test_parity_all_levels_products_multi_coupon_manual_follow(source, level, product_scope):
    freeze(source)
    compare(source, level=level, product_scope=product_scope)


def test_arbitrary_date_selects_earliest_responsibility_inside_window(source):
    source.add(ClueAssignmentRound(assignment_round_id="RA-LATER", order_id="O1", lead_key="LEAD-O1",
        round_no=2, assigned_store_id="A", assigned_at=AT + timedelta(days=3), execution_mode="formal", round_status="active"))
    source.commit()
    freeze(source)
    whole = compare(source, level="store")
    subset = compare(source, start=AT + timedelta(days=3), level="store")
    assert whole["totals"]["verification_numerator"] == 2
    assert subset["totals"]["verification_denominator"] == 1
    assert subset["totals"]["verification_numerator"] == 0


def test_period_start_sales_org_independent_of_first_lead_org_and_conflicts(source):
    from apps.api.dy_api.models import ClueMasterLead

    history = [dict(row) for row in source.execute(select(org_history)).mappings()]
    for row in history:
        row.update(mapping_version="moved", effective_from=AT + timedelta(days=5))
        if row["store_id"] == "A":
            row.update(district_key="new-district", district_name="新大区")
    source.execute(org_history.insert(), history)
    source.add(ClueMasterLead(lead_key="new-lead", source_clue_row_key="new-source", source_identity_key="new-identity", order_id="O1"))
    source.flush()
    source.add_all([
        RawDouyinOrder(order_id="later-sale", sku_id="TEST-JC", owner_account_id="A-store", sale_time=AT + timedelta(days=6)),
        ClueAssignmentRound(assignment_round_id="new-round", lead_key="new-lead", order_id="O1", assigned_store_id="A",
            assigned_at=AT + timedelta(days=6), execution_mode="formal", round_status="active"),
    ])
    source.commit()
    freeze(source)
    broad = compare(source, level="district")
    narrow = compare(source, start=AT + timedelta(days=6), level="district")
    assert broad["quality_json"]["conflicting_responsibility_versions"] == 1
    assert narrow["rows"][0]["name"] == "新大区"
    assert narrow["totals"]["order_count"] == 1


def test_quality_unknown_outside_missing_and_observation(source):
    source.add_all([
        RawDouyinOrder(order_id="unknown", sku_id="TEST-JC", owner_account_id="unknown", sale_time=AT),
        RawDouyinOrder(order_id="outside", sku_id="TEST-JC", owner_account_id="D-store", sale_time=AT),
        ClueAssignmentRound(assignment_round_id="unmapped", order_id="O1", assigned_store_id="missing",
            assigned_at=CUTOFF - timedelta(hours=1), execution_mode="formal", round_status="active"),
    ])
    source.commit()
    freeze(source)
    compare(source, end=CUTOFF + timedelta(days=1), level="store")


@pytest.mark.parametrize("sort_by", ["order_count", "order_average", "follow_24h_rate", "verification_rate"])
@pytest.mark.parametrize("sort_order", ["ASC", "DESC"])
def test_scope_filters_sort_competition_rank_and_pagination(source, sort_by, sort_order):
    freeze(source)
    compare(source, level="store", page=2, page_size=1, sort_by=sort_by, sort_order=sort_order)
    compare(source, level="group", scope_store_ids=("A",))
    compare(source, level="group", scope_store_ids=())
    compare(source, level="store", group_name="does-not-exist")


def test_frozen_read_has_no_source_access_writes_or_builder_and_export_same_id(source, monkeypatch):
    freeze(source)
    original = ranking.read_report(source, "pub", period_start=START, period_end=END, level="store")
    source.execute(delete(ClueFollowUpRecord))
    source.execute(delete(RawDouyinVerifyRecord))
    source.execute(delete(RawDouyinOrder))
    source.execute(delete(org_history))
    source.execute(delete(eligibility))
    source.commit()
    monkeypatch.setattr(ranking, "build", lambda *a, **k: pytest.fail("read invoked builder"))
    statements = []

    def guard(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert statement.lstrip().upper().startswith(("SELECT", "WITH"))
        for forbidden in ("raw_douyin", "clue_assignment_rounds", "clue_follow_up_records", "ranking_store_org_history", "ranking_store_eligibility"):
            assert forbidden not in statement.lower()

    event.listen(source.bind, "before_cursor_execute", guard)
    try:
        assert ranking.read_report(source, "pub", period_start=START, period_end=END, level="store") == original
        levels = ranking.read_levels(source, "pub", period_start=START, period_end=END)
        assert {value["snapshot_id"] for value in levels.values()} == {"pub"}
        assert {value["totals"]["order_count"] for value in levels.values()} == {10}
    finally:
        event.remove(source.bind, "before_cursor_execute", guard)
    assert statements


def test_builder_batches_full_history_without_period_cap_and_never_commits(source, monkeypatch):
    from apps.api.dy_api.dashboard_publications import ranking_build

    monkeypatch.setattr(ranking_build, "BATCH_SIZE", 2)
    monkeypatch.setattr(source, "commit", lambda: pytest.fail("builder committed"))
    add_publication(source)
    stats = ranking.build(source, "pub", CUTOFF)
    assert stats["orders"] == 11
    assert stats["rounds"] == 10
    assert source.scalar(select(func.count()).select_from(frozen.orders)) == 11
    source.rollback()
    assert source.scalar(select(func.count()).select_from(frozen.orders)) == 0
    assert source.scalar(select(func.count()).select_from(frozen.lead_bindings)) == 0


def test_new_lead_binding_survives_publications_and_detects_changed_first_assignment(source):
    freeze(source)
    pinned = source.execute(select(frozen.lead_bindings).where(frozen.lead_bindings.c.lead_key == "LEAD-O1")).mappings().one()
    assert source.scalar(select(func.count()).select_from(lead_bindings)) == 0
    row = source.get(ClueAssignmentRound, "RA1")
    row.assigned_at = AT + timedelta(days=1)
    source.commit()
    freeze(source, "pub2")
    result = ranking.read_report(source, "pub2", period_start=START, period_end=END)
    assert result["quality_json"]["first_assignment_changed_requires_review"] == 1
    again = source.execute(select(frozen.lead_bindings).where(frozen.lead_bindings.c.lead_key == "LEAD-O1")).mappings().one()
    assert dict(again) == dict(pinned)


def test_missing_publication_and_incomplete_roster_reject_explicitly(source):
    with pytest.raises(ValueError, match="尚未生成"):
        ranking.read_report(source, "missing", period_start=START, period_end=END)
    source.execute(org_history.delete().where(org_history.c.store_id == "C"))
    source.commit()
    freeze(source)
    with pytest.raises(ValueError, match="eligible"):
        ranking.read_report(source, "pub", period_start=START, period_end=END)


def test_cancel_and_missing_poi_are_frozen(source):
    from apps.api.dy_api.models import DimStorePoiMapping

    source.execute(delete(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == "TEST-POI-A"))
    source.commit()
    freeze(source)
    result = compare(source, level="store")
    assert result["totals"]["verification_numerator"] == 1


def test_membership_three_sources_and_unlinked_lead_first_round(source):
    from apps.api.dy_api.models import ClueCenterOrder, RawDouyinClue

    source.add_all([
        RawDouyinClue(clue_row_key="raw-only", order_id="raw-only", product_id="TEST-JC"),
        ClueCenterOrder(order_id="center-only", product_id="TEST-JC", lead_status="assigned", current_round_status="active"),
    ])
    for number, order in enumerate(("raw-only", "center-only", "unknown-product")):
        source.add(ClueAssignmentRound(assignment_round_id="membership-" + str(number), order_id=order,
            assigned_store_id="A", assigned_at=AT, execution_mode="formal", round_status="active"))
    source.commit()
    freeze(source)
    for product_scope in ("all", "byd", "jingcheng"):
        compare(source, product_scope=product_scope)


def test_all_history_exceeds_old_50000_row_batch_without_truncation(source):
    source.execute(RawDouyinOrder.__table__.insert(), [dict(order_id="bulk-" + str(number), sku_id="TEST-JC",
        sale_time=AT - timedelta(days=1), owner_account_id="A-store") for number in range(50001)])
    source.commit()
    stats = freeze(source)
    assert stats["orders"] == 50012
    result = ranking.read_report(source, "pub", period_start=START, period_end=END)
    assert result["totals"]["order_count"] == 50011
