"""DYDATA-102 driver real two-to-three child lifecycle regression tests.

Scope (honest, controller-visible):

* Real SQLite (in-memory) control-plane schema via ``Base.metadata`` and the
  real ``plan_day_recovery`` / ``plan_daily_sync`` / ``enqueue_finalize_if_ready``
  entry points.  No PostgreSQL, no network, no production dry-run, no credentials,
  no real upstream writes.
* These tests pin the *actual* planner contract that the recovery driver must
  honour: ``plan_day_recovery`` allocates exactly ``parent_sync`` + ``date_sync``
  first, and the official ``enqueue_finalize_if_ready`` (invoked from
  ``task_control.complete_job`` after a ``date_sync`` child succeeds) creates
  ``finalize`` later.  A driver that demands all three children immediately is
  therefore wrong, and a driver that fabricates a finalize itself is also wrong.
* The only fakes used are the driver's own seams (``published_days_revisions``
  monkeypatch, and a fake clock/sleep/resource-decision/child-runner for the loop
  budget) to prove control-flow properties that cannot be reached by static
  inspection.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _path in (str(ROOT), str(ROOT / "apps" / "api")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from apps.api.dy_api.models import Base, JobRun, JobStageRun  # noqa: E402
from apps.worker.daily_windows import enqueue_finalize_if_ready  # noqa: E402
from apps.worker.day_recovery import plan_day_recovery  # noqa: E402
from apps.worker.resource_monitor import ResourceAction, ResourceDecision  # noqa: E402

UTC = timezone.utc
TARGET = date(2026, 9, 14)


def _load_driver():
    path = ROOT / ".dsh-scoped-recovery-driver.py"
    spec = importlib.util.spec_from_file_location("dsh_driver_lifecycle", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


driver = _load_driver()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    e = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class FakeClock:
    def __init__(self, start=0.0, step=10.0):
        self.now = start
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


class Recorder:
    def __init__(self, result=None):
        self.calls: list[dict] = []
        self._result = result

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _base_parent(job_id="base-parent-9-14", status="failed") -> JobRun:
    return JobRun(
        job_id=job_id,
        job_name="range_sync",
        job_kind="range_sync",
        status=status,
        parent_job_id=None,
        data_source="api",
        config_version="priority-daily-v1",
        metadata_json={"target": "all"},
        window_start=datetime(2026, 9, 14, 0, 0),
        window_end=datetime(2026, 9, 15, 0, 0),
        execution_slot=None,
        business_date=None,
        attempt_count=0,
        max_attempts=3,
        quota_pause_count=0,
    )


def _recovery_plan(session, *, request_key="lifecycle-request-key", base_status="failed"):
    """Allocate one real recovery generation and return ``(base, plan)``."""
    base = _base_parent(status=base_status)
    session.add(base)
    session.flush()
    plan, _replayed = plan_day_recovery(
        session,
        parent=base,
        request_key=request_key,
        reason="lifecycle-test",
        actor="ops-agent",
    )
    session.commit()
    return base, plan


def _children_of(session, parent_id):
    return list(
        session.scalars(
            select(JobRun).where(JobRun.parent_job_id == parent_id)
        ).all()
    )


def _finalize_count(session):
    return session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.job_kind == "finalize")
    )


def _mark_date_children_success(session, plan) -> None:
    """Succeed every date child and build its committed settle stage fences."""
    now = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    for planned in plan.daily_jobs:
        child = session.get(JobRun, planned.job_id)
        assert child is not None
        child.status = "success"
        child.finished_at = now
        for stage_name in (child.metadata_json or {}).get("required_stages", []):
            checkpoint = {}
            if stage_name == "settle":
                checkpoint = {
                    "settlement_summary": {
                        "completed": True,
                        "impact_count": 0,
                        "coupon_count": 0,
                        "detail_count": 0,
                        "result_count": 0,
                        "adjustment_count": 0,
                        "last_impact_id": None,
                        "affected_months": [],
                        "affected_store_ids": [],
                    },
                    "store_score_snapshot": {
                        "deferred": True,
                        "consumer": "T3.4.finalize",
                        "affected_store_ids": [],
                        "rule_closure": "published-rules-and-eligible-stores",
                    },
                }
            session.add(
                JobStageRun(
                    stage_run_id=f"stage-{child.job_id}-{stage_name}",
                    job_id=child.job_id,
                    stage_name=stage_name,
                    status="success",
                    checkpoint_json=checkpoint,
                    lease_epoch=1,
                    started_at=now,
                    finished_at=now,
                    committed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
    session.flush()


def _mark_parent_stage_success(session, plan) -> None:
    now = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    required_stage = session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    if required_stage is not None:
        required_stage.status = "success"
        required_stage.committed_at = now
        required_stage.finished_at = now
    session.flush()


def _mark_parent_sync_success(session, parent_id) -> None:
    for row in _children_of(session, parent_id):
        if row.job_kind == "parent_sync":
            row.status = "success"
            row.finished_at = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    session.flush()


# ---------------------------------------------------------------------------
# 1. the actual planner initial state is two children, and the driver accepts it
# ---------------------------------------------------------------------------


def test_actual_planner_initial_two_child_state_is_accepted(session_factory):
    with session_factory() as session:
        _base, plan = _recovery_plan(session)

        # The real planner allocates exactly parent_sync + date_sync first; the
        # official finalize job does not exist yet.
        kinds = sorted(row.job_kind for row in _children_of(session, plan.parent_job_id))
        assert kinds == ["date_sync", "parent_sync"]
        assert _finalize_count(session) == 0

        # The driver must accept this lawful in-progress shape, not refuse it.
        children = driver._allocated_children(session, plan.parent_job_id)
        assert children is not None
        assert sorted(child.job_kind for child in children) == ["date_sync", "parent_sync"]


def test_plan_round_selects_a_child_from_the_two_child_state(session_factory):
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        _stamp_recovery(session, plan.parent_job_id)
        rows = driver._priority_rows_for_day(session, TARGET)
        children = driver._allocated_children(session, plan.parent_job_id)
        kind, payload = driver._plan_round(
            rows,
            children,
            expected_parent_id=plan.parent_job_id,
            select_candidate=driver._select_candidate,
            session=session,
            now=datetime(2026, 9, 14, tzinfo=UTC),
        )
        # The first selectable child in the two-child state is parent_sync.
        assert kind == "run"
        assert session.get(JobRun, payload).job_kind == "parent_sync"


def _stamp_recovery(session, parent_id):
    # The driver stamps the recovery generation onto its day's quota class before
    # selection, exactly as ``_drive`` does.  Without it ``_select_candidate``
    # sees no purpose and returns no candidate.
    rows = driver._priority_rows_for_day(session, TARGET)
    driver._stamp_recovery_generation(session, rows)
    session.commit()


# ---------------------------------------------------------------------------
# 2. the official finalize is created only after its dependencies
# ---------------------------------------------------------------------------


def test_official_finalize_is_created_only_after_dependencies(session_factory):
    with session_factory() as session:
        _base, plan = _recovery_plan(session)

        # Dependency 1: no date child has succeeded yet.
        assert enqueue_finalize_if_ready(session, plan.parent_job_id) is None
        assert _finalize_count(session) == 0

        # Dependency 2: date child succeeded, but the required parent
        # (collect_dimensions) stage has not committed yet.
        _mark_date_children_success(session, plan)
        assert enqueue_finalize_if_ready(session, plan.parent_job_id) is None
        assert _finalize_count(session) == 0

        # All dependencies satisfied -> the official mechanism creates finalize.
        _mark_parent_stage_success(session, plan)
        finalize = enqueue_finalize_if_ready(session, plan.parent_job_id)
        assert finalize is not None
        assert finalize.job_kind == "finalize"
        assert finalize.parent_job_id == plan.parent_job_id
        assert finalize.status == "pending"
        assert _finalize_count(session) == 1


def test_driver_does_not_fabricate_finalize_on_two_child_state(session_factory):
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        _stamp_recovery(session, plan.parent_job_id)
        # Running the round planner against the two-child state must neither
        # refuse nor invent a finalize row; it only selects the next real child.
        rows = driver._priority_rows_for_day(session, TARGET)
        children = driver._allocated_children(session, plan.parent_job_id)
        assert children is not None
        assert _finalize_count(session) == 0
        assert driver._validated_children(children) is not None


# ---------------------------------------------------------------------------
# 3. the final proof requires three successful children AND a published month
# ---------------------------------------------------------------------------


def _three_success_chain(session, plan):
    _mark_parent_sync_success(session, plan.parent_job_id)
    _mark_date_children_success(session, plan)
    _mark_parent_stage_success(session, plan)
    finalize = enqueue_finalize_if_ready(session, plan.parent_job_id)
    assert finalize is not None
    finalize.status = "success"
    finalize.finished_at = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    parent = session.get(JobRun, plan.parent_job_id)
    parent.status = "success"
    session.commit()


def test_final_proof_fails_with_just_two_success_children(session_factory, monkeypatch):
    monkeypatch.setattr(
        driver, "published_days_revisions", lambda s, month: [f"{TARGET.isoformat()}@x"]
    )
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        _mark_parent_sync_success(session, plan.parent_job_id)
        _mark_date_children_success(session, plan)
        _mark_parent_stage_success(session, plan)
        parent = session.get(JobRun, plan.parent_job_id)
        parent.status = "success"
        session.commit()

        ok, reason = driver._final_outcome(session, plan.parent_job_id)
        assert not ok
        assert reason in {"final_children_shape_invalid", "final_finalize_not_success"}
        # Exactly two success children and no finalize row exist.
        assert _finalize_count(session) == 0


def test_final_proof_fails_without_published_month(session_factory, monkeypatch):
    monkeypatch.setattr(driver, "published_days_revisions", lambda s, month: None)
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        _three_success_chain(session, plan)
        ok, reason = driver._final_outcome(session, plan.parent_job_id)
        assert not ok
        assert reason == "september_source_incomplete"


def test_final_proof_succeeds_with_three_children_and_published_month(
    session_factory, monkeypatch
):
    monkeypatch.setattr(
        driver, "published_days_revisions", lambda s, month: [f"{TARGET.isoformat()}@x"]
    )
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        _three_success_chain(session, plan)
        ok, reason = driver._final_outcome(session, plan.parent_job_id)
        assert ok
        assert reason == "success"


# ---------------------------------------------------------------------------
# 4. unknown / duplicate / missing children are rejected
# ---------------------------------------------------------------------------


def _kind(kind):
    return types.SimpleNamespace(job_kind=kind)


def test_validated_children_rejects_unknown_duplicate_and_missing():
    parent_sync = _kind("parent_sync")
    date_sync = _kind("date_sync")
    finalize = _kind("finalize")

    # Lawful shapes only.
    assert driver._validated_children((parent_sync, date_sync)) is not None
    assert driver._validated_children((parent_sync, date_sync, finalize)) is not None

    # Unknown kind.
    assert driver._validated_children((parent_sync, date_sync, _kind("settlement"))) is None
    # Duplicates.
    assert driver._validated_children((parent_sync, _kind("parent_sync"), date_sync)) is None
    assert driver._validated_children((date_sync, _kind("date_sync"), parent_sync)) is None
    assert driver._validated_children(
        (parent_sync, date_sync, finalize, _kind("finalize"))
    ) is None
    # Missing required children.
    assert driver._validated_children(()) is None
    assert driver._validated_children((parent_sync,)) is None
    assert driver._validated_children((date_sync,)) is None
    assert driver._validated_children((finalize,)) is None
    assert driver._validated_children((parent_sync, finalize)) is None
    assert driver._validated_children((date_sync, finalize)) is None


def test_allocated_children_inspects_unknown_kinds_instead_of_filtering_them(
    session_factory,
):
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        assert driver._allocated_children(session, plan.parent_job_id) is not None

        # An unknown child kind hanging under the allocated parent must refuse,
        # not be silently filtered away by a ``job_kind IN (...)` predicate.
        session.add(
            JobRun(
                job_id=f"{plan.parent_job_id}-unknown",
                job_name="range_sync",
                job_kind="range_sync",
                status="pending",
                parent_job_id=plan.parent_job_id,
                data_source="api",
                config_version=plan.config_version,
                metadata_json={"target": "all"},
                window_start=datetime(2026, 9, 14, 0, 0),
                window_end=datetime(2026, 9, 15, 0, 0),
                execution_slot=None,
                business_date=None,
                attempt_count=0,
                max_attempts=3,
                quota_pause_count=0,
            )
        )
        session.commit()
        assert driver._allocated_children(session, plan.parent_job_id) is None


# ---------------------------------------------------------------------------
# 5. a changed winning generation stops the driver
# ---------------------------------------------------------------------------


def test_winning_generation_change_stops_the_driver(session_factory):
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        rows = driver._priority_rows_for_day(session, TARGET)
        kind, payload = driver._plan_round(
            rows,
            None,
            expected_parent_id="some-other-parent",
            select_candidate=driver._select_candidate,
            session=session,
            now=datetime(2026, 9, 14, tzinfo=UTC),
        )
        assert kind == "refused"
        assert payload == ("winning_parent_changed", 4)


# ---------------------------------------------------------------------------
# 6. exhausted attempts and the resource guard keep the driver bounded
# ---------------------------------------------------------------------------


def test_exhausted_child_attempts_refuse_without_reset(session_factory):
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        _stamp_recovery(session, plan.parent_job_id)
        # Exhaust the date child's attempt budget (attempt_count == max_attempts).
        date_child = next(
            row for row in _children_of(session, plan.parent_job_id)
            if row.job_kind == "date_sync"
        )
        date_child.status = "failed"
        date_child.attempt_count = 3
        date_child.max_attempts = 3
        date_child.quota_pause_count = 0
        session.commit()

        rows = driver._priority_rows_for_day(session, TARGET)
        children = driver._allocated_children(session, plan.parent_job_id)
        kind, payload = driver._plan_round(
            rows,
            children,
            expected_parent_id=plan.parent_job_id,
            select_candidate=driver._select_candidate,
            session=session,
            now=datetime(2026, 9, 14, tzinfo=UTC),
        )
        assert kind == "refused"
        assert payload == ("budget_exhausted_child", 4)
        # No reset: the child is still terminal, never flipped back to runnable.
        assert date_child.status == "failed"


def test_resource_guard_never_starts_a_child_and_reaches_deadline(session_factory):
    with session_factory() as session:
        _base, plan = _recovery_plan(session)
        rows = driver._priority_rows_for_day(session, TARGET)
        children = driver._allocated_children(session, plan.parent_job_id)
        clock = FakeClock(start=0.0, step=10.0)
        sleeps: list[float] = []

        def _sleep(seconds):
            assert 0 < seconds <= driver.ROUND_WAIT_SECONDS
            sleeps.append(seconds)
            clock.now += seconds

        child = Recorder(result=RuntimeError("run_child must never be called"))
        code = driver._drive(
            factory=None,
            expected_parent_id=plan.parent_job_id,
            deadline=100.0,
            clock=clock,
            sleep=_sleep,
            resource_decision=lambda: ResourceDecision(ResourceAction.STOP, ("drain",)),
            run_child=child,
            rows_provider=lambda: rows,
            children_provider=lambda session, parent: children,
            select_candidate=driver._select_candidate,
        )
        assert code == 3
        assert child.calls == []
        assert sleeps
