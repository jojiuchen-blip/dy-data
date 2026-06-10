import json
from collections import Counter
from pathlib import Path

from src.dy_data.config import path_value

VERIFY_TEST_DIR = path_value("verify_by_selected_pois_test_dir")

paths = [
    VERIFY_TEST_DIR / "selected_poi_verify_records_20260601_20260610.json",
    VERIFY_TEST_DIR / "selected_poi_verify_records_20260530_20260601.json",
]

result = []
for path in paths:
    if not path.exists():
        continue
    rows = json.loads(path.read_text(encoding="utf-8"))
    counter = Counter(str(row.get("status")) for row in rows)
    samples = {}
    for row in rows:
        status = str(row.get("status"))
        samples.setdefault(status, row)
    result.append({
        "file": str(path),
        "records": len(rows),
        "status_counts": dict(counter),
        "sample_statuses": {
            key: {
                "certificate_id": value.get("certificate_id"),
                "verify_id": value.get("verify_id"),
                "verify_time": value.get("verify_time"),
                "status": value.get("status"),
                "cancel_time": value.get("cancel_time"),
                "verify_poi_id": value.get("verify_poi_id"),
                "verify_poi_name": value.get("verify_poi_name"),
            }
            for key, value in samples.items()
        },
    })

print(json.dumps(result, ensure_ascii=False, indent=2))
