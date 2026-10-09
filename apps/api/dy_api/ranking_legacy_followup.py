"""The pre-October-7 manual-only ranking rules, isolated from clue lifecycle rules."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from apps.api.dy_api.clue_followup_metrics import AssignmentRoundEvidence, FollowUpEvidence, FollowUpMetric, _aware
from apps.api.dy_api.models import ClueFollowUpRecord

LEGACY_RANKING_VERSION = "ranking-preoct7-manual-follow-v1"
LEGACY_DEFINITIONS = {
    "follow_24h_rate": "24小时内有未删除人工跟进记录的正式分配轮次数÷全部正式分配轮次数；未接通、战败计入，不自动计入核销，不因退款或关闭剔除分母；上级累加分子分母",
    "follow_any_rate": "有未删除人工跟进记录的正式分配轮次数÷全部正式分配轮次数，不限制跟进时间；未接通、战败计入，不自动计入核销，不因退款或关闭剔除分母；上级累加分子分母",
    "follow_action_rate": "兼容字段，等同旧口径跟进率；看板与导出不单独展示",
    "terminal_evidence": "人工跟进指标不使用核销、退款或关闭终态计分或筛除分母",
}

def evaluate_legacy_ranking_round(round_row, *, follow_ups=(), observed_through=None):
    row = round_row if isinstance(round_row, AssignmentRoundEvidence) else AssignmentRoundEvidence.from_row(round_row)
    cutoff = _aware(observed_through) or datetime.now(timezone.utc)
    at = _aware(row.assigned_at)
    deadline = at + timedelta(hours=24) if at else None
    if row.execution_mode != "formal" or at is None or at > cutoff:
        return FollowUpMetric(row.assignment_round_id,row.order_id,0,0,0,0,"legacy_round_not_observed",deadline,None,None)
    any_ids, window_ids, seen = [], [], set()
    for record in follow_ups:
        item = record if isinstance(record, FollowUpEvidence) else FollowUpEvidence.from_row(record)
        created = _aware(item.created_at)
        if item.follow_up_record_id in seen or item.deleted_at is not None or created is None:
            continue
        seen.add(item.follow_up_record_id)
        if item.assignment_round_id != row.assignment_round_id or item.assigned_store_id != row.assigned_store_id:
            continue
        if not at <= created <= cutoff:
            continue
        any_ids.append(item.follow_up_record_id)
        if created <= deadline:
            window_ids.append(item.follow_up_record_id)
    return FollowUpMetric(row.assignment_round_id,row.order_id,int(bool(window_ids)),1,int(bool(any_ids)),1,
        "legacy_manual_follow",deadline,None,None,follow_record_ids=tuple(window_ids),
        follow_any_record_ids=tuple(any_ids),under_observation=cutoff < deadline,
        follow_action_numerator=int(bool(any_ids)),follow_action_denominator=1,
        follow_action_record_ids=tuple(any_ids))

def bulk_evaluate_legacy_ranking_followup(session, order_ids, *, round_rows, observed_through=None):
    cutoff = _aware(observed_through) or datetime.now(timezone.utc)
    rows = list(round_rows)
    records = defaultdict(list)
    ids = [row.assignment_round_id for row in rows]
    for start in range(0,len(ids),500):
        for record in session.scalars(select(ClueFollowUpRecord).where(
            ClueFollowUpRecord.assignment_round_id.in_(ids[start:start+500]),
            ClueFollowUpRecord.deleted_at.is_(None), ClueFollowUpRecord.created_at <= cutoff)):
            records[record.assignment_round_id].append(record)
    return {row.assignment_round_id:evaluate_legacy_ranking_round(row,
        follow_ups=records[row.assignment_round_id],observed_through=cutoff) for row in rows}
