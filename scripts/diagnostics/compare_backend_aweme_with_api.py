import csv
import json
import re
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import path_value

try:
    import openpyxl
except ImportError as exc:
    raise SystemExit("MISSING_OPENPYXL") from exc


BACKEND_XLSX = path_value("backend_aweme_xlsx", env_name="BACKEND_AWEME_XLSX")
BACKEND_PARSED_CSV = path_value("backend_aweme_csv", env_name="BACKEND_AWEME_CSV")
API_CSV = path_value("craftsman_table", env_name="CRAFTSMAN_TABLE")
OUT_DIR = path_value("field_probe_dir", env_name="FIELD_PROBE_DIR")
OUT_JSON = OUT_DIR / "来客后台抖音号明细_vs_接口职人绑定_差异报告.json"
OUT_MISSING_CSV = OUT_DIR / "来客后台有_接口缺失_抖音号明细.csv"
OUT_API_ONLY_CSV = OUT_DIR / "接口有_后台未匹配_抖音号明细.csv"


def clean(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def norm_key(value):
    return clean(value).lower().replace(" ", "")


def read_api_rows():
    with API_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_backend_rows():
    if BACKEND_PARSED_CSV.exists():
        with BACKEND_PARSED_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return reader.fieldnames or [], list(reader)

    wb = openpyxl.load_workbook(BACKEND_XLSX, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [clean(v) for v in rows[0]]
    data = []
    for raw in rows[1:]:
        row = {headers[i]: clean(raw[i]) if i < len(raw) else "" for i in range(len(headers))}
        if any(row.values()):
            data.append(row)
    return headers, data


def pick_col(headers, candidates):
    for cand in candidates:
        for h in headers:
            if h == cand:
                return h
    for cand in candidates:
        for h in headers:
            if cand in h:
                return h
    return ""


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    backend_headers, backend_rows = read_backend_rows()
    api_rows = read_api_rows()

    backend_cols = {
        "抖音号": pick_col(backend_headers, ["抖音号", "账号", "抖音ID", "抖音id", "账号ID", "账号id"]),
        "抖音号昵称": pick_col(backend_headers, ["抖音号昵称", "抖音昵称", "昵称", "账号昵称"]),
        "绑定状态": pick_col(backend_headers, ["抖音号绑定状态", "绑定状态", "状态"]),
        "认证主体": pick_col(backend_headers, ["认证主体", "主体", "商家主体"]),
        "所属账户名称": pick_col(backend_headers, ["所属账户名称", "门店名称", "绑定门店名称", "账户名称"]),
        "门店ID": pick_col(backend_headers, ["门店ID", "门店id", "绑定门店ID", "poi_id", "POI ID"]),
    }

    api_cols = {
        "抖音号": "抖音号",
        "抖音号昵称": "抖音号昵称",
        "绑定状态": "绑定状态",
        "认证主体": "商家主体",
        "所属账户名称": "绑定门店名称",
        "门店ID": "绑定门店ID",
        "职人UID": "职人UID",
    }

    backend_by_aweme = {}
    backend_no_aweme = []
    for row in backend_rows:
        key = norm_key(row.get(backend_cols["抖音号"], "")) if backend_cols["抖音号"] else ""
        if key:
            backend_by_aweme.setdefault(key, []).append(row)
        else:
            backend_no_aweme.append(row)

    api_by_aweme = {}
    api_no_aweme = []
    for row in api_rows:
        key = norm_key(row.get(api_cols["抖音号"], ""))
        if key:
            api_by_aweme.setdefault(key, []).append(row)
        else:
            api_no_aweme.append(row)

    backend_keys = set(backend_by_aweme)
    api_keys = set(api_by_aweme)
    common_keys = backend_keys & api_keys
    missing_keys = backend_keys - api_keys
    api_only_keys = api_keys - backend_keys

    missing_rows = []
    for key in sorted(missing_keys):
        for row in backend_by_aweme[key]:
            missing_rows.append({
                "抖音号": row.get(backend_cols["抖音号"], ""),
                "抖音号昵称": row.get(backend_cols["抖音号昵称"], ""),
                "抖音号绑定状态": row.get(backend_cols["绑定状态"], ""),
                "认证主体": row.get(backend_cols["认证主体"], ""),
                "所属账户名称": row.get(backend_cols["所属账户名称"], ""),
                "门店ID": row.get(backend_cols["门店ID"], ""),
                "后台原始行": json.dumps(row, ensure_ascii=False),
            })

    api_only_rows = []
    for key in sorted(api_only_keys):
        for row in api_by_aweme[key]:
            api_only_rows.append({
                "抖音号": row.get(api_cols["抖音号"], ""),
                "抖音号昵称": row.get(api_cols["抖音号昵称"], ""),
                "绑定状态": row.get(api_cols["绑定状态"], ""),
                "认证主体": row.get(api_cols["认证主体"], ""),
                "绑定门店名称": row.get(api_cols["所属账户名称"], ""),
                "绑定门店ID": row.get(api_cols["门店ID"], ""),
                "职人UID": row.get(api_cols["职人UID"], ""),
            })

    status_missing = Counter(row["抖音号绑定状态"] for row in missing_rows)
    subject_missing = Counter(row["认证主体"] for row in missing_rows)
    store_missing = Counter(row["所属账户名称"] for row in missing_rows)

    report = {
        "backend_file": str(BACKEND_XLSX),
        "api_file": str(API_CSV),
        "backend_headers": backend_headers,
        "backend_detected_columns": backend_cols,
        "backend_rows": len(backend_rows),
        "backend_rows_with_aweme": sum(len(v) for v in backend_by_aweme.values()),
        "backend_unique_aweme": len(backend_keys),
        "backend_rows_without_aweme": len(backend_no_aweme),
        "api_rows": len(api_rows),
        "api_rows_with_aweme": sum(len(v) for v in api_by_aweme.values()),
        "api_unique_aweme": len(api_keys),
        "api_rows_without_aweme": len(api_no_aweme),
        "common_unique_aweme": len(common_keys),
        "backend_only_unique_aweme": len(missing_keys),
        "api_only_unique_aweme": len(api_only_keys),
        "backend_only_rows": len(missing_rows),
        "api_only_rows": len(api_only_rows),
        "backend_only_status_counts": dict(status_missing.most_common()),
        "backend_only_subject_top20": dict(subject_missing.most_common(20)),
        "backend_only_store_top30": dict(store_missing.most_common(30)),
        "backend_only_examples": missing_rows[:50],
        "api_only_examples": api_only_rows[:30],
        "missing_csv": str(OUT_MISSING_CSV),
        "api_only_csv": str(OUT_API_ONLY_CSV),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(OUT_MISSING_CSV, missing_rows, ["抖音号", "抖音号昵称", "抖音号绑定状态", "认证主体", "所属账户名称", "门店ID", "后台原始行"])
    write_csv(OUT_API_ONLY_CSV, api_only_rows, ["抖音号", "抖音号昵称", "绑定状态", "认证主体", "绑定门店名称", "绑定门店ID", "职人UID"])

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
