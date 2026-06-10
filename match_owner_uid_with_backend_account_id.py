import csv
import json
from collections import Counter
from pathlib import Path

from src.dy_data.config import path_value

SETTLEMENT_DIR = path_value("settlement_dir")
ORDERS_CSV = SETTLEMENT_DIR / "近10天商家已核销分账基础表_核销接口测试.csv"
BACKEND_CSV = path_value("backend_aweme_csv", env_name="BACKEND_AWEME_CSV")
OUT_JSON = SETTLEMENT_DIR / "订单归属UID匹配后台所属账户id_最近10天.json"
OUT_MATCHED_CSV = SETTLEMENT_DIR / "订单归属UID匹配后台所属账户id_最近10天_已匹配.csv"
OUT_UNMATCHED_CSV = SETTLEMENT_DIR / "订单归属UID匹配后台所属账户id_最近10天_未匹配.csv"


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean_id(value: str) -> str:
    text = (value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    orders = read_csv(ORDERS_CSV)
    awemes = read_csv(BACKEND_CSV)

    backend_by_account_id = {}
    for row in awemes:
        account_id = clean_id(row.get("所属账户id"))
        if account_id and account_id not in backend_by_account_id:
            backend_by_account_id[account_id] = row

    matched = []
    unmatched = []
    stats = Counter()
    uid_owner_counter = Counter()

    for row in orders:
        uid = clean_id(row.get("订单归属人抖音UID") or row.get("订单归属人UID"))
        owner = (row.get("订单归属人昵称") or "").strip()
        if not uid:
            stats["订单UID为空"] += 1
            unmatched.append({"订单归属人昵称": owner, "订单归属人UID": uid, "原因": "订单UID为空", "订单数": 1})
            continue
        hit = backend_by_account_id.get(uid)
        if hit:
            stats["匹配成功"] += 1
            enriched = dict(row)
            enriched.update({
                "匹配方式": "订单归属人UID=后台所属账户id",
                "后台抖音昵称": hit.get("抖音昵称", ""),
                "后台抖音id": hit.get("抖音id", ""),
                "账号类型": hit.get("账号类型", ""),
                "所属账户名称": hit.get("所属账户名称", ""),
                "所属账户id": hit.get("所属账户id", ""),
                "所属账户关联poi_id": hit.get("所属账户关联poi_id", ""),
                "认证主体_后台": hit.get("认证主体", ""),
                "抖音号绑定状态_后台": hit.get("抖音号绑定状态", ""),
            })
            matched.append(enriched)
        else:
            stats["UID有值但未匹配"] += 1
            uid_owner_counter[(owner, uid)] += 1

    for (owner, uid), count in uid_owner_counter.most_common():
        unmatched.append({"订单归属人昵称": owner, "订单归属人UID": uid, "原因": "UID有值但未匹配", "订单数": count})

    matched_fields = list(orders[0].keys()) + [
        "匹配方式",
        "后台抖音昵称",
        "后台抖音id",
        "账号类型",
        "所属账户名称",
        "所属账户id",
        "所属账户关联poi_id",
        "认证主体_后台",
        "抖音号绑定状态_后台",
    ] if orders else []
    write_csv(OUT_MATCHED_CSV, matched, matched_fields)
    write_csv(OUT_UNMATCHED_CSV, unmatched, ["订单归属人昵称", "订单归属人UID", "原因", "订单数"])

    unique_order_uids = {clean_id(r.get("订单归属人抖音UID") or r.get("订单归属人UID")) for r in orders if clean_id(r.get("订单归属人抖音UID") or r.get("订单归属人UID"))}
    summary = {
        "orders_file": str(ORDERS_CSV),
        "backend_file": str(BACKEND_CSV),
        "order_rows": len(orders),
        "backend_rows": len(awemes),
        "backend_unique_account_ids": len(backend_by_account_id),
        "order_unique_owner_uids": len(unique_order_uids),
        "stats": dict(stats),
        "matched_rows": len(matched),
        "unmatched_rows": len(orders) - len(matched),
        "unmatched_top50": unmatched[:50],
        "matched_csv": str(OUT_MATCHED_CSV),
        "unmatched_csv": str(OUT_UNMATCHED_CSV),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
