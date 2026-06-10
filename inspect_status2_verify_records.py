import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import path_value

VERIFY_DIR = path_value("verify_records_dir", env_name="VERIFY_RECORDS_DIR")
OUT = path_value("settlement_dir") / "status2_verify_records.json"


def fmt_ts(value):
    if value in (None, "", 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


rows = []
for path in sorted(VERIFY_DIR.glob("verify_*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    for record in data:
        if str(record.get("status")) == "2":
            sku = record.get("sku") or {}
            rows.append({
                "source_file": str(path),
                "certificate_id": record.get("certificate_id"),
                "verify_id": record.get("verify_id"),
                "status": record.get("status"),
                "verify_time": record.get("verify_time"),
                "verify_time_text": fmt_ts(record.get("verify_time")),
                "cancel_time": record.get("cancel_time"),
                "cancel_time_text": fmt_ts(record.get("cancel_time")),
                "sku_id": sku.get("sku_id"),
                "sku_title": sku.get("title"),
                "code": record.get("code"),
            })

OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "status2_count": len(rows),
    "dates": sorted({row["verify_time_text"][:10] for row in rows if row["verify_time_text"]}),
    "examples": rows[:20],
    "output": str(OUT),
}, ensure_ascii=False, indent=2))
