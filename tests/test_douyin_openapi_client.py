from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

from src.dy_data.douyin_client import DouyinApiError, DouyinCredentials, DouyinOpenApiClient


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeHttp:
    def __init__(self, responses: list[FakeResponse | Exception]):
        self.responses = responses
        self.calls: list[dict] = []

    def _next_response(self):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url: str, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self._next_response()

    def get(self, url: str, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._next_response()


def client_with(http: FakeHttp) -> DouyinOpenApiClient:
    return DouyinOpenApiClient(
        DouyinCredentials(app_id="app-1", app_secret="secret-1", account_id="acct-1"),
        http=http,
    )


def test_client_token_request_uses_client_credentials():
    http = FakeHttp([FakeResponse({"data": {"access_token": "token-1"}})])
    client = client_with(http)

    assert client.get_client_token() == "token-1"
    assert http.calls[0]["json"] == {
        "client_key": "app-1",
        "client_secret": "secret-1",
        "grant_type": "client_credential",
    }


def test_order_query_sends_life_account_header_and_returns_raw_payload():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            FakeResponse({"data": {"orders": [{"order_id": "o1"}], "search_after": {"CursorValue": ["c1", "1"]}}}),
        ]
    )
    client = client_with(http)

    payload = client.query_orders(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        page_size=50,
    )

    assert payload["data"]["orders"] == [{"order_id": "o1"}]
    assert http.calls[1]["headers"]["Rpc-Transit-Life-Account"] == "acct-1"
    assert http.calls[1]["params"]["cursor"] == "0"
    assert "page_num" not in http.calls[1]["params"]


def test_iter_orders_uses_search_after_cursor_value():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            FakeResponse({"data": {"orders": [{"order_id": "o1"}], "search_after": {"CursorValue": ["c1", "1"]}}}),
            FakeResponse({"data": {"orders": [{"order_id": "o2"}], "search_after": {"CursorValue": ["c2", "2"]}}}),
            FakeResponse({"data": {"orders": []}}),
        ]
    )
    client = client_with(http)

    orders = list(
        client.iter_orders(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            page_size=1,
        )
    )

    assert orders == [{"order_id": "o1"}, {"order_id": "o2"}]
    assert http.calls[1]["params"]["cursor"] == "0"
    assert http.calls[2]["params"]["cursor"] == '["c1","1"]'
    assert http.calls[3]["params"]["cursor"] == '["c2","2"]'


def test_verify_and_shop_poi_queries_return_raw_payloads():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            FakeResponse({"data": {"verify_records": [{"verify_id": "v1"}]}}),
            FakeResponse({"data": {"pois": [{"poi_id": "p1"}]}}),
        ]
    )
    client = client_with(http)

    verify_payload = client.query_verify_records(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        poi_id="p1",
    )
    poi_payload = client.query_shop_pois(relation_type=0)

    assert verify_payload["data"]["verify_records"][0]["verify_id"] == "v1"
    assert poi_payload["data"]["pois"][0]["poi_id"] == "p1"
    assert http.calls[1]["params"]["size"] == 20
    assert http.calls[1]["params"]["cursor"] == "0"
    assert "start_time" in http.calls[1]["params"]
    assert "end_time" in http.calls[1]["params"]
    assert http.calls[1]["params"]["poi_ids"] == "p1"
    assert "verify_start_time" not in http.calls[1]["params"]
    assert "verify_end_time" not in http.calls[1]["params"]
    assert "poi_id" not in http.calls[1]["params"]
    assert "page_size" not in http.calls[1]["params"]


def test_clue_query_sends_expected_url_and_query_params():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            FakeResponse({"data": {"clue_data": [{"clue_id": "clue-1"}]}}),
        ]
    )
    client = client_with(http)

    payload = client.query_clues(
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 2, tzinfo=timezone.utc),
        page=3,
        page_size=80,
    )

    assert payload["data"]["clue_data"] == [{"clue_id": "clue-1"}]
    assert http.calls[1]["url"] == "https://open.douyin.com/goodlife/v1/open_api/crm/clue/query/"
    assert http.calls[1]["headers"]["Rpc-Transit-Life-Account"] == "acct-1"
    assert http.calls[1]["params"] == {
        "account_id": "acct-1",
        "page": 3,
        "page_size": 80,
        "start_time": int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()),
        "end_time": int(datetime(2026, 6, 2, tzinfo=timezone.utc).timestamp()),
    }


def test_certificate_query_uses_order_id_and_returns_raw_payload():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            FakeResponse(
                {
                    "data": {
                        "certificates": [
                            {
                                "certificate_id": "coupon-1",
                                "verify_records": [{"verify_id": "verify-1", "poi_id": "poi-1"}],
                            }
                        ]
                    }
                }
            ),
        ]
    )
    client = client_with(http)

    payload = client.query_certificates(order_id="order-1")

    assert payload["data"]["certificates"][0]["certificate_id"] == "coupon-1"
    assert http.calls[1]["params"]["account_id"] == "acct-1"
    assert http.calls[1]["params"]["order_id"] == "order-1"


def test_api_error_sanitizes_secret_values():
    http = FakeHttp([FakeResponse({"error_code": 400, "description": "bad secret-1"}, status_code=400)])
    client = client_with(http)

    with pytest.raises(DouyinApiError) as exc_info:
        client.get_client_token()

    assert "secret-1" not in str(exc_info.value)
    assert "[redacted]" in str(exc_info.value)


def test_api_error_detects_nested_data_error_code():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            FakeResponse({"data": {"error_code": 2119005, "description": "应用未获商家授权"}}),
        ]
    )
    client = client_with(http)

    with pytest.raises(DouyinApiError) as exc_info:
        client.query_orders(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    assert "应用未获商家授权" in str(exc_info.value)


def test_api_error_summary_does_not_include_raw_order_payload():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            FakeResponse(
                {
                    "data": {
                        "error_code": 5000001,
                        "description": "服务打瞌睡了，请稍后再试",
                        "orders": [{"order_id": "order-sensitive", "contacts": [{"phone": "phone-sensitive"}]}],
                    },
                    "extra": {"logid": "log-1"},
                }
            ),
        ]
    )
    client = DouyinOpenApiClient(
        DouyinCredentials(app_id="app-1", app_secret="secret-1", account_id="acct-1"),
        http=http,
        retry_attempts=1,
    )

    with pytest.raises(DouyinApiError) as exc_info:
        client.query_orders(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    message = str(exc_info.value)
    assert "服务打瞌睡了" in message
    assert "order-sensitive" not in message
    assert "phone-sensitive" not in message


def test_get_request_retries_transient_transport_error():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            requests.ConnectionError("read timed out"),
            FakeResponse({"data": {"orders": [{"order_id": "o1"}], "page": {"total": 1}}}),
        ]
    )
    client = DouyinOpenApiClient(
        DouyinCredentials(app_id="app-1", app_secret="secret-1", account_id="acct-1"),
        http=http,
        retry_sleep_seconds=0,
    )

    payload = client.query_orders(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert payload["data"]["orders"] == [{"order_id": "o1"}]
    assert [call["method"] for call in http.calls] == ["POST", "GET", "GET"]


def test_get_request_retries_transient_api_error():
    http = FakeHttp(
        [
            FakeResponse({"data": {"access_token": "token-1"}}),
            FakeResponse({"data": {"error_code": 5000001, "description": "服务打瞌睡了，请稍后再试"}}),
            FakeResponse({"data": {"orders": [{"order_id": "o1"}], "search_after": {"CursorValue": ["c1", "1"]}}}),
        ]
    )
    client = DouyinOpenApiClient(
        DouyinCredentials(app_id="app-1", app_secret="secret-1", account_id="acct-1"),
        http=http,
        retry_sleep_seconds=0,
    )

    payload = client.query_orders(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert payload["data"]["orders"] == [{"order_id": "o1"}]
    assert [call["method"] for call in http.calls] == ["POST", "GET", "GET"]
