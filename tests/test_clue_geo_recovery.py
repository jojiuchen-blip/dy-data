from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, func

from apps.api.dy_api.models import (
    ClueMasterLead, ClueHeadquartersPoolEntry, RawDouyinClue, DimStore,
    DimStorePoiMapping, ClueAssignmentRound, ClueCenterOrder,
    ClueFollowUpRecord, ClueAllocationAuditLog,
)


T = datetime(2026, 8, 31, 16, tzinfo=timezone.utc)  # Shanghai September 1
NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def seed(s):
    store = DimStore(store_id='shop', store_name='Source shop', longitude=Decimal('121.5'),
                     latitude=Decimal('31.2'), standard_province='上海', standard_city='上海市',
                     city_code='上海', is_active=True, is_douyin_clue_applicable=False,
                     participates_in_clue_allocation=False, location_status='missing')
    raw = RawDouyinClue(clue_row_key='raw', order_id='order', follow_poi_id='poi',
                       follow_life_account_id='shop', create_time_detail=T,
                       order_status='待使用', raw_payload={'telephone': 'private-not-exported'})
    lead = ClueMasterLead(lead_key='lead', source_clue_row_key='raw', source_identity_key='identity',
                         order_id='order', lifecycle_status='active', normalized_order_status='active',
                         pool_location='headquarters_pool', allocation_state='headquarters',
                         first_seen_at=T, anchor_poi_id='poi', anchor_unavailable_reason='follow_poi_unmapped')
    hq = ClueHeadquartersPoolEntry(headquarters_pool_entry_id='hq', lead_key='lead',
                                   status='active', reason='follow_poi_unmapped', entered_at=T)
    s.add_all([store, raw, lead, hq, DimStorePoiMapping(store_id='shop', poi_id='poi', is_primary=True)])
    s.commit()
    return store, raw, lead, hq


def api():
    from apps.worker import clue_geo_recovery
    return clue_geo_recovery


def test_preview_is_read_only_and_apply_restores_source_store_once(db_session):
    s = db_session
    store, raw, lead, hq = seed(s)
    plan = api().preview(s, poi_ids={'poi'}, now=NOW)
    assert len(plan['candidates']) == 1
    assert lead.pool_location == 'headquarters_pool'
    assert s.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    assert 'private-not-exported' not in str(plan)
    result = api().apply_plan(s, plan, actor='test', now=NOW)
    s.commit()
    s.expire_all()
    assert result['restored'] == 1
    assert s.get(ClueMasterLead, 'lead').pool_location == 'store_follow_up_pool'
    center = s.get(ClueCenterOrder, 'order')
    assert center.assigned_store_id == 'shop'
    round_row = s.get(ClueAssignmentRound, center.current_assignment_round_id)
    assert round_row.auto_expiry_enabled is False
    assert round_row.expires_at is None
    assert s.get(ClueHeadquartersPoolEntry, 'hq').status == 'closed'
    assert store.is_douyin_clue_applicable is False
    assert store.participates_in_clue_allocation is False
    assert s.scalar(select(func.count()).select_from(ClueAllocationAuditLog)) == 1
    assert api().apply_plan(s, plan, actor='test', now=NOW)['restored'] == 0


@pytest.mark.parametrize('change', ['old_source', 'old_received', 'other_reason', 'closed',
    'intention_conflict', 'missing_coordinates', 'account_conflict', 'followup', 'history',
    'duplicate_master', 'source_conflict', 'outside_directory', 'prior_assignment_exit'])
def test_excludes_records_outside_explicit_recovery_scope(db_session, change):
    s = db_session
    store, raw, lead, hq = seed(s)
    old = datetime(2026, 8, 31, 15, 59, 59, tzinfo=timezone.utc)
    if change == 'old_source': raw.create_time_detail = old
    if change == 'old_received': lead.first_seen_at = old
    if change == 'other_reason': hq.reason = 'no_eligible_candidate'
    if change == 'closed': lead.lifecycle_status = 'closed_refunded'
    if change == 'intention_conflict': raw.intention_poi_id = 'other'
    if change == 'missing_coordinates': store.latitude = None
    if change == 'account_conflict': raw.follow_life_account_id = 'other'
    if change == 'prior_assignment_exit': hq.source_assignment_round_id = 'earlier'
    if change == 'followup': s.add(ClueFollowUpRecord(follow_up_record_id='f', order_id='order', assignment_round_id='a', round_no=1, follow_result='success'))
    if change == 'history': s.add(ClueAssignmentRound(assignment_round_id='retired', order_id='order', lead_key='lead', round_no=1, round_status='closed_reassigned', terminal_reason='legacy_engine_retired'))
    if change == 'duplicate_master': s.add(ClueMasterLead(lead_key='other', source_clue_row_key='other', source_identity_key='other', order_id='order', lifecycle_status='active'))
    if change == 'source_conflict': s.add(RawDouyinClue(clue_row_key='other', order_id='order', follow_poi_id='other', create_time_detail=T))
    s.commit()
    plan = api().preview(s, poi_ids={'other'} if change == 'outside_directory' else {'poi'}, now=NOW)
    assert plan['candidates'] == []
    assert api().apply_plan(s, plan, actor='test', now=NOW)['restored'] == 0
    assert s.get(ClueHeadquartersPoolEntry, 'hq').status == 'active'


def test_changed_source_between_preview_and_apply_is_skipped(db_session):
    s = db_session
    _, raw, lead, _ = seed(s)
    plan = api().preview(s, poi_ids={'poi'}, now=NOW)
    raw.intention_poi_id = 'new-customer-choice'
    s.commit()
    assert api().apply_plan(s, plan, actor='test', now=NOW)['restored'] == 0
    assert lead.pool_location == 'headquarters_pool'


def test_apply_can_be_rolled_back_atomically(db_session):
    s = db_session
    seed(s)
    plan = api().preview(s, poi_ids={'poi'}, now=NOW)
    api().apply_plan(s, plan, actor='test', now=NOW)
    s.rollback()
    assert s.get(ClueMasterLead, 'lead').pool_location == 'headquarters_pool'
    assert s.scalar(select(func.count()).select_from(ClueAssignmentRound)) == 0
    assert s.scalar(select(func.count()).select_from(ClueAllocationAuditLog)) == 0


@pytest.mark.parametrize('status', ['converted', 'refunded', 'closed'])
def test_terminal_center_is_preserved_even_if_master_is_stale(db_session, status):
    s = db_session
    seed(s)
    s.add(ClueCenterOrder(order_id='order', lead_status=status, current_round_status='closed'))
    s.commit()
    assert api().preview(s, poi_ids={'poi'}, now=NOW)['candidates'] == []


@pytest.mark.parametrize('evidence', ['clue', 'order', 'coupon', 'settlement'])
@pytest.mark.parametrize('after_preview', [False, True])
def test_authoritative_terminal_evidence_blocks_stale_active_projection(db_session, evidence, after_preview):
    from apps.api.dy_api.models import RawDouyinOrder, RawDouyinOrderCoupon, SettlementOrderDetail
    s = db_session
    _, raw, _, _ = seed(s)
    plan = api().preview(s, poi_ids={'poi'}, now=NOW)
    if evidence == 'clue':
        raw.order_status = '已退款'
    elif evidence == 'order':
        s.add(RawDouyinOrder(order_id='order', order_status='已退款', order_status_normalized='refunded'))
    elif evidence == 'coupon':
        s.add(RawDouyinOrderCoupon(coupon_id='coupon', order_id='order', raw_order_id=1, coupon_status_normalized='verified'))
    else:
        s.add(SettlementOrderDetail(coupon_id='coupon', order_id='order', product_type='test', is_verified=True, verify_time=T))
    s.commit()
    if after_preview:
        assert api().apply_plan(s, plan, actor='test', now=NOW)['restored'] == 0
    else:
        assert api().preview(s, poi_ids={'poi'}, now=NOW)['candidates'] == []
    assert s.get(ClueHeadquartersPoolEntry, 'hq').status == 'active'
