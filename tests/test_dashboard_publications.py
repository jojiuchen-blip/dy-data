"""Publication contracts; database rollback is exercised rather than mocked."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine, event, func, select, text, update
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.dashboard_publications.lifecycle import (
    PublicationError, cleanup_publications, pin_publication, publish_module,
    resolve_publication, unpin_publication,
)
from apps.api.dy_api.dashboard_publications.schema import heads, metadata, runs

test_metadata = MetaData()
runs.to_metadata(test_metadata)
facts = Table(
    "dashboard_publication_test_facts", test_metadata,
    Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("value", Integer, nullable=False),
)


@pytest.fixture()
def factory(tmp_path):
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "publications.db"))
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    metadata.create_all(engine)
    facts.create(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def build(session, publication_id, cutoff):
    session.execute(facts.insert().values(publication_id=publication_id, value=7))
    return {"row_count": 1}


def test_no_version_and_expired_id_are_read_only(factory):
    with factory() as session:
        for identifier, expected_code, expected_status in (
            (None, "PUBLICATION_NOT_READY", 503), ("missing", "PUBLICATION_EXPIRED", 410),
        ):
            with pytest.raises(PublicationError) as caught:
                resolve_publication(session, "sales", identifier)
            assert (caught.value.code, caught.value.http_status) == (expected_code, expected_status)
        assert session.scalar(select(func.count()).select_from(runs)) == 0


def test_publish_metadata_and_fixed_version(factory):
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    first = publish_module(factory, "sales", build, now=cutoff)
    second = publish_module(factory, "sales", build)
    with factory() as session:
        assert resolve_publication(session, "sales").id == second.id
        fixed = resolve_publication(session, "sales", first.id)
        assert fixed.id == first.id
        assert fixed.data_as_of is None
        assert fixed.published_at > fixed.cutoff
        assert fixed.meta()["status"] == "available"
        assert session.scalar(select(facts.c.value).where(facts.c.publication_id == fixed.id)) == 7
        with pytest.raises(PublicationError, match="过期"):
            resolve_publication(session, "other", first.id)


def test_failed_builder_rolls_back_facts_preserves_head_and_redacts_error(factory):
    first = publish_module(factory, "sales", build)

    def broken(session, publication_id, cutoff):
        build(session, publication_id, cutoff)
        raise ValueError("secret-cookie=must-never-appear")

    with pytest.raises(PublicationError) as caught:
        publish_module(factory, "sales", broken)
    assert "secret" not in str(caught.value)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(facts)) == 1
        assert resolve_publication(session, "sales").id == first.id
        assert resolve_publication(session, "sales").status == "failed"
        failed = session.execute(select(runs).where(runs.c.status == "failed")).mappings().one()
        assert failed["error_code"] == "PUBLICATION_BUILD_FAILED"
        assert failed["stats_json"] == {}


@pytest.mark.parametrize("operation", ["commit", "rollback_then_read"])
def test_builder_cannot_end_its_transaction(factory, operation):
    def broken(session, publication_id, cutoff):
        build(session, publication_id, cutoff)
        if operation == "commit":
            session.commit()
        else:
            session.rollback()
            session.execute(select(runs.c.id))
        return {}

    with pytest.raises(PublicationError):
        publish_module(factory, "sales", broken)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(facts)) == 0
        assert session.scalar(select(func.count()).select_from(heads)) == 0


def test_source_change_discards_version_and_unchanged_input_preserves_timestamps(factory):
    token = ["first"]
    first = publish_module(factory, "sales", build, fingerprint=lambda _: token[0])
    assert publish_module(factory, "sales", build, fingerprint=lambda _: token[0]) is None
    with factory() as session:
        assert resolve_publication(session, "sales").published_at == first.published_at

    def changed(session, publication_id, cutoff):
        token[0] = "changed-during-build"
        return build(session, publication_id, cutoff)

    token[0] = "new-before-build"
    with pytest.raises(PublicationError) as caught:
        publish_module(factory, "sales", changed, fingerprint=lambda _: token[0])
    assert caught.value.code == "PUBLICATION_SOURCE_CHANGED"
    with factory() as session:
        assert resolve_publication(session, "sales").id == first.id


def test_unchanged_source_after_refresh_interval_does_not_copy_facts(factory):
    first = publish_module(factory, "sales", build, fingerprint=lambda _: "stable")
    future = first.published_at + timedelta(minutes=10)
    assert publish_module(factory, "sales", build, fingerprint=lambda _: "stable", now=future) is None
    with factory() as session:
        current = resolve_publication(session, "sales")
        assert current.id == first.id
        assert current.published_at == first.published_at
        assert current.data_as_of == first.data_as_of
        assert current.next_refresh_at > first.next_refresh_at
        assert session.scalar(select(func.count()).select_from(facts)) == 1
    replacement = publish_module(factory, "sales", build, fingerprint=lambda _: "stable",
                                 now=future + timedelta(minutes=10), refresh_on_interval=True)
    assert replacement.id != first.id


def test_data_as_of_is_only_explicit_source_evidence(factory):
    observed = datetime.now(UTC) - timedelta(days=3)
    publication = publish_module(factory, "sales", lambda *_: {"data_as_of": observed, "row_count": 0})
    assert publication.data_as_of == observed
    assert publication.published_at > publication.data_as_of
    with pytest.raises(PublicationError):
        publish_module(factory, "sales", lambda *_: {"data_as_of": datetime.now(UTC) + timedelta(days=1)})


def test_retention_keeps_two_unpinned_plus_pin_active(factory):
    publications = [publish_module(factory, "sales", build) for _ in range(5)]
    old = datetime.now(UTC) - timedelta(hours=2)
    with factory.begin() as session:
        for index, publication in enumerate(publications):
            session.execute(update(runs).where(runs.c.id == publication.id).values(
                created_at=old + timedelta(seconds=index), published_at=old + timedelta(seconds=index),
            ))
        pin_publication(session, publications[0].id, reason="confirmed audit", actor="test")
        # Last two ordinary + pin remain, and projection cascade removes all
        # rows of the two obsolete complete versions.
        result = cleanup_publications(session)
        assert result["deleted"] == 2
    with factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(facts)) == 3
        assert resolve_publication(session, "sales").id == publications[-1].id
        unpin_publication(session, publications[0].id)
        assert cleanup_publications(session)["deleted"] == 1
    fresh = publish_module(factory, "sales", build)
    assert fresh
    with factory.begin() as session:
        assert cleanup_publications(session)["deleted"] == 1
        assert session.scalar(select(func.count()).select_from(runs)) == 2


def test_retention_never_relaxes_minimum_safety(factory):
    with factory() as session:
        with pytest.raises(ValueError):
            cleanup_publications(session, min_age=timedelta(seconds=-1))
        with pytest.raises(ValueError):
            cleanup_publications(session, keep=1)


def test_three_fresh_successes_immediately_keep_only_latest_two(factory):
    publications = [publish_module(factory, "sales", build) for _ in range(3)]
    with factory.begin() as session:
        assert cleanup_publications(session)["publication_ids"] == [publications[0].id]
        assert session.scalar(select(func.count()).select_from(facts)) == 2
        assert resolve_publication(session, "sales").id == publications[-1].id
    with factory.begin() as session:
        with pytest.raises(PublicationError) as caught:
            resolve_publication(session, "sales", publications[0].id)
        assert caught.value.http_status == 410


def test_explicit_nonnegative_grace_remains_available(factory):
    publications = [publish_module(factory, "sales", build) for _ in range(3)]
    with factory.begin() as session:
        assert cleanup_publications(session, min_age=timedelta(hours=1))["deleted"] == 0
        assert cleanup_publications(session, min_age=timedelta(0))["deleted"] == 1


def test_latest_failed_attempt_is_preserved_per_module_but_old_failures_are_removed(factory):
    head = publish_module(factory, "sales", build)
    def broken(*args):
        raise RuntimeError("not logged")
    for module in ("sales", "sales", "clue-overview"):
        with pytest.raises(PublicationError):
            publish_module(factory, module, broken)
    with factory.begin() as session:
        assert cleanup_publications(session)["deleted"] == 1
        assert resolve_publication(session, "sales").id == head.id
        assert resolve_publication(session, "sales").status == "failed"
        assert session.scalar(select(func.count()).select_from(runs).where(runs.c.status == "failed")) == 2


def test_source_guard_ignores_old_failures_but_defers_active_materialization(factory):
    from apps.api.dy_api.dashboard_publications.sources import assert_sources_ready
    with factory.begin() as session:
        session.execute(text("CREATE TABLE job_runs (job_id text, job_name text, job_kind text, status text, metadata_json json)"))
        session.execute(text("INSERT INTO job_runs VALUES ('old', 'settlement_rebuild', NULL, 'failed', '{}')"))
        assert_sources_ready(session)
        session.execute(text("INSERT INTO job_runs VALUES ('active', 'settlement_rebuild', NULL, 'running', '{}')"))
        with pytest.raises(PublicationError) as caught:
            assert_sources_ready(session)
        assert caught.value.code == "PUBLICATION_SOURCE_BUSY"


@pytest.mark.parametrize("status,metadata_json", [
    ("running", '{"needs_downstream_processing":false}'),
    ("partial", '{"needs_downstream_processing":false}'),
    ("failed", '{"needs_downstream_processing":true}'),
    ("success", '{"needs_downstream_processing":true}'),
    ("success", '{}'),
])
def test_refund_repair_does_not_release_dashboard_before_downstream_validation(factory, status, metadata_json):
    from apps.api.dy_api.dashboard_publications.sources import assert_sources_ready
    with factory.begin() as session:
        session.execute(text("CREATE TABLE job_runs (job_id text, job_name text, job_kind text, status text, metadata_json json)"))
        session.execute(text("INSERT INTO job_runs VALUES ('repair', 'refund_evidence_replay', NULL, :status, :metadata)"),
                        {"status": status, "metadata": metadata_json})
        with pytest.raises(PublicationError) as caught:
            assert_sources_ready(session)
        assert caught.value.code == "PUBLICATION_SOURCE_BUSY"
        assert_sources_ready(session, exclude_repair_run_id="repair")
        session.execute(text("INSERT INTO job_runs VALUES ('source', 'collect_once', NULL, 'running', '{}')"))
        with pytest.raises(PublicationError):
            assert_sources_ready(session, exclude_repair_run_id="source")


def test_refund_repair_verified_completion_and_heavy_claim_lock(factory):
    from apps.api.dy_api.dashboard_publications.sources import assert_sources_ready, writer_lock_keys
    from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
    assert HEAVY_SYNC_CLAIM_LOCK_KEY in writer_lock_keys()
    with factory.begin() as session:
        session.execute(text("CREATE TABLE job_runs (job_id text, job_name text, job_kind text, status text, metadata_json json)"))
        session.execute(text("INSERT INTO job_runs VALUES ('repair', 'refund_evidence_replay', NULL, 'success', :metadata)"),
                        {"metadata": '{"needs_downstream_processing":false}'})
        assert_sources_ready(session)


def test_source_dependency_names_exist_in_actual_schemas():
    from apps.api.dy_api.dashboard_publications.sources import SOURCE_TABLES
    from apps.api.dy_api.models import Base
    from apps.api.dy_api.ranking_schema_v1 import metadata as ranking_metadata
    assert set(SOURCE_TABLES) <= set(Base.metadata.tables) | set(ranking_metadata.tables)


def test_runtime_registry_and_injected_builder_tick(factory, monkeypatch):
    from apps.worker.dashboard_publications import load_builder, run_tick
    with pytest.raises(PublicationError) as caught:
        load_builder("unknown")
    assert caught.value.code == "PUBLICATION_MODULE_UNKNOWN"
    results = run_tick(factory, {"sales": build}, guarded=False)
    assert results == {"sales": "published"}


def test_worker_cleanup_does_not_erase_its_latest_failure(factory):
    from apps.worker.dashboard_publications import run_tick
    publication = publish_module(factory, "sales", build)
    def broken(*args):
        raise RuntimeError("not logged")
    assert run_tick(factory, {"sales": broken}, guarded=False) == {"sales": "PUBLICATION_BUILD_FAILED"}
    with factory() as session:
        current = resolve_publication(session, "sales")
        assert current.id == publication.id and current.status == "failed"


def test_read_only_ready_gate_and_busy_first_build_exit_codes(factory, monkeypatch):
    from apps.worker import dashboard_publications as worker
    monkeypatch.setattr(worker, "get_session_factory", lambda: factory)
    # A check must never execute this builder.
    def forbidden(*args):
        raise AssertionError("readiness invoked builder")
    monkeypatch.setattr(worker, "load_builder", lambda _: forbidden)
    assert worker.main(["--check-ready", "--module", "sales"]) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(runs)) == 0
    monkeypatch.setattr(worker, "run_tick", lambda *args, **kwargs: {"sales": "PUBLICATION_SOURCE_BUSY"})
    assert worker.main(["--once", "--require-ready", "--module", "sales"]) == 1
    publish_module(factory, "sales", build)
    assert worker.main(["--once", "--require-ready", "--module", "sales"]) == 0
    assert worker.main(["--check-ready", "--module", "sales"]) == 0


def test_failed_same_input_is_retried_instead_of_becoming_permanent(factory):
    first = publish_module(factory, "sales", build, fingerprint=lambda _: "stable")
    def broken(*args):
        raise RuntimeError("failure")
    with pytest.raises(PublicationError):
        publish_module(factory, "sales", broken, fingerprint=lambda _: "stable", force=True)
    replacement = publish_module(factory, "sales", build, fingerprint=lambda _: "stable")
    assert replacement.id != first.id
    with factory() as session:
        assert resolve_publication(session, "sales").status == "available"


def test_compose_runs_publications_as_an_independent_bounded_service():
    import re
    compose = (Path(__file__).resolve().parents[1] / "deploy/compose.yaml").read_text(encoding="utf-8")
    service = re.search(r"(?ms)^  publication-worker:\n(.*?)(?=^  [a-z0-9_-]+:\n)", compose).group(1)
    assert '"apps.worker.dashboard_publications"' in service
    assert "PUBLICATION_POLL_SECONDS" in service
    assert "PUBLICATION_BUILD_TIMEOUT_SECONDS" in service
    assert "mem_limit:" in service
    assert "cpus:" in service
    assert "DOUYIN_APP_SECRET" not in service
    assert "condition: service_completed_successfully" in service
