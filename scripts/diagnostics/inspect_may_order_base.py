import csv
import json
from collections import Counter
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import path_value

ORDER_CSV = path_value("base_table", env_name="BASE_TABLE")


def parse_time(text):
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def main():
    total = may = merchant = cert_rows = cert_ids = 0
    status = Counter()
    sale_roles = Counter()
    owner_empty = 0
    examples = []
    with ORDER_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            total += 1
            dt = parse_time(row.get("下单时间"))
            if not dt or dt.year != 2026 or dt.month != 5:
                continue
            may += 1
            status[row.get("订单状态", "")] += 1
            info = {}
            try:
                info = json.loads(row.get("order_sale_info") or "{}")
            except Exception:
                pass
            role = info.get("sale_role", "")
            sale_roles[role] += 1
            if role == "商家":
                merchant += 1
            if not info.get("transfer_nickName"):
                owner_empty += 1
            try:
                certs = json.loads(row.get("certificate") or "[]")
            except Exception:
                certs = []
            if certs:
                cert_rows += 1
                cert_ids += sum(1 for c in certs if c.get("certificate_id"))
            if len(examples) < 3 and certs:
                examples.append({
                    "订单ID": row.get("订单ID"),
                    "订单状态": row.get("订单状态"),
                    "实付金额": row.get("实付金额"),
                    "商品类型": row.get("商品类型"),
                    "SKU_ID": row.get("SKU_ID"),
                    "owner": info.get("transfer_nickName"),
                    "sale_role": role,
                    "certificates": certs[:2],
                })

    print(json.dumps({
        "total_rows": total,
        "may2026_rows": may,
        "may2026_order_status": dict(status),
        "may2026_sale_roles": dict(sale_roles),
        "may2026_merchant_rows": merchant,
        "may2026_rows_with_certificate": cert_rows,
        "may2026_certificate_ids": cert_ids,
        "may2026_owner_nickname_empty": owner_empty,
        "examples": examples,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
