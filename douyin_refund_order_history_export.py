import csv
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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

try:
    import requests
except ImportError:  # pragma: no cover - fallback for minimal runtimes
    requests = None


APP_ID = douyin_app_id()
APP_SECRET = douyin_app_secret()
ACCOUNT_ID = douyin_account_id()

API_URL = "https://open.douyin.com/goodlife/v1/trade/order/query/"
TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
SAVE_DIR = path_value("refund_order_save_dir", env_name="DOUYIN_REFUND_ORDER_SAVE_DIR")

PAGE_SIZE = min(max(as_int(env_or_config("DOUYIN_PAGE_SIZE", "douyin", "page_size", default=100), 100), 1), 100)
REQUEST_RETRY = max(as_int(os.getenv("DOUYIN_REQUEST_RETRY", "8"), 8), 20)
REQUEST_SLEEP_SECONDS = as_float(env_or_config("DOUYIN_REQUEST_SLEEP_SECONDS", "douyin", "request_sleep_seconds", default=0.2), 0.2)
CHUNK_DAYS = max(as_int(env_or_config("DOUYIN_REFUND_ORDER_CHUNK_DAYS", "douyin", "refund_order_chunk_days", default=7), 7), 1)
SAVE_PROGRESS = os.getenv("DOUYIN_REFUND_ORDER_SAVE_PROGRESS", "1").strip() not in ("0", "false", "False")
SESSION = requests.Session() if requests else None

SKU_TYPE_MAP = sku_type_map()
TARGET_SKU_IDS = set(SKU_TYPE_MAP)

FIELD_MAP = {
    "order_id": "订单ID",
    "sku_id": "SKU_ID",
    "sku_name": "SKU名称",
    "product_type": "商品类型",
    "order_status": "订单状态",
    "status": "状态",
    "trade_status": "交易状态",
    "certificate_status": "券状态",
    "item_status": "券状态",
    "order_type": "订单类型",
    "create_order_time": "下单时间",
    "pay_time": "支付时间",
    "update_order_time": "更新时间",
    "verify_time": "核销时间",
    "original_amount": "原价金额",
    "pay_amount": "实付金额",
    "receipt_amount": "到账金额",
    "refund_amount": "退款金额",
    "refund_time": "退款时间",
    "discount_amount": "优惠金额",
    "count": "购买数量",
    "poi_id": "门店ID",
    "contacts": "联系人信息",
}

PREFERRED_FIELDS = [
    "订单ID",
    "SKU_ID",
    "SKU名称",
    "商品类型",
    "订单状态",
    "状态",
    "交易状态",
    "券状态",
    "订单类型",
    "下单时间",
    "支付时间",
    "更新时间",
    "核销时间",
    "原价金额",
    "实付金额",
    "到账金额",
    "退款金额",
    "退款时间",
    "优惠金额",
    "购买数量",
    "门店ID",
    "联系人",
    "手机号",
]

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
    61: "直播间订卡",
    62: "短视频订卡",
    63: "货架订单",
    90: "团购套餐",
}


def setup_logging() -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = SAVE_DIR / "douyin_refund_order_history_export.log"
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
        raise RuntimeError("请先设置环境变量：" + ", ".join(missing))


def request_json(request: urllib.request.Request, timeout: int) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {text}") from exc
    return json.loads(text)


def post_json(url: str, payload: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    if SESSION:
        response = SESSION.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    return request_json(request, timeout)


def get_json(url: str, headers: Dict[str, str], params: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    if SESSION:
        response = SESSION.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(url + "?" + query, headers=headers, method="GET")
    return request_json(request, timeout)


def response_has_error(data: Dict[str, Any]) -> bool:
    extra_code = data.get("extra", {}).get("error_code")
    data_code = data.get("data", {}).get("error_code")
    top_code = data.get("error_code", data.get("err_no", data.get("code")))
    return (
        extra_code not in (None, 0, "0")
        or data_code not in (None, 0, "0")
        or top_code not in (None, 0, "0")
    )


def error_message(data: Dict[str, Any]) -> str:
    extra = data.get("extra", {})
    body = data.get("data", {})
    return (
        extra.get("description")
        or extra.get("sub_description")
        or body.get("description")
        or body.get("message")
        or data.get("message")
        or json.dumps(data, ensure_ascii=False)
    )


def is_token_expired(message: str) -> bool:
    return "access_token" in message and ("过期" in message or "expired" in message.lower())


def get_token(retry: int = REQUEST_RETRY) -> str:
    for attempt in range(1, retry + 1):
        try:
            data = post_json(
                TOKEN_URL,
                {
                    "client_key": APP_ID,
                    "client_secret": APP_SECRET,
                    "grant_type": "client_credential",
                },
            )
            token = data.get("data", {}).get("access_token")
            if token:
                logging.info("Token 获取成功")
                return token
            logging.warning("Token 获取失败（%s/%s）：%s", attempt, retry, data)
        except Exception as exc:
            logging.warning("Token 获取异常（%s/%s）：%s", attempt, retry, exc)
        time.sleep(min(attempt, 10))
    raise RuntimeError("Token 获取失败，已停止导出")


def parse_datetime(value: str) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"时间格式不正确：{value}，请使用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")


def export_range() -> Tuple[datetime, datetime]:
    start_value = os.getenv("DOUYIN_REFUND_ORDER_START", "2025-05-15 00:00:00")
    end_value = os.getenv("DOUYIN_REFUND_ORDER_END") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return parse_datetime(start_value), parse_datetime(end_value)


def split_ranges(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    ranges = []
    current = start
    while current < end:
        next_end = min(current + timedelta(days=CHUNK_DAYS), end)
        ranges.append((current, next_end))
        current = next_end
    return ranges


def normalize_id(value: Any) -> str:
    if value in ("", None):
        return ""
    text = str(value).strip()
    try:
        if "E" in text.upper():
            text = str(Decimal(text).to_integral_value())
        if text.endswith(".0"):
            text = text[:-2]
    except Exception:
        pass
    return text


def amount_cents(value: Any) -> int:
    if value in ("", None):
        return 0
    try:
        return int(Decimal(str(value)))
    except Exception:
        return 0


def product_type_for_sku(sku_id: Any) -> str:
    return SKU_TYPE_MAP.get(normalize_id(sku_id), "")


def is_target_refund_order(order: Dict[str, Any]) -> bool:
    sku_id = normalize_id(order.get("sku_id"))
    if sku_id not in TARGET_SKU_IDS:
        return False
    refund_amount, refund_time = refund_summary(order)
    if refund_amount > 0 or refund_time:
        return True
    status_values = [
        order.get("certificate_status"),
        order.get("item_status"),
        order.get("status"),
        order.get("order_status"),
        order.get("trade_status"),
    ]
    return any(str(value) in {"300", "301"} for value in status_values)


def refund_summary(order: Dict[str, Any]) -> Tuple[int, int]:
    total_refund_amount = amount_cents(order.get("refund_amount"))
    latest_refund_time = amount_cents(order.get("refund_time"))

    certificates = order.get("certificate")
    if isinstance(certificates, list):
        for certificate in certificates:
            if not isinstance(certificate, dict):
                continue
            total_refund_amount += amount_cents(certificate.get("refund_amount"))
            latest_refund_time = max(latest_refund_time, amount_cents(certificate.get("refund_time")))

    return total_refund_amount, latest_refund_time


def fetch_orders(token_state: Dict[str, str], start: datetime, end: datetime) -> List[Dict[str, Any]]:
    token = token_state["token"]
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    page = 1
    matched_orders: List[Dict[str, Any]] = []
    seen_order_ids = set()

    while True:
        params = {
            "account_id": ACCOUNT_ID,
            "page_num": page,
            "page_size": PAGE_SIZE,
            "create_order_start_time": int(start.timestamp()),
            "create_order_end_time": int(end.timestamp()),
        }
        data: Optional[Dict[str, Any]] = None
        for attempt in range(1, REQUEST_RETRY + 1):
            try:
                data = get_json(API_URL, headers=headers, params=params, timeout=30)
                if response_has_error(data):
                    message = error_message(data)
                    if is_token_expired(message):
                        token = get_token()
                        token_state["token"] = token
                        headers["access-token"] = token
                        logging.info("Token 已刷新，继续拉取订单")
                        continue
                    if attempt < REQUEST_RETRY:
                        logging.warning("订单接口返回错误（%s/%s）：%s", attempt, REQUEST_RETRY, message)
                        time.sleep(min(attempt, 10))
                        continue
                    raise RuntimeError("订单接口返回错误：" + message)
                break
            except Exception as exc:
                if "订单接口返回错误：" in str(exc):
                    raise
                logging.warning("订单请求异常（%s/%s）：%s", attempt, REQUEST_RETRY, exc)
                time.sleep(min(attempt, 10))

        if data is None:
            raise RuntimeError("订单接口无响应，已停止导出")

        orders = data.get("data", {}).get("orders") or []
        if not orders:
            break

        hit_count = 0
        for order in orders:
            order_id = normalize_id(order.get("order_id"))
            if not order_id or order_id in seen_order_ids:
                continue
            seen_order_ids.add(order_id)
            if is_target_refund_order(order):
                matched_orders.append(order)
                hit_count += 1

        logging.info(
            "%s 至 %s 第 %s 页：本页 %s 条，命中退款订单 %s 条，本段累计 %s 条",
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            page,
            len(orders),
            hit_count,
            len(matched_orders),
        )

        if len(orders) < PAGE_SIZE:
            break
        page += 1
        time.sleep(REQUEST_SLEEP_SECONDS)

    return matched_orders


def format_time(value: Any) -> Any:
    if value in ("", None):
        return ""
    try:
        timestamp = int(value)
        if timestamp > 1000000000000:
            timestamp = int(timestamp / 1000)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value


def format_amount(value: Any) -> Any:
    if value in ("", None):
        return ""
    try:
        return str((Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP))
    except Exception:
        return value


def flatten(value: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, item in value.items():
        field = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(flatten(item, field))
        elif isinstance(item, list):
            result[field] = json.dumps(item, ensure_ascii=False)
        else:
            result[field] = item
    return result


def format_status(key: str, value: Any) -> Any:
    try:
        code = int(value)
    except Exception:
        return value
    if key in {"order_status", "status", "trade_status"}:
        return ORDER_STATUS_MAP.get(code, value)
    if key in {"certificate_status", "item_status"}:
        return CERTIFICATE_STATUS_MAP.get(code, value)
    return value


def format_order(order: Dict[str, Any]) -> Dict[str, Any]:
    order = dict(order)
    refund_amount, refund_time = refund_summary(order)
    if refund_amount:
        order["refund_amount"] = refund_amount
    if refund_time:
        order["refund_time"] = refund_time
    flat = flatten(order)
    sku_id = normalize_id(order.get("sku_id"))
    flat["sku_id"] = sku_id
    flat["product_type"] = product_type_for_sku(sku_id)

    output: Dict[str, Any] = {}
    contacts = order.get("contacts")
    if isinstance(contacts, list) and contacts:
        output["联系人"] = contacts[0].get("name", "")
        output["手机号"] = contacts[0].get("phone", "")

    for key, value in flat.items():
        if key == "contacts":
            continue
        if "time" in key.lower():
            value = format_time(value)
        if any(keyword in key.lower() for keyword in ("amount", "price", "fee", "money", "discount")):
            value = format_amount(value)
        if key in {"order_id", "sku_id", "poi_id"}:
            value = normalize_id(value)
        if key == "order_type":
            try:
                value = ORDER_TYPE_MAP.get(int(value), value)
            except Exception:
                pass
        value = format_status(key, value)
        output[FIELD_MAP.get(key, key)] = value
    return output


def ordered_fields(rows: Iterable[Dict[str, Any]]) -> List[str]:
    fields = set()
    for row in rows:
        fields.update(row.keys())
    return PREFERRED_FIELDS + sorted(fields - set(PREFERRED_FIELDS))


def dedupe_orders(orders: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    seen = set()
    for order in orders:
        order_id = normalize_id(order.get("order_id"))
        if not order_id or order_id in seen:
            continue
        seen.add(order_id)
        result.append(order)
    return result


def save_orders(orders: List[Dict[str, Any]], start: datetime, end: datetime) -> Tuple[Path, Path]:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    base_name = f"抖音来客历史退款订单_{start:%Y%m%d}_{end:%Y%m%d}"
    csv_path = SAVE_DIR / f"{base_name}.csv"
    json_path = SAVE_DIR / f"{base_name}.json"

    rows = [format_order(order) for order in orders]
    fields = ordered_fields(rows) if rows else PREFERRED_FIELDS

    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(orders, file, ensure_ascii=False, indent=2)

    logging.info("CSV 已导出：%s", csv_path)
    logging.info("JSON 原始数据已导出：%s", json_path)
    return csv_path, json_path


def main() -> None:
    setup_logging()
    require_config()

    start, end = export_range()
    if start >= end:
        raise RuntimeError("导出开始时间必须早于结束时间")

    logging.info("开始导出历史退款订单：%s 到 %s", start, end)
    token = get_token()
    token_state = {"token": token}
    all_orders: List[Dict[str, Any]] = []
    ranges = split_ranges(start, end)

    for index, (range_start, range_end) in enumerate(ranges, start=1):
        logging.info("开始拉取分段 %s/%s：%s 到 %s", index, len(ranges), range_start, range_end)
        all_orders.extend(fetch_orders(token_state, range_start, range_end))
        if SAVE_PROGRESS:
            save_orders(dedupe_orders(all_orders), start, end)

    all_orders = dedupe_orders(all_orders)
    csv_path, json_path = save_orders(all_orders, start, end)
    logging.info("导出完成：%s 条；CSV=%s；JSON=%s", len(all_orders), csv_path, json_path)


if __name__ == "__main__":
    main()
