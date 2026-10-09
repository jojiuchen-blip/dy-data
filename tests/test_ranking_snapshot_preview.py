"""User-confirmed ranking policy: responsibility samples, eligibility, history."""
from datetime import datetime, timedelta, timezone
import importlib.util
import pytest
from sqlalchemy import select, func, insert, delete

from apps.api.dy_api.douyin_ranking import build_douyin_ranking_report
from apps.api.dy_api.models import (
    ClueAssignmentRound, DimStore, DimStoreOrgAssignment,
    DimSkuProductRule, RawDouyinOrder, SettlementOrderDetail,
)


def test_assigned_order_verified_elsewhere_is_not_self_verified(db_session):
    at = datetime(2026, 9, 2, tzinfo=timezone.utc)
    db_session.add_all([
        DimStore(store_id="A", store_name="虚拟A", service_store_code="A"),
        DimStoreOrgAssignment(service_store_code="A", district_name="虚拟大区"),
        DimSkuProductRule(sku_id="JC", product_scope="精诚养车"),
        RawDouyinOrder(order_id="O", sku_id="JC", sale_time=at),
        ClueAssignmentRound(assignment_round_id="R", order_id="O", assigned_store_id="A",
                            assigned_at=at, execution_mode="formal", round_status="active"),
        SettlementOrderDetail(coupon_id="C", order_id="O", product_type="保养",
                              is_verified=True, verify_time=at + timedelta(hours=2), verify_store_id="B"),
    ])
    db_session.commit()
    result = build_douyin_ranking_report(db_session, period_start=at,
                                       period_end=at + timedelta(days=2), level="store")
    assert result["totals"]["verification_denominator"] == 1
    assert result["totals"]["verification_numerator"] == 0
    # Any-store verification still receives the established 24h business bonus.
    assert result["totals"]["follow_numerator"] == 1
    assert result["totals"]["follow_any_numerator"] == 1
    assert result["totals"]["follow_action_numerator"] == 0


def test_snapshot_engine_is_available():
    assert importlib.util.find_spec("apps.api.dy_api.ranking_snapshots") is not None


def test_snapshot_early_verified_round_counts_one_of_one_without_follow(preview):
    """The production snapshot path must use the shared verified override."""
    from apps.api.dy_api.models import ClueFollowUpRecord
    from apps.worker.ranking_preview_fixture import AT

    round_row = preview.scalar(select(ClueAssignmentRound).where(
        ClueAssignmentRound.assignment_round_id == "RA1"
    ))
    round_row.verified_store_id = "A"
    round_row.verified_at = AT + timedelta(hours=4)
    round_row.updated_at = AT + timedelta(hours=4)
    preview.execute(delete(ClueFollowUpRecord).where(
        ClueFollowUpRecord.assignment_round_id == "RA1"
    ))
    preview.commit()

    from apps.api.dy_api.ranking_schema_v1 import samples
    calculate(preview)
    sample = preview.execute(select(samples).where(
        samples.c.metric_key == "follow_24h", samples.c.sample_key == "RA1"
    )).mappings().one()
    assert (sample["numerator"], sample["denominator"]) == (1, 1)
    assert sample["evidence_json"]["follow_record_ids"] == []


def test_snapshot_dimension_budget_rejects_incomplete_result(preview, monkeypatch):
    from apps.api.dy_api import ranking_snapshots as engine
    from apps.api.dy_api.ranking_schema_v1 import runs
    monkeypatch.setattr(engine, "MAX_ORG_HISTORY_ROWS", 2)
    with pytest.raises(ValueError, match="数据量"):
        calculate(preview)
    assert preview.scalar(select(func.count()).select_from(runs)) == 0


def test_report_budget_never_returns_partial_ranking(preview, monkeypatch):
    from apps.api.dy_api import ranking_snapshots as engine
    calculate(preview)
    monkeypatch.setattr(engine, "MAX_REPORT_ROWS", 2)
    with pytest.raises(ValueError, match="数据量"):
        report(preview)


@pytest.mark.parametrize("identity_kind", ["uid", "exact_name", "operating", "pending"])
def test_snapshot_uses_real_owner_evidence(preview, identity_kind):
    from apps.api.dy_api.models import RawAwemeBinding
    from apps.api.dy_api.ranking_schema_v1 import samples
    order = preview.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "O1"))
    order.owner_account_id = "RAW-CRAFT" if identity_kind in {"operating", "pending"} else None
    order.owner_douyin_uid = "RAW-UID" if identity_kind == "uid" else None
    order.owner_account_name = "exact merchant name" if identity_kind == "exact_name" else None
    preview.add(RawAwemeBinding(binding_key="RAW-BIND", account_id="RAW-CRAFT",
        douyin_id="RAW-UID", douyin_nickname="exact merchant name", poi_id="TEST-POI-A",
        binding_status="1" if identity_kind == "pending" else "105", raw_payload={}))
    preview.commit()
    calculate(preview)
    sample = preview.execute(select(samples).where(samples.c.metric_key == "order_count",
        samples.c.sample_key == "O1")).mappings().one()
    if identity_kind == "pending":
        assert sample["status"] == "unresolved"
        assert sample["reason_code"] == "invalid_account_binding"
    else:
        assert sample["status"] == "included"
        assert sample["store_id"] == "A"
        assert sample["evidence_json"]["historical_period_unverified"] is True


@pytest.mark.parametrize("level", ["store", "area", "district", "service_center", "group"])
def test_auxiliary_follow_rate_counts_late_once_without_changing_24h(preview, level):
    calculate(preview)
    result = report(preview, level=level)
    assert result["totals"]["follow_rate"] == .4  # 25h follow counts; duplicates/deleted do not
    assert result["totals"]["follow_any_numerator"] == 4
    assert result["totals"]["follow_24h_rate"] == .3
    if level == "store":
        rows = {r["key"]: r for r in result["rows"]}
        assert rows["B"]["follow_rate"] == .25
        assert rows["C"]["follow_rate"] is None


def test_auxiliary_follow_old_snapshot_is_unavailable_not_zero(preview):
    from apps.api.dy_api.ranking_schema_v1 import snapshots
    calculate(preview)
    preview.execute(snapshots.delete().where(snapshots.c.metric_key == "follow_any"))
    preview.commit()
    assert report(preview)["totals"]["follow_rate"] is None


def test_auxiliary_follow_respects_cutoff_and_assignment_store(preview):
    from apps.api.dy_api.models import ClueFollowUpRecord
    from apps.worker.ranking_preview_fixture import AT, CUTOFF
    for fid, store, created in [("future", "B", CUTOFF + timedelta(hours=1)),
                                 ("before", "B", AT - timedelta(hours=1)),
                                 ("wrong-store", "A", AT + timedelta(hours=3))]:
        preview.add(ClueFollowUpRecord(follow_up_record_id=fid, assignment_round_id="RB4",
            order_id="O3", round_no=3, assigned_store_id=store, created_at=created, follow_result="appointment"))
    preview.commit()
    calculate(preview)
    assert report(preview)["totals"]["follow_any_numerator"] == 4


def test_live_reader_auxiliary_follow_counts_after_24h(db_session):
    from apps.api.dy_api.models import ClueFollowUpRecord
    at = datetime(2026, 9, 2, tzinfo=timezone.utc)
    db_session.add_all([
        DimStore(store_id="A", store_name="虚拟A", service_store_code="A"),
        DimStoreOrgAssignment(service_store_code="A", district_name="虚拟大区"),
        DimSkuProductRule(sku_id="JC", product_scope="精诚养车"),
        RawDouyinOrder(order_id="O", sku_id="JC", sale_time=at),
        ClueAssignmentRound(assignment_round_id="R", order_id="O", assigned_store_id="A",
            assigned_at=at, execution_mode="formal", round_status="active"),
        ClueFollowUpRecord(follow_up_record_id="F", assignment_round_id="R", order_id="O",
            assigned_store_id="A", round_no=1, created_at=at + timedelta(hours=25), follow_result="appointment"),
    ])
    db_session.commit()
    totals = build_douyin_ranking_report(db_session, period_start=at,
        period_end=at + timedelta(days=1), level="store")["totals"]
    assert totals["follow_rate"] == 1
    assert totals["follow_24h_rate"] == 0


@pytest.fixture()
def preview(db_session):
    from apps.api.dy_api.ranking_schema_v1 import metadata
    from apps.worker.ranking_preview_fixture import seed_preview
    metadata.create_all(db_session.bind)
    seed_preview(db_session)
    db_session.commit()
    return db_session


def calculate(session, run_id="baseline", **overrides):
    from apps.api.dy_api.ranking_snapshots import calculate_snapshot
    from apps.worker.ranking_preview_fixture import START, END, CUTOFF, ELIGIBILITY_VERSION
    options = dict(run_id=run_id, period_start=START, period_end=END,
                   observed_through=CUTOFF, roster_at=START, eligibility_version=ELIGIBILITY_VERSION)
    options.update(overrides)
    calculate_snapshot(session, **options)
    session.commit()


def report(session, **options):
    from apps.api.dy_api.ranking_snapshots import read_snapshot_report
    from apps.worker.ranking_preview_fixture import START, END
    return read_snapshot_report(session, period_start=START, period_end=END, **options)


@pytest.mark.parametrize("level", ["store", "area", "district", "service_center", "group"])
def test_confirmed_arithmetic_and_zero_sales_eligibility(preview, level):
    calculate(preview)
    result = report(preview, level=level)
    totals = result["totals"]
    assert totals["store_count"] == 3  # D is in Laike but not the eligibility list
    assert totals["order_count"] == 10  # Includes refunded/all-channel/craftsman orders
    assert totals["order_average"] == 3.333333
    assert (totals["follow_numerator"], totals["follow_denominator"], totals["follow_24h_rate"]) == (3, 10, .3)
    assert (totals["verification_numerator"], totals["verification_denominator"], totals["verification_rate"]) == (2, 4, .5)
    if level == "store":
        rows = {row["key"]: row for row in result["rows"]}
        assert rows["A"]["verification_numerator"] == 1
        assert rows["B"]["verification_numerator"] == 1
        assert rows["C"]["order_count"] == 0
        assert rows["C"]["verification_rate"] is None
        assert "D" not in rows


def test_scope_filter_pagination_and_no_global_quality_leak(preview):
    calculate(preview)
    result = report(preview, scope_store_ids=("A",), level="group")
    assert result["totals"]["order_count"] == 4
    assert result["totals"]["store_count"] == 1
    assert result["totals"]["follow_24h_rate"] == 1
    assert result["quality_json"] == {}
    assert report(preview, scope_store_ids=())["total"] == 0
    result = report(preview, level="store", page_size=1, page=2)
    assert len(result["rows"]) == 1 and result["total"] == 3
    assert result["totals"]["order_count"] == 10
    assert report(preview, group_name="does-not-exist")["total"] == 0


def test_period_membership_keeps_three_sources_and_deduplicates_clues(preview):
    from apps.api.dy_api.models import RawDouyinClue, ClueCenterOrder
    from apps.api.dy_api.ranking_schema_v1 import samples
    from apps.worker.ranking_preview_fixture import START, END
    at = START + timedelta(hours=1)
    for order in ('ORDER_ONLY', 'OVERLAP'):
        preview.add(RawDouyinOrder(order_id=order, sku_id='TEST-JC', sale_time=at))
    for index, order in enumerate(('RAW_ONLY', 'OVERLAP', 'OVERLAP', None)):
        preview.add(RawDouyinClue(clue_row_key=f'PRODUCT-{index}', order_id=order, product_id='TEST-JC'))
    for order in ('CENTER_ONLY', 'OVERLAP'):
        preview.add(ClueCenterOrder(order_id=order, product_id='TEST-JC',
            lead_status='assigned', current_round_status='active'))
    for order in ('ORDER_ONLY', 'RAW_ONLY', 'CENTER_ONLY', 'OVERLAP', 'NO_PRODUCT'):
        preview.add(ClueAssignmentRound(assignment_round_id='NEW-'+order, order_id=order,
            assigned_store_id='A', assigned_at=at, execution_mode='formal', round_status='active'))
    preview.add(ClueAssignmentRound(assignment_round_id='OUTSIDE-END', order_id='OVERLAP',
        assigned_store_id='A', assigned_at=END, execution_mode='formal', round_status='active'))
    preview.add(ClueAssignmentRound(assignment_round_id='NOT-FORMAL', order_id='OVERLAP',
        assigned_store_id='A', assigned_at=at, execution_mode='shadow', round_status='active'))
    preview.commit()
    calculate(preview)
    included = set(preview.scalars(select(samples.c.sample_key).where(
        samples.c.metric_key == 'follow_24h', samples.c.sample_key.like('NEW-%'))))
    assert included == {'NEW-ORDER_ONLY', 'NEW-RAW_ONLY', 'NEW-CENTER_ONLY', 'NEW-OVERLAP'}
    assert not preview.scalar(select(func.count()).select_from(samples).where(
        samples.c.sample_key.in_(['OUTSIDE-END', 'NOT-FORMAL'])))


@pytest.mark.parametrize('source_budget', [None, 1])
def test_large_attribution_groups_are_shared_without_losing_evidence(preview, monkeypatch, source_budget):
    from apps.api.dy_api.models import RawAwemeBinding
    from apps.api.dy_api.ranking_schema_v1 import samples
    for number in range(40):
        preview.add(RawAwemeBinding(binding_key=f'SHARED-{number}', account_id=f'SHARED-ID-{number}',
            account_name='shared ambiguous company', poi_id='TEST-POI-A' if number % 2 else 'TEST-POI-B',
            binding_status='2', raw_payload={}))
    for order in preview.scalars(select(RawDouyinOrder).where(RawDouyinOrder.order_id.in_(['O1','O2']))):
        order.owner_account_id = None
        order.owner_douyin_uid = None
        order.owner_account_name = 'shared ambiguous company'
    preview.commit()
    if source_budget is not None:
        from apps.api.dy_api import ranking_snapshots
        from apps.api.dy_api.ranking_schema_v1 import runs
        monkeypatch.setattr(ranking_snapshots, 'MAX_SHARED_SOURCE_BYTES', source_budget)
        with pytest.raises(ValueError, match='归属证据超过'):
            calculate(preview)
        assert preview.scalar(select(func.count()).select_from(runs)) == 0
        return
    calculate(preview)
    facts = list(preview.execute(select(samples).where(samples.c.metric_key=='order_count',
        samples.c.sample_key.in_(['O1','O2']))).mappings())
    assert len(facts) == 2
    assert all(fact['reason_code']=='conflicting_name_binding' for fact in facts)
    assert all(len(fact['evidence_json']['source_identifiers']) <= 16 for fact in facts)
    keys = {fact['evidence_json']['source_group_key'] for fact in facts}
    assert len(keys) == 1
    group = preview.execute(select(samples).where(samples.c.metric_key=='order_attribution_sources',
        samples.c.sample_key==next(iter(keys)))).mappings().one()
    assert group['status']=='excluded' and group['numerator']==group['denominator']==0
    identifiers = group['evidence_json']['source_identifiers']
    assert len(identifiers)==40
    assert all(fact['evidence_json']['source_identifier_count']==40 for fact in facts)
    assert all(fact['evidence_json']['source_identifiers']==identifiers[:16] for fact in facts)
    assert report(preview)['totals']['follow_denominator']==10
    assert report(preview)['totals']['order_count']==8


@pytest.mark.parametrize("level", ["group", "service_center", "district", "area", "store"])
def test_sales_and_store_average_keep_period_start_organization(preview, level):
    from apps.api.dy_api.ranking_schema_v1 import org_history, samples
    from apps.worker.ranking_preview_fixture import START
    history = [dict(row) for row in preview.execute(select(org_history)).mappings()]
    for row in history:
        row.update(mapping_version="moved", effective_from=START + timedelta(days=14))
        if row["store_id"] == "A":
            for field in ("group", "service_center", "district", "area"):
                row[field + "_key"] = "new-" + field
                row[field + "_name"] = "新归属-" + field
    preview.execute(org_history.insert(), history)
    preview.add(RawDouyinOrder(order_id="MOVED-SALE", sku_id="TEST-JC",
        owner_account_id="A-store", sale_time=START + timedelta(days=15)))
    preview.commit()
    calculate(preview)
    fact = preview.execute(select(samples).where(samples.c.sample_key == "MOVED-SALE",
        samples.c.metric_key == "order_count")).mappings().one()
    assert fact["mapping_version"] == "synthetic-org-v1"
    result = report(preview, level=level)
    assert result["totals"]["order_count"] == 11
    assert result["totals"]["store_count"] == 3
    assert result["totals"]["order_average"] == 3.666667
    assert all(row["store_count"] > 0 for row in result["rows"] if row["order_count"])


def test_history_late_evidence_and_idempotent_batches(preview):
    from apps.api.dy_api.ranking_schema_v1 import org_history, samples, runs
    from apps.api.dy_api.models import ClueMasterLead, RawDouyinVerifyRecord
    from apps.worker.ranking_preview_fixture import START, AT
    calculate(preview)
    calculate(preview)
    assert preview.scalar(select(func.count()).select_from(runs)) == 1
    original = report(preview, run_id="baseline")
    history = [dict(row) for row in preview.execute(select(org_history)).mappings()]
    for row in history:
        row.update(mapping_version="v2", effective_from=START + timedelta(days=14))
        if row["store_id"] == "A":
            row.update(district_key="NEW-D", district_name="虚拟新大区")
    preview.execute(org_history.insert(), history)
    preview.add(ClueMasterLead(lead_key="NEW-LEAD", source_clue_row_key="NEW-RAW",
                              source_identity_key="NEW-IDENTITY", order_id="O4"))
    preview.flush()
    preview.add(ClueAssignmentRound(assignment_round_id="NEW-R", lead_key="NEW-LEAD", order_id="O4",
        assigned_at=START + timedelta(days=15), assigned_store_id="A", round_no=1,
        execution_mode="formal", round_status="active"))
    # A late self-verification for the old O2 sample must stay with old organization.
    preview.add(RawDouyinVerifyRecord(verify_id="LATE-V", coupon_id="C2", poi_id="TEST-POI-A",
        verify_status="success", verify_time=START + timedelta(days=19), sku_id="TEST-JC"))
    preview.commit()
    calculate(preview, "updated")
    facts = {row["sample_key"]: row for row in preview.execute(select(samples).where(
        samples.c.run_id == "updated", samples.c.metric_key == "follow_24h")).mappings()}
    assert facts["RA2"]["mapping_version"] == "synthetic-org-v1"
    assert facts["NEW-R"]["mapping_version"] == "v2"
    assert report(preview, run_id="baseline")["totals"] == original["totals"]
    assert report(preview, run_id="updated")["totals"]["verification_numerator"] == 3
    with pytest.raises(ValueError, match="another configuration"):
        calculate(preview, "baseline", roster_at=AT)


def test_unmapped_and_outside_eligibility_orders_are_audited(preview):
    from apps.worker.ranking_preview_fixture import AT
    preview.add_all([
        RawDouyinOrder(order_id="UNKNOWN", sku_id="TEST-JC", owner_account_id="unknown", sale_time=AT),
        RawDouyinOrder(order_id="OUTSIDE", sku_id="TEST-JC", owner_account_id="D-store", sale_time=AT),
    ])
    preview.commit()
    calculate(preview)
    result = report(preview)
    assert result["totals"]["order_count"] == 11
    assert result["totals"]["store_count"] == 3
    assert result["quality_json"]["missing_account_binding"] == 1
    assert result["quality_json"]["orders_outside_eligibility"] == 1


def test_no_snapshot_and_future_eligibility_fail_explicitly(preview):
    from apps.worker.ranking_preview_fixture import START
    with pytest.raises(ValueError, match="尚未生成"):
        report(preview)
    with pytest.raises(ValueError, match="eligibility"):
        calculate(preview, eligibility_version="missing")
    with pytest.raises(ValueError, match="no mapping"):
        calculate(preview, roster_at=START - timedelta(days=1))


def test_raw_numeric_verification_status_preserves_self_store_and_cancellation(preview):
    from apps.api.dy_api.models import RawDouyinVerifyRecord
    for row in preview.scalars(select(RawDouyinVerifyRecord)):
        row.verify_status = "2" if row.cancel_time else "1"
    preview.commit()
    calculate(preview)
    assert report(preview)["totals"]["verification_numerator"] == 2
    assert report(preview)["totals"]["verification_denominator"] == 4


def test_business_reader_never_returns_synthetic_snapshots(preview):
    calculate(preview)
    with pytest.raises(ValueError, match="尚未生成"):
        report(preview, data_mode="business")


def test_period_query_keeps_old_assigned_order_without_loading_all_sales(preview):
    from sqlalchemy import event
    from apps.worker.ranking_preview_fixture import START
    order = preview.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "O1"))
    order.sale_time = order.pay_time = START - timedelta(days=100)
    preview.commit()
    loaded = []
    def capture(session, obj):
        if isinstance(obj, RawDouyinOrder):
            loaded.append(obj.order_id)
    preview.expunge_all()
    event.listen(preview, "loaded_as_persistent", capture)
    try:
        calculate(preview)
    finally:
        event.remove(preview, "loaded_as_persistent", capture)
    assert "O1" not in loaded
    totals = report(preview)["totals"]
    assert totals["order_count"] == 9
    assert totals["follow_denominator"] == 10
    assert totals["verification_denominator"] == 4


@pytest.mark.parametrize("level", ["store", "area", "district", "service_center", "group"])
def test_three_follow_denominators_are_independent_in_snapshot_and_live(preview, level):
    from apps.api.dy_api.models import ClueFollowUpRecord, RawDouyinRefundRecord
    from apps.worker.ranking_preview_fixture import AT, START, END

    # Seven O3 rounds: only its 25h manual follow precedes the late refund.
    # Extra early-refunded round has a post-terminal lost/unreachable action.
    preview.add(RawDouyinOrder(order_id="EARLY", sku_id="TEST-JC", sale_time=AT,
                               order_status="已支付", owner_account_id="B-store"))
    preview.add(ClueAssignmentRound(assignment_round_id="EARLY-R", order_id="EARLY",
        assigned_store_id="B", assigned_at=AT, execution_mode="formal", round_status="closed"))
    for oid, hours in [("O3", 30), ("EARLY", 4)]:
        at = AT + timedelta(hours=hours)
        preview.add(RawDouyinRefundRecord(source_record_key="RF-" + oid, order_id=oid,
            refund_id="RF-" + oid, normalized_refund_status=2, raw_refund_status="50",
            refund_completed_at=at, source_observed_at=at, payload_hash=oid,
            raw_payload={"refund_type": "2", "refund_completed_at": at.isoformat()}))
    preview.add(ClueFollowUpRecord(follow_up_record_id="POST-TERMINAL", order_id="EARLY",
        assignment_round_id="EARLY-R", assigned_store_id="B", round_no=1,
        created_at=AT + timedelta(hours=5), follow_result="lost"))
    preview.commit()
    calculate(preview)
    totals = report(preview, level=level)["totals"]
    assert (totals["follow_numerator"], totals["follow_denominator"], totals["follow_24h_rate"]) == (3, 10, .3)
    assert (totals["follow_any_numerator"], totals["follow_any_denominator"], totals["follow_rate"]) == (4, 4, 1)
    assert (totals["follow_action_numerator"], totals["follow_action_denominator"], totals["follow_action_rate"]) == (5, 11, .454545)
    live = build_douyin_ranking_report(preview, period_start=START, period_end=END, level=level)["totals"]
    for key in ["follow_numerator", "follow_denominator", "follow_24h_rate", "follow_any_numerator",
                "follow_any_denominator", "follow_rate", "follow_action_numerator",
                "follow_action_denominator", "follow_action_rate"]:
        assert live[key] == totals[key], key


def test_manual_action_counts_unreachable_and_lost_results(preview):
    from apps.api.dy_api.models import ClueFollowUpRecord
    from apps.worker.ranking_preview_fixture import AT
    from apps.api.dy_api.ranking_schema_v1 import samples
    for rid, result in [("RB4", "unreachable"), ("RB5", "lost")]:
        preview.add(ClueFollowUpRecord(follow_up_record_id=result, assignment_round_id=rid,
            order_id="O3", assigned_store_id="B", round_no=1, follow_result=result,
            created_at=AT + timedelta(hours=50)))
    preview.commit()
    calculate(preview)
    rows = preview.execute(select(samples).where(samples.c.metric_key == "follow_action",
        samples.c.sample_key.in_(["RB4", "RB5"]))).mappings().all()
    assert len(rows) == 2
    assert all((row["numerator"], row["denominator"]) == (1, 1) for row in rows)
