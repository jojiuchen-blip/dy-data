import csv
import json
import sys
import time
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import douyin_verify_record_export as verify


POI_SOURCE = Path(r"D:\app\抖音来客看板\settlement\recent_matched_sales_pois.json")
BACKEND_CSV = Path(r"D:\app\抖音来客看板\field_probe\来客后台抖音号明细_XML解析.csv")
OUT_DIR = Path(r"D:\app\抖音来客看板\settlement\verify_by_selected_pois_test")
START_TEXT = os.getenv("VERIFY_SELECTED_START", "2026-06-01")
END_TEXT = os.getenv("VERIFY_SELECTED_END", "2026-06-10")
TAG = f"{START_TEXT.replace('-', '')}_{END_TEXT.replace('-', '')}"
OUT_JSON = OUT_DIR / f"selected_poi_verify_records_{TAG}.json"
OUT_REPORT = OUT_DIR / f"selected_poi_verify_match_report_{TAG}.json"
OUT_CSV = OUT_DIR / f"selected_poi_verify_records_{TAG}.csv"


def read_backend():
    with BACKEND_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean(value) -> str:
    return str(value or "").strip()


def format_time(value):
    if value in ("", None, 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pois = json.loads(POI_SOURCE.read_text(encoding="utf-8"))
    pois = [poi for poi in pois if clean(poi.get("poi_id")) and clean(poi.get("poi_id")) != "0"]

    backend = read_backend()
    backend_by_poi = {}
    backend_by_store = {}
    for row in backend:
        poi_id = clean(row.get("所属账户关联poi_id"))
        store = clean(row.get("所属账户名称"))
        if poi_id and poi_id not in backend_by_poi:
            backend_by_poi[poi_id] = row
        if store and store not in backend_by_store:
            backend_by_store[store] = row

    token = verify.get_token()
    start = datetime.strptime(START_TEXT, "%Y-%m-%d")
    end = datetime.strptime(END_TEXT, "%Y-%m-%d")
    records = []
    per_poi = []

    for idx, poi in enumerate(pois, start=1):
        poi_id = clean(poi.get("poi_id"))
        poi_name = clean(poi.get("所属账户名称"))
        try:
            rows = verify.fetch_verify_records(token, start, end, poi_id=poi_id, retry=5)
        except Exception as exc:
            per_poi.append({"poi_id": poi_id, "poi_name": poi_name, "error": str(exc), "records": 0})
            continue
        for row in rows:
            row["verify_poi_id"] = poi_id
            row["verify_poi_name"] = poi_name
            records.append(row)
        per_poi.append({"poi_id": poi_id, "poi_name": poi_name, "records": len(rows)})
        print(f"{idx}/{len(pois)} {poi_id} {poi_name} records={len(rows)}")
        time.sleep(0.05)

    flat_rows = []
    matched_by_id = 0
    matched_by_name = 0
    for row in records:
        poi_id = clean(row.get("verify_poi_id"))
        poi_name = clean(row.get("verify_poi_name"))
        hit_id = backend_by_poi.get(poi_id)
        hit_name = backend_by_store.get(poi_name)
        if hit_id:
            matched_by_id += 1
        if hit_name:
            matched_by_name += 1
        sku = row.get("sku") or {}
        amount = row.get("amount") or {}
        flat_rows.append({
            "核销门店ID": poi_id,
            "核销门店名称": poi_name,
            "核销门店ID匹配后台": "是" if hit_id else "否",
            "核销门店名称匹配后台": "是" if hit_name else "否",
            "后台所属账户名称": (hit_id or hit_name or {}).get("所属账户名称", ""),
            "后台认证主体": (hit_id or hit_name or {}).get("认证主体", ""),
            "后台抖音号绑定状态": (hit_id or hit_name or {}).get("抖音号绑定状态", ""),
            "券ID": clean(row.get("certificate_id")),
            "核销ID": clean(row.get("verify_id")),
            "核销状态": clean(row.get("status")),
            "核销时间": format_time(row.get("verify_time")),
            "SKU_ID": clean(sku.get("sku_id")),
            "商品名称": clean(sku.get("title")),
            "实付金额": clean(amount.get("pay_amount")),
        })

    OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(OUT_CSV, flat_rows, [
        "核销门店ID",
        "核销门店名称",
        "核销门店ID匹配后台",
        "核销门店名称匹配后台",
        "后台所属账户名称",
        "后台认证主体",
        "后台抖音号绑定状态",
        "券ID",
        "核销ID",
        "核销状态",
        "核销时间",
        "SKU_ID",
        "商品名称",
        "实付金额",
    ])

    report = {
        "poi_count": len(pois),
        "records": len(records),
        "pois_with_records": sum(1 for item in per_poi if item.get("records", 0) > 0),
        "matched_by_verify_poi_id_to_backend_poi_id": matched_by_id,
        "matched_by_verify_poi_name_to_backend_store_name": matched_by_name,
        "per_poi": per_poi,
        "csv": str(OUT_CSV),
        "json": str(OUT_JSON),
    }
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
