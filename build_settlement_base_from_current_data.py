import csv
import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


BASE_TABLE = Path(r"D:\app\抖音来客看板\data\看板基础表.csv")
CRAFTSMAN_TABLE = Path(r"D:\app\抖音来客看板\field_probe\职人绑定信息列表_测试.csv")
OUT_DIR = Path(r"D:\app\抖音来客看板\settlement")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TODAY = datetime(2026, 6, 9)
START_DATE = TODAY - timedelta(days=180)


def parse_json(value: str, default: Any):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def money(value: Any) -> str:
    if value in ("", None):
        return ""
    try:
        return str((Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP))
    except Exception:
        try:
            return str(Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP))
        except Exception:
            return str(value)


def normalize_id(value: Any) -> str:
    if value in ("", None):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def order_receipt_amount(row: dict[str, str]) -> str:
    sub_orders = parse_json(row.get("sub_order_amount_infos", ""), [])
    if isinstance(sub_orders, list) and sub_orders:
        total = Decimal("0")
        found = False
        for item in sub_orders:
            if not isinstance(item, dict):
                continue
            value = item.get("receipt_amount")
            if value in ("", None):
                continue
            total += Decimal(str(value))
            found = True
        if found:
            return money(total)
    return row.get("到账金额") or row.get("实付金额") or ""


def load_craftsman_map() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    with CRAFTSMAN_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            nickname = (row.get("抖音号昵称") or "").strip()
            if not nickname:
                continue
            current = result.get(nickname)
            # Prefer active/binding records over expired or unknown statuses.
            if current and current.get("绑定状态码") == "2":
                continue
            if not current or row.get("绑定状态码") == "2":
                result[nickname] = row
    return result


def is_refunded(row: dict[str, str]) -> bool:
    coupon_status = row.get("券状态", "")
    refund_amount = row.get("退款金额", "")
    if "已退款" in coupon_status or "退款" in coupon_status:
        return True
    try:
        return bool(refund_amount and Decimal(str(refund_amount)) > 0)
    except Exception:
        return False


def fulfilled_time(row: dict[str, str]) -> tuple[datetime | None, str, str]:
    verify_time = row.get("核销时间", "")
    parsed_verify = parse_datetime(verify_time)
    if parsed_verify:
        return parsed_verify, verify_time, "核销时间"
    return None, "", ""


def build() -> tuple[list[dict[str, str]], dict[str, Any]]:
    craftsman_map = load_craftsman_map()
    output_rows: list[dict[str, str]] = []
    scanned = 0
    with BASE_TABLE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            scanned += 1
            created_at = parse_datetime(row.get("下单时间", ""))
            verified_at, fulfilled_time_text, fulfilled_time_source = fulfilled_time(row)
            if not created_at or created_at < START_DATE or created_at > TODAY:
                continue
            if not verified_at:
                continue
            if is_refunded(row):
                continue

            sale_info = parse_json(row.get("order_sale_info", ""), {})
            if not isinstance(sale_info, dict):
                sale_info = {}
            sale_role = str(sale_info.get("sale_role") or "").strip()
            if sale_role != "商家":
                continue

            owner_nickname = str(sale_info.get("transfer_nickName") or "").strip()
            craftsman = craftsman_map.get(owner_nickname, {})
            sales_store_name = craftsman.get("绑定门店名称", "")
            verify_store_name = row.get("核销门店名称", "")
            cross_store = ""
            need_settlement = ""
            if verify_store_name and sales_store_name:
                cross_store = "是" if verify_store_name != sales_store_name else "否"
                need_settlement = cross_store

            output_rows.append(
                {
                    "订单ID": row.get("订单ID", ""),
                    "商品类型": row.get("商品类型", ""),
                    "SKU_ID": row.get("SKU_ID", ""),
                    "SKU名称": row.get("SKU名称", ""),
                    "下单时间": row.get("下单时间", ""),
                    "核销时间": fulfilled_time_text,
                    "核销时间来源": fulfilled_time_source,
                    "订单状态": row.get("订单状态", ""),
                    "券状态": row.get("券状态", ""),
                    "订单实收": order_receipt_amount(row),
                    "带货角色": sale_role,
                    "销售渠道": str(sale_info.get("sale_channel") or ""),
                    "订单归属人昵称": owner_nickname,
                    "订单归属人抖音UID": normalize_id(sale_info.get("transfer_douyin_uid")),
                    "订单归属人绑定门店ID": craftsman.get("绑定门店ID", ""),
                    "订单归属人绑定门店名称": sales_store_name,
                    "认证主体": craftsman.get("商家主体", ""),
                    "抖音号绑定状态": craftsman.get("绑定状态", ""),
                    "抖音号绑定状态码": craftsman.get("绑定状态码", ""),
                    "核销门店名称": verify_store_name,
                    "是否跨店核销": cross_store,
                    "是否需要分账": need_settlement,
                    "分账比例": "",
                    "分账金额": "",
                }
            )

    summary = {
        "source_rows": scanned,
        "start_date": START_DATE.strftime("%Y-%m-%d"),
        "end_date": TODAY.strftime("%Y-%m-%d"),
        "rows": len(output_rows),
        "with_owner_store": sum(1 for row in output_rows if row.get("订单归属人绑定门店名称")),
        "with_verify_store": sum(1 for row in output_rows if row.get("核销门店名称")),
        "with_cross_store_flag": sum(1 for row in output_rows if row.get("是否跨店核销")),
        "verify_time_rule": "仅使用核销记录接口回填后的真实核销时间；不使用更新时间代替",
    }
    return output_rows, summary


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "订单ID",
        "商品类型",
        "SKU_ID",
        "SKU名称",
        "下单时间",
        "核销时间",
        "核销时间来源",
        "订单状态",
        "券状态",
        "订单实收",
        "带货角色",
        "销售渠道",
        "订单归属人昵称",
        "订单归属人UID",
        "订单归属人抖音UID",
        "订单归属人绑定门店ID",
        "订单归属人绑定门店名称",
        "认证主体",
        "抖音号绑定状态",
        "抖音号绑定状态码",
        "核销门店名称",
        "核销操作人ID",
        "是否跨店核销",
        "是否需要分账",
        "分账比例",
        "分账金额",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows, summary = build()
    csv_path = OUT_DIR / "近180天商家已核销分账基础表_测试.csv"
    summary_path = OUT_DIR / "近180天商家已核销分账基础表_测试_summary.json"
    write_csv(csv_path, rows)
    summary["csv_path"] = str(csv_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
