import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

import douyin_verify_record_export as verify
from src.dy_data.config import path_value


BACKEND_AWEME_CSV = path_value("backend_aweme_csv", env_name="BACKEND_AWEME_CSV")
OUT_DIR = path_value("may_verify_dir", env_name="MAY_VERIFY_OUT_DIR")
PARTS_DIR = OUT_DIR / "parts"
OUT_JSON = OUT_DIR / "may2026_verify_records_by_poi.json"
OUT_CSV = OUT_DIR / "may2026_verify_records_by_poi.csv"
SUMMARY_JSON = OUT_DIR / "may2026_verify_records_by_poi_summary.json"

START = datetime(2026, 5, 1)
END = datetime(2026, 6, 1)
CHUNK_DAYS = int(os.getenv("MAY_VERIFY_CHUNK_DAYS", "7"))
REQUEST_SLEEP = float(os.getenv("MAY_VERIFY_REQUEST_SLEEP", "0.02"))
POI_LIMIT = int(os.getenv("MAY_VERIFY_POI_LIMIT", "0") or "0")


def read_backend_pois() -> list[dict[str, str]]:
    with BACKEND_AWEME_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    by_poi: dict[str, dict[str, str]] = {}
    for row in rows:
        poi_id = (row.get("所属账户关联poi_id") or "").strip()
        if not poi_id or poi_id == "0":
            continue
        current = by_poi.get(poi_id)
        # Prefer current official store accounts for the POI metadata.
        rank = status_rank(row)
        if not current or rank < status_rank(current):
            by_poi[poi_id] = row
    result = [
        {
            "poi_id": poi_id,
            "poi_name": row.get("所属账户名称", ""),
            "抖音昵称": row.get("抖音昵称", ""),
            "抖音id": row.get("抖音id", ""),
            "账号类型": row.get("账号类型", ""),
            "认证主体": row.get("认证主体", ""),
            "抖音号绑定状态": row.get("抖音号绑定状态", ""),
        }
        for poi_id, row in by_poi.items()
    ]
    result.sort(key=lambda item: item["poi_id"])
    if POI_LIMIT > 0:
        result = result[:POI_LIMIT]
    return result


def status_rank(row: dict[str, str]) -> tuple[int, int]:
    status = row.get("抖音号绑定状态", "")
    account_type = row.get("账号类型", "")
    status_score = 0 if status == "认证成功" else 1
    type_score = 0 if account_type == "子机构门店号" else 1
    return status_score, type_score


def split_ranges(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    ranges = []
    current = start
    while current < end:
        next_time = min(current + timedelta(days=CHUNK_DAYS), end)
        ranges.append((current, next_time))
        current = next_time
    return ranges


def part_path(start: datetime, end: datetime, poi_id: str) -> Path:
    return PARTS_DIR / f"verify_part_{start:%Y%m%d}_{(end - timedelta(seconds=1)):%Y%m%d}_{poi_id}.json"


def load_part(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_part(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fetch_part(token: str, start: datetime, end: datetime, poi: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    path = part_path(start, end, poi["poi_id"])
    cached = load_part(path)
    if cached is not None:
        return token, cached

    last_error = None
    for attempt in range(1, 5):
        try:
            records = verify.fetch_verify_records(token, start, end, poi_id=poi["poi_id"], retry=4)
            for record in records:
                record["verify_poi_id"] = poi["poi_id"]
                record["verify_poi_name"] = poi["poi_name"]
            save_part(path, records)
            return token, records
        except Exception as exc:
            last_error = exc
            if "access_token" in str(exc) or "token" in str(exc).lower():
                token = verify.get_token()
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(f"{poi['poi_id']} {start:%Y-%m-%d} failed: {last_error}")


def format_time(value: Any) -> str:
    if value in ("", None, 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def write_csv(records: list[dict[str, Any]]) -> None:
    fields = [
        "核销门店ID",
        "核销门店名称",
        "券ID",
        "核销ID",
        "核销状态",
        "核销时间",
        "SKU_ID",
        "商品名称",
        "实付金额",
        "券实付金额",
        "原价",
        "核销类型",
        "是否可撤销",
        "撤销时间",
    ]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for record in records:
            sku = record.get("sku") or {}
            amount = record.get("amount") or {}
            writer.writerow({
                "核销门店ID": record.get("verify_poi_id", ""),
                "核销门店名称": record.get("verify_poi_name", ""),
                "券ID": record.get("certificate_id", ""),
                "核销ID": record.get("verify_id", ""),
                "核销状态": record.get("status", ""),
                "核销时间": format_time(record.get("verify_time")),
                "SKU_ID": sku.get("sku_id", ""),
                "商品名称": sku.get("title", ""),
                "实付金额": amount.get("pay_amount", ""),
                "券实付金额": amount.get("coupon_pay_amount", ""),
                "原价": amount.get("original_amount", ""),
                "核销类型": record.get("verify_type", ""),
                "是否可撤销": record.get("can_cancel", ""),
                "撤销时间": format_time(record.get("cancel_time")),
            })


def main() -> None:
    verify.require_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pois = read_backend_pois()
    ranges = split_ranges(START, END)
    token = verify.get_token()
    all_records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    total_tasks = len(pois) * len(ranges)
    done = 0
    for range_start, range_end in ranges:
        print(f"range {range_start:%Y-%m-%d} - {range_end:%Y-%m-%d}, pois={len(pois)}")
        for poi in pois:
            done += 1
            try:
                token, records = fetch_part(token, range_start, range_end, poi)
                all_records.extend(records)
                if records:
                    print(f"{done}/{total_tasks} {poi['poi_id']} {poi['poi_name']} records={len(records)} total={len(all_records)}")
            except Exception as exc:
                failures.append({"poi_id": poi["poi_id"], "poi_name": poi["poi_name"], "error": str(exc)})
            time.sleep(REQUEST_SLEEP)

    OUT_JSON.write_text(json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(all_records)
    summary = {
        "start": START.strftime("%Y-%m-%d"),
        "end": END.strftime("%Y-%m-%d"),
        "poi_count": len(pois),
        "range_count": len(ranges),
        "records": len(all_records),
        "unique_certificates": len({str(r.get("certificate_id")) for r in all_records if r.get("certificate_id")}),
        "failures": failures,
        "json": str(OUT_JSON),
        "csv": str(OUT_CSV),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
