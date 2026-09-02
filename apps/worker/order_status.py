from __future__ import annotations

from typing import Any, Iterable


# Douyin's local-life order API returns numeric values. The raw value remains
# stored separately; these values are the stable application vocabulary.
ACTIVE_ORDER_STATUSES = {"201", "履约中", "待使用"}
COMPLETED_ORDER_STATUSES = {
    "1",
    "已完成",
    "已核销",
    "交易成功",
    "completed",
    "fulfilled",
    "transaction_success",
}
PAID_ORDER_STATUSES = {"200", "paid", "success", "payment_success", "支付成功"}
CLOSED_ORDER_STATUSES = {
    "101",
    "closed",
    "cancelled",
    "canceled",
    "unpaid_closed",
    "支付取消",
    "交易关闭",
}
REFUNDED_ORDER_STATUSES = {"300", "301", "refund", "refunded", "fully_refunded", "已退款"}

ACTIVE_COUPON_STATUSES = {"100", "200", "201", "400", "available", "unused", "valid"}
VERIFIED_COUPON_STATUSES = {
    "1",
    "401",
    "fulfilled",
    "verified",
    "used",
    "success",
    "transaction_success",
}
REFUNDED_COUPON_STATUSES = {"301", "refund", "refunded", "fully_refunded"}
CLOSED_COUPON_STATUSES = {"101", "closed", "cancelled", "canceled", "交易关闭"}


def normalize_order_status(value: Any, payload: dict[str, Any] | None = None) -> str:
    """Normalize a platform order for the raw order and settlement layers."""

    status = _status_text(value)
    certificates = certificate_statuses(payload)
    if status in CLOSED_ORDER_STATUSES:
        return "closed"
    if status in REFUNDED_ORDER_STATUSES or _all_certificates_refunded(certificates):
        return "refunded"
    if _all_certificates_closed(certificates):
        return "closed"
    if status in ACTIVE_ORDER_STATUSES or status in PAID_ORDER_STATUSES:
        return "paid"
    if status in COMPLETED_ORDER_STATUSES or status == "150":
        # Numeric 1 means completed履约 or fully refunded. If all certificates
        # are not refunded, the order is safe to treat as paid for settlement.
        return "paid"
    return "unknown"


def resolve_clue_order_status(
    value: Any,
    payload: dict[str, Any] | None = None,
    *,
    normalized_order_status: Any | None = None,
    coupon_statuses: Iterable[Any] | None = None,
) -> str:
    """Resolve the business status used by the clue master.

    Paid and waiting-use orders can enter the clue pool. Numeric 1 is terminal
    but needs certificate evidence to distinguish completed履约 from
    all-refunded. Missing evidence remains unknown and is quarantined by
    materialization.
    """

    status = _status_text(value)
    certificates = certificate_statuses(payload)
    normalized_order = _status_text(normalized_order_status)
    normalized_coupons = {
        _status_text(coupon_status)
        for coupon_status in (coupon_statuses or ())
        if _status_text(coupon_status)
    }
    if status in CLOSED_ORDER_STATUSES:
        return "closed"
    if status in REFUNDED_ORDER_STATUSES or _all_certificates_refunded(certificates):
        return "refunded"
    # Order/coupon projections are populated from separate Douyin endpoints.
    # Use them when the order payload does not embed certificate details.
    if normalized_order == "closed":
        return "closed"
    if normalized_order == "refunded":
        return "refunded"
    if normalized_coupons and normalized_coupons <= CLOSED_COUPON_STATUSES:
        return "closed"
    if normalized_coupons and normalized_coupons <= REFUNDED_COUPON_STATUSES:
        return "refunded"
    if (
        normalized_coupons
        and normalized_coupons & VERIFIED_COUPON_STATUSES
        and not normalized_coupons & ACTIVE_COUPON_STATUSES
    ):
        return "verified"
    if status in ACTIVE_ORDER_STATUSES or status in PAID_ORDER_STATUSES:
        if _all_certificates_closed(certificates):
            return "closed"
        if _has_verified_certificate(certificates) and not _has_active_certificate(certificates):
            return "verified"
        return "active"
    if status in COMPLETED_ORDER_STATUSES:
        if _all_certificates_closed(certificates):
            return "closed"
        if _has_verified_certificate(certificates):
            return "verified"
        # A textual terminal value is explicit. Numeric 1 is ambiguous without
        # certificate evidence because Douyin documents it as completed or
        # fully refunded.
        return "verified" if status != "1" else "unknown"
    # Payment success alone is not the same as a coupon entering 待使用.
    return "unknown"


def normalize_coupon_status(value: Any) -> str:
    status = _status_text(value)
    if status in REFUNDED_COUPON_STATUSES:
        return "refunded"
    if status in VERIFIED_COUPON_STATUSES:
        return "verified"
    if status in ACTIVE_COUPON_STATUSES:
        return "available"
    if status in CLOSED_COUPON_STATUSES:
        return "closed"
    if status in {"300", "cancelled", "canceled", "revoked", "reversed", "refund_pending"}:
        return "cancelled"
    return "unknown"


def certificate_statuses(payload: dict[str, Any] | None) -> list[tuple[str, str | None]]:
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("certificate", "certificates", "certificate_list", "coupons", "coupon_list"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    if not rows:
        order_items = payload.get("order_items") or payload.get("items") or []
        if isinstance(order_items, list):
            for item in order_items:
                if not isinstance(item, dict):
                    continue
                nested = item.get("certificates") or item.get("coupons") or []
                if isinstance(nested, list):
                    rows.extend(row for row in nested if isinstance(row, dict))
    return [
        (
            _status_text(row.get("item_status", row.get("coupon_status", row.get("status")))),
            _refund_time_text(row.get("refund_time", row.get("coupon_refund_time"))),
        )
        for row in rows
    ]


def _all_certificates_refunded(certificates: list[tuple[str, str | None]]) -> bool:
    return bool(certificates) and all(
        _is_refunded_certificate(status, refund_time) for status, refund_time in certificates
    )


def _has_verified_certificate(certificates: list[tuple[str, str | None]]) -> bool:
    return any(status in VERIFIED_COUPON_STATUSES for status, _ in certificates)


def _has_active_certificate(certificates: list[tuple[str, str | None]]) -> bool:
    return any(status in ACTIVE_COUPON_STATUSES for status, _ in certificates)


def _all_certificates_closed(certificates: list[tuple[str, str | None]]) -> bool:
    return bool(certificates) and all(
        status in CLOSED_COUPON_STATUSES for status, _ in certificates
    )


def _is_refunded_certificate(status: str, refund_time: str | None) -> bool:
    return status in REFUNDED_COUPON_STATUSES or bool(refund_time and refund_time != "0")


def _status_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    result = str(value).strip().lower().replace("-", "_")
    if result.endswith(".0"):
        result = result[:-2]
    return result


def _refund_time_text(value: Any) -> str | None:
    if value in (None, "", 0, "0"):
        return None
    return str(value).strip() or None
