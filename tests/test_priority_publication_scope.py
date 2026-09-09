from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import Base, JobRun, JobStageRun
from apps.worker.daily_windows import plan_daily_sync
from apps.worker.publication_scope import include_completed_domain_scope


def test_full_day_inherits_already_consumed_domain_publication_scope(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'publication.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        jobs = []
        for target in ("orders", "all"):
            plan = plan_daily_sync(session, start="2026-09-09", end="2026-09-10", target=target,
                                   requested_by="test", trigger_source="manual", config_version="priority-daily-v1")
            jobs.append(session.get(JobRun, plan.daily_jobs[0].job_id))
        source, destination = jobs
        source.status = "success"
        now = datetime.now(UTC)
        stage = JobStageRun(stage_run_id="scope-settle", job_id=source.job_id, stage_name="settle",
                            status="success", lease_epoch=1, committed_at=now,
                            checkpoint_json={"settlement_summary": {"completed": True,
                                "affected_months": ["2026-08", "2026-09"], "affected_store_ids": ["store-a"]}})
        session.add(stage)
        session.commit()
    summary = {"affected_months": [], "affected_store_ids": [], "impact_count": 0, "completed": True}
    result = include_completed_domain_scope(factory, destination, summary)
    assert result["affected_months"] == ["2026-08", "2026-09"]
    assert result["affected_store_ids"] == ["store-a"]
    assert result["impact_count"] == 0  # real counts are not fabricated
    assert result["publication_predecessors"][0]["job_id"] == source.job_id
    with factory() as session:
        session.get(JobRun, source.job_id).status = "failed"
        session.commit()
    with pytest.raises(RuntimeError, match="must finish"):
        include_completed_domain_scope(factory, destination, summary)
