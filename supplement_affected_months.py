import ast
import csv
import json
import logging
import os
import time
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Iterable, List

import requests

from src.dy_data.config import (
    as_float,
    as_int,
    douyin_account_id,
    douyin_app_id,
    douyin_app_secret,
    env_or_config,
    path_value,
    sku_type_map,
)


APP_ID = douyin_app_id()
APP_SECRET = douyin_app_secret()
ACCOUNT_ID = douyin_account_id()

API_URL = "https://open.douyin.com/goodlife/v1/trade/order/query/"
PAGE_SIZE = as_int(env_or_config("DOUYIN_PAGE_SIZE", "douyin", "page_size", default=100), 100)
REQUEST_SLEEP_SECONDS = as_float(env_or_config("DOUYIN_REQUEST_SLEEP_SECONDS", "douyin", "request_sleep_seconds", default=0.5), 0.5)
FORCE_DAYS_FROM = os.getenv("SUPPLEMENT_FORCE_DAYS_FROM", "").strip()
START_DATE = os.getenv("SUPPLEMENT_START_DATE", "").strip()
END_DATE = os.getenv("SUPPLEMENT_END_DATE", "").strip()
RUN_DIR = path_value("supplement_run_dir", env_name="SUPPLEMENT_RUN_DIR")
BASE_TABLE = path_value("base_table", env_name="BASE_TABLE")
SEED_TABLE = path_value("supplement_seed_table", env_name="SEED_TABLE")

AFFECTED_MONTHS = [
    (2025, 6),
    (2025, 8),
    (2025, 9),
    (2025, 12),
    (2026, 1),
    (2026, 2),
    (2026, 3),
    (2026, 4),
    (2026, 5),
]


def selected_months() -> List[tuple[int, int]]:
    value = os.getenv("SUPPLEMENT_MONTHS", "").strip()
    if not value:
        return AFFECTED_MONTHS
    months = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        year_text, month_text = item.split("-", 1)
        months.append((int(year_text), int(month_text)))
    return months


class TokenExpiredError(RuntimeError):
    pass

SKU_TYPE_MAP = sku_type_map()
TARGET_SKU_IDS = set(SKU_TYPE_MAP)

ORDER_STATUS_MAP = {
    0: "初始",
    100: "待支付",
    101: "支付取消",
    200: "已支付",
    201: "待使用",
    1: "已完成",
}
CERTIFICATE_STATUS_MAP = {
    0: "初始",
    100: "待使用",
    200: "预约中",
    201: "已预约",
    300: "退款中",
    301: "已退款",
    400: "履约中",
    401: "已履约",
}
ORDER_TYPE_MAP = {
    21: "卡券/次卡",
    61: "直播间订单",
    62: "短视频订单",
    63: "货架订单",
    90: "团购套餐",
}


def setup_logging() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(RUN_DIR / "supplement.log", encoding="utf-8"),
        ],
    )


def require_config() -> None:
    missing = []
    if not APP_ID:
        missing.append("DOUYIN_APP_ID")
    if not APP_SECRET:
        missing.append("DOUYIN_APP_SECRET")
    if not ACCOUNT_ID:
        missing.append("DOUYIN_ACCOUNT_ID")
    if missing:
        raise RuntimeError(f"请先设置环境变量: {', '.join(missing)}")


def normalize_id(value) -> str:
    try:
        if value is None:
            return ""
        text = str(value).strip()
        if "E" in text.upper():
            text = str(Decimal(text).to_integral_value())
        if text.endswith(".0"):
            text = text[:-2]
        return text
    except Exception:
        return str(value)


def format_time(value) -> str:
    try:
        if not value:
            return ""
        ts = int(value)
        if ts > 1000000000000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def format_amount(value):
    try:
        if value in ["", None]:
            return ""
        return str((Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return value


def status_text(key: str, value):
    try:
        code = int(value)
    except Exception:
        return value
    if key in {"order_status", "status", "trade_status"}:
        return ORDER_STATUS_MAP.get(code, value)
    if key in {"certificate_status", "item_status"}:
        return CERTIFICATE_STATUS_MAP.get(code, value)
    return value


def stringify(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def coupon_status_from_certificate(certificate_items: Iterable[Dict]) -> str:
    statuses = []
    for item in certificate_items or []:
        code = item.get("item_status")
        if code in ["", None]:
            continue
        text = str(status_text("item_status", code))
        if text not in statuses:
            statuses.append(text)
    return "|".join(statuses)


def row_from_order(order: Dict) -> Dict:
    certificate = order.get("certificate") or []
    contacts = order.get("contacts") or []
    first_contact = contacts[0] if contacts else {}
    row = {
        "订单ID": normalize_id(order.get("order_id")),
        "商品类型": SKU_TYPE_MAP.get(normalize_id(order.get("sku_id")), ""),
        "SKU_ID": normalize_id(order.get("sku_id")),
        "SKU名称": order.get("sku_name", ""),
        "门店ID": normalize_id(order.get("poi_id")),
        "订单状态": status_text("order_status", order.get("order_status")),
        "券状态": coupon_status_from_certificate(certificate),
        "状态": order.get("status", ""),
        "交易状态": status_text("trade_status", order.get("trade_status", "")),
        "订单类型": ORDER_TYPE_MAP.get(order.get("order_type"), order.get("order_type", "")),
        "下单时间": format_time(order.get("create_order_time")),
        "支付时间": format_time(order.get("pay_time")),
        "更新时间": format_time(order.get("update_order_time")),
        "核销时间": format_time(order.get("verify_time")),
        "原价金额": format_amount(order.get("original_amount")),
        "实付金额": format_amount(order.get("pay_amount")),
        "到账金额": format_amount(order.get("receipt_amount")),
        "退款金额": format_amount(order.get("refund_amount")),
        "优惠金额": format_amount(order.get("discount_amount")),
        "购买数量": order.get("count", ""),
        "联系人": first_contact.get("name", ""),
        "手机号": first_contact.get("phone", ""),
        "certificate": stringify(certificate),
    }
    for key, value in order.items():
        if key in {
            "order_id",
            "sku_id",
            "sku_name",
            "poi_id",
            "order_status",
            "status",
            "trade_status",
            "order_type",
            "create_order_time",
            "pay_time",
            "update_order_time",
            "verify_time",
            "original_amount",
            "pay_amount",
            "receipt_amount",
            "refund_amount",
            "discount_amount",
            "count",
            "contacts",
            "certificate",
        }:
            continue
        row[key] = stringify(value)
    return row


def get_token(retry: int = 3):
    for attempt in range(retry):
        try:
            response = requests.post(
                "https://open.douyin.com/oauth/client_token/",
                json={
                    "client_key": APP_ID,
                    "client_secret": APP_SECRET,
                    "grant_type": "client_credential",
                },
                timeout=10,
            )
            data = response.json()
            token = data.get("data", {}).get("access_token")
            if token:
                return token
            logging.error("Token 获取失败: %s", data)
        except Exception as exc:
            logging.warning("Token 获取异常 %s/%s: %s", attempt + 1, retry, exc)
            time.sleep(1)
    return None


def month_end(year: int, month: int) -> datetime:
    current = datetime(year, month, 1)
    next_month = current.replace(day=28) + timedelta(days=4)
    return next_month.replace(day=1)


def get_json_with_retry(url: str, *, headers: Dict, params: Dict, retry: int = 10) -> Dict:
    last_error = None
    for attempt in range(1, retry + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            return response.json()
        except Exception as exc:
            last_error = exc
            wait_seconds = min(60, attempt * 5)
            logging.warning("请求失败 %s/%s，%ss 后重试: %s", attempt, retry, wait_seconds, exc)
            time.sleep(wait_seconds)
    raise RuntimeError(f"请求连续失败 {retry} 次: {last_error}")


def fetch_window(token: str, start: datetime, end: datetime) -> List[Dict]:
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    rows = []
    seen = set()
    page = 1
    while True:
        params = {
            "account_id": ACCOUNT_ID,
            "page_num": page,
            "page_size": PAGE_SIZE,
            "create_order_start_time": int(start.timestamp()),
            "create_order_end_time": int(end.timestamp()),
        }
        data = get_json_with_retry(API_URL, headers=headers, params=params)
        orders = data.get("data", {}).get("orders", [])
        code = data.get("data", {}).get("error_code", data.get("error_code"))
        if str(code) == "2190008":
            raise TokenExpiredError(f"access_token过期: {start} 到 {end}")
        if code not in [None, 0, "0"] and not orders:
            logging.error("接口错误 %s - %s 到 %s: %s", code, start, end, data)
            break
        if not orders:
            break
        matched = 0
        for order in orders:
            order_id = normalize_id(order.get("order_id"))
            if not order_id or order_id in seen:
                continue
            seen.add(order_id)
            if normalize_id(order.get("sku_id")) in TARGET_SKU_IDS:
                rows.append(order)
                matched += 1
        logging.info("%s | 第%s页 | 本页%s | 命中%s | 累计%s", start.strftime("%Y-%m-%d"), page, len(orders), matched, len(rows))
        if len(orders) < PAGE_SIZE:
            break
        if page >= 100:
            logging.warning("%s 到 %s 仍触达100页，请继续缩小窗口", start, end)
            break
        page += 1
        time.sleep(REQUEST_SLEEP_SECONDS)
    return rows


def read_csv(path: Path) -> List[Dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: List[Dict], preferred: List[str]) -> None:
    all_fields = set()
    for row in rows:
        all_fields.update(row.keys())
    fields = [field for field in preferred if field in all_fields] + sorted(all_fields - set(preferred))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def merge_rows(base_rows: List[Dict], new_rows: List[Dict]) -> List[Dict]:
    merged = {normalize_id(row.get("订单ID")): row for row in base_rows if normalize_id(row.get("订单ID"))}
    for row in new_rows:
        order_id = normalize_id(row.get("订单ID"))
        if not order_id:
            continue
        merged[order_id] = row
    return list(merged.values())


def daily_path(day: datetime) -> Path:
    return RUN_DIR / "days" / f"{day.strftime('%Y-%m-%d')}.csv"


def should_force_day(day: datetime) -> bool:
    if not FORCE_DAYS_FROM:
        return False
    return day.date() >= datetime.strptime(FORCE_DAYS_FROM, "%Y-%m-%d").date()


def within_selected_dates(day: datetime) -> bool:
    day_value = day.date()
    if START_DATE and day_value < datetime.strptime(START_DATE, "%Y-%m-%d").date():
        return False
    if END_DATE and day_value > datetime.strptime(END_DATE, "%Y-%m-%d").date():
        return False
    return True


def main() -> None:
    setup_logging()
    require_config()
    if not BASE_TABLE.exists():
        if not SEED_TABLE.exists():
            raise FileNotFoundError(f"基础表不存在，且找不到种子表: {BASE_TABLE} / {SEED_TABLE}")
        base_seed_rows = read_csv(SEED_TABLE)
        write_csv(BASE_TABLE, base_seed_rows, PREFERRED_FIELDS)
        logging.info("已初始化固定基础表: %s <- %s", BASE_TABLE, SEED_TABLE)

    token = get_token()
    if not token:
        raise RuntimeError("Token 获取失败")

    all_new_rows = []
    failed_days = []
    active_months = selected_months()
    logging.info("本次补充月份: %s", ", ".join(f"{year}-{month:02d}" for year, month in active_months))
    for year, month in active_months:
        start = datetime(year, month, 1)
        end = month_end(year, month)
        current = start
        month_rows = []
        while current < end:
            next_day = min(current + timedelta(days=1), end)
            if not within_selected_dates(current):
                current = next_day
                continue
            day_file = daily_path(current)
            if day_file.exists() and not should_force_day(current):
                day_rows = read_csv(day_file)
                logging.info("%s 已有日文件，跳过重拉，命中 %s 条", current.strftime("%Y-%m-%d"), len(day_rows))
            else:
                try:
                    try:
                        day_orders = fetch_window(token, current, next_day)
                    except TokenExpiredError:
                        logging.warning("%s token过期，刷新后重试当天", current.strftime("%Y-%m-%d"))
                        token = get_token()
                        if not token:
                            raise RuntimeError("Token 刷新失败")
                        day_orders = fetch_window(token, current, next_day)
                    day_rows = [row_from_order(order) for order in day_orders]
                    write_csv(day_file, day_rows, PREFERRED_FIELDS)
                except Exception as exc:
                    failed_day = current.strftime("%Y-%m-%d")
                    failed_days.append(failed_day)
                    logging.error("%s 拉取失败，已跳过并继续后续日期: %s", failed_day, exc)
                    current = next_day
                    continue
            month_rows.extend(day_rows)
            current = next_day
        all_new_rows.extend(month_rows)
        write_csv(RUN_DIR / f"补充_{year}年{month:02d}月.csv", month_rows, PREFERRED_FIELDS)
        logging.info("%s-%02d 补充命中 %s 条", year, month, len(month_rows))

    base_rows = read_csv(BASE_TABLE)
    before = len({normalize_id(row.get("订单ID")) for row in base_rows if normalize_id(row.get("订单ID"))})
    new_ids = {normalize_id(row.get("订单ID")) for row in all_new_rows if normalize_id(row.get("订单ID"))}
    base_ids = {normalize_id(row.get("订单ID")) for row in base_rows if normalize_id(row.get("订单ID"))}
    additions = new_ids - base_ids
    merged = merge_rows(base_rows, all_new_rows)
    after = len({normalize_id(row.get("订单ID")) for row in merged if normalize_id(row.get("订单ID"))})

    write_csv(RUN_DIR / "受影响月份_按天补充汇总.csv", all_new_rows, PREFERRED_FIELDS)
    write_csv(RUN_DIR / "看板基础表_补齐受影响月份.csv", merged, PREFERRED_FIELDS)
    write_csv(BASE_TABLE, merged, PREFERRED_FIELDS)
    (RUN_DIR / "summary.json").write_text(
        json.dumps(
            {
                "base_unique_orders": before,
                "supplement_rows": len(all_new_rows),
                "supplement_unique_orders": len(new_ids),
                "new_order_ids": len(additions),
                "merged_unique_orders": after,
                "base_table": str(BASE_TABLE),
                "failed_days": failed_days,
                "affected_months": [f"{year}-{month:02d}" for year, month in active_months],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if failed_days:
        (RUN_DIR / "failed_days.txt").write_text("\n".join(failed_days), encoding="utf-8")
        logging.warning("补充完成但存在失败日期 %s 天: %s", len(failed_days), ", ".join(failed_days))
    logging.info("补充完成: base=%s supplement_unique=%s new=%s merged=%s fixed_table=%s", before, len(new_ids), len(additions), after, BASE_TABLE)


PREFERRED_FIELDS = [
    "订单ID",
    "商品类型",
    "SKU_ID",
    "SKU名称",
    "门店ID",
    "订单状态",
    "券状态",
    "状态",
    "交易状态",
    "订单类型",
    "下单时间",
    "支付时间",
    "更新时间",
    "核销时间",
    "原价金额",
    "实付金额",
    "到账金额",
    "退款金额",
    "优惠金额",
    "购买数量",
    "联系人",
    "手机号",
    "certificate",
]


if __name__ == "__main__":
    main()
