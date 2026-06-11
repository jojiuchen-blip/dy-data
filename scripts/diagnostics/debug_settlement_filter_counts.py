import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))
from build_settlement_base_from_current_data import BASE_TABLE, START_DATE, TODAY, is_refunded, parse_datetime, parse_json


def main() -> None:
    counts = {
        "source_rows": 0,
        "in_180d_by_order_time": 0,
        "with_verify_time": 0,
        "in_180d_and_with_verify_time": 0,
        "not_refunded_after_time_verify": 0,
        "sale_role_merchant_after_filters": 0,
        "coupon_fulfilled_in_180d": 0,
        "coupon_fulfilled_not_refunded": 0,
        "merchant_coupon_fulfilled_not_refunded": 0,
    }
    examples = []
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            counts["source_rows"] += 1
            created_at = parse_datetime(row.get("下单时间", ""))
            verified_at = parse_datetime(row.get("核销时间", ""))
            in_180d = bool(created_at and START_DATE <= created_at <= TODAY)
            if in_180d:
                counts["in_180d_by_order_time"] += 1
            if verified_at:
                counts["with_verify_time"] += 1
            if in_180d and verified_at:
                counts["in_180d_and_with_verify_time"] += 1
                if not is_refunded(row):
                    counts["not_refunded_after_time_verify"] += 1
                    sale_info = parse_json(row.get("order_sale_info", ""), {})
                    if isinstance(sale_info, dict) and sale_info.get("sale_role") == "商家":
                        counts["sale_role_merchant_after_filters"] += 1

            coupon_status = row.get("券状态", "")
            fulfilled = "已履约" in coupon_status
            if in_180d and fulfilled:
                counts["coupon_fulfilled_in_180d"] += 1
                if not is_refunded(row):
                    counts["coupon_fulfilled_not_refunded"] += 1
                    sale_info = parse_json(row.get("order_sale_info", ""), {})
                    if isinstance(sale_info, dict) and sale_info.get("sale_role") == "商家":
                        counts["merchant_coupon_fulfilled_not_refunded"] += 1
                        if len(examples) < 5:
                            examples.append(
                                {
                                    "订单ID": row.get("订单ID"),
                                    "下单时间": row.get("下单时间"),
                                    "核销时间": row.get("核销时间"),
                                    "更新时间": row.get("更新时间"),
                                    "券状态": coupon_status,
                                    "sale_role": sale_info.get("sale_role"),
                                    "owner": sale_info.get("transfer_nickName"),
                                }
                            )
    print(json.dumps({"counts": counts, "examples": examples}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
