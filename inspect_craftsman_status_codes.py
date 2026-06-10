import csv
import json
from collections import Counter
from pathlib import Path


path = Path(r"D:\app\抖音来客看板\field_probe\职人绑定信息列表_测试.csv")
with path.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

samples = {}
for row in rows:
    code = row.get("绑定状态码")
    if code in {"105", "106"} and code not in samples:
        samples[code] = row

print(json.dumps({
    "rows": len(rows),
    "status_counts": dict(Counter(row.get("绑定状态码") for row in rows)),
    "samples": samples,
}, ensure_ascii=False, indent=2))
