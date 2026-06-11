import csv
import json
from collections import Counter, defaultdict
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import path_value

SETTLEMENT_DIR = path_value("settlement_dir")
SETTLEMENT_CSV = SETTLEMENT_DIR / "近10天商家已核销分账基础表_核销接口测试.csv"
CRAFTSMAN_CSV = path_value("craftsman_table", env_name="CRAFTSMAN_TABLE")
OUT_JSON = SETTLEMENT_DIR / "订单归属昵称匹配抖音号明细_最近10天.json"
OUT_CSV = SETTLEMENT_DIR / "订单归属昵称匹配抖音号明细_最近10天_未匹配样本.csv"


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    orders = read_csv(SETTLEMENT_CSV)
    craftsmen = read_csv(CRAFTSMAN_CSV)

    exact_by_nick = defaultdict(list)
    exact_by_store = defaultdict(list)
    for row in craftsmen:
        nick = row.get("抖音号昵称", "")
        store = row.get("绑定门店名称", "")
        if nick.strip():
            exact_by_nick[nick.strip()].append(row)
        if store.strip():
            exact_by_store[store.strip()].append(row)

    unique_owner_names = sorted({(r.get("订单归属人昵称") or "").strip() for r in orders if (r.get("订单归属人昵称") or "").strip()})

    order_match_stats = Counter()
    owner_match_stats = Counter()
    owner_results = {}

    for owner in unique_owner_names:
        result = None
        if owner in exact_by_nick:
            result = {"method": "exact_抖音号昵称", "score": 1, "matched": exact_by_nick[owner][0]}
        elif owner in exact_by_store:
            result = {"method": "exact_绑定门店名称", "score": 1, "matched": exact_by_store[owner][0]}
        owner_results[owner] = result
        owner_match_stats[result["method"] if result else "未匹配"] += 1

    unmatched_counter = Counter()
    matched_examples = []
    for row in orders:
        owner = (row.get("订单归属人昵称") or "").strip()
        result = owner_results.get(owner)
        if result:
            order_match_stats[result["method"]] += 1
            if len(matched_examples) < 20:
                matched = result["matched"]
                matched_examples.append({
                    "订单归属人昵称": owner,
                    "匹配方式": result["method"],
                    "匹配分数": result["score"],
                    "抖音号昵称": matched.get("抖音号昵称", ""),
                    "抖音号": matched.get("抖音号", ""),
                    "绑定门店名称": matched.get("绑定门店名称", ""),
                    "绑定门店ID": matched.get("绑定门店ID", ""),
                    "绑定状态": matched.get("绑定状态", ""),
                    "商家主体": matched.get("商家主体", ""),
                })
        else:
            order_match_stats["未匹配"] += 1
            unmatched_counter[owner] += 1

    unmatched_top = [
        {"订单归属人昵称": k, "订单数": v}
        for k, v in unmatched_counter.most_common(50)
    ]

    summary = {
        "订单样本文件": str(SETTLEMENT_CSV),
        "抖音号明细文件": str(CRAFTSMAN_CSV),
        "订单行数": len(orders),
        "订单归属人昵称去重数": len(unique_owner_names),
        "抖音号明细行数": len(craftsmen),
        "按订单行匹配统计": dict(order_match_stats),
        "按订单归属人昵称去重匹配统计": dict(owner_match_stats),
        "匹配样例": matched_examples,
        "未匹配Top50": unmatched_top,
        "匹配规则": {
            "精确": ["订单归属人昵称 = 抖音号昵称", "订单归属人昵称 = 绑定门店名称"],
            "模糊匹配": "关闭",
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["订单归属人昵称", "订单数"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(unmatched_top)

    print(json.dumps({
        "订单行数": len(orders),
        "订单归属人昵称去重数": len(unique_owner_names),
        "按订单行匹配统计": dict(order_match_stats),
        "按订单归属人昵称去重匹配统计": dict(owner_match_stats),
        "报告": str(OUT_JSON),
        "未匹配样本": str(OUT_CSV),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
