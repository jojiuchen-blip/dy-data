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
    pois = verify.fetch_shop_pois(token, retry=3)
    matches = [
        poi for poi in pois
        if "梅州" in poi.get("poi_name", "") or "永迪" in poi.get("poi_name", "")
    ]
    verify.POI_NAME_MAP.update({poi["poi_id"]: poi.get("poi_name", "") for poi in pois})
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 4)
    samples = []
    for poi in matches[:20]:
        records = verify.fetch_verify_records(token, start, end, poi_id=poi["poi_id"], retry=3)
        if records:
            formatted = verify.format_record(records[0])
            samples.append(
                {
                    "poi": poi,
                    "record_count": len(records),
                    "sample": {
                        "券ID": formatted.get("券ID"),
                        "SKU_ID": formatted.get("SKU_ID"),
                        "商品名称": formatted.get("商品名称"),
                        "核销门店ID": formatted.get("核销门店ID"),
                        "核销门店名称": formatted.get("核销门店名称"),
                        "核销操作人": formatted.get("核销操作人"),
                        "核销时间": formatted.get("核销时间"),
                    },
                }
            )
    output = {"matches": matches[:20], "samples": samples}
    path = OUT_DIR / "jan2026_verify_specific_poi_probe.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), **output}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
