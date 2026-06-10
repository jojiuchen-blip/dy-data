import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ORDERS_CSV = Path(r"D:\app\抖音来客看板\settlement\近10天商家已核销分账基础表_核销接口测试.csv")
BACKEND_CSV = Path(r"D:\app\抖音来客看板\field_probe\来客后台抖音号明细_XML解析.csv")
OUT_JSON = Path(r"D:\app\抖音来客看板\settlement\订单归属昵称匹配后台抖音号明细_最近10天.json")
OUT_MATCHED_CSV = Path(r"D:\app\抖音来客看板\settlement\订单归属昵称匹配后台抖音号明细_最近10天_已匹配.csv")
OUT_UNMATCHED_CSV = Path(r"D:\app\抖音来客看板\settlement\订单归属昵称匹配后台抖音号明细_最近10天_未匹配.csv")


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean(value: str) -> str:
    return (value or "").strip()


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    orders = read_csv(ORDERS_CSV)
    awemes = read_csv(BACKEND_CSV)

    by_nick = defaultdict(list)
    by_store = defaultdict(list)
    for row in awemes:
        nick = clean(row.get("抖音昵称"))
        store = clean(row.get("所属账户名称"))
        if nick:
            by_nick[nick].append(row)
        if store:
            by_store[store].append(row)

    matched_rows = []
    unmatched_counter = Counter()
    match_counter = Counter()
    owner_match_result = {}

    for row in orders:
        owner = clean(row.get("订单归属人昵称"))
        matched = None
        method = ""
        if owner in by_nick:
            matched = by_nick[owner][0]
            method = "订单归属人昵称=抖音昵称"
        elif owner in by_store:
            matched = by_store[owner][0]
            method = "订单归属人昵称=所属账户名称"

        if matched:
            match_counter[method] += 1
            owner_match_result[owner] = method
            enriched = dict(row)
            enriched.update({
                "匹配方式": method,
                "后台抖音昵称": matched.get("抖音昵称", ""),
                "后台抖音id": matched.get("抖音id", ""),
                "账号类型": matched.get("账号类型", ""),
                "所属账户名称": matched.get("所属账户名称", ""),
                "所属账户id": matched.get("所属账户id", ""),
                "所属账户关联poi_id": matched.get("所属账户关联poi_id", ""),
                "认证类别": matched.get("认证类别", ""),
                "认证信息": matched.get("认证信息", ""),
                "认证主体_后台": matched.get("认证主体", ""),
                "抖音号绑定状态_后台": matched.get("抖音号绑定状态", ""),
            })
            matched_rows.append(enriched)
        else:
            match_counter["未匹配"] += 1
            unmatched_counter[owner] += 1
            owner_match_result.setdefault(owner, "未匹配")

    unique_owner_counter = Counter(owner_match_result.values())
    unmatched_rows = [
        {"订单归属人昵称": owner, "订单数": count}
        for owner, count in unmatched_counter.most_common()
    ]

    matched_fields = list(orders[0].keys()) + [
        "匹配方式",
        "后台抖音昵称",
        "后台抖音id",
        "账号类型",
        "所属账户名称",
        "所属账户id",
        "所属账户关联poi_id",
        "认证类别",
        "认证信息",
        "认证主体_后台",
        "抖音号绑定状态_后台",
    ] if orders else []
    write_csv(OUT_MATCHED_CSV, matched_rows, matched_fields)
    write_csv(OUT_UNMATCHED_CSV, unmatched_rows, ["订单归属人昵称", "订单数"])

    summary = {
        "orders_file": str(ORDERS_CSV),
        "backend_aweme_file": str(BACKEND_CSV),
        "order_rows": len(orders),
        "backend_aweme_rows": len(awemes),
        "unique_order_owner_names": len({clean(r.get("订单归属人昵称")) for r in orders if clean(r.get("订单归属人昵称"))}),
        "match_by_order_rows": dict(match_counter),
        "match_by_unique_owner_names": dict(unique_owner_counter),
        "matched_rows": len(matched_rows),
        "unmatched_rows": sum(unmatched_counter.values()),
        "unmatched_top50": unmatched_rows[:50],
        "matched_csv": str(OUT_MATCHED_CSV),
        "unmatched_csv": str(OUT_UNMATCHED_CSV),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
