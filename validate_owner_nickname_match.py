import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import path_value


BASE_TABLE = path_value("base_table", env_name="BASE_TABLE")
CRAFTSMAN_TABLE = path_value("craftsman_table", env_name="CRAFTSMAN_TABLE")
VERIFY_DIR = path_value("verify_records_dir", env_name="VERIFY_RECORDS_DIR")
OUT_PATH = path_value("settlement_dir") / "订单归属昵称匹配验证.json"


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

    by_uid = {}
    by_nickname = {}
    duplicate_nicknames = {}
    with CRAFTSMAN_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            uid = row.get("职人UID", "").strip()
            nick = row.get("抖音号昵称", "").strip()
            if uid:
                by_uid[uid] = row
            if nick:
                if nick in by_nickname:
                    duplicate_nicknames[nick] = duplicate_nicknames.get(nick, 1) + 1
                else:
                    by_nickname[nick] = row

    stats = {
        "商家有效核销订单": 0,
        "UID匹配": 0,
        "昵称匹配": 0,
        "UID或昵称匹配": 0,
        "仅昵称匹配": 0,
        "重复昵称数量": len(duplicate_nicknames),
    }
    examples_only_nick = []
    examples_unmatched = []
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            info = sale_info(row)
            if info.get("sale_role") != "商家":
                continue
            if not (set(cert_ids(row)) & valid_verify_cert_ids):
                continue
            stats["商家有效核销订单"] += 1
            uid = str(info.get("transfer_uid") or "").strip()
            nick = str(info.get("transfer_nickName") or "").strip()
            uid_hit = uid in by_uid
            nick_hit = nick in by_nickname
            if uid_hit:
                stats["UID匹配"] += 1
            if nick_hit:
                stats["昵称匹配"] += 1
            if uid_hit or nick_hit:
                stats["UID或昵称匹配"] += 1
            if nick_hit and not uid_hit:
                stats["仅昵称匹配"] += 1
                if len(examples_only_nick) < 20:
                    m = by_nickname[nick]
                    examples_only_nick.append(
                        {
                            "订单ID": row.get("订单ID"),
                            "订单归属人UID": uid,
                            "订单归属人昵称": nick,
                            "匹配绑定门店ID": m.get("绑定门店ID"),
                            "匹配绑定门店名称": m.get("绑定门店名称"),
                            "绑定状态": m.get("绑定状态"),
                        }
                    )
            if not uid_hit and not nick_hit and len(examples_unmatched) < 20:
                examples_unmatched.append(
                    {
                        "订单ID": row.get("订单ID"),
                        "订单归属人UID": uid,
                        "订单归属人昵称": nick,
                        "门店ID": row.get("门店ID"),
                        "intention_poi_id": row.get("intention_poi_id"),
                    }
                )

    output = {
        "stats": stats,
        "examples_only_nickname_match": examples_only_nick,
        "examples_unmatched": examples_unmatched,
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
