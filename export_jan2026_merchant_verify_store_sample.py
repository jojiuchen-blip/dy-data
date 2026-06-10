import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import douyin_verify_record_export as verify
import supplement_affected_months as orders_api
from export_jan2026_sale_owner_store_test import ORDER_CACHE, OUT_DIR, row_from_order, write_csv


def order_time(order):
    value = order.get("create_order_time")
    return datetime.fromtimestamp(int(value)) if value else None


def build_verify_lookup(start: datetime, end: datetime):
    token = verify.get_token()
    records = verify.fetch_verify_records(token, start, end, retry=8)
    pois = verify.fetch_shop_pois(verify.get_token(), retry=3)
    poi_id_by_name = {poi.get("poi_name", "").strip(): poi.get("poi_id", "") for poi in pois}

    lookup = {}
    for record in records:
        cert_id = orders_api.normalize_id(record.get("certificate_id"))
        if not cert_id:
            continue
        store_name = str(record.get("fulfil_operator_name") or "").strip()
        lookup[cert_id] = {
            "核销门店ID": poi_id_by_name.get(store_name, ""),
            "核销门店名称": store_name,
            "核销操作人": store_name,
            "核销时间_核销记录": orders_api.format_time(record.get("verify_time")),
        }
    return lookup


def main() -> None:
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 4)
    orders = json.loads(ORDER_CACHE.read_text(encoding="utf-8"))
    filtered_orders = []
    for order in orders:
        created = order_time(order)
        if not created or not (start <= created < end):
            continue
        if (order.get("order_sale_info") or {}).get("sale_role") != "商家":
            continue
        filtered_orders.append(order)

    verify_lookup = build_verify_lookup(start, end)
    rows = [row_from_order(order, verify_lookup) for order in filtered_orders]

    csv_path = OUT_DIR / "抖音订单_2026年01月1-3日_商家_核销门店回填测试.csv"
    summary_path = OUT_DIR / "抖音订单_2026年01月1-3日_商家_核销门店回填测试_summary.json"
    write_csv(csv_path, rows)
    summary = {
        "date_range": "2026-01-01 至 2026-01-03",
        "merchant_orders": len(rows),
        "verify_records_by_certificate": len(verify_lookup),
        "with_verify_store_name": sum(1 for row in rows if row.get("核销门店名称")),
        "with_verify_store_id": sum(1 for row in rows if row.get("核销门店ID")),
        "csv_path": str(csv_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
