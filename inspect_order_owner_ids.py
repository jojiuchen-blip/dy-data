import csv
import json
from pathlib import Path

from src.dy_data.config import path_value

BASE_TABLE = path_value("base_table", env_name="BASE_TABLE")
OUT_PATH = path_value("settlement_dir") / "订单归属人ID字段覆盖.json"


def parse_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def main():
    total = 0
    counts = {
        "transfer_uid": 0,
        "transfer_douyin_uid": 0,
        "transfer_nickName": 0,
    }
    by_role = {}
    examples = []
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            total += 1
            info = parse_json(row.get("order_sale_info", ""), {})
            if not isinstance(info, dict):
                info = {}
            role = str(info.get("sale_role") or "<空>")
            role_stat = by_role.setdefault(
                role,
                {"rows": 0, "transfer_uid": 0, "transfer_douyin_uid": 0, "transfer_nickName": 0},
            )
            role_stat["rows"] += 1
            for key in counts:
                if info.get(key):
                    counts[key] += 1
                    role_stat[key] += 1
            if len(examples) < 30 and (info.get("transfer_uid") or info.get("transfer_douyin_uid")):
                examples.append(
                    {
                        "订单ID": row.get("订单ID"),
                        "带货角色": role,
                        "订单归属人昵称": info.get("transfer_nickName", ""),
                        "transfer_uid": info.get("transfer_uid", ""),
                        "transfer_douyin_uid": info.get("transfer_douyin_uid", ""),
                        "销售渠道": info.get("sale_channel", ""),
                    }
                )
    output = {"rows": total, "counts": counts, "by_role": by_role, "examples": examples}
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
