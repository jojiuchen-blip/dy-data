from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import Base, JobRun, JobStageRun
from apps.worker.dimension_snapshot import reusable_dimension_snapshot


def test_history_reuses_only_fresh_actual_dimension_collection(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dimensions.db'}")
    Base.metadata.create_all(engine, tables=[JobRun.__table__, JobStageRun.__table__])
    factory = sessionmaker(engine)
    now = datetime(2026, 9, 10, 4, tzinfo=UTC)
    history = SimpleNamespace(job_id="history", config_version="priority-daily-v1", data_source="douyin",
                              metadata_json={"target": "all", "priority_purpose": "history"})
    with factory() as session:
        session.add(JobRun(job_id="range", job_name="range_sync", job_kind="range_sync", status="success"))
        source = JobRun(job_id="dimensions", job_name="parent_sync", job_kind="parent_sync", status="success",
                        parent_job_id="range", execution_slot="heavy_sync", config_version="priority-daily-v1",
                        data_source="douyin", window_start=now-timedelta(days=1), window_end=now)
        session.add(source)
        stage = JobStageRun(stage_run_id="dimensions-stage", job_id=source.job_id, stage_name="collect_dimensions",
                            status="success", lease_epoch=1, committed_at=now-timedelta(hours=1),
                            checkpoint_json={"phases": {"shop_pois": {"failed": 0}, "aweme_bindings": {"failed": 0}}})
        session.add(stage)
        session.commit()
        proof = reusable_dimension_snapshot(session, history, now=now)
        assert proof["dimension_snapshot_sources"]["shop_pois"]["job_id"] == source.job_id
        assert proof["phases"]["shop_pois"]["fetched"] == 0
        assert reusable_dimension_snapshot(session, history, now=now+timedelta(hours=2)) is None
        # A freshly committed reuse cannot renew a stale snapshot forever.
        stage.checkpoint_json = proof
        stage.committed_at = now
        session.commit()
        assert reusable_dimension_snapshot(session, history, now=now) is None


def test_history_dimension_handler_reuses_snapshot_before_creating_client(monkeypatch):
    from apps.worker.daily_task import default_stage_handlers

    proof = {"dimension_snapshot_reused": True, "phases": {}}
    monkeypatch.setattr(
        "apps.worker.dimension_snapshot.reusable_dimension_snapshot",
        lambda session, job: proof,
    )

    def unexpected_client():
        raise AssertionError("fresh dimension snapshot should avoid an API client")

    monkeypatch.setattr("apps.worker.pipeline.build_douyin_client_from_env", unexpected_client)
    assert default_stage_handlers()["collect_dimensions"](None, object()) is proof
