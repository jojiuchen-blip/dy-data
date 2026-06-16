from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueReassignRuleSetting,
    DimSkuProductRule,
    RawDouyinClue,
    SettlementOrderDetail,
    utcnow,
)

FOLLOWED_RESULTS = {"success", "failed", "unreachable", "continue_following"}
SUCCESS_RESULT = "success"
GLOBAL_REASSIGN_RULE_KEY = "global"


def mask_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 11:
        return ""
    phone = digits[-11:]
    return f"{phone[:3]}****{phone[-4:]}"


def load_reassign_sla_hours(session: Session) -> int | None:
    setting = session.get(ClueReassignRuleSetting, GLOBAL_REASSIGN_RULE_KEY)
    if setting is None:
        return None
    return setting.reassign_sla_hours


def rebuild_clue_center(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    now = _aware(now or utcnow())
    sla_hours = load_reassign_sla_hours(session)
    raw_clues = session.scalars(
        select(RawDouyinClue)
        .where(RawDouyinClue.order_status == "履约中")
        .where(RawDouyinClue.order_id.is_not(None))
        .where(RawDouyinClue.order_id != "")
        .where(RawDouyinClue.order_id != "0")
    ).all()

    grouped: dict[str, list[RawDouyinClue]] = defaultdict(list)
    for clue in raw_clues:
        order_id = (clue.order_id or "").strip()
        if order_id:
            grouped[order_id].append(clue)

    if not grouped:
        return {"eligible_orders": 0, "assignment_rounds": 0}

    order_ids = set(grouped)
    sku_rules = _sku_rules(session, raw_clues)
    verifications = _verification_rows(session, order_ids)
    existing_rounds = _existing_rounds(session, order_ids)

    assignment_rounds = 0
    for order_id, clues in grouped.items():
        sorted_clues = sorted(clues, key=_clue_sort_key)
        canonical = sorted_clues[0]
        assigned_at = _aware(canonical.create_time_detail)
        expires_at = _expires_at(assigned_at, sla_hours)
        assignment_round_id = f"{order_id}-1"
        round_row = existing_rounds.get(order_id)
        if round_row is None:
            round_row = ClueAssignmentRound(
                assignment_round_id=assignment_round_id,
                order_id=order_id,
                round_no=1,
                follow_result="pending",
                created_at=now,
                updated_at=now,
                round_status="active_unfollowed",
            )
            session.add(round_row)
            existing_rounds[order_id] = round_row

        round_row.assignment_round_id = assignment_round_id
        round_row.order_id = order_id
        round_row.round_no = 1
        round_row.assigned_at = assigned_at
        round_row.assigned_at_source = "clue_create_time_detail"
        round_row.assigned_store_id = _clean(canonical.follow_life_account_id)
        round_row.assigned_store_name = _clean(canonical.follow_life_account_name)
        round_row.follow_result = _clean(round_row.follow_result) or "pending"
        round_row.is_followed = round_row.follow_result in FOLLOWED_RESULTS
        round_row.is_follow_success = round_row.follow_result == SUCCESS_RESULT
        round_row.expires_at = expires_at
        round_row.round_status, round_row.reassign_reason = _round_status(
            follow_result=round_row.follow_result,
            is_followed=round_row.is_followed,
            expires_at=expires_at,
            now=now,
        )

        verification = _select_verification(
            verifications.get(order_id, []),
            assigned_store_id=round_row.assigned_store_id,
            require_self_store=round_row.is_follow_success,
        )
        round_row.verified_store_id = verification.get("verify_store_id")
        round_row.verified_store_name = verification.get("verify_store_name")
        round_row.verified_at = verification.get("verify_time")
        round_row.is_self_store_verified = bool(
            round_row.is_follow_success
            and round_row.assigned_store_id
            and round_row.verified_store_id == round_row.assigned_store_id
        )
        round_row.updated_at = now
        assignment_rounds += 1

        product_rule = sku_rules.get(_clean(canonical.product_id) or "")
        center_order = session.get(ClueCenterOrder, order_id)
        if center_order is None:
            center_order = ClueCenterOrder(order_id=order_id, created_at=now, updated_at=now)
            session.add(center_order)

        center_order.source_clue_ids = [_clue_identifier(clue) for clue in sorted_clues]
        center_order.source_clue_count = len(sorted_clues)
        center_order.canonical_clue_id = _clean(canonical.clue_id)
        center_order.lead_status = _lead_status(round_row)
        center_order.current_assignment_round_id = assignment_round_id
        center_order.current_round_no = 1
        center_order.current_round_status = round_row.round_status
        center_order.assigned_at = assigned_at
        center_order.assigned_at_source = "clue_create_time_detail"
        center_order.assigned_store_id = round_row.assigned_store_id
        center_order.assigned_store_name = round_row.assigned_store_name
        center_order.assigned_city = _clean(canonical.auto_city_name)
        center_order.assigned_province = _clean(canonical.auto_province_name)
        center_order.phone_masked = mask_phone(canonical.telephone)
        center_order.phone_source = "telephone" if center_order.phone_masked else None
        center_order.product_id = _clean(canonical.product_id)
        center_order.product_name = _clean(canonical.product_name)
        center_order.product_type = product_rule.product_type if product_rule else None
        center_order.author_nickname = _clean(canonical.author_nickname)
        center_order.follow_result = round_row.follow_result
        center_order.is_followed = round_row.is_followed
        center_order.is_follow_success = round_row.is_follow_success
        center_order.verified_store_id = round_row.verified_store_id
        center_order.verified_store_name = round_row.verified_store_name
        center_order.verified_at = round_row.verified_at
        center_order.is_self_store_verified = round_row.is_self_store_verified
        center_order.expires_at = expires_at
        center_order.reassign_reason = round_row.reassign_reason
        center_order.updated_at = now

    session.flush()
    return {"eligible_orders": len(grouped), "assignment_rounds": assignment_rounds}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _clue_sort_key(clue: RawDouyinClue) -> tuple[datetime, str, str]:
    return (
        _aware(clue.create_time_detail) or datetime.max.replace(tzinfo=timezone.utc),
        _clean(clue.clue_id) or "",
        clue.clue_row_key,
    )


def _clue_identifier(clue: RawDouyinClue) -> str:
    return _clean(clue.clue_id) or clue.clue_row_key


def _expires_at(assigned_at: datetime | None, sla_hours: int | None) -> datetime | None:
    if assigned_at is None or sla_hours is None:
        return None
    return assigned_at + timedelta(hours=sla_hours)


def _round_status(
    *,
    follow_result: str,
    is_followed: bool,
    expires_at: datetime | None,
    now: datetime | None,
) -> tuple[str, str | None]:
    if follow_result == "failed":
        return "failed_pending_reassign", "follow_failed"
    if expires_at is not None and now is not None and not is_followed and now >= expires_at:
        return "expired_pending_reassign", "timeout"
    if is_followed:
        return "active_followed", None
    return "active_unfollowed", None


def _lead_status(round_row: ClueAssignmentRound) -> str:
    if round_row.is_follow_success and round_row.verified_at is not None:
        return "converted"
    if round_row.round_status in {"failed_pending_reassign", "expired_pending_reassign"}:
        return "pending_reassign"
    return "active"


def _sku_rules(session: Session, raw_clues: list[RawDouyinClue]) -> dict[str, DimSkuProductRule]:
    product_ids = {_clean(clue.product_id) for clue in raw_clues}
    product_ids.discard(None)
    if not product_ids:
        return {}
    rows = session.scalars(select(DimSkuProductRule).where(DimSkuProductRule.sku_id.in_(product_ids))).all()
    return {row.sku_id: row for row in rows}


def _existing_rounds(session: Session, order_ids: set[str]) -> dict[str, ClueAssignmentRound]:
    rows = session.scalars(
        select(ClueAssignmentRound)
        .where(ClueAssignmentRound.order_id.in_(order_ids))
        .where(ClueAssignmentRound.round_no == 1)
    ).all()
    return {row.order_id: row for row in rows}


def _verification_rows(session: Session, order_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    rows = session.execute(
        select(
            SettlementOrderDetail.order_id,
            SettlementOrderDetail.verify_store_id,
            SettlementOrderDetail.verify_store_name,
            SettlementOrderDetail.verify_time,
        )
        .where(SettlementOrderDetail.order_id.in_(order_ids))
        .where(SettlementOrderDetail.is_verified.is_(True))
    ).mappings()
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[row["order_id"]].append(dict(row))
    for values in result.values():
        values.sort(key=lambda row: (_aware(row.get("verify_time")) or datetime.max.replace(tzinfo=timezone.utc)))
    return result


def _select_verification(
    rows: list[dict[str, Any]],
    *,
    assigned_store_id: str | None,
    require_self_store: bool,
) -> dict[str, Any]:
    if not rows:
        return {}
    if require_self_store and assigned_store_id:
        for row in rows:
            if row.get("verify_store_id") == assigned_store_id:
                return row
    return rows[0]
