from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
import time
from typing import Any

import requests

from .douyin_rate_limits import DouyinApiError, endpoint_key_for_url


TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
ORDER_QUERY_URL = "https://open.douyin.com/goodlife/v1/trade/order/query/"
VERIFY_RECORD_QUERY_URL = "https://open.douyin.com/goodlife/v1/fulfilment/certificate/verify_record/query/"
CERTIFICATE_QUERY_URL = "https://open.douyin.com/goodlife/v1/fulfilment/certificate/query/"
REFUND_QUERY_URL = "https://open.douyin.com/goodlife/v1/akte/after_sale/order/query/"
SHOP_POI_QUERY_URL = "https://open.douyin.com/goodlife/v1/shop/poi/query/"
CRAFTSMAN_BIND_INFO_URL = "https://open.douyin.com/goodlife/v2/craftsman_openapi/merchat/craftsman/bind_info/all/"
CLUE_QUERY_URL = "https://open.douyin.com/goodlife/v1/open_api/crm/clue/query/"
PRODUCT_ONLINE_QUERY_URL = "https://open.douyin.com/goodlife/v1/goods/product/online/query/"
PRODUCT_ONLINE_GET_URL = "https://open.douyin.com/goodlife/v1/goods/product/online/get/"
CIPHER_DECRYPT_URL = "https://open.douyin.com/goodlife/v1/open/common_biz/crypto/decrypt/batch/"
CIPHER_DECRYPT_MASK_URL = "https://open.douyin.com/goodlife/v1/open/common_biz/crypto/decrypt_mask/batch/"
CIPHER_BATCH_SIZE = 50


def douyin_headers(token: str, account_id: str) -> dict[str, str]:
    return {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": account_id,
    }


@dataclass(frozen=True)
class DouyinCredentials:
    app_id: str
    app_secret: str
    account_id: str


class DouyinOpenApiClient:
    def __init__(
        self,
        credentials: DouyinCredentials,
        *,
        http: Any | None = None,
        timeout_seconds: int = 30,
        retry_attempts: int = 3,
        retry_sleep_seconds: float = 1.0,
        rate_limit_retry_sleep_seconds: float = 60.0,
        request_governor: Any | None = None,
        governor: Any | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if request_governor is not None and governor is not None:
            raise ValueError("Pass only one of request_governor or governor")
        self.credentials = credentials
        self.http = http or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_sleep_seconds = retry_sleep_seconds
        self.rate_limit_retry_sleep_seconds = rate_limit_retry_sleep_seconds
        self.request_governor = request_governor if request_governor is not None else governor
        self.clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._token: str | None = None

    def get_client_token(self) -> str:
        payload = {
            "client_key": self.credentials.app_id,
            "client_secret": self.credentials.app_secret,
            "grant_type": "client_credential",
        }
        data = self._post_json(TOKEN_URL, payload, headers={"content-type": "application/json"})
        token = data.get("data", {}).get("access_token")
        if not token:
            raise DouyinApiError(self._sanitize(f"Douyin token response did not include access_token: {data}"))
        self._token = str(token)
        return self._token

    def query_orders(
        self,
        start: datetime,
        end: datetime,
        *,
        page_size: int = 100,
        cursor: str | int | None = None,
    ) -> dict[str, Any]:
        params = {
            "account_id": self.credentials.account_id,
            "cursor": _cursor_param(cursor),
            "page_size": page_size,
            "create_order_start_time": int(start.timestamp()),
            "create_order_end_time": int(end.timestamp()),
        }
        return self._get_json(ORDER_QUERY_URL, params)

    def query_refunds(
        self,
        start: datetime,
        end: datetime,
        *,
        page_size: int = 100,
        cursor: str | int | None = None,
        time_field: str = "refund_done",
    ) -> dict[str, Any]:
        """Query one bounded after-sale/refund page."""

        if page_size < 1 or page_size > 100:
            raise ValueError("Refund query page_size must be between 1 and 100")
        if time_field not in {"refund_done", "create_order"}:
            raise ValueError("Refund time_field must be refund_done or create_order")
        params = {
            "account_id": self.credentials.account_id,
            "cursor": _cursor_param(cursor),
            "page_size": page_size,
            f"{time_field}_start_time": int(start.timestamp()),
            f"{time_field}_end_time": int(end.timestamp()),
        }
        return self._get_json(REFUND_QUERY_URL, params)

    def query_product_page(
        self,
        *,
        url: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Send one authenticated product-page request.

        The external product endpoint, request parameter names, and response mapping
        are intentionally injected until a sanitized official sample freezes that
        contract.  This method only provides the existing authenticated/retrying
        transport boundary.
        """

        if not str(url or "").strip():
            raise ValueError("Product sync URL is required")
        return self._get_json(str(url).strip(), dict(params))

    def query_online_products(
        self,
        *,
        status: int,
        cursor: str | None = None,
        count: int = 50,
        goods_query_type: int = 2,
    ) -> dict[str, Any]:
        """Query one official online-product list page.

        Douyin documents status 1/2/3 as online/offline/banned and caps a
        normal page at 50 rows. The account is sent in both the authenticated
        transit header and query parameters, consistent with the other
        Goodlife endpoints used by this client.
        """

        if status not in {1, 2, 3}:
            raise ValueError("Product status must be 1, 2, or 3")
        if count < 1 or count > 50:
            raise ValueError("Product query count must be between 1 and 50")
        if goods_query_type not in {1, 2, 3}:
            raise ValueError("goods_query_type must be 1, 2, or 3")
        params: dict[str, Any] = {
            "account_id": self.credentials.account_id,
            "count": count,
            "goods_query_type": goods_query_type,
            "status": status,
        }
        if cursor not in (None, ""):
            params["cursor"] = str(cursor)
        return self._get_json(PRODUCT_ONLINE_QUERY_URL, params)

    def query_online_products_by_id(
        self,
        product_ids: list[str],
    ) -> dict[str, Any]:
        """Query official online-product details for at most ten product IDs."""

        cleaned = list(
            dict.fromkeys(str(value).strip() for value in product_ids if str(value).strip())
        )
        if not cleaned:
            raise ValueError("At least one product ID is required")
        if len(cleaned) > 10:
            raise ValueError("Product ID query accepts at most 10 product IDs")
        return self._get_json(
            PRODUCT_ONLINE_GET_URL,
            {
                "account_id": self.credentials.account_id,
                "product_ids": cleaned,
            },
        )

    def iter_orders(self, start: datetime, end: datetime, *, page_size: int = 100):
        cursor: str | None = "0"
        seen: set[str] = set()
        seen_cursors: set[str] = set()
        while cursor and cursor not in seen_cursors:
            seen_cursors.add(cursor)
            payload = self.query_orders(start, end, page_size=page_size, cursor=cursor)
            data = payload.get("data", {})
            orders = data.get("orders") or data.get("list") or []
            for order in orders:
                order_id = str(order.get("order_id") or "").strip()
                if order_id and order_id in seen:
                    continue
                if order_id:
                    seen.add(order_id)
                yield order

            if len(orders) < page_size:
                break
            cursor = _order_next_cursor(data)

    def iter_refunds(
        self,
        start: datetime,
        end: datetime,
        *,
        page_size: int = 100,
        time_field: str = "refund_done",
    ):
        """Yield refund rows while guarding cursor loops and non-advancing pages."""

        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            payload = self.query_refunds(
                start,
                end,
                page_size=page_size,
                cursor=cursor,
                time_field=time_field,
            )
            data = payload.get("data", {})
            rows = (
                data.get("refunds")
                or data.get("after_sales")
                or data.get("after_sale_orders")
                or data.get("after_sale_order_list")
                or data.get("records")
                or data.get("list")
                or []
            )
            if not isinstance(rows, list):
                rows = []
            for row in rows:
                if isinstance(row, dict):
                    yield row
            page_info = data.get("page_info") if isinstance(data.get("page_info"), dict) else {}
            raw_has_more = (
                data.get("has_more")
                if data.get("has_more") is not None
                else page_info.get("has_more")
            )
            has_more = _explicit_bool(raw_has_more)
            if has_more is False:
                break
            if has_more is None:
                raise DouyinApiError("refund has_more must be explicit true or false")
            next_cursor = _refund_next_cursor(data, rows)
            if not next_cursor:
                raise DouyinApiError("refund cursor missing while has_more is true")
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise DouyinApiError(f"refund cursor did not advance: {next_cursor}")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def query_verify_records(
        self,
        start: datetime,
        end: datetime,
        *,
        poi_id: str | None = None,
        page_size: int = 20,
        cursor: str | int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "account_id": self.credentials.account_id,
            "size": page_size,
            "cursor": str(cursor or "0"),
            "start_time": int(start.timestamp()),
            "end_time": int(end.timestamp()),
        }
        if poi_id:
            params["poi_ids"] = poi_id
        return self._get_json(VERIFY_RECORD_QUERY_URL, params)

    def query_certificates(self, *, order_id: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "account_id": self.credentials.account_id,
            "order_id": order_id,
        }
        return self._get_json(CERTIFICATE_QUERY_URL, params)

    def query_shop_pois(self, *, relation_type: int = 0, cursor: str | int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "account_id": self.credentials.account_id,
            "relation_type": relation_type,
        }
        if cursor not in (None, ""):
            params["cursor"] = cursor
        return self._get_json(SHOP_POI_QUERY_URL, params)

    def query_craftsman_bind_info(self, *, cursor: str | int | None = None, size: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {
            "account_id": self.credentials.account_id,
            "cursor": str(cursor or "0"),
            "size": size,
        }
        return self._get_json(CRAFTSMAN_BIND_INFO_URL, params)

    def query_clues(
        self,
        start: datetime,
        end: datetime,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "account_id": self.credentials.account_id,
            "page": page,
            "page_size": page_size,
            "start_time": _datetime_param(start),
            "end_time": _datetime_param(end),
        }
        return self._get_json(CLUE_QUERY_URL, params)

    def decrypt_cipher_texts(self, cipher_texts: list[str]) -> dict[str, str]:
        return self._decrypt_cipher_texts(CIPHER_DECRYPT_URL, cipher_texts)

    def decrypt_mask_cipher_texts(self, cipher_texts: list[str]) -> dict[str, str]:
        return self._decrypt_cipher_texts(CIPHER_DECRYPT_MASK_URL, cipher_texts)

    def _decrypt_cipher_texts(self, url: str, cipher_texts: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        cleaned = _clean_cipher_texts(cipher_texts)
        for batch in _chunks(cleaned, CIPHER_BATCH_SIZE):
            payload = self._post_json(
                url,
                {
                    "account_id": self.credentials.account_id,
                    "cipher_texts": batch,
                },
                headers=self._token_headers(),
            )
            result.update(_cipher_result_map(payload, batch))
        return result

    def _token_headers(self) -> dict[str, str]:
        token = self._token or self.get_client_token()
        return douyin_headers(token, self.credentials.account_id)

    def _post_json(self, url: str, payload: dict[str, Any], *, headers: dict[str, str]) -> dict[str, Any]:
        return self._json_request_with_retries(
            "post",
            url,
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
        )

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._json_request_with_retries(
            "get",
            url,
            headers=self._token_headers(),
            params=params,
            timeout=self.timeout_seconds,
        )

    def _json_request_with_retries(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        attempts = max(1, self.retry_attempts)
        last_error: DouyinApiError | None = None
        for attempt in range(1, attempts + 1):
            response = self._request_with_retries(method, url, **kwargs)
            try:
                return self._handle_response(response)
            except DouyinApiError as exc:
                last_error = exc
                if _is_token_expired_api_error(str(exc)) and attempt < attempts:
                    self._token = None
                    headers = kwargs.get("headers")
                    if isinstance(headers, dict) and "access-token" in headers:
                        kwargs["headers"] = self._token_headers()
                    continue
                if not _is_transient_api_error(str(exc)) or attempt >= attempts:
                    raise
                delay_seconds = (
                    self.rate_limit_retry_sleep_seconds * (2 ** (attempt - 1))
                    if _is_rate_limit_api_error(str(exc))
                    else self.retry_sleep_seconds * attempt
                )
                self._sleep(delay_seconds)
        raise last_error or DouyinApiError("Douyin API request failed.")

    def _request_with_retries(self, method: str, url: str, **kwargs: Any) -> Any:
        attempts = max(1, self.retry_attempts)
        last_error: requests.RequestException | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._acquire_request(url, method)
                request = getattr(self.http, method)
                return request(url, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                self._sleep(self.retry_sleep_seconds * attempt)
        raise DouyinApiError(self._sanitize(f"Douyin API transport error: {last_error}")) from last_error

    def _acquire_request(self, url: str, method: str) -> None:
        if self.request_governor is None:
            return
        acquire = getattr(self.request_governor, "acquire", None)
        if not callable(acquire):
            raise TypeError("request_governor must provide acquire(endpoint_key)")
        acquire(endpoint_key_for_url(url, method))

    def _handle_response(self, response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - external API response parsing boundary.
            raise DouyinApiError(self._sanitize(f"Douyin API returned non-JSON response: {response.text}")) from exc

        if getattr(response, "status_code", 200) >= 400 or _has_api_error(payload):
            raise DouyinApiError(self._sanitize(f"Douyin API error: {_api_error_summary(payload)}"))
        return payload

    def _sanitize(self, message: str) -> str:
        sanitized = message
        for secret in (self.credentials.app_secret, self._token):
            if secret:
                sanitized = sanitized.replace(secret, "[redacted]")
        return sanitized[:1800]


def _has_api_error(payload: dict[str, Any]) -> bool:
    code = _api_error_code(payload)
    return code not in (None, 0, "0")


def _api_error_code(payload: dict[str, Any]) -> Any:
    code = payload.get("error_code", payload.get("err_no", payload.get("code")))
    if code in (None, 0, "0"):
        data = payload.get("data")
        if isinstance(data, dict):
            code = data.get("error_code")
    return code


def _api_error_summary(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    return {
        "error_code": _api_error_code(payload),
        "description": _first_text(
            data.get("description"),
            payload.get("description"),
            payload.get("message"),
            extra.get("description"),
        ),
        "sub_error_code": extra.get("sub_error_code"),
        "sub_description": extra.get("sub_description"),
        "logid": extra.get("logid") or extra.get("log_id"),
        "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "list_lengths": {key: len(value) for key, value in data.items() if isinstance(value, list)}
        if isinstance(data, dict)
        else {},
    }


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_transient_api_error(message: str) -> bool:
    return (
        "5000001" in message
        or "2100004" in message
        or "系统繁忙" in message
        or _is_rate_limit_api_error(message)
    )


def _is_rate_limit_api_error(message: str) -> bool:
    return "2119003" in message or "请求太过频繁" in message


def _is_token_expired_api_error(message: str) -> bool:
    return "2190008" in message or "access_token过期" in message


def _cursor_param(cursor: Any) -> str:
    if cursor in (None, ""):
        return "0"
    if isinstance(cursor, (list, dict)):
        return json.dumps(cursor, separators=(",", ":"), ensure_ascii=False)
    return str(cursor)


def _datetime_param(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _clean_cipher_texts(values: list[str]) -> list[str]:
    return [str(value).strip() for value in values if str(value or "").strip()]


def _chunks(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _cipher_result_map(payload: dict[str, Any], requested: list[str]) -> dict[str, str]:
    rows = _cipher_result_rows(payload)
    result: dict[str, str] = {}
    if rows and all(isinstance(row, str) for row in rows):
        for cipher_text, plain_text in zip(requested, rows):
            if plain_text:
                result[cipher_text] = str(plain_text)
        return result

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        cipher_text = _first_text(
            row.get("cipher_text"),
            row.get("ciphertext"),
            row.get("encrypted_text"),
            row.get("encrypt_text"),
        )
        if not cipher_text and index < len(requested):
            cipher_text = requested[index]
        plain_text = _first_text(
            row.get("plain_text"),
            row.get("decrypt_text"),
            row.get("decrypted_text"),
            row.get("phone_number"),
            row.get("phone"),
            row.get("masked_phone"),
            row.get("masked_text"),
            row.get("mask_text"),
            row.get("text"),
            row.get("value"),
        )
        if cipher_text and plain_text:
            result[str(cipher_text)] = str(plain_text)
    return result


def _cipher_result_rows(payload: dict[str, Any]) -> list[Any]:
    data = payload.get("data")
    if isinstance(data, list):
        return data
    source = data if isinstance(data, dict) else payload
    for key in (
        "decrypt_result_list",
        "decrypt_results",
        "result_list",
        "results",
        "phone_number_list",
        "plain_text_list",
        "list",
    ):
        value = source.get(key)
        if isinstance(value, list):
            return value
    return []


def _order_next_cursor(data: dict[str, Any]) -> str | None:
    search_after = data.get("search_after")
    if not isinstance(search_after, dict):
        return None
    cursor_value = search_after.get("CursorValue")
    if not cursor_value:
        return None
    return _cursor_param(cursor_value)


def _refund_next_cursor(data: dict[str, Any], rows: list[Any]) -> str | None:
    page_info = data.get("page_info") if isinstance(data.get("page_info"), dict) else {}
    for key in ("next_cursor", "cursor", "next_page_token"):
        value = data.get(key) if data.get(key) not in (None, "") else page_info.get(key)
        if value not in (None, "", "0", 0, "-1", -1):
            return _cursor_param(value)
    if rows and isinstance(rows[-1], dict):
        value = rows[-1].get("cursor") or rows[-1].get("next_cursor")
        if value not in (None, "", "0", 0, "-1", -1):
            return _cursor_param(value)
    return None


def _explicit_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off"}:
            return False
        if normalized in {"true", "1", "yes", "on"}:
            return True
    return None
