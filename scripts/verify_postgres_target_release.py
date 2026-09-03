from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


EXPECTED_HEAD = "20260903_0050"
SNAPSHOT_EXCEPTION_TABLES = (
    "settlement_statement_snapshot_migration_exception",
    "settlement_statement_entry_snapshot_migration_exception",
)


def _database_url() -> str:
    value = os.environ.get("DY_RELEASE_POSTGRES_URL")
    if not value:
        raise SystemExit("DY_RELEASE_POSTGRES_URL is required")
    return value


def _pg_dump_url(database_url: str) -> str:
    parsed = make_url(database_url)
    if parsed.drivername.startswith("postgresql+"):
        parsed = parsed.set(drivername="postgresql")
    return parsed.render_as_string(hide_password=False)


def _validate_existing_lineage(engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("alembic_version"):
        return
    with engine.begin() as connection:
        revisions = list(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    if len(revisions) > 1:
        raise RuntimeError(f"target database has multiple Alembic heads: {revisions}")
    if not revisions:
        return

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    if ScriptDirectory.from_config(config).get_revision(revisions[0]) is None:
        raise RuntimeError(f"target database has unknown Alembic revision: {revisions[0]}")


def _backup_database(database_url: str, backup_file: Path) -> None:
    backup_file.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(backup_file),
            "--dbname",
            _pg_dump_url(database_url),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "target PostgreSQL backup failed\n"
            f"stderr:\n{result.stderr[-2000:]}"
        )
    if not backup_file.is_file() or backup_file.stat().st_size == 0:
        raise RuntimeError("target PostgreSQL backup is missing or empty")
    backup_file.chmod(0o600)


def _run_upgrade(database_url: str) -> None:
    environment = os.environ.copy()
    environment["DY_DATABASE_URL"] = database_url
    environment["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "target PostgreSQL migration failed\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )


def _verify_target_state(engine) -> None:
    with engine.begin() as connection:
        revisions = list(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
        if revisions != [EXPECTED_HEAD]:
            raise AssertionError(f"expected one Alembic head {EXPECTED_HEAD}, got {revisions}")

        unresolved = 0
        for table_name in SNAPSHOT_EXCEPTION_TABLES:
            unresolved += int(
                connection.execute(
                    text(
                        f"SELECT count(*) FROM {table_name} "
                        "WHERE resolved_at IS NULL"
                    )
                ).scalar_one()
            )
        if unresolved:
            raise AssertionError(f"unresolved snapshot migration exceptions: {unresolved}")


def main() -> None:
    database_url = _database_url()
    backup_file = Path(
        os.environ.get("DY_RELEASE_BACKUP_FILE", "/tmp/dydata-pre-migrate.dump")
    )
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("target release gate requires PostgreSQL")
        _validate_existing_lineage(engine)
        _backup_database(database_url, backup_file)
        _run_upgrade(database_url)
        _verify_target_state(engine)
    finally:
        engine.dispose()
    print(
        "Target PostgreSQL release gate passed: "
        f"head={EXPECTED_HEAD}, backup={backup_file}"
    )


if __name__ == "__main__":
    main()
