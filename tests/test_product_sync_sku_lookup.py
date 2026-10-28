"""Known-only product SKU completion using synthetic upstream responses."""
import copy
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import DimSkuProductRule
from apps.worker.product_sync import DouyinProductSyncAdapter, ProductSyncPayloadError, execute_product_sync, extract_known_order_products
from test_worker_product_sync import _queue


def record(*, present=(), status=1):
    return {"online_status": status, "product": {"product_id": "product-known", "owner_account_id": "owner-known",
        "creator_account_id": "creator-known", "account_name": "Synthetic merchant", "product_name": "Synthetic product"},
        "skus": [{"sku_id": sku_id, "sku_name": sku_id} for sku_id in present]}


class Client:
    def __init__(self, reply=None, rows=None):
        self.calls = []
        self.id_calls = []
        self.reply = reply
        self.rows = rows if rows is not None else [record()]
    def query_online_products(self, **kwargs):
        return {"data": {"products": self.rows if kwargs["status"] == 1 else [], "has_more": False, "next_cursor": ""}}
    def query_online_products_by_id(self, product_ids):
        self.id_calls.append(list(product_ids))
        return {"data": {"product_onlines": [row for row in self.rows if row["product"]["product_id"] in product_ids]}}
    def query_product_skus(self, product_id, sku_ids):
        self.calls.append((product_id, list(sku_ids)))
        if isinstance(self.reply, Exception):
            raise self.reply
        if self.reply is not None:
            return copy.deepcopy(self.reply)
        return {"data": {"error_code": 0, "skus": [{"sku_id": sku_id, "sku_name": sku_id, "status": 1} for sku_id in sku_ids]}}


def adapter(client, ids=None):
    return DouyinProductSyncAdapter(client, known_products={"product-known": set(ids or ["sku-a", "sku-b"])})


def consume_pages(sync):
    cursor, items = None, []
    while True:
        page = sync.fetch_page(mode="FULL", cursor=cursor)
        items.extend(page.items)
        if not page.has_more:
            return items
        cursor = page.next_cursor


def test_empty_online_skus_are_filled_once_after_list_scan_and_id_fallback():
    client = Client(); sync = adapter(client)
    first_page = sync.fetch_page(mode="FULL", cursor=None)
    assert first_page.items == () and client.calls == [] and client.id_calls == []
    items = consume_pages(sync)
    assert {item.sku_id for item in items} == {"sku-a", "sku-b"}
    assert all(item.sync_status == "SUCCESS" and item.owner_account_id == "owner-known" for item in items)
    assert client.calls == [("product-known", ["sku-a", "sku-b"])]
    assert client.id_calls == [["product-known"]]
    # The completed coverage set suppresses further scoped requests even if
    # another ID page is replayed on the same adapter.
    assert not sync._fetch_id_page(0).items
    assert len(client.calls) == 1


def test_partial_inline_skus_query_only_missing_and_do_not_mutate_source():
    source = record(present=("sku-a",)); client = Client(rows=[source]); sync = adapter(client)
    items = consume_pages(sync)
    assert {item.sku_id for item in items} == {"sku-a", "sku-b"}
    assert client.calls == [("product-known", ["sku-b"])]
    assert len(source["skus"]) == 1


def test_id_fallback_with_empty_skus_uses_scoped_completion():
    client = Client(); sync = adapter(client)
    page = sync._fetch_id_page(0)
    assert len(page.items) == 2 and all(item.sync_status == "SUCCESS" for item in page.items)
    assert len(client.calls) == 1


def test_lookup_is_batched_to_fifty_known_ids():
    client = Client(); sync = adapter(client, [f"sku-{index:03}" for index in range(101)])
    assert len(consume_pages(sync)) == 101
    assert [len(ids) for _, ids in client.calls] == [50, 50, 1]


@pytest.mark.parametrize("case", ["partial", "duplicate", "extra", "product-conflict", "owner-conflict", "unknown-status", "deleted-status", "business-error", "transport-error"])
def test_bad_lookup_fails_whole_adapter_and_preserves_current(db_session, case):
    returned = [{"sku_id": "sku-a", "status": 1}, {"sku_id": "sku-b", "status": 1}]
    response = {"data": {"error_code": 0, "skus": returned}}
    if case == "partial": returned.pop()
    elif case == "duplicate": returned[1] = dict(returned[0])
    elif case == "extra": returned[1]["sku_id"] = "unknown-sku"
    elif case == "product-conflict": returned[0]["product_id"] = "different-product"
    elif case == "owner-conflict": returned[0]["owner_account_id"] = "sale-account"
    elif case == "unknown-status": returned[0]["status"] = 999
    elif case == "deleted-status": returned[0]["status"] = -1
    elif case == "business-error": response["extra"] = {"error_code": 2190004}
    else: response = RuntimeError("synthetic upstream error")
    db_session.add(DimSkuProductRule(sku_id="sku-a", product_id="product-known", owner_account_id="owner-known",
        sku_name="Trusted", sync_status="SUCCESS", is_active_product=True, product_status_normalized="ACTIVE"))
    _queue(db_session)
    result = execute_product_sync(db_session, job_id="product-sync-1", adapter=adapter(Client(reply=response)))
    assert result.status == "FAILED"
    current = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-a"))
    assert current.sku_name == "Trusted" and current.sync_status == "SUCCESS" and current.is_active_product


@pytest.mark.parametrize("case", ["unknown-product", "unknown-state", "missing-owner"])
def test_no_lookup_for_untrusted_or_unknown_product(case):
    source = record()
    if case == "unknown-product": source["product"]["product_id"] = "unknown"
    elif case == "unknown-state": source["online_status"] = 999
    else: source["product"].pop("owner_account_id")
    client = Client(rows=[source]); sync = adapter(client)
    if case == "unknown-product":
        with pytest.raises(ProductSyncPayloadError, match="incomplete after bounded retries"):
            consume_pages(sync)
        assert client.id_calls == [["product-known", "unknown"]] * 3
    else:
        with pytest.raises(ProductSyncPayloadError): consume_pages(sync)
    assert client.calls == []


def test_known_catalog_only_mapping_is_available_and_conflicts_refused(db_session):
    from apps.api.dy_api.models import RawDouyinOrder
    db_session.add(DimSkuProductRule(sku_id="catalog-only", product_id="known-product"))
    db_session.flush()
    assert extract_known_order_products(db_session) == {"known-product": {"catalog-only"}}
    db_session.add(RawDouyinOrder(order_id="synthetic-order", raw_payload={"products": [{"sku_id": "catalog-only", "product_id": "wrong-product"}]}))
    db_session.flush()
    with pytest.raises(ProductSyncPayloadError, match="identities conflict"):
        extract_known_order_products(db_session)


def test_inactive_product_stays_inactive_after_sku_lookup():
    page = adapter(Client(rows=[record(status=2)]))._fetch_id_page(0)
    assert all(item.product_status_normalized == "INACTIVE" for item in page.items)


def test_completed_known_skus_restore_normal_sync_without_losing_manual_fields(db_session):
    db_session.add(DimSkuProductRule(sku_id="sku-a", product_id="product-known", sku_name="Old name",
        owner_account_id="owner-known", product_scope="Manual scope", product_type="Manual type",
        is_service_product=True, sync_status="MASKED"))
    _queue(db_session)
    client = Client()
    result = execute_product_sync(db_session, job_id="product-sync-1", adapter=adapter(client))
    assert result.status == "SUCCESS"
    rows = list(db_session.scalars(select(DimSkuProductRule).order_by(DimSkuProductRule.sku_id)))
    assert len(rows) == 2
    assert all(row.sync_status == "SUCCESS" and row.owner_account_id == "owner-known" for row in rows)
    assert (rows[0].product_scope, rows[0].product_type, rows[0].is_service_product) == ("Manual scope", "Manual type", True)
    assert client.calls == [("product-known", ["sku-a", "sku-b"])]


def test_id_lookup_must_not_accept_an_unrequested_product():
    client = Client(rows=[{**record(), "product": {**record()["product"], "product_id": "wrong-product"}}])
    client.query_online_products_by_id = lambda product_ids: {"data": {"product_onlines": client.rows}}
    with pytest.raises(ProductSyncPayloadError, match="unexpected product"):
        adapter(client)._fetch_id_page(0)
    assert client.calls == []


def test_known_sku_cannot_belong_to_two_products():
    with pytest.raises(ProductSyncPayloadError, match="conflicting product"):
        DouyinProductSyncAdapter(Client(), known_products={"product-a": {"same-sku"}, "product-b": {"same-sku"}})


def test_detail_omitting_listed_variant_queries_only_globally_unseen_sku():
    source = record(present=("sku-a",))
    client = Client(rows=[source])
    client.query_online_products_by_id = lambda product_ids: {"data": {"product_onlines": [record()]}}
    items = consume_pages(adapter(client))
    assert [item.sku_id for item in items] == ["sku-a", "sku-b"]
    assert client.calls == [("product-known", ["sku-b"])]
