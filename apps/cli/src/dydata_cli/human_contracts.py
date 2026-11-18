"""Validated, credential-free contracts for the separate human product console."""

from __future__ import annotations

from typing import Any

from .client import CliError


HOUR_FIELDS = {
    "first_follow_up_sla_hours": 168,
    "appointment_hours": 8760,
    "further_follow_up_hours": 8760,
    "unreachable_hours": 8760,
}
ACTION_FIELDS = {
    "pending_action", "appointment_action", "further_follow_up_action", "unreachable_action",
}
PRODUCT_ERRORS = {
    "PRODUCT_FORBIDDEN": "无权管理该商品。",
    "STORE_IDS_REQUIRED": "需要有效门店名单。",
    "UNKNOWN_STORE_IDS": "名单包含未知或无效门店编码。",
    "PUBLISHED_LIST_REQUIRED": "请先成功发布该商品的有效名单。",
    "AUTHORIZATION_REQUIRED": "开启需要明确的业务授权说明。",
    "INVALID_RULE": "规则字段或取值无效。",
    "PRODUCT_NOT_FOUND": "商品不存在。",
    "CONFLICT": "商品状态冲突，请刷新预览后重试。",
    "PRODUCT_LIMIT_EXCEEDED": "商品数量超过单批限制，请缩小范围。",
    "PREVIEW_REQUIRED": "开启前必须重新预览并确认当前已发布的有效名单。",
    "LIST_VERSION_CHANGED": "适用名单已在预览后变更，本次开启未执行；请重新预览并确认当前版本。",
    "PRODUCT_NOT_ENABLED": "本品首次开启前继承精诚共享基座，请先按已确认名单开启，之后可发布独立规则。",
}


def require_text(value: Any, *, empty: bool = False) -> str:
    """Require normalized printable text before displaying external values."""
    if not isinstance(value, str) or value != value.strip():
        raise CliError("SCHEMA_MISMATCH")
    if (not value and not empty) or (value and not value.isprintable()):
        raise CliError("SCHEMA_MISMATCH")
    return value


def require_ids(value: Any, *, empty: bool = True) -> list[str]:
    """Require a unique list of terminal-safe identifiers."""
    if not isinstance(value, list):
        raise CliError("SCHEMA_MISMATCH")
    result = [require_text(item) for item in value]
    if len(result) != len(set(result)) or (not empty and not result):
        raise CliError("SCHEMA_MISMATCH")
    return result


def validate_rule_patch(value: Any) -> dict[str, Any]:
    """Allow only supported field patches, preserving omitted fields."""
    if not isinstance(value, dict):
        raise CliError("INVALID_ARGUMENT")
    flat = dict(value)
    nested = flat.pop("follow_up_policy", {})
    if not isinstance(nested, dict) or set(flat) & set(nested):
        raise CliError("INVALID_ARGUMENT")
    if "first_follow_up_sla_hours" in nested:
        raise CliError("INVALID_ARGUMENT")
    flat.update(nested)
    if not flat or set(flat) - HOUR_FIELDS.keys() - ACTION_FIELDS:
        raise CliError("INVALID_ARGUMENT")
    for key, item in flat.items():
        if key in HOUR_FIELDS:
            if type(item) is not int or not 1 <= item <= HOUR_FIELDS[key]:
                raise CliError("INVALID_ARGUMENT")
        elif not isinstance(item, str) or item not in {"next", "close"}:
            raise CliError("INVALID_ARGUMENT")
    return flat


def product_snapshot(value: Any) -> dict[str, Any]:
    """Select known business fields; never forward arbitrary server fields."""
    if not isinstance(value, dict):
        raise CliError("SCHEMA_MISMATCH")
    if not value:
        return {}
    result: dict[str, Any] = {
        "product_id": require_text(value.get("product_id")),
        "product_name": require_text(value.get("product_name"), empty=True),
        "product_scope": require_text(value.get("product_scope")),
        "store_ids": require_ids(value.get("store_ids")),
    }
    for key in ("routing_enabled", "can_manage"):
        if type(value.get(key)) is not bool:
            raise CliError("SCHEMA_MISMATCH")
        result[key] = value[key]
    for key in ("rule_version_id", "list_version"):
        item = value.get(key)
        if item is not None and type(item) is not int:
            item = require_text(item)
        result[key] = item
    hours = value.get("first_follow_up_sla_hours")
    if type(hours) is not int or not 1 <= hours <= 168:
        raise CliError("SCHEMA_MISMATCH")
    result["first_follow_up_sla_hours"] = hours
    policy = value.get("follow_up_policy")
    if not isinstance(policy, dict):
        raise CliError("SCHEMA_MISMATCH")
    try:
        result["follow_up_policy"] = validate_rule_patch(policy) if policy else {}
    except CliError:
        raise CliError("SCHEMA_MISMATCH") from None
    if value.get("proposed_change") is True:
        result["proposed_change"] = True
    return result


def validate_results(value: Any, *, preview: bool) -> list[dict[str, Any]]:
    """Validate item status and whitelist useful business errors and snapshots."""
    if not isinstance(value, list):
        raise CliError("SCHEMA_MISMATCH")
    results = []
    for row in value:
        if not isinstance(row, dict):
            raise CliError("SCHEMA_MISMATCH")
        product_id = require_text(row.get("product_id"))
        status = row.get("status")
        if status not in {"failed", "preview" if preview else "success"}:
            raise CliError("SCHEMA_MISMATCH")
        result = {
            "product_id": product_id, "status": status,
            "before": product_snapshot(row.get("before", {})),
            "after": product_snapshot(row.get("after", {})),
        }
        if status != "failed" and (
            result["before"].get("product_id") != product_id
            or result["after"].get("product_id") != product_id
        ):
            raise CliError("SCHEMA_MISMATCH")
        if status == "failed":
            error = row.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            code = code if code in PRODUCT_ERRORS else "CONFLICT"
            result["error"] = {"code": code, "message": PRODUCT_ERRORS[code]}
        results.append(result)
    require_ids([row["product_id"] for row in results])
    return results
