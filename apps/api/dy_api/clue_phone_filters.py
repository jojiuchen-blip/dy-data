"""Exact phone selection without remote calls or decrypting a source table."""
from __future__ import annotations

import re
from sqlalchemy import func, or_, select, union
from sqlalchemy.orm import Session

from apps.api.dy_api.models import ClueCenterOrder, RawDouyinClue
from apps.worker.order_status import ACTIVE_ORDER_STATUSES, PAID_ORDER_STATUSES
from src.dy_data.phones import normalize_phone, phone_source_fingerprint

PHONE_PAYLOAD_KEYS = ("telephone", "tel_addr", "phone", "mobile", "phone_number", "customer_phone", "contact_phone")


def validate_phone_filter(value: object) -> str | None:
    """Accept only a complete unformatted mobile number, never echo the input."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("请输入完整的11位中国大陆手机号")
    phone = value.strip()
    if not phone:
        return None
    if not re.fullmatch(r"1[3-9][0-9]{9}", phone):
        raise ValueError("请输入完整的11位中国大陆手机号")
    return phone


def _candidate_phone(column, phone):
    # Source ingestion accepts common separators and a country prefix. This
    # SQL preselection is deliberately broad; the shared parser checks exact
    # source validity below, so arbitrary text can never become a match.
    compact = func.trim(column)
    for separator in (" ", "\t", "\r", "\n", "(", ")", ".", "-"):
        compact = func.replace(compact, separator, "")
    return compact.in_((phone, "+86" + phone, "0086" + phone))


def matching_phone_order_ids(session: Session, phone: str) -> list[str]:
    """Select only matching candidates and verify their current phone source.

    Candidate/source reads are batched. Cached plaintext can be used only for
    its matching current ciphertext fingerprint. No external resolver is called.
    The caller must intersect these IDs with its existing authorization query.
    """
    from apps.api.dy_api.routes._data import _phone_from_clue_payload, _encrypted_phone_from_clue_payload, _json_object

    statuses = sorted(ACTIVE_ORDER_STATUSES | PAID_ORDER_STATUSES)
    raw_values = [RawDouyinClue.telephone, *(RawDouyinClue.raw_payload[key].as_string() for key in PHONE_PAYLOAD_KEYS)]
    raw_candidates = select(RawDouyinClue.order_id.label("order_id")).where(
        RawDouyinClue.order_status.in_(statuses),
        or_(*(_candidate_phone(value, phone) for value in raw_values)),
    )
    candidates = union(select(ClueCenterOrder.order_id).where(ClueCenterOrder.phone_plain == phone), raw_candidates).subquery()
    matched: list[str] = []
    cursor = ""
    while True:
        ids = list(session.scalars(select(candidates.c.order_id).where(candidates.c.order_id > cursor).order_by(candidates.c.order_id).limit(200)))
        if not ids:
            break
        cached = {row.order_id: row for row in session.execute(select(ClueCenterOrder.order_id, ClueCenterOrder.phone_plain, ClueCenterOrder.phone_source_fingerprint).where(ClueCenterOrder.order_id.in_(ids)))}
        rows = session.execute(select(RawDouyinClue.order_id, RawDouyinClue.telephone, RawDouyinClue.enc_telephone, RawDouyinClue.raw_payload).where(
            RawDouyinClue.order_id.in_(ids), RawDouyinClue.order_status.in_(statuses),
        ).order_by(RawDouyinClue.create_time_detail.is_(None), RawDouyinClue.create_time_detail, func.coalesce(RawDouyinClue.clue_id, ""), RawDouyinClue.clue_row_key)).mappings()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["order_id"], []).append(dict(row))
        for order_id in ids:
            sources = grouped.get(order_id, [])
            plain = next((value for row in sources if (value := _phone_from_clue_payload(row))), "")
            if plain:
                if plain == phone:
                    matched.append(order_id)
                continue
            # A masked current source takes priority over cached ciphertext.
            if any(isinstance(value, str) and re.fullmatch(r"1[3-9][0-9]\*{4}[0-9]{4}", value.strip()) for row in sources for value in [row.get("telephone"), *(_json_object(row.get("raw_payload")).get(key) for key in PHONE_PAYLOAD_KEYS)]):
                continue
            cipher = next((value for row in sources if (value := _encrypted_phone_from_clue_payload(row))), "")
            stored = cached.get(order_id)
            fingerprint = phone_source_fingerprint(cipher_text=cipher)
            if fingerprint and stored and stored.phone_source_fingerprint == fingerprint and normalize_phone(stored.phone_plain) == phone:
                matched.append(order_id)
        cursor = ids[-1]
    return matched
