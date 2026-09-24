"""DYDATA-97: strict receipt-amount extraction for settlement fee bases.

Settlement commission is based on the *receipt* amount persisted in the raw
platform payload, never on the ``paid`` columns. ``paid`` remains an order /
verification fact with its own meaning; it must not be repurposed as the fee
basis.

This helper reads only the already saved ``raw_payload`` of an order and its
coupons. It returns an amount only when it is proven to be a whole,
non-negative number of cents with an unambiguous coupon/item attribution:

* ``receipt_amount`` on the coupon payload wins when it is valid. If the field
  is present but unusable, resolution fails closed instead of falling back;
* for a multi-coupon order a ``sub_order_amount_infos`` entry may be used only
  when the coupon's ``order_item_id`` points at exactly one usable entry and no
  other coupon in the same order shares that item;
* for a single-coupon order the order basis is the sum of every
  ``sub_order_amount_infos`` line when all lines are proven (the authoritative
  script's full ``receipt_amount`` total, no invented attribution key);
* ``sub_order_amount_infos`` that is present but not a list (``null``, dict,
  string, number, ...) is damaged evidence and blocks; an explicitly empty list
  means the order carried no sub-order lines, so it stays equivalent to a
  missing field and may still fall back;
* a partial, corrupt or explicitly duplicated non-empty sub-order list blocks
  instead of falling back to a single line or the order total;
* the order-level ``receipt_amount`` may be used only when the order has exactly
  one coupon and the interface ``count`` evidence does not prove more units;
* any missing, corrupt or ambiguous value yields ``None`` (fail closed).

Amounts are integer cents. ``0`` is a valid receipt. ``bool``, negatives,
non-finite numbers (``NaN`` / ``Infinity``), fractional cents, non-numeric
strings and absent values are rejected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import RawDouyinOrder, RawDouyinOrderCoupon

RECEIPT_AMOUNT_FIELD = "receipt_amount"
SUB_ORDER_AMOUNT_FIELD = "sub_order_amount_infos"
ORDER_ITEM_ID_FIELD = "order_item_id"
# The order payload's own purchase-quantity field ("购买数量"). It is the only
# unit-count evidence we trust when deciding a single-coupon order total.
INTERFACE_COUNT_FIELD = "count"


def parse_receipt_amount_cent(value: Any) -> int | None:
    """Return ``value`` as non-negative integer cents, or ``None`` if unprovable.

    ``bool`` is rejected even though it is an ``int`` subclass. ``None``,
    negatives, non-finite numbers, fractional cents and non-numeric strings are
    rejected. ``0`` is a valid, proven receipt.
    """

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        amount = value
    elif isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            return None
        amount = int(value)
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        amount = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
        if not parsed.is_finite() or parsed != parsed.to_integral_value():
            return None
        amount = int(parsed)
    else:
        return None
    if amount < 0:
        return None
    return amount


@dataclass(frozen=True)
class SubOrderReceipts:
    """Receipt facts parsed from an order's ``sub_order_amount_infos``.

    ``unique`` holds item ids with exactly one proven entry. ``unusable`` holds
    item ids that were listed but cannot be proven (duplicate, conflicting or
    missing receipt). Anything absent from both maps had no usable entry at all.
    ``entries_present`` is true when the payload carried a non-empty list, and
    ``complete_total`` is the integer-cent sum of every line only when every
    line is a dict with a proven receipt and no item id is duplicated; otherwise
    it is ``None`` so the whole list blocks instead of yielding a partial sum.
    ``corrupt`` is true only when the field exists but is not a list at all
    (``null``, dict, string, number, ...). That is damaged evidence and must
    block, unlike an absent field or an explicitly empty list, which carries no
    sub-order lines and therefore no contradicting evidence.

    ``0`` is a valid receipt, so a proven zero line still counts as evidence
    rather than a missing value.
    """

    unique: dict[str, int]
    unusable: frozenset[str]
    entries_present: bool
    complete_total: int | None
    corrupt: bool = False

    @classmethod
    def from_payload(cls, payload: Any) -> "SubOrderReceipts":
        if not isinstance(payload, dict):
            return cls(
                unique={},
                unusable=frozenset(),
                entries_present=False,
                complete_total=None,
            )
        if SUB_ORDER_AMOUNT_FIELD not in payload:
            return cls(
                unique={},
                unusable=frozenset(),
                entries_present=False,
                complete_total=None,
            )
        entries = payload.get(SUB_ORDER_AMOUNT_FIELD)
        if not isinstance(entries, list):
            # Field present but not a list (null/dict/string/number/bool):
            # damaged evidence, never the same as an absent field.
            return cls(
                unique={},
                unusable=frozenset(),
                entries_present=False,
                complete_total=None,
                corrupt=True,
            )
        if not entries:
            # Explicit empty list: the platform recorded no sub-order lines.
            # Well-formed "no lines" evidence, so the caller may still fall back
            # to the order-level total.
            return cls(
                unique={},
                unusable=frozenset(),
                entries_present=False,
                complete_total=None,
            )
        observed: dict[str, list[int | None]] = {}
        total = 0
        complete = True
        for entry in entries:
            if not isinstance(entry, dict):
                complete = False
                continue
            parsed = parse_receipt_amount_cent(entry.get(RECEIPT_AMOUNT_FIELD))
            if parsed is None:
                complete = False
            else:
                total += parsed
            raw_item_id = entry.get(ORDER_ITEM_ID_FIELD)
            if raw_item_id is None:
                continue
            item_id = str(raw_item_id).strip()
            if not item_id:
                continue
            observed.setdefault(item_id, []).append(parsed)
        unique: dict[str, int] = {}
        unusable: set[str] = set()
        for item_id, parsed_values in observed.items():
            if len(parsed_values) == 1 and parsed_values[0] is not None:
                unique[item_id] = parsed_values[0]
            else:
                unusable.add(item_id)
        if unusable:
            complete = False
        return cls(
            unique=unique,
            unusable=frozenset(unusable),
            entries_present=True,
            complete_total=total if complete else None,
        )


@dataclass(frozen=True)
class OrderAttribution:
    """Locally precomputed coupon attribution for one order.

    Callers that resolve many coupons can build these from a bounded batch and
    pass them into :func:`resolve_coupon_receipt_cent` to avoid a query per
    coupon. Instances describe the batch that built them and are never cached
    across runs.
    """

    coupon_count: int
    item_share_counts: Mapping[str, int] = field(default_factory=dict)

    def item_share_count(self, item_id: str) -> int:
        return int(self.item_share_counts.get(item_id, 0))


def load_order_attributions(
    session: Session, order_ids: Iterable[int]
) -> dict[int, OrderAttribution]:
    """Build per-order coupon counts and item shares with two grouped queries."""

    ids = tuple(sorted({int(value) for value in order_ids}))
    if not ids:
        return {}
    counts: dict[int, int] = {}
    for raw_order_id, count in session.execute(
        select(RawDouyinOrderCoupon.raw_order_id, func.count())
        .where(RawDouyinOrderCoupon.raw_order_id.in_(ids))
        .group_by(RawDouyinOrderCoupon.raw_order_id)
    ):
        counts[int(raw_order_id)] = int(count)
    shares: dict[int, dict[str, int]] = {}
    for raw_order_id, item_id, count in session.execute(
        select(
            RawDouyinOrderCoupon.raw_order_id,
            RawDouyinOrderCoupon.order_item_id,
            func.count(),
        )
        .where(
            RawDouyinOrderCoupon.raw_order_id.in_(ids),
            RawDouyinOrderCoupon.order_item_id.is_not(None),
        )
        .group_by(
            RawDouyinOrderCoupon.raw_order_id,
            RawDouyinOrderCoupon.order_item_id,
        )
    ):
        if item_id is None:
            continue
        shares.setdefault(int(raw_order_id), {})[str(item_id)] = int(count)
    return {
        raw_order_id: OrderAttribution(
            coupon_count=counts.get(raw_order_id, 0),
            item_share_counts=shares.get(raw_order_id, {}),
        )
        for raw_order_id in ids
    }


def _payload_of(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _order_coupon_count(session: Session, order: RawDouyinOrder) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(RawDouyinOrderCoupon)
        .where(RawDouyinOrderCoupon.raw_order_id == order.id)
    )
    return int(count or 0)


def _coupon_item_share_count(
    session: Session, order: RawDouyinOrder, item_id: str
) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(RawDouyinOrderCoupon)
        .where(
            RawDouyinOrderCoupon.raw_order_id == order.id,
            RawDouyinOrderCoupon.order_item_id == item_id,
        )
    )
    return int(count or 0)


def _item_share_count(
    session: Session,
    order: RawDouyinOrder,
    item_id: str,
    attribution: OrderAttribution | None,
) -> int:
    if attribution is not None:
        return attribution.item_share_count(item_id)
    return _coupon_item_share_count(session, order, item_id)


def _interface_count_blocks_order_basis(order_payload: dict[str, Any]) -> bool:
    """True only when the interface count is proven to be more than one."""

    if INTERFACE_COUNT_FIELD not in order_payload:
        return False
    count = parse_receipt_amount_cent(order_payload.get(INTERFACE_COUNT_FIELD))
    return count is not None and count > 1


def resolve_coupon_receipt_cent(
    session: Session,
    order: RawDouyinOrder,
    coupon: RawDouyinOrderCoupon,
    *,
    attribution: OrderAttribution | None = None,
) -> int | None:
    """Return the proven receipt basis in cents for ``coupon``, else ``None``.

    Resolution order is coupon-level receipt, uniquely attributed sub-order
    receipt (or the proven full sub-order sum for a single-coupon order), then a
    single-coupon order total. A field that exists but is unusable is corrupt
    evidence and blocks; it never silently falls through to a broader total.
    ``attribution`` may carry already-loaded coupon counts for a batch run.
    """

    coupon_payload = _payload_of(coupon.raw_payload)
    if RECEIPT_AMOUNT_FIELD in coupon_payload:
        # Present-but-unusable coupon evidence must fail closed, not fall back.
        return parse_receipt_amount_cent(coupon_payload.get(RECEIPT_AMOUNT_FIELD))

    order_payload = _payload_of(order.raw_payload)
    sub_orders = SubOrderReceipts.from_payload(order_payload)
    if sub_orders.corrupt:
        # Present-but-unusable sub-order evidence (field exists but is not a
        # list) blocks every path; it must never fall through to the order total.
        return None
    coupon_count = (
        attribution.coupon_count
        if attribution is not None
        else _order_coupon_count(session, order)
    )

    if coupon_count != 1:
        # Several coupons must each own a proven item; never split the total.
        item_id = coupon.order_item_id
        if isinstance(item_id, str) and item_id:
            if item_id in sub_orders.unusable:
                return None
            if item_id in sub_orders.unique:
                if _item_share_count(session, order, item_id, attribution) != 1:
                    return None
                return sub_orders.unique[item_id]
        return None

    # Exactly one coupon: the order is this coupon's basis, but only when the
    # interface does not prove the order carried more units than were collected.
    if _interface_count_blocks_order_basis(order_payload):
        return None
    if sub_orders.entries_present:
        # Use the interface's own full line sum, or block. A single proven line
        # must never stand in for a partial or corrupt list.
        return sub_orders.complete_total
    if RECEIPT_AMOUNT_FIELD in order_payload:
        return parse_receipt_amount_cent(order_payload.get(RECEIPT_AMOUNT_FIELD))
    return None
