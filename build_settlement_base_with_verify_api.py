import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import douyin_verify_record_export as verify
from build_settlement_base_from_current_data import (
    BASE_TABLE,
    CRAFTSMAN_TABLE,
    OUT_DIR,
    START_DATE,
    TODAY,
    is_refunded,
    load_craftsman_map,
    normalize_id,
    order_receipt_amount,
    parse_datetime,
    parse_json,
    write_csv,
)


VERIFY_CACHE_DIR = OUT_DIR / "verify_records_180d_days"
VERIFY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOOKBACK_DAYS = int(os.getenv("SETTLEMENT_LOOKBACK_DAYS", "10"))
TEST_START_DATE = TODAY - timedelta(days=LOOKBACK_DAYS)


def format_time(value: Any) -> str:
    if value in ("", None, 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def fetch_verify_day(token: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    cache_path = VERIFY_CACHE_DIR / f"verify_{start:%Y%m%d}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    for _ in range(3):
        try:
            records = verify.fetch_verify_records(token, start, end, retry=10)
            cache_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            return records
        except RuntimeError as exc:
            if "access_token" not in str(exc):
                raise
            token = verify.get_token()
    raise RuntimeError(f"核销记录接口 token 刷新后仍失败: {start:%Y-%m-%d}")


def build_verify_lookup() -> dict[str, dict[str, str]]:
    token = verify.get_token()
    lookup: dict[str, dict[str, str]] = {}
    current = TEST_START_DATE.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = TODAY + timedelta(days=1)
    while current < end_day:
        next_day = current + timedelta(days=1)
        records = fetch_verify_day(token, current, next_day)
        for record in records:
            cert_id = normalize_id(record.get("certificate_id"))
            if not cert_id:
                continue
            store_name = str(record.get("fulfil_operator_name") or "").strip()
            lookup[cert_id] = {
                "核销时间": format_time(record.get("verify_time")),
                "核销门店名称": store_name,
                "核销操作人ID": normalize_id(record.get("fulfil_operator_id")),
                "核销操作人": store_name,
            }
        print(f"{current:%Y-%m-%d} 核销记录 {len(records)} 条，累计券 {len(lookup)}")
        current = next_day
        time.sleep(0.05)
    return lookup


def certificate_ids(row: dict[str, str]) -> list[str]:
    certificate = parse_json(row.get("certificate", ""), [])
    ids: list[str] = []
    if isinstance(certificate, list):
        for item in certificate:
            if isinstance(item, dict):
                cert_id = normalize_id(item.get("certificate_id"))
                if cert_id:
                    ids.append(cert_id)
    return ids


def first_verify_info(cert_ids: list[str], lookup: dict[str, dict[str, str]]) -> dict[str, str]:
    for cert_id in cert_ids:
        info = lookup.get(cert_id)
        if info:
            return info
    return {}


def build_rows(verify_lookup: dict[str, dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    craftsman_map = load_craftsman_map()
    output_rows: list[dict[str, str]] = []
    scanned = 0
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            scanned += 1
            created_at = parse_datetime(row.get("下单时间", ""))
            if not created_at or created_at < TEST_START_DATE or created_at > TODAY:
                continue
            if is_refunded(row):
                continue
            sale_info = parse_json(row.get("order_sale_info", ""), {})
            if not isinstance(sale_info, dict):
                sale_info = {}
            sale_role = str(sale_info.get("sale_role") or "").strip()
            if sale_role != "商家":
                continue

            cert_ids = certificate_ids(row)
            verify_info = first_verify_info(cert_ids, verify_lookup)
            verify_time = verify_info.get("核销时间", "")
            if not verify_time:
                continue

            owner_nickname = str(sale_info.get("transfer_nickName") or "").strip()
            craftsman = craftsman_map.get(owner_nickname, {})
            sales_store_name = craftsman.get("绑定门店名称", "")
            verify_store_name = verify_info.get("核销门店名称", "")
            cross_store = ""
            need_settlement = ""
            if verify_store_name and sales_store_name:
                cross_store = "是" if verify_store_name != sales_store_name else "否"
                need_settlement = cross_store

            output_rows.append(
                {
                    "订单ID": row.get("订单ID", ""),
                    "商品类型": row.get("商品类型", ""),
                    "SKU_ID": row.get("SKU_ID", ""),
                    "SKU名称": row.get("SKU名称", ""),
                    "下单时间": row.get("下单时间", ""),
                    "核销时间": verify_time,
                    "核销时间来源": "核销记录接口",
                    "订单状态": row.get("订单状态", ""),
                    "券状态": row.get("券状态", ""),
                    "订单实收": order_receipt_amount(row),
                    "带货角色": sale_role,
                    "销售渠道": str(sale_info.get("sale_channel") or ""),
                    "订单归属人昵称": owner_nickname,
                    "订单归属人UID": normalize_id(sale_info.get("transfer_uid")),
                    "订单归属人抖音UID": normalize_id(sale_info.get("transfer_douyin_uid")),
                    "订单归属人绑定门店ID": craftsman.get("绑定门店ID", ""),
                    "订单归属人绑定门店名称": sales_store_name,
                    "认证主体": craftsman.get("商家主体", ""),
                    "抖音号绑定状态": craftsman.get("绑定状态", ""),
                    "抖音号绑定状态码": craftsman.get("绑定状态码", ""),
                    "核销门店名称": verify_store_name,
                    "核销操作人ID": verify_info.get("核销操作人ID", ""),
                    "是否跨店核销": cross_store,
                    "是否需要分账": need_settlement,
                    "分账比例": "",
                    "分账金额": "",
                }
            )

    summary = {
        "source_rows": scanned,
        "start_date": TEST_START_DATE.strftime("%Y-%m-%d"),
        "end_date": TODAY.strftime("%Y-%m-%d"),
        "verify_certificates": len(verify_lookup),
        "rows": len(output_rows),
        "with_owner_store": sum(1 for row in output_rows if row.get("订单归属人绑定门店名称")),
        "with_verify_store": sum(1 for row in output_rows if row.get("核销门店名称")),
        "with_cross_store_flag": sum(1 for row in output_rows if row.get("是否跨店核销")),
        "verify_time_rule": "仅使用核销记录接口返回的 verify_time",
    }
    return output_rows, summary


def main() -> None:
    verify_lookup = build_verify_lookup()
    rows, summary = build_rows(verify_lookup)
    csv_path = OUT_DIR / f"近{LOOKBACK_DAYS}天商家已核销分账基础表_核销接口测试.csv"
    summary_path = OUT_DIR / f"近{LOOKBACK_DAYS}天商家已核销分账基础表_核销接口测试_summary.json"
    write_csv(csv_path, rows)
    summary["csv_path"] = str(csv_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
