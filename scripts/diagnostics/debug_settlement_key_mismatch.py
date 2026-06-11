import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import path_value


BASE_TABLE = path_value("base_table", env_name="BASE_TABLE")
CRAFTSMAN_TABLE = path_value("craftsman_table", env_name="CRAFTSMAN_TABLE")
VERIFY_DIR = path_value("verify_records_dir", env_name="VERIFY_RECORDS_DIR")
OUT_PATH = path_value("settlement_dir") / "分账关联差异样本.json"


def parse_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def cert_ids(row):
    certs = parse_json(row.get("certificate", ""), [])
    result = []
    if isinstance(certs, list):
        for item in certs:
            if isinstance(item, dict) and item.get("certificate_id"):
                result.append(str(item.get("certificate_id")))
    return result


def sale_info(row):
    info = parse_json(row.get("order_sale_info", ""), {})
    return info if isinstance(info, dict) else {}


def main():
    valid_verify_cert_ids = set()
    for path in VERIFY_DIR.glob("verify_*.json"):
        for record in json.loads(path.read_text(encoding="utf-8")):
            if str(record.get("status")) == "1" and record.get("certificate_id"):
                valid_verify_cert_ids.add(str(record.get("certificate_id")))

    order_by_cert = {}
    role_counts = {}
    diff_examples = []
    uid_examples = []
    poi_examples = []
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            info = sale_info(row)
            role = str(info.get("sale_role") or "")
            uid = str(info.get("transfer_uid") or "")
            nickname = str(info.get("transfer_nickName") or "")
            for cert_id in cert_ids(row):
                order_by_cert[cert_id] = {
                    "订单ID": row.get("订单ID", ""),
                    "订单状态": row.get("订单状态", ""),
                    "券状态": row.get("券状态", ""),
                    "带货角色": role,
                    "订单归属人UID": uid,
                    "订单归属人昵称": nickname,
                    "门店ID_poi_id": row.get("门店ID", ""),
                    "intention_poi_id": row.get("intention_poi_id", ""),
                    "SKU_ID": row.get("SKU_ID", ""),
                    "下单时间": row.get("下单时间", ""),
                }
            if uid and len(uid_examples) < 20:
                uid_examples.append(
                    {
                        "订单ID": row.get("订单ID", ""),
                        "订单归属人UID": uid,
                        "订单归属人昵称": nickname,
                        "带货角色": role,
                        "门店ID_poi_id": row.get("门店ID", ""),
                        "intention_poi_id": row.get("intention_poi_id", ""),
                    }
                )
            if len(poi_examples) < 20 and (row.get("门店ID") or row.get("intention_poi_id")):
                poi_examples.append(
                    {
                        "订单ID": row.get("订单ID", ""),
                        "门店ID_poi_id": row.get("门店ID", ""),
                        "intention_poi_id": row.get("intention_poi_id", ""),
                        "订单归属人昵称": nickname,
                        "带货角色": role,
                    }
                )

    matched = valid_verify_cert_ids & set(order_by_cert)
    for cert_id in matched:
        role = order_by_cert[cert_id]["带货角色"] or "<空>"
        role_counts[role] = role_counts.get(role, 0) + 1
        if role != "商家" and len(diff_examples) < 30:
            example = {"券ID": cert_id}
            example.update(order_by_cert[cert_id])
            diff_examples.append(example)

    craftsman_rows = []
    with CRAFTSMAN_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for idx, row in enumerate(csv.DictReader(file)):
            if idx >= 20:
                break
            craftsman_rows.append(row)

    output = {
        "有效核销券可匹配订单数": len(matched),
        "按带货角色分布": role_counts,
        "非商家样本": diff_examples,
        "订单UID样本": uid_examples,
        "职人表样本": craftsman_rows,
        "订单门店字段样本": poi_examples,
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
