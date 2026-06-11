import csv
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

import douyin_verify_record_export as verify
import supplement_affected_months as orders_api
from export_jan2026_sale_owner_store_test import ORDER_CACHE, OUT_DIR, row_from_order, write_csv


VERIFY_NAME_CACHE_DIR = OUT_DIR / "jan2026_verify_name_days"
VERIFY_NAME_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def fetch_verify_day(token: str, start: datetime, end: datetime) -> list[dict]:
    cache_path = VERIFY_NAME_CACHE_DIR / f"verify_{start:%Y%m%d}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    for _ in range(3):
        try:
            records = verify.fetch_verify_records(token, start, end, retry=8)
            cache_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            return records
        except RuntimeError as exc:
            if "access_token" not in str(exc):
                raise
            token = verify.get_token()
    raise RuntimeError(f"核销记录接口 token 刷新后仍失败: {start:%Y-%m-%d}")


def build_verify_name_lookup() -> dict[str, dict[str, str]]:
    token = verify.get_token()
    lookup: dict[str, dict[str, str]] = {}
    current = datetime(2026, 1, 1)
    end_month = datetime(2026, 2, 1)
    while current < end_month:
        next_day = current + timedelta(days=1)
        records = fetch_verify_day(token, current, next_day)
        for record in records:
            cert_id = orders_api.normalize_id(record.get("certificate_id"))
            if not cert_id:
                continue
            store_name = str(record.get("fulfil_operator_name") or "").strip()
            lookup[cert_id] = {
                "核销门店ID": "",
                "核销门店名称": store_name,
                "核销操作人": store_name,
                "核销时间_核销记录": orders_api.format_time(record.get("verify_time")),
            }
        print(f"{current:%Y-%m-%d} 核销记录 {len(records)} 条，累计券 {len(lookup)}")
        current = next_day
        time.sleep(0.1)
    return lookup


def main() -> None:
    orders = json.loads(ORDER_CACHE.read_text(encoding="utf-8"))
    verify_lookup = build_verify_name_lookup()
    rows = [
        row_from_order(order, verify_lookup)
        for order in orders
        if (order.get("order_sale_info") or {}).get("sale_role") == "商家"
    ]

    csv_path = OUT_DIR / "抖音订单_2026年01月_商家_核销门店名称测试.csv"
    summary_path = OUT_DIR / "抖音订单_2026年01月_商家_核销门店名称测试_summary.json"
    write_csv(csv_path, rows)
    summary = {
        "month": "2026-01",
        "raw_target_sku_orders": len(orders),
        "sale_role_filter": "商家",
        "orders": len(rows),
        "verify_certificates": len(verify_lookup),
        "with_owner_nickname": sum(1 for row in rows if row.get("订单归属人昵称")),
        "with_verify_store_name": sum(1 for row in rows if row.get("核销门店名称")),
        "csv_path": str(csv_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
