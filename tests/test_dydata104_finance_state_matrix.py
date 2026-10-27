"""Real finance routes must preserve facts outside each import's explicit target."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    Base,
    DimStore,
    FinanceImportRow,
    InvoiceRecord,
    PromotionInvoice,
    PromotionInvoiceAllocation,
    PromotionInvoiceNumberRegistry,
    SettlementStatement,
    SettlementStatementConfirmation,
    StoreFinanceProfile,
)
from test_api_finance_imports import _commit, _login, _upload, client  # noqa: F401
from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency
from dy_api.routes import dashboard as dashboard_routes
from apps.api.dy_api.dashboard_publications.schema import metadata as publication_metadata
from publication_fixture_helpers import publish_fixture
from test_api_finance_imports import _commit, _login, _upload, client  # noqa: F401


CONTENTS = {
    "BASIC_INFO": "storeId,storeName,sapCode,importedAt\nstore-1,Store One,000012345678901234567890,2026-08-21T10:00:00+08:00\n",
    "SAP_CONFIRMATION": "storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,factoryConfirmationResult,confirmedAt\nstore-1,Store One,SAP-OLD,SVC-001,SAP-FINAL,CONFIRMED,2026-08-21T11:00:00+08:00\n",
    "PROMOTION_FACTORY_RESULT": "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n12345678901234567890,APPROVED_SETTLED,,2026-08-21,1200\n",
    "MANAGEMENT_FACTORY_RESULT": "storeId,statementMonth,storeName,invoiceNumber,invoiceDate,deductionDate,deductionAmountCent\nstore-1,2026-08,Store One,22345678901234567890,2026-08-20,2026-08-21,2500\n",
}


@pytest.fixture()
def db_session(db_session):
    """Optionally exercise the same HTTP matrix in a disposable local PG schema."""
    url = os.getenv("DYDATA_FINANCE_TEST_DATABASE_URL")
    if not url:
        yield db_session
        return
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.endswith("_test")
    schema = "finance_matrix_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"})
    try:
        Base.metadata.create_all(engine)
        with Session(engine, autoflush=False) as session:
            yield session
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _seed(session, *, statement_status=4):
    for store_id, month in (("store-1", "2026-08"), ("store-1", "2026-09"), ("store-2", "2026-08")):
        statement_id = f"matrix-{store_id}-{month}"
        session.add(SettlementStatement(
            statement_id=statement_id, store_id=store_id, statement_month=month,
            version_no=1, is_current=True, statement_status=statement_status,
            promotion_original_fee_cent=1200, promotion_net_fee_cent=1200,
            management_original_fee_cent=2500, management_net_fee_cent=2500,
        ))
        session.flush()
        for direction, amount in ((1, 1200), (2, 2500)):
            session.add(SettlementStatementConfirmation(
                confirmation_id=f"{statement_id}-{direction}", statement_id=statement_id,
                fee_direction=direction, confirmation_status=1,
                confirmed_amount_cent=amount, confirmed_by=store_id,
            ))
    session.add(PromotionInvoice(
        invoice_id="matrix-promotion", physical_invoice_id="matrix-physical",
        store_id="store-1", version_no=1, is_current=True,
        invoice_number="12345678901234567890", invoice_date=date(2026, 8, 20),
        invoice_amount_cent=1200, buyer_name="Synthetic Buyer", tax_rate_percent=6,
        invoice_status=2, registered_by="synthetic",
    ))
    session.flush()
    session.add_all([
        PromotionInvoiceNumberRegistry(
            invoice_number="12345678901234567890", physical_invoice_id="matrix-physical",
            first_invoice_id="matrix-promotion", store_id="store-1",
        ),
        PromotionInvoiceAllocation(
            allocation_id="matrix-allocation", invoice_id="matrix-promotion", store_id="store-1",
            statement_id="matrix-store-1-2026-08", statement_month="2026-08",
            settlement_batch_month="2026-08", allocated_amount_cent=1200, is_current=True,
        ),
    ])
    session.commit()


def _facts(session, *, exclude=()):
    """Fingerprint complete persisted financial rows, jobs, and frozen publications."""
    session.expire_all()
    prefixes = ("settlement_", "invoice_", "promotion_invoice", "store_finance_", "management_", "job_", "dashboard_", "dim_store", "sku_fee_rule", "dim_sku_product_rule")
    tables = list(Base.metadata.sorted_tables)
    existing = set(inspect(session.get_bind()).get_table_names())
    tables.extend(table for table in publication_metadata.sorted_tables if table.name in existing)
    return {
        table.name: sorted(repr(tuple(row)) for row in session.execute(select(table)))
        for table in tables
        if table.name.startswith(prefixes) and table.name not in exclude
    }


def _act_as(client, *, store_ids=("store-1",), role="admin", pages=("FIN01", "FIN02", "FIN04", "FIN06")):
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="matrix-user", username="matrix-user", display_name="Synthetic",
        role=role, store_ids=store_ids, auth_type="user", store_scope_mode="specified",
        page_keys=pages,
    )


@pytest.mark.parametrize("import_type", CONTENTS)
def test_upload_preview_templates_errors_and_logs_leave_business_facts_unchanged(client, db_session, import_type):
    _login(client)
    _seed(db_session)
    before = _facts(db_session)
    uploaded = _upload(client, import_type, CONTENTS[import_type])
    assert uploaded.status_code == 200, uploaded.text
    batch = uploaded.json()["data"]
    assert batch["scenario"] == "FIRST_IMPORT_READY"
    for path in (
        f"/api/v1/admin/finance-imports/templates/{import_type}",
        "/api/v1/admin/finance-imports?page=1&pageSize=1",
        f"/api/v1/admin/finance-imports/{batch['batchId']}",
        f"/api/v1/admin/finance-imports/{batch['batchId']}/error-file",
    ):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert _facts(db_session) == before


@pytest.mark.parametrize("import_type", CONTENTS)
def test_each_commit_changes_only_its_fact_family_and_replays_once(client, db_session, import_type):
    _login(client)
    _seed(db_session)
    changed = {
        "BASIC_INFO": ("store_finance_profile",), "SAP_CONFIRMATION": ("store_finance_profile",),
        "PROMOTION_FACTORY_RESULT": ("promotion_invoice", "promotion_invoice_allocation", "invoice_status_event"),
        "MANAGEMENT_FACTORY_RESULT": ("invoice_record", "management_carryforward_application"),
    }[import_type]
    before = _facts(db_session, exclude=changed)
    batch = _upload(client, import_type, CONTENTS[import_type]).json()["data"]
    key = f"matrix-commit-{uuid4().hex}"
    result = _commit(client, batch, key)
    assert result.status_code == 200, result.text
    assert _facts(db_session, exclude=changed) == before
    after = _facts(db_session)
    assert _commit(client, batch, key).status_code == 200
    assert _facts(db_session) == after
    duplicate = _upload(client, import_type, CONTENTS[import_type])
    assert duplicate.json()["data"]["scenario"] == "NO_CHANGE"
    assert _commit(client, duplicate.json()["data"], f"matrix-noop-{uuid4().hex}").status_code == 409
    assert _facts(db_session) == after
    if import_type in ("BASIC_INFO", "SAP_CONFIRMATION"):
        profile = db_session.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.is_current.is_(True)))
        assert profile.sap_code == ("SAP-FINAL" if import_type == "SAP_CONFIRMATION" else "000012345678901234567890")
        assert profile.factory_confirmed == (True if import_type == "SAP_CONFIRMATION" else None)
    elif import_type == "PROMOTION_FACTORY_RESULT":
        assert db_session.scalar(select(PromotionInvoice.invoice_status).where(PromotionInvoice.is_current.is_(True))) == 3
    else:
        invoice = db_session.scalar(select(InvoiceRecord).where(InvoiceRecord.is_current.is_(True)))
        assert (invoice.invoice_status, invoice.invoice_amount_cent, invoice.factory_deduction_amount_cent) == (3, 2500, 2500)


@pytest.mark.parametrize("mutation", ("confirmation", "invoice", "store"))
def test_management_commit_revalidates_target_after_preview_without_partial_results(client, db_session, mutation):
    _login(client)
    _seed(db_session)
    batch = _upload(client, "MANAGEMENT_FACTORY_RESULT", CONTENTS["MANAGEMENT_FACTORY_RESULT"]).json()["data"]
    if mutation == "confirmation":
        confirmation = db_session.scalar(select(SettlementStatementConfirmation).where(SettlementStatementConfirmation.confirmation_id == "matrix-store-1-2026-08-2"))
        confirmation.confirmed_amount_cent = 2499
    elif mutation == "invoice":
        db_session.add(InvoiceRecord(
            invoice_id="competing-management", store_id="store-1", statement_month="2026-08",
            statement_id="matrix-store-1-2026-08", fee_direction=2, version_no=1,
            is_current=True, invoice_number="99999999999999999999", invoice_date=date(2026, 8, 20),
            invoice_amount_cent=2500, invoice_status=3, source_type=2, registered_by="other",
            factory_deduction_date=date(2026, 8, 21), factory_deduction_amount_cent=2500,
        ))
    else:
        db_session.get(DimStore, "store-1").store_name = "Changed Name"
    db_session.commit()
    before = _facts(db_session)
    response = _commit(client, batch, f"matrix-stale-{uuid4().hex}")
    assert response.status_code == 409, response.text
    assert _facts(db_session) == before


@pytest.mark.parametrize("import_type", ("BASIC_INFO", "SAP_CONFIRMATION"))
def test_header_only_import_cannot_advance_a_version(client, db_session, import_type):
    _login(client)
    before = _facts(db_session)
    response = _upload(client, import_type, CONTENTS[import_type].splitlines()[0] + "\n")
    assert response.status_code == 422, response.text
    assert _facts(db_session) == before


@pytest.mark.parametrize("invoice_number", ("１２３４５６７８９０１２３４５６７８９０", "1234567890123456789", "123456789012345678901"))
def test_management_rejects_non_ascii_or_wrong_length_invoice_number(client, db_session, invoice_number):
    _login(client)
    _seed(db_session)
    before = _facts(db_session)
    response = _upload(client, "MANAGEMENT_FACTORY_RESULT", CONTENTS["MANAGEMENT_FACTORY_RESULT"].replace("22345678901234567890", invoice_number))
    assert response.json()["data"]["scenario"] == "BATCH_VALIDATION_FAILED", response.text
    assert _facts(db_session) == before


@pytest.mark.parametrize("direction", ("PROMOTION", "MANAGEMENT"))
@pytest.mark.parametrize("path", ("invoices/export", "stores/export", "stores/sap-discrepancies/export", "order-details/export"))
def test_finance_exports_reuse_published_facts_without_business_or_job_writes(client, db_session, direction, path):
    _login(client)
    _seed(db_session)
    publish_fixture(db_session, "finance")
    before = _facts(db_session)
    response = client.get(f"/api/v1/admin/finance/{path}", params={"month": "2026-08", "feeDirection": direction, "metricScope": "MONTH"})
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert _facts(db_session) == before


@pytest.mark.parametrize("import_type", CONTENTS)
def test_store_role_cannot_upload_or_download_finance_templates(client, db_session, import_type):
    _seed(db_session)
    _act_as(client, role="store")
    before = _facts(db_session)
    assert _upload(client, import_type, CONTENTS[import_type]).status_code == 403
    assert client.get(f"/api/v1/admin/finance-imports/templates/{import_type}").status_code == 403
    assert _facts(db_session) == before


def test_reimport_of_superseded_basic_content_is_a_difference_not_a_noop(client, db_session):
    _login(client)
    original = _upload(client, "BASIC_INFO", CONTENTS["BASIC_INFO"]).json()["data"]
    assert _commit(client, original, "matrix-original-basic").status_code == 200
    changed = _upload(client, "BASIC_INFO", CONTENTS["BASIC_INFO"].replace("000012345678901234567890", "SAP-CHANGED")).json()["data"]
    assert _commit(client, changed, "matrix-changed-basic").status_code == 200
    repeated = _upload(client, "BASIC_INFO", CONTENTS["BASIC_INFO"])
    assert repeated.json()["data"]["scenario"] == "DIFF_CONFIRMATION_REQUIRED", repeated.text


@pytest.mark.parametrize("import_type", CONTENTS)
def test_commit_rechecks_permission_after_preview(client, db_session, import_type):
    _login(client)
    _seed(db_session)
    batch = _upload(client, import_type, CONTENTS[import_type]).json()["data"]
    before = _facts(db_session)
    _act_as(client, store_ids=("store-2",))
    response = _commit(client, batch, f"matrix-permission-{uuid4().hex}")
    assert response.status_code == 403, response.text
    assert _facts(db_session) == before


def test_management_later_row_failure_rolls_back_earlier_invoice_and_deduction(client, db_session):
    _login(client)
    _seed(db_session)
    content = CONTENTS["MANAGEMENT_FACTORY_RESULT"] + "store-2,2026-08,Store Two,32345678901234567890,2026-08-20,2026-08-21,2500\n"
    preview = _upload(client, "MANAGEMENT_FACTORY_RESULT", content)
    assert preview.json()["data"]["scenario"] == "FIRST_IMPORT_READY", preview.text
    confirmation = db_session.scalar(select(SettlementStatementConfirmation).where(
        SettlementStatementConfirmation.confirmation_id == "matrix-store-2-2026-08-2"
    ))
    confirmation.confirmed_amount_cent = 2499
    db_session.commit()
    before = _facts(db_session)
    response = _commit(client, preview.json()["data"], "matrix-second-row-failure")
    assert response.status_code == 409, response.text
    assert _facts(db_session) == before


@pytest.mark.parametrize("field,old,new", (
    ("statementMonth", "store-1,2026-08", "store-1,2026-09"),
    ("storeName", "Store One", "Store Two"),
    ("deductionAmountCent", ",2500\n", ",0\n"),
    ("deductionAmountCent", ",2500\n", ",-1\n"),
    ("deductionAmountCent", ",2500\n", ",2499\n"),
))
def test_invalid_management_scope_month_and_amount_fail_atomically(client, db_session, field, old, new):
    _login(client)
    _seed(db_session)
    before = _facts(db_session)
    result = _upload(client, "MANAGEMENT_FACTORY_RESULT", CONTENTS["MANAGEMENT_FACTORY_RESULT"].replace(old, new))
    batch = result.json()["data"]
    assert batch["scenario"] == "BATCH_VALIDATION_FAILED", result.text
    assert field in {row["field"] for row in batch["errors"]["list"]}
    assert _commit(client, batch, f"matrix-invalid-{uuid4().hex}").status_code == 409
    assert _facts(db_session) == before


def test_promotion_wrong_month_and_management_direction_do_not_match(client, db_session):
    _login(client)
    _seed(db_session)
    before = _facts(db_session)
    promotion = CONTENTS["PROMOTION_FACTORY_RESULT"].replace("12345678901234567890", "22345678901234567890")
    assert _upload(client, "PROMOTION_FACTORY_RESULT", promotion).json()["data"]["scenario"] == "BATCH_VALIDATION_FAILED"
    result = client.post(
        "/api/v1/admin/finance-imports", data={"importType": "PROMOTION_FACTORY_RESULT", "statementMonth": "2026-09"},
        files={"file": ("wrong-month.csv", CONTENTS["PROMOTION_FACTORY_RESULT"].encode(), "text/csv")},
        headers={"Idempotency-Key": "matrix-wrong-month"},
    )
    assert result.json()["data"]["scenario"] == "BATCH_VALIDATION_FAILED"
    assert _facts(db_session) == before


@pytest.mark.parametrize("second_type,second_month", (("BASIC_INFO", "2026-08"), ("SAP_CONFIRMATION", "2026-08"), ("BASIC_INFO", "2026-09")))
def test_cross_type_and_month_profile_preview_cannot_overwrite_another_commit(client, db_session, second_type, second_month):
    _login(client)
    first = _upload(client, "BASIC_INFO", CONTENTS["BASIC_INFO"]).json()["data"]
    second = client.post(
        "/api/v1/admin/finance-imports", data={"importType": second_type, "statementMonth": second_month},
        files={"file": ("second.csv", CONTENTS[second_type].encode(), "text/csv")},
        headers={"Idempotency-Key": f"matrix-second-{uuid4().hex}"},
    ).json()["data"]
    assert _commit(client, first, "matrix-first-profile-commit").status_code == 200
    before = _facts(db_session)
    response = _commit(client, second, "matrix-second-profile-commit")
    assert response.status_code == 409, response.text
    assert _facts(db_session) == before


@pytest.mark.parametrize("second_type,second_month", (("BASIC_INFO", "2026-08"), ("SAP_CONFIRMATION", "2026-08"), ("BASIC_INFO", "2026-09")))
def test_postgres_real_http_concurrent_profile_commits_have_one_winner(client, db_session, second_type, second_month):
    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("requires DYDATA_FINANCE_TEST_DATABASE_URL disposable local PG database")
    _login(client)
    first = _upload(client, "BASIC_INFO", CONTENTS["BASIC_INFO"]).json()["data"]
    second = client.post(
        "/api/v1/admin/finance-imports", data={"importType": second_type, "statementMonth": second_month},
        files={"file": ("second.csv", CONTENTS[second_type].encode(), "text/csv")},
        headers={"Idempotency-Key": f"matrix-concurrent-second-{uuid4().hex}"},
    ).json()["data"]
    engine = db_session.get_bind()
    barrier = Barrier(2)

    def execute(batch):
        with Session(engine, autoflush=False) as session:
            app = create_app()
            def override_session():
                yield session
            app.dependency_overrides[get_session_dependency] = override_session
            app.dependency_overrides[get_current_user] = lambda: AuthContext(
                user_id="matrix-admin", username="matrix-admin", display_name="Synthetic",
                role="admin", store_ids=(), auth_type="user", store_scope_mode="all", page_keys=("FIN04",),
            )
            with TestClient(app) as thread_client:
                barrier.wait(timeout=10)
                response = _commit(thread_client, batch, f"matrix-concurrent-{uuid4().hex}")
                return response.status_code, response.text

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(execute, (first, second)))
    assert sorted(code for code, _ in results) == [200, 409], results
    db_session.expire_all()
    profiles = list(db_session.scalars(select(StoreFinanceProfile)))
    assert len(profiles) == 1 and profiles[0].version_no == 1 and profiles[0].is_current


@pytest.mark.parametrize("import_type", ("PROMOTION_FACTORY_RESULT", "MANAGEMENT_FACTORY_RESULT"))
def test_settled_factory_results_cannot_be_reversed_in_detail_or_post(client, db_session, import_type):
    _login(client)
    _seed(db_session)
    batch = _upload(client, import_type, CONTENTS[import_type]).json()["data"]
    committed = _commit(client, batch, f"matrix-settled-{import_type}")
    assert committed.status_code == 200, committed.text
    before = _facts(db_session)
    detail = client.get(f"/api/v1/admin/finance-imports/{batch['batchId']}").json()["data"]
    assert not detail["canReverse"] and detail["reverseNotAllowedCode"] == "IMPORT_SETTLEMENT_PROTECTED"
    response = client.post(
        f"/api/v1/admin/finance-imports/{batch['batchId']}/reversals",
        json={"readVersion": committed.json()["data"]["currentVersion"], "changeReason": "禁止回退已结算事实"},
        headers={"Idempotency-Key": f"matrix-protected-{import_type}"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "IMPORT_SETTLEMENT_PROTECTED"
    assert _facts(db_session) == before


def test_unsettled_rejected_result_can_restore_prior_pending_review_without_fee_changes(client, db_session):
    _login(client)
    _seed(db_session)
    untouched = _facts(db_session, exclude=("promotion_invoice", "promotion_invoice_allocation", "invoice_status_event"))
    rejected = CONTENTS["PROMOTION_FACTORY_RESULT"].replace("APPROVED_SETTLED,,2026-08-21,1200", "REJECTED_REUPLOAD,合成退回,,")
    batch = _upload(client, "PROMOTION_FACTORY_RESULT", rejected).json()["data"]
    committed = _commit(client, batch, "matrix-rejected-result")
    assert committed.status_code == 200, committed.text
    detail = client.get(f"/api/v1/admin/finance-imports/{batch['batchId']}").json()["data"]
    assert detail["canReverse"]
    response = client.post(
        f"/api/v1/admin/finance-imports/{batch['batchId']}/reversals",
        json={"readVersion": 1, "changeReason": "恢复未结算待审结果"},
        headers={"Idempotency-Key": "matrix-rejected-reversal"},
    )
    assert response.status_code == 200, response.text
    assert db_session.scalar(select(PromotionInvoice.invoice_status).where(PromotionInvoice.is_current.is_(True))) == 2
    assert _facts(db_session, exclude=("promotion_invoice", "promotion_invoice_allocation", "invoice_status_event")) == untouched


def test_promotion_settled_result_cannot_import_a_rejection_or_modify_other_facts(client, db_session):
    _login(client)
    _seed(db_session)
    batch = _upload(client, "PROMOTION_FACTORY_RESULT", CONTENTS["PROMOTION_FACTORY_RESULT"]).json()["data"]
    assert _commit(client, batch, "matrix-promotion-settled").status_code == 200
    before = _facts(db_session)
    rejected = CONTENTS["PROMOTION_FACTORY_RESULT"].replace("APPROVED_SETTLED,,2026-08-21,1200", "REJECTED_REUPLOAD,禁止回退,,")
    response = _upload(client, "PROMOTION_FACTORY_RESULT", rejected)
    assert response.json()["data"]["scenario"] == "BATCH_VALIDATION_FAILED"
    assert "已结算" in str(response.json()["data"]["errors"])
    assert _facts(db_session) == before


def test_consumed_profile_cannot_be_reversed_after_statement_freezes_its_identity(client, db_session):
    _login(client)
    _seed(db_session)
    batch = _upload(client, "BASIC_INFO", CONTENTS["BASIC_INFO"]).json()["data"]
    assert _commit(client, batch, "matrix-consumed-profile").status_code == 200
    profile = db_session.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.is_current.is_(True)))
    statement = db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "matrix-store-1-2026-08"))
    statement.store_snapshot_profile_id = profile.profile_id
    db_session.commit()
    before = _facts(db_session)
    detail = client.get(f"/api/v1/admin/finance-imports/{batch['batchId']}").json()["data"]
    assert not detail["canReverse"] and detail["reverseNotAllowedCode"] == "IMPORT_DEPENDENCY_PROTECTED"
    response = client.post(
        f"/api/v1/admin/finance-imports/{batch['batchId']}/reversals",
        json={"readVersion": 1, "changeReason": "禁止撤销已消费资料"},
        headers={"Idempotency-Key": "matrix-consumed-reversal"},
    )
    assert response.status_code == 409, response.text
    assert _facts(db_session) == before


def test_unexpected_failure_during_second_write_rolls_back_the_first_row(client, db_session, monkeypatch):
    _login(client)
    content = CONTENTS["BASIC_INFO"] + "store-2,Store Two,SAP-SECOND,2026-08-21T10:00:00+08:00\n"
    batch = _upload(client, "BASIC_INFO", content).json()["data"]
    before = _facts(db_session)
    original = dashboard_routes._commit_final_finance_import_row
    count = 0
    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("synthetic connection failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(dashboard_routes, "_commit_final_finance_import_row", fail_second)
    with pytest.raises(RuntimeError, match="synthetic connection failure"):
        _commit(client, batch, "matrix-interrupted-commit")
    assert _facts(db_session) == before


@pytest.mark.parametrize("same_file", (True, False))
def test_management_cannot_reuse_one_invoice_number_across_stores(client, db_session, same_file):
    _login(client)
    _seed(db_session)
    content = CONTENTS["MANAGEMENT_FACTORY_RESULT"]
    if same_file:
        content += "store-2,2026-08,Store Two,22345678901234567890,2026-08-20,2026-08-21,2500\n"
    else:
        first = _upload(client, "MANAGEMENT_FACTORY_RESULT", content).json()["data"]
        assert _commit(client, first, "matrix-first-invoice-number").status_code == 200
        content = content.replace("store-1", "store-2").replace("Store One", "Store Two")
    before = _facts(db_session)
    response = _upload(client, "MANAGEMENT_FACTORY_RESULT", content)
    assert response.json()["data"]["scenario"] == "BATCH_VALIDATION_FAILED", response.text
    assert "invoiceNumber" in {row["field"] for row in response.json()["data"]["errors"]["list"]}
    assert _facts(db_session) == before


def _correction(number, *, version=1):
    return {
        "invoiceNumber": number, "invoiceDate": "2026-08-20", "invoiceAmountCent": 2500,
        "deductionDate": "2026-08-21", "deductionAmountCent": 2500,
        "changeReason": "Synthetic correction", "readVersion": version,
    }


def test_direct_management_correction_cannot_steal_current_or_historical_invoice_number(client, db_session):
    _login(client)
    _seed(db_session)
    original_number = "22345678901234567890"
    for store_id, name, number in (("store-1", "Store One", original_number), ("store-2", "Store Two", "32345678901234567890")):
        content = CONTENTS["MANAGEMENT_FACTORY_RESULT"].replace("store-1", store_id).replace("Store One", name).replace(original_number, number)
        batch = _upload(client, "MANAGEMENT_FACTORY_RESULT", content).json()["data"]
        assert _commit(client, batch, f"matrix-owner-{store_id}").status_code == 200
    changed = client.post(
        "/api/v1/admin/finance/management-invoices/store-1/2026-08/corrections",
        json=_correction("42345678901234567890"), headers={"Idempotency-Key": "matrix-owner-new-number"},
    )
    assert changed.status_code == 200, changed.text
    before = _facts(db_session)
    for number in (original_number, "42345678901234567890"):
        response = client.post(
            "/api/v1/admin/finance/management-invoices/store-2/2026-08/corrections",
            json=_correction(number), headers={"Idempotency-Key": f"matrix-duplicate-{number}"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "INVOICE_NUMBER_ALREADY_USED"
        assert _facts(db_session) == before
    own_history = client.post(
        "/api/v1/admin/finance/management-invoices/store-1/2026-08/corrections",
        json=_correction(original_number, version=2), headers={"Idempotency-Key": "matrix-own-history-allowed"},
    )
    assert own_history.status_code == 200, own_history.text


@pytest.mark.parametrize("mode", ("imports", "corrections", "mixed"))
@pytest.mark.parametrize("other_store,other_month", (("store-2", "2026-08"), ("store-1", "2026-09")))
def test_postgres_management_number_ownership_serializes_all_http_writers(client, db_session, mode, other_store, other_month):
    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("requires DYDATA_FINANCE_TEST_DATABASE_URL disposable local PG database")
    _login(client)
    _seed(db_session)
    shared = "92345678901234567890"
    posts = []
    for index, (store_id, month) in enumerate((("store-1", "2026-08"), (other_store, other_month))):
        content = CONTENTS["MANAGEMENT_FACTORY_RESULT"].replace("store-1", store_id).replace("Store One", "Store Two" if store_id == "store-2" else "Store One").replace("2026-08,", month + ",")
        is_correction = mode == "corrections" or (mode == "mixed" and index == 0)
        number = ("52345678901234567890" if index == 0 else "62345678901234567890") if is_correction else shared
        preview = client.post(
            "/api/v1/admin/finance-imports", data={"importType": "MANAGEMENT_FACTORY_RESULT", "statementMonth": month},
            files={"file": ("management.csv", content.replace("22345678901234567890", number).encode(), "text/csv")},
            headers={"Idempotency-Key": f"matrix-number-preview-{uuid4().hex}"},
        ).json()["data"]
        assert preview["scenario"] in {"FIRST_IMPORT_READY", "DIFF_CONFIRMATION_REQUIRED"}, preview
        if is_correction:
            assert _commit(client, preview, f"matrix-number-original-{uuid4().hex}").status_code == 200
            posts.append((f"/api/v1/admin/finance/management-invoices/{store_id}/{month}/corrections", _correction(shared)))
        else:
            posts.append((f"/api/v1/admin/finance-imports/{preview['batchId']}/commits", {"readVersion": preview["readVersion"], "changeReason": "Synthetic concurrent import"}))
    engine = db_session.get_bind()
    barrier = Barrier(2)
    def execute(post):
        with Session(engine, autoflush=False) as session:
            app = create_app()
            def override_session():
                yield session
            app.dependency_overrides[get_session_dependency] = override_session
            app.dependency_overrides[get_current_user] = lambda: AuthContext(
                user_id="matrix-admin", username="matrix-admin", display_name="Synthetic", role="admin",
                store_ids=(), auth_type="user", store_scope_mode="all", page_keys=("FIN02",),
            )
            with TestClient(app) as thread_client:
                barrier.wait(timeout=10)
                result = thread_client.post(post[0], json=post[1], headers={"Idempotency-Key": f"matrix-number-race-{uuid4().hex}"})
                return result.status_code, result.text
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(execute, posts))
    assert sorted(code for code, _ in results) == [200, 409], results
    db_session.expire_all()
    owners = list(db_session.scalars(select(InvoiceRecord).where(InvoiceRecord.invoice_number == shared)))
    assert len(owners) == 1 and owners[0].is_current and owners[0].factory_deduction_amount_cent == 2500


@pytest.mark.parametrize("import_type", CONTENTS)
def test_frozen_row_preview_uses_only_whitelisted_fields_and_does_not_drift(client, db_session, import_type):
    _login(client)
    _seed(db_session)
    if import_type in {"BASIC_INFO", "SAP_CONFIRMATION"}:
        db_session.add(StoreFinanceProfile(
            profile_id="preview-prior", store_id="store-1", profile_type=1, source_type=2,
            version_no=1, is_current=True, store_name_snapshot="Store One", sap_code="BEFORE-SAP",
        ))
        db_session.commit()
    before_upload = _facts(db_session)
    batch = _upload(client, import_type, CONTENTS[import_type]).json()["data"]
    assert _facts(db_session) == before_upload
    path = f"/api/v1/admin/finance-imports/{batch['batchId']}/rows"
    response = client.get(path, params={"pageSize": 1})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["previewSummary"] == {"frozenAvailable": True, "blockedRowCount": 0, "totalRows": 1}
    preview = data["list"][0]["preview"]
    assert preview["available"] and preview["stateTransition"]["allowed"]
    if import_type == "MANAGEMENT_FACTORY_RESULT":
        assert preview["after"]["invoiceNumber"] == "22345678901234567890"
    if import_type in {"BASIC_INFO", "SAP_CONFIRMATION"}:
        assert preview["before"]["sapCode" if import_type == "BASIC_INFO" else "finalSapCode"] == "BEFORE-SAP"
        target = db_session.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.profile_id == "preview-prior"))
        target.sap_code = "AFTER-UPLOAD-SAP"
    else:
        invoice = db_session.scalar(select(PromotionInvoice).where(PromotionInvoice.is_current.is_(True)))
        invoice.invoice_status = 4
    db_session.commit()
    stable_facts = _facts(db_session)
    assert client.get(path).json()["data"]["list"][0]["preview"] == preview
    assert _facts(db_session) == stable_facts
    assert not {"fillerPhone", "fillerPhoneCiphertext", "buyerName", "file", "__preview", "_previewProfileId"}.intersection(preview["after"])
    assert not {"fillerPhone", "fillerPhoneCiphertext", "buyerName", "file"}.intersection(preview["before"] or {})
    _act_as(client, store_ids=("store-2",))
    assert client.get(path).status_code == 403


def test_preview_rows_have_real_pagination_whole_batch_summary_and_legacy_unavailable(client, db_session):
    _login(client)
    content = CONTENTS["BASIC_INFO"] + "store-2,Wrong Name,SAP-X,2026-08-21T10:00:00+08:00\n"
    batch = _upload(client, "BASIC_INFO", content).json()["data"]
    path = f"/api/v1/admin/finance-imports/{batch['batchId']}/rows"
    first = client.get(path, params={"page": 1, "pageSize": 1}).json()["data"]
    second = client.get(path, params={"page": 2, "pageSize": 1}).json()["data"]
    assert first["total"] == second["total"] == 2
    assert first["list"][0]["rowNumber"] == 2 and second["list"][0]["rowNumber"] == 3
    assert first["previewSummary"] == second["previewSummary"] == {"frozenAvailable": True, "blockedRowCount": 1, "totalRows": 2}
    assert not second["list"][0]["preview"]["stateTransition"]["allowed"]
    assert second["list"][0]["preview"]["blockedReasons"]
    assert client.get(path, params={"pageSize": 51}).status_code == 422
    assert client.get(path, params={"page": 3, "pageSize": 1}).json()["data"]["list"] == []
    _act_as(client, store_ids=("store-1",))
    assert client.get(path).status_code == 403
    client.app.dependency_overrides.pop(get_current_user)
    ready = _upload(client, "BASIC_INFO", CONTENTS["BASIC_INFO"]).json()["data"]
    row = db_session.scalar(select(FinanceImportRow).where(FinanceImportRow.batch_id == ready["batchId"]))
    row.normalized_payload = dashboard_routes._finance_import_business_payload(row.normalized_payload)
    db_session.commit()
    before = _facts(db_session)
    legacy = client.get(f"/api/v1/admin/finance-imports/{ready['batchId']}/rows").json()["data"]
    assert legacy["previewSummary"]["frozenAvailable"] is False
    assert legacy["list"][0]["preview"]["reasonCode"] == "PREVIEW_SNAPSHOT_UNAVAILABLE"
    denied = _commit(client, ready, "matrix-legacy-preview-commit")
    assert denied.status_code == 409 and denied.json()["detail"]["code"] == "IMPORT_PREVIEW_SNAPSHOT_REQUIRED"
    assert _facts(db_session) == before


