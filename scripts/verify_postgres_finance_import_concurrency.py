from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import FinanceImportBatch, FinanceOperationAudit  # noqa: E402
from dy_api.auth import AuthContext  # noqa: E402
from dy_api.routes import dashboard as dashboard_routes  # noqa: E402
from dy_api.routes._data import DashboardDataStore  # noqa: E402


def _database_url() -> str:
    value = os.environ.get("DY_RELEASE_POSTGRES_URL")
    if not value:
        raise SystemExit("DY_RELEASE_POSTGRES_URL is required")
    return value


def _seed_batches(session, batch_prefix: str) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    batch_ids = (f"{batch_prefix}-a", f"{batch_prefix}-b")
    session.add_all(
        [
            FinanceImportBatch(
                batch_id=batch_id,
                import_type=1,
                statement_month="2026-08",
                file_name=f"{batch_id}.csv",
                file_sha256=("a" if index == 0 else "b") * 64,
                normalized_sha256=("c" if index == 0 else "d") * 64,
                read_version=0,
                current_version=0,
                batch_status=3,
                total_rows=0,
                success_rows=0,
                error_rows=0,
                content_changed=False,
                submitted_by="release-gate",
                submitted_at=now,
                created_at=now,
                updated_at=now,
            )
            for index, batch_id in enumerate(batch_ids)
        ]
    )
    session.commit()
    return batch_ids


def _request(request_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(),
        headers={"X-Request-ID": request_id},
    )


def _commit_one(session_factory, batch_id: str, key: str) -> tuple[str, int]:
    current_user = AuthContext(
        user_id="release-gate-admin",
        username="release-gate-admin",
        display_name="Release Gate Admin",
        role="admin",
        store_ids=(),
        auth_type="user",
        store_scope_mode="all",
        page_keys=("FIN04",),
    )
    with session_factory() as session:
        try:
            response = dashboard_routes.commit_finance_import(
                batch_id=batch_id,
                payload={"readVersion": 0, "changeReason": "release concurrency gate"},
                request=_request(f"release-gate-{key}"),
                idempotency_key=key,
                current_user=current_user,
                store=DashboardDataStore(session),
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if exc.status_code != 409 or detail.get("code") != "VERSION_CONFLICT":
                raise
            return "conflict", int(detail["data"]["currentVersion"])
        return "committed", int(response["data"]["currentVersion"])


def main() -> None:
    database_url = _database_url()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, future=True)
    prefix = f"release-concurrency-{uuid4().hex[:12]}"
    try:
        with session_factory() as session:
            batch_ids = _seed_batches(session, prefix)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _commit_one,
                    session_factory,
                    batch_id,
                    f"{prefix}-idempotency-{index:02d}",
                )
                for index, batch_id in enumerate(batch_ids)
            ]
            outcomes = [future.result(timeout=60) for future in futures]

        with session_factory() as session:
            rows = list(
                session.scalars(
                    select(FinanceImportBatch).where(
                        FinanceImportBatch.batch_id.in_(batch_ids)
                    )
                )
            )
            audit_count = session.scalar(
                select(func.count())
                .select_from(FinanceOperationAudit)
                .where(
                    FinanceOperationAudit.target_id.in_(batch_ids),
                    FinanceOperationAudit.operation_type == "FINANCE_IMPORT_COMMIT",
                )
            )
            if sorted(outcomes) != [("committed", 1), ("conflict", 1)]:
                raise AssertionError(
                    "expected one version-1 commit and one VERSION_CONFLICT, "
                    f"got {outcomes}"
                )
            if sorted((row.batch_status, row.current_version) for row in rows) != [
                (5, 1),
                (7, 1),
            ]:
                raise AssertionError("concurrent batches do not retain commit/conflict states")
            if audit_count != 1:
                raise AssertionError(f"expected one successful commit audit, got {audit_count}")
    finally:
        engine.dispose()
    print(
        "PostgreSQL finance import concurrency gate passed: "
        "one version-1 commit and one VERSION_CONFLICT"
    )


if __name__ == "__main__":
    main()
