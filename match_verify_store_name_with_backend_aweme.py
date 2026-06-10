import csv
import json
from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import path_value

VERIFY_DIR = path_value("verify_records_dir", env_name="VERIFY_RECORDS_DIR")
BACKEND_CSV = path_value("backend_aweme_csv", env_name="BACKEND_AWEME_CSV")
OUT_JSON = path_value("settlement_dir") / "核销门店名称匹配后台所属账户名称_最近10天.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean(value) -> str:
    return str(value or "").strip()


def main():
    records = []
    for path in sorted(VERIFY_DIR.glob("verify_202606*.json")):
        records.extend(read_json(path))

    backend = read_csv(BACKEND_CSV)
    backend_by_store = {}
    for row in backend:
        store = clean(row.get("所属账户名称"))
        if store and store not in backend_by_store:
            backend_by_store[store] = row

    with_store = []
    matched = []
    unmatched = []
    for record in records:
        name = clean(record.get("fulfil_operator_name"))
        if not name:
            continue
        with_store.append(record)
        hit = backend_by_store.get(name)
        item = {
            "certificate_id": clean(record.get("certificate_id")),
            "verify_id": clean(record.get("verify_id")),
            "核销门店名称": name,
            "核销操作人ID": clean(record.get("fulfil_operator_id")),
            "核销状态": clean(record.get("status")),
            "核销时间": clean(record.get("verify_time")),
        }
        if hit:
            item.update({
                "匹配所属账户名称": hit.get("所属账户名称", ""),
                "抖音昵称": hit.get("抖音昵称", ""),
                "抖音id": hit.get("抖音id", ""),
                "所属账户关联poi_id": hit.get("所属账户关联poi_id", ""),
                "认证主体": hit.get("认证主体", ""),
                "抖音号绑定状态": hit.get("抖音号绑定状态", ""),
            })
            matched.append(item)
        else:
            unmatched.append(item)

    report = {
        "verify_files": [str(p) for p in sorted(VERIFY_DIR.glob("verify_202606*.json"))],
        "verify_records": len(records),
        "records_with_fulfil_operator_name": len(with_store),
        "unique_fulfil_operator_names": len({clean(r.get("fulfil_operator_name")) for r in with_store}),
        "matched_by_exact_store_name": len(matched),
        "unmatched_by_exact_store_name": len(unmatched),
        "fulfil_operator_name_counts": dict(Counter(clean(r.get("fulfil_operator_name")) for r in with_store).most_common()),
        "matched_examples": matched[:30],
        "unmatched_examples": unmatched[:30],
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
