from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimStorePoiMapping, RawDouyinVerifyRecord
from apps.worker.collectors.types import CollectionWindow
from apps.worker.collectors.verify_records import collect_shop_pois, collect_verify_records


class FakeVerifyClient:
    def query_shop_pois(self, *, relation_type: int = 0, cursor=None):
        return {
            "data": {
                "pois": [
                    {
                        "poi_id": "poi-1",
                        "poi_name": "Store One POI",
                        "store_id": "store-1",
                        "store_name": "Store One",
                    }
                ],
                "has_more": False,
            }
        }

    def query_verify_records(self, start: datetime, end: datetime, *, poi_id=None, page_size: int = 20, cursor=None):
        return {
            "data": {
                "verify_records": [
                    {
                        "verify_id": "verify-1",
                        "certificate_id": "coupon-1",
                        "status": "valid",
                        "verify_time": 1767225600,
                        "verify_poi_id": "poi-1",
                        "verify_poi_name": "Store One POI",
                        "sku": {"sku_id": "sku-1", "title": "Service Product"},
                        "amount": {"pay_amount": 12345},
                    },
                    {
                        "verify_id": "verify-cancelled",
                        "certificate_id": "coupon-2",
                        "status": "cancelled",
                        "verify_time": 1767225600,
                        "verify_poi_id": "poi-1",
                        "cancel_time": 1767230000,
                    },
                ],
                "has_more": False,
            }
        }


def count(session: Session, model: type) -> int:
    value = session.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


def window() -> CollectionWindow:
    return CollectionWindow(
        start=datetime.fromisoformat("2026-01-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-01-02T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )


def test_collect_shop_pois_upserts_store_poi_mappings_idempotently(db_session: Session):
    client = FakeVerifyClient()

    first = collect_shop_pois(db_session, client, source_run_id="run-verify")
    second = collect_shop_pois(db_session, client, source_run_id="run-verify")

    assert first.fetched == 1
    assert first.upserted == 2
    assert second.upserted == 2
    assert count(db_session, DimStorePoiMapping) == 1

    mapping = db_session.get(DimStorePoiMapping, ("store-1", "poi-1"))
    assert mapping is not None
    assert mapping.poi_name == "Store One POI"
    assert mapping.mapping_source == "douyin_shop_poi"


def test_collect_verify_records_upserts_cancel_state_and_raw_payload(db_session: Session):
    client = FakeVerifyClient()

    first = collect_verify_records(db_session, client, window(), source_run_id="run-verify")
    second = collect_verify_records(db_session, client, window(), source_run_id="run-verify")

    assert first.fetched == 2
    assert first.upserted == 2
    assert second.upserted == 2
    assert count(db_session, RawDouyinVerifyRecord) == 2

    record = db_session.get(RawDouyinVerifyRecord, "verify-1")
    assert record is not None
    assert record.coupon_id == "coupon-1"
    assert record.verify_status == "valid"
    assert record.poi_id == "poi-1"
    assert record.verify_store_name_raw == "Store One POI"
    assert record.sku_id == "sku-1"
    assert record.product_name == "Service Product"
    assert record.paid_amount_cent == 12345
    assert record.raw_payload["amount"]["pay_amount"] == 12345

    cancelled = db_session.get(RawDouyinVerifyRecord, "verify-cancelled")
    assert cancelled is not None
    assert cancelled.verify_status == "cancelled"
    assert cancelled.cancel_time is not None


def test_collect_verify_records_splits_large_windows_by_chunk_days(db_session: Session):
    class EmptyVerifyClient:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def query_verify_records(
            self,
            start: datetime,
            end: datetime,
            *,
            poi_id=None,
            page_size: int = 20,
            cursor=None,
        ):
            self.calls.append((start.isoformat(), end.isoformat()))
            return {"data": {"verify_records": [], "has_more": False}}

    client = EmptyVerifyClient()
    large_window = CollectionWindow(
        start=datetime.fromisoformat("2026-01-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-01-16T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )

    collect_verify_records(db_session, client, large_window, source_run_id="run-verify", chunk_days=7)

    assert client.calls == [
        ("2026-01-01T00:00:00+08:00", "2026-01-08T00:00:00+08:00"),
        ("2026-01-08T00:00:00+08:00", "2026-01-15T00:00:00+08:00"),
        ("2026-01-15T00:00:00+08:00", "2026-01-16T00:00:00+08:00"),
    ]
