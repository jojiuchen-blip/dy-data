"""Real PostgreSQL isolation/locking gates in a disposable loopback schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from threading import Event
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
