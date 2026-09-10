"""Regression coverage for the page/size shop POI contract."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimStore, DimStorePoiMapping
from apps.worker.collectors.verify_records import collect_shop_pois
from apps.worker.repositories import upsert_store, upsert_store_poi_mapping
from tests.test_douyin_openapi_client import FakeHttp, FakeResponse, client_with


def poi_row(number: int) -> dict:
    return {
        "poi": {"poi_id": f"poi-{number}", "poi_name": f"POI {number}"},
        "account": {"poi_account": {"account_id": f"store-{number}", "account_name": f"Store {number}"}},
    }


class PageClient:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls: list[int] = []

    def query_shop_pois(self, *, relation_type=0, page=1, size=50, cursor=None):
        self.calls.append(page)
        return {"data": self.pages[page - 1]}


def test_shop_poi_request_uses_page_and_size() -> None:
    http = FakeHttp([FakeResponse({"data": {"access_token": "test-token"}}), FakeResponse({"data": {"pois": [], "total": 0}})])
    client_with(http).query_shop_pois(page=2, size=50)
    assert http.calls[-1]["params"] == {"account_id": "acct-1", "relation_type": 0, "page": 2, "size": 50}


def test_shop_pois_collects_all_pages_without_cursor(db_session: Session) -> None:
    client = PageClient([
        {"pois": [poi_row(i) for i in range(50)], "total": 51},
        {"pois": [poi_row(50)], "total": 51},
    ])
    stats = collect_shop_pois(db_session, client, source_run_id="pagination-test")
    assert stats.fetched == 51
    assert client.calls == [1, 2]
    assert db_session.scalar(select(func.count()).select_from(DimStorePoiMapping)) == 51


@pytest.mark.parametrize("second", [
    {"pois": [], "total": 51},
    {"pois": [poi_row(0)], "total": 51},
    {"pois": [poi_row(50)], "total": 52},
    {"pois": [], "total": 51, "error_code": 1},
])
def test_shop_pois_incomplete_scan_does_not_write(db_session: Session, second: dict) -> None:
    client = PageClient([{"pois": [poi_row(i) for i in range(50)], "total": 51}, second])
    with pytest.raises(ValueError):
        collect_shop_pois(db_session, client, source_run_id="pagination-test")
    assert db_session.scalar(select(func.count()).select_from(DimStore)) == 0


def test_shop_pois_keeps_conflicting_existing_mapping(db_session: Session) -> None:
    upsert_store(db_session, "original-store", "Original")
    upsert_store_poi_mapping(db_session, "original-store", "poi-1", mapping_source="manual")
    stats = collect_shop_pois(db_session, PageClient([{"pois": [poi_row(1)], "total": 1}]), source_run_id="pagination-test")
    assert stats.skipped == 1
    assert db_session.scalar(select(DimStorePoiMapping.store_id)) == "original-store"
    assert db_session.get(DimStore, "store-1") is None


def test_shop_pois_does_not_substitute_parent_account(db_session: Session) -> None:
    row = {"poi": {"poi_id": "poi-1"}, "root_account": {"account_id": "parent-company"}}
    stats = collect_shop_pois(db_session, PageClient([{"pois": [row], "total": 1}]), source_run_id="pagination-test")
    assert stats.skipped == 1
    assert db_session.get(DimStore, "parent-company") is None


@pytest.mark.parametrize("page_data", [
    {"pois": None, "total": 0},
    {"total": 0},
    {"pois": [poi_row(1), None], "total": 1},
    {"pois": [poi_row(i) for i in range(51)], "total": 51},
])
def test_shop_pois_rejects_malformed_pages(db_session: Session, page_data: dict) -> None:
    with pytest.raises(ValueError):
        collect_shop_pois(db_session, PageClient([page_data]), source_run_id="pagination-test")
    assert db_session.scalar(select(func.count()).select_from(DimStore)) == 0


def test_atomic_mapping_guard_rejects_conflicting_owner(db_session: Session) -> None:
    upsert_store(db_session, "original", "Original")
    upsert_store(db_session, "other", "Other")
    upsert_store_poi_mapping(db_session, "original", "poi-1")
    with pytest.raises(ValueError, match="conflict"):
        upsert_store_poi_mapping(db_session, "other", "poi-1", preserve_existing_store=True)
    assert db_session.scalar(select(DimStorePoiMapping.store_id)) == "original"
