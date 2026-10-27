"""Synthetic completeness, identity, and retry-budget evidence for DYDATA-104."""

import copy
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from sqlalchemy import select

from apps.api.dy_api.models import DataQualityIssue, DimSkuProductRule, JobRun
from apps.worker.product_sync import DouyinProductSyncAdapter, execute_product_sync
from src.dy_data.douyin_client import DouyinApiError, DouyinCredentials, DouyinOpenApiClient
from test_douyin_openapi_client import FakeHttp, FakeResponse
from test_worker_product_sync import SkuCoverageClient, _platform_product, _queue


def run_sync(session, client, known):
    _queue(session)
    return execute_product_sync(
        session, job_id="product-sync-1",
        adapter=DouyinProductSyncAdapter(client, known_products=known),
    )


def test_partial_sku_lookup_retries_only_missing_ids_and_tracks_budget(db_session, caplog):
    source = _platform_product("synthetic-product", [])
    client = SkuCoverageClient({}, {"synthetic-product": source})
    client.retry_attempts = 3

    def partial(product_id, sku_ids):
        client.sku_calls.append((product_id, list(sku_ids)))
        return {"data": {"skus": [{"sku_id": sku_ids[0], "status": 1}]}}

    client.query_product_skus = partial
    result = run_sync(db_session, client, {"synthetic-product": {"sku-a", "sku-b", "sku-c"}})
    assert result.status == "SUCCESS"
    assert client.sku_calls == [
        ("synthetic-product", ["sku-a", "sku-b", "sku-c"]),
        ("synthetic-product", ["sku-b", "sku-c"]),
        ("synthetic-product", ["sku-c"]),
    ]
    assert {row.sku_id for row in db_session.scalars(select(DimSkuProductRule))} == {"sku-a", "sku-b", "sku-c"}
    stats = db_session.get(JobRun, "product-sync-1").metadata_json["lookup_stats"]
    assert stats == {"attempt_limit_per_batch": 3, "product_id_requests": 1,
                     "sku_requests": 3, "partial_responses": 2,
                     "business_attempt_limit_per_query": 3,
                     "transport_attempt_limit_per_business_attempt": 3,
                     "product_http_attempt_upper_bound_per_query": 9}
    assert "missing_count=2" in caplog.text


def test_partial_product_lookup_accumulates_returned_products_without_refetch(db_session):
    products = {f"product-{index}": _platform_product(f"product-{index}", [f"sku-{index}"]) for index in range(3)}
    client = SkuCoverageClient({}, products)

    def partial(product_ids):
        client.id_calls.append(list(product_ids))
        return {"data": {"product_onlines": [products[product_ids[0]]]}}

    client.query_online_products_by_id = partial
    result = run_sync(db_session, client, {f"product-{index}": {f"sku-{index}"} for index in range(3)})
    assert result.status == "SUCCESS"
    assert client.id_calls == [["product-0", "product-1", "product-2"], ["product-1", "product-2"], ["product-2"]]
    assert result.inserted_count == 3


@pytest.mark.parametrize("missing_kind", ["product", "sku"])
def test_exhausted_partial_reply_alerts_without_overwriting_good_catalog(db_session, missing_kind):
    source = _platform_product("product-known", ["sku-a"])
    client = SkuCoverageClient({(1, None): {"products": [source], "has_more": False}},
                               {"product-known": source} if missing_kind == "sku" else {})

    def partial(product_id, sku_ids):
        client.sku_calls.append((product_id, list(sku_ids)))
        return {"data": {"skus": []}}

    client.query_product_skus = partial
    db_session.add(DimSkuProductRule(sku_id="sku-a", product_id="product-known", sku_name="Trusted",
                                    sync_status="SUCCESS", product_status_normalized="ACTIVE", is_active_product=True))
    result = run_sync(db_session, client, {"product-known": {"sku-a", "sku-b"}})
    db_session.commit()
    db_session.expire_all()
    assert (result.status, result.error_code, result.inserted_count, result.updated_count) == ("FAILED", "INCOMPLETE_RESPONSE", 0, 0)
    rows = list(db_session.scalars(select(DimSkuProductRule)))
    assert [(row.sku_id, row.sku_name, row.sync_status) for row in rows] == [("sku-a", "Trusted", "SUCCESS")]
    job = db_session.get(JobRun, "product-sync-1")
    assert job.metadata_json["retryable"] is True
    assert job.metadata_json["lookup_stats"]["partial_responses"] == 3
    assert job.metadata_json["lookup_stats"]["sku_requests" if missing_kind == "sku" else "product_id_requests"] == 3
    issues = list(db_session.scalars(select(DataQualityIssue)))
    assert len(issues) == 1 and issues[0].issue_type == "product_sync_incomplete_response"


def test_catalog_above_baseline_with_long_ids_all_pages_and_inactive_unlisted_skus(db_session):
    product_id = "900719925474099312345678901234567890"
    sku_ids = [str(900719925474099312345678901234567891 + index) for index in range(125)]
    pages = {}
    for index in range(3):
        current_cursor = None if index == 0 else f"page-{index}"
        pages[(1, current_cursor)] = {
            "products": [_platform_product(product_id, sku_ids[index * 50:(index + 1) * 50])],
            "has_more": index < 2, "next_cursor": f"page-{index + 1}",
        }
    offline = _platform_product("offline-unlisted-product", ["offline-unlisted-sku"])
    offline["online_status"] = 2
    pages[(2, None)] = {"products": [offline], "has_more": False}
    client = SkuCoverageClient(pages, {})
    result = run_sync(db_session, client, {product_id: set(sku_ids)})
    assert result.status == "SUCCESS" and result.inserted_count == 126
    rows = {row.sku_id: row for row in db_session.scalars(select(DimSkuProductRule))}
    assert set(rows) == set(sku_ids) | {"offline-unlisted-sku"}
    assert rows[sku_ids[-1]].product_id == product_id
    assert rows["offline-unlisted-sku"].product_status_normalized == "INACTIVE"
    assert rows["offline-unlisted-sku"].is_active_product is False
    assert rows["offline-unlisted-sku"].product_type == ""
    assert client.id_calls == [] and client.sku_calls == []
    assert client.list_calls == [(1, None), (1, "page-1"), (1, "page-2"), (2, None), (3, None)]


@pytest.mark.parametrize("conflict", ["inline-duplicate", "known-product", "inline-product", "inline-owner", "detail-owner", "missing-id"])
def test_conflicting_or_malformed_sku_never_overwrites_snapshot(db_session, conflict):
    source = _platform_product("product-known", ["sku-a"])
    detail = copy.deepcopy(source)
    if conflict == "inline-duplicate":
        source["skus"].append({"sku_id": "sku-a", "sku_name": "conflicting"})
    elif conflict == "known-product":
        source["product"]["product_id"] = "wrong-product"
    elif conflict == "inline-product":
        source["skus"][0]["product_id"] = "wrong-product"
    elif conflict == "inline-owner":
        source["skus"][0]["owner_account_id"] = "wrong-owner"
    elif conflict == "detail-owner":
        detail["product"]["owner_account_id"] = "different-owner"
        detail["skus"].append({"sku_id": "sku-b"})
    else:
        source["skus"].append({"sku_name": "no exact ID"})
    client = SkuCoverageClient({(1, None): {"products": [source], "has_more": False}}, {"product-known": detail})
    db_session.add(DimSkuProductRule(sku_id="sku-a", product_id="product-known", sku_name="Trusted", sync_status="SUCCESS"))
    result = run_sync(db_session, client, {"product-known": {"sku-a", "sku-b"}})
    assert result.status == "FAILED" and result.error_code == "INVALID_RESPONSE"
    assert list(db_session.scalars(select(DimSkuProductRule.sku_name))) == ["Trusted"]
    assert len(client.id_calls) <= 1


def test_transport_error_does_not_restart_partial_lookup_budget(db_session):
    client = SkuCoverageClient({}, {"product-known": _platform_product("product-known", [])})

    def failing(product_id, sku_ids):
        client.sku_calls.append((product_id, list(sku_ids)))
        raise RuntimeError("synthetic transport retry budget exhausted")

    client.query_product_skus = failing
    result = run_sync(db_session, client, {"product-known": {"sku-a"}})
    assert result.status == "FAILED" and result.error_code == "UPSTREAM_ERROR"
    assert client.sku_calls == [("product-known", ["sku-a"])]
    assert db_session.get(JobRun, "product-sync-1").metadata_json["lookup_stats"]["sku_requests"] == 1


def test_real_transport_retry_limit_is_not_restarted_after_partial_response():
    http = FakeHttp([
        FakeResponse({"data": {"access_token": "synthetic-token"}}),
        FakeResponse({"data": {"skus": [{"sku_id": "sku-a", "status": 1}]}}),
        requests.ConnectionError("synthetic timeout"), requests.ConnectionError("synthetic timeout"),
        requests.ConnectionError("synthetic timeout"),
    ])
    client = DouyinOpenApiClient(DouyinCredentials("synthetic-app", "synthetic-secret", "synthetic-account"),
                                http=http, retry_sleep_seconds=0, sleep=lambda seconds: None)
    adapter = DouyinProductSyncAdapter(client)
    with pytest.raises(DouyinApiError, match="transport error"):
        adapter._fetch_sku_batch("synthetic-product", {"owner_account_id": "synthetic-owner"}, ["sku-a", "sku-b"])
    # One successful partial + the existing three transport attempts. There
    # is no third logical lookup after the second one's transport exhaustion.
    assert len(http.calls) == 5  # Includes the one token request.
    assert adapter.lookup_stats["sku_requests"] == 2
    assert adapter.lookup_stats["partial_responses"] == 1


def test_conflicting_partial_product_response_fails_before_retrying_missing_product(db_session):
    client = SkuCoverageClient({}, {})
    corrupt = _platform_product("product-a", ["sku-b"])

    def partial(product_ids):
        client.id_calls.append(list(product_ids))
        return {"data": {"product_onlines": [corrupt]}}

    client.query_online_products_by_id = partial
    result = run_sync(db_session, client, {"product-a": {"sku-a"}, "product-b": {"sku-b"}})
    assert result.status == "FAILED" and result.error_code == "INVALID_RESPONSE"
    assert client.id_calls == [["product-a", "product-b"]]


def test_unknown_product_without_sku_has_explicit_warning_and_no_fabricated_variant(db_session):
    client = SkuCoverageClient({(1, None): {"products": [_platform_product("unlisted-product", [])], "has_more": False}}, {})
    result = run_sync(db_session, client, {})
    assert result.status == "SUCCESS" and result.skipped_count == 1
    assert list(db_session.scalars(select(DimSkuProductRule))) == []
    assert client.id_calls == [] and client.sku_calls == []
    issues = list(db_session.scalars(select(DataQualityIssue)))
    assert len(issues) == 1 and issues[0].issue_type == "product_sync_missing_sku_identity"


def test_nonconsecutive_cursor_loop_fails_before_requery(db_session):
    pages = {(1, cursor): {"products": [], "has_more": True, "next_cursor": following}
             for cursor, following in [(None, "cursor-a"), ("cursor-a", "cursor-b"), ("cursor-b", "cursor-a")]}
    client = SkuCoverageClient(pages, {})
    result = run_sync(db_session, client, {})
    assert result.status == "FAILED" and result.error_code == "INVALID_RESPONSE"
    assert client.list_calls == [(1, None), (1, "cursor-a"), (1, "cursor-b")]


def test_batch_query_encoding_retains_long_and_reserved_ids_as_single_json_array():
    http = FakeHttp([FakeResponse({"data": {"access_token": "synthetic-token"}}),
                     FakeResponse({"data": {"product_onlines": []}}), FakeResponse({"data": {"skus": []}})])
    client = DouyinOpenApiClient(DouyinCredentials("synthetic-app", "synthetic-secret", "synthetic-account"), http=http)
    product_ids = ["90071992547409931234567890", "synthetic&+?产品"]
    sku_ids = ["90071992547409931234567891", "synthetic&+?规格"]
    client.query_online_products_by_id(product_ids)
    client.query_product_skus(product_ids[0], sku_ids)
    for call, field, expected in zip(http.calls[1:], ["product_ids", "sku_ids"], [product_ids, sku_ids]):
        prepared = requests.Request("GET", call["url"], params=call["params"]).prepare()
        query = parse_qs(urlsplit(prepared.url).query)
        assert len(query[field]) == 1 and json.loads(query[field][0]) == expected
