import json
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import path_value

TARGET = path_value("verify_by_selected_pois_test_dir") / "selected_poi_verify_records_20260601_20260610.json"


def has_value(value):
    return value not in (None, "", 0, "0")


def main():
    rows = json.loads(TARGET.read_text(encoding="utf-8"))
    status_counts = Counter(str(row.get("status")) for row in rows)
    can_cancel_counts = Counter(str(row.get("can_cancel")) for row in rows)
    verify_type_counts = Counter(str(row.get("verify_type")) for row in rows)
    cancel_rows = [row for row in rows if has_value(row.get("cancel_time"))]
    invalid_rows = [row for row in rows if str(row.get("status")) != "1" or has_value(row.get("cancel_time"))]

    result = {
        "file": str(TARGET),
        "records": len(rows),
        "status_counts": dict(status_counts),
        "cancel_time_non_empty": len(cancel_rows),
        "can_cancel_counts": dict(can_cancel_counts),
        "verify_type_counts": dict(verify_type_counts),
        "invalid_by_final_rule": len(invalid_rows),
        "invalid_samples": [
            {
                "certificate_id": row.get("certificate_id"),
                "verify_id": row.get("verify_id"),
                "status": row.get("status"),
                "cancel_time": row.get("cancel_time"),
                "verify_poi_id": row.get("verify_poi_id"),
                "verify_poi_name": row.get("verify_poi_name"),
            }
            for row in invalid_rows[:10]
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
