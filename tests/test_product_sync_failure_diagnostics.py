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
    product_sync_latest_success_at,
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


def _assert_failure_preserves_catalog(session, expected_count, *, expected_history=0):
    rows = list(session.scalars(select(DimSkuProductRule)))
    assert len(rows) == expected_count
    assert all((row.sku_name, row.sync_status, row.sync_run_id) == (
        "Trusted", "SUCCESS", "prior-good-run"
    ) for row in rows)
    assert len(list(session.scalars(select(SkuProductSyncHistory)))) == expected_history


def test_failed_product_batches_all_persist_exact_ids_and_final_scan_counts(diagnostic_session):
    session = diagnostic_session
    known = _prepare(session)
    client = SkuCoverageClient({}, {})
    result, job = _execute(session, client, known)
    assert (result.status, result.error_code) == ("FAILED", "INCOMPLETE_RESPONSE")
    issues = list(session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "product_sync_incomplete_response",
    )))
    assert len(issues) == 3
    diagnostics = sorted((issue.raw_context_json["lookup_diagnostics"] for issue in issues),
                         key=lambda item: item["batchOffset"])
    expected_calls = []
    for diagnostic, offset in zip(diagnostics, (0, 10, 20)):
        batch = sorted(known)[offset:offset + 10]
        assert diagnostic["batchProductIds"] == diagnostic["pendingProductIds"] == batch
        assert diagnostic["frozenProductCount"] == 23
        assert diagnostic["remainingProductLookupCount"] == 23 - offset
        assert diagnostic["batchOffset"] == offset
        assert diagnostic["batchMissingCount"] == len(batch)
        assert diagnostic["unvisitedProductCount"] == max(0, 23 - offset - 10)
        assert [item["requestedProductIds"] for item in diagnostic["attempts"]] == [batch] * 3
        assert all(item["responseReceived"] and item["returnedProductCount"] == 0 for item in diagnostic["attempts"])
        expected_calls.extend([batch] * 3)
    assert client.id_calls == expected_calls and client.sku_calls == []
    final_diagnostic = job.metadata_json["lookup_diagnostics"]
    assert final_diagnostic == {
        **diagnostics[-1], "unvisitedProductCount": 0, "remainingProductLookupCount": 23,
    }
    assert job.metadata_json["lookup_scan"] == {
        "frozenProductCount": 23, "visitedProductCount": 23, "unvisitedProductCount": 0,
        "unresolvedProductCount": 23, "incompleteBatchCount": 3,
        "enumerationCompleted": True, "coverageComplete": False,
    }
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
    diagnostics = [issue.raw_context_json["lookup_diagnostics"] for issue in session.scalars(
        select(DataQualityIssue).where(DataQualityIssue.issue_type == "product_sync_incomplete_response")
    )]
    diagnostic = next(item for item in diagnostics if item["batchOffset"] == offset)
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
        assert diagnostic["attempts"][0]["products"] == [
            {"productId": batch[0], "skuCount": 1, "productStatus": "ACTIVE"}
        ]
    assert diagnostic["attempts"][1]["requestedProductIds"] == missing
    assert "DO-NOT-SAVE" not in json.dumps(job.metadata_json)
    assert len(client.id_calls) == (7 if offset else 9)
    assert job.metadata_json["lookup_scan"]["visitedProductCount"] == 23
    assert job.metadata_json["lookup_scan"]["unvisitedProductCount"] == 0
    assert job.metadata_json["lookup_scan"]["unresolvedProductCount"] == (13 if offset else 22)
    assert job.metadata_json["lookup_diagnostics"]["remainingProductLookupCount"] == (13 if offset else 22)
    _assert_failure_preserves_catalog(session, 23, expected_history=10 if offset else 1)


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
    assert all(item["products"] == [{"productId": "unknown-product", "skuCount": 0, "productStatus": "ACTIVE"}]
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
            "products": [{"productId": item, "skuCount": 1, "secret": "DO-NOT-SAVE",
                          "productStatus": ["DO-NOT-SAVE"]}
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
    assert all(row["productStatus"] == "UNKNOWN" for item in diagnostic["attempts"] for row in item["products"])
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
    assert session.get(JobRun, "product-sync-2").metadata_json.get("lookup_scan") is None
    assert session.get(JobRun, "product-sync-1").metadata_json["lookup_diagnostics"]


def test_inactive_unknown_skus_do_not_starve_later_products_or_refresh_current_catalog(diagnostic_session):
    session = diagnostic_session
    product_ids = [f"product-{index:02}" for index in range(23)]
    known = _prepare(session)
    missing_ids = product_ids[:10]
    for product_id in missing_ids:
        session.execute(delete(DimSkuProductRule).where(
            DimSkuProductRule.product_id == product_id,
        ))
        del known[product_id]
    empty = [_platform_product(product_id, []) for product_id in missing_ids]
    for record in empty:
        record["online_status"] = 2
    detail = {record["product"]["product_id"]: record for record in empty}
    detail.update({product_id: _platform_product(product_id, list(sku_ids))
                   for product_id, sku_ids in known.items()})
    client = SkuCoverageClient({(2, None): {"products": empty, "has_more": False}}, detail)
    result, job = _execute(session, client, known)
    assert (result.status, result.error_code, result.failed_count) == ("FAILED", "INCOMPLETE_RESPONSE", 10)
    assert client.id_calls == [missing_ids] * 3 + [product_ids[10:20], product_ids[20:]]
    assert client.sku_calls == []
    _assert_failure_preserves_catalog(session, 13, expected_history=13)
    assert product_sync_latest_success_at(session, job.job_id) is None
    assert job.metadata_json["lookup_scan"] == {
        "frozenProductCount": 23, "visitedProductCount": 23, "unvisitedProductCount": 0,
        "unresolvedProductCount": 10, "incompleteBatchCount": 1,
        "enumerationCompleted": True, "coverageComplete": False,
    }
    diagnostic = job.metadata_json["lookup_diagnostics"]
    assert diagnostic["pendingProductIds"] == missing_ids
    assert all(product["skuCount"] == 0 and product["productStatus"] == "INACTIVE"
               for attempt in diagnostic["attempts"] for product in attempt["products"])


def test_fatal_later_batch_preserves_verified_history_and_does_not_restart_retry_budgets(diagnostic_session):
    session = diagnostic_session
    known = _prepare(session)
    product_ids = sorted(known)
    client = SkuCoverageClient({}, {})

    def reply(requested):
        client.id_calls.append(list(requested))
        if len(client.id_calls) == 1:
            rows = [_platform_product(product_id, list(known[product_id])) for product_id in requested]
        elif len(client.id_calls) == 2:
            rows = [_platform_product(requested[0], list(known[requested[0]]))]
        elif len(client.id_calls) < 5:
            rows = []
        else:
            raise RuntimeError("synthetic transport exhausted")
        return {"data": {"product_onlines": rows}}

    client.query_online_products_by_id = reply
    result, job = _execute(session, client, known)
    assert (result.status, result.error_code) == ("FAILED", "UPSTREAM_ERROR")
    assert client.id_calls == [product_ids[:10], product_ids[10:20], product_ids[11:20],
                               product_ids[11:20], product_ids[20:]]
    _assert_failure_preserves_catalog(session, 23, expected_history=11)
    assert product_sync_latest_success_at(session, job.job_id) is None
    assert job.metadata_json["lookup_scan"]["visitedProductCount"] == 20
    assert job.metadata_json["lookup_scan"]["unvisitedProductCount"] == 3
    assert job.metadata_json["lookup_scan"]["unresolvedProductCount"] == 9
    assert job.metadata_json["lookup_diagnostics"]["attempts"][0]["responseReceived"] is False
    assert job.metadata_json["lookup_diagnostics"]["unvisitedProductCount"] == 3
    assert job.metadata_json["lookup_diagnostics"]["remainingProductLookupCount"] == 12


def test_exhausted_sku_retry_retains_exact_partial_sku_proof_in_history(diagnostic_session):
    session = diagnostic_session
    known = _prepare(session, count=1)
    known["product-00"].add("missing-sku")
    client = SkuCoverageClient({}, {"product-00": _platform_product("product-00", [])})

    def partial(product_id, sku_ids):
        client.sku_calls.append((product_id, list(sku_ids)))
        rows = [{"sku_id": "sku-00", "sku_name": "Verified source", "status": 1}] if len(client.sku_calls) == 1 else []
        return {"data": {"skus": rows}}

    client.query_product_skus = partial
    result, job = _execute(session, client, known)
    assert (result.status, result.error_code) == ("FAILED", "INCOMPLETE_RESPONSE")
    assert client.sku_calls == [("product-00", ["missing-sku", "sku-00"]),
                                ("product-00", ["missing-sku"]), ("product-00", ["missing-sku"])]
    _assert_failure_preserves_catalog(session, 1, expected_history=1)
    history = session.scalar(select(SkuProductSyncHistory))
    assert (history.sku_id, history.sku_name, history.product_id) == ("sku-00", "Verified source", "product-00")
    assert product_sync_latest_success_at(session, job.job_id) is None
