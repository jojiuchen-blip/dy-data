"""Persist bounded evidence without changing product completeness or retries."""

import json

import pytest
from sqlalchemy import delete, select

from apps.api.dy_api.models import (
    DataQualityIssue,
    DimSkuProductRule,
    JobEvent,
    JobRun,
    SkuProductSyncHistory,
)
from apps.worker.product_sync import (
    DouyinProductSyncAdapter,
    ProductSyncPayloadError,
    execute_product_sync,
    sanitize_product_lookup_diagnostics,
)
from test_data_settlement_incremental_postgres import POSTGRES_URL, postgres_stack  # noqa: F401
from test_worker_product_sync import SkuCoverageClient, _platform_product, _queue


@pytest.fixture(params=("sqlite", "postgres"))
def diagnostic_session(request, db_session):
    if request.param == "sqlite":
        yield db_session
        return
    if not POSTGRES_URL:
        pytest.skip("dedicated local PostgreSQL test URL is not configured")
    _engine, factory = request.getfixturevalue("postgres_stack")
    with factory() as session:
        for model in (DataQualityIssue, SkuProductSyncHistory, DimSkuProductRule, JobEvent, JobRun):
            session.execute(delete(model))
        session.commit()
        yield session


def _prepare(session, count=23):
    known = {f"product-{index:02}": {f"sku-{index:02}"} for index in range(count)}
    for index in range(count):
        session.add(DimSkuProductRule(
            sku_id=f"sku-{index:02}", product_id=f"product-{index:02}",
            sku_name="Trusted", sync_status="SUCCESS", sync_run_id="prior-good-run",
        ))
    _queue(session)
    return known


def _execute(session, client, known):
    result = execute_product_sync(
        session, job_id="product-sync-1",
        adapter=DouyinProductSyncAdapter(client, known_products=known),
    )
    session.commit()
    session.expire_all()
    return result, session.get(JobRun, "product-sync-1")


def _assert_failure_preserves_catalog(session, expected_count):
    rows = list(session.scalars(select(DimSkuProductRule)))
    assert len(rows) == expected_count
    assert all((row.sku_name, row.sync_status, row.sync_run_id) == (
        "Trusted", "SUCCESS", "prior-good-run"
    ) for row in rows)
    assert list(session.scalars(select(SkuProductSyncHistory))) == []


def test_first_failed_product_batch_persists_exact_ids_and_global_remaining_count(diagnostic_session):
    session = diagnostic_session
    known = _prepare(session)
    client = SkuCoverageClient({}, {})
    result, job = _execute(session, client, known)
    assert (result.status, result.error_code) == ("FAILED", "INCOMPLETE_RESPONSE")
    diagnostic = job.metadata_json["lookup_diagnostics"]
    first_batch = sorted(known)[:10]
    assert diagnostic["batchProductIds"] == diagnostic["pendingProductIds"] == first_batch
    assert diagnostic["frozenProductCount"] == diagnostic["remainingProductLookupCount"] == 23
    assert diagnostic["batchOffset"] == 0
    assert diagnostic["batchMissingCount"] == 10
    assert diagnostic["unvisitedProductCount"] == 13
    assert [item["requestedProductIds"] for item in diagnostic["attempts"]] == [first_batch] * 3
    assert all(item["responseReceived"] and item["returnedProductCount"] == 0 for item in diagnostic["attempts"])
    assert client.id_calls == [first_batch] * 3 and client.sku_calls == []
    issue = session.scalar(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "product_sync_incomplete_response",
    ))
    assert issue.raw_context_json["lookup_diagnostics"] == diagnostic
    _assert_failure_preserves_catalog(session, 23)


@pytest.mark.parametrize("offset", (0, 10))
def test_partial_and_later_batch_failures_keep_exact_attempt_scope(diagnostic_session, offset):
    session = diagnostic_session
    known = _prepare(session)
    client = SkuCoverageClient({}, {})

    def reply(product_ids):
        client.id_calls.append(list(product_ids))
        if offset and len(client.id_calls) == 1:
            rows = [_platform_product(product_id, list(known[product_id])) for product_id in product_ids]
        elif not offset and len(client.id_calls) == 1:
            rows = [_platform_product(product_ids[0], list(known[product_ids[0]]))]
        else:
            rows = []
        return {"data": {"product_onlines": rows, "error_code": 0}, "access_token": "DO-NOT-SAVE"}

    client.query_online_products_by_id = reply
    result, job = _execute(session, client, known)
    diagnostic = job.metadata_json["lookup_diagnostics"]
    batch = sorted(known)[offset:offset + 10]
    missing = batch if offset else batch[1:]
    assert result.error_code == "INCOMPLETE_RESPONSE"
    assert diagnostic["batchOffset"] == offset
    assert diagnostic["batchProductIds"] == batch
    assert diagnostic["pendingProductIds"] == missing
    assert diagnostic["batchMissingCount"] == len(missing)
    assert diagnostic["unvisitedProductCount"] == 23 - offset - 10
    assert diagnostic["remainingProductLookupCount"] == len(missing) + 23 - offset - 10
    assert len(diagnostic["attempts"]) == 3
    assert diagnostic["attempts"][0]["requestedProductIds"] == batch
    if not offset:
        assert diagnostic["attempts"][0]["products"] == [{"productId": batch[0], "skuCount": 1}]
    assert diagnostic["attempts"][1]["requestedProductIds"] == missing
    assert "DO-NOT-SAVE" not in json.dumps(job.metadata_json)
    assert len(client.id_calls) == (4 if offset else 3)
    _assert_failure_preserves_catalog(session, 23)


@pytest.mark.parametrize("failure", ("business-code", "invalid-code", "malformed", "unexpected-id", "transport"))
def test_failed_product_response_summary_is_safe_and_does_not_restart_retries(diagnostic_session, failure):
    session = diagnostic_session
    known = _prepare(session, count=1)
    client = SkuCoverageClient({}, {})

    def fail(product_ids):
        client.id_calls.append(list(product_ids))
        if failure == "transport":
            raise RuntimeError("synthetic upstream transport error")
        payload = {"data": {"product_onlines": []}, "access_token": "DO-NOT-SAVE"}
        if failure == "business-code":
            payload["data"]["error_code"] = 2190004
        elif failure == "invalid-code":
            payload["data"]["error_code"] = "--1"
        elif failure == "malformed":
            payload["data"]["product_onlines"] = {"secret": "DO-NOT-SAVE"}
        else:
            payload["data"]["product_onlines"] = [_platform_product("DO-NOT-SAVE", [])]
        return payload

    client.query_online_products_by_id = fail
    result, job = _execute(session, client, known)
    assert result.error_code == ("UPSTREAM_ERROR" if failure == "transport" else "INVALID_RESPONSE")
    diagnostic = job.metadata_json["lookup_diagnostics"]
    assert diagnostic["batchProductIds"] == diagnostic["pendingProductIds"] == ["product-00"]
    assert len(diagnostic["attempts"]) == len(client.id_calls) == 1
    attempt = diagnostic["attempts"][0]
    assert attempt["responseReceived"] is (failure != "transport")
    if failure == "business-code":
        assert attempt["errorCodes"] == {"data": 2190004}
    assert "DO-NOT-SAVE" not in json.dumps(diagnostic)
    issues = list(session.scalars(select(DataQualityIssue)))
    assert len(issues) == 1
    assert issues[0].raw_context_json["lookup_diagnostics"] == diagnostic
    _assert_failure_preserves_catalog(session, 1)


def test_unknown_empty_envelopes_remain_pending_with_zero_sku_evidence(diagnostic_session):
    session = diagnostic_session
    _queue(session)
    empty = _platform_product("unknown-product", [])
    client = SkuCoverageClient(
        {(1, None): {"products": [empty], "has_more": False}},
        {"unknown-product": empty},
    )
    result, job = _execute(session, client, {})
    diagnostic = job.metadata_json["lookup_diagnostics"]
    assert result.error_code == "INCOMPLETE_RESPONSE"
    assert diagnostic["batchMissingCount"] == diagnostic["remainingProductLookupCount"] == 1
    assert all(item["products"] == [{"productId": "unknown-product", "skuCount": 0}]
               for item in diagnostic["attempts"])


def test_successful_product_retry_does_not_leave_failure_diagnostics(diagnostic_session):
    session = diagnostic_session
    known = _prepare(session, count=1)
    client = SkuCoverageClient({}, {})

    def recover(product_ids):
        client.id_calls.append(list(product_ids))
        rows = [] if len(client.id_calls) == 1 else [_platform_product("product-00", ["sku-00"])]
        return {"data": {"product_onlines": rows}}

    client.query_online_products_by_id = recover
    result, job = _execute(session, client, known)
    assert result.status == "SUCCESS" and len(client.id_calls) == 2
    assert job.metadata_json.get("lookup_diagnostics") is None
    assert len(list(session.scalars(select(SkuProductSyncHistory)))) == 1


def test_diagnostic_projection_bounds_every_collection_and_rejects_unlisted_fields():
    product_ids = [f"product-{index}" for index in range(20)]
    diagnostic = sanitize_product_lookup_diagnostics({
        "version": 1, "kind": "product_id", "batchProductIds": product_ids,
        "pendingProductIds": product_ids + ["not-requested"], "access_token": "DO-NOT-SAVE",
        "attempts": [{
            "attempt": index + 1, "requestedProductIds": product_ids,
            "products": [{"productId": item, "skuCount": 1, "secret": "DO-NOT-SAVE"}
                         for item in product_ids],
            "errorCodes": {"response": 0, "data": "DO-NOT-SAVE", "extra": True, "secret": 1},
            "raw_payload": "DO-NOT-SAVE",
        } for index in range(10)],
    })
    assert len(diagnostic["batchProductIds"]) == len(diagnostic["pendingProductIds"]) == 10
    assert len(diagnostic["attempts"]) == 3
    assert all(len(item["requestedProductIds"]) == len(item["products"]) == 10
               for item in diagnostic["attempts"])
    assert all(item["errorCodes"] == {"response": 0} for item in diagnostic["attempts"])
    assert "DO-NOT-SAVE" not in json.dumps(diagnostic)


def test_reused_adapter_cannot_attribute_old_failed_batch_to_a_new_list_failure(diagnostic_session):
    session = diagnostic_session
    known = _prepare(session, count=1)
    client = SkuCoverageClient({}, {})
    adapter = DouyinProductSyncAdapter(client, known_products=known)
    execute_product_sync(session, job_id="product-sync-1", adapter=adapter)
    session.commit()
    assert session.get(JobRun, "product-sync-1").metadata_json["lookup_diagnostics"]
    _queue(session, job_id="product-sync-2")

    def invalid_list(**_kwargs):
        raise ProductSyncPayloadError("synthetic invalid list page")

    client.query_online_products = invalid_list
    result = execute_product_sync(session, job_id="product-sync-2", adapter=adapter)
    session.commit()
    session.expire_all()
    assert result.error_code == "INVALID_RESPONSE"
    assert session.get(JobRun, "product-sync-2").metadata_json.get("lookup_diagnostics") is None
    assert session.get(JobRun, "product-sync-1").metadata_json["lookup_diagnostics"]
