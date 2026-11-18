"""Validated follow-up settings shared by product publication and lead binding."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_FOLLOW_UP_POLICY = {
    "appointment_hours": 72,
    "further_follow_up_hours": 168,
    "unreachable_hours": 168,
    "pending_action": "next",
    "appointment_action": "next",
    "further_follow_up_action": "next",
    "unreachable_action": "close",
}
HOUR_POLICY_KEYS = frozenset({"appointment_hours", "further_follow_up_hours", "unreachable_hours"})
ACTION_POLICY_KEYS = frozenset(DEFAULT_FOLLOW_UP_POLICY) - HOUR_POLICY_KEYS


def normalize_follow_up_policy(value: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a complete validated policy, preserving supported partial patches."""
    if value is not None and not isinstance(value, Mapping):
        raise ValueError("保护期规则须为对象")
    unknown = set(value or {}) - set(DEFAULT_FOLLOW_UP_POLICY)
    if unknown:
        raise ValueError("包含不支持的保护期字段")
    result = {**DEFAULT_FOLLOW_UP_POLICY, **dict(value or {})}
    for key in HOUR_POLICY_KEYS:
        hours = result[key]
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 8760:
            raise ValueError("保护期须为 1 至 8760 的整数小时")
    for key in ACTION_POLICY_KEYS:
        if result[key] not in {"next", "close"}:
            raise ValueError("到期动作仅支持 next 或 close")
    return result
