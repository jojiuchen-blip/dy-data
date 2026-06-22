from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import time
from typing import Any

import requests


TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
ORDER_QUERY_URL = "https://open.douyin.com/goodlife/v1/trade/order/query/"
VERIFY_RECORD_QUERY_URL = "https://open.douyin.com/goodlife/v1/fulfilment/certificate/verify_record/query/"
CERTIFICATE_QUERY_URL = "https://open.douyin.com/goodlife/v1/fulfilment/certificate/query/"
REFUND_QUERY_URL = "https://open.douyin.com/goodlife/v1/akte/after_sale/order/query/"
SHOP_POI_QUERY_URL = "https://open.douyin.com/goodlife/v1/shop/poi/query/"
CRAFTSMAN_BIND_INFO_URL = "https://open.douyin.com/goodlife/v2/craftsman_openapi/merchat/craftsman/bind_info/all/"
CLUE_QUERY_URL = "https://open.douyin.com/goodlife/v1/open_api/crm/clue/query/"
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


class DouyinApiError(RuntimeError):
    pass


class DouyinOpenApiClient:
    def __init__(
        self,
        credentials: DouyinCredentials,
        *,
        http: Any | None = None,
        timeout_seconds: int = 30,
        retry_attempts: int = 3,
        retry_sleep_seconds: float = 1.0,
    ) -> None:
        self.credentials = credentials
        self.http = http or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_sleep_seconds = retry_sleep_seconds
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
                time.sleep(self.retry_sleep_seconds * attempt)
        raise last_error or DouyinApiError("Douyin API request failed.")

    def _request_with_retries(self, method: str, url: str, **kwargs: Any) -> Any:
        attempts = max(1, self.retry_attempts)
        last_error: requests.RequestException | None = None
        for attempt in range(1, attempts + 1):
            try:
                request = getattr(self.http, method)
                return request(url, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                time.sleep(self.retry_sleep_seconds * attempt)
        raise DouyinApiError(self._sanitize(f"Douyin API transport error: {last_error}")) from last_error

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
    return "5000001" in message or "2100004" in message or "系统繁忙" in message


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
