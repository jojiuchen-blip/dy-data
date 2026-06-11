import csv
import json
import os
import time
from datetime import datetime
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import douyin_account_id, douyin_app_id, douyin_app_secret, path_value


OUT_DIR = path_value("field_probe_dir", env_name="FIELD_PROBE_DIR")
OUT_DIR.mkdir(parents=True, exist_ok=True)

APP_ID = douyin_app_id()
APP_SECRET = douyin_app_secret()
ACCOUNT_ID = douyin_account_id()

API_URL = "https://open.douyin.com/goodlife/v2/craftsman_openapi/merchat/craftsman/bind_info/all/"

BIND_STATUS_MAP = {
    1: "待确认",
    2: "绑定中",
    3: "已拒绝",
    4: "已解绑",
    5: "已失效",
}

PAYMENT_STATUS_MAP = {
    1: "未开通",
    2: "已开通",
}


def require_config() -> None:
    missing = []
    if not APP_ID:
        missing.append("DOUYIN_APP_ID")
    if not APP_SECRET:
        missing.append("DOUYIN_APP_SECRET")
    if not ACCOUNT_ID:
        missing.append("DOUYIN_ACCOUNT_ID")
    if missing:
        raise RuntimeError("请先设置环境变量或 config.local.json：" + ", ".join(missing))


def normalize_id(value: Any) -> str:
    if value in ("", None):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def format_time(value: Any) -> str:
    if value in ("", None, 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def get_client_token() -> str:
    response = requests.post(
        "https://open.douyin.com/oauth/client_token/",
        json={
            "client_key": APP_ID,
            "client_secret": APP_SECRET,
            "grant_type": "client_credential",
        },
        timeout=20,
    )
    data = response.json()
    token = data.get("data", {}).get("access_token")
    if not token:
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    return token


def request_page(token: str, cursor: str, size: int = 50) -> dict[str, Any]:
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    params = {"account_id": ACCOUNT_ID, "cursor": str(cursor), "size": str(size)}
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = requests.get(API_URL, headers=headers, params=params, timeout=30)
            data = response.json()
            body = data.get("data") or {}
            code = body.get("error_code", data.get("extra", {}).get("error_code"))
            if code in (None, 0, "0"):
                return data
            print(f"cursor={cursor} attempt={attempt} error={json.dumps(data, ensure_ascii=False)}")
        except Exception as exc:
            last_error = exc
            print(f"cursor={cursor} attempt={attempt} exception={exc}")
        time.sleep(min(20, attempt * 3))
    if last_error:
        raise last_error
    return data


def fetch_all() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    token = get_client_token()
    cursor = "0"
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    seen_cursors = set()

    while True:
        data = request_page(token, cursor)
        pages.append(data)
        body = data.get("data") or {}
        code = body.get("error_code", data.get("extra", {}).get("error_code"))
        if code not in (None, 0, "0"):
            raise RuntimeError(json.dumps(data, ensure_ascii=False))
        items = body.get("openapi_merchat_craftsman_info") or []
        rows.extend(items)

        next_cursor = str(body.get("cursor") or "").strip()
        has_more = bool(body.get("has_more"))
        print(f"cursor={cursor} 本页={len(items)} 累计={len(rows)} has_more={has_more}")
        if not has_more or not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        cursor = next_cursor
        time.sleep(0.2)
    return rows, pages


def to_row(item: dict[str, Any]) -> dict[str, Any]:
    bind_status = item.get("bind_status")
    payment_status = item.get("payment_status")
    return {
        "抖音号昵称": item.get("nickname", ""),
        "抖音号": item.get("aweme_short_id", ""),
        "职人UID": item.get("craftsman_uid", ""),
        "绑定门店ID": normalize_id(item.get("poi_id")),
        "绑定门店名称": item.get("poi_account_name", ""),
        "商家账号ID": normalize_id(item.get("account_id")),
        "商家主体": item.get("account_name", ""),
        "绑定状态码": bind_status,
        "绑定状态": BIND_STATUS_MAP.get(bind_status, bind_status),
        "绑定开始时间": format_time(item.get("bind_start_time")),
        "绑定结束时间": format_time(item.get("bind_end_time")),
        "合作模式": item.get("cooperation_mode", ""),
        "支付状态码": payment_status,
        "支付状态": PAYMENT_STATUS_MAP.get(payment_status, payment_status),
        "实名信息": item.get("real_name", ""),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "抖音号昵称",
        "抖音号",
        "职人UID",
        "绑定门店ID",
        "绑定门店名称",
        "商家账号ID",
        "商家主体",
        "绑定状态码",
        "绑定状态",
        "绑定开始时间",
        "绑定结束时间",
        "合作模式",
        "支付状态码",
        "支付状态",
        "实名信息",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    require_config()
    items, pages = fetch_all()
    rows = [to_row(item) for item in items]
    csv_path = OUT_DIR / "职人绑定信息列表_测试.csv"
    raw_path = OUT_DIR / "职人绑定信息列表_测试_raw.json"
    summary_path = OUT_DIR / "职人绑定信息列表_测试_summary.json"

    write_csv(csv_path, rows)
    raw_path.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "rows": len(rows),
        "with_nickname": sum(1 for row in rows if row.get("抖音号昵称")),
        "with_poi_id": sum(1 for row in rows if row.get("绑定门店ID")),
        "with_poi_name": sum(1 for row in rows if row.get("绑定门店名称")),
        "bind_status_counts": {},
        "csv_path": str(csv_path),
        "raw_path": str(raw_path),
    }
    for row in rows:
        key = str(row.get("绑定状态"))
        summary["bind_status_counts"][key] = summary["bind_status_counts"].get(key, 0) + 1
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
