import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import douyin_refund_export as refund_api
from inspect_revoked_verify_refunds import load_revoked_records
from src.dy_data.config import path_value


OUT_DIR = path_value("settlement_dir")


def main() -> None:
    token = refund_api.get_token()
    revoked = load_revoked_records()
    revoked_cert_ids = {str(item.get("certificate_id")) for item in revoked}
    start = datetime(2026, 5, 30)
    end = datetime.now()
    refunds = refund_api.fetch_refunds(token, start, end, None)
    matches = []
    for item in refunds:
        text = json.dumps(item, ensure_ascii=False)
        if any(cert_id and cert_id in text for cert_id in revoked_cert_ids):
            matches.append(item)
    output = {
        "revoked_verify_records": len(revoked),
        "refund_records": len(refunds),
        "matched_refund_records": len(matches),
        "matches": matches[:20],
    }
    path = OUT_DIR / "最近10天核销已撤销记录_退款接口核对.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
