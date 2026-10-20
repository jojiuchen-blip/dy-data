"""Live correction reads stay independent from immutable finance publications."""
from datetime import date, datetime, timezone
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes import dashboard as dashboard_routes
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.models import InvoiceRecord
from publication_fixture_helpers import publish_fixture
from test_api_finance_g2 import _seed_management_periods


CURRENT_URL = "/api/v1/admin/finance/management-invoices/current-store/2026-08/current"
CORRECTION_URL = CURRENT_URL.removesuffix("current") + "corrections"
FROZEN_URL = "/api/v1/admin/finance/invoices"
FROZEN_FILTERS = {"month": "2026-08", "feeDirection": "MANAGEMENT", "metricScope": "MONTH"}


def _identity(*, role="admin", stores=("current-store",), pages=("FIN02",)):
    return AuthContext(user_id="finance-reader", username="finance-reader",
        display_name="Finance reader", role=role, store_ids=stores, auth_type="user",
        store_scope_mode="specified", page_keys=pages)


@pytest.fixture
def current_client(db_session, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    _seed_management_periods(db_session, [("current-statement", "2026-08", 1000)],
        store_id="current-store")
    identity = [_identity()]
    app = create_app()
    app.dependency_overrides[get_session_dependency] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: identity[0]
    with TestClient(app) as client:
        yield client, identity


def _invoice(version=1, **overrides):
    values = dict(invoice_id=f"current-invoice-v{version}", store_id="current-store",
        statement_month="2026-08", statement_id="current-statement", fee_direction=2,
        version_no=version, is_current=True, is_tombstone=False,
        invoice_number=f"{version}2345678901234567890", invoice_date=date(2026, 8, 20),
        invoice_amount_cent=900 + (version - 1) * 100, invoice_status=3, source_type=2,
        factory_deduction_date=date(2026, 8, 21),
        factory_deduction_amount_cent=900 + (version - 1) * 100,
        registered_at=datetime(2026, 8, 22, tzinfo=timezone.utc), registered_by="finance-reader")
    return InvoiceRecord(**(values | overrides))


def _forbid_calculation(*args, **kwargs):
    pytest.fail("Current invoice GET must not calculate business values")


def test_current_v2_reads_without_writes_while_publication_and_post_version_stay_pinned(
    current_client, db_session, monkeypatch,
):
    client, _ = current_client
    first = _invoice()
    db_session.add(first)
    publication = publish_fixture(db_session, "finance")
    params = FROZEN_FILTERS | {"publication_id": publication.id}
    before = client.get(FROZEN_URL, params=params)
    assert before.status_code == 200, before.text
    frozen = before.json()["data"]
    assert frozen["list"][0]["invoiceId"] == first.invoice_id

    first.is_current = False
    db_session.flush()
    db_session.add(_invoice(2))
    db_session.commit()
    monkeypatch.setattr(dashboard_routes, "_management_invoiceable_projection", _forbid_calculation)
    monkeypatch.setattr(dashboard_routes, "_finance_summary_metrics", _forbid_calculation)
    sql = []
    orm_statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        sql.append(statement)

    def observe_orm(state):
        orm_statements.append(state.statement)

    event.listen(db_session.bind, "before_cursor_execute", observe)
    event.listen(db_session, "do_orm_execute", observe_orm)
    try:
        response = client.get(CURRENT_URL)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
        event.remove(db_session, "do_orm_execute", observe_orm)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "invoiceId": "current-invoice-v2", "storeId": "current-store",
        "statementId": "current-statement", "statementMonth": "2026-08",
        "feeDirection": "MANAGEMENT", "versionNo": 2, "isCurrent": True,
        "invoiceNumber": "22345678901234567890", "invoiceDate": "2026-08-20",
        "invoiceAmountCent": 1000, "status": "APPROVED_SETTLED", "sourceType": 2,
        "importBatchId": None, "registeredAt": "2026-08-22T00:00:00+00:00",
        "factoryDeductionDate": "2026-08-21", "factoryDeductionAmountCent": 1000,
        "settledAt": "2026-08-22T00:00:00+00:00",
    }
    assert "publication" not in response.json()["meta"]
    assert "X-Publication-ID" not in response.headers
    assert sql and all(statement.lstrip().upper().startswith("SELECT") for statement in sql)
    # SQLite omits FOR UPDATE in compiled SQL, so inspect the ORM statement too.
    assert all(getattr(statement, "_for_update_arg", None) is None for statement in orm_statements)
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    after = client.get(FROZEN_URL, params=params)
    assert after.status_code == 200, after.text
    assert after.json()["data"] == frozen

    stale = client.post(CORRECTION_URL, headers={"Idempotency-Key": "live-current-stale-version"},
        json={"readVersion": 1, "invoiceNumber": "32345678901234567890",
            "invoiceDate": "2026-08-22", "invoiceAmountCent": 1000,
            "deductionDate": "2026-08-23", "deductionAmountCent": 1000,
            "changeReason": "Stale correction must still fail"})
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "VERSION_CONFLICT"
    assert stale.json()["detail"]["data"]["currentVersion"] == 2
    assert db_session.scalar(select(func.count()).select_from(InvoiceRecord)) == 2
    assert client.get(CURRENT_URL).json()["data"]["versionNo"] == 2


@pytest.mark.parametrize("identity,code", [
    (_identity(stores=("other-store",)), "DATA_SCOPE_FORBIDDEN"),
    (_identity(stores=()), "DATA_SCOPE_FORBIDDEN"),
    (_identity(pages=("FIN01",)), "PAGE_ACCESS_FORBIDDEN"),
    (_identity(role="store"), "DATA_SCOPE_FORBIDDEN"),
])
def test_current_invoice_rechecks_live_permissions(current_client, db_session, identity, code):
    client, active_identity = current_client
    db_session.add(_invoice())
    db_session.commit()
    assert client.get(CURRENT_URL).status_code == 200
    active_identity[0] = identity
    denied = client.get(CURRENT_URL)
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == code


@pytest.mark.parametrize("overrides", [None, {"is_current": False},
    {"is_tombstone": True}, {"fee_direction": 1}])
def test_missing_current_management_invoice_returns_404(current_client, db_session, overrides):
    client, _ = current_client
    if overrides is not None:
        db_session.add(_invoice(**overrides))
        db_session.commit()
    response = client.get(CURRENT_URL)
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"


def test_current_invoice_validates_month_and_store(current_client):
    client, _ = current_client
    assert client.get(CURRENT_URL.replace("2026-08", "2026-13")).status_code == 422
    assert client.get(CURRENT_URL.replace("current-store", "missing-store")).status_code == 404
