from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from apps.api.dy_api.models import RawDouyinClue
from apps.worker.collectors.clues import collect_clues
from apps.worker.collectors.types import CollectionWindow


class FakeClueClient:
    def __init__(self, pages: list[list[dict[str, Any]]]):
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def query_clues(
        self,
        start: datetime,
        end: datetime,
        *,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        self.calls.append(
            {"start": start, "end": end, "page": page, "page_size": page_size}
        )
        rows = self.pages[page - 1] if page <= len(self.pages) else []
        return {"data": {"clue_data": rows}}


def window() -> CollectionWindow:
    return CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-06-02T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )


def test_collect_clues_upserts_raw_rows_and_parses_phone_fields(
    db_session: Session,
) -> None:
    client = FakeClueClient(
        [
            [
                {
                    "clue_id": "clue-1",
                    "create_time_detail": "2026-06-01 10:00:00",
                    "modify_time": "2026-06-01 10:05:00",
                    "name": "Customer A",
                    "tel_addr": "13812345678",
                    "enc_telephone": "encrypted-phone",
                    "product_id": "sku-1",
                    "product_name": "Service Product",
                    "order_id": "order-1",
                    "order_status": "履约中",
                    "follow_life_account_id": "store-1",
                    "follow_life_account_name": "Store One",
                    "follow_poi_id": "poi-anchor-1",
                    "intention_poi_id": "poi-intention-1",
                    "auto_city_name": "Shanghai",
                    "auto_province_name": "Shanghai",
                    "author_nickname": "Author One",
                },
                {
                    "clue_id": "clue-2",
                    "create_time_detail": 1780311600,
                    "telephone": "13912345678",
                    "order_id": "order-2",
                    "order_status": "履约中",
                },
            ],
            [
                {
                    "clue_id": "clue-3",
                    "telephone": "",
                    "enc_telephone": "encrypted-only",
                    "order_id": "order-3",
                    "order_status": "履约中",
                }
            ],
        ]
    )

    first = collect_clues(db_session, client, window(), source_run_id="run-1", page_size=2)
    second = collect_clues(db_session, client, window(), source_run_id="run-1", page_size=2)

    assert first.fetched == 3
    assert first.upserted == 3
    assert second.upserted == 3
    assert db_session.query(RawDouyinClue).count() == 3

    clue = db_session.get(RawDouyinClue, "clue-1")
    assert clue is not None
    assert clue.telephone == "13812345678"
    assert clue.enc_telephone == "encrypted-phone"
    assert clue.order_id == "order-1"
    assert clue.order_status == "履约中"
    assert clue.follow_life_account_id == "store-1"
    assert clue.follow_poi_id == "poi-anchor-1"
    assert clue.intention_poi_id == "poi-intention-1"
    assert clue.raw_payload["tel_addr"] == "13812345678"
    assert clue.source_file is None
    assert clue.fetched_at is not None
