import csv
import json
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import path_value


BASE_TABLE = path_value("base_table", env_name="BASE_TABLE")
CRAFTSMAN_TABLE = path_value("craftsman_table", env_name="CRAFTSMAN_TABLE")
OUT_DIR = path_value("settlement_dir")
OUT_JSON = OUT_DIR / "订单归属昵称与UID匹配一致性验证.json"
OUT_UNMATCHED_CSV = OUT_DIR / "订单归属昵称与UID均未匹配订单.csv"
OUT_CONFLICT_CSV = OUT_DIR / "订单归属昵称与UID匹配冲突订单.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def clean(value) -> str:
    text = str(value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def parse_json(value: str, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def sale_info(row: dict[str, str]) -> dict:
    info = parse_json(row.get("order_sale_info", ""), {})
    return info if isinstance(info, dict) else {}


def store_key(row: dict[str, str]) -> tuple[str, str]:
    return clean(row.get("绑定门店ID")), clean(row.get("绑定门店名称"))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    orders = read_csv(BASE_TABLE)
    craftsmen = read_csv(CRAFTSMAN_TABLE)

    by_uid: dict[str, dict[str, str]] = {}
    by_nick: dict[str, dict[str, str]] = {}
    duplicate_nicks = Counter()
    for row in craftsmen:
        uid = clean(row.get("职人UID"))
        nick = clean(row.get("抖音号昵称"))
        if uid and uid not in by_uid:
            by_uid[uid] = row
        if nick:
            duplicate_nicks[nick] += 1
            by_nick.setdefault(nick, row)

    stats = Counter()
    unmatched_rows: list[dict[str, str]] = []
    conflict_rows: list[dict[str, str]] = []

    for row in orders:
        info = sale_info(row)
        if clean(info.get("sale_role")) != "商家":
            continue

        stats["商家订单数"] += 1
        order_id = clean(row.get("订单ID"))
        uid = clean(info.get("transfer_uid"))
        nick = clean(info.get("transfer_nickName"))
        uid_hit = by_uid.get(uid) if uid else None
        nick_hit = by_nick.get(nick) if nick else None

        if uid_hit:
            stats["UID匹配"] += 1
        if nick_hit:
            stats["昵称匹配"] += 1
        if uid_hit and nick_hit:
            stats["UID和昵称均匹配"] += 1
            if store_key(uid_hit) == store_key(nick_hit):
                stats["两种匹配门店一致"] += 1
            else:
                stats["两种匹配门店冲突"] += 1
                conflict_rows.append(
                    {
                        "订单ID": order_id,
                        "订单归属人UID": uid,
                        "订单归属人昵称": nick,
                        "UID匹配门店ID": clean(uid_hit.get("绑定门店ID")),
                        "UID匹配门店名称": clean(uid_hit.get("绑定门店名称")),
                        "昵称匹配门店ID": clean(nick_hit.get("绑定门店ID")),
                        "昵称匹配门店名称": clean(nick_hit.get("绑定门店名称")),
                    }
                )
        elif uid_hit:
            stats["仅UID匹配"] += 1
        elif nick_hit:
            stats["仅昵称匹配"] += 1
        else:
            stats["UID和昵称均未匹配"] += 1
            unmatched_rows.append(
                {
                    "订单ID": order_id,
                    "订单归属人UID": uid,
                    "订单归属人昵称": nick,
                    "订单状态": clean(row.get("订单状态")),
                    "券状态": clean(row.get("券状态")),
                    "门店ID": clean(row.get("门店ID")),
                    "intention_poi_id": clean(row.get("intention_poi_id")),
                }
            )

    unmatched_fields = [
        "订单ID",
        "订单归属人UID",
        "订单归属人昵称",
        "订单状态",
        "券状态",
        "门店ID",
        "intention_poi_id",
    ]
    conflict_fields = [
        "订单ID",
        "订单归属人UID",
        "订单归属人昵称",
        "UID匹配门店ID",
        "UID匹配门店名称",
        "昵称匹配门店ID",
        "昵称匹配门店名称",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_UNMATCHED_CSV, unmatched_rows, unmatched_fields)
    write_csv(OUT_CONFLICT_CSV, conflict_rows, conflict_fields)

    output = {
        "stats": dict(stats),
        "duplicate_nickname_count": sum(1 for _, count in duplicate_nicks.items() if count > 1),
        "unmatched_csv": str(OUT_UNMATCHED_CSV),
        "conflict_csv": str(OUT_CONFLICT_CSV),
        "notes": [
            "订单范围为订单基础表中的商家订单。",
            "UID 匹配使用订单 order_sale_info.transfer_uid = 职人绑定表 职人UID。",
            "昵称匹配使用订单 order_sale_info.transfer_nickName = 职人绑定表 抖音号昵称。",
            "一致性按绑定门店ID和绑定门店名称同时一致判断。",
        ],
    }
    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
