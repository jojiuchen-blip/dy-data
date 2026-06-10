import csv
import json
import sys
from pathlib import Path


path = Path(r"D:\app\抖音来客看板\field_probe\来客后台抖音号明细_XML解析.csv")
queries = sys.argv[1:] or ["比亚迪王朝|遵义通联航天4S店", "遵义通联航天", "通联航天"]

with path.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

matches = []
for row in rows:
    text = " ".join(str(value) for value in row.values())
    if any(query in text for query in queries):
        matches.append(row)

print(json.dumps(matches, ensure_ascii=False, indent=2))
