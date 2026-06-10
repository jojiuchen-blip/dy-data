import csv
import json
from collections import Counter
from pathlib import Path


ORDERS_CSV = Path(r"D:\app\抖音来客看板\settlement\近10天商家已核销分账基础表_核销接口测试.csv")
BACKEND_CSV = Path(r"D:\app\抖音来客看板\field_probe\来客后台抖音号明细_XML解析.csv")
OUT_JSON = Path(r"D:\app\抖音来客看板\settlement\订单归属UID匹配后台抖音id_最近10天.json")


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean(value: str) -> str:
    text = (value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.lower()


def main():
    orders = read_csv(ORDERS_CSV)
    backend = read_csv(BACKEND_CSV)

    by_aweme_id = {}
    for row in backend:
        aweme_id = clean(row.get("抖音id"))
        if aweme_id and aweme_id not in by_aweme_id:
            by_aweme_id[aweme_id] = row

    stats = Counter()
    matched_examples = []
    unmatched_uid_counter = Counter()

    for row in orders:
        uid = clean(row.get("订单归属人UID"))
        owner = (row.get("订单归属人昵称") or "").strip()
        if not uid:
            stats["订单归属人UID为空"] += 1
            continue
        hit = by_aweme_id.get(uid)
        if hit:
            stats["匹配成功"] += 1
            if len(matched_examples) < 30:
                matched_examples.append({
                    "订单归属人昵称": owner,
                    "订单归属人UID": row.get("订单归属人UID", ""),
                    "后台抖音昵称": hit.get("抖音昵称", ""),
                    "后台抖音id": hit.get("抖音id", ""),
                    "账号类型": hit.get("账号类型", ""),
                    "所属账户名称": hit.get("所属账户名称", ""),
                    "抖音号绑定状态": hit.get("抖音号绑定状态", ""),
                })
        else:
            stats["UID有值但未匹配抖音id"] += 1
            unmatched_uid_counter[(owner, row.get("订单归属人UID", ""))] += 1

    report = {
        "orders_file": str(ORDERS_CSV),
        "backend_file": str(BACKEND_CSV),
        "order_rows": len(orders),
        "backend_rows": len(backend),
        "backend_unique_aweme_ids": len(by_aweme_id),
        "stats": dict(stats),
        "matched_examples": matched_examples,
        "unmatched_uid_top50": [
            {"订单归属人昵称": owner, "订单归属人UID": uid, "订单数": count}
            for (owner, uid), count in unmatched_uid_counter.most_common(50)
        ],
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
