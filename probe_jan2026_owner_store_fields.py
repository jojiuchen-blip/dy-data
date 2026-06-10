import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import supplement_affected_months as dy

from src.dy_data.config import path_value

OUT_DIR = path_value("field_probe_dir", env_name="FIELD_PROBE_DIR")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_WORDS = [
    "role",
    "达人",
    "带货",
    "owner",
    "belong",
    "归属",
    "nickname",
    "nick",
    "昵称",
    "verify",
    "核销",
    "poi",
    "shop",
    "store",
    "门店",
]


def walk(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, item
            yield from walk(item, path)
    elif isinstance(value, list):
        for idx, item in enumerate(value[:3]):
            path = f"{prefix}[{idx}]"
            yield path, item
            yield from walk(item, path)


def is_interesting(path: str) -> bool:
    text = path.lower()
    return any(word.lower() in text for word in TARGET_WORDS)


def fetch_january_sample(token: str, max_days: int = 31, max_pages_per_day: int = 5):
    orders = []
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": dy.ACCOUNT_ID,
    }
    day = datetime(2026, 1, 1)
    end = datetime(2026, 2, 1)
    while day < end and (day - datetime(2026, 1, 1)).days < max_days:
        next_day = day + timedelta(days=1)
        for page in range(1, max_pages_per_day + 1):
            params = {
                "account_id": dy.ACCOUNT_ID,
                "page_num": page,
                "page_size": dy.PAGE_SIZE,
                "create_order_start_time": int(day.timestamp()),
                "create_order_end_time": int(next_day.timestamp()),
            }
            payload = dy.get_json_with_retry(dy.API_URL, headers=headers, params=params)
            data = payload.get("data") or {}
            page_orders = data.get("orders") or data.get("list") or []
            if not page_orders:
                break
            orders.extend(page_orders)
            if len(page_orders) < dy.PAGE_SIZE:
                break
            time.sleep(float(os.getenv("DOUYIN_REQUEST_SLEEP_SECONDS", "0.2")))
        day = next_day
    return orders


def main() -> None:
    dy.require_config()
    token = dy.get_token()
    max_days = int(os.getenv("PROBE_MAX_DAYS", "31"))
    max_pages = int(os.getenv("PROBE_MAX_PAGES_PER_DAY", "5"))
    orders = fetch_january_sample(token, max_days=max_days, max_pages_per_day=max_pages)
    all_paths: dict[str, Any] = {}
    interesting: dict[str, Any] = {}
    for order in orders:
        for path, value in walk(order):
            if path not in all_paths and not isinstance(value, (dict, list)):
                all_paths[path] = value
            if is_interesting(path) and path not in interesting and not isinstance(value, (dict, list)):
                interesting[path] = value

    sample_path = OUT_DIR / "jan2026_order_sample.json"
    fields_path = OUT_DIR / "jan2026_field_probe.json"
    sample_path.write_text(json.dumps(orders[:20], ensure_ascii=False, indent=2), encoding="utf-8")
    fields_path.write_text(
        json.dumps(
            {
                "sample_order_count": len(orders),
                "interesting_fields": interesting,
                "all_scalar_fields": all_paths,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "sample_order_count": len(orders),
                "sample_path": str(sample_path),
                "fields_path": str(fields_path),
                "interesting_fields": interesting,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
