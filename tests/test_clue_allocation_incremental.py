from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueHeadquartersPoolEntry,
    ClueMaterializationTarget,
    ClueMasterLead,
    ClueMaterializationWorkItem,
    ClueOrderStatusEvent,
    ClueSourceIdentifierHistory,
    DataQualityIssue,
    DimStore,
    DimStorePoiMapping,
    JobAttempt,
    JobImpact,
    JobImpactWatermark,
    RawDouyinClue,
    RawDouyinOrder,
    SettlementOrderDetail,
    Base,
)
from apps.worker import clue_allocation
from apps.worker import daily_task
from apps.worker.clue_allocation import (
    _verified_at_by_order,
    materialize_clue_master_leads,
    run_incremental_clue_materialization,
)
from apps.worker.clue_center import (
    _verification_rows,
    refresh_clue_center_projection as rebuild_clue_center,
)
from apps.worker.repositories import upsert_raw_clue
from apps.worker.subprocess_supervisor import read_process_rss_bytes


def _dt(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def _store(store_id: str, poi_id: str) -> tuple[DimStore, DimStorePoiMapping]:
    return (
        DimStore(
            store_id=store_id,
            store_name=store_id,
            is_active=True,
            standard_province="上海",
            standard_city="上海",
            city_code="上海",
            longitude=Decimal("121.470000"),
            latitude=Decimal("31.230000"),
            is_douyin_clue_applicable=True,
            participates_in_clue_allocation=True,
            location_source="test",
            location_status="valid",
            location_updated_at=_dt(1),
        ),
        DimStorePoiMapping(
            store_id=store_id,
            poi_id=poi_id,
            mapping_source="test",
        ),
    )


def _clue(row_key: str, clue_id: str, order_id: str, poi_id: str) -> RawDouyinClue:
    return RawDouyinClue(
        clue_row_key=row_key,
        clue_id=clue_id,
        order_id=order_id,
        order_status="履约中",
        telephone="13800000000",
        follow_poi_id=poi_id,
        create_time_detail=_dt(1),
        fetched_at=_dt(1),
        imported_at=_dt(1),
        updated_at=_dt(1),
        raw_payload={"clue_id": clue_id, "follow_poi_id": poi_id},
    )


def _factory(session: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)


def test_incremental_materialization_processes_three_keyset_pages_and_freezes_upper_bound(
    db_session: Session,
) -> None:
    store, mapping = _store("store-a", "poi-a")
    db_session.add_all(
        [
            store,
            mapping,
            *[
                RawDouyinOrder(order_id=f"order-{index}", order_status="履约中", updated_at=_dt(1))
                for index in range(5)
            ],
            _clue("raw-a", "clue-a", "order-a", "poi-a"),
        ]
    )
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(2))
    db_session.commit()

    for index in range(5):
        upsert_raw_clue(
            db_session,
            f"raw-{index}",
            clue_id=f"clue-{index}",
            order_id=f"order-{index}",
            order_status="履约中",
            follow_poi_id="poi-a",
            create_time_detail=_dt(1),
            fetched_at=_dt(3),
            imported_at=_dt(3),
            updated_at=_dt(3),
            raw_payload={"clue_id": f"clue-{index}"},
            source_observed_at=_dt(3),
            observation_key=f"obs-{index}",
        )
    db_session.commit()

    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=2,
        lease_token="attempt-3-pages",
        now=_dt(4),
    )

    assert result["work_items"] == 5
    assert result["batches"] == 3
    assert result["frozen_upper_bound_id"] >= 5
    assert db_session.scalar(
        select(func.count()).select_from(ClueMaterializationWorkItem).where(
            ClueMaterializationWorkItem.state == "completed"
        )
    ) == 5
    checkpoint = db_session.get(JobImpactWatermark, "clue_materialization")
    assert checkpoint is not None
    max_completed = db_session.scalar(
        select(func.max(ClueMaterializationWorkItem.work_item_id)).where(
            ClueMaterializationWorkItem.state == "completed"
        )
    )
    assert checkpoint.last_work_item_id == max_completed
    assert db_session.scalar(
        select(func.count()).select_from(ClueMaterializationWorkItem).where(
            ClueMaterializationWorkItem.state != "completed",
            ClueMaterializationWorkItem.impact_id <= checkpoint.frozen_upper_bound_id,
        )
    ) == 0


def test_incremental_materialization_retries_a_crashed_batch_without_duplicate_history_or_events(
    db_session: Session,
) -> None:
    store, mapping = _store("store-a", "poi-a")
    db_session.add_all([store, mapping, _clue("raw-a", "clue-a", "order-a", "poi-a")])
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(2))
    db_session.commit()
    upsert_raw_clue(
        db_session,
        "raw-a",
        clue_id="clue-b",
        order_id="order-a",
        order_status="履约中",
        follow_poi_id="poi-a",
        telephone="13900000000",
        fetched_at=_dt(3),
        imported_at=_dt(3),
        updated_at=_dt(3),
        raw_payload={"clue_id": "clue-b"},
        source_observed_at=_dt(3),
        observation_key="obs-b",
    )
    db_session.commit()
    impact_count_before = db_session.scalar(select(func.count()).select_from(JobImpact))

    factory = _factory(db_session)
    original_complete = clue_allocation.complete_clue_materialization_batch

    def fail_complete(*args, **kwargs):
        raise RuntimeError("injected crash before complete")

    clue_allocation.complete_clue_materialization_batch = fail_complete
    try:
        with pytest.raises(RuntimeError, match="injected crash before complete"):
            run_incremental_clue_materialization(
                factory,
                batch_size=1,
                lease_token="attempt-crash",
                now=_dt(4),
            )
    finally:
        clue_allocation.complete_clue_materialization_batch = original_complete
    assert db_session.scalar(
        select(func.count()).select_from(ClueMaterializationWorkItem).where(
            ClueMaterializationWorkItem.state == "pending"
        )
    ) >= 1
    # Raw projection pages are durable before the center completion fence.  A
    # completion failure therefore leaves the page's two identifier values
    # committed; the retry only needs to finish the center phase.
    assert db_session.scalar(select(func.count()).select_from(ClueSourceIdentifierHistory)) == 4
    assert db_session.scalar(select(ClueMasterLead.canonical_clue_id)) == "clue-b"

    second = run_incremental_clue_materialization(
        factory,
        batch_size=1,
        lease_token="attempt-retry",
        now=_dt(5),
    )
    assert second["work_items"] == 1
    assert db_session.scalar(select(func.count()).select_from(JobImpact)) == impact_count_before
    assert db_session.scalar(select(func.count()).select_from(ClueSourceIdentifierHistory)) == 4
    master = db_session.scalar(select(ClueMasterLead))
    assert master is not None
    assert master.canonical_clue_id == "clue-b"
    third = run_incremental_clue_materialization(
        factory,
        batch_size=1,
        lease_token="attempt-idempotent",
        now=_dt(6),
    )
    assert third["work_items"] == 0
    assert db_session.scalar(select(func.count()).select_from(ClueSourceIdentifierHistory)) == 4


def test_incremental_exception_releases_unprocessed_claimed_batch_items(
    db_session: Session,
) -> None:
    """A normal stage exception must not strand the rest of its claimed batch."""

    db_session.add_all(
        [
            JobImpact(
                impact_key="ordinary-error-batch-a",
                entity_type="clue",
                entity_key="raw-ordinary-error-a",
                affected_closure_json={},
            ),
            JobImpact(
                impact_key="ordinary-error-batch-b",
                entity_type="clue",
                entity_key="raw-ordinary-error-b",
                affected_closure_json={},
            ),
        ]
    )
    db_session.commit()

    original_process = clue_allocation._process_incremental_clue_work_item

    def fail_before_processing(*_args, **_kwargs):
        raise RuntimeError("ordinary page failure")

    clue_allocation._process_incremental_clue_work_item = fail_before_processing
    try:
        with pytest.raises(RuntimeError, match="ordinary page failure"):
            run_incremental_clue_materialization(
                _factory(db_session),
                scope="clue_materialization",
                batch_size=2,
                lease_token="attempt-ordinary-error",
                now=_dt(4),
            )
    finally:
        clue_allocation._process_incremental_clue_work_item = original_process

    db_session.expire_all()
    items = list(
        db_session.scalars(
            select(ClueMaterializationWorkItem).order_by(
                ClueMaterializationWorkItem.work_item_id
            )
        )
    )
    assert len(items) == 2
    assert all(item.state == "pending" for item in items)
    assert all(item.lease_owner is None for item in items)
    assert all(item.lease_expires_at is None for item in items)


def test_finished_attempt_crash_resumes_from_committed_raw_cursor_without_duplicate(
    db_session: Session,
) -> None:
    """A finished crashed attempt lets the next attempt resume the next raw page."""

    store_a, mapping_a = _store("store-crash-a", "poi-crash-a")
    store_b, mapping_b = _store("store-crash-b", "poi-crash-b")
    db_session.add_all(
        [
            store_a,
            mapping_a,
            store_b,
            mapping_b,
            RawDouyinOrder(
                order_id="order-crash-a",
                order_status="fulfilled",
                updated_at=_dt(1),
            ),
            RawDouyinOrder(
                order_id="order-crash-b",
                order_status="fulfilled",
                updated_at=_dt(1),
            ),
            _clue("raw-crash-a", "clue-crash-a", "order-crash-a", "poi-crash-a"),
            _clue("raw-crash-b", "clue-crash-b", "order-crash-b", "poi-crash-b"),
            JobImpact(
                impact_key="finished-attempt-crash-impact",
                entity_type="clue",
                entity_key="raw-crash-a",
                affected_closure_json={
                    "clue_ids": ["clue-crash-a", "clue-crash-b"],
                    "order_ids": ["order-crash-a", "order-crash-b"],
                    "poi_ids": ["poi-crash-a", "poi-crash-b"],
                },
            ),
        ]
    )
    db_session.commit()

    commit_calls = 0

    class CrashAfterPageCommitSession(Session):
        def commit(self):  # type: ignore[override]
            nonlocal commit_calls
            super().commit()
            commit_calls += 1
            if commit_calls == 2:
                raise KeyboardInterrupt("simulated host crash after page commit")

    crash_factory = sessionmaker(
        bind=db_session.get_bind(),
        class_=CrashAfterPageCommitSession,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    with pytest.raises(KeyboardInterrupt, match="simulated host crash"):
        run_incremental_clue_materialization(
            crash_factory,
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-a-crash",
            now=_dt(4),
        )

    db_session.expire_all()
    work = db_session.scalar(select(ClueMaterializationWorkItem))
    assert work is not None
    assert work.state == "processing"
    assert work.lease_owner == "attempt-a-crash"
    assert work.raw_cursor == "raw-crash-a"
    first_master_count = db_session.scalar(select(func.count()).select_from(ClueMasterLead))
    assert first_master_count == 1
    first_master = db_session.scalar(select(ClueMasterLead))
    assert first_master is not None
    first_master_key = first_master.lead_key
    first_master_history_count = db_session.scalar(
        select(func.count()).select_from(ClueSourceIdentifierHistory).where(
            ClueSourceIdentifierHistory.lead_key == first_master_key
        )
    )

    finished_at = datetime.now(timezone.utc)
    db_session.add(
        JobAttempt(
            attempt_id="attempt-a-crash",
            job_id="job-attempt-a-crash",
            stage_run_id=None,
            attempt_number=1,
            lease_epoch=1,
            component_type="worker",
            component_instance_id="component-attempt-a-crash",
            started_at=finished_at - timedelta(seconds=1),
            finished_at=finished_at,
            exit_type="crashed",
            created_at=finished_at - timedelta(seconds=1),
        )
    )
    db_session.commit()

    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-b-recovery",
        now=_dt(5),
    )
    assert result["work_items"] == 1
    assert result["raw_rows"] == 1
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == first_master_count + 1
    assert (
        db_session.scalar(select(func.count()).select_from(ClueSourceIdentifierHistory))
        >= first_master_history_count
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(ClueSourceIdentifierHistory).where(
                ClueSourceIdentifierHistory.lead_key == first_master_key
            )
        )
        == first_master_history_count
    )
    db_session.expire_all()
    resumed = db_session.get(ClueMaterializationWorkItem, work.work_item_id)
    assert resumed is not None and resumed.state == "completed"

    before_replay = {
        "masters": db_session.scalar(select(func.count()).select_from(ClueMasterLead)),
        "history": db_session.scalar(
            select(func.count()).select_from(ClueSourceIdentifierHistory)
        ),
        "status_events": db_session.scalar(
            select(func.count()).select_from(ClueOrderStatusEvent)
        ),
        "assignment_rounds": db_session.scalar(
            select(func.count()).select_from(ClueAssignmentRound)
        ),
        "center_orders": db_session.scalar(
            select(func.count()).select_from(ClueCenterOrder)
        ),
    }
    replay = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-c-idempotent-replay",
        now=_dt(6),
    )
    assert replay["work_items"] == 0
    assert {
        "masters": db_session.scalar(select(func.count()).select_from(ClueMasterLead)),
        "history": db_session.scalar(
            select(func.count()).select_from(ClueSourceIdentifierHistory)
        ),
        "status_events": db_session.scalar(
            select(func.count()).select_from(ClueOrderStatusEvent)
        ),
        "assignment_rounds": db_session.scalar(
            select(func.count()).select_from(ClueAssignmentRound)
        ),
        "center_orders": db_session.scalar(
            select(func.count()).select_from(ClueCenterOrder)
        ),
    } == before_replay


def test_incremental_materialization_uses_only_bounded_closure_queries(
    db_session: Session,
) -> None:
    store, mapping = _store("store-a", "poi-a")
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id="order-a", order_status="履约中", updated_at=_dt(1)),
            _clue("raw-a", "clue-a", "order-a", "poi-a"),
        ]
    )
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(2))
    db_session.commit()
    upsert_raw_clue(
        db_session,
        "raw-a",
        clue_id="clue-b",
        order_id="order-a",
        order_status="履约中",
        follow_poi_id="poi-a",
        fetched_at=_dt(3),
        imported_at=_dt(3),
        updated_at=_dt(3),
        raw_payload={"clue_id": "clue-b"},
        source_observed_at=_dt(3),
        observation_key="obs-b",
    )
    db_session.commit()

    statements: list[str] = []

    def collect_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", collect_sql)
    try:
        run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            lease_token="attempt-bounded",
            now=_dt(4),
        )
    finally:
        event.remove(engine, "before_cursor_execute", collect_sql)

    assert statements
    assert not any(
        "FROM RAW_DOUYIN_CLUES" in statement.upper()
        and "WHERE" not in statement.upper()
        for statement in statements
    )
    assert not any(
        "FROM CLUE_MASTER_LEADS" in statement.upper()
        and "WHERE" not in statement.upper()
        for statement in statements
    )


def test_incremental_materialization_scale_keeps_loaded_rows_bounded() -> None:
    """A fixed one-row impact must not load unrelated 10N history into a page session."""

    def run_case(history_size: int) -> dict[str, object]:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
        with factory() as seed:
            store, mapping = _store(
                f"store-scale-{history_size}",
                f"poi-scale-{history_size}",
            )
            target = _clue(
                f"raw-scale-target-{history_size}",
                f"clue-scale-target-{history_size}",
                f"order-scale-target-{history_size}",
                f"poi-scale-{history_size}",
            )
            target.source_observed_at = _dt(5)
            target.observation_key = "target"
            seed.add_all(
                [
                    store,
                    mapping,
                    RawDouyinOrder(
                        order_id=target.order_id,
                        order_status="fulfilled",
                        updated_at=_dt(1),
                    ),
                    target,
                ]
            )
            for index in range(history_size):
                lead_key = f"lead-scale-unrelated-{index}"
                row_key = f"raw-scale-unrelated-{index}"
                clue_id = f"clue-scale-unrelated-{index}"
                seed.add(
                    ClueMasterLead(
                        lead_key=lead_key,
                        source_clue_row_key=row_key,
                        source_identity_key=f"identity-scale-unrelated-{index}",
                        canonical_clue_id=clue_id,
                        order_id=f"order-scale-unrelated-{index}",
                        raw_order_status="fulfilled",
                        normalized_order_status="fulfilled",
                        status_source="clue",
                        lifecycle_status="active",
                        pool_location="headquarters_pool",
                        first_seen_at=_dt(1),
                        last_seen_at=_dt(2),
                        last_observation_key="history",
                    )
                )
                seed.add(
                    ClueSourceIdentifierHistory(
                        identifier_history_id=f"history-scale-unrelated-{index}",
                        lead_key=lead_key,
                        source_clue_row_key=row_key,
                        identifier_type="clue_id",
                        identifier_value=clue_id,
                        first_seen_at=_dt(1),
                        last_seen_at=_dt(2),
                        is_current=True,
                    )
                )
            seed.commit()
            seed.add(
                JobImpact(
                    impact_key=f"impact-scale-{history_size}",
                    entity_type="clue",
                    entity_key=target.clue_row_key,
                    change_kind="upsert",
                    affected_closure_json={
                        "clue_ids": [target.clue_id],
                        "order_ids": [target.order_id],
                        "poi_ids": [mapping.poi_id],
                    },
                )
            )
            seed.commit()

        metrics: dict[str, object] = {
            "raw_page_sizes": [],
            "identity_peaks": [],
            "selects": [],
        }
        original_bounded_raw_clues = clue_allocation._bounded_raw_clues
        original_materialize = clue_allocation.materialize_clue_master_leads

        def record_bounded_raw_clues(session: Session, *args, **kwargs):
            rows = original_bounded_raw_clues(session, *args, **kwargs)
            metrics["raw_page_sizes"].append(len(rows))
            return rows

        def record_materialize(session: Session, *args, **kwargs):
            result = original_materialize(session, *args, **kwargs)
            metrics["identity_peaks"].append(len(session.identity_map))
            return result

        def collect_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                metrics["selects"].append(" ".join(statement.upper().split()))

        event.listen(engine, "before_cursor_execute", collect_sql)
        clue_allocation._bounded_raw_clues = record_bounded_raw_clues
        clue_allocation.materialize_clue_master_leads = record_materialize
        try:
            result = run_incremental_clue_materialization(
                factory,
                batch_size=1,
                raw_batch_size=1,
                lease_token=f"attempt-scale-{history_size}",
                now=_dt(6),
            )
        finally:
            clue_allocation._bounded_raw_clues = original_bounded_raw_clues
            clue_allocation.materialize_clue_master_leads = original_materialize
            event.remove(engine, "before_cursor_execute", collect_sql)

        metrics["result"] = result
        metrics["raw_loaded_rows"] = sum(metrics["raw_page_sizes"])
        metrics["identity_peak"] = max(metrics["identity_peaks"], default=0)
        engine.dispose()
        return metrics

    small = run_case(20)
    large = run_case(200)

    assert small["result"]["work_items"] == 1
    assert large["result"]["work_items"] == 1
    # The page cursor's raw objects are passed directly into the bounded
    # materializer, so the target is loaded exactly once.
    assert small["raw_loaded_rows"] == 1
    assert large["raw_loaded_rows"] == 1
    assert max(small["raw_page_sizes"]) == 1
    assert max(large["raw_page_sizes"]) == 1
    assert large["identity_peak"] <= small["identity_peak"] + 8
    assert large["identity_peak"] <= 64
    for metrics in (small, large):
        for table_name in (
            "RAW_DOUYIN_CLUES",
            "CLUE_MASTER_LEADS",
            "CLUE_SOURCE_IDENTIFIER_HISTORY",
        ):
            assert all(
                f"FROM {table_name}" not in statement
                or " WHERE " in statement
                for statement in metrics["selects"]
            )


def test_incremental_materialization_rss_delta_is_not_linear_in_unrelated_history() -> None:
    """Fresh child-process RSS during one fixed impact stays bounded at 10N history."""

    repo_root = Path(__file__).resolve().parents[1]
    child_script = r'''
import json
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import JobImpact, Base
from apps.worker import clue_allocation
from apps.worker.clue_allocation import run_incremental_clue_materialization

db_path = Path(sys.argv[1]).resolve()
engine = create_engine(
    "sqlite+pysqlite:///" + db_path.as_posix(),
    future=True,
)
factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
with factory() as ready_session:
    ready_session.execute(select(JobImpact.id).limit(1)).first()
print("READY", flush=True)
sys.stdin.readline()
original_materialize = clue_allocation.materialize_clue_master_leads

def delayed_materialize(*args, **kwargs):
    result = original_materialize(*args, **kwargs)
    # Keep the bounded page Session alive long enough for the parent sampler to
    # observe the execution-phase peak, without changing the query shape.
    time.sleep(0.20)
    return result

clue_allocation.materialize_clue_master_leads = delayed_materialize
result = run_incremental_clue_materialization(
    factory,
    batch_size=1,
    raw_batch_size=1,
    lease_token="rss-child-attempt",
)
print(json.dumps(result, sort_keys=True), flush=True)
engine.dispose()
'''

    def run_case(history_size: int) -> dict[str, int]:
        with tempfile.TemporaryDirectory(prefix="dydata-t32-rss-") as temp_dir:
            db_path = Path(temp_dir) / "fixture.sqlite"
            engine = create_engine(
                "sqlite+pysqlite:///" + db_path.as_posix(),
                future=True,
            )
            Base.metadata.create_all(engine)
            factory = sessionmaker(
                bind=engine,
                autoflush=False,
                expire_on_commit=False,
                future=True,
            )
            with factory() as seed_session:
                store, mapping = _store(
                    f"store-rss-{history_size}",
                    f"poi-rss-{history_size}",
                )
                target = _clue(
                    f"raw-rss-target-{history_size}",
                    f"clue-rss-target-{history_size}",
                    f"order-rss-target-{history_size}",
                    f"poi-rss-{history_size}",
                )
                seed_session.add_all(
                    [
                        store,
                        mapping,
                        RawDouyinOrder(
                            order_id=target.order_id,
                            order_status="fulfilled",
                            updated_at=_dt(1),
                        ),
                        target,
                    ]
                )
                for index in range(history_size):
                    lead_key = f"lead-rss-unrelated-{index}"
                    row_key = f"raw-rss-unrelated-{index}"
                    clue_id = f"clue-rss-unrelated-{index}"
                    seed_session.add(
                        ClueMasterLead(
                            lead_key=lead_key,
                            source_clue_row_key=row_key,
                            source_identity_key=f"identity-rss-unrelated-{index}",
                            canonical_clue_id=clue_id,
                            order_id=f"order-rss-unrelated-{index}",
                            raw_order_status="fulfilled",
                            normalized_order_status="fulfilled",
                            status_source="clue",
                            lifecycle_status="active",
                            pool_location="headquarters_pool",
                            first_seen_at=_dt(1),
                            last_seen_at=_dt(2),
                            last_observation_key="history",
                        )
                    )
                    seed_session.add(
                        ClueSourceIdentifierHistory(
                            identifier_history_id=f"history-rss-unrelated-{index}",
                            lead_key=lead_key,
                            source_clue_row_key=row_key,
                            identifier_type="clue_id",
                            identifier_value=clue_id,
                            first_seen_at=_dt(1),
                            last_seen_at=_dt(2),
                            is_current=True,
                        )
                    )
                seed_session.commit()
                seed_session.add(
                    JobImpact(
                        impact_key=f"impact-rss-{history_size}",
                        entity_type="clue",
                        entity_key=target.clue_row_key,
                        change_kind="upsert",
                        affected_closure_json={
                            "clue_ids": [target.clue_id],
                            "order_ids": [target.order_id],
                            "poi_ids": [mapping.poi_id],
                        },
                    )
                )
                seed_session.commit()
            engine.dispose()

            process = subprocess.Popen(
                [sys.executable, "-c", child_script, str(db_path)],
                cwd=str(repo_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                ready = process.stdout.readline().strip() if process.stdout else ""
                assert ready == "READY", process.stderr.read() if process.stderr else "child did not become ready"
                baseline = None
                for _ in range(100):
                    baseline = read_process_rss_bytes(process.pid)
                    if baseline is not None:
                        break
                    time.sleep(0.005)
                if baseline is None:
                    pytest.skip("read_process_rss_bytes is unavailable in this environment")
                assert process.stdin is not None
                process.stdin.write("\n")
                process.stdin.flush()
                peak = baseline
                deadline = time.monotonic() + 60
                while process.poll() is None:
                    rss = read_process_rss_bytes(process.pid)
                    if rss is not None:
                        peak = max(peak, rss)
                    if time.monotonic() >= deadline:
                        process.kill()
                        raise AssertionError("RSS benchmark child timed out")
                    time.sleep(0.005)
                output = process.stdout.read() if process.stdout else ""
                error = process.stderr.read() if process.stderr else ""
                assert process.returncode == 0, error or output
                payload = json.loads(output.strip().splitlines()[-1])
                return {
                    "baseline": int(baseline),
                    "peak": int(peak),
                    "delta": int(peak - baseline),
                    "work_items": int(payload["work_items"]),
                }
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)

    small = run_case(100)
    large = run_case(1000)
    print(
        "RSS fixed-impact benchmark: "
        f"100N={small['delta']} bytes, 1000N={large['delta']} bytes"
    )
    assert small["work_items"] == 1
    assert large["work_items"] == 1
    assert large["delta"] <= small["delta"] + 12 * 1024 * 1024


def test_incremental_page_does_not_reload_full_same_order_fanout(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-row raw page must keep raw/master/history fanout bounded to that page."""

    store, mapping = _store("store-page-fanout", "poi-page-fanout")
    order_id = "order-page-fanout"
    clues = []
    for index in range(5):
        clue = _clue(
            f"raw-page-fanout-{index}",
            f"clue-page-fanout-{index}",
            order_id,
            mapping.poi_id,
        )
        clue.telephone = f"138000{index:05d}"
        clues.append(clue)
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=order_id, order_status="履约中", updated_at=_dt(1)),
            *clues,
        ]
    )
    db_session.commit()
    impact = JobImpact(
        impact_key="impact-page-fanout",
        entity_type="order",
        entity_key=order_id,
        change_kind="upsert",
        affected_closure_json={
            "clue_ids": [clue.clue_id for clue in clues],
            "order_ids": [order_id],
            "poi_ids": [mapping.poi_id],
        },
    )
    db_session.add(impact)
    db_session.commit()

    raw_load_sizes: list[int] = []
    master_batch_sizes: list[int] = []
    history_batch_sizes: list[int] = []
    identity_peaks: list[int] = []
    original_bounded_raw = clue_allocation._bounded_raw_clues
    original_bounded_masters = clue_allocation._bounded_existing_masters
    original_bounded_history = clue_allocation._bounded_identifier_history
    original_materialize = clue_allocation.materialize_clue_master_leads

    def record_raw(session: Session, *args, **kwargs):
        rows = original_bounded_raw(session, *args, **kwargs)
        raw_load_sizes.append(len(rows))
        return rows

    def record_masters(session: Session, *args, **kwargs):
        rows = original_bounded_masters(session, *args, **kwargs)
        master_batch_sizes.append(len(rows))
        return rows

    def record_history(session: Session, *args, **kwargs):
        rows = original_bounded_history(session, *args, **kwargs)
        history_batch_sizes.append(len(rows))
        return rows

    def record_materialize(session: Session, *args, **kwargs):
        result = original_materialize(session, *args, **kwargs)
        identity_peaks.append(len(session.identity_map))
        return result

    monkeypatch.setattr(clue_allocation, "_bounded_raw_clues", record_raw)
    monkeypatch.setattr(clue_allocation, "_bounded_existing_masters", record_masters)
    monkeypatch.setattr(clue_allocation, "_bounded_identifier_history", record_history)
    monkeypatch.setattr(clue_allocation, "materialize_clue_master_leads", record_materialize)
    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-page-fanout",
        now=_dt(4),
    )

    assert result["work_items"] == 1
    assert result["raw_rows"] == 5
    # RED before page/context separation: materialize's inner raw query returns
    # all five rows for every one-row page, and existing masters grow by order.
    assert max(raw_load_sizes) <= 1
    assert max(master_batch_sizes, default=0) <= 1
    assert max(identity_peaks, default=0) <= 24


def test_incremental_center_phase_reads_a_fifty_row_order_once(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Center projection must not reread one order once per raw page."""

    store, mapping = _store("store-center-n2", "poi-center-n2")
    order_id = "order-center-n2"
    clues = [
        _clue(
            f"raw-center-n2-{index:03d}",
            f"clue-center-n2-{index:03d}",
            order_id,
            mapping.poi_id,
        )
        for index in range(50)
    ]
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=order_id, order_status="履约中", updated_at=_dt(1)),
            *clues,
            JobImpact(
                impact_key="impact-center-n2",
                entity_type="order",
                entity_key=order_id,
                change_kind="upsert",
                affected_closure_json={
                    "clue_ids": [clue.clue_id for clue in clues],
                    "order_ids": [order_id],
                    "poi_ids": [mapping.poi_id],
                },
            ),
        ]
    )
    db_session.commit()

    center_calls: list[set[str]] = []
    center_raw_queries: list[str] = []
    original_center = clue_allocation.refresh_clue_center_projection

    def record_center(session: Session, *args, **kwargs):
        center_calls.append(set(kwargs.get("order_ids") or set()))
        return original_center(session, *args, **kwargs)

    def record_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lower()
        if (
            "from raw_douyin_clues" in normalized
            and "order_id in" in normalized
            and "limit" not in normalized
        ):
            center_raw_queries.append(statement)

    monkeypatch.setattr(
        clue_allocation,
        "refresh_clue_center_projection",
        record_center,
    )
    event.listen(db_session.get_bind(), "before_cursor_execute", record_sql)
    try:
        result = run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-center-n2",
            now=_dt(4),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record_sql)

    assert result["work_items"] == 1
    assert result["raw_rows"] == 50
    assert result["center_orders"] == 1
    assert center_calls == [{order_id}]
    assert len(center_raw_queries) == 1


def test_incremental_center_phase_deduplicates_same_order_across_fifty_impacts(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cycle with many clue impacts must center one affected order once."""

    store, mapping = _store("store-center-cycle", "poi-center-cycle")
    order_id = "order-center-cycle"
    clues = [
        _clue(
            f"raw-center-cycle-{index:03d}",
            f"clue-center-cycle-{index:03d}",
            order_id,
            mapping.poi_id,
        )
        for index in range(50)
    ]
    impacts = [
        JobImpact(
            impact_key=f"impact-center-cycle-{index:03d}",
            entity_type="clue",
            entity_key=clue.clue_row_key,
            change_kind="upsert",
            affected_closure_json={
                "clue_ids": [clue.clue_id],
                "order_ids": [order_id],
                "poi_ids": [mapping.poi_id],
            },
        )
        for index, clue in enumerate(clues)
    ]
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=order_id, order_status="履约中", updated_at=_dt(1)),
            *clues,
            *impacts,
        ]
    )
    db_session.commit()

    center_calls: list[set[str]] = []
    center_raw_queries: list[str] = []
    center_active = False
    raw_page_sizes: list[int] = []
    master_page_sizes: list[int] = []
    original_center = clue_allocation.refresh_clue_center_projection
    original_raw = clue_allocation._bounded_raw_clues
    original_materialize = clue_allocation.materialize_clue_master_leads

    def record_raw(session: Session, *args, **kwargs):
        rows = original_raw(session, *args, **kwargs)
        raw_page_sizes.append(len(rows))
        return rows

    def record_materialize(session: Session, *args, **kwargs):
        master_page_sizes.append(len(kwargs.get("raw_page_clues") or []))
        return original_materialize(session, *args, **kwargs)

    def record_center(session: Session, *args, **kwargs):
        nonlocal center_active
        center_calls.append(set(kwargs.get("order_ids") or set()))
        center_active = True
        try:
            return original_center(session, *args, **kwargs)
        finally:
            center_active = False

    def record_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lower()
        if center_active and "from raw_douyin_clues" in normalized and "order_id in" in normalized:
            center_raw_queries.append(normalized)

    monkeypatch.setattr(
        clue_allocation,
        "refresh_clue_center_projection",
        record_center,
    )
    monkeypatch.setattr(clue_allocation, "_bounded_raw_clues", record_raw)
    monkeypatch.setattr(clue_allocation, "materialize_clue_master_leads", record_materialize)
    event.listen(db_session.get_bind(), "before_cursor_execute", record_sql)
    try:
        result = run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            raw_batch_size=50,
            lease_token="attempt-center-cycle",
            now=_dt(4),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record_sql)

    assert result["work_items"] == 50
    assert sum(raw_page_sizes) == 50
    assert sum(master_page_sizes) == 50
    assert result["center_orders"] == 1
    assert center_calls == [{order_id}]
    assert len(center_raw_queries) == 1


def test_incremental_cycle_target_markers_allow_a_new_observation_to_reopen_the_cycle(
    db_session: Session,
) -> None:
    """A later impact gets a new cycle target set instead of being skipped."""

    store, mapping = _store("store-cycle-reopen", "poi-cycle-reopen")
    order_id = "order-cycle-reopen"
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=order_id, order_status="履约中", updated_at=_dt(1)),
        ]
    )
    upsert_raw_clue(
        db_session,
        "raw-cycle-reopen",
        clue_id="clue-cycle-reopen-old",
        order_id=order_id,
        order_status="\u5c65\u7ea6\u4e2d",
        telephone="13800000001",
        follow_poi_id=mapping.poi_id,
        fetched_at=_dt(1),
        imported_at=_dt(1),
        updated_at=_dt(1),
        raw_payload={"version": "old"},
        source_observed_at=_dt(1),
        observation_key="old",
    )
    db_session.commit()

    first = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-cycle-reopen-1",
        now=_dt(2),
    )
    assert first["raw_rows"] == 1
    assert first["center_orders"] == 1
    checkpoint_one = db_session.get(JobImpactWatermark, "clue_materialization")
    assert checkpoint_one is not None
    cycle_one = checkpoint_one.cycle_id
    assert db_session.scalar(
        select(func.count()).select_from(ClueMaterializationTarget).where(
            ClueMaterializationTarget.scope == "clue_materialization",
            ClueMaterializationTarget.cycle_id == cycle_one,
        )
    ) == 2

    upsert_raw_clue(
        db_session,
        "raw-cycle-reopen",
        clue_id="clue-cycle-reopen-new",
        order_id=order_id,
        order_status="\u5c65\u7ea6\u4e2d",
        telephone="13900000002",
        follow_poi_id=mapping.poi_id,
        fetched_at=_dt(3),
        imported_at=_dt(3),
        updated_at=_dt(3),
        raw_payload={"version": "new"},
        source_observed_at=_dt(3),
        observation_key="new",
    )
    db_session.commit()

    second = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-cycle-reopen-2",
        now=_dt(4),
    )
    assert second["raw_rows"] == 1
    assert second["center_orders"] == 1
    db_session.expire_all()
    checkpoint_two = db_session.get(JobImpactWatermark, "clue_materialization")
    assert checkpoint_two is not None
    assert checkpoint_two.cycle_id != cycle_one
    master = db_session.scalar(
        select(ClueMasterLead).where(ClueMasterLead.order_id == order_id)
    )
    assert master is not None
    assert master.canonical_clue_id == "clue-cycle-reopen-new"
    center = db_session.get(ClueCenterOrder, order_id)
    assert center is not None
    assert center.canonical_clue_id == "clue-cycle-reopen-new"

    replay = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-cycle-reopen-3",
        now=_dt(5),
    )
    assert replay["raw_rows"] == 0
    assert replay["center_orders"] == 0


def test_incremental_identifier_collision_is_bounded_and_fail_closed(
    db_session: Session,
) -> None:
    """A shared clue id across many leads must not choose an arbitrary lead."""

    store, mapping = _store("store-identifier-collision", "poi-identifier-collision")
    old_leads = [
        ClueMasterLead(
            lead_key=f"lead-identifier-collision-{index:04d}",
            source_clue_row_key=f"raw-identifier-collision-{index:04d}",
            source_identity_key=f"identity-identifier-collision-{index:04d}",
            canonical_clue_id=f"clue-old-{index:04d}",
            order_id=f"order-old-{index:04d}",
            normalized_order_status="active",
            lifecycle_status="active",
            allocation_state="pending_allocation",
        )
        for index in range(5000)
    ]
    old_history = [
        ClueSourceIdentifierHistory(
            identifier_history_id=f"history-identifier-collision-{index:04d}",
            lead_key=lead.lead_key,
            source_clue_row_key=lead.source_clue_row_key,
            identifier_type="clue_id",
            identifier_value="shared-id",
            first_seen_at=_dt(1),
            last_seen_at=_dt(1),
            is_current=True,
        )
        for index, lead in enumerate(old_leads)
    ]
    raw = _clue("raw-identifier-collision-new", "shared-id", "order-identifier-collision-new", mapping.poi_id)
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(
                order_id=raw.order_id,
                order_status="201",
                updated_at=_dt(2),
            ),
            *old_leads,
            *old_history,
            raw,
        ]
    )
    db_session.commit()

    before_lead_keys = set(
        db_session.scalars(select(ClueMasterLead.lead_key)).all()
    )
    result = materialize_clue_master_leads(
        db_session,
        now=_dt(3),
        raw_page_clues=[raw],
        raw_clue_row_keys={raw.clue_row_key},
        clue_ids={raw.clue_id},
        order_ids={raw.order_id},
        poi_ids={mapping.poi_id},
        source_identity_keys={clue_allocation._source_identity_key(raw)},
        existing_clue_ids={raw.clue_id},
        existing_order_ids={raw.order_id},
        existing_poi_ids={mapping.poi_id},
        existing_source_identity_keys={clue_allocation._source_identity_key(raw)},
    )

    assert result["master_leads"] == 0
    assert set(db_session.scalars(select(ClueMasterLead.lead_key)).all()) == before_lead_keys
    issues = list(
        db_session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_type == "clue_identifier_collision"
            )
        )
    )
    assert len(issues) == 1
    assert issues[0].raw_context_json["distinct_lead_count"] >= 2
    assert "shared-id" not in str(issues[0].raw_context_json)


@pytest.mark.parametrize("strong_match", ["source", "order", "identity"])
def test_incremental_identifier_collision_yields_to_stronger_match(
    db_session: Session,
    strong_match: str,
) -> None:
    """A collision never overrides an exact source/order/identity match."""

    store, mapping = _store(
        f"store-identifier-strong-{strong_match}",
        f"poi-identifier-strong-{strong_match}",
    )
    raw = _clue(
        f"raw-identifier-strong-{strong_match}",
        "shared-strong-id",
        (
            f"order-identifier-strong-{strong_match}"
            if strong_match == "order"
            else None
        ),
        mapping.poi_id,
    )
    raw_source_identity = clue_allocation._source_identity_key(raw)
    old_lead = ClueMasterLead(
        lead_key=f"lead-identifier-strong-{strong_match}",
        source_clue_row_key=(
            raw.clue_row_key
            if strong_match == "source"
            else f"raw-identifier-strong-old-{strong_match}"
        ),
        source_identity_key=(
            raw_source_identity
            if strong_match == "identity"
            else f"identity-identifier-strong-old-{strong_match}"
        ),
        canonical_clue_id=f"clue-identifier-strong-old-{strong_match}",
        order_id=raw.order_id,
        normalized_order_status="active",
        lifecycle_status="active",
        allocation_state="pending_allocation",
    )
    other_lead = ClueMasterLead(
        lead_key=f"lead-identifier-strong-other-{strong_match}",
        source_clue_row_key=f"raw-identifier-strong-other-{strong_match}",
        source_identity_key=f"identity-identifier-strong-other-{strong_match}",
        canonical_clue_id=f"clue-identifier-strong-other-{strong_match}",
        order_id=f"order-identifier-strong-other-{strong_match}",
        normalized_order_status="active",
        lifecycle_status="active",
        allocation_state="pending_allocation",
    )
    histories = [
        ClueSourceIdentifierHistory(
            identifier_history_id=f"history-identifier-strong-old-{strong_match}",
            lead_key=old_lead.lead_key,
            source_clue_row_key=old_lead.source_clue_row_key,
            identifier_type="clue_id",
            identifier_value=raw.clue_id,
            first_seen_at=_dt(1),
            last_seen_at=_dt(1),
            is_current=True,
        ),
        ClueSourceIdentifierHistory(
            identifier_history_id=f"history-identifier-strong-other-{strong_match}",
            lead_key=other_lead.lead_key,
            source_clue_row_key=other_lead.source_clue_row_key,
            identifier_type="clue_id",
            identifier_value=raw.clue_id,
            first_seen_at=_dt(1),
            last_seen_at=_dt(1),
            is_current=True,
        ),
    ]
    db_session.add_all(
        [
            store,
            mapping,
            old_lead,
            other_lead,
            *histories,
            raw,
        ]
    )
    if raw.order_id:
        db_session.add(
            RawDouyinOrder(order_id=raw.order_id, order_status="201", updated_at=_dt(2))
        )
    db_session.commit()

    result = materialize_clue_master_leads(
        db_session,
        now=_dt(3),
        raw_page_clues=[raw],
        raw_clue_row_keys={raw.clue_row_key},
        clue_ids={raw.clue_id},
        order_ids={raw.order_id},
        poi_ids={mapping.poi_id},
        source_identity_keys={raw_source_identity},
        existing_clue_ids={raw.clue_id},
        existing_order_ids={raw.order_id},
        existing_poi_ids={mapping.poi_id},
        existing_source_identity_keys={raw_source_identity},
    )

    assert result["master_leads"] == 1
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 2
    assert db_session.scalar(
        select(func.count()).select_from(DataQualityIssue).where(
            DataQualityIssue.issue_type == "clue_identifier_collision"
        )
    ) == 0
    assert db_session.get(ClueMasterLead, old_lead.lead_key).canonical_clue_id == raw.clue_id


def test_incremental_identifier_reverse_unique_lead_is_bounded_and_type_scoped(
    db_session: Session,
) -> None:
    """One distinct lead may be reused; a different identifier type is isolated."""

    store, mapping = _store("store-identifier-unique", "poi-identifier-unique")
    lead = ClueMasterLead(
        lead_key="lead-identifier-unique",
        source_clue_row_key="raw-identifier-unique-old",
        source_identity_key="identity-identifier-unique-old",
        canonical_clue_id="clue-identifier-unique-old",
        order_id=None,
        normalized_order_status="active",
        lifecycle_status="active",
        allocation_state="pending_allocation",
    )
    other_lead = ClueMasterLead(
        lead_key="lead-identifier-unique-other-type",
        source_clue_row_key="raw-identifier-unique-other",
        source_identity_key="identity-identifier-unique-other",
        canonical_clue_id="clue-identifier-unique-other",
        order_id=None,
        normalized_order_status="active",
        lifecycle_status="active",
        allocation_state="pending_allocation",
    )
    history = [
        ClueSourceIdentifierHistory(
            identifier_history_id=f"history-identifier-unique-{index:04d}",
            lead_key=lead.lead_key,
            source_clue_row_key=f"raw-identifier-unique-history-{index:04d}",
            identifier_type="clue_id",
            identifier_value="shared-unique-id",
            first_seen_at=_dt(1),
            last_seen_at=_dt(1),
            is_current=False,
        )
        for index in range(5000)
    ]
    history.append(
        ClueSourceIdentifierHistory(
            identifier_history_id="history-identifier-unique-other-type",
            lead_key=other_lead.lead_key,
            source_clue_row_key="raw-identifier-unique-other",
            identifier_type="source_identity_key",
            identifier_value="shared-unique-id",
            first_seen_at=_dt(1),
            last_seen_at=_dt(1),
            is_current=True,
        )
    )
    raw = _clue("raw-identifier-unique-new", "shared-unique-id", "order-identifier-unique-new", mapping.poi_id)
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=raw.order_id, order_status="201", updated_at=_dt(2)),
            lead,
            other_lead,
            *history,
            raw,
        ]
    )
    db_session.commit()

    identifiers = {("clue_id", "shared-unique-id")}
    history_rows = clue_allocation._bounded_identifier_history(
        db_session,
        raw_clue_row_keys={raw.clue_row_key},
        candidate_identifiers=identifiers,
    )
    assert len(history_rows) == 1
    assert history_rows[0].lead_key == lead.lead_key
    assert not db_session.info.get("clue_identifier_conflicts")
    masters = clue_allocation._bounded_existing_masters(
        db_session,
        [raw],
        order_ids={raw.order_id},
        clue_ids={raw.clue_id},
        poi_ids={mapping.poi_id},
        source_identity_keys={clue_allocation._source_identity_key(raw)},
    )
    assert {master.lead_key for master in masters} == {lead.lead_key}


def test_incremental_identifier_candidate_in_avoids_expression_depth_for_1000_values(
    db_session: Session,
) -> None:
    """A 1000-value page compiles as grouped IN predicates, not 1000 ORs."""

    candidates = {
        ("clue_id", f"clue-page-{index:04d}")
        for index in range(1000)
    }
    rows = clue_allocation._bounded_identifier_history(
        db_session,
        raw_clue_row_keys={"raw-page-1000"},
        candidate_identifiers=candidates,
    )
    assert rows == []


def test_incremental_anchor_issue_lookup_is_bounded_for_1000_leads(
    db_session: Session,
) -> None:
    """Anchor DQI lookup must not build a lead-wide LIKE OR expression."""

    lead_keys = {f"lead-anchor-bounded-{index:04d}" for index in range(1000)}
    assert clue_allocation._bounded_anchor_issue_ids(db_session, lead_keys) == []


def test_incremental_page_does_not_reload_all_masters_for_poi_mapping_fanout(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A POI impact uses page row identity, not every historical master at that POI."""

    store, mapping = _store("store-poi-fanout", "poi-poi-fanout")
    clues: list[RawDouyinClue] = []
    orders: list[RawDouyinOrder] = []
    for index in range(5):
        order_id = f"order-poi-fanout-{index}"
        clue = _clue(
            f"raw-poi-fanout-{index}",
            f"clue-poi-fanout-{index}",
            order_id,
            mapping.poi_id,
        )
        clue.telephone = f"139000{index:05d}"
        clues.append(clue)
        orders.append(
            RawDouyinOrder(order_id=order_id, order_status="fulfilled", updated_at=_dt(1))
        )
    db_session.add_all([store, mapping, *orders, *clues])
    db_session.commit()
    impact = JobImpact(
        impact_key="impact-poi-fanout",
        entity_type="store_poi_mapping",
        entity_key=mapping.poi_id,
        change_kind="upsert",
        affected_closure_json={
            "clue_ids": [clue.clue_id for clue in clues],
            "order_ids": [clue.order_id for clue in clues],
            "poi_ids": [mapping.poi_id],
        },
    )
    db_session.add(impact)
    db_session.commit()

    raw_load_sizes: list[int] = []
    master_batch_sizes: list[int] = []
    identity_peaks: list[int] = []
    original_bounded_raw = clue_allocation._bounded_raw_clues
    original_bounded_masters = clue_allocation._bounded_existing_masters
    original_materialize = clue_allocation.materialize_clue_master_leads

    def record_raw(session: Session, *args, **kwargs):
        rows = original_bounded_raw(session, *args, **kwargs)
        raw_load_sizes.append(len(rows))
        return rows

    def record_masters(session: Session, *args, **kwargs):
        rows = original_bounded_masters(session, *args, **kwargs)
        master_batch_sizes.append(len(rows))
        return rows

    def record_materialize(session: Session, *args, **kwargs):
        result = original_materialize(session, *args, **kwargs)
        identity_peaks.append(len(session.identity_map))
        return result

    monkeypatch.setattr(clue_allocation, "_bounded_raw_clues", record_raw)
    monkeypatch.setattr(clue_allocation, "_bounded_existing_masters", record_masters)
    monkeypatch.setattr(clue_allocation, "materialize_clue_master_leads", record_materialize)
    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-poi-fanout",
        now=_dt(4),
    )

    assert result["work_items"] == 1
    assert result["raw_rows"] == 5
    assert max(raw_load_sizes) <= 1
    assert max(master_batch_sizes, default=0) <= 1
    assert max(identity_peaks, default=0) <= 24


def test_verification_projection_delta_flushes_cross_order_fanout_in_small_batches(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify impacts must not hand an unbounded order set to both projections."""

    order_count = 250
    db_session.add_all(
        [
            JobImpact(
                impact_key=f"impact-verify-fanout-{index}",
                entity_type="verify",
                entity_key=f"verify-{index}",
                change_kind="upsert",
                affected_closure_json={"order_ids": [f"order-verify-fanout-{index}"]},
                source_run_id="job-verify-fanout",
            )
            for index in range(order_count)
        ]
    )
    db_session.commit()

    materialize_batches: list[set[str]] = []
    center_batches: list[set[str]] = []

    def record_materialize(_session: Session, **kwargs):
        materialize_batches.append(set(kwargs.get("order_ids") or set()))
        return {"master_leads": 0, "closed_leads": 0, "headquarters_pool": 0}

    def record_center(_session: Session, **kwargs):
        center_batches.append(set(kwargs.get("order_ids") or set()))
        return {"eligible_orders": len(kwargs.get("order_ids") or set()), "assignment_rounds": 0}

    monkeypatch.setattr(daily_task, "materialize_clue_master_leads", record_materialize)
    monkeypatch.setattr(
        daily_task,
        "refresh_clue_center_projection",
        record_center,
    )

    result = daily_task._run_verification_projection_delta(
        db_session,
        SimpleNamespace(job_id="job-verify-fanout"),
    )

    assert result["impact_count"] == order_count
    assert result["order_count"] == order_count
    assert materialize_batches == center_batches
    assert sum(len(batch) for batch in materialize_batches) == order_count
    assert max(map(len, materialize_batches)) <= 64


def test_verification_projection_delta_splits_one_impact_large_closure(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single impact carrying 250 orders is partitioned before projection."""

    order_ids = [f"order-single-impact-{index}" for index in range(250)]
    db_session.add(
        JobImpact(
            impact_key="impact-single-large-closure",
            entity_type="verify",
            entity_key="verify-single-large-closure",
            change_kind="upsert",
            affected_closure_json={"order_ids": order_ids},
            source_run_id="job-single-large-closure",
        )
    )
    db_session.commit()

    materialize_batches: list[set[str]] = []
    center_batches: list[set[str]] = []
    monkeypatch.setattr(
        daily_task,
        "materialize_clue_master_leads",
        lambda _session, **kwargs: (
            materialize_batches.append(set(kwargs.get("order_ids") or set()))
            or {"master_leads": 0, "closed_leads": 0, "headquarters_pool": 0}
        ),
    )
    monkeypatch.setattr(
        daily_task,
        "refresh_clue_center_projection",
        lambda _session, **kwargs: (
            center_batches.append(set(kwargs.get("order_ids") or set()))
            or {"eligible_orders": len(kwargs.get("order_ids") or set()), "assignment_rounds": 0}
        ),
    )

    result = daily_task._run_verification_projection_delta(
        db_session,
        SimpleNamespace(job_id="job-single-large-closure"),
    )

    assert result["impact_count"] == 1
    assert result["order_count"] == 250
    assert materialize_batches == center_batches
    assert max(map(len, materialize_batches)) <= 64


def test_incremental_identifier_history_keeps_one_current_value_after_rename(
    db_session: Session,
) -> None:
    """A page must load the old current identifier before promoting the new one."""

    store, mapping = _store("store-history-rename", "poi-history-rename")
    raw = _clue("raw-history-rename", "clue-history-old", "order-history-rename", mapping.poi_id)
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=raw.order_id, order_status="履约中", updated_at=_dt(1)),
            raw,
        ]
    )
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(2))
    db_session.commit()

    raw.clue_id = "clue-history-new"
    raw.source_observed_at = _dt(3)
    raw.observation_key = "history-rename-new"
    raw.updated_at = _dt(3)
    db_session.commit()
    materialize_clue_master_leads(
        db_session,
        now=_dt(4),
        raw_page_clues=[raw],
        raw_clue_row_keys={raw.clue_row_key},
        clue_ids={raw.clue_id},
        order_ids={raw.order_id},
        poi_ids={mapping.poi_id},
        source_identity_keys={clue_allocation._source_identity_key(raw)},
        existing_clue_ids={raw.clue_id},
        existing_order_ids={raw.order_id},
        existing_poi_ids={mapping.poi_id},
        existing_source_identity_keys={clue_allocation._source_identity_key(raw)},
    )

    current_values = list(
        db_session.scalars(
            select(ClueSourceIdentifierHistory.identifier_value).where(
                ClueSourceIdentifierHistory.source_clue_row_key == raw.clue_row_key,
                ClueSourceIdentifierHistory.identifier_type == "clue_id",
                ClueSourceIdentifierHistory.is_current.is_(True),
            )
        )
    )
    assert current_values == ["clue-history-new"]


def test_incremental_identifier_history_reads_page_candidates_not_all_lead_history(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A five-thousand-row legacy history must not enter a one-row page session."""

    store, mapping = _store("store-history-bounded", "poi-history-bounded")
    raw = _clue("raw-history-bounded", "clue-history-bounded", "order-history-bounded", mapping.poi_id)
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=raw.order_id, order_status="201", updated_at=_dt(1)),
            raw,
        ]
    )
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(2))
    db_session.commit()
    lead = db_session.scalar(select(ClueMasterLead).where(ClueMasterLead.order_id == raw.order_id))
    assert lead is not None
    db_session.add_all(
        [
            ClueSourceIdentifierHistory(
                identifier_history_id=f"legacy-history-{index}",
                lead_key=lead.lead_key,
                source_clue_row_key=f"legacy-row-{index}",
                identifier_type="clue_id",
                identifier_value=f"legacy-clue-{index}",
                first_seen_at=_dt(1),
                last_seen_at=_dt(1),
                is_current=False,
                created_at=_dt(1),
                updated_at=_dt(1),
            )
            for index in range(5000)
        ]
    )
    db_session.commit()

    history_sizes: list[int] = []
    original_history = clue_allocation._bounded_identifier_history

    def record_history(session: Session, *args, **kwargs):
        rows = original_history(session, *args, **kwargs)
        history_sizes.append(len(rows))
        return rows

    monkeypatch.setattr(clue_allocation, "_bounded_identifier_history", record_history)
    raw = db_session.get(RawDouyinClue, raw.clue_row_key)
    assert raw is not None
    materialize_clue_master_leads(
        db_session,
        now=_dt(3),
        raw_page_clues=[raw],
        raw_clue_row_keys={raw.clue_row_key},
        clue_ids={raw.clue_id},
        order_ids={raw.order_id},
        poi_ids={mapping.poi_id},
        source_identity_keys={clue_allocation._source_identity_key(raw)},
        existing_clue_ids={raw.clue_id},
        existing_order_ids={raw.order_id},
        existing_poi_ids={mapping.poi_id},
        existing_source_identity_keys={clue_allocation._source_identity_key(raw)},
    )

    assert history_sizes
    assert max(history_sizes) <= 4


def test_incremental_status_event_dedup_checks_exact_id_not_all_lead_events(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status deduplication must use the deterministic event primary key."""

    store, mapping = _store("store-event-bounded", "poi-event-bounded")
    raw = _clue("raw-event-bounded", "clue-event-bounded", "order-event-bounded", mapping.poi_id)
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=raw.order_id, order_status="201", updated_at=_dt(1)),
            raw,
        ]
    )
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(2))
    db_session.commit()
    lead = db_session.scalar(select(ClueMasterLead).where(ClueMasterLead.order_id == raw.order_id))
    assert lead is not None
    db_session.add_all(
        [
            ClueOrderStatusEvent(
                event_id=f"status-history-{index}",
                event_key=f"status-history-key-{index}",
                lead_key=lead.lead_key,
                order_id=raw.order_id,
                raw_status="201",
                normalized_status="active",
                status_source="clue",
                observed_at=_dt(1),
                created_at=_dt(1),
            )
            for index in range(5000)
        ]
    )
    db_session.commit()

    raw = db_session.get(RawDouyinClue, raw.clue_row_key)
    assert raw is not None
    raw_order = db_session.scalar(
        select(RawDouyinOrder).where(RawDouyinOrder.order_id == raw.order_id)
    )
    assert raw_order is not None
    raw.order_status = "fulfilled"
    raw_order.order_status = "fulfilled"
    raw.source_observed_at = _dt(3)
    raw.observation_key = "event-bounded-new"
    raw.updated_at = _dt(3)
    db_session.commit()
    status_sql: list[str] = []

    def record_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lower()
        if "clue_order_status_events" in normalized:
            status_sql.append(normalized)

    event.listen(db_session.get_bind(), "before_cursor_execute", record_sql)
    try:
        materialize_clue_master_leads(
            db_session,
            now=_dt(3),
            raw_page_clues=[raw],
            raw_clue_row_keys={raw.clue_row_key},
            clue_ids={raw.clue_id},
            order_ids={raw.order_id},
            poi_ids={mapping.poi_id},
            source_identity_keys={clue_allocation._source_identity_key(raw)},
            existing_clue_ids={raw.clue_id},
            existing_order_ids={raw.order_id},
            existing_poi_ids={mapping.poi_id},
            existing_source_identity_keys={clue_allocation._source_identity_key(raw)},
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record_sql)

    select_status_sql = [statement for statement in status_sql if statement.lstrip().startswith("select")]
    assert select_status_sql
    assert all("where clue_order_status_events.lead_key" not in statement for statement in select_status_sql)
    assert any("where clue_order_status_events.event_id" in statement for statement in select_status_sql)


def test_verified_at_by_order_aggregates_high_cardinality_details(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification status needs only the earliest timestamp per order."""

    order_id = "order-verified-at-bounded"
    db_session.add_all(
        [
            SettlementOrderDetail(
                coupon_id=f"coupon-verified-at-{index}",
                order_id=order_id,
                product_type="test",
                is_verified=True,
                verify_store_id="store-verified",
                verify_store_name="Verified",
                verify_time=_dt(10) - timedelta(minutes=index),
            )
            for index in range(5000)
        ]
    )
    db_session.commit()

    execute_row_counts: list[int] = []
    original_execute = db_session.execute

    class CountingResult:
        def __init__(self, result):
            self._result = result

        def all(self):
            rows = self._result.all()
            execute_row_counts.append(len(rows))
            return rows

        def __getattr__(self, name):
            return getattr(self._result, name)

    def record_execute(statement, *args, **kwargs):
        result = original_execute(statement, *args, **kwargs)
        if "settlement_order_details" in str(statement).lower():
            return CountingResult(result)
        return result

    monkeypatch.setattr(db_session, "execute", record_execute)
    result = _verified_at_by_order(db_session, {order_id})

    assert result[order_id] == _dt(10) - timedelta(minutes=4999)
    assert execute_row_counts == [1]


def test_center_verification_rows_bounded_for_high_cardinality_order(
    db_session: Session,
) -> None:
    """Center selection must not retain every verified detail for one order."""

    order_id = "order-center-verification-bounded"
    db_session.add_all(
        [
            SettlementOrderDetail(
                coupon_id=f"coupon-center-verification-{index}",
                order_id=order_id,
                product_type="test",
                is_verified=True,
                verify_store_id="store-center-verification",
                verify_store_name="Verified",
                verify_time=_dt(10) - timedelta(minutes=index),
            )
            for index in range(5000)
        ]
    )
    db_session.commit()

    rows = _verification_rows(db_session, {order_id})

    assert len(rows[order_id]) == 1


def test_incremental_materialization_rejects_legacy_stale_observation_without_switching_current_identifier(
    db_session: Session,
) -> None:
    store, mapping = _store("store-a", "poi-a")
    db_session.add_all([store, mapping, _clue("raw-a", "clue-a", "order-a", "poi-a")])
    db_session.commit()
    raw = db_session.get(RawDouyinClue, "raw-a")
    assert raw is not None
    raw.source_observed_at = _dt(3)
    raw.observation_key = "obs-new"
    raw.updated_at = _dt(3)
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(4))
    db_session.commit()
    before_history = db_session.scalar(select(func.count()).select_from(ClueSourceIdentifierHistory))
    before_impacts = db_session.scalar(select(func.count()).select_from(JobImpact))

    raw.clue_id = "clue-old"
    raw.order_status = "已核销"
    raw.source_observed_at = _dt(2)
    raw.observation_key = "obs-old"
    raw.updated_at = _dt(2)
    raw.raw_payload = {"clue_id": "clue-old"}
    impact = JobImpact(
        impact_key="manual-stale-impact",
        entity_type="clue",
        entity_key="raw-a",
        change_kind="update",
        old_values_json={"clue_id": "clue-b", "order_id": "order-a"},
        new_values_json={"clue_id": "clue-old", "order_id": "order-a"},
        affected_closure_json={
            "clue_ids": ["raw-a", "clue-b", "clue-old"],
            "order_ids": ["order-a"],
            "poi_ids": ["poi-a"],
        },
    )
    db_session.add(impact)
    db_session.commit()
    db_session.add(
        ClueMaterializationWorkItem(
            scope="clue_materialization",
            impact_id=impact.id,
            entity_type="clue",
            entity_key="raw-a",
        )
    )
    db_session.commit()

    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        lease_token="attempt-stale",
        now=_dt(5),
    )

    assert result["work_items"] == 1
    assert db_session.scalar(select(func.count()).select_from(JobImpact)) == before_impacts + 1
    assert db_session.scalar(select(func.count()).select_from(ClueSourceIdentifierHistory)) == before_history + 1
    master = db_session.scalar(select(ClueMasterLead))
    assert master is not None
    assert master.canonical_clue_id == "clue-a"
    history = db_session.scalars(
        select(ClueSourceIdentifierHistory).where(
            ClueSourceIdentifierHistory.lead_key == master.lead_key,
            ClueSourceIdentifierHistory.identifier_type == "clue_id",
        )
    ).all()
    assert {row.identifier_value for row in history} >= {"clue-a", "clue-old"}
    stale = next(row for row in history if row.identifier_value == "clue-old")
    assert stale.is_current is False


def test_stale_replay_of_current_identifier_does_not_rewind_payload_hash(
    db_session: Session,
) -> None:
    store, mapping = _store("store-stale-hash", "poi-stale-hash")
    raw = _clue("raw-stale-hash", "clue-stale-hash", "order-stale-hash", "poi-stale-hash")
    raw.source_observed_at = _dt(4)
    raw.observation_key = "current"
    raw.raw_payload = {"version": "current"}
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(
                order_id="order-stale-hash",
                order_status="fulfilled",
                updated_at=_dt(1),
            ),
            raw,
        ]
    )
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(5))
    db_session.commit()
    master = db_session.scalar(select(ClueMasterLead))
    assert master is not None
    current_history = db_session.scalar(
        select(ClueSourceIdentifierHistory).where(
            ClueSourceIdentifierHistory.lead_key == master.lead_key,
            ClueSourceIdentifierHistory.identifier_type == "clue_id",
            ClueSourceIdentifierHistory.identifier_value == "clue-stale-hash",
        )
    )
    assert current_history is not None
    current_payload_hash = current_history.source_payload_hash

    raw.source_observed_at = _dt(3)
    raw.observation_key = "older"
    raw.raw_payload = {"version": "stale"}
    impact = JobImpact(
        impact_key="stale-current-identifier-impact",
        entity_type="clue",
        entity_key=raw.clue_row_key,
        change_kind="update",
        affected_closure_json={
            "clue_ids": [raw.clue_id],
            "order_ids": [raw.order_id],
            "poi_ids": [mapping.poi_id],
        },
    )
    db_session.add(impact)
    db_session.commit()
    db_session.add(
        ClueMaterializationWorkItem(
            scope="clue_materialization",
            impact_id=impact.id,
            entity_type="clue",
            entity_key=raw.clue_row_key,
        )
    )
    db_session.commit()

    run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        lease_token="attempt-stale-current-hash",
        now=_dt(6),
    )

    db_session.expire_all()
    current_history = db_session.scalar(
        select(ClueSourceIdentifierHistory).where(
            ClueSourceIdentifierHistory.lead_key == master.lead_key,
            ClueSourceIdentifierHistory.identifier_type == "clue_id",
            ClueSourceIdentifierHistory.identifier_value == "clue-stale-hash",
        )
    )
    assert current_history is not None
    assert current_history.is_current is True
    assert current_history.source_payload_hash == current_payload_hash


def _parity_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _seed_parity_fixture(session: Session) -> list[RawDouyinClue]:
    store, mapping = _store("store-parity", "poi-parity")
    orders = [
        RawDouyinOrder(order_id="order-parity-active", order_status="fulfilled", updated_at=_dt(1)),
        RawDouyinOrder(order_id="order-parity-headquarters", order_status="fulfilled", updated_at=_dt(1)),
    ]
    clues = [
        _clue("raw-parity-active", "clue-parity-active", "order-parity-active", "poi-parity"),
        _clue(
            "raw-parity-headquarters",
            "clue-parity-headquarters",
            "order-parity-headquarters",
            "poi-parity-missing",
        ),
    ]
    for index, raw_clue in enumerate(clues):
        raw_clue.source_observed_at = _dt(2)
        raw_clue.observation_key = f"parity-{index}"
        raw_clue.raw_payload = {
            "clue_id": raw_clue.clue_id,
            "observation_key": raw_clue.observation_key,
        }
    session.add_all([store, mapping, *orders, *clues])
    session.commit()
    return clues


def _parity_checksum(session: Session) -> str:
    def rows(model, fields: tuple[str, ...], *, normalize_json: bool = False):
        output = []
        for row in session.scalars(select(model).order_by(getattr(model, fields[0]))):
            values = []
            for field in fields:
                value = getattr(row, field)
                if normalize_json and isinstance(value, list):
                    value = sorted(value)
                values.append(value)
            output.append(values)
        return output

    snapshot = {
        "master": rows(
            ClueMasterLead,
            (
                "lead_key",
                "source_clue_row_key",
                "source_identity_key",
                "canonical_clue_id",
                "order_id",
                "normalized_order_status",
                "lifecycle_status",
                "pool_location",
                "allocation_state",
                "anchor_poi_id",
                "anchor_store_id",
                "last_observation_key",
            ),
        ),
        "identifier_history": rows(
            ClueSourceIdentifierHistory,
            (
                "identifier_history_id",
                "lead_key",
                "source_clue_row_key",
                "identifier_type",
                "identifier_value",
                "source_payload_hash",
                "is_current",
            ),
        ),
        "status_events": rows(
            ClueOrderStatusEvent,
            (
                "event_id",
                "event_key",
                "lead_key",
                "order_id",
                "normalized_status",
                "status_source",
                "observed_at",
            ),
        ),
        "data_quality": rows(
            DataQualityIssue,
            ("issue_id", "issue_type", "order_id", "severity", "message"),
        ),
        "headquarters": rows(
            ClueHeadquartersPoolEntry,
            ("headquarters_pool_entry_id", "lead_key", "status", "reason", "source_snapshot"),
        ),
        "assignment_rounds": rows(
            ClueAssignmentRound,
            ("assignment_round_id", "lead_key", "order_id", "round_no", "round_status"),
        ),
        "center": rows(
            ClueCenterOrder,
            (
                "order_id",
                "source_clue_ids",
                "source_clue_count",
                "canonical_clue_id",
                "lead_status",
                "current_round_status",
                "assigned_store_id",
            ),
            normalize_json=True,
        ),
    }
    return sha256(repr(snapshot).encode("utf-8")).hexdigest()


def test_legacy_full_and_incremental_fixture_have_equal_projection_checksum() -> None:
    legacy_factory = _parity_factory()
    incremental_factory = _parity_factory()
    with legacy_factory() as legacy, incremental_factory() as incremental:
        _seed_parity_fixture(legacy)
        incremental_clues = _seed_parity_fixture(incremental)
        materialize_clue_master_leads(legacy, now=_dt(3))
        rebuild_clue_center(legacy, now=_dt(3), phone_plain_resolver=lambda values: {value: value for value in values})
        legacy.commit()

        impact = JobImpact(
            impact_key="parity-impact",
            entity_type="clue",
            entity_key=incremental_clues[0].clue_row_key,
            affected_closure_json={
                "clue_ids": [clue.clue_id for clue in incremental_clues],
                "order_ids": [clue.order_id for clue in incremental_clues],
                "poi_ids": ["poi-parity", "poi-parity-missing"],
            },
        )
        incremental.add(impact)
        incremental.commit()
        incremental.add(
            ClueMaterializationWorkItem(
                scope="clue_materialization",
                impact_id=impact.id,
                entity_type="clue",
                entity_key=incremental_clues[0].clue_row_key,
            )
        )
        incremental.commit()
        run_incremental_clue_materialization(
            lambda: incremental_factory(),
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-parity",
            now=_dt(3),
            phone_plain_resolver=lambda values: {value: value for value in values},
        )
        assert _parity_checksum(legacy) == _parity_checksum(incremental)


def test_legacy_and_incremental_old_new_projection_update_have_equal_checksum() -> None:
    """Legacy full replay and bounded replay consume the same changed source row."""

    def seed_and_materialize(session: Session) -> None:
        old_store, old_mapping = _store("store-parity-update-old", "poi-parity-update-old")
        new_store, new_mapping = _store("store-parity-update-new", "poi-parity-update-new")
        session.add_all(
            [
                old_store,
                old_mapping,
                new_store,
                new_mapping,
                RawDouyinOrder(
                    order_id="order-parity-update",
                    order_status="fulfilled",
                    updated_at=_dt(1),
                ),
            ]
        )
        upsert_raw_clue(
            session,
            "raw-parity-update",
            clue_id="clue-parity-update-old",
            order_id="order-parity-update",
            order_status="fulfilled",
            telephone="13800000011",
            follow_poi_id=old_mapping.poi_id,
            create_time_detail=_dt(1),
            fetched_at=_dt(2),
            imported_at=_dt(2),
            updated_at=_dt(2),
            raw_payload={"version": "old"},
            source_observed_at=_dt(2),
            observation_key="old",
        )
        session.commit()
        materialize_clue_master_leads(session, now=_dt(3))
        rebuild_clue_center(
            session,
            now=_dt(3),
            phone_plain_resolver=lambda values: {value: value for value in values},
        )
        session.commit()
        initial_impact = session.scalar(select(JobImpact).order_by(JobImpact.id.asc()))
        assert initial_impact is not None
        initial_work_item = session.scalar(
            select(ClueMaterializationWorkItem).where(
                ClueMaterializationWorkItem.impact_id == initial_impact.id
            )
        )
        assert initial_work_item is not None
        initial_work_item.state = "completed"
        initial_work_item.completed_at = _dt(3)
        session.commit()

    legacy_factory = _parity_factory()
    incremental_factory = _parity_factory()
    with legacy_factory() as legacy, incremental_factory() as incremental:
        seed_and_materialize(legacy)
        seed_and_materialize(incremental)

        for session in (legacy, incremental):
            upsert_raw_clue(
                session,
                "raw-parity-update",
                clue_id="clue-parity-update-new",
                order_id="order-parity-update",
                order_status="fulfilled",
                telephone="13900000022",
                follow_poi_id="poi-parity-update-new",
                create_time_detail=_dt(1),
                fetched_at=_dt(4),
                imported_at=_dt(4),
                updated_at=_dt(4),
                raw_payload={"version": "new"},
                source_observed_at=_dt(4),
                observation_key="new",
            )
            session.commit()

        materialize_clue_master_leads(legacy, now=_dt(5))
        rebuild_clue_center(
            legacy,
            now=_dt(5),
            phone_plain_resolver=lambda values: {value: value for value in values},
        )
        legacy.commit()
        run_incremental_clue_materialization(
            lambda: incremental_factory(),
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-parity-update",
            now=_dt(5),
            phone_plain_resolver=lambda values: {value: value for value in values},
        )

        assert _parity_checksum(legacy) == _parity_checksum(incremental)
        for session in (legacy, incremental):
            master = session.scalar(select(ClueMasterLead))
            assert master is not None
            assert master.canonical_clue_id == "clue-parity-update-new"
            assert master.anchor_poi_id == "poi-parity-update-new"
            history_values = {
                row.identifier_value
                for row in session.scalars(select(ClueSourceIdentifierHistory)).all()
                if row.identifier_type == "clue_id"
            }
            assert {"clue-parity-update-old", "clue-parity-update-new"} <= history_values


def test_legacy_and_incremental_order_change_closure_have_equal_conflict_checksum() -> None:
    """An order-side identity change stays quarantined identically in both paths."""

    def seed(session: Session) -> None:
        old_store, old_mapping = _store("store-parity-order-old", "poi-parity-order-old")
        new_store, new_mapping = _store("store-parity-order-new", "poi-parity-order-new")
        session.add_all(
            [
                old_store,
                old_mapping,
                new_store,
                new_mapping,
                RawDouyinOrder(
                    order_id="order-parity-order-old",
                    order_status="fulfilled",
                    updated_at=_dt(1),
                ),
                RawDouyinOrder(
                    order_id="order-parity-order-new",
                    order_status="fulfilled",
                    updated_at=_dt(4),
                ),
            ]
        )
        upsert_raw_clue(
            session,
            "raw-parity-order-change",
            clue_id="clue-parity-order-old",
            order_id="order-parity-order-old",
            order_status="fulfilled",
            telephone="13800000033",
            follow_poi_id=old_mapping.poi_id,
            create_time_detail=_dt(1),
            fetched_at=_dt(2),
            imported_at=_dt(2),
            updated_at=_dt(2),
            raw_payload={"version": "old"},
            source_observed_at=_dt(2),
            observation_key="old",
        )
        session.commit()
        materialize_clue_master_leads(session, now=_dt(3))
        rebuild_clue_center(
            session,
            now=_dt(3),
            phone_plain_resolver=lambda values: {value: value for value in values},
        )
        session.commit()
        initial_impact = session.scalar(select(JobImpact).order_by(JobImpact.id.asc()))
        assert initial_impact is not None
        initial_work_item = session.scalar(
            select(ClueMaterializationWorkItem).where(
                ClueMaterializationWorkItem.impact_id == initial_impact.id
            )
        )
        assert initial_work_item is not None
        initial_work_item.state = "completed"
        initial_work_item.completed_at = _dt(3)
        session.commit()

    legacy_factory = _parity_factory()
    incremental_factory = _parity_factory()
    with legacy_factory() as legacy, incremental_factory() as incremental:
        seed(legacy)
        seed(incremental)
        for session in (legacy, incremental):
            upsert_raw_clue(
                session,
                "raw-parity-order-change",
                clue_id="clue-parity-order-new",
                order_id="order-parity-order-new",
                order_status="fulfilled",
                telephone="13900000044",
                follow_poi_id="poi-parity-order-new",
                create_time_detail=_dt(1),
                fetched_at=_dt(4),
                imported_at=_dt(4),
                updated_at=_dt(4),
                raw_payload={"version": "new"},
                source_observed_at=_dt(4),
                observation_key="new",
            )
            session.commit()

        materialize_clue_master_leads(legacy, now=_dt(5))
        rebuild_clue_center(
            legacy,
            now=_dt(5),
            phone_plain_resolver=lambda values: {value: value for value in values},
        )
        legacy.commit()
        run_incremental_clue_materialization(
            lambda: incremental_factory(),
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-parity-order-change",
            now=_dt(5),
            phone_plain_resolver=lambda values: {value: value for value in values},
        )

        assert _parity_checksum(legacy) == _parity_checksum(incremental)
        for session in (legacy, incremental):
            master = session.scalar(select(ClueMasterLead))
            assert master is not None
            assert master.order_id == "order-parity-order-old"
            issue = session.scalar(
                select(DataQualityIssue).where(
                    DataQualityIssue.issue_type == "clue_identity_conflict"
                )
            )
            assert issue is not None
            assert issue.raw_context_json["reason"] == "source_record_order_changed"


def test_clue_impact_closure_retains_old_and_new_identity_order_and_poi_sides(
    db_session: Session,
) -> None:
    upsert_raw_clue(
        db_session,
        "raw-closure-sides",
        clue_id="clue-closure-old",
        order_id="order-closure-old",
        telephone="13800000001",
        follow_poi_id="poi-closure-old",
        source_run_id="closure-run",
        source_observed_at=_dt(1),
        observation_key="closure-1",
        raw_payload={"version": "old"},
    )
    db_session.commit()
    upsert_raw_clue(
        db_session,
        "raw-closure-sides",
        clue_id="clue-closure-new",
        order_id="order-closure-new",
        telephone="13800000002",
        follow_poi_id="poi-closure-new",
        source_run_id="closure-run",
        source_observed_at=_dt(2),
        observation_key="closure-2",
        raw_payload={"version": "new"},
    )
    db_session.commit()

    impact = db_session.scalar(
        select(JobImpact).where(JobImpact.source_run_id == "closure-run").order_by(JobImpact.id.desc())
    )
    assert impact is not None
    closure = impact.affected_closure_json or {}
    assert {"clue-closure-old", "clue-closure-new"} <= set(closure["clue_ids"])
    assert {"order-closure-old", "order-closure-new"} <= set(closure["order_ids"])
    assert {"poi-closure-old", "poi-closure-new"} <= set(closure["poi_ids"])
    assert len(set(closure["source_identity_keys"])) == 2


def test_incremental_old_new_closure_updates_projection_and_history(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed clue/contact/POI is consumed, not merely captured in JobImpact."""

    old_store, old_mapping = _store("store-closure-consume-old", "poi-closure-consume-old")
    new_store, new_mapping = _store("store-closure-consume-new", "poi-closure-consume-new")
    order_id = "order-closure-consume"
    row_key = "raw-closure-consume"
    db_session.add_all(
        [
            old_store,
            old_mapping,
            new_store,
            new_mapping,
            RawDouyinOrder(order_id=order_id, order_status="fulfilled", updated_at=_dt(1)),
        ]
    )
    upsert_raw_clue(
        db_session,
        row_key,
        clue_id="clue-closure-consume-old",
        order_id=order_id,
        order_status="\u5c65\u7ea6\u4e2d",
        telephone="13800000001",
        follow_poi_id=old_mapping.poi_id,
        create_time_detail=_dt(1),
        fetched_at=_dt(2),
        imported_at=_dt(2),
        updated_at=_dt(2),
        raw_payload={"version": "old"},
        source_observed_at=_dt(2),
        observation_key="old",
    )
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(3))
    db_session.commit()
    initial_impact = db_session.scalar(select(JobImpact).order_by(JobImpact.id.asc()))
    assert initial_impact is not None
    initial_work_item = db_session.scalar(
        select(ClueMaterializationWorkItem).where(
            ClueMaterializationWorkItem.impact_id == initial_impact.id
        )
    )
    assert initial_work_item is not None
    initial_work_item.state = "completed"
    initial_work_item.completed_at = _dt(3)
    db_session.commit()
    before = db_session.scalar(select(ClueMasterLead))
    assert before is not None
    before_lead_key = before.lead_key
    before_source_row_key = before.source_clue_row_key
    before_identity = before.source_identity_key

    upsert_raw_clue(
        db_session,
        row_key,
        clue_id="clue-closure-consume-new",
        order_id=order_id,
        order_status="fulfilled",
        telephone="13900000002",
        follow_poi_id=new_mapping.poi_id,
        create_time_detail=_dt(1),
        fetched_at=_dt(4),
        imported_at=_dt(4),
        updated_at=_dt(4),
        raw_payload={"version": "new"},
        source_observed_at=_dt(4),
        observation_key="new",
    )
    db_session.commit()
    impact = db_session.scalar(select(JobImpact).order_by(JobImpact.id.desc()))
    assert impact is not None
    closure = impact.affected_closure_json or {}
    assert {"clue-closure-consume-old", "clue-closure-consume-new"} <= set(
        closure["clue_ids"]
    )
    assert {old_mapping.poi_id, new_mapping.poi_id} <= set(closure["poi_ids"])
    assert len(set(closure["source_identity_keys"])) == 2

    captured_identity_selectors: list[set[str]] = []
    original_bounded_existing = clue_allocation._bounded_existing_masters

    def capture_bounded_existing(session: Session, raw_clues, *args, **kwargs):
        captured_identity_selectors.append(set(kwargs.get("source_identity_keys") or set()))
        return original_bounded_existing(session, raw_clues, *args, **kwargs)

    monkeypatch.setattr(
        clue_allocation,
        "_bounded_existing_masters",
        capture_bounded_existing,
    )
    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-closure-consume",
        now=_dt(5),
    )

    assert result["work_items"] == 1
    assert captured_identity_selectors
    assert set(closure["source_identity_keys"]) <= captured_identity_selectors[0]
    db_session.expire_all()
    masters = db_session.scalars(select(ClueMasterLead)).all()
    assert len(masters) == 1
    master = masters[0]
    assert master.lead_key == before_lead_key
    assert master.source_clue_row_key == before_source_row_key
    assert master.canonical_clue_id == "clue-closure-consume-new"
    assert master.source_identity_key != before_identity
    assert master.anchor_poi_id == new_mapping.poi_id
    history = db_session.scalars(
        select(ClueSourceIdentifierHistory).where(
            ClueSourceIdentifierHistory.lead_key == before_lead_key
        )
    ).all()
    assert {row.identifier_value for row in history if row.identifier_type == "clue_id"} >= {
        "clue-closure-consume-old",
        "clue-closure-consume-new",
    }
    assert {row.identifier_value for row in history if row.identifier_type == "source_identity_key"} >= {
        before_identity,
        master.source_identity_key,
    }
    current_by_type = {
        identifier_type: [row for row in history if row.identifier_type == identifier_type and row.is_current]
        for identifier_type in ("clue_id", "source_identity_key")
    }
    assert [row.identifier_value for row in current_by_type["clue_id"]] == [
        "clue-closure-consume-new"
    ]
    assert [row.identifier_value for row in current_by_type["source_identity_key"]] == [
        master.source_identity_key
    ]


def test_incremental_new_raw_key_with_stable_order_reuses_unique_order_master(
    db_session: Session,
) -> None:
    """A new raw row for an otherwise unique order must merge like legacy full replay."""

    store, mapping = _store("store-order-compatible", "poi-order-compatible")
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(
                order_id="order-order-compatible",
                order_status="fulfilled",
                updated_at=_dt(1),
            ),
        ]
    )
    upsert_raw_clue(
        db_session,
        "raw-order-compatible-old",
        clue_id="clue-order-compatible-old",
        order_id="order-order-compatible",
        order_status="fulfilled",
        telephone="13800000055",
        follow_poi_id=mapping.poi_id,
        source_observed_at=_dt(2),
        observation_key="old",
        raw_payload={"version": "old"},
    )
    db_session.commit()
    materialize_clue_master_leads(db_session, now=_dt(3))
    db_session.commit()
    initial_impact = db_session.scalar(select(JobImpact).order_by(JobImpact.id.asc()))
    assert initial_impact is not None
    initial_work_item = db_session.scalar(
        select(ClueMaterializationWorkItem).where(
            ClueMaterializationWorkItem.impact_id == initial_impact.id
        )
    )
    assert initial_work_item is not None
    initial_work_item.state = "completed"
    initial_work_item.completed_at = _dt(3)
    db_session.commit()
    before = db_session.scalar(select(ClueMasterLead))
    assert before is not None

    upsert_raw_clue(
        db_session,
        "raw-order-compatible-new",
        clue_id="clue-order-compatible-new",
        order_id="order-order-compatible",
        order_status="fulfilled",
        telephone="13900000066",
        follow_poi_id=mapping.poi_id,
        source_observed_at=_dt(4),
        observation_key="new",
        raw_payload={"version": "new"},
    )
    db_session.commit()

    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-order-compatible",
        now=_dt(5),
    )

    assert result["work_items"] == 1
    db_session.expire_all()
    masters = db_session.scalars(select(ClueMasterLead)).all()
    assert len(masters) == 1
    assert masters[0].lead_key == before.lead_key
    assert masters[0].canonical_clue_id == "clue-order-compatible-new"


def test_incremental_order_candidate_window_preserves_ambiguity_with_strong_match(
    db_session: Session,
) -> None:
    """A strong match must not hide a second same-order candidate from order matching."""

    store, mapping = _store("store-order-ambiguous", "poi-order-ambiguous")
    order_id = "order-order-ambiguous"
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id=order_id, order_status="fulfilled", updated_at=_dt(1)),
            ClueMasterLead(
                lead_key="lead-order-ambiguous-1",
                source_clue_row_key="raw-order-ambiguous-1",
                source_identity_key="identity-order-ambiguous-1",
                canonical_clue_id="clue-order-ambiguous-1",
                order_id=order_id,
                raw_order_status="fulfilled",
                normalized_order_status="fulfilled",
                status_source="clue",
                lifecycle_status="active",
                pool_location="headquarters_pool",
                first_seen_at=_dt(1),
                last_seen_at=_dt(2),
            ),
            ClueMasterLead(
                lead_key="lead-order-ambiguous-2",
                source_clue_row_key="raw-order-ambiguous-2",
                source_identity_key="identity-order-ambiguous-2",
                canonical_clue_id="clue-order-ambiguous-2",
                order_id=order_id,
                raw_order_status="fulfilled",
                normalized_order_status="fulfilled",
                status_source="clue",
                lifecycle_status="active",
                pool_location="headquarters_pool",
                first_seen_at=_dt(1),
                last_seen_at=_dt(2),
            ),
            _clue(
                "raw-order-ambiguous-new",
                "clue-order-ambiguous-new",
                order_id,
                mapping.poi_id,
            ),
        ]
    )
    db_session.commit()
    impact = JobImpact(
        impact_key="impact-order-ambiguous-new",
        entity_type="order",
        entity_key=order_id,
        change_kind="upsert",
        affected_closure_json={
            "clue_ids": [
                "clue-order-ambiguous-1",
                "clue-order-ambiguous-new",
            ],
            "order_ids": [order_id],
            "poi_ids": [mapping.poi_id],
        },
    )
    db_session.add(impact)
    db_session.commit()

    raw_new = db_session.get(RawDouyinClue, "raw-order-ambiguous-new")
    assert raw_new is not None
    candidate_rows = clue_allocation._bounded_existing_masters(
        db_session,
        [raw_new],
        order_ids={order_id},
        clue_ids={"clue-order-ambiguous-1"},
        poi_ids={mapping.poi_id},
    )
    # RED before the bounded order-candidate window: the strong clue selector
    # returned only one row and silently enabled order_match.
    assert {row.lead_key for row in candidate_rows} >= {
        "lead-order-ambiguous-1",
        "lead-order-ambiguous-2",
    }

    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-order-ambiguous",
        now=_dt(4),
    )

    assert result["work_items"] == 1
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 3


def test_incremental_materialization_requires_attempt_scoped_lease_before_sql(
    db_session: Session,
) -> None:
    statements: list[str] = []

    def collect_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", collect_sql)
    try:
        with pytest.raises(ValueError, match="lease_token"):
            run_incremental_clue_materialization(_factory(db_session), lease_token=None)
    finally:
        event.remove(engine, "before_cursor_execute", collect_sql)
    assert statements == []


def test_incremental_lock_contention_leaves_work_pending(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, mapping = _store("store-a", "poi-a")
    db_session.add_all([store, mapping, _clue("raw-a", "clue-a", "order-a", "poi-a")])
    db_session.commit()
    upsert_raw_clue(
        db_session,
        "raw-a",
        clue_id="clue-b",
        order_id="order-a",
        order_status="履约中",
        follow_poi_id="poi-a",
        fetched_at=_dt(3),
        imported_at=_dt(3),
        updated_at=_dt(3),
        raw_payload={"clue_id": "clue-b"},
        source_observed_at=_dt(3),
        observation_key="obs-b",
    )
    db_session.commit()
    original = clue_allocation.materialize_clue_master_leads

    def locked(*args, **kwargs):
        return {"master_leads": 0, "closed_leads": 0, "headquarters_pool": 0, "skipped": "locked"}

    monkeypatch.setattr(clue_allocation, "materialize_clue_master_leads", locked)
    with pytest.raises(RuntimeError, match="lock unavailable"):
        run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            lease_token="attempt-lock",
            now=_dt(4),
        )
    assert db_session.scalar(
        select(func.count()).select_from(ClueMaterializationWorkItem).where(
            ClueMaterializationWorkItem.state == "pending"
        )
    ) >= 1
    monkeypatch.setattr(clue_allocation, "materialize_clue_master_leads", original)


def test_incremental_raw_pages_commit_cursor_and_resume_after_short_lease_crash(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raw fanout must be recoverable at the last committed page, not replayed."""

    store, mapping = _store("store-a", "poi-a")
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id="order-a", order_status="fulfilled", updated_at=_dt(1)),
            _clue("raw-1", "clue-1", "order-a", "poi-a"),
            _clue("raw-2", "clue-2", "order-a", "poi-a"),
            _clue("raw-3", "clue-3", "order-a", "poi-a"),
        ]
    )
    db_session.commit()
    impact = JobImpact(
        impact_key="manual-three-page-crash",
        entity_type="clue",
        entity_key="raw-1",
        change_kind="update",
        affected_closure_json={
            "clue_ids": ["clue-1", "clue-2", "clue-3"],
            "order_ids": ["order-a"],
            "poi_ids": ["poi-a"],
        },
    )
    db_session.add(impact)
    db_session.commit()
    work = ClueMaterializationWorkItem(
        scope="clue_materialization",
        impact_id=impact.id,
        entity_type="clue",
        entity_key="raw-1",
    )
    db_session.add(work)
    db_session.commit()

    base_factory = _factory(db_session)
    created_sessions: list[Session] = []
    closed_sessions: list[Session] = []

    def tracking_factory() -> Session:
        session = base_factory()
        created_sessions.append(session)
        original_close = session.close

        def close() -> None:
            closed_sessions.append(session)
            original_close()

        session.close = close  # type: ignore[method-assign]
        return session

    original = clue_allocation.materialize_clue_master_leads
    calls = 0

    def crash_on_second_page(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            # Model an OOM/process interruption: application cleanup cannot
            # return the lease, so the persisted cursor must be reclaimed only
            # after expiry by the next attempt.
            raise KeyboardInterrupt("injected second-page crash")
        return original(*args, **kwargs)

    monkeypatch.setattr(clue_allocation, "materialize_clue_master_leads", crash_on_second_page)
    with pytest.raises(KeyboardInterrupt, match="second-page crash"):
        run_incremental_clue_materialization(
            tracking_factory,
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-page-crash",
            # The test expires the persisted lease explicitly below. Keep the
            # initial lease long enough that a loaded CI runner can commit the
            # first page before the injected second-page crash.
            lease_seconds=30,
            now=_dt(4),
        )

    db_session.expire_all()
    persisted = db_session.get(ClueMaterializationWorkItem, work.work_item_id)
    assert persisted is not None
    assert persisted.state == "processing"
    assert persisted.raw_cursor == "raw-1"
    assert persisted.raw_page_complete is False
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 1

    # Simulate the database clock passing the short lease before the retry.
    persisted.lease_expires_at = _dt(1)
    db_session.commit()
    monkeypatch.setattr(clue_allocation, "materialize_clue_master_leads", original)
    result = run_incremental_clue_materialization(
        tracking_factory,
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-page-retry",
        lease_seconds=30,
        now=_dt(5),
    )
    assert result["work_items"] == 1
    assert db_session.scalar(
        select(func.count()).select_from(ClueMaterializationWorkItem).where(
            ClueMaterializationWorkItem.state == "completed"
        )
    ) == 1
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 1
    assert len(created_sessions) == len(closed_sessions)
    assert all(not session.in_transaction() for session in closed_sessions)
    assert {"clue-1", "clue-2", "clue-3"} <= {
        value
        for value in db_session.scalars(
            select(ClueSourceIdentifierHistory.identifier_value)
        )
        if value
    }


def test_center_phase_crash_resumes_after_committed_order_cursor(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A center commit fences one order; a crash resumes the next keyset page."""

    store_a, mapping_a = _store("store-center-crash-a", "poi-center-crash-a")
    store_b, mapping_b = _store("store-center-crash-b", "poi-center-crash-b")
    order_a = "order-center-crash-a"
    order_b = "order-center-crash-b"
    clue_a = _clue("raw-center-crash-a", "clue-center-crash-a", order_a, mapping_a.poi_id)
    clue_b = _clue("raw-center-crash-b", "clue-center-crash-b", order_b, mapping_b.poi_id)
    db_session.add_all(
        [
            store_a,
            mapping_a,
            store_b,
            mapping_b,
            RawDouyinOrder(order_id=order_a, order_status="履约中", updated_at=_dt(1)),
            RawDouyinOrder(order_id=order_b, order_status="履约中", updated_at=_dt(1)),
            clue_a,
            clue_b,
            JobImpact(
                impact_key="impact-center-crash",
                entity_type="order",
                entity_key=order_a,
                change_kind="upsert",
                affected_closure_json={
                    "clue_ids": [clue_a.clue_id, clue_b.clue_id],
                    "order_ids": [order_a, order_b],
                    "poi_ids": [mapping_a.poi_id, mapping_b.poi_id],
                },
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(clue_allocation, "CENTER_ORDER_BATCH_SIZE", 1)
    center_calls: list[set[str]] = []
    original_center = clue_allocation.refresh_clue_center_projection

    def crash_on_second_center(session: Session, *args, **kwargs):
        center_calls.append(set(kwargs.get("order_ids") or set()))
        if len(center_calls) == 2:
            raise KeyboardInterrupt("simulated center crash")
        return original_center(session, *args, **kwargs)

    monkeypatch.setattr(
        clue_allocation,
        "refresh_clue_center_projection",
        crash_on_second_center,
    )
    with pytest.raises(KeyboardInterrupt, match="simulated center crash"):
        run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            raw_batch_size=2,
            lease_token="attempt-center-crash",
            lease_seconds=30,
            now=_dt(4),
        )

    db_session.expire_all()
    work = db_session.scalar(select(ClueMaterializationWorkItem))
    assert work is not None
    assert work.state == "processing"
    assert work.raw_page_complete is True
    assert work.center_cursor == order_a
    assert db_session.scalar(select(func.count()).select_from(ClueCenterOrder)) == 1

    work.lease_expires_at = _dt(1)
    db_session.commit()
    monkeypatch.setattr(
        clue_allocation,
        "refresh_clue_center_projection",
        original_center,
    )
    retry = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=2,
        lease_token="attempt-center-retry",
        lease_seconds=30,
        now=_dt(5),
    )
    assert retry["work_items"] == 1
    assert db_session.scalar(select(func.count()).select_from(ClueCenterOrder)) == 2
    db_session.expire_all()
    work = db_session.scalar(select(ClueMaterializationWorkItem))
    assert work is not None and work.state == "completed"

    replay = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=2,
        lease_token="attempt-center-replay",
        now=_dt(6),
    )
    assert replay["work_items"] == 0
    assert db_session.scalar(select(func.count()).select_from(ClueCenterOrder)) == 2


def test_incremental_closure_uses_identifier_history_to_reach_legacy_lead(
    db_session: Session,
) -> None:
    """An identifier-only impact must load the lead through history reverse mapping."""

    store, mapping = _store("store-a", "poi-a")
    db_session.add_all(
        [
            store,
            mapping,
            _clue("raw-new", "legacy-clue", "order-new", "poi-a"),
            ClueMasterLead(
                lead_key="lead-legacy",
                source_clue_row_key="raw-legacy",
                source_identity_key="identity-legacy",
                canonical_clue_id="current-clue",
                order_id=None,
                raw_order_status="fulfilled",
                normalized_order_status="fulfilled",
                lifecycle_status="active",
                pool_location="headquarters_pool",
                first_seen_at=_dt(1),
                last_seen_at=_dt(3),
            ),
            ClueSourceIdentifierHistory(
                identifier_history_id="history-legacy-clue",
                lead_key="lead-legacy",
                source_clue_row_key="raw-legacy",
                identifier_type="clue_id",
                identifier_value="legacy-clue",
                first_seen_at=_dt(1),
                last_seen_at=_dt(3),
                is_current=True,
            ),
        ]
    )
    db_session.commit()
    raw_new = db_session.get(RawDouyinClue, "raw-new")
    assert raw_new is not None
    raw_new.source_observed_at = _dt(4)
    raw_new.fetched_at = _dt(4)
    raw_new.updated_at = _dt(4)
    db_session.commit()
    impact = JobImpact(
        impact_key="identifier-only-legacy-impact",
        entity_type="clue",
        entity_key="raw-new",
        change_kind="update",
        affected_closure_json={"clue_ids": ["legacy-clue"]},
    )
    db_session.add(impact)
    db_session.commit()
    db_session.add(
        ClueMaterializationWorkItem(
            scope="clue_materialization",
            impact_id=impact.id,
            entity_type="clue",
            entity_key="raw-new",
        )
    )
    db_session.commit()

    result = run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        lease_token="attempt-history-reverse",
        now=_dt(4),
    )

    assert result["work_items"] == 1
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 1
    master = db_session.get(ClueMasterLead, "lead-legacy")
    assert master is not None
    assert master.canonical_clue_id == "legacy-clue"
    assert db_session.scalar(
        select(func.count()).select_from(ClueSourceIdentifierHistory).where(
            ClueSourceIdentifierHistory.lead_key == "lead-legacy",
            ClueSourceIdentifierHistory.source_clue_row_key == "raw-new",
            ClueSourceIdentifierHistory.identifier_value == "legacy-clue",
        )
    ) == 1


def test_incremental_identifier_history_reverse_lookup_is_type_scoped(
    db_session: Session,
) -> None:
    """A telephone/history collision must not select a clue-id lead."""

    raw = _clue("raw-collision", "shared-id", "order-new", "poi-a")
    lead = ClueMasterLead(
        lead_key="lead-phone-only",
        source_clue_row_key="raw-phone",
        source_identity_key="identity-phone",
        canonical_clue_id="different-clue",
        order_id=None,
        raw_order_status="fulfilled",
        normalized_order_status="fulfilled",
        lifecycle_status="active",
        pool_location="headquarters_pool",
        first_seen_at=_dt(1),
        last_seen_at=_dt(3),
    )
    history = ClueSourceIdentifierHistory(
        identifier_history_id="history-phone-collision",
        lead_key=lead.lead_key,
        source_clue_row_key=lead.source_clue_row_key,
        identifier_type="telephone",
        identifier_value="shared-id",
        first_seen_at=_dt(1),
        last_seen_at=_dt(3),
        is_current=True,
    )
    db_session.add_all([raw, lead, history])
    db_session.commit()

    masters = clue_allocation._bounded_existing_masters(
        db_session,
        [raw],
        order_ids=set(),
    )

    assert masters == []


def test_incremental_page_fence_blocks_old_attempt_after_takeover(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost JobRun fence must roll back the next page and leave its cursor."""

    store, mapping = _store("store-fence", "poi-fence")
    db_session.add_all(
        [
            store,
            mapping,
            RawDouyinOrder(order_id="order-fence", order_status="fulfilled", updated_at=_dt(1)),
            _clue("raw-fence-1", "clue-fence-1", "order-fence", "poi-fence"),
            _clue("raw-fence-2", "clue-fence-2", "order-fence", "poi-fence"),
        ]
    )
    db_session.commit()
    impact = JobImpact(
        impact_key="fence-takeover-impact",
        entity_type="clue",
        entity_key="raw-fence-1",
        affected_closure_json={
            "clue_ids": ["clue-fence-1", "clue-fence-2"],
            "order_ids": ["order-fence"],
            "poi_ids": ["poi-fence"],
        },
    )
    db_session.add(impact)
    db_session.commit()
    work = ClueMaterializationWorkItem(
        scope="clue_materialization",
        impact_id=impact.id,
        entity_type="clue",
        entity_key="raw-fence-1",
    )
    db_session.add(work)
    db_session.commit()

    checks = 0
    fence_sessions: list[Session] = []
    fence_transaction_states: list[bool] = []
    operation_sessions: list[Session] = []

    original_materialize = clue_allocation.materialize_clue_master_leads
    original_rebuild_center = clue_allocation.refresh_clue_center_projection
    original_renew = clue_allocation.renew_clue_materialization_batch

    def record_materialize(page_session: Session, *args, **kwargs):
        operation_sessions.append(page_session)
        return original_materialize(page_session, *args, **kwargs)

    def record_rebuild_center(page_session: Session, *args, **kwargs):
        operation_sessions.append(page_session)
        return original_rebuild_center(page_session, *args, **kwargs)

    def record_renew(page_session: Session, *args, **kwargs):
        operation_sessions.append(page_session)
        return original_renew(page_session, *args, **kwargs)

    monkeypatch.setattr(clue_allocation, "materialize_clue_master_leads", record_materialize)
    monkeypatch.setattr(
        clue_allocation,
        "refresh_clue_center_projection",
        record_rebuild_center,
    )
    monkeypatch.setattr(
        clue_allocation,
        "renew_clue_materialization_batch",
        record_renew,
    )

    def fence(page_session: Session) -> bool:
        nonlocal checks
        fence_sessions.append(page_session)
        fence_transaction_states.append(page_session.in_transaction())
        checks += 1
        return checks == 1

    with pytest.raises(RuntimeError, match="lease is no longer valid"):
        run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            raw_batch_size=1,
            lease_token="attempt-old-epoch",
            lease_seconds=30,
            page_fence=fence,
            now=_dt(4),
        )

    db_session.expire_all()
    persisted = db_session.get(ClueMaterializationWorkItem, work.work_item_id)
    assert persisted is not None
    assert persisted.state == "pending"
    assert persisted.raw_cursor == "raw-fence-1"
    assert db_session.scalar(select(func.count()).select_from(ClueMasterLead)) == 1
    assert len(fence_sessions) == 2
    assert len({id(page_session) for page_session in fence_sessions}) == 2
    assert fence_transaction_states == [True, True]
    assert all(page_session in operation_sessions for page_session in fence_sessions)
    assert all(not page_session.in_transaction() for page_session in fence_sessions)


def test_incremental_empty_claim_does_not_report_success_with_active_unfinished_work(
    db_session: Session,
) -> None:
    """An active lease held by another attempt must fail/retry, never stage-success."""

    impact = JobImpact(
        impact_key="active-unfinished-impact",
        entity_type="clue",
        entity_key="raw-active-unfinished",
        affected_closure_json={},
    )
    db_session.add(impact)
    db_session.commit()
    db_session.add(
        JobImpactWatermark(
            scope="clue_materialization",
            cycle_id="cycle-active-unfinished",
            frozen_upper_bound_id=impact.id,
            last_work_item_id=0,
        )
    )
    db_session.add(
        ClueMaterializationWorkItem(
            scope="clue_materialization",
            impact_id=impact.id,
            entity_type="clue",
            entity_key="raw-active-unfinished",
            state="processing",
            lease_owner="attempt-other",
            leased_at=datetime.now(timezone.utc),
            lease_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    db_session.commit()

    with pytest.raises(RuntimeError, match="unfinished"):
        run_incremental_clue_materialization(
            _factory(db_session),
            batch_size=1,
            lease_token="attempt-new",
        )


@pytest.mark.parametrize(
    ("first_row_observation_key", "second_row_observation_key"),
    [("z", "a"), ("a", "z")],
)
def test_equal_observation_time_uses_highest_observation_key_across_pages(
    db_session: Session,
    first_row_observation_key: str,
    second_row_observation_key: str,
) -> None:
    """A same-time replay must not let page/row order replace the latest state."""

    store, mapping = _store("store-observation-tie", "poi-observation-tie")
    order = RawDouyinOrder(
        order_id="order-observation-tie",
        order_status="fulfilled",
        updated_at=_dt(1),
    )
    first = _clue(
        "raw-observation-tie-1",
        "clue-observation-tie-1",
        "order-observation-tie",
        "poi-observation-tie",
    )
    second = _clue(
        "raw-observation-tie-2",
        "clue-observation-tie-2",
        "order-observation-tie",
        "poi-observation-tie",
    )
    for raw_clue, observation_key in (
        (first, first_row_observation_key),
        (second, second_row_observation_key),
    ):
        raw_clue.source_observed_at = _dt(5)
        raw_clue.observation_key = observation_key
        raw_clue.raw_payload = {"clue_id": raw_clue.clue_id, "observation_key": observation_key}
    db_session.add_all([store, mapping, order, first, second])
    db_session.commit()

    impact = JobImpact(
        impact_key="observation-tie-impact",
        entity_type="clue",
        entity_key=first.clue_row_key,
        affected_closure_json={
            "clue_ids": [first.clue_id, second.clue_id],
            "order_ids": [order.order_id],
            "poi_ids": [mapping.poi_id],
        },
    )
    db_session.add(impact)
    db_session.commit()
    db_session.add(
        ClueMaterializationWorkItem(
            scope="clue_materialization",
            impact_id=impact.id,
            entity_type="clue",
            entity_key=first.clue_row_key,
        )
    )
    db_session.commit()

    run_incremental_clue_materialization(
        _factory(db_session),
        batch_size=1,
        raw_batch_size=1,
        lease_token="attempt-observation-tie",
        now=_dt(6),
    )

    master = db_session.scalar(select(ClueMasterLead))
    assert master is not None
    assert master.last_observation_key == "z"
    assert master.canonical_clue_id == (
        first.clue_id
        if first_row_observation_key == "z"
        else second.clue_id
    )
