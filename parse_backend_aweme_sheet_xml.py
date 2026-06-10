import csv
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


SHEET_XML = Path(r"D:\app\抖音来客看板\tmp_xlsx_inspect\xl\worksheets\sheet1.xml")
OUT_CSV = Path(r"D:\app\抖音来客看板\field_probe\来客后台抖音号明细_XML解析.csv")
OUT_JSON = Path(r"D:\app\抖音来客看板\field_probe\来客后台抖音号明细_XML解析_summary.json")

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def col_index(cell_ref: str) -> int:
    letters = re.sub(r"\d+", "", cell_ref)
    idx = 0
    for ch in letters:
        idx = idx * 26 + ord(ch.upper()) - ord("A") + 1
    return idx - 1


def cell_text(cell: ET.Element) -> str:
    # Inline strings are stored as c/is/t; formulas or plain values as c/v.
    texts = [t.text or "" for t in cell.findall(".//a:is/a:t", NS)]
    if texts:
        return "".join(texts).strip()
    v = cell.find("a:v", NS)
    return (v.text or "").strip() if v is not None else ""


def main():
    root = ET.parse(SHEET_XML).getroot()
    rows = []
    max_cols = 0
    for row_el in root.findall(".//a:sheetData/a:row", NS):
        values = []
        for cell in row_el.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            idx = col_index(ref)
            while len(values) <= idx:
                values.append("")
            values[idx] = cell_text(cell)
        if any(values):
            max_cols = max(max_cols, len(values))
            rows.append(values)

    if not rows:
        raise SystemExit("no rows")

    headers = rows[0] + [f"字段{i}" for i in range(len(rows[0]) + 1, max_cols + 1)]
    headers = headers[:max_cols]
    records = []
    for raw in rows[1:]:
        raw = raw + [""] * (max_cols - len(raw))
        records.append({headers[i] or f"字段{i+1}": raw[i] for i in range(max_cols)})

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[h or f"字段{i+1}" for i, h in enumerate(headers)])
        writer.writeheader()
        writer.writerows(records)

    summary = {
        "xml": str(SHEET_XML),
        "rows_including_header": len(rows),
        "data_rows": len(records),
        "max_cols": max_cols,
        "headers": headers,
        "first_10_records": records[:10],
        "csv": str(OUT_CSV),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
