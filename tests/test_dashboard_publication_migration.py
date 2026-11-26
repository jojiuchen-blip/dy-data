"""Frozen DDL parity and complete-chain PostgreSQL publication migrations."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
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


def task_publication_migration():
    path = ROOT / "alembic/versions/20261119_0071_clue_task_publications.py"
    spec = importlib.util.spec_from_file_location("publication_migration_0070", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial_publication_migration():
    path = ROOT / "alembic/versions/20261120_0073_fee_trial.py"
    spec = importlib.util.spec_from_file_location("publication_migration_0073", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ddl_lines(table, dialect):
    return sorted(line.strip().rstrip(",") for line in str(CreateTable(table).compile(dialect=dialect)).splitlines() if line.strip())


def test_frozen_migration_has_no_runtime_import_and_matches_final_schema(monkeypatch):
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "from apps." not in source and "import apps." not in source
    frozen = migration().frozen_metadata_0063()
    later = task_publication_migration()
    assert "from apps." not in Path(later.__file__).read_text(encoding="utf-8")
    # Compare the current sidecar against immutable 0063 plus the additive
    # frozen revision. Never edit the executed 0063 schema to match new code.
    import sqlalchemy as sa
    for table, fields in (("dashboard_publication_clue_rounds", later.TASK_COLUMNS),
                          ("dashboard_ranking_rounds", later.RANKING_COLUMNS)):
        for field in fields:
            assert field not in frozen.tables[table].c
            frozen.tables[table].append_column(sa.Column(field, sa.Integer(), nullable=False, server_default="0"))
    frozen.tables["dashboard_ranking_rounds"].append_column(sa.Column("task_under_observation", sa.Boolean(),
        nullable=False, server_default=sa.false()))
    later.frozen_metadata_0070().tables[later.VERIFICATION_TABLE].to_metadata(frozen)
    # Replay the later migration's actual frozen DDL declarations. Capture
    # its operations without deriving the expected schema from runtime tables.
    trial = trial_publication_migration()
    trial_source = Path(trial.__file__).read_text(encoding="utf-8")
    assert "from apps." not in trial_source and "import apps." not in trial_source
    before_trial = set(frozen.tables)
    operations = SimpleNamespace(
        create_table=lambda name, *columns, **options: sa.Table(name, frozen, *columns, **options),
        create_index=lambda name, table, columns, **options: sa.Index(
            name, *(frozen.tables[table].c[column] for column in columns), **options),
        get_bind=lambda: SimpleNamespace(dialect=sqlite.dialect()),
        execute=lambda statement: None,
    )
    monkeypatch.setattr(trial, "op", operations)
    trial.upgrade()
    assert set(frozen.tables) - before_trial == {"dashboard_publication_fee_trial"}
    assert set(frozen.tables) == set(metadata.tables)
    # Later additive migrations own these counters; the 0063 DDL stays frozen.
    later_sources = {
        "historical_sale_attribution_decisions", "account_qualification_version", "ranking_area_corrections",
        "settlement_month_close", "settlement_statement_balance", "settlement_statement_visibility",
        "raw_douyin_refund_records", "douyin_refund_event",
        "clue_order_status_events",
        *trial.SOURCE_TABLES,
    }
    assert later_sources <= set(SOURCE_TABLES)
    assert set(migration().SOURCE_TABLES_0063) == set(SOURCE_TABLES) - later_sources
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
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20261126_0076"
        assert session.scalar(text("SELECT count(*) FROM dashboard_publication_source_counters")) == len(SOURCE_TABLES)
        assert source_fingerprint(session, "sales")
        if populated:
            assert session.get(DimStore, "migration-store").store_name == "Migration Store"
        assert session.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname='dashboard_publication_change' "
                                   "AND tgrelid IN (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                   "WHERE n.nspname=current_schema())")) == len(SOURCE_TABLES)
    # The new revision itself is reversible before any sidecar facts exist;
    # source facts survive and can be tracked again after re-upgrading.
    command.downgrade(config, "20261009_0062")
    command.upgrade(config, "head")
    assert set(metadata.tables) <= set(inspect(engine).get_table_names())
    columns = {column["name"]: column for column in inspect(engine).get_columns("dashboard_publication_sales_coupons")}
    assert columns["cycle_sort_days"]["nullable"] and columns["cycle_sort_days"]["default"] is None
    assert (columns["cycle_sort_days"]["type"].precision, columns["cycle_sort_days"]["type"].scale) == (24, 2)


def test_production_0071_upgrades_to_monthly_evidence_and_trial(full_pg_stack):
    config, engine = full_pg_stack
    command.upgrade(config, "20261119_0071")
    with Session(engine) as session:
        session.add(DimStore(store_id="pre-trial-store", store_name="Original Store"))
        session.commit()

    command.upgrade(config, "head")
    with Session(engine) as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20261126_0076"
        assert session.get(DimStore, "pre-trial-store").store_name == "Original Store"
    schema = inspect(engine)
    assert {"monthly_store_evidence_snapshot", "dashboard_publication_fee_trial"} <= set(schema.get_table_names())
    assert schema.get_pk_constraint("dashboard_publication_fee_trial")["constrained_columns"] == ["publication_id", "row_id"]
    assert "uq_mses_qualification_content" in {
        item["name"] for item in schema.get_unique_constraints("monthly_store_evidence_snapshot")
    }
    assert {"ck_pub_fee_trial_direction", "ck_pub_fee_trial_status", "ck_pub_fee_trial_known_amount"} <= {
        item["name"] for item in schema.get_check_constraints("dashboard_publication_fee_trial")
    }
    trial_columns = {item["name"]: item for item in schema.get_columns("dashboard_publication_fee_trial")}
    assert trial_columns["fee_amount_cent"]["nullable"] and trial_columns["base_amount_cent"]["nullable"]
    assert "ix_pub_fee_trial_filter" in {item["name"] for item in schema.get_indexes("dashboard_publication_fee_trial")}
    with engine.connect() as connection:
        guards = set(connection.execute(text("""
            SELECT t.tgname FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=current_schema() AND c.relname='monthly_store_evidence_snapshot'
                AND NOT t.tgisinternal AND t.tgenabled <> 'D'
        """)).scalars())
        assert {"monthly_store_evidence_guard", "monthly_store_evidence_no_truncate"} <= guards
        assert connection.scalar(text("SELECT count(*) FROM dashboard_publication_source_counters WHERE source_name='data_quality_issues'")) == 1
