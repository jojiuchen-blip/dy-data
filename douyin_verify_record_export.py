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


APP_ID = os.getenv("DOUYIN_APP_ID")
APP_SECRET = os.getenv("DOUYIN_APP_SECRET")
ACCOUNT_ID = os.getenv("DOUYIN_ACCOUNT_ID")
POI_IDS = [x.strip() for x in os.getenv("DOUYIN_POI_IDS", "").split(",") if x.strip()]
POI_NAME_MAP = json.loads(os.getenv("DOUYIN_POI_NAME_MAP", "{}") or "{}")

API_URL = "https://open.douyin.com/goodlife/v1/fulfilment/certificate/verify_record/query/"
SHOP_POI_QUERY_URL = "https://open.douyin.com/goodlife/v1/shop/poi/query/"
TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
SAVE_DIR = Path(os.getenv("DOUYIN_VERIFY_SAVE_DIR", r"D:\抖音来客看板\output-finished"))
PARTS_DIR = SAVE_DIR / "parts"

PAGE_SIZE = min(max(int(os.getenv("DOUYIN_PAGE_SIZE", "20")), 1), 20)
REQUEST_SLEEP_SECONDS = float(os.getenv("DOUYIN_REQUEST_SLEEP_SECONDS", "0.2"))
CHUNK_DAYS = max(int(os.getenv("DOUYIN_VERIFY_CHUNK_DAYS", "7")), 1)
QUERY_SHOP_POIS = os.getenv("DOUYIN_VERIFY_QUERY_SHOP_POIS", "0") == "1"
POI_LIMIT = int(os.getenv("DOUYIN_VERIFY_POI_LIMIT", "0") or "0")
SHOP_POI_RELATION_TYPES = [
    int(x.strip())
    for x in os.getenv("DOUYIN_SHOP_POI_RELATION_TYPES", "0").split(",")
    if x.strip()
]

SKU_TYPE_MAP = {
    "1834808062911500": "268保养",
    "1839843694054411": "268保养",
    "1836174558502924": "268保养",
    "1834807415534650": "168保养",
    "1836174232747016": "168保养",
    "1842945450213424": "漆面",
    "1859247916957723": "漆面",
    "1859251879725066": "漆面",
    "1838947657772048": "漆面",
    "1865042571753472": "蒸发箱清洗",
    "1865042831665155": "外循环清洗",
}
TARGET_SKU_IDS = set(SKU_TYPE_MAP)


FIELD_MAP = {
    "verify_poi_id": "核销门店ID",
    "verify_poi_name": "核销门店名称",
    "verify_time": "核销时间",
    "verify_id": "核销ID",
    "certificate_id": "券ID",
    "code": "券码",
    "certificate_status": "券状态",
    "status": "记录状态",
    "verify_type": "核销类型",
    "fulfil_operator_name": "核销操作人",
    "fulfil_operator_id": "核销操作人ID",
    "can_cancel": "是否可撤销",
    "cancel_time": "撤销时间",
    "cursor": "游标",
    "sku.sku_id": "SKU_ID",
    "sku.title": "商品名称",
    "sku.product_id": "商品ID",
    "sku.product_out_id": "外部商品ID",
    "sku.sku_out_id": "外部SKU_ID",
    "sku.third_sku_id": "三方SKU_ID",
    "product_type": "商品类型",
    "sku.account_id": "商家账号ID",
    "sku.market_price": "市场价",
    "amount.original_amount": "原价",
    "amount.pay_amount": "实付金额",
    "amount.coupon_pay_amount": "券实付金额",
    "amount.platform_discount_amount": "平台优惠",
    "amount.merchant_ticket_amount": "商家营销金额",
    "amount.brand_ticket_amount": "品牌补贴",
    "amount.payment_discount_amount": "支付优惠",
    "amount.list_market_amount": "划线价",
}

PREFERRED_FIELDS = [
    "核销门店ID",
    "核销门店名称",
    "核销时间",
    "核销ID",
    "券ID",
    "券码",
    "商品名称",
    "SKU_ID",
    "商品类型",
    "商品ID",
    "外部商品ID",
    "外部SKU_ID",
    "三方SKU_ID",
    "核销操作人",
    "核销操作人ID",
    "核销类型",
    "券状态",
    "记录状态",
    "是否可撤销",
    "撤销时间",
    "原价",
    "实付金额",
    "券实付金额",
    "平台优惠",
    "商家营销金额",
    "品牌补贴",
    "支付优惠",
    "划线价",
    "商家账号ID",
    "游标",
]

STATUS_MAP = {
    0: "未知",
    1: "有效/已核销",
    2: "已撤销",
}

VERIFY_TYPE_MAP = {
    1: "抖音券核销",
    2: "三方券核销",
}


def setup_logging() -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = SAVE_DIR / "douyin_verify_record_export.log"
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


def get_token(retry: int = 10) -> str:
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
        time.sleep(1)
    raise RuntimeError("Token 获取失败，已停止导出")


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


def parse_datetime(value: str) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt == "%Y-%m-%d" and " 23:59:59" in value:
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
    start_value = os.getenv("DOUYIN_VERIFY_START")
    end_value = os.getenv("DOUYIN_VERIFY_END")
    if start_value and end_value:
        return parse_datetime(start_value), parse_datetime(end_value)
    if start_value or end_value:
        raise RuntimeError("DOUYIN_VERIFY_START 和 DOUYIN_VERIFY_END 需要同时设置")
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


def fetch_shop_pois(token: str, retry: int = 3) -> List[Dict[str, str]]:
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    result: List[Dict[str, str]] = []
    seen = set()

    for relation_type in SHOP_POI_RELATION_TYPES:
        page = 1
        while True:
            params = {
                "account_id": ACCOUNT_ID,
                "page": page,
                "size": 50,
                "relation_type": relation_type,
            }
            data = None
            for attempt in range(1, retry + 1):
                try:
                    data = get_json(SHOP_POI_QUERY_URL, headers=headers, params=params, timeout=30)
                    break
                except Exception as exc:
                    logging.warning("门店列表请求异常（%s/%s）：%s", attempt, retry, exc)
                    time.sleep(1)

            if data is None:
                raise RuntimeError("门店列表接口无响应，已停止导出")
            if response_has_error(data):
                raise RuntimeError("门店列表接口返回错误：" + error_message(data))

            body = data.get("data", {})
            pois = body.get("pois") or body.get("poi_list") or body.get("list") or []
            if not pois:
                break

            for poi in pois:
                poi_info = poi.get("poi") if isinstance(poi.get("poi"), dict) else poi
                poi_id = normalize_id(poi_info.get("poi_id") or poi_info.get("id"))
                if not poi_id or poi_id in seen:
                    continue
                seen.add(poi_id)
                poi_name = str(poi_info.get("poi_name") or poi_info.get("name") or "").strip()
                result.append({"poi_id": poi_id, "poi_name": poi_name})

            total = body.get("total")
            logging.info(
                "门店列表 relation_type=%s 第%s页，本页%s个，累计%s个",
                relation_type,
                page,
                len(pois),
                len(result),
            )
            if total not in (None, ""):
                try:
                    if page * 50 >= int(total):
                        break
                except Exception:
                    pass
            if len(pois) < 50:
                break
            page += 1
            time.sleep(REQUEST_SLEEP_SECONDS)

    return result


def fetch_verify_records(
    token: str,
    start: datetime,
    end: datetime,
    poi_id: Optional[str] = None,
    retry: int = 12,
) -> List[Dict[str, Any]]:
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    cursor = "0"
    records: List[Dict[str, Any]] = []
    seen_keys = set()

    while True:
        params: Dict[str, Any] = {
            "account_id": ACCOUNT_ID,
            "cursor": cursor,
            "size": PAGE_SIZE,
            "start_time": int(start.timestamp()),
            "end_time": int(end.timestamp()),
        }
        if poi_id:
            params["poi_ids"] = json.dumps([poi_id], ensure_ascii=False)
        elif POI_IDS:
            params["poi_ids"] = json.dumps(POI_IDS, ensure_ascii=False)

        data = None
        last_error = ""
        for attempt in range(1, retry + 1):
            try:
                data = get_json(API_URL, headers=headers, params=params, timeout=30)
                if response_has_error(data):
                    last_error = error_message(data)
                    logging.warning("接口返回错误（%s/%s）：%s", attempt, retry, last_error)
                    data = None
                    time.sleep(1)
                    continue
                break
            except Exception as exc:
                logging.warning("请求异常（%s/%s）：%s", attempt, retry, exc)
                time.sleep(1)

        if data is None:
            raise RuntimeError(last_error or "接口无响应，已停止导出")

        body = data.get("data", {})
        page_records = body.get("records_v2") or body.get("records") or []
        if not page_records:
            break

        matched_count = 0
        for record in page_records:
            key = record.get("verify_id") or record.get("certificate_id") or json.dumps(record, sort_keys=True)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if is_target_record(record):
                if poi_id:
                    record["verify_poi_id"] = poi_id
                    record["verify_poi_name"] = POI_NAME_MAP.get(poi_id, "")
                records.append(record)
                matched_count += 1

        next_cursor = str(page_records[-1].get("cursor", "")).strip()
        logging.info(
            "本页 %s 条，命中 %s 条，累计命中 %s 条，cursor=%s",
            len(page_records),
            matched_count,
            len(records),
            next_cursor,
        )
        if not next_cursor or next_cursor == cursor or len(page_records) < PAGE_SIZE:
            break
        cursor = next_cursor
        time.sleep(REQUEST_SLEEP_SECONDS)

    return records


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


def record_sku_id(record: Dict[str, Any]) -> str:
    sku = record.get("sku")
    if isinstance(sku, dict):
        return normalize_id(sku.get("sku_id"))
    return normalize_id(record.get("sku_id") or record.get("sku.sku_id"))


def product_type_for_sku(sku_id: str) -> str:
    return SKU_TYPE_MAP.get(normalize_id(sku_id), "")


def is_target_record(record: Dict[str, Any]) -> bool:
    return record_sku_id(record) in TARGET_SKU_IDS


def is_amount_field(key: str) -> bool:
    keywords = ("amount", "price", "fee", "money", "discount")
    return any(keyword in key.lower() for keyword in keywords)


def format_record(record: Dict[str, Any]) -> Dict[str, Any]:
    flat = flatten(record)
    sku_id = record_sku_id(record)
    flat["product_type"] = product_type_for_sku(sku_id)
    output: Dict[str, Any] = {}
    for key, value in flat.items():
        if "time" in key.lower():
            value = format_time(value)
        if is_amount_field(key):
            value = format_amount(value)
        if key in {"verify_id", "certificate_id", "sku.sku_id", "sku.product_id"}:
            value = normalize_id(value)
        if key in {"certificate_status", "status"}:
            try:
                value = STATUS_MAP.get(int(value), value)
            except Exception:
                pass
        if key == "verify_type":
            try:
                value = VERIFY_TYPE_MAP.get(int(value), value)
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


def fetch_range_with_retries(
    start: datetime,
    end: datetime,
    poi_id: Optional[str] = None,
    retry: int = 20,
) -> List[Dict[str, Any]]:
    last_error = None
    for attempt in range(1, retry + 1):
        try:
            token = get_token()
            return fetch_verify_records(token, start, end, poi_id=poi_id, retry=12)
        except Exception as exc:
            last_error = exc
            logging.warning("分段拉取失败（%s/%s）：%s", attempt, retry, exc)
            time.sleep(min(attempt * 5, 30))
    raise RuntimeError(f"分段拉取失败，已重试 {retry} 次：{last_error}")


def record_key(record: Dict[str, Any]) -> str:
    return str(record.get("verify_id") or record.get("certificate_id") or json.dumps(record, sort_keys=True))


def dedupe_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    seen = set()
    for record in records:
        key = record_key(record)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def part_path(start: datetime, end: datetime, poi_id: Optional[str] = None) -> Path:
    suffix = f"_{poi_id}" if poi_id else ""
    return PARTS_DIR / f"verify_part_{start:%Y%m%d}_{(end - timedelta(seconds=1)):%Y%m%d}{suffix}.json"


def load_part(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        records = json.load(file)
    logging.info("复用已完成分段：%s（%s 条）", path, len(records))
    return records


def save_part(path: Path, records: List[Dict[str, Any]]) -> None:
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
    tmp_path.replace(path)
    logging.info("分段已保存：%s（%s 条）", path, len(records))


def fetch_or_load_part(start: datetime, end: datetime, poi_id: Optional[str] = None) -> List[Dict[str, Any]]:
    path = part_path(start, end, poi_id)
    cached = load_part(path)
    if cached is not None:
        return cached
    records = fetch_range_with_retries(start, end, poi_id=poi_id)
    save_part(path, records)
    return records


def save_records(records: List[Dict[str, Any]], start: datetime, end: datetime) -> Tuple[Path, Path]:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    base_name = f"抖音来客券核销清单_{start:%Y%m%d}_{(end - timedelta(seconds=1)):%Y%m%d}"
    csv_path = SAVE_DIR / f"{base_name}.csv"
    json_path = SAVE_DIR / f"{base_name}.json"

    rows = [format_record(record) for record in records]
    fields = ordered_fields(rows) if rows else PREFERRED_FIELDS

    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    logging.info("CSV 已导出：%s", csv_path)
    logging.info("JSON 原始数据已导出：%s", json_path)
    return csv_path, json_path


def main() -> None:
    setup_logging()
    require_config()

    start, end = export_range()
    if start >= end:
        raise RuntimeError("导出开始时间必须早于结束时间")

    logging.info("开始导出核销清单：%s 到 %s", start, end)
    poi_ids = POI_IDS
    if not poi_ids and QUERY_SHOP_POIS:
        token = get_token()
        shop_pois = fetch_shop_pois(token)
        poi_ids = [poi["poi_id"] for poi in shop_pois]
        POI_NAME_MAP.update({poi["poi_id"]: poi.get("poi_name", "") for poi in shop_pois})
        logging.info("已从门店接口获取 %s 个门店，将逐门店拉取验券历史", len(poi_ids))
    if POI_LIMIT > 0:
        poi_ids = poi_ids[:POI_LIMIT]
        logging.info("已限制本次只拉取前 %s 个门店", len(poi_ids))

    records = []
    ranges = split_ranges(start, end)
    for index, (range_start, range_end) in enumerate(ranges, start=1):
        logging.info("开始拉取分段 %s/%s：%s 到 %s", index, len(ranges), range_start, range_end)
        if poi_ids:
            for poi_index, poi_id in enumerate(poi_ids, start=1):
                logging.info("开始拉取门店 %s/%s：%s", poi_index, len(poi_ids), poi_id)
                try:
                    records.extend(fetch_or_load_part(range_start, range_end, poi_id=poi_id))
                except Exception as exc:
                    logging.warning("门店 %s 拉取失败，已跳过：%s", poi_id, exc)
        else:
            records.extend(fetch_or_load_part(range_start, range_end))
    records = dedupe_records(records)
    csv_path, json_path = save_records(records, start, end)
    logging.info("导出完成：%s 条；CSV=%s；JSON=%s", len(records), csv_path, json_path)


if __name__ == "__main__":
    main()
