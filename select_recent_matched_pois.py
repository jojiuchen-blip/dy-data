import csv
import json
from collections import Counter
from pathlib import Path


MATCHED_CSV = Path(r"D:\app\抖音来客看板\settlement\订单归属昵称匹配后台抖音号明细_最近10天_已匹配.csv")
OUT_JSON = Path(r"D:\app\抖音来客看板\settlement\recent_matched_sales_pois.json")


with MATCHED_CSV.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

counter = Counter()
meta = {}
for row in rows:
    poi_id = (row.get("所属账户关联poi_id") or "").strip()
    if not poi_id:
        continue
    counter[poi_id] += 1
    meta.setdefault(poi_id, {
        "poi_id": poi_id,
        "所属账户名称": row.get("所属账户名称", ""),
        "抖音昵称": row.get("后台抖音昵称", ""),
        "抖音id": row.get("后台抖音id", ""),
        "订单数": 0,
    })

result = []
for poi_id, count in counter.most_common(30):
    item = dict(meta[poi_id])
    item["订单数"] = count
    result.append(item)

OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
