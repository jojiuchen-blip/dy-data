import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

import douyin_verify_record_export as verify

from src.dy_data.config import path_value


OUT_DIR = path_value("field_probe_dir", env_name="FIELD_PROBE_DIR")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    token = verify.get_token()
    pois = verify.fetch_shop_pois(token, retry=3)
    verify.POI_NAME_MAP.update({poi["poi_id"]: poi.get("poi_name", "") for poi in pois})
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 4)
    samples = []
    for poi in pois[:10]:
        records = verify.fetch_verify_records(token, start, end, poi_id=poi["poi_id"], retry=3)
        if records:
            formatted = verify.format_record(records[0])
            samples.append(
                {
                    "poi_id": poi["poi_id"],
                    "poi_name": poi.get("poi_name", ""),
                    "record_count": len(records),
                    "sample": {
                        "订单ID": formatted.get("订单ID") or formatted.get("order_id"),
                        "券ID": formatted.get("券ID"),
                        "SKU_ID": formatted.get("SKU_ID"),
                        "核销门店ID": formatted.get("核销门店ID"),
                        "核销门店名称": formatted.get("核销门店名称"),
                        "核销操作人": formatted.get("核销操作人"),
                        "核销时间": formatted.get("核销时间"),
                    },
                }
            )
        if samples:
            break
    output = {"shop_poi_count": len(pois), "first_pois": pois[:10], "samples": samples}
    path = OUT_DIR / "jan2026_verify_by_poi_probe.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), **output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
