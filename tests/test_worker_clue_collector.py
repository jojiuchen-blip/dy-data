from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from apps.api.dy_api.models import RawDouyinClue
from apps.worker.collectors.clues import ClueCollectionError, collect_clues
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
    assert second.upserted == 0
    assert second.unchanged == 3
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


def test_collect_clues_passes_observation_metadata_and_classifies_replays(
    db_session: Session,
) -> None:
    row = {
        "clue_id": "clue-changing",
        "modify_time": "2026-06-01T10:00:00+00:00",
        "telephone": "13812345678",
        "order_status": "履约中",
        "follow_life_account_id": "store-old",
    }
    client = FakeClueClient([[row]])

    first = collect_clues(
        db_session,
        client,
        window(),
        source_run_id="run-insert",
        page_size=100,
    )

    assert first.inserted == 1
    assert first.updated == 0
    assert first.unchanged == 0
    assert first.rejected == 0
    assert first.upserted == 1

    changed = {
        **row,
        "modify_time": "2026-06-01T11:00:00+00:00",
        "telephone": "13912345678",
        "order_status": "已退款",
        "follow_life_account_id": "store-new",
    }
    client.pages = [[changed]]
    second = collect_clues(
        db_session,
        client,
        window(),
        source_run_id="run-update",
        page_size=100,
    )

    stored = db_session.get(RawDouyinClue, "clue-changing")
    assert stored is not None
    assert stored.telephone == "13912345678"
    assert stored.order_status == "已退款"
    assert stored.follow_life_account_id == "store-new"
    assert stored.source_run_id == "run-update"
    assert stored.source_observed_at == datetime.fromisoformat("2026-06-01T11:00:00")
    assert stored.observation_key
    assert second.inserted == 0
    assert second.updated == 1
    assert second.unchanged == 0
    assert second.rejected == 0
    assert second.upserted == 1

    duplicate = collect_clues(
        db_session,
        client,
        window(),
        source_run_id="run-duplicate",
        page_size=100,
    )
    assert duplicate.inserted == 0
    assert duplicate.updated == 0
    assert duplicate.unchanged == 1
    assert duplicate.rejected == 0
    assert duplicate.upserted == 0

    stale = {**row, "modify_time": "2026-06-01T09:00:00+00:00"}
    client.pages = [[stale]]
    rejected = collect_clues(
        db_session,
        client,
        window(),
        source_run_id="run-stale",
        page_size=100,
    )
    stored = db_session.get(RawDouyinClue, "clue-changing")
    assert stored is not None
    assert stored.telephone == "13912345678"
    assert stored.order_status == "已退款"
    assert rejected.inserted == 0
    assert rejected.updated == 0
    assert rejected.unchanged == 0
    assert rejected.rejected == 1
    assert rejected.upserted == 0

    no_time = {"clue_id": "clue-no-time", "order_status": "履约中"}
    client.pages = [[no_time]]
    initial_without_time = collect_clues(
        db_session,
        client,
        window(),
        source_run_id="run-no-time-insert",
        page_size=100,
    )
    assert initial_without_time.inserted == 1
    client.pages = [[{**no_time, "order_status": "已退款"}]]
    replay_without_time = collect_clues(
        db_session,
        client,
        window(),
        source_run_id="run-no-time-replay",
        page_size=100,
    )
    no_time_stored = db_session.get(RawDouyinClue, "clue-no-time")
    assert no_time_stored is not None
    assert no_time_stored.order_status == "履约中"
    assert replay_without_time.rejected == 1
    assert replay_without_time.upserted == 0


def test_collect_clues_rejects_an_incomplete_minimum_window() -> None:
    class SaturatedClient:
        def __init__(self) -> None:
            self.calls = 0

        def query_clues(
            self,
            start: datetime,
            end: datetime,
            *,
            page: int,
            page_size: int,
        ) -> dict[str, Any]:
            self.calls += 1
            return {
                "data": {
                    "total": 10_000,
                    "clue_data": [
                        {"clue_id": f"second-{index}"}
                        for index in range(page_size)
                    ],
                }
            }

    client = SaturatedClient()
    minimum_window = CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
        end=datetime.fromisoformat("2026-06-01T00:00:01+00:00"),
        timezone_name="UTC",
    )

    with pytest.raises(ClueCollectionError, match="incomplete"):
        collect_clues(
            None,  # type: ignore[arg-type]
            client,
            minimum_window,
            source_run_id="run-saturated",
            page_size=100,
        )

    assert client.calls == 1


def test_collect_clues_rejects_a_short_page_before_declared_total() -> None:
    class PartialPageClient:
        def __init__(self) -> None:
            self.calls = 0

        def query_clues(
            self,
            start: datetime,
            end: datetime,
            *,
            page: int,
            page_size: int,
        ) -> dict[str, Any]:
            self.calls += 1
            return {
                "data": {
                    "total": 500,
                    "clue_data": [
                        {"clue_id": f"partial-{index}"}
                        for index in range(min(20, page_size))
                    ],
                }
            }

    client = PartialPageClient()
    minimum_window = CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
        end=datetime.fromisoformat("2026-06-01T01:00:00+00:00"),
        timezone_name="UTC",
    )

    with pytest.raises(ClueCollectionError, match="incomplete"):
        collect_clues(
            None,  # type: ignore[arg-type]
            client,
            minimum_window,
            source_run_id="run-partial-page",
            page_size=100,
        )

    assert client.calls == 12


def test_collect_clues_splits_a_saturated_hour_into_half_hours(db_session: Session) -> None:
    class SplitClient:
        def __init__(self) -> None:
            self.calls: list[tuple[datetime, datetime, int]] = []

        def query_clues(
            self,
            start: datetime,
            end: datetime,
            *,
            page: int,
            page_size: int,
        ) -> dict[str, Any]:
            self.calls.append((start, end, page))
            if end - start >= timedelta(hours=1):
                return {
                    "data": {
                        "total": 10_000,
                        "clue_data": [{"clue_id": "wide-saturated"}],
                    }
                }
            return {
                "data": {
                    "total": 1,
                    "clue_data": [{"clue_id": f"half-{start.isoformat()}"}],
                }
            }

    client = SplitClient()
    split_window = CollectionWindow(
        start=datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
        end=datetime.fromisoformat("2026-06-01T01:00:00+00:00"),
        timezone_name="UTC",
    )

    stats = collect_clues(
        db_session,
        client,
        split_window,
        source_run_id="run-split",
        page_size=100,
    )

    assert stats.inserted == 2
    assert stats.failed == 0
    assert len(client.calls) == 3
    assert [(start, end) for start, end, _ in client.calls] == [
        (
            datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
            datetime.fromisoformat("2026-06-01T01:00:00+00:00"),
        ),
        (
            datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
            datetime.fromisoformat("2026-06-01T00:30:00+00:00"),
        ),
        (
            datetime.fromisoformat("2026-06-01T00:30:00+00:00"),
            datetime.fromisoformat("2026-06-01T01:00:00+00:00"),
        ),
    ]
