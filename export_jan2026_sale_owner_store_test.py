import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import douyin_verify_record_export as verify
import supplement_affected_months as orders_api

from src.dy_data.config import path_value

OUT_DIR = path_value("field_probe_dir", env_name="FIELD_PROBE_DIR")
OUT_DIR.mkdir(parents=True, exist_ok=True)
ORDER_CACHE = OUT_DIR / "jan2026_target_orders_raw.json"
VERIFY_CACHE = OUT_DIR / "jan2026_verify_records_raw.json"
POI_CACHE = OUT_DIR / "shop_pois_raw.json"


def unique_join(values: list[str]) -> str:
    seen = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "|".join(seen)


def certificate_ids(order: dict[str, Any]) -> list[str]:
    ids = []
    for item in order.get("certificate") or []:
        cert_id = orders_api.normalize_id(item.get("certificate_id"))
        if cert_id:
            ids.append(cert_id)
    return ids


def fetch_january_orders(token: str) -> list[dict[str, Any]]:
    if ORDER_CACHE.exists():
        return json.loads(ORDER_CACHE.read_text(encoding="utf-8"))

    start = datetime(2026, 1, 1)
    end = datetime(2026, 2, 1)
    current = start
    result = []
    seen = set()
    while current < end:
        next_day = current + timedelta(days=1)
        try:
            day_orders = orders_api.fetch_window(token, current, next_day)
        except orders_api.TokenExpiredError:
            token = orders_api.get_token()
            day_orders = orders_api.fetch_window(token, current, next_day)
        for order in day_orders:
            order_id = orders_api.normalize_id(order.get("order_id"))
            if order_id and order_id not in seen:
                seen.add(order_id)
                result.append(order)
        current = next_day
        ORDER_CACHE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def fetch_verify_records_with_refresh(token: str) -> list[dict[str, Any]]:
    if VERIFY_CACHE.exists():
        return json.loads(VERIFY_CACHE.read_text(encoding="utf-8"))

    start = datetime(2026, 1, 1)
    end = datetime(2026, 2, 1)
    for _ in range(3):
        try:
            records = verify.fetch_verify_records(token, start, end, retry=12)
            VERIFY_CACHE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            return records
        except RuntimeError as exc:
            if "access_token" not in str(exc):
                raise
            token = verify.get_token()
    raise RuntimeError("核销记录接口 token 刷新后仍失败")


def fetch_shop_pois_with_refresh(token: str) -> list[dict[str, str]]:
    if POI_CACHE.exists():
        return json.loads(POI_CACHE.read_text(encoding="utf-8"))

    for _ in range(3):
        try:
            pois = verify.fetch_shop_pois(token, retry=3)
            POI_CACHE.write_text(json.dumps(pois, ensure_ascii=False, indent=2), encoding="utf-8")
            return pois
        except RuntimeError as exc:
            if "access_token" not in str(exc):
                raise
            token = verify.get_token()
    raise RuntimeError("门店列表接口 token 刷新后仍失败")


def build_verify_lookup(token: str) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    records = fetch_verify_records_with_refresh(token)
    pois = fetch_shop_pois_with_refresh(verify.get_token())
    poi_id_by_name = {poi.get("poi_name", "").strip(): poi.get("poi_id", "") for poi in pois}

    by_certificate: dict[str, dict[str, str]] = {}
    for record in records:
        cert_id = orders_api.normalize_id(record.get("certificate_id"))
        if not cert_id:
            continue
        operator_name = str(record.get("fulfil_operator_name") or "").strip()
        poi_id = poi_id_by_name.get(operator_name, "")
        by_certificate[cert_id] = {
            "核销门店ID": poi_id,
            "核销门店名称": operator_name,
            "核销操作人": operator_name,
            "核销时间_核销记录": orders_api.format_time(record.get("verify_time")),
        }
    return by_certificate, poi_id_by_name


def row_from_order(order: dict[str, Any], verify_by_cert: dict[str, dict[str, str]]) -> dict[str, Any]:
    row = orders_api.row_from_order(order)
    sale_info = order.get("order_sale_info") or {}
    cert_ids = certificate_ids(order)
    verify_rows = [verify_by_cert[cert_id] for cert_id in cert_ids if cert_id in verify_by_cert]

    row["带货角色"] = sale_info.get("sale_role", "")
    row["销售渠道"] = sale_info.get("sale_channel", "")
    row["订单归属人昵称"] = sale_info.get("transfer_nickName", "")
    row["订单归属人抖音UID"] = orders_api.normalize_id(sale_info.get("transfer_douyin_uid"))
    row["券ID"] = unique_join(cert_ids)
    row["核销门店ID"] = unique_join([item.get("核销门店ID", "") for item in verify_rows])
    row["核销门店名称"] = unique_join([item.get("核销门店名称", "") for item in verify_rows])
    row["核销操作人"] = unique_join([item.get("核销操作人", "") for item in verify_rows])
    if not row.get("核销时间"):
        row["核销时间"] = unique_join([item.get("核销时间_核销记录", "") for item in verify_rows])
    return row


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    preferred = [
        "订单ID",
        "商品类型",
        "SKU_ID",
        "SKU名称",
        "带货角色",
        "销售渠道",
        "订单归属人昵称",
        "订单归属人抖音UID",
        "门店ID",
        "核销门店ID",
        "核销门店名称",
        "核销操作人",
        "订单状态",
        "券状态",
        "下单时间",
        "支付时间",
        "更新时间",
        "核销时间",
        "实付金额",
        "到账金额",
        "退款金额",
        "购买数量",
        "券ID",
    ]
    fields = []
    for field in preferred:
        if field not in fields:
            fields.append(field)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    orders_api.require_config()
    order_token = orders_api.get_token()
    verify_token = verify.get_token()
    orders = fetch_january_orders(order_token)
    verify_by_cert, poi_id_by_name = build_verify_lookup(verify_token)
    rows = [
        row_from_order(order, verify_by_cert)
        for order in orders
        if (order.get("order_sale_info") or {}).get("sale_role") == "商家"
    ]

    csv_path = OUT_DIR / "抖音订单_2026年01月_带货归属核销门店测试.csv"
    json_path = OUT_DIR / "抖音订单_2026年01月_带货归属核销门店测试_summary.json"
    write_csv(csv_path, rows)
    summary = {
        "orders": len(rows),
        "raw_target_sku_orders": len(orders),
        "sale_role_filter": "商家",
        "verify_certificate_records": len(verify_by_cert),
        "poi_name_map_count": len(poi_id_by_name),
        "with_sale_role": sum(1 for row in rows if row.get("带货角色")),
        "with_owner_nickname": sum(1 for row in rows if row.get("订单归属人昵称")),
        "with_verify_store_name": sum(1 for row in rows if row.get("核销门店名称")),
        "with_verify_store_id": sum(1 for row in rows if row.get("核销门店ID")),
        "csv_path": str(csv_path),
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
