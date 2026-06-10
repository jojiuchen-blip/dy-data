import csv
import json
from pathlib import Path


BASE_TABLE = Path(r"D:\app\抖音来客看板\data\看板基础表.csv")
CRAFTSMAN_TABLE = Path(r"D:\app\抖音来客看板\field_probe\职人绑定信息列表_测试.csv")
VERIFY_DIR = Path(r"D:\app\抖音来客看板\settlement\verify_records_180d_days")
OUT_PATH = Path(r"D:\app\抖音来客看板\settlement\订单归属UID未匹配昵称分布.json")


def parse_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def sale_info(row):
    info = parse_json(row.get("order_sale_info", ""), {})
    return info if isinstance(info, dict) else {}


def cert_ids(row):
    certs = parse_json(row.get("certificate", ""), [])
    result = []
    if isinstance(certs, list):
        for item in certs:
            if isinstance(item, dict) and item.get("certificate_id"):
                result.append(str(item.get("certificate_id")))
    return result


def main():
    valid_verify_cert_ids = set()
    for path in VERIFY_DIR.glob("verify_*.json"):
        for record in json.loads(path.read_text(encoding="utf-8")):
            if str(record.get("status")) == "1" and record.get("certificate_id"):
                valid_verify_cert_ids.add(str(record.get("certificate_id")))

    craftsman_uids = set()
    with CRAFTSMAN_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            uid = row.get("职人UID", "").strip()
            if uid:
                craftsman_uids.add(uid)

    total = 0
    uid_present = 0
    uid_matched = 0
    unmatched = []
    nickname_counts = {}
    uid_type_counts = {"空UID": 0, "数字UID": 0, "下划线UID": 0, "其他UID": 0}
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            info = sale_info(row)
            if info.get("sale_role") != "商家":
                continue
            if not (set(cert_ids(row)) & valid_verify_cert_ids):
                continue
            total += 1
            uid = str(info.get("transfer_uid") or "").strip()
            nick = str(info.get("transfer_nickName") or "").strip()
            if uid:
                uid_present += 1
            if uid in craftsman_uids:
                uid_matched += 1
                continue
            if not uid:
                uid_type_counts["空UID"] += 1
            elif uid.isdigit():
                uid_type_counts["数字UID"] += 1
            elif uid.startswith("_"):
                uid_type_counts["下划线UID"] += 1
            else:
                uid_type_counts["其他UID"] += 1
            nickname_counts[nick or "<空昵称>"] = nickname_counts.get(nick or "<空昵称>", 0) + 1
            if len(unmatched) < 100:
                unmatched.append(
                    {
                        "订单ID": row.get("订单ID"),
                        "订单归属人UID": uid,
                        "订单归属人昵称": nick,
                        "订单状态": row.get("订单状态"),
                        "券状态": row.get("券状态"),
                        "门店ID": row.get("门店ID"),
                        "intention_poi_id": row.get("intention_poi_id"),
                    }
                )

    top_nicknames = [
        {"订单归属人昵称": name, "count": count}
        for name, count in sorted(nickname_counts.items(), key=lambda item: item[1], reverse=True)[:50]
    ]
    output = {
        "商家有效核销订单": total,
        "订单归属人UID有值": uid_present,
        "UID匹配职人表": uid_matched,
        "UID未匹配": total - uid_matched,
        "未匹配UID类型分布": uid_type_counts,
        "未匹配昵称Top50": top_nicknames,
        "未匹配样本": unmatched,
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
