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
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

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

API_URL = "https://open.douyin.com/goodlife/v1/akte/after_sale/order/query/"
ORDER_API_URL = "https://open.douyin.com/goodlife/v1/trade/order/query/"
TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
SAVE_DIR = path_value("refund_save_dir", env_name="DOUYIN_REFUND_SAVE_DIR")

PAGE_SIZE = min(max(as_int(env_or_config("DOUYIN_PAGE_SIZE", "douyin", "page_size", default=100), 100), 1), 100)
REQUEST_SLEEP_SECONDS = as_float(env_or_config("DOUYIN_REQUEST_SLEEP_SECONDS", "douyin", "request_sleep_seconds", default=0.2), 0.2)
CHUNK_DAYS = max(as_int(env_or_config("DOUYIN_REFUND_CHUNK_DAYS", "douyin", "refund_chunk_days", default=7), 7), 1)
TIME_FIELD = os.getenv("DOUYIN_REFUND_TIME_FIELD", "create").strip().lower()
REQUEST_RETRY = max(int(os.getenv("DOUYIN_REQUEST_RETRY", "8")), 1)
REFUND_STATUSES = [
    int(value.strip())
    for value in os.getenv("DOUYIN_REFUND_STATUSES", "").split(",")
    if value.strip()
]
MAX_PAGES = int(os.getenv("DOUYIN_REFUND_MAX_PAGES", "0"))
MAX_ORDER_PAGES = int(os.getenv("DOUYIN_REFUND_MAX_ORDER_PAGES", "0"))
FILTER_TARGET_SKUS = os.getenv("DOUYIN_REFUND_FILTER_TARGET_SKUS", "1").strip() not in ("0", "false", "False")

SKU_TYPE_MAP = sku_type_map()
TARGET_SKU_IDS = set(SKU_TYPE_MAP)


FIELD_MAP = {
    "after_sale_id": "售后单ID",
    "order_id": "订单ID",
    "sku_id": "SKU_ID",
    "sku_name": "SKU名称",
    "product_type": "商品类型",
    "status": "售后单状态",
    "refund_status": "退款状态",
    "create_time": "退款创建时间",
    "update_time": "更新时间",
    "audit_time": "审核时间",
    "complete_time": "退款完成时间",
    "reject_reason": "拒绝原因",
    "audit_result": "审核结果",
    "refund_type": "退款类型",
    "trade_type": "交易类型",
    "order_type": "订单类型",
    "reason.desc": "退款原因说明",
    "reason.reason_code": "退款原因编码",
    "reason.show_reason": "前台退款原因",
    "merchant_account_id": "商户账号ID",
    "out_biz_after_sale_id": "外部售后单ID",
    "out_refund_payment_id": "外部退款支付ID",
    "refund_amount": "退款金额",
    "total_refund_amount": "总退款金额",
    "user_refund_amount": "用户退款金额",
    "real_refund_amount": "实际退款金额",
    "deduct_fee_amount": "手续费扣减金额",
    "user_deduct_fee_amount": "用户手续费扣减金额",
    "market_refund_amount": "营销退款金额",
    "market_deduct_fee_amount": "营销扣减金额",
    "refund_info_list": "退款明细",
}

PREFERRED_FIELDS = [
    "售后单ID",
    "订单ID",
    "SKU_ID",
    "SKU名称",
    "商品类型",
    "售后单状态",
    "退款状态",
    "退款创建时间",
    "退款完成时间",
    "更新时间",
    "审核时间",
    "退款金额",
    "总退款金额",
    "用户退款金额",
    "实际退款金额",
    "手续费扣减金额",
    "用户手续费扣减金额",
    "营销退款金额",
    "营销扣减金额",
    "退款原因说明",
    "退款原因编码",
    "前台退款原因",
    "拒绝原因",
    "审核结果",
    "退款类型",
    "交易类型",
    "订单类型",
    "商户账号ID",
    "外部售后单ID",
    "外部退款支付ID",
    "退款明细",
]

REFUND_STATUS_MAP = {
    9: "初始化",
    10: "审核中",
    20: "已审核",
    25: "已拒绝",
    30: "平台仲裁",
    40: "取消退款",
    50: "退款成功",
    59: "退款失败",
}


def setup_logging() -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = SAVE_DIR / "douyin_refund_export.log"
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


def post_json(url: str, payload: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    return request_json(request, timeout)


def get_json(url: str, headers: Dict[str, str], params: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(url + separator + query, headers=headers, method="GET")
    return request_json(request, timeout)


def request_json(request: urllib.request.Request, timeout: int) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {text}") from exc
    return json.loads(text)


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
            logging.error("Token 获取失败，响应：%s", data)
        except Exception as exc:
            logging.warning("Token 获取异常（%s/%s）：%s", attempt, retry, exc)
        time.sleep(min(attempt, 10))
    raise RuntimeError("Token 获取失败，已停止导出")


def parse_datetime(value: str) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt == "%Y-%m-%d" and value.endswith(" 23:59:59"):
                return parsed.replace(hour=23, minute=59, second=59)
            return parsed
        except ValueError:
            continue
    raise ValueError(f"时间格式不正确：{value}，请使用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")


def default_week_range(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    now = now or datetime.now()
    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return this_monday - timedelta(days=7), this_monday


def export_range() -> Tuple[datetime, datetime]:
    start_value = os.getenv("DOUYIN_REFUND_START")
    end_value = os.getenv("DOUYIN_REFUND_END")
    if start_value and end_value:
        return parse_datetime(start_value), parse_datetime(end_value)
    if start_value or end_value:
        raise RuntimeError("DOUYIN_REFUND_START 和 DOUYIN_REFUND_END 需要同时设置")
    return default_week_range()


def response_has_error(data: Dict[str, Any]) -> bool:
    extra_code = data.get("extra", {}).get("error_code")
    data_code = data.get("data", {}).get("error_code")
    return extra_code not in (None, 0, "0") or data_code not in (None, 0, "0")


def error_message(data: Dict[str, Any]) -> str:
    extra = data.get("extra", {})
    body = data.get("data", {})
    return (
        extra.get("description")
        or extra.get("sub_description")
        or body.get("description")
        or json.dumps(data, ensure_ascii=False)
    )


def is_token_expired(message: str) -> bool:
    return "access_token" in message and ("过期" in message or "expired" in message.lower())


def time_params(start: datetime, end: datetime) -> Dict[str, int]:
    if TIME_FIELD in ("done", "complete", "completed", "refund_done"):
        return {
            "refund_done_start_time": int(start.timestamp()),
            "refund_done_end_time": int(end.timestamp()),
        }
    return {
        "create_order_start_time": int(start.timestamp()),
        "create_order_end_time": int(end.timestamp()),
    }


def fetch_refunds(
    token: str,
    start: datetime,
    end: datetime,
    refund_status: Optional[int],
    retry: int = REQUEST_RETRY,
) -> List[Dict[str, Any]]:
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    cursor = "0"
    refunds: List[Dict[str, Any]] = []
    seen_keys = set()

    while True:
        current_page = len(refunds) // PAGE_SIZE + 1
        params: Dict[str, Any] = {
            "account_id": ACCOUNT_ID,
            "page_size": PAGE_SIZE,
            "cursor": cursor,
        }
        params.update(time_params(start, end))
        if refund_status is not None:
            params["refund_status"] = refund_status

        data = None
        for attempt in range(1, retry + 1):
            try:
                data = get_json(API_URL, headers=headers, params=params, timeout=30)
                if response_has_error(data):
                    message = error_message(data)
                    if is_token_expired(message):
                        token = get_token()
                        headers["access-token"] = token
                        logging.info("Token 已刷新，继续拉取退款单")
                        continue
                    if attempt < retry:
                        logging.warning("接口返回错误（%s/%s）：%s", attempt, retry, message)
                        time.sleep(attempt)
                        continue
                    raise RuntimeError("接口返回错误：" + message)
                break
            except Exception as exc:
                if "接口返回错误：" in str(exc):
                    raise
                logging.warning("请求异常（%s/%s）：%s", attempt, retry, exc)
                time.sleep(min(attempt, 10))

        if data is None:
            raise RuntimeError("接口无响应，已停止导出")

        body = data.get("data", {})
        page_refunds = body.get("after_sale_order_list") or []
        if not page_refunds:
            break

        added_count = 0
        for refund in page_refunds:
            key = refund.get("after_sale_id") or refund.get("order_id") or json.dumps(refund, sort_keys=True)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            refunds.append(refund)
            added_count += 1

        next_cursor = str(body.get("cursor", "")).strip()
        logging.info(
            "状态=%s 本页 %s 条，新增 %s 条，累计 %s 条，cursor=%s",
            refund_status if refund_status is not None else "全部",
            len(page_refunds),
            added_count,
            len(refunds),
            next_cursor,
        )
        if not body.get("has_more") or not next_cursor or next_cursor == cursor:
            break
        if MAX_PAGES and current_page >= MAX_PAGES:
            logging.info("已达到测试页数上限 DOUYIN_REFUND_MAX_PAGES=%s，提前结束", MAX_PAGES)
            break
        cursor = next_cursor
        time.sleep(REQUEST_SLEEP_SECONDS)

    return refunds


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


def product_type_for_sku(sku_id: Any) -> str:
    return SKU_TYPE_MAP.get(normalize_id(sku_id), "")


def order_key(value: Any) -> str:
    return normalize_id(value)


def is_amount_field(key: str) -> bool:
    keywords = ("amount", "price", "fee", "money", "discount")
    return any(keyword in key.lower() for keyword in keywords)


def fetch_target_order_map(
    token: str,
    start: datetime,
    end: datetime,
    retry: int = REQUEST_RETRY,
) -> Dict[str, Dict[str, str]]:
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    result: Dict[str, Dict[str, str]] = {}
    seen_order_ids = set()
    page = 1

    while True:
        params = {
            "account_id": ACCOUNT_ID,
            "page_num": page,
            "page_size": PAGE_SIZE,
            "create_order_start_time": int(start.timestamp()),
            "create_order_end_time": int(end.timestamp()),
        }
        data = None
        for attempt in range(1, retry + 1):
            try:
                data = get_json(ORDER_API_URL, headers=headers, params=params, timeout=30)
                if response_has_error(data):
                    message = error_message(data)
                    if is_token_expired(message):
                        token = get_token()
                        headers["access-token"] = token
                        logging.info("Token 已刷新，继续建立订单 SKU 映射")
                        continue
                    if attempt < retry:
                        logging.warning("订单接口返回错误（%s/%s）：%s", attempt, retry, message)
                        time.sleep(attempt)
                        continue
                    raise RuntimeError("订单接口返回错误：" + message)
                break
            except Exception as exc:
                if "订单接口返回错误：" in str(exc):
                    raise
                logging.warning("订单映射请求异常（%s/%s）：%s", attempt, retry, exc)
                time.sleep(min(attempt, 10))

        if data is None:
            raise RuntimeError("订单接口无响应，无法建立 SKU 映射")

        body = data.get("data", {})
        orders = body.get("orders") or []
        if not orders:
            break

        matched_count = 0
        for order in orders:
            order_id = order_key(order.get("order_id"))
            if not order_id or order_id in seen_order_ids:
                continue
            seen_order_ids.add(order_id)
            sku_id = normalize_id(order.get("sku_id"))
            product_type = product_type_for_sku(sku_id)
            if not product_type:
                continue
            result[order_id] = {
                "sku_id": sku_id,
                "sku_name": str(order.get("sku_name") or ""),
                "product_type": product_type,
            }
            matched_count += 1

        logging.info(
            "订单映射第 %s 页：本页 %s 条，命中 %s 条，累计命中 %s 条",
            page,
            len(orders),
            matched_count,
            len(result),
        )

        if MAX_ORDER_PAGES and page >= MAX_ORDER_PAGES:
            logging.info("已达到订单测试页数上限 DOUYIN_REFUND_MAX_ORDER_PAGES=%s，提前结束", MAX_ORDER_PAGES)
            break
        if len(orders) < PAGE_SIZE:
            break
        page += 1
        time.sleep(REQUEST_SLEEP_SECONDS)

    return result


def attach_order_sku_info(refunds: List[Dict[str, Any]], order_map: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    result = []
    for refund in refunds:
        info = order_map.get(order_key(refund.get("order_id")))
        if FILTER_TARGET_SKUS and not info:
            continue
        if info:
            refund = dict(refund)
            refund["sku_id"] = info["sku_id"]
            refund["sku_name"] = info["sku_name"]
            refund["product_type"] = info["product_type"]
        result.append(refund)
    return result


def format_refund(refund: Dict[str, Any]) -> Dict[str, Any]:
    flat = flatten(refund)
    output: Dict[str, Any] = {}
    for key, value in flat.items():
        if "time" in key.lower():
            value = format_time(value)
        if is_amount_field(key):
            value = format_amount(value)
        if key in {"after_sale_id", "order_id", "merchant_account_id"}:
            value = normalize_id(value)
        if key in {"status", "refund_status"}:
            try:
                value = REFUND_STATUS_MAP.get(int(value), value)
            except Exception:
                pass
        output[FIELD_MAP.get(key, key)] = value
    return output


def ordered_fields(rows: Iterable[Dict[str, Any]]) -> List[str]:
    fields = set()
    for row in rows:
        fields.update(row.keys())
    return PREFERRED_FIELDS + sorted(fields - set(PREFERRED_FIELDS))


def split_ranges(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    ranges = []
    current = start
    while current < end:
        next_end = min(current + timedelta(days=CHUNK_DAYS), end)
        ranges.append((current, next_end))
        current = next_end
    return ranges


def save_refunds(refunds: List[Dict[str, Any]], start: datetime, end: datetime) -> Tuple[Path, Path]:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    base_name = f"抖音来客退款单_{start:%Y%m%d}_{(end - timedelta(seconds=1)):%Y%m%d}"
    csv_path = SAVE_DIR / f"{base_name}.csv"
    json_path = SAVE_DIR / f"{base_name}.json"

    rows = [format_refund(refund) for refund in refunds]
    fields = ordered_fields(rows) if rows else PREFERRED_FIELDS

    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(refunds, file, ensure_ascii=False, indent=2)

    logging.info("CSV 已导出：%s", csv_path)
    logging.info("JSON 原始数据已导出：%s", json_path)
    return csv_path, json_path


def dedupe_refunds(refunds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    seen = set()
    for refund in refunds:
        key = refund.get("after_sale_id") or refund.get("order_id") or json.dumps(refund, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(refund)
    return result


def main() -> None:
    setup_logging()
    require_config()

    start, end = export_range()
    if start >= end:
        raise RuntimeError("导出开始时间必须早于结束时间")

    logging.info("开始导出退款单：%s 到 %s，时间字段=%s", start, end, TIME_FIELD)
    token = get_token()
    order_map = fetch_target_order_map(token, start, end) if FILTER_TARGET_SKUS else {}
    if FILTER_TARGET_SKUS:
        logging.info("订单 SKU 映射建立完成，命中目标 SKU 的订单数：%s", len(order_map))

    refunds: List[Dict[str, Any]] = []
    statuses: List[Optional[int]] = REFUND_STATUSES or [None]
    ranges = split_ranges(start, end)

    for range_index, (range_start, range_end) in enumerate(ranges, start=1):
        logging.info("开始拉取分段 %s/%s：%s 到 %s", range_index, len(ranges), range_start, range_end)
        for status in statuses:
            refunds.extend(fetch_refunds(token, range_start, range_end, status))

    refunds = dedupe_refunds(refunds)
    before_filter_count = len(refunds)
    refunds = attach_order_sku_info(refunds, order_map)
    if FILTER_TARGET_SKUS:
        logging.info("按目标 SKU 过滤退款单：%s -> %s 条", before_filter_count, len(refunds))
    csv_path, json_path = save_refunds(refunds, start, end)
    logging.info("导出完成：%s 条；CSV=%s；JSON=%s", len(refunds), csv_path, json_path)


if __name__ == "__main__":
    main()
