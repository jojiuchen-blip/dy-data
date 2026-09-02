from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueMasterLead,
    DimSkuProductRule,
    RawDouyinClue,
    SettlementOrderDetail,
    utcnow,
)
from apps.worker.order_status import ACTIVE_ORDER_STATUSES, PAID_ORDER_STATUSES

BUSINESS_EXECUTION_MODE = "formal"
ACTIVE_ROUND_STATUSES = ("active_unfollowed", "active_followed")
CLUE_SOURCE_ACTIVE_ORDER_STATUSES = tuple(
    sorted(ACTIVE_ORDER_STATUSES | PAID_ORDER_STATUSES)
)
PHONE_PAYLOAD_KEYS = (
    "telephone",
    "tel_addr",
    "phone",
    "mobile",
    "phone_number",
    "customer_phone",
    "contact_phone",
)
ENCRYPTED_PHONE_PAYLOAD_KEYS = ("enc_telephone", "encrypted_telephone")
PhonePlainResolver = Callable[[list[str]], dict[str, str]]


def normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 11:
        return ""
    return digits[-11:]


def mask_phone(value: str | None) -> str:
    phone = normalize_phone(value)
    if not phone:
        return ""
    return f"{phone[:3]}****{phone[-4:]}"


def refresh_clue_center_projection(
    session: Session,
    *,
    now: datetime | None = None,
    phone_plain_resolver: PhonePlainResolver | None = None,
    order_ids: set[str] | None = None,
) -> dict[str, int]:
    """Refresh order/contact/product fields without creating assignment rounds."""

    now = _aware(now or utcnow())
    selected_order_ids = {
        str(order_id).strip()
        for order_id in (order_ids or set())
        if str(order_id).strip() not in {"", "0"}
    }
    incremental = order_ids is not None
    if incremental and not selected_order_ids:
        return {"eligible_orders": 0, "projected_orders": 0}

    raw_stmt = (
        select(RawDouyinClue)
        .where(RawDouyinClue.order_status.in_(CLUE_SOURCE_ACTIVE_ORDER_STATUSES))
        .where(RawDouyinClue.order_id.is_not(None))
        .where(RawDouyinClue.order_id != "")
        .where(RawDouyinClue.order_id != "0")
    )
    if incremental:
        raw_stmt = raw_stmt.where(RawDouyinClue.order_id.in_(selected_order_ids))
    raw_clues = session.scalars(
        raw_stmt.order_by(RawDouyinClue.order_id, RawDouyinClue.clue_row_key)
    ).all()

    grouped: dict[str, list[RawDouyinClue]] = defaultdict(list)
    for clue in raw_clues:
        order_id = (clue.order_id or "").strip()
        if order_id:
            grouped[order_id].append(clue)

    if not grouped:
        return {"eligible_orders": 0, "projected_orders": 0}

    order_ids = set(grouped)
    sku_rules = _sku_rules(session, raw_clues)
    master_leads_by_source_clue_row_key = _master_leads_by_source_clue_row_key(session, raw_clues)
    preferred_store_by_order = {
        order_id: store_id
        for order_id, store_id in session.execute(
            select(
                ClueAssignmentRound.order_id,
                ClueAssignmentRound.assigned_store_id,
            )
            .where(ClueAssignmentRound.order_id.in_(order_ids))
            .where(ClueAssignmentRound.execution_mode == BUSINESS_EXECUTION_MODE)
            .where(ClueAssignmentRound.round_status.in_(ACTIVE_ROUND_STATUSES))
            .where(ClueAssignmentRound.is_follow_success.is_(True))
            .where(ClueAssignmentRound.assigned_store_id.is_not(None))
        ).all()
        if order_id and store_id
    }
    verifications = _verification_rows(
        session,
        order_ids,
        preferred_store_by_order=preferred_store_by_order,
    )
    existing_center_orders = _existing_center_orders(session, order_ids)
    encrypted_phone_plain_values = _encrypted_phone_plain_values(
        grouped,
        existing_center_orders,
        phone_plain_resolver,
    )

    projected_orders = 0
    for order_id, clues in grouped.items():
        sorted_clues = sorted(clues, key=_clue_sort_key)
        canonical = sorted_clues[0]
        lead = next(
            (
                master_leads_by_source_clue_row_key.get(clue.clue_row_key)
                for clue in sorted_clues
                if master_leads_by_source_clue_row_key.get(clue.clue_row_key) is not None
            ),
            None,
        )
        center_order = existing_center_orders.get(order_id)
        if lead is not None and lead.lifecycle_status != "active" and center_order is None:
            continue
        product_rule = sku_rules.get(_clean(canonical.product_id) or "")
        if center_order is None:
            center_order = ClueCenterOrder(
                order_id=order_id,
                lead_status="pending_allocation",
                current_round_no=0,
                current_round_status="pending_allocation",
                created_at=now,
                updated_at=now,
            )
            session.add(center_order)
            existing_center_orders[order_id] = center_order

        _refresh_center_source_fields(
            center_order,
            sorted_clues=sorted_clues,
            canonical=canonical,
            product_rule=product_rule,
            encrypted_phone_plain_values=encrypted_phone_plain_values,
        )
        round_row = _formal_round_for_projection(session, lead, center_order)
        if round_row is not None:
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

            center_order.lead_status = _lead_status_for_projection(round_row, lead)
            center_order.current_assignment_round_id = round_row.assignment_round_id
            center_order.current_round_no = round_row.round_no
            center_order.current_round_status = round_row.round_status
            center_order.assigned_at = round_row.assigned_at
            center_order.assigned_at_source = round_row.assigned_at_source
            center_order.assigned_store_id = round_row.assigned_store_id
            center_order.assigned_store_name = round_row.assigned_store_name
            center_order.follow_result = round_row.follow_result
            center_order.is_followed = round_row.is_followed
            center_order.is_follow_success = round_row.is_follow_success
            center_order.verified_store_id = round_row.verified_store_id
            center_order.verified_store_name = round_row.verified_store_name
            center_order.verified_at = round_row.verified_at
            center_order.is_self_store_verified = round_row.is_self_store_verified
            center_order.expires_at = round_row.expires_at
            center_order.reassign_reason = round_row.reassign_reason
        else:
            previous_round = _latest_closed_formal_round(session, lead, center_order)
            _project_unassigned_state(center_order, lead, previous_round=previous_round)
            verification = _select_verification(
                verifications.get(order_id, []),
                assigned_store_id=None,
                require_self_store=False,
            )
            center_order.verified_store_id = verification.get("verify_store_id")
            center_order.verified_store_name = verification.get("verify_store_name")
            center_order.verified_at = verification.get("verify_time")
        center_order.updated_at = now
        projected_orders += 1

    session.flush()
    return {"eligible_orders": projected_orders, "projected_orders": projected_orders}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clue_phone(clue: RawDouyinClue) -> tuple[str | None, str | None]:
    telephone = normalize_phone(clue.telephone)
    if telephone:
        return telephone, "telephone"

    raw_payload = clue.raw_payload if isinstance(clue.raw_payload, dict) else {}
    for key in PHONE_PAYLOAD_KEYS:
        value = normalize_phone(_clean(raw_payload.get(key)))
        if value:
            return value, "raw_payload"
    return None, None


def _first_clue_phone(
    clues: list[RawDouyinClue],
    encrypted_phone_plain_values: dict[str, str],
) -> tuple[str | None, str | None]:
    phone, source = _first_plain_clue_phone(clues)
    if phone:
        return phone, source
    for clue in clues:
        cipher_text = _encrypted_phone_text(clue)
        if cipher_text:
            phone = normalize_phone(encrypted_phone_plain_values.get(cipher_text))
            if phone:
                return phone, "enc_telephone"
    return None, None


def _first_plain_clue_phone(clues: list[RawDouyinClue]) -> tuple[str | None, str | None]:
    for clue in clues:
        phone_value, phone_source = _clue_phone(clue)
        if phone_value:
            return phone_value, phone_source
    return None, None


def _encrypted_phone_plain_values(
    grouped: dict[str, list[RawDouyinClue]],
    existing_center_orders: dict[str, ClueCenterOrder],
    resolver: PhonePlainResolver | None,
) -> dict[str, str]:
    if resolver is None:
        return {}
    cipher_texts: list[str] = []
    for order_id, clues in grouped.items():
        existing = existing_center_orders.get(order_id)
        if existing is not None and normalize_phone(existing.phone_plain):
            continue
        sorted_clues = sorted(clues, key=_clue_sort_key)
        plain_phone, _ = _first_plain_clue_phone(sorted_clues)
        if plain_phone:
            continue
        for clue in sorted_clues:
            cipher_text = _encrypted_phone_text(clue)
            if cipher_text:
                cipher_texts.append(cipher_text)
                break
    cipher_texts = [cipher_text for cipher_text in dict.fromkeys(cipher_texts) if cipher_text]
    if not cipher_texts:
        return {}
    try:
        return {
            cipher_text: phone
            for cipher_text, value in resolver(cipher_texts).items()
            if (phone := normalize_phone(value))
        }
    except Exception:
        print("[worker-clue-center] encrypted phone resolver failed", flush=True)
        return {}


def _encrypted_phone_text(clue: RawDouyinClue) -> str | None:
    value = _clean(clue.enc_telephone)
    if _is_online_cipher(value):
        return value

    raw_payload = clue.raw_payload if isinstance(clue.raw_payload, dict) else {}
    for key in ENCRYPTED_PHONE_PAYLOAD_KEYS:
        value = _clean(raw_payload.get(key))
        if _is_online_cipher(value):
            return value

    for key in PHONE_PAYLOAD_KEYS:
        value = _clean(raw_payload.get(key))
        if _is_online_cipher(value):
            return value
    return None


def _is_online_cipher(value: str | None) -> bool:
    return bool(value and value.startswith("Enc."))


def _mask_or_masked_phone(value: str | None) -> str:
    text = _clean(value) or ""
    if re.fullmatch(r"\d{3}\*{4}\d{4}", text):
        return text
    return mask_phone(text)


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


def _lead_status(round_row: ClueAssignmentRound) -> str:
    if round_row.is_follow_success and round_row.verified_at is not None:
        return "converted"
    if round_row.round_status in {"failed_pending_reassign", "expired_pending_reassign"}:
        return "pending_reassign"
    return "active"


def _lead_status_for_projection(
    round_row: ClueAssignmentRound,
    lead: ClueMasterLead | None,
) -> str:
    if lead is not None:
        terminal_status = {
            "closed_verified": "converted",
            "closed_refunded": "refunded",
            "closed_order": "closed",
            "status_review": "status_review",
        }.get(lead.lifecycle_status)
        if terminal_status:
            return terminal_status
    return _lead_status(round_row)


def _sku_rules(session: Session, raw_clues: list[RawDouyinClue]) -> dict[str, DimSkuProductRule]:
    product_ids = {_clean(clue.product_id) for clue in raw_clues}
    product_ids.discard(None)
    if not product_ids:
        return {}
    rows = session.scalars(select(DimSkuProductRule).where(DimSkuProductRule.sku_id.in_(product_ids))).all()
    return {row.sku_id: row for row in rows}


def _master_leads_by_source_clue_row_key(
    session: Session,
    raw_clues: list[RawDouyinClue],
) -> dict[str, ClueMasterLead]:
    source_clue_row_keys = {clue.clue_row_key for clue in raw_clues if clue.clue_row_key}
    if not source_clue_row_keys:
        return {}
    rows = session.scalars(
        select(ClueMasterLead).where(ClueMasterLead.source_clue_row_key.in_(source_clue_row_keys))
    ).all()
    return {row.source_clue_row_key: row for row in rows}


def _formal_round_for_projection(
    session: Session,
    lead: ClueMasterLead | None,
    center_order: ClueCenterOrder,
) -> ClueAssignmentRound | None:
    round_id = (
        lead.current_assignment_round_id
        if lead is not None
        else center_order.current_assignment_round_id
    )
    if not round_id:
        return None
    round_row = session.get(ClueAssignmentRound, round_id)
    if round_row is None or round_row.execution_mode != BUSINESS_EXECUTION_MODE:
        return None
    if round_row.round_status not in ACTIVE_ROUND_STATUSES:
        return None
    if round_row.order_id != center_order.order_id:
        return None
    if lead is not None and (
        round_row.lead_key != lead.lead_key
        or round_row.order_id != lead.order_id
    ):
        return None
    return round_row


def _latest_closed_formal_round(
    session: Session,
    lead: ClueMasterLead | None,
    center_order: ClueCenterOrder,
) -> ClueAssignmentRound | None:
    statement = (
        select(ClueAssignmentRound)
        .where(ClueAssignmentRound.order_id == center_order.order_id)
        .where(ClueAssignmentRound.execution_mode == BUSINESS_EXECUTION_MODE)
        .where(ClueAssignmentRound.round_status.not_in(ACTIVE_ROUND_STATUSES))
        .order_by(
            ClueAssignmentRound.round_no.desc(),
            ClueAssignmentRound.assigned_at.desc(),
            ClueAssignmentRound.assignment_round_id.desc(),
        )
        .limit(1)
    )
    if lead is not None:
        statement = statement.where(ClueAssignmentRound.lead_key == lead.lead_key)
    return session.scalar(statement)


def _project_unassigned_state(
    center_order: ClueCenterOrder,
    lead: ClueMasterLead | None,
    *,
    previous_round: ClueAssignmentRound | None = None,
) -> None:
    allocation_state = _clean(lead.allocation_state) if lead is not None else None
    pool_location = _clean(lead.pool_location) if lead is not None else None
    lifecycle_state = _clean(lead.lifecycle_status) if lead is not None else None
    display_state = {
        "closed_verified": "converted",
        "closed_refunded": "refunded",
        "closed_order": "closed",
        "status_review": "status_review",
    }.get(lifecycle_state) or (
        "headquarters"
        if pool_location == "headquarters_pool"
        else "pending_reassign"
        if allocation_state == "pending_reassign"
        else "pending_allocation"
    )
    center_order.lead_status = display_state
    center_order.current_assignment_round_id = None
    center_order.current_round_no = 0
    center_order.current_round_status = display_state
    center_order.assigned_at = None
    center_order.assigned_at_source = "clue_projection"
    center_order.assigned_store_id = None
    center_order.assigned_store_name = None
    center_order.assigned_city = None
    center_order.assigned_province = None
    center_order.follow_result = previous_round.follow_result if previous_round is not None else "pending"
    center_order.is_followed = previous_round.is_followed if previous_round is not None else False
    center_order.is_follow_success = False
    center_order.verified_store_id = None
    center_order.verified_store_name = None
    center_order.verified_at = None
    center_order.is_self_store_verified = False
    center_order.expires_at = None
    center_order.reassign_reason = (
        previous_round.reassign_reason or previous_round.terminal_reason
        if previous_round is not None
        else None
    )


def _refresh_center_source_fields(
    center_order: ClueCenterOrder,
    *,
    sorted_clues: list[RawDouyinClue],
    canonical: RawDouyinClue,
    product_rule: DimSkuProductRule | None,
    encrypted_phone_plain_values: dict[str, str],
) -> None:
    center_order.source_clue_ids = [_clue_identifier(clue) for clue in sorted_clues]
    center_order.source_clue_count = len(sorted_clues)
    center_order.canonical_clue_id = _clean(canonical.clue_id)
    phone_plain, phone_source = _first_clue_phone(sorted_clues, encrypted_phone_plain_values)
    if not phone_plain:
        phone_plain = normalize_phone(center_order.phone_plain)
        phone_source = _clean(center_order.phone_source)
    phone_masked = mask_phone(phone_plain)
    if not phone_masked:
        phone_masked = _mask_or_masked_phone(center_order.phone_masked)
        phone_source = phone_source or _clean(center_order.phone_source)
    center_order.phone_plain = phone_plain or None
    center_order.phone_masked = phone_masked
    center_order.phone_source = phone_source if phone_plain or phone_masked else None
    center_order.product_id = _clean(canonical.product_id)
    center_order.product_name = _clean(canonical.product_name)
    center_order.product_type = product_rule.product_type if product_rule else None
    center_order.author_nickname = _clean(canonical.author_nickname)


def _existing_center_orders(session: Session, order_ids: set[str]) -> dict[str, ClueCenterOrder]:
    rows = session.scalars(select(ClueCenterOrder).where(ClueCenterOrder.order_id.in_(order_ids))).all()
    return {row.order_id: row for row in rows}


def _verification_rows(
    session: Session,
    order_ids: set[str],
    *,
    preferred_store_by_order: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    selected_order_ids = {
        str(value) for value in order_ids if _clean(value)
    }
    if not selected_order_ids:
        return {}

    def ranked_rows(
        store_filter: Any | None = None,
    ) -> dict[str, dict[str, Any]]:
        ranking = func.row_number().over(
            partition_by=SettlementOrderDetail.order_id,
            order_by=(
                SettlementOrderDetail.verify_time.asc().nulls_last(),
                SettlementOrderDetail.coupon_id.asc(),
            ),
        ).label("verification_rank")
        ranked = (
            select(
                SettlementOrderDetail.order_id,
                SettlementOrderDetail.verify_store_id,
                SettlementOrderDetail.verify_store_name,
                SettlementOrderDetail.verify_time,
                ranking,
            )
            .where(
                SettlementOrderDetail.order_id.in_(selected_order_ids)
            )
            .where(SettlementOrderDetail.is_verified.is_(True))
        )
        if store_filter is not None:
            ranked = ranked.where(store_filter)
        ranked_subquery = ranked.subquery()
        rows = session.execute(
            select(
                ranked_subquery.c.order_id,
                ranked_subquery.c.verify_store_id,
                ranked_subquery.c.verify_store_name,
                ranked_subquery.c.verify_time,
            ).where(ranked_subquery.c.verification_rank == 1)
        ).mappings()
        return {row["order_id"]: dict(row) for row in rows}

    result: dict[str, list[dict[str, Any]]] = {}
    preferred = {
        order_id: store_id
        for order_id, store_id in (
            preferred_store_by_order or {}
        ).items()
        if order_id in selected_order_ids and _clean(store_id)
    }
    if preferred:
        preferred_store = case(
            preferred,
            value=SettlementOrderDetail.order_id,
        )
        for order_id, row in ranked_rows(
            SettlementOrderDetail.verify_store_id == preferred_store
        ).items():
            result[order_id] = [row]

    for order_id, row in ranked_rows().items():
        result.setdefault(order_id, [row])
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
