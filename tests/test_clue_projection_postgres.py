"""Opt-in PostgreSQL lock-order regression for clue projection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.models import Base, ClueMasterLead
from apps.worker.clue_center import _locked_master_leads


@pytest.fixture()
def postgres_engine():
    url = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_CLUE_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database and parsed.database.endswith("_test")
    schema = "clue_projection_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"},
    )
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            observed_at = datetime(2026, 9, 7, 10, tzinfo=timezone.utc)
            session.add_all(
                [
                    ClueMasterLead(
                        lead_key="lead-a",
                        source_clue_row_key="source-a",
                        source_identity_key="identity-a",
                        canonical_clue_id="clue-a",
                        order_id="order-z",
                        normalized_order_status="active",
                        status_source="test",
                        lifecycle_status="active",
                        allocation_state="pending_allocation",
                        first_seen_at=observed_at,
                        last_seen_at=observed_at,
                        created_at=observed_at,
                        updated_at=observed_at,
                    ),
                    ClueMasterLead(
                        lead_key="lead-b",
                        source_clue_row_key="source-b",
                        source_identity_key="identity-b",
                        canonical_clue_id="clue-b",
                        order_id="order-a",
                        normalized_order_status="active",
                        status_source="test",
                        lifecycle_status="active",
                        allocation_state="pending_allocation",
                        first_seen_at=observed_at,
                        last_seen_at=observed_at,
                        created_at=observed_at,
                        updated_at=observed_at,
                    ),
                ]
            )
            session.commit()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_projection_master_lock_order_is_independent_of_order_sort(postgres_engine) -> None:
    entered = [Event(), Event()]
    first_locked = Event()
    release_first = Event()

    def lock_batch(candidate_order: tuple[str, str], index: int) -> tuple[str, ...]:
        with Session(postgres_engine) as session:
            candidates = [session.get(ClueMasterLead, key) for key in candidate_order]
            assert all(candidates)
            entered[index].set()
            locked = _locked_master_leads(session, candidates)
            if index == 0:
                first_locked.set()
                assert release_first.wait(5)
            session.commit()
            return tuple(locked)

    # order-a maps to lead-b while order-z maps to lead-a.  The two callers
    # deliberately submit opposite order-derived candidate lists.
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(lock_batch, ("lead-b", "lead-a"), 0)
        assert first_locked.wait(5)
        second = executor.submit(lock_batch, ("lead-a", "lead-b"), 1)
        assert entered[1].wait(5)
        release_first.set()
        assert first.result(timeout=10) == ("lead-a", "lead-b")
        assert second.result(timeout=10) == ("lead-a", "lead-b")
