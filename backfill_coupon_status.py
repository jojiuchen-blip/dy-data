import ast
import csv
import json
import os
from pathlib import Path


STATUS_MAP = {
    0: "初始",
    100: "待使用",
    200: "预约中",
    201: "已预约",
    300: "退款中",
    301: "已退款",
    400: "履约中",
    401: "已履约",
}

INPUT_CSV = Path(os.getenv("BACKFILL_INPUT_CSV", ""))
OUTPUT_CSV = Path(os.getenv("BACKFILL_OUTPUT_CSV", ""))
OUTPUT_JSON = Path(os.getenv("BACKFILL_OUTPUT_JSON", ""))


def status_text(code) -> str:
    try:
        return STATUS_MAP.get(int(code), str(code))
    except Exception:
        return str(code)


def parse_certificate(raw_value: str) -> list[dict]:
    if not raw_value:
        return []
    try:
        value = ast.literal_eval(raw_value)
    except Exception:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def extract_coupon_status(certificate_items: list[dict]) -> str:
    statuses = []
    for item in certificate_items:
        code = item.get("item_status")
        if code in ["", None]:
            continue
        text = status_text(code)
        if text not in statuses:
            statuses.append(text)
    return "|".join(statuses)


def ordered_fieldnames(fieldnames: list[str]) -> list[str]:
    if "券状态" in fieldnames:
        return fieldnames
    if "订单状态" in fieldnames:
        index = fieldnames.index("订单状态") + 1
        return fieldnames[:index] + ["券状态"] + fieldnames[index:]
    return ["券状态"] + fieldnames


def main() -> None:
    if not INPUT_CSV:
        raise RuntimeError("缺少 BACKFILL_INPUT_CSV")
    if not OUTPUT_CSV:
        raise RuntimeError("缺少 BACKFILL_OUTPUT_CSV")
    if not OUTPUT_JSON:
        raise RuntimeError("缺少 BACKFILL_OUTPUT_JSON")

    rows = []
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = ordered_fieldnames(list(reader.fieldnames or []))
        for row in reader:
            certificate_items = parse_certificate(row.get("certificate", ""))
            row["券状态"] = extract_coupon_status(certificate_items)
            rows.append(row)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    with OUTPUT_JSON.open("w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)

    print(f"WROTE {OUTPUT_CSV}")
    print(f"WROTE {OUTPUT_JSON}")
    print(f"ROWS {len(rows)}")


if __name__ == "__main__":
    main()
