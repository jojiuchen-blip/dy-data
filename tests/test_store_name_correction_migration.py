"""The historical name repair must not change identity or business facts."""

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select, text

from apps.api.dy_api.ranking_schema_v1 import (
    eligibility, lead_bindings, metadata, org_history, runs, samples, snapshots,
)


REVISION = "20261008_0061"
PREVIOUS = "20260916_0060"
AUDIT = "ranking_store_name_correction_0061"
FIRST_ID = "7380305331350308915"
SECOND_ID = "7402151814281398298"
FIRST_CODE = "BYDEFJ008W"
SECOND_CODE = "BYDFJ062W"
LONGCHANGHONG = "福建龙长鸿汽车销售服务有限公司"
LONGDIXIN = "福建龙迪鑫汽车销售服务有限公司"
AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.delenv("DY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{(tmp_path / 'names.sqlite').as_posix()}")
    command.upgrade(config, PREVIOUS)
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    yield config, engine
    engine.dispose()


def _seed(engine):
    rows = [
        ("old", FIRST_ID, FIRST_CODE, LONGCHANGHONG),
        ("current", FIRST_ID, FIRST_CODE, LONGCHANGHONG),
        ("old", SECOND_ID, SECOND_CODE, LONGDIXIN),
        ("current", SECOND_ID, SECOND_CODE, LONGDIXIN),
        ("already-correct", FIRST_ID, FIRST_CODE, LONGDIXIN),
        ("already-correct", SECOND_ID, SECOND_CODE, LONGCHANGHONG),
        ("wrong-code", FIRST_ID, SECOND_CODE, LONGCHANGHONG),
        ("wrong-code", SECOND_ID, FIRST_CODE, LONGDIXIN),
        ("unrelated", "other-store", FIRST_CODE, LONGCHANGHONG),
        ("later-name", FIRST_ID, FIRST_CODE, "later legal name"),
    ]
    with engine.begin() as connection:
        connection.execute(org_history.insert(), [dict(
            mapping_version=version, store_id=store_id, service_store_code=code,
            store_name=name, effective_from=AT, source_hash=f"original-{version}",
            group_key="g", group_name="group", service_center_key="c",
            service_center_name="center", district_key="d", district_name="district",
            area_key="a", area_name="area",
        ) for version, store_id, code, name in rows])
        connection.execute(eligibility.insert(), dict(
            eligibility_version="elig", service_store_code=FIRST_CODE,
            product_scope="精诚养车", effective_from=AT, source_hash="elig-hash"))
        connection.execute(lead_bindings.insert(), dict(
            lead_key="lead", first_assigned_at=AT, mapping_version="old"))
        connection.execute(runs.insert(), dict(
            run_id="run", period_start=AT, period_end=datetime(2026, 10, 1, tzinfo=timezone.utc),
            observed_through=AT, roster_at=AT, eligibility_version="elig",
            metric_version="v1", data_mode="production", status="success",
            quality_json={}, created_at=AT))
        connection.execute(snapshots.insert(), dict(
            run_id="run", store_id=FIRST_ID, mapping_version="old",
            metric_key="follow", numerator=2, denominator=3))
        connection.execute(samples.insert(), dict(
            run_id="run", store_id=FIRST_ID, mapping_version="old",
            metric_key="follow", sample_key="sample", sample_time=AT,
            numerator=1, denominator=1, status="included", evidence_json={"id": "evidence"}))


def _all_rows(engine):
    with engine.connect() as connection:
        return {table.name: [dict(row) for row in connection.execute(select(table)).mappings()]
                for table in metadata.sorted_tables}


def test_exact_names_across_versions_only_and_lossless_rollback(database):
    config, engine = database
    _seed(engine)
    before = _all_rows(engine)
    command.upgrade(config, "head")
    after = _all_rows(engine)
    expected = _all_rows(engine)
    expected[org_history.name] = [dict(row) for row in before[org_history.name]]
    for row in expected[org_history.name]:
        if row["mapping_version"] in {"old", "current"}:
            row["store_name"] = LONGDIXIN if row["store_id"] == FIRST_ID else LONGCHANGHONG
    assert after == expected
    with engine.connect() as connection:
        audit = connection.execute(text(f"SELECT * FROM {AUDIT}")).mappings().all()
        assert len(audit) == 4
        assert {row["mapping_version"] for row in audit} == {"old", "current"}
        for row in audit:
            original = next(item for item in before[org_history.name]
                            if (item["mapping_version"], item["store_id"]) ==
                            (row["mapping_version"], row["store_id"]))
            assert row["old_store_name"] == original["store_name"]
            assert row["source_hash"] == original["source_hash"]
        # The existing snapshot's join observes the repaired historical label.
        assert connection.execute(select(org_history.c.store_name).select_from(
            snapshots.join(org_history))).scalar_one() == LONGDIXIN
    command.upgrade(config, "head")
    assert _all_rows(engine) == after
    command.downgrade(config, PREVIOUS)
    assert _all_rows(engine) == before
    assert AUDIT not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert _all_rows(engine) == after


@pytest.mark.parametrize("later_change", [
    {"store_name": "subsequent correction"},
    {"service_store_code": "subsequent-code"},
    {"source_hash": "subsequent-import"},
    {"effective_from": datetime(2026, 10, 2, tzinfo=timezone.utc)},
])
def test_downgrade_does_not_overwrite_later_changes(database, later_change):
    config, engine = database
    _seed(engine)
    command.upgrade(config, REVISION)
    target = (org_history.c.mapping_version == "old") & (org_history.c.store_id == FIRST_ID)
    with engine.begin() as connection:
        connection.execute(org_history.update().where(target).values(**later_change))
        later_row = dict(connection.execute(select(org_history).where(target)).mappings().one())
    command.downgrade(config, PREVIOUS)
    with engine.connect() as connection:
        assert dict(connection.execute(select(org_history).where(target)).mappings().one()) == later_row


def test_empty_database_upgrade_is_safe(database):
    config, engine = database
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT COUNT(*) FROM {AUDIT}")).scalar_one() == 0
    command.downgrade(config, PREVIOUS)


def test_postgresql_offline_sql_uses_publication_and_table_locks(database):
    config, _ = database
    config.set_main_option("sqlalchemy.url", "postgresql://unused/unused")
    output = StringIO()
    config.output_buffer = output
    command.upgrade(config, f"{PREVIOUS}:{REVISION}", sql=True)
    sql = output.getvalue()
    assert "pg_advisory_xact_lock(7342091101)" in sql
    assert "LOCK TABLE ranking_store_org_history IN SHARE ROW EXCLUSIVE MODE" in sql
    assert FIRST_ID in sql and SECOND_ID in sql
    assert FIRST_CODE in sql and SECOND_CODE in sql
