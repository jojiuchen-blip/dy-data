"""Real PostgreSQL isolation/locking gates in a disposable loopback schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
import subprocess
import sys
from threading import Event
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.dashboard_publications.lifecycle import (
    PublicationError, cleanup_publications, publish_module, resolve_publication,
)
from apps.api.dy_api.dashboard_publications.schema import metadata, runs


@pytest.fixture()
def pg_factory():
    raw = os.getenv("DYDATA_PUBLICATION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set DYDATA_PUBLICATION_TEST_DATABASE_URL to a disposable local PostgreSQL test database")
    url = make_url(raw)
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert url.database and "test" in url.database
    schema = "dashboard_publication_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=2000"})
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE test_source (id integer PRIMARY KEY, value integer NOT NULL)"))
        connection.execute(text("INSERT INTO test_source VALUES (1, 1)"))
        connection.execute(text("CREATE TABLE test_projection (publication_id varchar(64) PRIMARY KEY "
                                "REFERENCES dashboard_publication_runs(id) ON DELETE CASCADE, value integer)"))
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def pg_build(session, publication_id, cutoff):
    assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
    session.execute(text("INSERT INTO test_projection VALUES (:id, 7)"), {"id": publication_id})
    return {"row_count": 1}


def test_real_atomic_failure_keeps_previous_head(pg_factory):
    previous = publish_module(pg_factory, "sales", pg_build)

    def broken(session, publication_id, cutoff):
        pg_build(session, publication_id, cutoff)
        raise RuntimeError("private source payload")

    with pytest.raises(PublicationError):
        publish_module(pg_factory, "sales", broken)
    with pg_factory() as session:
        assert resolve_publication(session, "sales").id == previous.id
        assert session.scalar(text("SELECT count(*) FROM test_projection")) == 1
        assert session.scalar(select(func.count()).select_from(runs).where(runs.c.status == "failed")) == 1


def test_reader_sees_old_version_until_complete_commit_and_builder_mutex(pg_factory):
    previous = publish_module(pg_factory, "sales", pg_build)
    entered, release = Event(), Event()

    def waiting(session, publication_id, cutoff):
        result = pg_build(session, publication_id, cutoff)
        entered.set()
        assert release.wait(10)
        return result

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(publish_module, pg_factory, "sales", waiting)
        try:
            assert entered.wait(10)
            with pg_factory() as session:
                current = resolve_publication(session, "sales")
                assert current.id == previous.id
                assert current.status == "refreshing"
                assert session.scalar(text("SELECT count(*) FROM test_projection")) == 1
            assert publish_module(pg_factory, "sales", pg_build) is None
        finally:
            release.set()
        replacement = future.result(timeout=10)
    with pg_factory() as session:
        assert resolve_publication(session, "sales").id == replacement.id


def test_cleanup_skips_read_lock_then_cascades_only_analytical_rows(pg_factory):
    publications = [publish_module(pg_factory, "sales", pg_build) for _ in range(3)]
    with pg_factory() as reader:
        resolve_publication(reader, "sales", publications[0].id)
        with pg_factory.begin() as cleaner:
            assert cleanup_publications(cleaner)["deleted"] == 0
        reader.rollback()
    with pg_factory.begin() as cleaner:
        assert cleanup_publications(cleaner)["deleted"] == 1
    with pg_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM test_projection")) == 2
        assert session.scalar(text("SELECT value FROM test_source")) == 1


def test_three_fresh_postgres_versions_immediately_delete_first_and_preserve_failed_status(pg_factory):
    publications = [publish_module(pg_factory, "sales", pg_build) for _ in range(3)]
    with pg_factory.begin() as session:
        assert cleanup_publications(session)["publication_ids"] == [publications[0].id]
        assert session.scalar(text("SELECT count(*) FROM test_projection")) == 2
    def broken(*args):
        raise RuntimeError("not logged")
    for _ in range(2):
        with pytest.raises(PublicationError):
            publish_module(pg_factory, "sales", broken)
    with pg_factory.begin() as session:
        failures = session.execute(select(runs.c.id).where(runs.c.status == "failed")
                                   .order_by(runs.c.created_at, runs.c.id)).scalars().all()
        assert cleanup_publications(session)["publication_ids"] == [failures[0]]
        assert resolve_publication(session, "sales").status == "failed"
        assert session.scalar(select(func.count()).select_from(runs).where(runs.c.status == "failed")) == 1
        assert session.scalar(text("SELECT count(*) FROM test_projection")) == 2


def test_source_commit_during_repeatable_read_is_detected_by_observer(pg_factory):
    previous = publish_module(pg_factory, "sales", pg_build)
    observed = []

    def fingerprint(session):
        return str(session.scalar(text("SELECT value FROM test_source WHERE id=1")))

    def changing(session, publication_id, cutoff):
        observed.append(session.scalar(text("SELECT value FROM test_source WHERE id=1")))
        with pg_factory.begin() as writer:
            writer.execute(text("UPDATE test_source SET value=2 WHERE id=1"))
        observed.append(session.scalar(text("SELECT value FROM test_source WHERE id=1")))
        return pg_build(session, publication_id, cutoff)

    with pytest.raises(PublicationError) as caught:
        publish_module(pg_factory, "sales", changing, fingerprint=fingerprint)
    assert caught.value.code == "PUBLICATION_SOURCE_CHANGED"
    assert observed == [1, 1]
    with pg_factory() as session:
        assert resolve_publication(session, "sales").id == previous.id
        assert session.scalar(text("SELECT count(*) FROM test_projection")) == 1


def test_shared_writer_lock_defers_build_without_leaking_connection_lock(pg_factory):
    key = 987654321
    with pg_factory() as writer:
        writer.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        assert publish_module(pg_factory, "sales", pg_build, shared_lock_keys=(key,)) is None
        writer.rollback()
    assert publish_module(pg_factory, "sales", pg_build, shared_lock_keys=(key,)) is not None
    with pg_factory() as writer:
        assert writer.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}) is True


def test_statement_tracking_covers_mutation_rollback_and_missing_counter(pg_factory):
    from sqlalchemy.exc import DBAPIError
    from apps.api.dy_api.dashboard_publications.schema import source_counters
    from apps.api.dy_api.dashboard_publications.sources import MODULE_SOURCE_TABLES, source_fingerprint, tracking_ddl

    with pg_factory.begin() as session:
        for name in MODULE_SOURCE_TABLES["sales"]:
            session.execute(text(f'CREATE TABLE "{name}" (id integer PRIMARY KEY, value integer)'))
            for statement in tracking_ddl(name):
                session.execute(text(statement))
    with pg_factory() as session:
        before = source_fingerprint(session, "sales")
        tokens = [before]
        for statement in (
            "INSERT INTO settlement_order_details VALUES (1, 1)",
            "UPDATE settlement_order_details SET value=2",
            "DELETE FROM settlement_order_details",
            "TRUNCATE settlement_order_details",
        ):
            session.execute(text(statement))
            tokens.append(source_fingerprint(session, "sales"))
        assert len(set(tokens)) == 5
        session.rollback()
        assert source_fingerprint(session, "sales") == before
    previous = publish_module(pg_factory, "sales", pg_build)
    with pg_factory.begin() as session:
        session.execute(source_counters.delete().where(source_counters.c.source_name == "settlement_order_details"))
    with pg_factory() as session:
        with pytest.raises(PublicationError) as caught:
            source_fingerprint(session, "sales")
        assert caught.value.code == "PUBLICATION_SOURCE_TRACKING_INCOMPLETE"
    with pg_factory() as session:
        with pytest.raises(DBAPIError, match="counter missing"):
            session.execute(text("INSERT INTO settlement_order_details VALUES (1, 1)"))
        session.rollback()
    with pytest.raises(PublicationError):
        publish_module(pg_factory, "sales", pg_build, fingerprint=lambda session: source_fingerprint(session, "sales"))
    with pg_factory() as session:
        assert resolve_publication(session, "sales").id == previous.id


def _prepare_timed_sources(factory):
    from apps.api.dy_api.models import Base
    from apps.api.dy_api.ranking_schema_v1 import metadata as ranking_metadata
    from apps.api.dy_api.dashboard_publications.schema import source_counters
    from apps.api.dy_api.dashboard_publications.sources import SOURCE_TABLES
    with factory() as session:
        engine = session.get_bind()
    # Create this reproduction's real source relations and their FK closure,
    # rather than rebuilding unrelated billing/admin schemas for every case.
    names = {"dim_stores", "dim_sku_product_rules", "raw_douyin_orders", "raw_douyin_clues",
             "clue_center_orders", "clue_master_leads", "clue_assignment_rounds",
             "dim_store_org_assignments", "job_runs"}
    pending = list(names)
    while pending:
        table = Base.metadata.tables[pending.pop()]
        for foreign_key in table.foreign_keys:
            target = foreign_key.column.table.name
            if target not in names:
                names.add(target)
                pending.append(target)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in names])
    ranking_metadata.tables["ranking_store_org_history"].create(engine)
    metadata.create_all(engine)
    with factory.begin() as session:
        session.execute(source_counters.insert(), [
            {"source_name": name, "generation": 0, "changed_at": datetime.now(UTC)} for name in SOURCE_TABLES
        ])


def test_future_clue_organization_becomes_effective_without_source_dml(pg_factory):
    from apps.api.dy_api.dashboard_publications import clues
    from apps.api.dy_api.dashboard_publications.schema import source_counters
    from apps.api.dy_api.models import DimStore
    from apps.api.dy_api.ranking_schema_v1 import org_history
    from apps.worker.dashboard_publications import run_tick
    _prepare_timed_sources(pg_factory)
    before = datetime(2026, 10, 19, 15, tzinfo=UTC)
    after = datetime(2026, 10, 20, 15, tzinfo=UTC)
    with pg_factory.begin() as session:
        session.add(DimStore(store_id="timed-store", store_name="Timed Store"))
        session.execute(org_history.insert(), [
            {"mapping_version": "old", "store_id": "timed-store", "service_store_code": "timed-store",
             "store_name": "Timed Store", "group_name": "Old Group", "source_hash": "old",
             "effective_from": datetime(2026, 10, 1, tzinfo=UTC)},
            {"mapping_version": "future", "store_id": "timed-store", "service_store_code": "timed-store",
             "store_name": "Timed Store", "group_name": "New Group", "source_hash": "future",
             "effective_from": datetime(2026, 10, 20, tzinfo=UTC)},
        ])
    assert run_tick(pg_factory, {"clue-overview": clues.build}, now=before) == {"clue-overview": "published"}
    with pg_factory() as session:
        first_id = resolve_publication(session, "clue-overview").id
        assert session.scalar(select(clues.organizations.c.group_name).where(clues.organizations.c.publication_id == first_id)) == "Old Group"
        counter_values = session.execute(select(source_counters.c.source_name, source_counters.c.generation)).all()
    # Arbitrarily many polling ticks before the actual boundary reuse the head.
    assert run_tick(pg_factory, {"clue-overview": clues.build}, now=before + timedelta(hours=1)) == {"clue-overview": "unchanged_or_busy"}
    assert run_tick(pg_factory, {"clue-overview": clues.build}, now=after) == {"clue-overview": "published"}
    with pg_factory() as session:
        second_id = resolve_publication(session, "clue-overview").id
        assert second_id != first_id
        assert session.scalar(select(clues.organizations.c.group_name).where(clues.organizations.c.publication_id == second_id)) == "New Group"
        assert session.scalar(select(clues.organizations.c.group_name).where(clues.organizations.c.publication_id == first_id)) == "Old Group"
        assert session.execute(select(source_counters.c.source_name, source_counters.c.generation)).all() == counter_values


@pytest.mark.parametrize("module", ["finance", "settlement"])
def test_shanghai_month_boundary_rebuilds_without_source_changes(pg_factory, module):
    from apps.api.dy_api.dashboard_publications.finance import _months_through
    from apps.api.dy_api.dashboard_publications.schema import source_counters
    from apps.worker.dashboard_publications import run_tick
    _prepare_timed_sources(pg_factory)
    before = datetime(2026, 10, 31, 15, 59, tzinfo=UTC)
    after = datetime(2026, 10, 31, 16, 6, tzinfo=UTC)
    def builder(session, publication_id, cutoff):
        pg_build(session, publication_id, cutoff)
        return {"last_month": _months_through({"2026-08"}, cutoff)[-1]}
    assert run_tick(pg_factory, {module: builder}, now=before) == {module: "published"}
    with pg_factory() as session:
        first_id = resolve_publication(session, module).id
        assert session.scalar(select(runs.c.stats_json).where(runs.c.id == first_id))["last_month"] == "2026-10"
        before_counters = session.execute(select(source_counters.c.source_name, source_counters.c.generation)).all()
    assert run_tick(pg_factory, {module: builder}, now=before + timedelta(seconds=30)) == {module: "unchanged_or_busy"}
    assert run_tick(pg_factory, {module: builder}, now=after) == {module: "published"}
    with pg_factory() as session:
        second_id = resolve_publication(session, module).id
        assert second_id != first_id
        assert session.scalar(select(runs.c.stats_json).where(runs.c.id == second_id))["last_month"] == "2026-11"
        assert session.execute(select(source_counters.c.source_name, source_counters.c.generation)).all() == before_counters


def test_killed_real_builder_is_failed_before_busy_source_check(pg_factory):
    previous = publish_module(pg_factory, "sales", pg_build)
    with pg_factory() as session:
        engine = session.get_bind()
        schema = session.scalar(text("SELECT current_schema()"))
    # A real subprocess owns the module advisory lock and commits a visible
    # building attempt, then sleeps while its uncommitted projection exists.
    child = r'''
import sys, time
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from apps.api.dy_api.dashboard_publications.lifecycle import publish_module
engine = create_engine(sys.argv[1])
factory = sessionmaker(engine)
def builder(session, publication_id, cutoff):
    session.execute(text("INSERT INTO test_projection VALUES (:id, 99)"), {"id": publication_id})
    time.sleep(120)
    return {}
publish_module(factory, "sales", builder)
'''
    child_url = engine.url.update_query_dict({"options": "-csearch_path=" + schema})
    process = subprocess.Popen([sys.executable, "-c", child, child_url.render_as_string(hide_password=False)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    abandoned = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with pg_factory() as session:
                abandoned = session.scalar(select(runs.c.id).where(runs.c.module == "sales", runs.c.status == "building"))
            if abandoned:
                break
            time.sleep(0.05)
        assert abandoned is not None and process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=5)
    # Waiting for the OS process is not a PostgreSQL disconnect barrier,
    # especially across Windows/Docker networking. Wait on the actual module
    # lock, with database-enforced bounds, before testing abandoned recovery.
    # Otherwise publish_module may correctly return None for a still-held lock.
    from apps.api.dy_api.dashboard_publications.lifecycle import _lock_key
    with pg_factory() as disconnect_barrier:
        disconnect_barrier.execute(text("SET LOCAL lock_timeout = '10s'"))
        disconnect_barrier.execute(text("SET LOCAL statement_timeout = '12s'"))
        disconnect_barrier.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key("sales")})
        disconnect_barrier.rollback()
    def busy(session):
        raise PublicationError("PUBLICATION_SOURCE_BUSY", "busy", 503)
    with pytest.raises(PublicationError) as caught:
        publish_module(pg_factory, "sales", pg_build, readiness_check=busy)
    assert caught.value.code == "PUBLICATION_SOURCE_BUSY"
    with pg_factory.begin() as session:
        assert session.scalar(select(runs.c.status).where(runs.c.id == abandoned)) == "failed"
        assert session.scalar(select(runs.c.error_code).where(runs.c.id == abandoned)) == "PUBLICATION_INTERRUPTED"
        cleanup_publications(session)
        current = resolve_publication(session, "sales")
        assert current.id == previous.id and current.status == "failed"
        assert session.scalar(text("SELECT count(*) FROM test_projection")) == 1


def test_abandoned_status_repaired_even_when_writer_advisory_lock_is_busy(pg_factory):
    publication = publish_module(pg_factory, "sales", pg_build)
    with pg_factory.begin() as session:
        session.execute(runs.insert().values(id="abandoned", module="sales", status="building",
                        cutoff=datetime.now(UTC), created_at=datetime.now(UTC), stats_json={}))
    with pg_factory() as writer:
        writer.execute(text("SELECT pg_advisory_xact_lock(543219876)"))
        assert publish_module(pg_factory, "sales", pg_build, shared_lock_keys=(543219876,)) is None
    with pg_factory() as session:
        current = resolve_publication(session, "sales")
        assert current.id == publication.id and current.status == "failed"
