from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
ORDER_QUERY_URL = "https://open.douyin.com/goodlife/v1/trade/order/query/"
VERIFY_RECORD_QUERY_URL = "https://open.douyin.com/goodlife/v1/fulfilment/certificate/verify_record/query/"
REFUND_QUERY_URL = "https://open.douyin.com/goodlife/v1/akte/after_sale/order/query/"
SHOP_POI_QUERY_URL = "https://open.douyin.com/goodlife/v1/shop/poi/query/"
CRAFTSMAN_BIND_INFO_URL = "https://open.douyin.com/goodlife/v2/craftsman_openapi/merchat/craftsman/bind_info/all/"


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
    ) -> None:
        self.credentials = credentials
        self.http = http or requests.Session()
        self.timeout_seconds = timeout_seconds
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
        page_num = int(cursor or 1)
        params = {
            "account_id": self.credentials.account_id,
            "page_num": page_num,
            "page_size": page_size,
            "create_order_start_time": int(start.timestamp()),
            "create_order_end_time": int(end.timestamp()),
        }
        return self._get_json(ORDER_QUERY_URL, params)

    def iter_orders(self, start: datetime, end: datetime, *, page_size: int = 100):
        page = 1
        seen: set[str] = set()
        while True:
            payload = self.query_orders(start, end, page_size=page_size, cursor=page)
            data = payload.get("data", {})
            orders = data.get("orders") or data.get("list") or []
            for order in orders:
                order_id = str(order.get("order_id") or "").strip()
                if order_id and order_id in seen:
                    continue
                if order_id:
                    seen.add(order_id)
                yield order

            page_info = data.get("page") or {}
            total = _safe_int(page_info.get("total"))
            if total is not None and page * page_size >= total:
                break
            if len(orders) < page_size:
                break
            page += 1

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
            "page_size": page_size,
            "verify_start_time": int(start.timestamp()),
            "verify_end_time": int(end.timestamp()),
        }
        if cursor not in (None, ""):
            params["cursor"] = cursor
        if poi_id:
            params["poi_id"] = poi_id
        return self._get_json(VERIFY_RECORD_QUERY_URL, params)

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

    def _token_headers(self) -> dict[str, str]:
        token = self._token or self.get_client_token()
        return douyin_headers(token, self.credentials.account_id)

    def _post_json(self, url: str, payload: dict[str, Any], *, headers: dict[str, str]) -> dict[str, Any]:
        response = self.http.post(url, json=payload, headers=headers, timeout=self.timeout_seconds)
        return self._handle_response(response)

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.http.get(url, headers=self._token_headers(), params=params, timeout=self.timeout_seconds)
        return self._handle_response(response)

    def _handle_response(self, response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - external API response parsing boundary.
            raise DouyinApiError(self._sanitize(f"Douyin API returned non-JSON response: {response.text}")) from exc

        if getattr(response, "status_code", 200) >= 400 or _has_api_error(payload):
            raise DouyinApiError(self._sanitize(f"Douyin API error: {payload}"))
        return payload

    def _sanitize(self, message: str) -> str:
        sanitized = message
        for secret in (self.credentials.app_secret, self._token):
            if secret:
                sanitized = sanitized.replace(secret, "[redacted]")
        return sanitized[:1800]


def _has_api_error(payload: dict[str, Any]) -> bool:
    code = payload.get("error_code", payload.get("err_no", payload.get("code")))
    return code not in (None, 0, "0")


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
