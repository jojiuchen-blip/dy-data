import json
from pathlib import Path
from typing import Any


VERIFY_DIR = Path(r"D:\app\抖音来客看板\settlement\verify_records_180d_days")
OUT_PATH = Path(r"D:\app\抖音来客看板\settlement\核销券接口字段清单_最近10天.json")


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
    records = []
    for path in sorted(VERIFY_DIR.glob("verify_*.json")):
        if "verify_20260530" <= path.stem <= "verify_20260609":
            records.extend(json.loads(path.read_text(encoding="utf-8")))

    fields = {}
    for record in records:
        for path, value in walk(record):
            if isinstance(value, (dict, list)):
                continue
            item = fields.setdefault(
                path,
                {
                    "sample_values": [],
                    "non_empty_count": 0,
                },
            )
            if value not in ("", None):
                item["non_empty_count"] += 1
                if len(item["sample_values"]) < 5 and value not in item["sample_values"]:
                    item["sample_values"].append(value)

    order_like = {
        path: info
        for path, info in fields.items()
        if "order" in path.lower() or "订单" in path or "sub" in path.lower()
    }
    output = {
        "record_count": len(records),
        "field_count": len(fields),
        "has_order_id_field": bool(order_like),
        "order_like_fields": order_like,
        "fields": fields,
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
