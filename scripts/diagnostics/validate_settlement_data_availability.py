import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import path_value


BASE_TABLE = path_value("base_table", env_name="BASE_TABLE")
CRAFTSMAN_TABLE = path_value("craftsman_table", env_name="CRAFTSMAN_TABLE")
VERIFY_DIR = path_value("verify_records_dir", env_name="VERIFY_RECORDS_DIR")
OUT_PATH = path_value("settlement_dir") / "分账基础数据可获取性验证.json"


def parse_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def cert_ids_from_order(row):
    certs = parse_json(row.get("certificate", ""), [])
    result = []
    if isinstance(certs, list):
        for item in certs:
            if isinstance(item, dict) and item.get("certificate_id"):
                result.append(str(item.get("certificate_id")))
    return result


def order_uid(row):
    sale_info = parse_json(row.get("order_sale_info", ""), {})
    if isinstance(sale_info, dict):
        return str(sale_info.get("transfer_uid") or "").strip()
    return ""


def sale_role(row):
    sale_info = parse_json(row.get("order_sale_info", ""), {})
    if isinstance(sale_info, dict):
        return str(sale_info.get("sale_role") or "").strip()
    return ""


def main():
    verify_cert_ids = set()
    verify_rows = 0
    valid_verify_rows = 0
    verify_field_counts = {
        "券ID": 0,
        "核销时间": 0,
        "核销状态": 0,
        "SKU_ID": 0,
        "商品名称": 0,
    }
    for path in VERIFY_DIR.glob("verify_*.json"):
        for record in json.loads(path.read_text(encoding="utf-8")):
            verify_rows += 1
            if record.get("certificate_id"):
                verify_field_counts["券ID"] += 1
            if record.get("verify_time"):
                verify_field_counts["核销时间"] += 1
            if record.get("status") not in ("", None):
                verify_field_counts["核销状态"] += 1
            sku = record.get("sku") if isinstance(record.get("sku"), dict) else {}
            if sku.get("sku_id"):
                verify_field_counts["SKU_ID"] += 1
            if sku.get("title"):
                verify_field_counts["商品名称"] += 1
            if str(record.get("status")) == "1" and record.get("certificate_id"):
                valid_verify_rows += 1
                verify_cert_ids.add(str(record.get("certificate_id")))

    craftsman_uids = set()
    craftsman_rows = 0
    craftsman_field_counts = {
        "订单归属人UID": 0,
        "抖音号昵称": 0,
        "抖音号": 0,
        "认证主体": 0,
        "所属账户名称": 0,
        "绑定门店ID": 0,
        "抖音号绑定状态": 0,
    }
    with CRAFTSMAN_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            craftsman_rows += 1
            uid = row.get("职人UID", "")
            if uid:
                craftsman_uids.add(uid)
                craftsman_field_counts["订单归属人UID"] += 1
            if row.get("抖音号昵称"):
                craftsman_field_counts["抖音号昵称"] += 1
            if row.get("抖音号"):
                craftsman_field_counts["抖音号"] += 1
            if row.get("商家主体"):
                craftsman_field_counts["认证主体"] += 1
            if row.get("绑定门店名称"):
                craftsman_field_counts["所属账户名称"] += 1
            if row.get("绑定门店ID"):
                craftsman_field_counts["绑定门店ID"] += 1
            if row.get("绑定状态码"):
                craftsman_field_counts["抖音号绑定状态"] += 1

    order_rows = 0
    merchant_orders = 0
    order_field_counts = {
        "订单ID": 0,
        "订单状态": 0,
        "实收金额": 0,
        "带货角色": 0,
        "订单归属人UID": 0,
        "券ID": 0,
    }
    order_cert_ids = set()
    order_uids = set()
    merchant_order_cert_ids = set()
    merchant_order_uids = set()
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            order_rows += 1
            role = sale_role(row)
            uid = order_uid(row)
            cert_ids = cert_ids_from_order(row)
            if row.get("订单ID"):
                order_field_counts["订单ID"] += 1
            if row.get("订单状态"):
                order_field_counts["订单状态"] += 1
            if row.get("到账金额") or row.get("实付金额") or row.get("sub_order_amount_infos"):
                order_field_counts["实收金额"] += 1
            if role:
                order_field_counts["带货角色"] += 1
            if uid:
                order_field_counts["订单归属人UID"] += 1
                order_uids.add(uid)
            if cert_ids:
                order_field_counts["券ID"] += 1
                order_cert_ids.update(cert_ids)
            if role == "商家":
                merchant_orders += 1
                merchant_order_cert_ids.update(cert_ids)
                if uid:
                    merchant_order_uids.add(uid)

    output = {
        "订单接口表": {
            "rows": order_rows,
            "merchant_orders": merchant_orders,
            "field_counts": order_field_counts,
        },
        "核销券接口表": {
            "rows": verify_rows,
            "valid_status_1_rows": valid_verify_rows,
            "field_counts": verify_field_counts,
        },
        "职人绑定表": {
            "rows": craftsman_rows,
            "field_counts": craftsman_field_counts,
        },
        "关联验证": {
            "订单券ID数量": len(order_cert_ids),
            "有效核销券ID数量": len(verify_cert_ids),
            "有效核销券ID可匹配订单数量": len(verify_cert_ids & order_cert_ids),
            "商家订单券ID可匹配有效核销数量": len(verify_cert_ids & merchant_order_cert_ids),
            "订单归属人UID数量": len(order_uids),
            "职人UID数量": len(craftsman_uids),
            "订单归属人UID可匹配职人数量": len(order_uids & craftsman_uids),
            "商家订单归属人UID可匹配职人数量": len(merchant_order_uids & craftsman_uids),
        },
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
