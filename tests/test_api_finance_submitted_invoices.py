"""Promotional invoices remain searchable with no monthly bill publication."""

import csv
from dataclasses import replace
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.models import DimStore, PromotionInvoice, PromotionInvoiceAllocation


URL = "/api/v1/admin/finance/promotion-invoices/submitted"
PENDING = "SUBMITTED_PENDING_FACTORY_REVIEW"
ALLOWED_NUMBER = "00001234567890123456"
OTHER_NUMBER = "99991234567890123456"


def test_submitted_invoices_use_current_invoice_not_monthly_readiness(db_session, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    registered_at = datetime(2026, 10, 26, 8, 40, tzinfo=UTC)
    db_session.add_all([
        DimStore(store_id="allowed", store_name="可见门店"),
        DimStore(store_id="other", store_name="其他门店"),
    ])
    for invoice_id, store_id, number, version, current, tombstone in (
        ("allowed-previous", "allowed", ALLOWED_NUMBER, 1, False, False),
        ("allowed-current", "allowed", ALLOWED_NUMBER, 2, True, False),
        ("other-current", "other", OTHER_NUMBER, 1, True, False),
        ("voided", "allowed", "01234567890123456789", 1, True, True),
    ):
        db_session.add(PromotionInvoice(
            invoice_id=invoice_id, physical_invoice_id=f"physical-{number}", store_id=store_id,
            version_no=version, is_current=current, is_tombstone=tombstone,
            invoice_number=number, invoice_date=date(2026, 10, 26), invoice_amount_cent=1680,
            buyer_name="测试购买方", tax_rate_percent=6, registered_by="test-store",
            registered_at=registered_at,
        ))
    db_session.flush()
    for invoice_id, store_id, periods in (
        ("allowed-current", "allowed", ("2026-08", "2026-09")),
        ("other-current", "other", ("2026-09",)),
    ):
        for month in periods:
            db_session.add(PromotionInvoiceAllocation(
                allocation_id=f"{invoice_id}-{month}", invoice_id=invoice_id, store_id=store_id,
                statement_id=f"{store_id}-{month}", statement_month=month,
                settlement_batch_month="2026-10", allocated_amount_cent=840 if store_id == "allowed" else 1680,
            ))
    db_session.commit()
    app = create_app()
    identity = AuthContext(user_id="finance", username="finance", display_name="财务",
        role="admin", store_ids=("allowed",), store_scope_mode="specified", auth_type="test", page_keys=("FIN01",))

    def current_user():
        return identity

    app.dependency_overrides[get_session_dependency] = lambda: db_session
    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as client:
        response = client.get(URL)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 1
        assert [item["invoiceId"] for item in data["list"]] == ["allowed-current"]
        invoice = data["list"][0]
        assert invoice["statementMonths"] == ["2026-08", "2026-09"]
        assert invoice["settlementBatchMonths"] == ["2026-10"]
        assert invoice["invoiceAmountCent"] == 1680

        filters = {"month": "2026-09", "q": ALLOWED_NUMBER, "invoiceStatus": PENDING}
        assert client.get(URL, params=filters).json()["data"] == data
        assert client.get(URL, params={"month": "2026-10"}).json()["data"]["total"] == 0
        assert client.get(URL, params={"q": OTHER_NUMBER}).json()["data"]["total"] == 0
        assert client.get(URL, params={"month": "2026-13"}).status_code == 422

        export = client.get(URL + "/export", params=filters | {"locale": "zh-CN"})
        assert export.status_code == 200, export.text
        rows = list(csv.DictReader(StringIO(export.content.decode("utf-8-sig"))))
        assert len(rows) == 1
        assert rows[0]["发票记录ID"] == "allowed-current"
        assert rows[0]["发票号码"].removeprefix("'") == ALLOWED_NUMBER
        assert rows[0]["发票金额（元）"] == "16.80"
        assert rows[0]["原账期"] == "2026-08、2026-09"

        identity = replace(identity, store_scope_mode="all")
        assert client.get(URL, params={"pageSize": 1}).json()["data"]["total"] == 2
        identity = replace(identity, page_keys=("FIN02",))
        assert client.get(URL).status_code == 403
        assert client.get(URL + "/export").status_code == 403
        identity = replace(identity, role="store", page_keys=("FIN01",))
        assert client.get(URL).status_code == 403
