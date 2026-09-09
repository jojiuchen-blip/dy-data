from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobRun, JobStageRun, RawDouyinRefundRecord
from apps.worker.paged_collection import (
    LeaseFenceLost,
    PagedCollectionError,
    collect_priority_pages,
)
from apps.worker.priority_budget import PriorityBudgetPauseError


WINDOW_START = datetime.fromisoformat("2026-09-09T00:00:00+08:00")
WINDOW_END = datetime.fromisoformat("2026-09-10T00:00:00+08:00")


def _factory(db_session: Session) -> sessionmaker[Session]:
    return sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def _job(db_session: Session, *, target: str = "refunds", job_id: str = "paged-job") -> JobRun:
    job = JobRun(
        job_id=job_id,
        job_name="date_sync",
        status="running",
        config_version="priority-daily-v1",
        metadata_json={
            "target": target,
            "source_window": {
                "start": WINDOW_START.isoformat(),
                "end": WINDOW_END.isoformat(),
                "timezone": "Asia/Shanghai",
            },
        },
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _refund(
    refund_id: str,
    *,
    status: str = "50",
    observed: str = "2026-09-09T10:00:00+08:00",
) -> dict[str, Any]:
    return {
        "after_sale_id": refund_id,
        "order_id": f"order-{refund_id}",
        "refund_status": status,
        "refund_type": "full",
        "refund_amount_cent": 100,
        "complete_time": observed,
    }


class _PagedRefundClient:
    def __init__(self, pages: dict[str | None, dict[str, Any] | BaseException]):
        self.pages = pages
        self.calls: list[str | None] = []

    def query_refunds(self, _start, _end, *, page_size: int, cursor: str | None = None):
        self.calls.append(cursor)
        result = self.pages.get(cursor)
        if isinstance(result, BaseException):
            raise result
        if result is None:
            raise AssertionError(f"unexpected refund cursor {cursor!r}")
        return result


def _refund_page(rows: list[dict[str, Any]], *, has_more: bool, cursor: str | None = None):
    data: dict[str, Any] = {"refunds": rows, "has_more": has_more}
    if cursor is not None:
        data["next_cursor"] = cursor
    return {"data": data}


def test_refund_page_checkpoint_survives_quota_pause_and_resume_without_replaying_first_page(
    db_session: Session,
):
    job = _job(db_session)
    client = _PagedRefundClient(
        {
            None: _refund_page([_refund("r-1")], has_more=True, cursor="c1"),
            "c1": PriorityBudgetPauseError(3600),
        }
    )
    factory = _factory(db_session)

    with pytest.raises(PriorityBudgetPauseError):
        collect_priority_pages(factory, client, job)

    db_session.expire_all()
    first_raw = db_session.scalar(
        select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.refund_id == "r-1")
    )
    assert first_raw is not None
    stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == job.job_id,
            JobStageRun.stage_name == "collect",
        )
    )
    assert stage is not None
    assert stage.checkpoint_json["domains"]["refunds"]["cursor"] == "c1"
    assert stage.checkpoint_json["domains"]["refunds"]["pages_committed"] == 1
    assert client.calls == [None, "c1"]

    client.pages["c1"] = _refund_page([_refund("r-2")], has_more=False)
    collect_priority_pages(factory, client, job)

    db_session.expire_all()
    assert (
        db_session.scalar(
            select(RawDouyinRefundRecord).where(
                RawDouyinRefundRecord.refund_id == "r-2"
            )
        )
        is not None
    )
    stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == job.job_id,
            JobStageRun.stage_name == "collect",
        )
    )
    assert stage is not None
    assert stage.checkpoint_json["completed"] is True
    assert stage.checkpoint_json["domains"]["refunds"]["pages_committed"] == 2
    # The first committed page is never queried again after a restart.
    assert client.calls == [None, "c1", "c1"]


def test_stale_page_fence_rolls_back_raw_rows_and_checkpoint(db_session: Session):
    job = _job(db_session, job_id="stale-fence-job")
    client = _PagedRefundClient({None: _refund_page([_refund("r-stale")], has_more=False)})
    calls = 0

    def fence(_session: Session) -> bool:
        nonlocal calls
        calls += 1
        # preflight, pre-write, then lease expiry immediately before commit
        return calls < 3

    with pytest.raises(LeaseFenceLost):
        collect_priority_pages(_factory(db_session), client, job, page_fence=fence)

    db_session.expire_all()
    assert (
        db_session.scalar(
            select(RawDouyinRefundRecord).where(
                RawDouyinRefundRecord.refund_id == "r-stale"
            )
        )
        is None
    )
    assert db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == job.job_id,
            JobStageRun.stage_name == "collect",
        )
    ) is None


def test_refund_normalizer_keeps_newer_completed_status_on_older_replay(db_session: Session):
    job = _job(db_session, job_id="status-regression-job")
    client = _PagedRefundClient(
        {
            None: _refund_page([_refund("r-status", status="50")], has_more=True, cursor="older"),
            "older": _refund_page(
                [_refund("r-status", status="9", observed="2026-09-09T09:00:00+08:00")],
                has_more=False,
            ),
        }
    )

    collect_priority_pages(_factory(db_session), client, job)
    db_session.expire_all()
    row = db_session.scalar(
        select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.refund_id == "r-status")
    )
    assert row is not None
    assert row.raw_refund_status == "50"
    assert row.normalized_refund_status == 2


def test_checkpoint_rejects_wrong_endpoint_and_empty_page_completes(db_session: Session):
    job = _job(db_session, job_id="checkpoint-contract-job")
    db_session.add(
        JobStageRun(
            stage_run_id="stage-checkpoint-contract-job-collect",
            job_id=job.job_id,
            stage_name="collect",
            status="pending",
            checkpoint_json={
                "protocol": "priority-paged-v1",
                "window": {
                    "start": WINDOW_START.isoformat(),
                    "end": WINDOW_END.isoformat(),
                    "timezone": "Asia/Shanghai",
                },
                "target": "refunds",
                "domains": {
                    "refunds": {"endpoint": "wrong-endpoint", "cursor": None, "completed": False}
                },
            },
        )
    )
    db_session.commit()
    client = _PagedRefundClient({None: _refund_page([], has_more=False)})

    with pytest.raises(PagedCollectionError, match="endpoint"):
        collect_priority_pages(_factory(db_session), client, job)
    assert client.calls == []


def test_all_target_advances_each_supported_domain_and_order_update_phase(
    db_session: Session,
):
    job = _job(db_session, target="all", job_id="all-domains-job")

    class Client:
        def __init__(self):
            self.calls: list[tuple[str, Any]] = []

        def query_orders(self, _start, _end, *, page_size, cursor=None, time_field="create_order"):
            self.calls.append((time_field, cursor))
            return {"data": {"orders": []}}

        def query_refunds(self, _start, _end, *, page_size, cursor=None):
            self.calls.append(("refunds", cursor))
            return _refund_page([], has_more=False)

        def query_clues(self, _start, _end, *, page, page_size):
            self.calls.append(("clues", page))
            return {"data": {"clue_data": []}}

        def query_verify_records(self, _start, _end, *, page_size, cursor=None):
            self.calls.append(("verify_records", cursor))
            return {"data": {"verify_records": [], "has_more": False}}

    client = Client()
    checkpoint = collect_priority_pages(_factory(db_session), client, job)

    assert checkpoint["completed"] is True
    assert all(
        state["completed"] for state in checkpoint["domains"].values()
    )
    assert ("create_order", None) in client.calls
    assert ("update_order", None) in client.calls
    assert ("refunds", None) in client.calls
    assert ("clues", 1) in client.calls
    assert ("verify_records", None) in client.calls
