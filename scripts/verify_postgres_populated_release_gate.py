from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


EXPECTED_HEAD = "20260831_0046"


def _run_alembic(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DY_DATABASE_URL"] = database_url
    environment["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"populated PostgreSQL migration to {revision} failed\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )


def _create_database(base_url: str, database_name: str) -> None:
    maintenance_url = make_url(base_url).set(database="postgres")
    engine = create_engine(maintenance_url, future=True)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        engine.dispose()


def _drop_database(base_url: str, database_name: str) -> None:
    maintenance_url = make_url(base_url).set(database="postgres")
    engine = create_engine(maintenance_url, future=True)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
    finally:
        engine.dispose()


def _seed_fixture(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    occurred_at = datetime(2026, 8, 1, 8, tzinfo=timezone.utc)
    profile_at = datetime(2026, 8, 1, 9, tzinfo=timezone.utc)
    statement_at = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO finance_import_batch "
                    "(batch_id, import_type, statement_month, file_name, "
                    "file_sha256, normalized_sha256, read_version, current_version, "
                    "batch_status, total_rows, success_rows, error_rows, content_changed, "
                    "submitted_by, committed_by, submitted_at, committed_at, gmt_create, gmt_modified) "
                    "VALUES ('release-gate-profile-batch', 1, '2026-08', 'profile.csv', "
                    ":file_sha256, :normalized_sha256, 0, 1, 5, 1, 1, 0, TRUE, "
                    "'admin', 'admin', :occurred_at, :occurred_at, :occurred_at, :occurred_at)"
                ),
                {
                    "file_sha256": "a" * 64,
                    "normalized_sha256": "b" * 64,
                    "occurred_at": occurred_at,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO store_finance_profile "
                    "(profile_id, store_id, profile_type, source_type, version_no, "
                    "is_current, is_tombstone, store_name_snapshot, sap_code, "
                    "import_batch_id, gmt_create, gmt_modified) "
                    "VALUES ('release-gate-profile', 'store-1', 1, 1, 1, TRUE, FALSE, "
                    "'Release Gate Store', 'SAP-RELEASE', 'release-gate-profile-batch', "
                    ":profile_at, :profile_at)"
                ),
                {"profile_at": profile_at},
            )
            connection.execute(
                text(
                    "INSERT INTO settlement_statement "
                    "(statement_id, store_id, statement_month, version_no, is_current, "
                    "gmt_create, gmt_modified) VALUES "
                    "('release-gate-backfilled', 'store-1', '2026-08', 1, TRUE, :statement_at, :statement_at), "
                    "('release-gate-unresolved', 'store-2', '2026-08', 1, TRUE, :statement_at, :statement_at)"
                ),
                {"statement_at": statement_at},
            )
    finally:
        engine.dispose()


def _verify_fixture(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != EXPECTED_HEAD:
                raise AssertionError(f"expected {EXPECTED_HEAD}, got {revision}")
            backfilled = connection.execute(
                text(
                    "SELECT store_name_snapshot, store_snapshot_status "
                    "FROM settlement_statement WHERE statement_id = 'release-gate-backfilled'"
                )
            ).one()
            if backfilled != ("Release Gate Store", "BACKFILLED_PROFILE"):
                raise AssertionError(f"unexpected backfilled snapshot: {backfilled}")
            unresolved = connection.execute(
                text(
                    "SELECT store_snapshot_status FROM settlement_statement "
                    "WHERE statement_id = 'release-gate-unresolved'"
                )
            ).scalar_one()
            if unresolved != "UNRESOLVED":
                raise AssertionError(f"unexpected unresolved snapshot status: {unresolved}")
            exception = connection.execute(
                text(
                    "SELECT reason_code FROM settlement_statement_snapshot_migration_exception "
                    "WHERE statement_id = 'release-gate-unresolved'"
                )
            ).scalar_one()
            if exception != "NO_PRIOR_BASIC_PROFILE":
                raise AssertionError(f"unexpected snapshot exception: {exception}")
    finally:
        engine.dispose()


def main() -> None:
    base_url = os.environ.get("DY_RELEASE_POSTGRES_URL")
    if not base_url:
        raise SystemExit("DY_RELEASE_POSTGRES_URL is required")
    database_name = f"dydata_populated_gate_{uuid.uuid4().hex[:12]}"
    _create_database(base_url, database_name)
    fixture_url = make_url(base_url).set(database=database_name).render_as_string(
        hide_password=False
    )
    try:
        _run_alembic(fixture_url, "20260824_0042")
        _seed_fixture(fixture_url)
        _run_alembic(fixture_url, "head")
        _verify_fixture(fixture_url)
    finally:
        _drop_database(base_url, database_name)
    print(
        "Populated PostgreSQL release gate passed: "
        "backfilled and unresolved snapshot fixtures verified"
    )


if __name__ == "__main__":
    main()
