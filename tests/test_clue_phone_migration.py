from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _config(repo_root: Path, database_url: str) -> Config:
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_phone_source_fingerprint_migration_preserves_old_cache_as_unverified(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "clue-phone-source-fingerprint.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = _config(repo_root, database_url)

    # This starts from an empty database and lands immediately before the
    # additive migration, then seeds a legacy cached phone with no proof of
    # which source produced it.
    command.upgrade(config, "20260903_0050")
    engine = create_engine(database_url)
    assert "phone_source_fingerprint" not in {
        column["name"] for column in inspect(engine).get_columns("clue_center_orders")
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO clue_center_orders (
                    order_id, source_clue_ids, source_clue_count,
                    lead_status, current_round_no, current_round_status,
                    assigned_at_source, phone_plain, phone_masked, phone_source,
                    follow_result, is_followed, is_follow_success,
                    is_self_store_verified, created_at, updated_at
                ) VALUES (
                    'legacy-phone-order', '[]', 1,
                    'pending_allocation', 0, 'pending_allocation',
                    'test', '13912345678', '139****5678', 'telephone',
                    'pending', 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )

    command.upgrade(config, "20260907_0051")
    upgraded = inspect(engine)
    assert "phone_source_fingerprint" in {
        column["name"] for column in upgraded.get_columns("clue_center_orders")
    }
    with engine.connect() as connection:
        cached = connection.execute(
            text(
                "SELECT phone_plain, phone_source_fingerprint "
                "FROM clue_center_orders WHERE order_id = 'legacy-phone-order'"
            )
        ).mappings().one()
    assert cached == {
        "phone_plain": "13912345678",
        "phone_source_fingerprint": None,
    }

    command.downgrade(config, "20260903_0050")
    assert "phone_source_fingerprint" not in {
        column["name"] for column in inspect(engine).get_columns("clue_center_orders")
    }
