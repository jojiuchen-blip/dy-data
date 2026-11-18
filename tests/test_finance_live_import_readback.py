"""Official manufacturer results update finance reads within the same publication."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from apps.api.dy_api.dashboard_publications import finance
from apps.api.dy_api.models import (
    DimStore, InvoiceRecord, PromotionInvoice, SettlementStatement, SettlementStatementConfirmation,
)
from test_api_finance_imports import _commit, _login, _upload, client  # noqa: F401
from test_dydata104_finance_state_matrix import CONTENTS, _seed, db_session  # noqa: F401
from publication_fixture_helpers import publish_fixture


@pytest.mark.parametrize("kind,direction,amount,number", [
    ("PROMOTION_FACTORY_RESULT", "PROMOTION", 1200, "12345678901234567890"),
    ("MANAGEMENT_FACTORY_RESULT", "MANAGEMENT", 2500, "22345678901234567890"),
])
def test_formal_commit_updates_summary_filters_pagination_export_without_republishing(
    client, db_session, kind, direction, amount, number,
):
    _login(client)
    _seed(db_session)
    publication_id = publish_fixture(db_session, "finance").id
    filters = dict(month="2026-08", fee_direction=direction, metric_scope="MONTH",
        store_id="store-1", q=None, invoice_status=None, scope_store_ids=None)
    before = finance.read_finance_summary(db_session, publication_id, **filters)["metrics"]
    frozen_rows = list(db_session.execute(select(finance.invoices).where(
        finance.invoices.c.publication_id == publication_id)))
    batch = _upload(client, kind, CONTENTS[kind]).json()["data"]
    assert _commit(client, batch, uuid4().hex).status_code == 200
    db_session.expire_all()
    after = finance.read_finance_summary(db_session, publication_id, **filters)["metrics"]
    assert after["statement_total_cent"] == before["statement_total_cent"]
    assert after["confirmed_amount_cent"] == before["confirmed_amount_cent"]
    assert after["settled_or_deducted_amount_cent"] == amount
    assert after["pending_invoice_amount_cent"] == 0
    model = PromotionInvoice if direction == "PROMOTION" else InvoiceRecord
    current = db_session.scalar(select(model).where(model.is_current.is_(True)))
    selected = filters | {"q": number, "invoice_status": 3}
    page = finance.read_finance_invoices(db_session, publication_id, page_size=1, **selected)
    assert page["total"] == 1 and page["list"][0]["invoice_id"] == current.invoice_id
    assert page["list"][0]["status"] == "APPROVED_SETTLED"
    assert finance.export_finance_invoices(db_session, publication_id, **selected) == page["list"]
    assert finance.read_finance_invoices(db_session, publication_id, **(filters | {"invoice_status": 1}))["total"] == 0
    assert list(db_session.execute(select(finance.invoices).where(
        finance.invoices.c.publication_id == publication_id))) == frozen_rows
    response = client.get("/api/v1/admin/finance/invoices", params={
        "month": "2026-08", "feeDirection": direction, "metricScope": "MONTH", "q": number,
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["list"][0]["invoiceId"] == current.invoice_id


def test_promotion_rejection_correction_and_reversal_update_current_reason(client, db_session):
    _login(client)
    _seed(db_session)
    publication_id = publish_fixture(db_session, "finance").id
    content = (
        "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
        "12345678901234567890,REJECTED_REUPLOAD,首次退回原因,,\n"
    )
    first = _upload(client, "PROMOTION_FACTORY_RESULT", content).json()["data"]
    assert _commit(client, first, uuid4().hex).status_code == 200
    second = _upload(client, "PROMOTION_FACTORY_RESULT", content.replace("首次退回原因", "更正后的退回原因")).json()["data"]
    corrected = client.post(f"/api/v1/admin/finance-imports/{second['batchId']}/corrections",
        json={"readVersion": second["readVersion"], "changeReason": "隔离更正原因"},
        headers={"Idempotency-Key": uuid4().hex})
    assert corrected.status_code == 200, corrected.text
    filters = dict(month="2026-08", fee_direction="PROMOTION", metric_scope="MONTH", store_id="store-1")
    items = finance.export_finance_invoices(db_session, publication_id, **filters)
    assert len(items) == 1 and items[0]["rejection_reason"] == "更正后的退回原因"
    reversed_batch = client.post(f"/api/v1/admin/finance-imports/{second['batchId']}/reversals",
        json={"readVersion": corrected.json()["data"]["currentVersion"], "changeReason": "隔离撤销更正"},
        headers={"Idempotency-Key": uuid4().hex})
    assert reversed_batch.status_code == 200, reversed_batch.text
    items = finance.export_finance_invoices(db_session, publication_id, **filters)
    assert len(items) == 1 and items[0]["rejection_reason"] == "首次退回原因"


def test_current_state_overlay_cannot_include_unpublished_bills(client, db_session):
    _login(client)
    _seed(db_session)
    publication_id = publish_fixture(db_session, "finance").id
    filters = dict(month="2026-08", fee_direction="MANAGEMENT", metric_scope="MONTH")
    before = finance.read_finance_summary(db_session, publication_id, **filters)
    items = finance.export_finance_invoices(db_session, publication_id, **filters)
    db_session.add(DimStore(store_id="unpublished-store", store_name="Unpublished"))
    db_session.flush()
    db_session.add(SettlementStatement(statement_id="unpublished-bill", store_id="unpublished-store",
        statement_month="2026-08", version_no=1, is_current=True, statement_status=4,
        management_original_fee_cent=987654, management_net_fee_cent=987654))
    db_session.flush()
    db_session.add(SettlementStatementConfirmation(confirmation_id="unpublished-confirmation",
        statement_id="unpublished-bill", fee_direction=2, confirmation_status=1,
        confirmed_amount_cent=987654, confirmed_by="synthetic"))
    db_session.commit()
    assert finance.read_finance_summary(db_session, publication_id, **filters) == before
    assert finance.export_finance_invoices(db_session, publication_id, **filters) == items
    assert finance.read_finance_invoices(db_session, publication_id, q="unpublished", **filters)["total"] == 0
