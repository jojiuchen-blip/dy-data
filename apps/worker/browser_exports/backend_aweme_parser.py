from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from apps.worker.collectors.normalizers import text


HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "douyin_nickname": ("抖音昵称", "抖音号昵称", "nickname", "douyin_nickname"),
    "douyin_id": ("抖音id", "抖音ID", "抖音号", "aweme_id", "aweme_short_id", "douyin_id"),
    "account_id": ("所属账户id", "所属账户ID", "账户id", "职人UID", "account_id", "craftsman_uid"),
    "account_name": ("所属账户名称", "所属账户", "认证主体", "商家主体", "account_name"),
    "poi_id": ("所属账户关联poi_id", "所属账户关联POI_ID", "关联poi_id", "绑定门店ID", "poi_id"),
    "binding_status": ("抖音号绑定状态", "绑定状态", "bind_status", "binding_status"),
}


def parse_backend_aweme_workbook(path: str | Path) -> list[dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [_cell_text(value) for value in rows[0]]
    records: list[dict[str, Any]] = []
    for raw_row in rows[1:]:
        raw_payload = {
            header: _cell_text(raw_row[index]) if index < len(raw_row) else ""
            for index, header in enumerate(headers)
            if header
        }
        if not any(raw_payload.values()):
            continue
        record = {
            "douyin_nickname": _alias_value(raw_payload, "douyin_nickname"),
            "douyin_id": _alias_value(raw_payload, "douyin_id"),
            "account_id": _alias_value(raw_payload, "account_id"),
            "account_name": _alias_value(raw_payload, "account_name"),
            "poi_id": _alias_value(raw_payload, "poi_id"),
            "binding_status": _alias_value(raw_payload, "binding_status"),
            "raw_payload": raw_payload,
        }
        if any(record[key] for key in ("douyin_nickname", "douyin_id", "account_id", "poi_id")):
            records.append(record)
    return records


def _alias_value(raw_payload: dict[str, str], field: str) -> str | None:
    for alias in HEADER_ALIASES[field]:
        value = text(raw_payload.get(alias))
        if value:
            return value
    return None


def _cell_text(value: Any) -> str:
    return text(value) or ""

