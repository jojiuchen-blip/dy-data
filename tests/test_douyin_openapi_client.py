from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.dy_data.douyin_client import DouyinApiError, DouyinCredentials, DouyinOpenApiClient


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeHttp:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.responses.pop(0)

    def get(self, url: str, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.responses.pop(0)


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
            FakeResponse({"data": {"orders": [{"order_id": "o1"}], "cursor": "next"}}),
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


def test_api_error_sanitizes_secret_values():
    http = FakeHttp([FakeResponse({"error_code": 400, "description": "bad secret-1"}, status_code=400)])
    client = client_with(http)

    with pytest.raises(DouyinApiError) as exc_info:
        client.get_client_token()

    assert "secret-1" not in str(exc_info.value)
    assert "[redacted]" in str(exc_info.value)
