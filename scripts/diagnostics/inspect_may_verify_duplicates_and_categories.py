import csv
import json
from collections import Counter, defaultdict
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import path_value, sku_type_map


VERIFY_JSON = path_value("may_verify_dir") / "may2026_verify_records_by_poi.json"
ORDER_CSV = path_value("base_table", env_name="BASE_TABLE")

SKU_TO_PRODUCT_TYPE = sku_type_map()


def clean(value):
    return str(value or "").strip()


def main():
    verify_rows = json.loads(VERIFY_JSON.read_text(encoding="utf-8"))
    by_cert = defaultdict(list)
    for row in verify_rows:
        cert_id = clean(row.get("certificate_id"))
        if cert_id:
            by_cert[cert_id].append(row)

    duplicate_groups = {cert: rows for cert, rows in by_cert.items() if len(rows) > 1}
    duplicate_summary = []
    same_store = 0
    diff_store = 0
    for cert, rows in duplicate_groups.items():
        stores = sorted({clean(r.get("verify_poi_id")) for r in rows})
        statuses = sorted({clean(r.get("status")) for r in rows})
        if len(stores) == 1:
            same_store += 1
        else:
            diff_store += 1
        duplicate_summary.append({
            "券ID": cert,
            "记录数": len(rows),
            "不同核销门店数": len(stores),
            "核销门店ID": stores,
            "核销门店名称": sorted({clean(r.get("verify_poi_name")) for r in rows}),
            "状态": statuses,
            "核销时间": sorted([clean(r.get("verify_time")) for r in rows]),
        })

    verify_category_counts = Counter()
    verify_unique_category_counts = Counter()
    seen_cert_category = {}
    for row in verify_rows:
        sku = row.get("sku") or {}
        sku_id = clean(sku.get("sku_id"))
        category = SKU_TO_PRODUCT_TYPE.get(sku_id, "其他商品")
        verify_category_counts[category] += 1
        cert_id = clean(row.get("certificate_id"))
        if cert_id:
            seen_cert_category.setdefault(cert_id, category)
    verify_unique_category_counts.update(seen_cert_category.values())

    order_cert_category = {}
    with ORDER_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sku_id = clean(row.get("SKU_ID"))
            category = SKU_TO_PRODUCT_TYPE.get(sku_id, "其他商品")
            try:
                certs = json.loads(row.get("certificate") or "[]")
            except Exception:
                certs = []
            for cert in certs:
                cert_id = clean(cert.get("certificate_id"))
                if cert_id:
                    order_cert_category.setdefault(cert_id, category)

    matched_order_categories = Counter()
    unmatched_verify_certs = 0
    for cert in by_cert:
        category = order_cert_category.get(cert)
        if category:
            matched_order_categories[category] += 1
        else:
            unmatched_verify_certs += 1

    out = {
        "verify_records": len(verify_rows),
        "verify_unique_certificates": len(by_cert),
        "duplicate_certificate_groups": len(duplicate_groups),
        "duplicate_extra_records": sum(len(rows) - 1 for rows in duplicate_groups.values()),
        "duplicate_same_store_groups": same_store,
        "duplicate_different_store_groups": diff_store,
        "duplicate_samples": duplicate_summary[:20],
        "verify_record_category_counts_by_verify_sku": dict(verify_category_counts),
        "verify_unique_certificate_category_counts_by_verify_sku": dict(verify_unique_category_counts),
        "verify_unique_certificate_category_counts_by_order_sku_when_matched": dict(matched_order_categories),
        "verify_unique_certificates_not_found_in_order_base": unmatched_verify_certs,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
