import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import path_value

BASE_TABLE = path_value("base_table", env_name="BASE_TABLE")
OUT_PATH = path_value("settlement_dir") / "订单接口字段清单_主表样本.json"


def parse_json(value: str):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


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
    fields: dict[str, dict[str, Any]] = {}
    rows_seen = 0
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            rows_seen += 1
            normalized = {}
            for key, value in row.items():
                parsed = parse_json(value)
                normalized[key] = parsed if parsed is not None else value
            for path, value in walk(normalized):
                if isinstance(value, (dict, list)):
                    continue
                info = fields.setdefault(path, {"sample_values": [], "non_empty_count": 0})
                if value not in ("", None):
                    info["non_empty_count"] += 1
                    if len(info["sample_values"]) < 5 and value not in info["sample_values"]:
                        info["sample_values"].append(value)
            if rows_seen >= 5000:
                break

    key_fields = {
        path: info
        for path, info in fields.items()
        if any(
            word in path.lower()
            for word in [
                "order",
                "certificate",
                "amount",
                "pay",
                "receipt",
                "refund",
                "sale",
                "transfer",
                "poi",
                "sku",
                "time",
                "status",
            ]
        )
    }
    output = {
        "sample_rows": rows_seen,
        "field_count": len(fields),
        "key_fields": key_fields,
        "fields": fields,
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
