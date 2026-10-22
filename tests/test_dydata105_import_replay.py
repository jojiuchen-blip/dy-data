"""A management import may recognize its own current result without bypassing validation."""

import pytest
from sqlalchemy import func, select

from test_api_finance_imports import client, _login, _upload, _commit
from apps.api.dy_api.models import InvoiceRecord, SettlementStatement, SettlementStatementConfirmation


CONTENT = (
    "storeId,statementMonth,storeName,invoiceNumber,invoiceDate,deductionDate,deductionAmountCent\n"
    "store-1,2026-08,Store One,22345678901234567890,2026-08-20,2026-08-21,2500\n"
)


@pytest.fixture()
def committed_management(client, db_session):
    _login(client)
    db_session.add(SettlementStatement(
        statement_id="management-noop", store_id="store-1", statement_month="2026-08",
        version_no=1, is_current=True, statement_status=4,
        management_original_fee_cent=2500, management_net_fee_cent=2500,
    ))
    db_session.flush()
    db_session.add(SettlementStatementConfirmation(
        confirmation_id="management-noop", statement_id="management-noop", fee_direction=2,
        confirmation_status=1, confirmed_amount_cent=2500, confirmed_by="store-1",
    ))
    db_session.commit()
    uploaded = _upload(client, "MANAGEMENT_FACTORY_RESULT", CONTENT)
    assert uploaded.status_code == 200, uploaded.text
    committed = _commit(client, uploaded.json()["data"], "dy105-management-commit-1")
    assert committed.status_code == 200, committed.text


def test_identical_management_import_is_no_change_and_cannot_create_another_invoice(
    client, db_session, committed_management,
):
    response = _upload(client, "MANAGEMENT_FACTORY_RESULT", CONTENT)
    assert response.status_code == 200, response.text
    batch = response.json()["data"]
    assert batch["scenario"] == "NO_CHANGE"
    assert batch["errorRows"] == 0
    duplicate = _commit(client, batch, "dy105-management-commit-2")
    assert duplicate.status_code == 409
    assert "IMPORT_BATCH_NOT_READY" in duplicate.text
    assert db_session.scalar(select(func.count()).select_from(InvoiceRecord)) == 1


@pytest.mark.parametrize("before,after", [
    ("2500", "2499"),
    ("22345678901234567890", "22345678901234567891"),
    ("2026-08-21", "2026-08-22"),
    ("Store One", "Wrong Name"),
])
def test_current_management_invoice_does_not_make_changed_or_invalid_rows_valid(
    client, db_session, committed_management, before, after,
):
    response = _upload(client, "MANAGEMENT_FACTORY_RESULT", CONTENT.replace(before, after))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["scenario"] == "BATCH_VALIDATION_FAILED"
    assert db_session.scalar(select(func.count()).select_from(InvoiceRecord)) == 1


def test_superseded_management_import_row_is_not_a_current_noop(client, db_session, committed_management):
    from dy_api.routes.dashboard import _management_import_payload_is_current
    from apps.api.dy_api.models import FinanceImportRow

    row = db_session.scalar(select(FinanceImportRow).where(FinanceImportRow.row_status == 5))
    invoice = db_session.scalar(select(InvoiceRecord))
    invoice.is_current = False
    db_session.commit()
    assert not _management_import_payload_is_current(db_session, row.normalized_payload)
