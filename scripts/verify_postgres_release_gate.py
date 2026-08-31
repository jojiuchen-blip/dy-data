from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy import create_engine, text


EXPECTED_HEAD = "20260831_0048"
LOCK_KEY = "dydata-release-gate:finance-import-version:3:2026-08"


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
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "concurrent Alembic upgrade failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def _verify_migration_state(engine) -> None:
    with engine.begin() as connection:
        revisions = list(
            connection.execute(text("SELECT version_num FROM alembic_version"))
            .scalars()
        )
        if revisions != [EXPECTED_HEAD]:
            raise AssertionError(f"expected one Alembic head {EXPECTED_HEAD}, got {revisions}")

        unresolved = 0
        for table_name in (
            "settlement_statement_snapshot_migration_exception",
            "settlement_statement_entry_snapshot_migration_exception",
        ):
            unresolved += int(
                connection.execute(
                    text(
                        f"SELECT count(*) FROM {table_name} "
                        "WHERE resolved_at IS NULL"
                    )
                ).scalar_one()
            )
        if unresolved != 0:
            raise AssertionError(f"unresolved snapshot migration exceptions: {unresolved}")


def _verify_transaction_lock(engine) -> None:
    first_acquired = Event()
    second_started = Event()
    release_first = Event()
    second_acquired = Event()

    def acquire_first() -> None:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": LOCK_KEY},
            )
            first_acquired.set()
            if not release_first.wait(timeout=30):
                raise TimeoutError("timed out waiting to release first PostgreSQL lock")

    def acquire_second() -> None:
        if not first_acquired.wait(timeout=30):
            raise TimeoutError("first PostgreSQL lock was not acquired")
        second_started.set()
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": LOCK_KEY},
            )
            second_acquired.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(acquire_first)
        second_future = executor.submit(acquire_second)
        if not first_acquired.wait(timeout=30):
            raise TimeoutError("first PostgreSQL lock was not acquired")
        if not second_started.wait(timeout=30):
            raise TimeoutError("second PostgreSQL lock attempt did not start")
        time.sleep(0.25)
        if second_acquired.is_set():
            raise AssertionError("second PostgreSQL session acquired the transaction lock too early")
        release_first.set()
        first_future.result(timeout=30)
        second_future.result(timeout=30)


def main() -> None:
    database_url = os.environ.get("DY_RELEASE_POSTGRES_URL")
    if not database_url:
        raise SystemExit("DY_RELEASE_POSTGRES_URL is required")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_run_upgrade, database_url) for _ in range(2)]
        for future in futures:
            future.result()

    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        _verify_migration_state(engine)
        _verify_transaction_lock(engine)
    finally:
        engine.dispose()
    print(f"PostgreSQL release gate passed: head={EXPECTED_HEAD}, advisory lock=serialized")


if __name__ == "__main__":
    main()
