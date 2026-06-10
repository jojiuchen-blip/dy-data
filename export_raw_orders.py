import csv
import json
import logging
import os
import time
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import as_int, douyin_account_id, douyin_app_id, douyin_app_secret, env_or_config, path_value, sku_type_map


APP_ID = douyin_app_id()
APP_SECRET = douyin_app_secret()
ACCOUNT_ID = douyin_account_id()

API_URL = "https://open.douyin.com/goodlife/v1/trade/order/query/"
SAVE_DIR = path_value("raw_order_save_dir", env_name="DOUYIN_SAVE_DIR")
PAGE_SIZE = as_int(env_or_config("DOUYIN_PAGE_SIZE", "douyin", "page_size", default=100), 100)

START_YEAR = int(os.getenv("DOUYIN_START_YEAR", "2025"))
START_MONTH = int(os.getenv("DOUYIN_START_MONTH", "5"))
START_DAY = int(os.getenv("DOUYIN_START_DAY", "13"))
END_YEAR = int(os.getenv("DOUYIN_END_YEAR", "2026"))
END_MONTH = int(os.getenv("DOUYIN_END_MONTH", "5"))

CONTACT_NAME_FIELD = "联系人"
CONTACT_PHONE_FIELD = "手机号"
PRODUCT_TYPE_FIELD = "商品类型"

SKU_TYPE_MAP = sku_type_map()
TARGET_SKU_IDS = set(SKU_TYPE_MAP.keys())

FIELD_MAP = {
    "order_id": "订单ID",
    "order_status": "订单状态",
    "status": "状态",
    "trade_status": "交易状态",
    "certificate_status": "券状态",
    "order_type": "订单类型",
    "create_order_time": "下单时间",
    "pay_time": "支付时间",
    "update_order_time": "更新时间",
    "verify_time": "核销时间",
    "original_amount": "原价金额",
    "pay_amount": "实付金额",
    "receipt_amount": "到账金额",
    "refund_amount": "退款金额",
    "discount_amount": "优惠金额",
    "sku_id": "SKU_ID",
    "sku_name": "SKU名称",
    "count": "购买数量",
    "poi_id": "门店ID",
}

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

ORDER_STATUS_KEYS = {"order_status", "status", "trade_status"}
CERTIFICATE_STATUS_KEYS = {"certificate_status", "item_status"}

ORDER_TYPE_MAP = {
    21: "卡券/次卡",
    61: "直播间订单",
    62: "短视频订单",
    63: "货架订单",
    90: "团购套餐",
}


def setup_logging() -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = SAVE_DIR / "douyin_order_export.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
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


def format_time(ts):
    try:
        if not ts:
            return ""
        ts = int(ts)
        if ts > 1000000000000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def format_amount(value):
    try:
        if value in ["", None]:
            return ""
        amount = (Decimal(str(value)) / Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        return str(amount)
    except Exception:
        return value


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


def get_product_type(sku_id: str) -> str:
    return SKU_TYPE_MAP.get(normalize_id(sku_id), "")


def is_target_order(order: Dict) -> bool:
    return normalize_id(order.get("sku_id", "")) in TARGET_SKU_IDS


def format_status(key: str, value):
    try:
        code = int(value)
    except Exception:
        return value

    if key in ORDER_STATUS_KEYS:
        return ORDER_STATUS_MAP.get(code, value)
    if key in CERTIFICATE_STATUS_KEYS:
        return CERTIFICATE_STATUS_MAP.get(code, value)
    if key.lower().endswith("_status"):
        return ORDER_STATUS_MAP.get(code, CERTIFICATE_STATUS_MAP.get(code, value))
    return value


def stringify_complex(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def format_order(order: Dict) -> Dict:
    new_order = {PRODUCT_TYPE_FIELD: get_product_type(order.get("sku_id"))}

    for key, value in order.items():
        if key == "contacts":
            try:
                if value:
                    new_order[CONTACT_NAME_FIELD] = value[0].get("name", "")
                    new_order[CONTACT_PHONE_FIELD] = value[0].get("phone", "")
            except Exception:
                pass

        if "time" in key.lower():
            value = format_time(value)
        amount_keywords = ["amount", "price", "fee", "money", "discount", "payment"]
        if any(keyword in key.lower() for keyword in amount_keywords):
            value = format_amount(value)
        value = format_status(key, value)

        if key == "order_type":
            try:
                value = ORDER_TYPE_MAP.get(int(value), value)
            except Exception:
                pass

        if key in {"sku_id", "order_id", "poi_id", "intention_poi_id"}:
            value = normalize_id(value)

        new_order[FIELD_MAP.get(key, key)] = stringify_complex(value)

    if CONTACT_NAME_FIELD not in new_order:
        new_order[CONTACT_NAME_FIELD] = ""
    if CONTACT_PHONE_FIELD not in new_order:
        new_order[CONTACT_PHONE_FIELD] = ""

    return new_order


def response_has_error(data: Dict) -> bool:
    code = data.get("error_code", data.get("err_no", data.get("code")))
    return code not in [None, 0, "0"]


def get_token(retry: int = 3):
    url = "https://open.douyin.com/oauth/client_token/"
    for attempt in range(retry):
        try:
            response = requests.post(
                url,
                json={
                    "client_key": APP_ID,
                    "client_secret": APP_SECRET,
                    "grant_type": "client_credential",
                },
                timeout=10,
            )
            data = response.json()
            if "data" in data and "access_token" in data["data"]:
                logging.info("Token 获取成功")
                return data["data"]["access_token"]
            logging.error("Token 获取失败，HTTP %s，响应: %s", response.status_code, data)
        except Exception as exc:
            logging.warning("Token 获取异常（尝试 %s/%s）: %s", attempt + 1, retry, exc)
            time.sleep(1)
    return None


def fetch_month_orders(token: str, start: datetime, end: datetime, retry: int = 3) -> List[Dict]:
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    all_orders = []
    seen_order_ids = set()
    page = 1
    total_pages = None

    while True:
        params = {
            "account_id": ACCOUNT_ID,
            "page_num": page,
            "page_size": PAGE_SIZE,
            "create_order_start_time": int(start.timestamp()),
            "create_order_end_time": int(end.timestamp()),
        }
        data = None
        for attempt in range(retry):
            try:
                response = requests.get(API_URL, headers=headers, params=params, timeout=30)
                data = response.json()
                break
            except Exception as exc:
                logging.warning("请求异常（尝试 %s/%s）: %s", attempt + 1, retry, exc)
                time.sleep(1)

        if data is None or "data" not in data:
            logging.error("接口异常，停止当前月份拉取。响应: %s", data)
            break

        orders = data["data"].get("orders", [])
        if response_has_error(data) and not orders:
            logging.error("接口返回错误，停止当前月份拉取。响应: %s", data)
            break

        page_info = data["data"].get("page", {})
        total = page_info.get("total")
        if total_pages is None and total not in [None, ""]:
            try:
                total_pages = max(1, (int(total) + PAGE_SIZE - 1) // PAGE_SIZE)
            except Exception:
                total_pages = None

        if not orders:
            break

        matched = 0
        for order in orders:
            order_id = normalize_id(order.get("order_id"))
            if order_id in seen_order_ids:
                continue
            seen_order_ids.add(order_id)
            if is_target_order(order):
                all_orders.append(order)
                matched += 1

        logging.info(
            "%s 第%s页 | 本页 %s 条 | 命中 %s 条 | 累计 %s 条",
            start.strftime("%Y-%m"),
            page,
            len(orders),
            matched,
            len(all_orders),
        )

        if total_pages is not None and page >= total_pages:
            break
        if len(orders) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.3)

    return all_orders


def dedupe_orders(orders: List[Dict]) -> List[Dict]:
    result = []
    seen = set()
    for order in orders:
        order_id = normalize_id(order.get("order_id"))
        if order_id in seen:
            continue
        seen.add(order_id)
        result.append(order)
    return result


def ordered_fields(orders: List[Dict]) -> List[str]:
    all_fields = set()
    for order in orders:
        all_fields.update(order.keys())

    preferred = [
        "订单ID",
        PRODUCT_TYPE_FIELD,
        "SKU_ID",
        "SKU名称",
        "门店ID",
        "订单状态",
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
        CONTACT_NAME_FIELD,
        CONTACT_PHONE_FIELD,
        "certificate",
    ]
    return preferred + sorted(all_fields - set(preferred))


def save_orders(orders: List[Dict], base_filename: str) -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = SAVE_DIR / f"{base_filename}.csv"
    json_path = SAVE_DIR / f"{base_filename}.json"

    if not orders:
        logging.warning("%s 无数据，将覆盖为空文件", base_filename)
        csv_path.write_text("", encoding="utf-8-sig")
        json_path.write_text("[]\n", encoding="utf-8")
        return

    formatted = [format_order(order) for order in dedupe_orders(orders)]
    fields = ordered_fields(formatted)

    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(formatted)
    logging.info("CSV 已导出: %s", csv_path)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(formatted, file, ensure_ascii=False, indent=2)
    logging.info("JSON 已导出: %s", json_path)


def generate_month_ranges(
    start_year: int,
    start_month: int,
    start_day: int,
    end_year: int,
    end_month: int,
) -> List[Tuple[datetime, datetime]]:
    ranges = []
    current = datetime(start_year, start_month, start_day)
    while current.year < end_year or (current.year == end_year and current.month <= end_month):
        month_anchor = current.replace(day=28) + timedelta(days=4)
        next_month = month_anchor.replace(day=1)
        ranges.append((current, next_month))
        current = next_month
    return ranges


def main() -> None:
    setup_logging()
    require_config()

    token = get_token()
    if not token:
        raise RuntimeError("Token 获取失败，已停止导出")

    all_ranges = generate_month_ranges(
        START_YEAR,
        START_MONTH,
        START_DAY,
        END_YEAR,
        END_MONTH,
    )
    logging.info("开始全量更新，共 %s 个月", len(all_ranges))

    all_orders_collected = []
    for start, end in all_ranges:
        month_str = start.strftime("%Y年%m月")
        logging.info("开始处理 %s", month_str)
        orders = fetch_month_orders(token, start, end)
        all_orders_collected.extend(orders)
        save_orders(orders, f"抖音订单_{month_str}")

    save_orders(
        all_orders_collected,
        f"抖音订单_{START_YEAR}年{START_MONTH:02d}月到{END_YEAR}年{END_MONTH:02d}月_总表",
    )
    logging.info("全部完成，共 %s 条筛选后订单", len(dedupe_orders(all_orders_collected)))


if __name__ == "__main__":
    main()
