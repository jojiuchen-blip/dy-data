import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import config_value, path_value, sku_type_map


ORDER_CSV = path_value("base_table", env_name="BASE_TABLE")
BACKEND_CSV = path_value("backend_aweme_csv", env_name="BACKEND_AWEME_CSV")
VERIFY_JSON = path_value("may_verify_dir") / "may2026_verify_records_by_poi.json"
OUT_CSV = path_value("may_settlement_dashboard_dir") / "核销券未进入分账原因明细.csv"

MONTH_START = datetime(2026, 5, 1)
MONTH_END = datetime(2026, 6, 1)
EXCLUDED_OWNER_NAMES = set(config_value("settlement", "excluded_owner_names", default=["比亚迪汽车销售有限公司"]))
SKU_TO_PRODUCT_TYPE = sku_type_map()


def clean(value):
    return str(value or "").strip()


def parse_dt(value):
    text = clean(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def safe_json(value, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def account_rank(row):
    status_score = 0 if clean(row.get("抖音号绑定状态")) == "认证成功" else 1
    type_score = 0 if clean(row.get("账号类型")) == "子机构门店号" else 1
    return status_score, type_score


def load_backend_maps():
    by_nick = {}
    by_store = {}
    with BACKEND_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            for key in (clean(row.get("抖音昵称")), clean(row.get("所属账户名称"))):
                if key and (key not in by_nick or account_rank(row) < account_rank(by_nick[key])):
                    by_nick[key] = row
    return by_nick, by_store


def valid_verify_cert_ids():
    rows = json.loads(VERIFY_JSON.read_text(encoding="utf-8"))
    valid = set()
    invalid = set()
    for row in rows:
        cert_id = clean(row.get("certificate_id"))
        if not cert_id:
            continue
        status = clean(row.get("status"))
        cancel_time = clean(row.get("cancel_time"))
        if status == "1" and cancel_time in ("", "0"):
            valid.add(cert_id)
        else:
            invalid.add(cert_id)
    return valid, invalid


def classify_order(row, backend):
    order_time = parse_dt(row.get("下单时间"))
    if not order_time or not (MONTH_START <= order_time < MONTH_END):
        return "订单不在2026年5月下单"

    info = safe_json(row.get("order_sale_info"), {})
    if clean(info.get("sale_role")) != "商家":
        return "非商家带货"
    if clean(row.get("订单状态")) == "支付取消":
        return "支付取消"

    owner = clean(info.get("transfer_nickName"))
    if owner in EXCLUDED_OWNER_NAMES:
        return "销售归属为比亚迪汽车销售有限公司"

    owner_hit = backend.get(owner)
    if not owner_hit:
        return "销售账号未匹配抖音号明细"

    poi_id = clean(owner_hit.get("所属账户关联poi_id"))
    store = clean(owner_hit.get("所属账户名称"))
    if not poi_id or poi_id == "0" or not store:
        return "销售门店ID缺失"

    sku_id = clean(row.get("SKU_ID"))
    if sku_id not in SKU_TO_PRODUCT_TYPE:
        return "商品类型未配置"

    certs = safe_json(row.get("certificate"), [])
    target_cert = clean(row.get("_target_cert_id"))
    target = next((cert for cert in certs if clean(cert.get("certificate_id")) == target_cert), None)
    if not target:
        return "订单含券列表未找到该券"
    if int(target.get("refund_amount") or 0) > 0:
        return "券已退款"

    return "应进入分账但未进入"


def main():
    backend, _ = load_backend_maps()
    valid_certs, invalid_certs = valid_verify_cert_ids()

    order_rows_by_cert = defaultdict(list)
    with ORDER_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            certs = safe_json(row.get("certificate"), [])
            for cert in certs:
                cert_id = clean(cert.get("certificate_id"))
                if cert_id:
                    copied = dict(row)
                    copied["_target_cert_id"] = cert_id
                    order_rows_by_cert[cert_id].append(copied)

    detail_rows = []
    reason_counts = Counter()
    for cert_id in sorted(valid_certs):
        candidates = order_rows_by_cert.get(cert_id, [])
        if not candidates:
            reason = "订单基础表无该券ID"
            detail_rows.append({"券ID": cert_id, "原因": reason})
            reason_counts[reason] += 1
            continue

        reasons = [classify_order(row, backend) for row in candidates]
        if any(reason == "应进入分账但未进入" for reason in reasons):
            # This means the current diagnostic found an eligible order; keep it visible for script audit.
            reason = "应进入分账但未进入"
        else:
            reason = reasons[0]
        row = candidates[0]
        info = safe_json(row.get("order_sale_info"), {})
        detail_rows.append({
            "券ID": cert_id,
            "原因": reason,
            "订单ID": clean(row.get("订单ID")),
            "下单时间": clean(row.get("下单时间")),
            "订单状态": clean(row.get("订单状态")),
            "SKU_ID": clean(row.get("SKU_ID")),
            "商品类型": clean(row.get("商品类型")),
            "订单归属人昵称": clean(info.get("transfer_nickName")),
            "带货角色": clean(info.get("sale_role")),
        })
        reason_counts[reason] += 1

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["券ID", "原因", "订单ID", "下单时间", "订单状态", "SKU_ID", "商品类型", "订单归属人昵称", "带货角色"]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(detail_rows)

    print(json.dumps({
        "valid_verify_unique_certs": len(valid_certs),
        "invalid_verify_unique_certs": len(invalid_certs),
        "reason_counts": dict(reason_counts.most_common()),
        "detail_csv": str(OUT_CSV),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
