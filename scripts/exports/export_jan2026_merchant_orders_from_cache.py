import json
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from export_jan2026_sale_owner_store_test import ORDER_CACHE, OUT_DIR, row_from_order, write_csv


def main() -> None:
    orders = json.loads(ORDER_CACHE.read_text(encoding="utf-8"))
    rows = [
        row_from_order(order, {})
        for order in orders
        if (order.get("order_sale_info") or {}).get("sale_role") == "商家"
    ]
    csv_path = OUT_DIR / "抖音订单_2026年01月_带货角色商家_测试.csv"
    summary_path = OUT_DIR / "抖音订单_2026年01月_带货角色商家_测试_summary.json"
    write_csv(csv_path, rows)
    summary = {
        "raw_target_sku_orders": len(orders),
        "sale_role_filter": "商家",
        "orders": len(rows),
        "with_owner_nickname": sum(1 for row in rows if row.get("订单归属人昵称")),
        "with_sale_channel": sum(1 for row in rows if row.get("销售渠道")),
        "with_verify_store_name": sum(1 for row in rows if row.get("核销门店名称")),
        "note": "核销门店需要单独跑核销记录接口回填；本文件先验证订单接口中的带货角色和订单归属人字段。",
        "csv_path": str(csv_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
