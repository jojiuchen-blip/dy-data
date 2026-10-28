"""Synthetic downloads preserve business rows and allow normal access audit."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications.schema import metadata as publication_metadata
from apps.api.dy_api.models import Base, FinanceOperationAudit, SettlementStatementEntry
from publication_fixture_helpers import publish_fixture
from test_api_finance_contract_g5 import (
    _login,
    _seed_promotion_invoice,
    _seed_store_and_statement,
    client,  # noqa: F401 - reuse the real application/session fixture
)


def _database_fingerprint(session: Session) -> dict[str, str]:
    """Fingerprint all business/task tables; access audit is checked separately."""
    result = {}
    tables = [*Base.metadata.tables.values(), *publication_metadata.tables.values()]
    for table in sorted(tables, key=lambda item: item.name):
        if table.name == FinanceOperationAudit.__tablename__:
            continue
        rows = [
            json.dumps(dict(row), sort_keys=True, default=str, ensure_ascii=False)
            for row in session.execute(select(table)).mappings()
        ]
        result[table.name] = hashlib.sha256(
            "\n".join(sorted(rows)).encode("utf-8")
        ).hexdigest()
    return result


def test_every_finance_download_keeps_business_versions_amounts_and_jobs(
    client: TestClient, db_session: Session, tmp_path: Path,
) -> None:
    """Compare full persisted values after each of 24 repeated real downloads."""
    statement = _seed_store_and_statement(db_session)
    _seed_promotion_invoice(db_session, statement=statement)
    for direction in (1, 2):
        key = f"oct27-export-{direction}"
        db_session.add(SettlementStatementEntry(
            statement_entry_id=key, statement_id=statement.statement_id,
            statement_line_id=key, source_type=1, source_record_id=key,
            original_fee_result_id=key, coupon_id="00000000000000000123",
            order_id="9223372036854775808123", fee_direction=direction,
            original_business_month="2026-08", statement_posting_month="2026-08",
            product_scope="synthetic", product_type="合成类型", base_amount_cent=10000,
            fee_amount_cent=1000, rule_version="synthetic-v1",
            sale_time_snapshot=datetime(2026, 8, 2, tzinfo=timezone.utc),
            verify_time_snapshot=datetime(2026, 8, 3, tzinfo=timezone.utc),
            received_amount_cent_snapshot=10000, fee_rate_snapshot=Decimal("0.1"),
        ))
    db_session.commit()
    publish_fixture(db_session, "finance")
    _login(client)
    uploaded = client.post(
        "/api/v1/admin/finance-imports",
        data={"importType": "BASIC_INFO", "statementMonth": "2026-08"},
        files={"file": ("synthetic-errors.csv",
            b"storeId,storeName,sapCode,importedAt\nmissing,Missing,,bad-date\n", "text/csv")},
        headers={"Idempotency-Key": "oct27-readonly-error-fixture"},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["data"]["scenario"] == "BATCH_VALIDATION_FAILED"
    batch_id = uploaded.json()["data"]["batchId"]
    baseline = _database_fingerprint(db_session)
    cases = [
        (f"/api/v1/admin/finance-imports/templates/{kind}", {}, False)
        for kind in ("BASIC_INFO", "PROMOTION_FACTORY_RESULT", "MANAGEMENT_FACTORY_RESULT", "SAP_CONFIRMATION")
    ]
    cases += [
        ("/api/v1/admin/finance/invoices/export", {"month": "2026-08", "feeDirection": direction}, direction == "PROMOTION")
        for direction in ("PROMOTION", "MANAGEMENT")
    ]
    cases += [
        ("/api/v1/admin/finance/order-details/export", {"month": "2026-08", "feeDirection": direction}, True)
        for direction in ("PROMOTION", "MANAGEMENT")
    ]
    cases += [
        ("/api/v1/admin/finance/stores/export", {"month": "2026-08", "feeDirection": "PROMOTION", "metricScope": "MONTH"}, True),
        ("/api/v1/admin/finance/stores/sap-discrepancies/export", {"month": "2026-08", "feeDirection": "PROMOTION", "metricScope": "MONTH"}, False),
        ("/api/v1/admin/disputes/export", {}, False),
        (f"/api/v1/admin/finance-imports/{batch_id}/error-file", {}, True),
    ]
    receipts = []
    for endpoint, params, expect_rows in cases:
        for attempt in range(2):
            response = client.get(endpoint, params=params)
            assert response.status_code == 200, (endpoint, response.text)
            assert response.content.startswith(b"\xef\xbb\xbf"), endpoint
            rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
            if expect_rows:
                assert rows, endpoint
            assert _database_fingerprint(db_session) == baseline, endpoint
            if "order-details/export" in endpoint:
                assert rows[0]["order_id"] == "9223372036854775808123"
                assert rows[0]["coupon_id"] == "00000000000000000123"
            audits = list(db_session.scalars(select(FinanceOperationAudit)))
            assert all(audit.operation_type == "FINANCE_ORDER_DETAILS_EXPORT" for audit in audits)
            assert all(audit.after_snapshot["result"] == "SUCCESS" for audit in audits)
            receipts.append({"endpoint": endpoint, "params": params, "attempt": attempt,
                "rows": len(rows), "sha256": hashlib.sha256(response.content).hexdigest(),
                "normal_export_audit_count": len(audits)})
    assert len(audits) == 4
    (tmp_path / "download-receipts.json").write_text(
        json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8",
    )
