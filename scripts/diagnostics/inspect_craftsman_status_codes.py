import csv
import json
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import path_value

path = path_value("craftsman_table", env_name="CRAFTSMAN_TABLE")
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
