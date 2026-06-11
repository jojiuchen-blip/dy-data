import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

import douyin_verify_record_export as verify

from src.dy_data.config import path_value


OUT_DIR = path_value("field_probe_dir", env_name="FIELD_PROBE_DIR")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def walk(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, item
            yield from walk(item, path)
    elif isinstance(value, list):
        for idx, item in enumerate(value[:3]):
            path = f"{prefix}[{idx}]"
            yield path, item
            yield from walk(item, path)


def main() -> None:
    token = verify.get_token()
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 4)
    records = verify.fetch_verify_records(token, start, end, retry=3)
    interesting = {}
    all_fields = {}
    for record in records[:200]:
        for path, value in walk(record):
            if not isinstance(value, (dict, list)) and path not in all_fields:
                all_fields[path] = value
            text = path.lower()
            if any(word in text for word in ["poi", "shop", "store", "门店", "verify", "核销"]):
                if not isinstance(value, (dict, list)) and path not in interesting:
                    interesting[path] = value

    output = {
        "record_count": len(records),
        "interesting_fields": interesting,
        "all_scalar_fields": all_fields,
    }
    path = OUT_DIR / "jan2026_verify_field_probe.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), **output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
