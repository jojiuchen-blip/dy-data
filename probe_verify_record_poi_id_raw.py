import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import douyin_verify_record_export as verify


OUT_DIR = Path(r"D:\app\抖音来客看板\field_probe")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    token = verify.get_token()
    poi_id = "7379966246109841419"
    records = verify.fetch_verify_records(
        token,
        datetime(2026, 1, 1),
        datetime(2026, 1, 4),
        poi_id=poi_id,
        retry=5,
    )
    output = {
        "query_poi_id": poi_id,
        "record_count": len(records),
        "first_record": records[0] if records else None,
        "first_formatted": verify.format_record(records[0]) if records else None,
    }
    path = OUT_DIR / "verify_record_poi_id_raw_probe.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), **output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
