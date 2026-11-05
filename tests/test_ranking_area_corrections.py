from datetime import UTC, datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from apps.api.dy_api.ranking_area_corrections import corrections, effective_roster
from apps.api.dy_api.ranking_schema_v1 import org_history


def test_correction_is_visible_since_recorded_but_preserves_original_effective_date():
    engine = create_engine("sqlite://")
    org_history.create(engine)
    corrections.create(engine)
    at = datetime(2026, 9, 1, tzinfo=UTC)
    later = datetime(2026, 11, 5, tzinfo=UTC)
    with Session(engine) as session:
        for version, store in (("v1","target"), ("v2","target"), ("v1","neighbor")):
            session.execute(org_history.insert().values(mapping_version=version,store_id=store,
                service_store_code=store,store_name=store,effective_from=at,source_hash="hash",
                area_key="two",area_name="Area 2"))
        session.execute(corrections.insert().values(mapping_version="v1",store_id="target",
            service_store_code="target",source_hash="hash",old_key="two",old_area="Area 2",
            new_key="one",new_area="Area 1",reason="confirmed registration error",recorded_at=later))
        def values(source):
            return {(row.mapping_version,row.store_id): (row.area_key,row.area_name,row.effective_from.date())
                    for row in session.execute(select(source))}
        original=values(org_history)
        assert values(effective_roster(session,at))==original
        corrected=values(effective_roster(session,later))
        assert corrected=={**original,("v1","target"):("one","Area 1",at.date())}
        assert values(org_history)==original
def test_migration_preserves_history_and_refuses_to_drop_populated_audit(tmp_path):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    import pytest
    root = Path(__file__).resolve().parents[1]
    url = "sqlite:///" + (tmp_path / "area.sqlite").as_posix()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine=create_engine(url)
    with engine.begin() as connection:
        connection.execute(org_history.insert().values(mapping_version="v",store_id="x",
            service_store_code="x",store_name="x",effective_from=datetime.now(UTC),source_hash="h",
            area_key="a",area_name="A"))
        connection.execute(corrections.insert().values(mapping_version="v",store_id="x",
            service_store_code="x",source_hash="h",old_key="a",old_area="A",new_key="b",new_area="B",reason="confirmed"))
        for name in ("dashboard_publication_source_counters","ranking_source_change_counters"):
            assert connection.scalar(text(f"select generation from {name} where source_name='ranking_area_corrections'")) == 1
        for op in ("UPDATE ranking_area_corrections SET new_area='C'", "DELETE FROM ranking_area_corrections"):
            with pytest.raises(DBAPIError, match="append only"):
                connection.execute(text(op))
    with pytest.raises(RuntimeError,match="Preserve"):
        command.downgrade(cfg,"20261027_0066")
