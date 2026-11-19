"""Multi-store import commits must use one target-lock order across batches."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError, local
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import FinanceImportBatch, StoreFinanceProfile
from test_api_finance_imports import _commit, _login, _upload, client  # noqa: F401
from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes import dashboard as dashboard_routes
from dy_api.routes._data import get_session_dependency
from test_dydata104_finance_state_matrix import db_session  # noqa: F401


@pytest.mark.parametrize("second_type", ["BASIC_INFO", "SAP_CONFIRMATION"])
@pytest.mark.parametrize("first_operation", ["commit", "reverse"])
def test_postgres_opposite_store_order_commits_without_deadlock(
    client, db_session, monkeypatch, second_type, first_operation,
):
    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("requires DYDATA_FINANCE_TEST_DATABASE_URL disposable local PG database")
    _login(client)
    basic = (
        "storeId,storeName,sapCode,importedAt\n"
        "store-1,Store One,SAP-001,2026-08-21T10:00:00+08:00\n"
        "store-2,Store Two,SAP-002,2026-08-21T10:00:00+08:00\n"
    )
    first = _upload(client, "BASIC_INFO", basic).json()["data"]
    if first_operation == "reverse":
        assert _commit(client, first, uuid4().hex).status_code == 200
    if second_type == "BASIC_INFO":
        header, first_row, second_row = basic.splitlines()
        second_content = "\n".join((header, second_row, first_row)) + "\n"
    else:
        second_content = (
            "storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,factoryConfirmationResult,confirmedAt\n"
            "store-2,Store Two,SAP-002,SVC-002,SAP-FINAL-002,CONFIRMED,2026-08-21T11:00:00+08:00\n"
            "store-1,Store One,SAP-001,SVC-001,SAP-FINAL-001,CONFIRMED,2026-08-21T11:00:00+08:00\n"
        )
    response = client.post(
        "/api/v1/admin/finance-imports",
        data={"importType": second_type, "statementMonth": "2026-09"},
        files={"file": ("opposite.csv", second_content.encode(), "text/csv")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 200, response.text
    second = response.json()["data"]
    assert first["scenario"] == "FIRST_IMPORT_READY"
    assert second["scenario"] in ("FIRST_IMPORT_READY", "DIFF_CONFIRMATION_REQUIRED")

    # Concurrent writers are allowed to reach the first mutation together.
    # Batch-level target locking must serialize them before either writes.
    original_writer = dashboard_routes._commit_store_finance_profile_row
    original_reversal_guard = dashboard_routes._require_finance_import_reversal_unprotected
    first_row_barrier = Barrier(2)
    state = local()

    def pause_after_first_target():
        state.rows = getattr(state, "rows", 0) + 1
        if state.rows == 1:
            try:
                first_row_barrier.wait(timeout=1)
            except BrokenBarrierError:
                pass

    def pause_after_first_write(*args, **kwargs):
        original_writer(*args, **kwargs)
        pause_after_first_target()

    def pause_after_first_reversal_guard(*args, **kwargs):
        original_reversal_guard(*args, **kwargs)
        pause_after_first_target()

    monkeypatch.setattr(
        dashboard_routes, "_commit_store_finance_profile_row", pause_after_first_write,
    )
    monkeypatch.setattr(
        dashboard_routes, "_require_finance_import_reversal_unprotected",
        pause_after_first_reversal_guard,
    )
    start = Barrier(2)
    engine = db_session.get_bind()

    def execute(batch):
        with Session(engine, autoflush=False) as session:
            app = create_app()

            def override_session():
                yield session

            app.dependency_overrides[get_session_dependency] = override_session
            app.dependency_overrides[get_current_user] = lambda: AuthContext(
                user_id="batch-lock-admin", username="batch-lock-admin",
                display_name="Synthetic", role="admin", store_ids=(),
                auth_type="user", store_scope_mode="all", page_keys=("FIN04",),
            )
            with TestClient(app) as thread_client:
                start.wait(timeout=10)
                if first_operation == "reverse" and batch["batchId"] == first["batchId"]:
                    result = thread_client.post(
                        f"/api/v1/admin/finance-imports/{batch['batchId']}/reversals",
                        json={"readVersion": 1, "changeReason": "隔离测试撤销"},
                        headers={"Idempotency-Key": uuid4().hex},
                    )
                else:
                    result = _commit(thread_client, batch, uuid4().hex)
                return result.status_code, result.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, (first, second)))
    assert sorted(code for code, _ in results) == [200, 409], results
    conflict_code = next(body for code, body in results if code == 409)["detail"]["code"]
    assert conflict_code in {"IMPORT_PREVIEW_STALE", "REVERSAL_BUSINESS_VERSION_CONFLICT"}
    with Session(engine) as fresh:
        profiles = list(fresh.scalars(select(StoreFinanceProfile)))
        assert len(profiles) == (4 if first_operation == "reverse" else 2)
        assert {row.store_id for row in profiles} == {"store-1", "store-2"}
        current = [row for row in profiles if row.is_current]
        assert len(current) == 2
        assert all(row.version_no == (2 if first_operation == "reverse" else 1) for row in current)
        assert len({row.is_tombstone for row in current}) == 1
        committed = list(fresh.scalars(select(FinanceImportBatch).where(
            FinanceImportBatch.batch_status.in_((5, 8)),
        )))
        expected_committed = 1 + int(first_operation == "reverse" and results[1][0] == 200)
        assert len(committed) == expected_committed
        assert all(batch.total_rows == 2 for batch in committed)
