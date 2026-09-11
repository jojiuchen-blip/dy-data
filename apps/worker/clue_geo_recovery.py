"""Explicit, previewed recovery of September leads stranded by missing store data.

This is an operator tool, never a scheduled allocation strategy. It preserves
the source POI assignment and does not change store/product eligibility.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationAuditLog, ClueAssignmentRound, ClueCenterOrder,
    ClueFollowUpRecord, ClueHeadquartersPoolEntry, ClueMasterLead,
    DimStore, DimStorePoiMapping, RawDouyinClue, RawDouyinOrder, utcnow,
)
from apps.worker.clue_allocation import _coupon_statuses_by_order, _verified_at_by_order, _resolve_status
from apps.worker.clue_headquarters_pool import canonical_headquarters_pool_reason

# An incident-specific lower bound; callers cannot expand recovery into August.
SINCE = datetime(2026, 8, 31, 16, tzinfo=timezone.utc)
VERSION = 'store-geo-recovery-september-v1'
MAX_BATCH = 100


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _in_window(value, until):
    return value is not None and SINCE <= _aware(value) <= until


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _inspect(session, lead, poi_ids, until):
    """Read only business evidence needed for one candidate; never export PII."""
    if (lead.lifecycle_status != 'active' or lead.normalized_order_status != 'active'
            or lead.pool_location != 'headquarters_pool' or lead.allocation_state != 'headquarters'
            or lead.current_assignment_round_id or lead.closed_at or lead.ended_without_assignment
            or not lead.order_id or lead.master_kind != 1):
        return None, 'not_unassigned_active_headquarters'
    if not _in_window(lead.first_seen_at, until):
        return None, 'outside_received_window'
    entries = list(session.scalars(select(ClueHeadquartersPoolEntry).where(
        ClueHeadquartersPoolEntry.lead_key == lead.lead_key,
        ClueHeadquartersPoolEntry.status == 'active')).all())
    if len(entries) != 1:
        return None, 'headquarters_entry_not_unique'
    hq = entries[0]
    if (canonical_headquarters_pool_reason(hq.reason) not in {'anchor_store_unmapped', 'anchor_geo_invalid'}
            or hq.source_assignment_round_id or not _in_window(hq.entered_at, until)):
        return None, 'not_initial_store_data_failure'
    raw = session.get(RawDouyinClue, lead.source_clue_row_key)
    if raw is None or raw.order_id != lead.order_id or not _in_window(raw.create_time_detail, until):
        return None, 'outside_source_window'
    if not raw.follow_poi_id or raw.follow_poi_id not in poi_ids:
        return None, 'outside_verified_directory'
    mapping = session.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == raw.follow_poi_id))
    store = session.get(DimStore, mapping.store_id) if mapping else None
    if (store is None or not store.is_active or store.longitude is None or store.latitude is None
            or not (-180 <= store.longitude <= 180 and -90 <= store.latitude <= 90)
            or not all((store.standard_province, store.standard_city, store.city_code))):
        return None, 'store_data_still_unavailable'
    if not raw.follow_life_account_id or raw.follow_life_account_id != store.store_id:
        return None, 'source_account_not_confirmed'
    sources = list(session.scalars(select(RawDouyinClue).where(RawDouyinClue.order_id == lead.order_id)).all())
    order = session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == lead.order_id))
    coupons = _coupon_statuses_by_order(session, {lead.order_id}).get(lead.order_id, [])
    verified_at = _verified_at_by_order(session, {lead.order_id}).get(lead.order_id)
    if any(_resolve_status(r, order, verified_at, until, coupons).normalized_status != 'active'
           for r in sources):
        return None, 'authoritative_order_not_active'
    if order and order.intention_poi_id and order.intention_poi_id != raw.follow_poi_id:
        return None, 'source_history_or_customer_choice_conflict'
    if any(r.follow_poi_id != raw.follow_poi_id or
           (r.intention_poi_id and r.intention_poi_id != raw.follow_poi_id) or
           (r.follow_life_account_id and r.follow_life_account_id != store.store_id) or
           not _in_window(r.create_time_detail, until) for r in sources):
        return None, 'source_history_or_customer_choice_conflict'
    masters = list(session.scalars(select(ClueMasterLead.lead_key).where(
        ClueMasterLead.order_id == lead.order_id)).all())
    if masters != [lead.lead_key]:
        return None, 'multiple_order_masters'
    if session.scalar(select(ClueAssignmentRound.assignment_round_id).where(
            ClueAssignmentRound.order_id == lead.order_id).limit(1)):
        return None, 'existing_assignment_history'
    if session.scalar(select(ClueFollowUpRecord.follow_up_record_id).where(
            ClueFollowUpRecord.order_id == lead.order_id).limit(1)):
        return None, 'existing_follow_up_history'
    center = session.get(ClueCenterOrder, lead.order_id)
    if center and (center.current_assignment_round_id or center.is_followed or center.is_follow_success
                   or center.verified_at or center.verified_store_id
                   or center.is_self_store_verified
                   or center.lead_status in {'converted', 'refunded', 'closed', 'closed_verified', 'closed_refunded', 'closed_order'}):
        return None, 'center_has_business_state'
    result = dict(lead_key=lead.lead_key, order_id=lead.order_id,
                  headquarters_pool_entry_id=hq.headquarters_pool_entry_id, reason=hq.reason,
                  source_clue_row_key=raw.clue_row_key, poi_id=raw.follow_poi_id,
                  store_id=store.store_id, store_name=store.store_name,
                  source_created_at=_aware(raw.create_time_detail).isoformat(),
                  first_seen_at=_aware(lead.first_seen_at).isoformat(),
                  longitude=str(store.longitude), latitude=str(store.latitude),
                  province=store.standard_province, city=store.standard_city, city_code=store.city_code)
    # Detect concurrent status/source edits between operator preview and execution.
    result['fingerprint'] = _digest([result, lead.state_version, str(lead.updated_at),
        str(hq.updated_at), str(center.updated_at) if center else None,
        [str(order.updated_at), order.payload_fingerprint] if order else None,
        sorted(coupons), str(verified_at),
        sorted((r.clue_row_key, str(r.updated_at), r.payload_fingerprint) for r in sources)])
    return result, None


def preview(session: Session, *, poi_ids: set[str], now=None):
    until = _aware(now or utcnow())
    if not poi_ids or until < SINCE:
        raise ValueError('verified POI directory and valid incident window required')
    candidates, skipped = [], Counter()
    cursor = ''
    while True:
        leads = list(session.scalars(select(ClueMasterLead).where(
            ClueMasterLead.lead_key > cursor,
            ClueMasterLead.pool_location == 'headquarters_pool',
            ClueMasterLead.first_seen_at >= SINCE,
            ClueMasterLead.first_seen_at <= until,
        ).order_by(ClueMasterLead.lead_key).limit(MAX_BATCH)).all())
        if not leads:
            break
        for lead in leads:
            row, reason = _inspect(session, lead, poi_ids, until)
            if row:
                candidates.append(row)
            else:
                skipped[reason] += 1
        cursor = leads[-1].lead_key
    return dict(version=VERSION, since=SINCE.isoformat(), until=until.isoformat(),
                poi_ids=sorted(poi_ids), candidates=candidates, skipped=dict(skipped))


def apply_plan(session: Session, plan: dict, *, actor: str, now=None):
    """Apply at most 100 previewed records in the caller's atomic transaction."""
    if session.new or session.dirty or session.deleted:
        raise ValueError('recovery requires a clean dedicated transaction')
    if plan.get('version') != VERSION or plan.get('since') != SINCE.isoformat() or not actor.strip():
        raise ValueError('invalid recovery plan or actor')
    candidates = plan['candidates']
    if len(candidates) > MAX_BATCH or len({r['lead_key'] for r in candidates}) != len(candidates):
        raise ValueError('apply requires a unique batch of at most 100 leads')
    now = _aware(now or utcnow())
    until = _aware(datetime.fromisoformat(plan['until']))
    if until > now or until < SINCE:
        raise ValueError('invalid preview window')
    if candidates and session.bind.dialect.name == 'postgresql':
        # A short, bounded operator transaction. Block ALL competing writers,
        # including insertions of another master/source row for the same order.
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text("SET LOCAL statement_timeout = '30s'"))
        session.execute(text('LOCK TABLE raw_douyin_clues, raw_douyin_orders, raw_douyin_order_coupons, '
            'settlement_order_details, dim_stores, dim_store_poi_mappings, '
            'clue_master_leads, clue_assignment_rounds, clue_center_orders, '
            'clue_follow_up_records, clue_headquarters_pool_entries IN SHARE ROW EXCLUSIVE MODE'))
    session.expire_all()
    skipped, restored = Counter(), []
    for expected in sorted(candidates, key=lambda r: r['lead_key']):
        lead = session.get(ClueMasterLead, expected['lead_key'])
        current, reason = _inspect(session, lead, set(plan['poi_ids']), until) if lead else (None, 'missing_lead')
        if current != expected:
            skipped[reason or 'changed_since_preview'] += 1
            continue
        hq = session.get(ClueHeadquartersPoolEntry, current['headquarters_pool_entry_id'])
        round_id = 'geo-recovery-' + _digest([VERSION, lead.lead_key, hq.headquarters_pool_entry_id])[:24]
        source_time = datetime.fromisoformat(current['source_created_at'])
        row = ClueAssignmentRound(assignment_round_id=round_id, lead_key=lead.lead_key,
            order_id=lead.order_id, round_no=1, execution_mode='formal',
            assigned_store_id=current['store_id'], assigned_store_name=current['store_name'],
            assigned_at=source_time, assigned_at_source='geo_recovery_clue_create_time',
            round_status='active_unfollowed', follow_result='pending', is_followed=False,
            is_follow_success=False, auto_expiry_enabled=False, expires_at=None,
            first_sla_expires_at=None, created_at=now, updated_at=now)
        session.add(row)
        hq.status, hq.closed_at, hq.close_reason, hq.updated_at = 'closed', now, VERSION, now
        lead.pool_location, lead.allocation_state = 'store_follow_up_pool', 'assigned'
        lead.current_assignment_round_id, lead.ended_without_assignment = round_id, False
        lead.anchor_poi_id, lead.anchor_store_id = current['poi_id'], current['store_id']
        lead.anchor_source, lead.anchor_unavailable_reason = 'follow_poi_id', None
        lead.anchor_longitude, lead.anchor_latitude = current['longitude'], current['latitude']
        lead.anchor_province, lead.anchor_city, lead.anchor_city_code = current['province'], current['city'], current['city_code']
        lead.state_version = (lead.state_version or 0) + 1
        lead.updated_at = now
        center = session.get(ClueCenterOrder, lead.order_id)
        if center is None:
            center = ClueCenterOrder(order_id=lead.order_id, created_at=now)
            session.add(center)
        center.lead_status, center.current_round_status = 'active', 'active_unfollowed'
        center.current_assignment_round_id, center.current_round_no = round_id, 1
        center.assigned_at, center.assigned_at_source = source_time, row.assigned_at_source
        center.assigned_store_id, center.assigned_store_name = current['store_id'], current['store_name']
        center.assigned_city, center.assigned_province = current['city_code'], current['province']
        center.follow_result, center.is_followed, center.is_follow_success = 'pending', False, False
        center.expires_at, center.reassign_reason, center.updated_at = None, None, now
        session.add(ClueAllocationAuditLog(audit_log_id=round_id, event_type='store_geo_recovery',
            actor=actor, reason_code=VERSION, before_snapshot=current,
            after_snapshot=dict(lead_key=lead.lead_key, assignment_round_id=round_id,
                store_id=current['store_id'], auto_expiry_enabled=False),
            detail_json=dict(source_time_is_creation_proxy=True, since=plan['since']), created_at=now))
        session.flush()
        restored.append(lead.lead_key)
    return dict(restored=len(restored), lead_keys=restored, skipped=dict(skipped))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preview-directory', type=Path)
    mode.add_argument('--apply-plan', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--actor')
    parser.add_argument('--backup-reference')
    args = parser.parse_args(argv)
    from apps.api.dy_api.db import get_session_factory
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError('database configuration required')
    if args.output.exists():
        raise ValueError('output already exists; choose a new audit file')
    if args.preview_directory:
        directory = json.loads(args.preview_directory.read_text(encoding='utf-8'))
        with factory() as session:
            result = preview(session, poi_ids={str(r['poi_id']) for r in directory})
            session.rollback()
    else:
        if not args.actor or not args.backup_reference:
            raise ValueError('apply requires actor and verified backup reference')
        plan = json.loads(args.apply_plan.read_text(encoding='utf-8'))
        result = dict(batches=[], backup_reference=args.backup_reference)
        for offset in range(0, len(plan['candidates']), MAX_BATCH):
            with factory.begin() as session:
                batch = apply_plan(session, dict(plan, candidates=plan['candidates'][offset:offset + MAX_BATCH]), actor=args.actor)
            result['batches'].append(batch)
            # Persist progress after each committed batch; DB audit is authoritative
            # if the process stops between commit and writing this receipt.
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(args.output), candidates=len(result.get('candidates', [])),
        restored=sum(r['restored'] for r in result.get('batches', []))), ensure_ascii=False))


if __name__ == '__main__':
    main()
