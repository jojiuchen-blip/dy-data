"""Frozen DDL parity and complete-chain PostgreSQL publication migrations."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from apps.api.dy_api.dashboard_publications import clues, finance, ranking, sales  # noqa: F401
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.api.dy_api.dashboard_publications.sources import SOURCE_TABLES, source_fingerprint
from apps.api.dy_api.models import Base, DimStore
from apps.api.dy_api.ranking_schema_v1 import metadata as ranking_metadata

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic/versions/20261019_0063_dashboard_publications.py"


def migration():
    spec = importlib.util.spec_from_file_location("publication_migration_0063", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ddl_lines(table, dialect):
    return sorted(line.strip().rstrip(",") for line in str(CreateTable(table).compile(dialect=dialect)).splitlines() if line.strip())


def test_frozen_migration_has_no_runtime_import_and_matches_final_schema():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "from apps." not in source and "import apps." not in source
    frozen = migration().frozen_metadata_0063()
    assert set(frozen.tables) == set(metadata.tables)
    assert set(migration().SOURCE_TABLES_0063) == set(SOURCE_TABLES) - {"historical_sale_attribution_decisions"}
    cycle_sort = frozen.tables["dashboard_publication_sales_coupons"].c.cycle_sort_days
    assert cycle_sort.nullable and cycle_sort.default is None and cycle_sort.server_default is None
    assert (cycle_sort.type.precision, cycle_sort.type.scale) == (24, 2)
    assert not any("cycle_sort_days" in index.columns for index in cycle_sort.table.indexes)
    for dialect in (postgresql.dialect(), sqlite.dialect()):
        for name, table in metadata.tables.items():
            assert _ddl_lines(table, dialect) == _ddl_lines(frozen.tables[name], dialect), name
            assert {str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes} == {
                str(CreateIndex(index).compile(dialect=dialect)) for index in frozen.tables[name].indexes
            }, name


def test_latest_migration_adds_only_sidecars_and_can_downgrade_when_unused(tmp_path):
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "migration.sqlite"))
    Base.metadata.create_all(engine)
    ranking_metadata.create_all(engine)
    revision = migration()
    with Session(engine) as session:
        session.add(DimStore(store_id="migration-store", store_name="Migration Store"))
        session.commit()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
    with Session(engine) as session:
        assert source_fingerprint(session, "sales")
        assert session.get(DimStore, "migration-store").store_name == "Migration Store"
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            revision.downgrade()
    assert "dashboard_publication_runs" not in inspect(engine).get_table_names()
    assert "dim_stores" in inspect(engine).get_table_names()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
        connection.execute(runs.insert().values(id="failed-attempt", module="sales", status="failed",
            cutoff=text("CURRENT_TIMESTAMP"), created_at=text("CURRENT_TIMESTAMP"), stats_json={}))
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="contain data"):
            revision.downgrade()
    engine.dispose()


@pytest.fixture()
def full_pg_stack(monkeypatch):
    raw = os.getenv("DYDATA_PUBLICATION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set DYDATA_PUBLICATION_TEST_DATABASE_URL to a disposable local PostgreSQL test database")
    url = make_url(raw)
    assert url.host in {"127.0.0.1", "localhost", "::1"} and url.database and "test" in url.database
    schema = "publication_migration_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = url.update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("DY_DATABASE_URL", isolated.render_as_string(hide_password=False))
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    engine = create_engine(isolated)
    try:
        yield config, engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("populated", [False, True])
def test_clean_and_populated_full_postgres_chain_upgrade(full_pg_stack, populated):
    config, engine = full_pg_stack
    if populated:
        command.upgrade(config, "20261009_0062")
        with Session(engine) as session:
            session.add(DimStore(store_id="migration-store", store_name="Migration Store"))
            session.commit()
    command.upgrade(config, "head")
    with Session(engine) as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20261023_0065"
        assert session.scalar(text("SELECT count(*) FROM dashboard_publication_source_counters")) == 43
        assert source_fingerprint(session, "sales")
        if populated:
            assert session.get(DimStore, "migration-store").store_name == "Migration Store"
        assert session.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname='dashboard_publication_change' "
                                   "AND tgrelid IN (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                   "WHERE n.nspname=current_schema())")) == 43
    # The new revision itself is reversible before any sidecar facts exist;
    # source facts survive and can be tracked again after re-upgrading.
    command.downgrade(config, "20261009_0062")
    command.upgrade(config, "head")
    assert set(metadata.tables) <= set(inspect(engine).get_table_names())
    columns = {column["name"]: column for column in inspect(engine).get_columns("dashboard_publication_sales_coupons")}
    assert columns["cycle_sort_days"]["nullable"] and columns["cycle_sort_days"]["default"] is None
    assert (columns["cycle_sort_days"]["type"].precision, columns["cycle_sort_days"]["type"].scale) == (24, 2)
