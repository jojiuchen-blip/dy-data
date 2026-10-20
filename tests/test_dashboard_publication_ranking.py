"""Parity and isolation contracts for frozen arbitrary-date ranking reports."""
from datetime import timedelta

import pytest
from sqlalchemy import delete, event, func, or_, select

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


def seed_membership_cases(session):
    from apps.api.dy_api.models import ClueCenterOrder, DimSkuProductRule, RawDouyinClue

    session.add_all([
        DimSkuProductRule(sku_id="member-sku", product_id="member-product", product_scope="精诚养车"),
        DimSkuProductRule(sku_id="other-sku", product_id="other-product", product_scope="其他"),
        # Membership has no sale-time predicate, unlike the sales projection.
        RawDouyinOrder(order_id="member-order", sku_id="member-sku", sale_time=CUTOFF + timedelta(days=1)),
        RawDouyinOrder(order_id="member-overlap", sku_id="member-sku", sale_time=AT),
        RawDouyinOrder(order_id="member-wrong", sku_id="member-product", sale_time=AT),
        RawDouyinClue(clue_row_key="member-raw", order_id="member-raw", product_id="member-product"),
        RawDouyinClue(clue_row_key="member-raw-duplicate", order_id="member-raw", product_id="member-product"),
        RawDouyinClue(clue_row_key="member-raw-sku", order_id="member-raw-sku", product_id="member-sku"),
        RawDouyinClue(clue_row_key="member-overlap", order_id="member-overlap", product_id="member-product"),
        RawDouyinClue(clue_row_key="member-wrong", order_id="member-wrong", product_id="other-product"),
        RawDouyinClue(clue_row_key="member-null", order_id=None, product_id="member-product"),
        ClueCenterOrder(order_id="member-center", product_id="member-product", lead_status="assigned", current_round_status="active"),
        ClueCenterOrder(order_id="member-overlap", product_id="member-sku", lead_status="assigned", current_round_status="active"),
        ClueCenterOrder(order_id="member-wrong", product_id="other-sku", lead_status="assigned", current_round_status="active"),
    ])
    expected = {"member-order": True, "member-raw": True, "member-raw-sku": True,
        "member-center": True, "member-overlap": True, "member-wrong": False, "member-missing": False}
    for order_id in expected:
        session.add(ClueAssignmentRound(assignment_round_id=order_id, order_id=order_id,
            assigned_store_id="A", assigned_at=AT, execution_mode="formal", round_status="active"))
    session.commit()
    return expected


def old_membership(session, order_ids):
    """Independent old correlated-EXISTS oracle, including current SKU rules."""
    from apps.api.dy_api.models import ClueCenterOrder, DimSkuProductRule, RawDouyinClue

    rules = list(session.scalars(select(DimSkuProductRule).where(DimSkuProductRule.product_scope == "精诚养车")))
    skus = {row.sku_id for row in rules}
    products = skus | {row.product_id for row in rules if row.product_id}
    predicates = [select(model.order_id).where(model.order_id == ClueAssignmentRound.order_id,
        product_column.in_(allowed)).correlate(ClueAssignmentRound).exists()
        for model, product_column, allowed in (
            (RawDouyinOrder, RawDouyinOrder.sku_id, skus),
            (RawDouyinClue, RawDouyinClue.product_id, products),
            (ClueCenterOrder, ClueCenterOrder.product_id, products))]
    return dict(session.execute(select(ClueAssignmentRound.order_id, or_(*predicates)).where(
        ClueAssignmentRound.order_id.in_(order_ids))).all())


def test_membership_current_rules_match_old_exists_across_batches(source, monkeypatch):
    from apps.api.dy_api.dashboard_publications import ranking_build
    from apps.api.dy_api.models import DimSkuProductRule

    expected = seed_membership_cases(source)
    assert old_membership(source, expected) == expected
    monkeypatch.setattr(ranking_build, "BATCH_SIZE", 2)
    freeze(source)
    actual = dict(source.execute(select(frozen.rounds.c.order_id, frozen.rounds.c.is_jingcheng).where(
        frozen.rounds.c.publication_id == "pub", frozen.rounds.c.order_id.in_(expected))).all())
    assert actual == expected
    for product_scope in ("all", "byd", "jingcheng"):
        compare(source, product_scope=product_scope)
    source.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "member-sku")).product_scope = "其他"
    source.commit()
    assert old_membership(source, expected) == dict.fromkeys(expected, False)
    freeze(source, "changed-rules")
    assert not any(source.scalars(select(frozen.rounds.c.is_jingcheng).where(
        frozen.rounds.c.publication_id == "changed-rules", frozen.rounds.c.order_id.in_(expected))))
    assert dict(source.execute(select(frozen.rounds.c.order_id, frozen.rounds.c.is_jingcheng).where(
        frozen.rounds.c.publication_id == "pub", frozen.rounds.c.order_id.in_(expected))).all()) == expected


def test_all_history_exceeds_old_50000_row_batch_without_truncation(source):
    source.execute(RawDouyinOrder.__table__.insert(), [dict(order_id="bulk-" + str(number), sku_id="TEST-JC",
        sale_time=AT - timedelta(days=1), owner_account_id="A-store") for number in range(50001)])
    source.commit()
    stats = freeze(source)
    assert stats["orders"] == 50012
    result = ranking.read_report(source, "pub", period_start=START, period_end=END)
    assert result["totals"]["order_count"] == 50011


def test_filter_choices_use_frozen_shanghai_months_and_cutoff_organization(source):
    from datetime import datetime, timezone

    history = [dict(row) for row in source.execute(select(org_history)).mappings()]
    for row in history:
        row.update(mapping_version="latest", effective_from=AT + timedelta(days=10), district_name="截止时大区")
    source.execute(org_history.insert(), history)
    source.add_all([
        RawDouyinOrder(order_id="month-before", sku_id="TEST-JC", owner_account_id="A-store",
            sale_time=datetime(2025, 12, 31, 15, 59, tzinfo=timezone.utc)),
        RawDouyinOrder(order_id="month-after", sku_id="TEST-JC", owner_account_id="A-store",
            sale_time=datetime(2025, 12, 31, 16, 0, tzinfo=timezone.utc)),
    ])
    source.commit()
    freeze(source)
    expected = ranking.read_filters(source, "pub")
    assert expected["sale_months"] == ["2026-09", "2026-01", "2025-12"]
    assert expected["years"] == [2026, 2025]
    assert expected["district_names"] == ["截止时大区"]
    assert expected["product_scopes"] == ["all", "jingcheng", "byd"]
    assert expected["default_product_type"] == "all"
    assert len(expected["stores"]) == 4
    source.execute(delete(RawDouyinOrder))
    source.execute(delete(org_history))
    source.commit()
    statements = []

    def guard(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert statement.lstrip().upper().startswith("SELECT")
        assert "raw_douyin" not in statement and "ranking_store_org_history" not in statement

    event.listen(source.bind, "before_cursor_execute", guard)
    try:
        assert ranking.read_filters(source, "pub") == expected
        assert ranking.read_filters(source, "pub", scope_store_ids=())["sale_months"] == []
        assert ranking.read_filters(source, "pub", scope_store_ids=())["stores"] == []
        assert len(ranking.read_filters(source, "pub", scope_store_ids=("A",))["stores"]) == 1
        with pytest.raises(ValueError, match="尚未生成"):
            ranking.read_filters(source, "missing")
    finally:
        event.remove(source.bind, "before_cursor_execute", guard)
    assert statements


def test_builder_round_evidence_does_not_trigger_per_round_lazy_sql(source):
    source.expunge_all()

    def reject_lazy_load(state):
        assert not state.is_column_load, "round evidence must be batch loaded, never one SELECT per field per round"

    event.listen(source, "do_orm_execute", reject_lazy_load)
    try:
        add_publication(source)
        ranking.build(source, "pub", CUTOFF)
    finally:
        event.remove(source, "do_orm_execute", reject_lazy_load)


def test_outside_eligibility_quality_is_unique_null_safe_and_matches_old_report(source):
    from apps.api.dy_api.models import DimAwemeAccount

    source.execute(eligibility.insert(), [dict(eligibility_version="older-" + str(number),
        service_store_code="TEST-A", product_scope="精诚养车", effective_from=START - timedelta(days=number + 1),
        source_hash="test") for number in range(3)])
    source.add(DimAwemeAccount(account_id="no-historical-org", store_id="NO-ORG", binding_status="active"))
    source.add_all([
        RawDouyinOrder(order_id="null-owner", sku_id="TEST-JC", owner_account_id=None, sale_time=AT),
        RawDouyinOrder(order_id="unknown-owner", sku_id="TEST-JC", owner_account_id="unknown", sale_time=AT),
        RawDouyinOrder(order_id="missing-org", sku_id="TEST-JC", owner_account_id="no-historical-org", sale_time=AT),
        RawDouyinOrder(order_id="outside", sku_id="TEST-JC", owner_account_id="D-store", sale_time=AT),
    ])
    source.commit()
    freeze(source)
    result = compare(source, level="store")
    assert result["totals"]["order_count"] == 11
    assert result["quality_json"]["orders_outside_eligibility"] == 1
    assert result["quality_json"]["missing_account_binding"] == 2
    assert result["quality_json"]["missing_historical_store_mapping"] == 1


def test_empty_eligibility_remains_explicit_configuration_error(source):
    source.execute(eligibility.delete())
    source.commit()
    freeze(source)
    with pytest.raises(ValueError, match="名单"):
        ranking.read_report(source, "pub", period_start=START, period_end=END)


def test_sales_preaggregation_preserves_null_organization_names_and_counts(source):
    source.execute(org_history.update().values(group_key=None, group_name=None))
    source.commit()
    freeze(source)
    result = compare(source, level="group")
    assert result["total"] == 1
    assert result["rows"][0]["key"] == "unmapped:group"
    assert result["rows"][0]["name"] == "未映射组织"
    assert result["totals"]["order_count"] == 10
