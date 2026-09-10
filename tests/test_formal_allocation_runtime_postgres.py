"""Real PostgreSQL transaction and cross-connection exclusion tests."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    Base,
    ClueAssignmentRound,
    ClueCenterOrder,
    DimStorePoiMapping,
    RawDouyinClue,
    RawDouyinOrder,
)
from apps.worker import formal_allocation_runtime as runtime
from test_formal_allocation_runtime import NOW, seed, setup


@pytest.fixture()
def factory():
    url = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable local PostgreSQL")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.endswith("_test")
    schema = "formal_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"})
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as session:
            setup(session)
            seed(session)
            session.commit()
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_overlapping_consumers_excluded_and_lock_released(factory, monkeypatch):
    entered, release = Event(), Event()
    original = runtime.allocate_lead

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "allocate_lead", blocked)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.run_formal_allocation_batch, factory)
        try:
            assert entered.wait(10)
            second = runtime.run_formal_allocation_batch(factory)
            assert second["skipped_reason"] == "locked"
        finally:
            release.set()
        assert future.result(timeout=10)["assigned"] == 1
    assert runtime.run_formal_allocation_batch(factory)["assigned"] == 0
    with factory() as reader:
        assert reader.query(ClueAssignmentRound).count() == 1


def test_failure_after_allocation_rolls_back_and_next_sweep_recovers(factory, monkeypatch):
    original = runtime.allocate_lead

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("after writes before commit")

    monkeypatch.setattr(runtime, "allocate_lead", fail)
    assert runtime.run_formal_allocation_batch(factory)["failed"] == 1
    with factory() as reader:
        assert reader.query(ClueAssignmentRound).count() == 0
    monkeypatch.setattr(runtime, "allocate_lead", original)
    runtime.run_formal_allocation_batch(factory)  # Wrap the durable keyset cursor.
    assert runtime.run_formal_allocation_batch(factory)["assigned"] == 1


def test_missing_center_with_coupon_is_projected_allocated_and_idempotent(factory):
    with factory() as session:
        session.add(DimStorePoiMapping(store_id="anchor", poi_id="pg-poi-anchor"))
        lead = seed_missing_center(session)
        session.commit()

    first = runtime.run_formal_allocation_batch(
        factory, order_ids=[lead.order_id], now=NOW
    )
    second = runtime.run_formal_allocation_batch(
        factory, order_ids=[lead.order_id], now=NOW
    )

    assert first["center_repaired"] == 1
    assert first["assigned"] == 1
    assert second["center_repaired"] == 0
    assert second["assigned"] == 0
    with factory() as reader:
        center = reader.get(ClueCenterOrder, lead.order_id)
        assert center is not None
        rounds = reader.query(ClueAssignmentRound).filter_by(order_id=lead.order_id).all()
        assert len(rounds) == 1
        assert rounds[0].execution_mode == "formal"
        assert center.current_assignment_round_id == rounds[0].assignment_round_id


def seed_missing_center(session):
    from test_clue_allocation_engine import _lead

    lead = _lead("pg-missing-center", order_id="pg-missing-center-order")
    session.add_all(
        [
            lead,
            RawDouyinClue(
                clue_row_key=lead.source_clue_row_key,
                clue_id=lead.canonical_clue_id,
                order_id=lead.order_id,
                order_status="200",
                follow_poi_id="pg-poi-anchor",
                source_observed_at=NOW,
                raw_payload={},
            ),
            RawDouyinOrder(
                order_id=lead.order_id,
                order_status="200",
                raw_payload={"certificate": [{"item_status": 400}]},
            ),
        ]
    )
    return lead
