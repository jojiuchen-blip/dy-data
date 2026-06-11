import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from build_settlement_base_from_current_data import BASE_TABLE, normalize_id, parse_json
from src.dy_data.config import path_value


VERIFY_DIR = path_value("verify_records_dir", env_name="VERIFY_RECORDS_DIR")
OUT_DIR = path_value("settlement_dir")


def load_revoked_records():
    records = []
    for path in sorted(VERIFY_DIR.glob("verify_*.json")):
        if not ("verify_20260530" <= path.stem <= "verify_20260609"):
            continue
        for record in json.loads(path.read_text(encoding="utf-8")):
            if str(record.get("status")) == "2":
                records.append(record)
    return records


def certificate_ids_from_order(row):
    result = []
    certificate = parse_json(row.get("certificate", ""), [])
    if isinstance(certificate, list):
        for item in certificate:
            if isinstance(item, dict):
                cert_id = normalize_id(item.get("certificate_id"))
                if cert_id:
                    result.append(cert_id)
    return result


def main() -> None:
    revoked = load_revoked_records()
    revoked_ids = {normalize_id(item.get("certificate_id")) for item in revoked}
    matches = []
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            cert_ids = certificate_ids_from_order(row)
            hit = [cert_id for cert_id in cert_ids if cert_id in revoked_ids]
            if not hit:
                continue
            matches.append(
                {
                    "订单ID": row.get("订单ID", ""),
                    "券ID": "|".join(hit),
                    "SKU_ID": row.get("SKU_ID", ""),
                    "商品类型": row.get("商品类型", ""),
                    "订单状态": row.get("订单状态", ""),
                    "券状态": row.get("券状态", ""),
                    "下单时间": row.get("下单时间", ""),
                    "更新时间": row.get("更新时间", ""),
                    "退款金额": row.get("退款金额", ""),
                    "certificate": row.get("certificate", ""),
                }
            )
    output = {"revoked_count": len(revoked), "matched_orders": len(matches), "matches": matches}
    path = OUT_DIR / "最近10天核销已撤销记录_订单退款核对.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
