from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes import dashboard as dashboard_routes  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    DimStore,
    FinanceImportBatch,
    FinanceImportRow,
    FinanceOperationAudit,
    InvoiceRecord,
    ManagementCarryforwardApplication,
    PromotionInvoice,
    PromotionInvoiceAllocation,
    SapSuggestion,
    SettlementStatement,
    SettlementStatementConfirmation,
    StoreFinanceProfile,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def _act_as_store(client: TestClient, store_id: str = "g2-store-1") -> None:
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=f"{store_id}-user",
        username=f"{store_id}-user",
        display_name="G2 Store User",
        role="store",
        store_ids=(store_id,),
        auth_type="user",
        store_scope_mode="assigned",
    )


def _seed_management_periods(
    db_session: Session,
    periods: list[tuple[str, str, int]],
    *,
    store_id: str = "g2-store-1",
) -> None:
    db_session.add(
        DimStore(store_id=store_id, store_name="G2 Store", is_active=True)
    )
    for statement_id, statement_month, confirmed_amount_cent in periods:
        db_session.add(
            SettlementStatement(
                statement_id=statement_id,
                store_id=store_id,
                statement_month=statement_month,
                version_no=1,
                is_current=True,
                statement_status=4,
                promotion_original_fee_cent=0,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=0,
                management_original_fee_cent=max(confirmed_amount_cent, 0),
                management_adjustment_fee_cent=min(confirmed_amount_cent, 0),
                management_net_fee_cent=confirmed_amount_cent,
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        )
        db_session.add(
            SettlementStatementConfirmation(
                confirmation_id=f"confirmation-{statement_id}",
                statement_id=statement_id,
                fee_direction=2,
                confirmation_status=1,
                confirmed_amount_cent=confirmed_amount_cent,
                confirmed_by=store_id,
                confirmed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
        )
    db_session.commit()


def test_management_invoiceable_projection_offsets_continuous_negatives_oldest_first(
    db_session: Session,
) -> None:
    _seed_management_periods(
        db_session,
        [
            ("management-aug", "2026-08", 1000),
            ("management-sep", "2026-09", 800),
            ("management-oct", "2026-10", -1500),
            ("management-nov", "2026-11", -400),
            ("management-dec", "2026-12", 1200),
        ],
    )

    periods, applications = dashboard_routes._management_invoiceable_projection(
        db_session,
        store_id="g2-store-1",
        through_month="2026-12",
    )

    assert {
        period["statement_month"]: period["invoiceable_amount_cent"]
        for period in periods
    } == {
        "2026-08": 0,
        "2026-09": 0,
        "2026-10": 0,
        "2026-11": 0,
        "2026-12": 1100,
    }
    assert [
        (
            application["source_statement_id"],
            application["target_statement_id"],
            application["applied_amount_cent"],
        )
        for application in applications
    ] == [
        ("management-oct", "management-aug", 1000),
        ("management-oct", "management-sep", 500),
        ("management-nov", "management-sep", 300),
        ("management-nov", "management-dec", 100),
    ]


def test_management_import_validation_uses_projection_after_locked_invoice(
    db_session: Session,
) -> None:
    _seed_management_periods(
        db_session,
        [
            ("locked-management-aug", "2026-08", 1000),
            ("open-management-sep", "2026-09", 800),
            ("negative-management-oct", "2026-10", -1500),
            ("negative-management-nov", "2026-11", -400),
            ("open-management-dec", "2026-12", 1200),
        ],
    )
    db_session.add(
        InvoiceRecord(
            invoice_id="locked-management-invoice",
            store_id="g2-store-1",
            statement_month="2026-08",
            statement_id="locked-management-aug",
            fee_direction=2,
            version_no=1,
            is_current=True,
            invoice_number="60345678901234567890",
            invoice_date=date(2026, 9, 1),
            invoice_amount_cent=1000,
            invoice_status=3,
            source_type=2,
            import_batch_id="locked-management-batch",
            factory_deduction_date=date(2026, 9, 2),
            factory_deduction_amount_cent=1000,
            registered_by="system-admin",
        )
    )
    db_session.commit()

    periods, _ = dashboard_routes._management_invoiceable_projection(
        db_session,
        store_id="g2-store-1",
        through_month="2026-12",
    )
    assert {
        period["statement_month"]: period["invoiceable_amount_cent"]
        for period in periods
    }["2026-12"] == 100

    _, _, errors = dashboard_routes._validate_final_finance_import_row(
        db_session,
        import_type="MANAGEMENT_FACTORY_RESULT",
        statement_month="2026-12",
        row_number=2,
        raw_row={
            "storeId": "g2-store-1",
            "statementMonth": "2026-12",
            "storeName": "G2 Store",
            "invoiceNumber": "61345678901234567890",
            "invoiceDate": "2026-12-20",
            "deductionDate": "2026-12-21",
            "deductionAmountCent": "100",
        },
    )

    assert errors == []
    monthly_metrics = dashboard_routes._finance_summary_metrics(
        db_session,
        month="2026-12",
        fee_direction="MANAGEMENT",
        metric_scope="MONTH",
        store_id="g2-store-1",
    )
    cumulative_metrics = dashboard_routes._finance_summary_metrics(
        db_session,
        month="2026-12",
        fee_direction="MANAGEMENT",
        metric_scope="CUMULATIVE",
        store_id="g2-store-1",
    )
    assert monthly_metrics["pending_invoice_amount_cent"] == 100
    assert cumulative_metrics["pending_invoice_amount_cent"] == 100


def test_management_direct_correction_versions_replays_conflicts_and_audits(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_management_periods(
        db_session,
        [("management-correction-statement", "2026-08", 1000)],
    )
    db_session.add(
        InvoiceRecord(
            invoice_id="management-correction-v1",
            store_id="g2-store-1",
            statement_month="2026-08",
            statement_id="management-correction-statement",
            fee_direction=2,
            version_no=1,
            is_current=True,
            invoice_number="62345678901234567890",
            invoice_date=date(2026, 8, 20),
            invoice_amount_cent=900,
            invoice_status=3,
            source_type=2,
            import_batch_id="management-original-batch",
            factory_deduction_date=date(2026, 8, 21),
            factory_deduction_amount_cent=900,
            registered_by="system-admin",
        )
    )
    db_session.commit()
    _login(client)
    payload = {
        "invoiceNumber": "63345678901234567890",
        "invoiceDate": "2026-08-22",
        "invoiceAmountCent": 1000,
        "deductionDate": "2026-08-23",
        "deductionAmountCent": 1000,
        "changeReason": "修正厂家发票号码与日期",
        "readVersion": 1,
    }

    response = client.post(
        "/api/v1/admin/finance/management-invoices/g2-store-1/2026-08/corrections",
        json=payload,
        headers={"Idempotency-Key": "management-direct-correction-0001"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["versionNo"] == 2
    assert response.json()["data"]["invoiceAmountCent"] == 1000
    assert response.json()["data"]["factoryDeductionAmountCent"] == 1000
    versions = list(
        db_session.scalars(
            select(InvoiceRecord)
            .where(
                InvoiceRecord.store_id == "g2-store-1",
                InvoiceRecord.statement_month == "2026-08",
                InvoiceRecord.fee_direction == 2,
            )
            .order_by(InvoiceRecord.version_no)
        )
    )
    assert [version.is_current for version in versions] == [False, True]
    assert versions[-1].source_type == 3
    assert versions[-1].import_batch_id is None
    assert versions[-1].invoice_number == payload["invoiceNumber"]
    assert db_session.scalar(
        select(func.count())
        .select_from(FinanceOperationAudit)
        .where(FinanceOperationAudit.operation_type == "MANAGEMENT_INVOICE_CORRECTION")
    ) == 1

    replay = client.post(
        "/api/v1/admin/finance/management-invoices/g2-store-1/2026-08/corrections",
        json=payload,
        headers={"Idempotency-Key": "management-direct-correction-0001"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["invoiceId"] == response.json()["data"]["invoiceId"]
    assert db_session.scalar(select(func.count()).select_from(InvoiceRecord)) == 2

    reused = client.post(
        "/api/v1/admin/finance/management-invoices/g2-store-1/2026-08/corrections",
        json={**payload, "changeReason": "不同载荷"},
        headers={"Idempotency-Key": "management-direct-correction-0001"},
    )
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    stale = client.post(
        "/api/v1/admin/finance/management-invoices/g2-store-1/2026-08/corrections",
        json=payload,
        headers={"Idempotency-Key": "management-direct-correction-stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["data"]["currentVersion"] == 2

    _act_as_store(client)
    forbidden = client.post(
        "/api/v1/admin/finance/management-invoices/g2-store-1/2026-08/corrections",
        json={**payload, "readVersion": 2},
        headers={"Idempotency-Key": "management-direct-correction-store"},
    )
    assert forbidden.status_code == 403
    conflict_audits = list(
        db_session.scalars(
            select(FinanceOperationAudit).where(
                FinanceOperationAudit.operation_type
                == "MANAGEMENT_INVOICE_CORRECTION",
                FinanceOperationAudit.result_status == 2,
            )
        )
    )
    assert len(conflict_audits) >= 2
    assert all(audit.idempotency_key_hash is None for audit in conflict_audits)
    assert all(
        audit.after_snapshot.get("attemptedIdempotencyKeyHash")
        for audit in conflict_audits
    )


def test_sap_suggestion_store_scope_admin_decision_versions_and_search(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_management_periods(
        db_session,
        [("sap-search-statement", "2026-08", 1000)],
    )
    db_session.add(
        StoreFinanceProfile(
            profile_id="sap-profile-v1",
            store_id="g2-store-1",
            profile_type=2,
            source_type=1,
            version_no=1,
            is_current=True,
            store_name_snapshot="G2 Store",
            sap_code="SAP-OLD",
            factory_confirmed=True,
            confirmed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            import_batch_id="sap-import-v1",
        )
    )
    db_session.commit()

    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="global-admin",
        username="global-admin",
        display_name="Global Admin",
        role="admin",
        store_ids=(),
        auth_type="user",
        store_scope_mode="all",
        page_keys=("D01",),
    )
    admin_submit = client.post(
        "/api/v1/stores/g2-store-1/sap-suggestions",
        json={
            "suggestedSapCode": "SAP-ADMIN-FORBIDDEN",
            "suggestionNote": "管理员不得冒充门店提交建议",
            "readVersion": 0,
        },
        headers={"Idempotency-Key": "sap-suggestion-admin-forbidden"},
    )
    assert admin_submit.status_code == 403
    admin_list = client.get("/api/v1/stores/g2-store-1/sap-suggestions")
    assert admin_list.status_code == 403

    _act_as_store(client)
    payload = {
        "suggestedSapCode": "SAP-NEW",
        "suggestionNote": "门店确认应使用新的 SAP 编码",
        "readVersion": 0,
    }
    response = client.post(
        "/api/v1/stores/g2-store-1/sap-suggestions",
        json=payload,
        headers={"Idempotency-Key": "sap-suggestion-store-0001"},
    )
    assert response.status_code == 200
    suggestion = response.json()["data"]
    assert suggestion["versionNo"] == 1
    assert suggestion["status"] == "PENDING"
    replay = client.post(
        "/api/v1/stores/g2-store-1/sap-suggestions",
        json=payload,
        headers={"Idempotency-Key": "sap-suggestion-store-0001"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["suggestionId"] == suggestion["suggestionId"]
    assert db_session.scalar(select(func.count()).select_from(SapSuggestion)) == 1
    forbidden_scope = client.post(
        "/api/v1/stores/other-store/sap-suggestions",
        json=payload,
        headers={"Idempotency-Key": "sap-suggestion-store-other"},
    )
    assert forbidden_scope.status_code == 403

    client.app.dependency_overrides.pop(get_current_user, None)
    _login(client)
    decision = {
        "action": "CORRECT",
        "confirmedSapCode": "SAP-CORRECTED",
        "handlingReason": "按财务主数据修正后确认",
        "suggestionVersion": 1,
        "expectedConfirmedVersion": 1,
    }
    decided = client.post(
        f"/api/v1/admin/finance/sap-suggestions/{suggestion['suggestionId']}/decisions",
        json=decision,
        headers={"Idempotency-Key": "sap-suggestion-decision-0001"},
    )
    assert decided.status_code == 200
    assert decided.json()["data"]["status"] == "CORRECTED"
    assert decided.json()["data"]["versionNo"] == 2
    assert decided.json()["data"]["confirmedVersion"] == 2
    suggestion_versions = list(
        db_session.scalars(
            select(SapSuggestion)
            .where(SapSuggestion.store_id == "g2-store-1")
            .order_by(SapSuggestion.version_no)
        )
    )
    assert len(suggestion_versions) == 2
    assert suggestion_versions[0].is_current is False
    assert suggestion_versions[0].suggestion_status == 1
    assert suggestion_versions[0].handled_at is None
    assert suggestion_versions[1].is_current is True
    assert suggestion_versions[1].supersedes_suggestion_id == suggestion["suggestionId"]
    assert suggestion_versions[1].suggestion_status == 3
    profiles = list(
        db_session.scalars(
            select(StoreFinanceProfile)
            .where(
                StoreFinanceProfile.store_id == "g2-store-1",
                StoreFinanceProfile.profile_type == 2,
            )
            .order_by(StoreFinanceProfile.version_no)
        )
    )
    assert [profile.is_current for profile in profiles] == [False, True]
    assert profiles[-1].sap_code == "SAP-CORRECTED"
    assert profiles[-1].source_type == 2
    assert profiles[-1].import_batch_id is None
    assert db_session.scalar(
        select(func.count())
        .select_from(FinanceOperationAudit)
        .where(FinanceOperationAudit.operation_type.in_(("SAP_SUGGESTION_SUBMIT", "SAP_SUGGESTION_DECISION")))
    ) == 2

    decision_replay = client.post(
        f"/api/v1/admin/finance/sap-suggestions/{suggestion['suggestionId']}/decisions",
        json=decision,
        headers={"Idempotency-Key": "sap-suggestion-decision-0001"},
    )
    assert decision_replay.status_code == 200
    assert decision_replay.json()["data"]["suggestionId"] == suggestion_versions[1].suggestion_id
    assert decision_replay.json()["data"]["versionNo"] == 2
    assert decision_replay.json()["data"]["confirmedVersion"] == 2

    db_session.add_all(
        [
            DimStore(
                store_id="g2-store-without-statement",
                store_name="G2 No Statement Store",
                is_active=True,
            ),
            SapSuggestion(
                suggestion_id="sap-no-statement-v1",
                store_id="g2-store-without-statement",
                version_no=1,
                is_current=True,
                suggested_sap_code="SAP-NO-STATEMENT",
                suggestion_note="无当月账单也必须进入管理员队列",
                suggestion_status=1,
                submitted_by="g2-store-without-statement-user",
                submitted_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()
    no_statement_search = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "MANAGEMENT",
            "metricScope": "MONTH",
            "q": "SAP-NO-STATEMENT",
        },
    )
    assert no_statement_search.status_code == 200
    assert no_statement_search.json()["data"]["total"] == 1
    assert no_statement_search.json()["data"]["list"][0]["storeId"] == "g2-store-without-statement"

    store_search = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "MANAGEMENT",
            "metricScope": "MONTH",
            "q": "SAP-CORRECTED",
        },
    )
    assert store_search.status_code == 200
    assert store_search.json()["data"]["total"] == 1
    row = store_search.json()["data"]["list"][0]
    assert row["sapCode"] == "SAP-CORRECTED"
    assert row["confirmedVersion"] == 2
    assert row["suggestionStatus"] == "CORRECTED"

    stale_decision = client.post(
        f"/api/v1/admin/finance/sap-suggestions/{suggestion['suggestionId']}/decisions",
        json={**decision, "handlingReason": "重复处理旧建议"},
        headers={"Idempotency-Key": "sap-suggestion-decision-stale"},
    )
    assert stale_decision.status_code == 409
    assert db_session.scalar(
        select(func.count())
        .select_from(FinanceOperationAudit)
        .where(
            FinanceOperationAudit.operation_type == "SAP_SUGGESTION_DECISION",
            FinanceOperationAudit.result_status == 2,
        )
    ) == 1

    _act_as_store(client)
    forbidden_decision = client.post(
        f"/api/v1/admin/finance/sap-suggestions/{suggestion['suggestionId']}/decisions",
        json=decision,
        headers={"Idempotency-Key": "sap-suggestion-decision-store"},
    )
    assert forbidden_decision.status_code == 403


def test_sap_decision_uses_independent_suggestion_and_confirmed_version_locks(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            DimStore(
                store_id="g2-store-1",
                store_name="G2 Store",
                is_active=True,
            ),
            StoreFinanceProfile(
                profile_id="sap-lock-profile-v1",
                store_id="g2-store-1",
                profile_type=2,
                source_type=1,
                version_no=1,
                is_current=True,
                store_name_snapshot="G2 Store",
                sap_code="SAP-LOCK-V1",
                factory_confirmed=True,
                confirmed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                import_batch_id="sap-lock-import-v1",
            ),
        ]
    )
    db_session.commit()
    _act_as_store(client)
    submitted = client.post(
        "/api/v1/stores/g2-store-1/sap-suggestions",
        json={
            "suggestedSapCode": "SAP-LOCK-SUGGESTED",
            "suggestionNote": "验证建议和确认值使用独立版本锁",
            "readVersion": 0,
        },
        headers={"Idempotency-Key": "sap-lock-submit-0001"},
    )
    assert submitted.status_code == 200
    suggestion_id = submitted.json()["data"]["suggestionId"]

    client.app.dependency_overrides.pop(get_current_user, None)
    _login(client)
    stale_suggestion = client.post(
        f"/api/v1/admin/finance/sap-suggestions/{suggestion_id}/decisions",
        json={
            "action": "CONFIRM",
            "handlingReason": "使用错误的建议读取版本",
            "suggestionVersion": 2,
            "expectedConfirmedVersion": 1,
        },
        headers={"Idempotency-Key": "sap-lock-stale-suggestion-0001"},
    )
    assert stale_suggestion.status_code == 409
    assert stale_suggestion.json()["detail"]["code"] == "SUGGESTION_VERSION_CONFLICT"

    profile_v1 = db_session.scalar(
        select(StoreFinanceProfile).where(
            StoreFinanceProfile.profile_id == "sap-lock-profile-v1"
        )
    )
    assert profile_v1 is not None
    profile_v1.is_current = False
    db_session.add(
        StoreFinanceProfile(
            profile_id="sap-lock-profile-v2",
            store_id="g2-store-1",
            profile_type=2,
            source_type=1,
            version_no=2,
            is_current=True,
            store_name_snapshot="G2 Store",
            sap_code="SAP-LOCK-V2",
            factory_confirmed=True,
            confirmed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            import_batch_id="sap-lock-import-v2",
        )
    )
    db_session.commit()
    stale_confirmed = client.post(
        f"/api/v1/admin/finance/sap-suggestions/{suggestion_id}/decisions",
        json={
            "action": "CONFIRM",
            "handlingReason": "确认值已由导入更新",
            "suggestionVersion": 1,
            "expectedConfirmedVersion": 1,
        },
        headers={"Idempotency-Key": "sap-lock-stale-confirmed-0001"},
    )
    assert stale_confirmed.status_code == 409
    assert stale_confirmed.json()["detail"]["code"] == "CONFIRMED_VERSION_CONFLICT"
    assert db_session.scalar(select(func.count()).select_from(SapSuggestion)) == 1

    payload = {
        "action": "CONFIRM",
        "handlingReason": "按最新确认版本处理",
        "suggestionVersion": 1,
        "expectedConfirmedVersion": 2,
    }
    decided = client.post(
        f"/api/v1/admin/finance/sap-suggestions/{suggestion_id}/decisions",
        json=payload,
        headers={"Idempotency-Key": "sap-lock-success-0001"},
    )
    assert decided.status_code == 200
    assert decided.json()["data"]["versionNo"] == 2
    assert decided.json()["data"]["confirmedVersion"] == 3
    replay = client.post(
        f"/api/v1/admin/finance/sap-suggestions/{suggestion_id}/decisions",
        json=payload,
        headers={"Idempotency-Key": "sap-lock-success-0001"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["suggestionId"] == decided.json()["data"]["suggestionId"]
    versions = list(
        db_session.scalars(
            select(SapSuggestion)
            .where(SapSuggestion.store_id == "g2-store-1")
            .order_by(SapSuggestion.version_no)
        )
    )
    assert [version.is_current for version in versions] == [False, True]
    assert versions[0].handled_at is None
    assert versions[1].supersedes_suggestion_id == versions[0].suggestion_id


def _seed_committed_import(
    db_session: Session,
    *,
    batch_id: str,
    import_type: int,
    month: str,
    target_record_id: str,
    business_key: str,
) -> None:
    committed_at = datetime(2026, 8, 20, tzinfo=timezone.utc)
    db_session.add(
        FinanceImportBatch(
            batch_id=batch_id,
            import_type=import_type,
            statement_month=month,
            file_name=f"{batch_id}.xlsx",
            file_sha256="a" * 64,
            normalized_sha256="b" * 64,
            read_version=0,
            current_version=1,
            batch_status=5,
            total_rows=1,
            success_rows=1,
            error_rows=0,
            content_changed=True,
            submitted_by="system-admin",
            committed_by="system-admin",
            submitted_at=committed_at,
            committed_at=committed_at,
        )
    )
    db_session.add(
        FinanceImportRow(
            batch_id=batch_id,
            row_number=2,
            business_key=business_key,
            normalized_payload={"businessKey": business_key},
            row_status=5,
            validation_errors=[],
            target_record_id=target_record_id,
        )
    )


def test_finance_import_version_slot_uses_postgres_lock_and_final_version_constraint(
    db_session: Session,
) -> None:
    executed: list[tuple[str, dict]] = []

    class FakePostgresSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, parameters):
            executed.append((str(statement), parameters))

    dashboard_routes._lock_finance_import_version_slot(
        FakePostgresSession(),
        import_type=3,
        statement_month="2026-08",
    )
    assert "pg_advisory_xact_lock" in executed[0][0]
    assert executed[0][1]["slot_key"] == "finance-import-version:3:2026-08"

    for batch_id in ("concurrent-final-a", "concurrent-final-b"):
        _seed_committed_import(
            db_session,
            batch_id=batch_id,
            import_type=3,
            month="2026-08",
            target_record_id=f"{batch_id}-target",
            business_key=f"{batch_id}-business",
        )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_finance_import_reversal_locks_version_slot_before_business_targets(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(client)
    _seed_committed_import(
        db_session,
        batch_id="reversal-lock-order-batch",
        import_type=3,
        month="2026-08",
        target_record_id="reversal-lock-order-target",
        business_key="g2-store-1|2026-08",
    )
    db_session.commit()
    lock_order: list[str] = []

    def record_version_slot(*args, **kwargs) -> None:
        lock_order.append("version-slot")

    def stop_after_business_lock_plan(*args, **kwargs):
        lock_order.append("business-targets")
        raise RuntimeError("stop after observing lock order")

    monkeypatch.setattr(
        dashboard_routes,
        "_lock_finance_import_version_slot",
        record_version_slot,
    )
    monkeypatch.setattr(
        dashboard_routes,
        "_finance_import_reversal_plan",
        stop_after_business_lock_plan,
    )

    with pytest.raises(RuntimeError, match="stop after observing lock order"):
        response = client.post(
            "/api/v1/admin/finance-imports/reversal-lock-order-batch/reversals",
            json={"readVersion": 1, "changeReason": "验证统一锁顺序"},
            headers={"Idempotency-Key": "reversal-lock-order-0001"},
        )
        pytest.fail(
            f"expected reversal plan to run, got {response.status_code}: {response.text}"
        )

    assert lock_order == ["version-slot", "business-targets"]


def test_finance_import_reversal_restores_or_tombstones_all_four_fact_types(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add(DimStore(store_id="g2-store-1", store_name="G2 Store", is_active=True))
    _seed_committed_import(
        db_session,
        batch_id="basic-batch-v1",
        import_type=1,
        month="2026-08",
        target_record_id="basic-profile-v1",
        business_key="g2-store-1",
    )
    db_session.add(
        StoreFinanceProfile(
            profile_id="basic-profile-v1",
            store_id="g2-store-1",
            profile_type=1,
            source_type=1,
            version_no=1,
            is_current=True,
            store_name_snapshot="G2 Store",
            sap_code="BASIC-SAP",
            import_batch_id="basic-batch-v1",
        )
    )

    _seed_committed_import(
        db_session,
        batch_id="sap-batch-v2",
        import_type=4,
        month="2026-09",
        target_record_id="sap-profile-import-v2",
        business_key="g2-store-1",
    )
    db_session.add_all(
        [
            StoreFinanceProfile(
                profile_id="sap-profile-page-v1",
                store_id="g2-store-1",
                profile_type=2,
                source_type=2,
                version_no=1,
                is_current=False,
                store_name_snapshot="G2 Store",
                sap_code="SAP-PREVIOUS",
                factory_confirmed=True,
                confirmed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                import_batch_id=None,
            ),
            StoreFinanceProfile(
                profile_id="sap-profile-import-v2",
                store_id="g2-store-1",
                profile_type=2,
                source_type=1,
                version_no=2,
                is_current=True,
                store_name_snapshot="G2 Store",
                sap_code="SAP-IMPORTED",
                factory_confirmed=True,
                confirmed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                import_batch_id="sap-batch-v2",
            ),
        ]
    )

    _seed_committed_import(
        db_session,
        batch_id="management-batch-v1",
        import_type=3,
        month="2026-10",
        target_record_id="management-import-v1",
        business_key="g2-store-1|2026-10",
    )
    db_session.add(
        InvoiceRecord(
            invoice_id="management-import-v1",
            store_id="g2-store-1",
            statement_month="2026-10",
            statement_id="management-statement-oct",
            fee_direction=2,
            version_no=1,
            is_current=True,
            invoice_number="64345678901234567890",
            invoice_date=date(2026, 10, 20),
            invoice_amount_cent=1000,
            invoice_status=3,
            source_type=2,
            import_batch_id="management-batch-v1",
            factory_deduction_date=date(2026, 10, 21),
            factory_deduction_amount_cent=1000,
            registered_by="system-admin",
        )
    )

    _seed_committed_import(
        db_session,
        batch_id="promotion-batch-v1",
        import_type=2,
        month="2026-11",
        target_record_id="promotion-result-v2",
        business_key="65345678901234567890|2026-11",
    )
    db_session.add_all(
        [
            PromotionInvoice(
                invoice_id="promotion-registration-v1",
                physical_invoice_id="promotion-physical-1",
                store_id="g2-store-1",
                version_no=1,
                version_kind=1,
                is_current=False,
                invoice_number="65345678901234567890",
                invoice_date=date(2026, 11, 20),
                invoice_amount_cent=1000,
                buyer_name="比亚迪汽车销售有限公司",
                tax_rate_percent=6,
                invoice_status=2,
                registered_by="g2-store-1-user",
            ),
            PromotionInvoice(
                invoice_id="promotion-result-v2",
                physical_invoice_id="promotion-physical-1",
                store_id="g2-store-1",
                version_no=2,
                version_kind=2,
                is_current=True,
                supersedes_invoice_id="promotion-registration-v1",
                invoice_number="65345678901234567890",
                invoice_date=date(2026, 11, 20),
                invoice_amount_cent=1000,
                buyer_name="比亚迪汽车销售有限公司",
                tax_rate_percent=6,
                invoice_status=3,
                registered_by="g2-store-1-user",
            ),
            PromotionInvoiceAllocation(
                allocation_id="promotion-allocation-v1",
                invoice_id="promotion-registration-v1",
                store_id="g2-store-1",
                statement_id="promotion-statement-nov",
                statement_month="2026-11",
                settlement_batch_month="2026-11",
                allocated_amount_cent=1000,
                is_current=False,
            ),
            PromotionInvoiceAllocation(
                allocation_id="promotion-allocation-v2",
                invoice_id="promotion-result-v2",
                store_id="g2-store-1",
                statement_id="promotion-statement-nov",
                statement_month="2026-11",
                settlement_batch_month="2026-11",
                allocated_amount_cent=1000,
                is_current=True,
            ),
        ]
    )
    db_session.commit()
    _login(client)

    responses = {}
    for batch_id in (
        "basic-batch-v1",
        "sap-batch-v2",
        "management-batch-v1",
        "promotion-batch-v1",
    ):
        response = client.post(
            f"/api/v1/admin/finance-imports/{batch_id}/reversals",
            json={"readVersion": 1, "changeReason": f"撤销 {batch_id}"},
            headers={"Idempotency-Key": f"reversal-{batch_id}-0001"},
        )
        assert response.status_code == 200, response.text
        responses[batch_id] = response.json()["data"]
        assert responses[batch_id]["scenario"] == "REVERSED"
        assert responses[batch_id]["reversesBatchId"] == batch_id

    basic_current = db_session.scalar(
        select(StoreFinanceProfile).where(
            StoreFinanceProfile.store_id == "g2-store-1",
            StoreFinanceProfile.profile_type == 1,
            StoreFinanceProfile.is_current.is_(True),
        )
    )
    assert basic_current is not None and basic_current.is_tombstone is True
    assert basic_current.version_no == 2
    sap_current = db_session.scalar(
        select(StoreFinanceProfile).where(
            StoreFinanceProfile.store_id == "g2-store-1",
            StoreFinanceProfile.profile_type == 2,
            StoreFinanceProfile.is_current.is_(True),
        )
    )
    assert sap_current is not None and sap_current.sap_code == "SAP-PREVIOUS"
    assert sap_current.version_no == 3 and sap_current.source_type == 3
    management_current = db_session.scalar(
        select(InvoiceRecord).where(
            InvoiceRecord.invoice_id.not_in(["management-import-v1"]),
            InvoiceRecord.store_id == "g2-store-1",
            InvoiceRecord.statement_month == "2026-10",
            InvoiceRecord.is_current.is_(True),
        )
    )
    assert management_current is not None and management_current.is_tombstone is True
    promotion_current = db_session.scalar(
        select(PromotionInvoice).where(
            PromotionInvoice.physical_invoice_id == "promotion-physical-1",
            PromotionInvoice.is_current.is_(True),
        )
    )
    assert promotion_current is not None
    assert promotion_current.invoice_status == 2
    assert promotion_current.version_no == 3
    assert db_session.scalar(
        select(func.count())
        .select_from(FinanceImportRow)
        .where(FinanceImportRow.reversal_effect_type.is_not(None))
    ) == 4
    assert db_session.scalar(
        select(func.count())
        .select_from(FinanceOperationAudit)
        .where(FinanceOperationAudit.operation_type == "FINANCE_IMPORT_REVERSAL")
    ) == 4

    replay = client.post(
        "/api/v1/admin/finance-imports/basic-batch-v1/reversals",
        json={"readVersion": 1, "changeReason": "撤销 basic-batch-v1"},
        headers={"Idempotency-Key": "reversal-basic-batch-v1-0001"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["batchId"] == responses["basic-batch-v1"]["batchId"]
    original_detail = client.get("/api/v1/admin/finance-imports/basic-batch-v1")
    assert original_detail.status_code == 200
    original_data = original_detail.json()["data"]
    assert original_data["canReverse"] is False
    assert original_data["reverseNotAllowedCode"] == "IMPORT_ALREADY_REVERSED"
    assert original_data["reversedByBatchId"] == responses["basic-batch-v1"]["batchId"]
    assert original_data["reversalChain"] == [
        "basic-batch-v1",
        responses["basic-batch-v1"]["batchId"],
    ]
    reversal_rows = original_data["reversalRows"]
    assert reversal_rows["total"] == 1
    assert reversal_rows["list"] == [
        {
            "businessKey": "g2-store-1",
            "originalTargetRecordId": "basic-profile-v1",
            "previousTargetRecordId": None,
            "reversalTargetRecordId": basic_current.profile_id,
            "effectType": "TOMBSTONE",
            "isCurrent": True,
        }
    ]


def test_reversal_of_reimport_preserves_previous_tombstone_for_all_fact_types(
    db_session: Session,
) -> None:
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    reversal_batch = FinanceImportBatch(
        batch_id="second-reversal-batch",
        import_type=1,
        statement_month="2026-12",
        file_name="second-reversal.xlsx",
        file_sha256="c" * 64,
        normalized_sha256="d" * 64,
        read_version=2,
        current_version=3,
        batch_status=9,
        total_rows=3,
        success_rows=3,
        error_rows=0,
        content_changed=True,
        reverses_batch_id="reimport-batch",
        submitted_by="system-admin",
        committed_by="system-admin",
        submitted_at=now,
        committed_at=now,
    )
    profile_tombstone = StoreFinanceProfile(
        profile_id="profile-tombstone-v2",
        store_id="g2-store-1",
        profile_type=1,
        source_type=3,
        version_no=2,
        is_current=False,
        is_tombstone=True,
        store_name_snapshot="G2 Store",
        import_batch_id="first-reversal-batch",
    )
    profile_reimport = StoreFinanceProfile(
        profile_id="profile-reimport-v3",
        store_id="g2-store-1",
        profile_type=1,
        source_type=1,
        version_no=3,
        is_current=True,
        store_name_snapshot="G2 Store Reimported",
        import_batch_id="reimport-batch",
    )
    management_tombstone = InvoiceRecord(
        invoice_id="management-tombstone-v2",
        store_id="g2-store-1",
        statement_month="2026-12",
        statement_id="management-dec",
        fee_direction=2,
        version_no=2,
        is_current=False,
        is_tombstone=True,
        invoice_number="68345678901234567890",
        invoice_date=date(2026, 12, 20),
        invoice_amount_cent=1000,
        invoice_status=3,
        source_type=3,
        import_batch_id="first-reversal-batch",
        factory_deduction_date=date(2026, 12, 21),
        factory_deduction_amount_cent=1000,
        registered_by="system-admin",
    )
    management_reimport = InvoiceRecord(
        invoice_id="management-reimport-v3",
        store_id="g2-store-1",
        statement_month="2026-12",
        statement_id="management-dec",
        fee_direction=2,
        version_no=3,
        is_current=True,
        invoice_number="69345678901234567890",
        invoice_date=date(2026, 12, 22),
        invoice_amount_cent=1000,
        invoice_status=3,
        source_type=2,
        import_batch_id="reimport-batch",
        factory_deduction_date=date(2026, 12, 23),
        factory_deduction_amount_cent=1000,
        registered_by="system-admin",
    )
    promotion_tombstone = PromotionInvoice(
        invoice_id="promotion-tombstone-v2",
        physical_invoice_id="promotion-physical-reimport",
        store_id="g2-store-1",
        version_no=2,
        version_kind=2,
        is_current=False,
        is_tombstone=True,
        invoice_number="70345678901234567890",
        invoice_date=date(2026, 12, 20),
        invoice_amount_cent=1000,
        buyer_name="比亚迪汽车销售有限公司",
        tax_rate_percent=6,
        invoice_status=3,
        registered_by="g2-store-1-user",
    )
    promotion_reimport = PromotionInvoice(
        invoice_id="promotion-reimport-v3",
        physical_invoice_id="promotion-physical-reimport",
        store_id="g2-store-1",
        version_no=3,
        version_kind=2,
        is_current=True,
        supersedes_invoice_id=promotion_tombstone.invoice_id,
        invoice_number="71345678901234567890",
        invoice_date=date(2026, 12, 22),
        invoice_amount_cent=1000,
        buyer_name="比亚迪汽车销售有限公司",
        tax_rate_percent=6,
        invoice_status=3,
        registered_by="g2-store-1-user",
    )
    db_session.add_all(
        [
            reversal_batch,
            profile_tombstone,
            profile_reimport,
            management_tombstone,
            management_reimport,
            promotion_tombstone,
            promotion_reimport,
        ]
    )
    db_session.flush()

    restored_profile = dashboard_routes._append_profile_reversal_version(
        db_session,
        target=profile_reimport,
        previous=profile_tombstone,
        batch=reversal_batch,
        now=now,
    )
    restored_management = dashboard_routes._append_management_reversal_version(
        db_session,
        target=management_reimport,
        previous=management_tombstone,
        batch=reversal_batch,
        operator_id="system-admin",
        now=now,
    )
    restored_promotion = dashboard_routes._append_promotion_reversal_version(
        db_session,
        target=promotion_reimport,
        previous=promotion_tombstone,
        batch=reversal_batch,
        operator_id="system-admin",
        now=now,
    )

    assert restored_profile.is_tombstone is True
    assert restored_management.is_tombstone is True
    assert restored_promotion.is_tombstone is True


def test_management_reversal_to_previous_tombstone_reprojects_and_reports_tombstone(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(
        DimStore(store_id="g2-store-tombstone", store_name="G2 Tombstone", is_active=True)
    )
    _seed_committed_import(
        db_session,
        batch_id="management-reimport-batch",
        import_type=3,
        month="2026-12",
        target_record_id="management-reimport-v3",
        business_key="g2-store-tombstone|2026-12",
    )
    previous_tombstone = InvoiceRecord(
        invoice_id="management-tombstone-v2",
        store_id="g2-store-tombstone",
        statement_month="2026-12",
        statement_id="management-tombstone-dec",
        fee_direction=2,
        version_no=2,
        is_current=False,
        is_tombstone=True,
        invoice_number="72345678901234567890",
        invoice_date=date(2026, 12, 20),
        invoice_amount_cent=1000,
        invoice_status=3,
        source_type=3,
        import_batch_id="first-reversal-batch",
        factory_deduction_date=date(2026, 12, 21),
        factory_deduction_amount_cent=1000,
        registered_by="system-admin",
    )
    current_reimport = InvoiceRecord(
        invoice_id="management-reimport-v3",
        store_id="g2-store-tombstone",
        statement_month="2026-12",
        statement_id="management-tombstone-dec",
        fee_direction=2,
        version_no=3,
        is_current=True,
        is_tombstone=False,
        invoice_number="73345678901234567890",
        invoice_date=date(2026, 12, 22),
        invoice_amount_cent=1000,
        invoice_status=3,
        source_type=2,
        import_batch_id="management-reimport-batch",
        factory_deduction_date=date(2026, 12, 23),
        factory_deduction_amount_cent=1000,
        registered_by="system-admin",
    )
    db_session.add_all([previous_tombstone, current_reimport])
    db_session.commit()

    synchronized: list[dict] = []

    def capture_synchronization(_session, **kwargs):
        synchronized.append(kwargs)

    monkeypatch.setattr(
        dashboard_routes,
        "_synchronize_management_carryforward_applications",
        capture_synchronization,
    )
    _login(client)
    response = client.post(
        "/api/v1/admin/finance-imports/management-reimport-batch/reversals",
        json={"readVersion": 1, "changeReason": "恢复历史 tombstone"},
        headers={"Idempotency-Key": "management-reimport-reversal"},
    )

    assert response.status_code == 200, response.text
    assert synchronized[-1]["invoice_id_by_statement"] == {}
    detail = client.get("/api/v1/admin/finance-imports/management-reimport-batch")
    assert detail.status_code == 200
    assert detail.json()["data"]["reversalRows"]["list"][0]["effectType"] == "TOMBSTONE"


def test_finance_import_reversal_rejects_one_overwritten_business_key_atomically(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            DimStore(store_id="g2-store-1", store_name="G2 Store", is_active=True),
            DimStore(store_id="g2-store-2", store_name="G2 Store 2", is_active=True),
        ]
    )
    _seed_committed_import(
        db_session,
        batch_id="basic-two-row-batch",
        import_type=1,
        month="2026-08",
        target_record_id="basic-store-1-v1",
        business_key="g2-store-1",
    )
    db_session.flush()
    batch = db_session.scalar(
        select(FinanceImportBatch).where(FinanceImportBatch.batch_id == "basic-two-row-batch")
    )
    assert batch is not None
    batch.total_rows = 2
    batch.success_rows = 2
    db_session.add(
        FinanceImportRow(
            batch_id=batch.batch_id,
            row_number=3,
            business_key="g2-store-2",
            normalized_payload={"businessKey": "g2-store-2"},
            row_status=5,
            validation_errors=[],
            target_record_id="basic-store-2-v1",
        )
    )
    db_session.add_all(
        [
            StoreFinanceProfile(
                profile_id="basic-store-1-v1",
                store_id="g2-store-1",
                profile_type=1,
                source_type=1,
                version_no=1,
                is_current=False,
                store_name_snapshot="G2 Store",
                import_batch_id=batch.batch_id,
            ),
            StoreFinanceProfile(
                profile_id="basic-store-1-page-v2",
                store_id="g2-store-1",
                profile_type=1,
                source_type=2,
                version_no=2,
                is_current=True,
                store_name_snapshot="G2 Store Updated",
                import_batch_id=None,
            ),
            StoreFinanceProfile(
                profile_id="basic-store-2-v1",
                store_id="g2-store-2",
                profile_type=1,
                source_type=1,
                version_no=1,
                is_current=True,
                store_name_snapshot="G2 Store 2",
                import_batch_id=batch.batch_id,
            ),
        ]
    )
    db_session.commit()
    _login(client)

    detail_before_reversal = client.get(
        "/api/v1/admin/finance-imports/basic-two-row-batch"
    )
    assert detail_before_reversal.status_code == 200
    detail_data = detail_before_reversal.json()["data"]
    assert detail_data["canReverse"] is False
    assert detail_data["reverseNotAllowedCode"] == "REVERSAL_BUSINESS_VERSION_CONFLICT"
    assert "g2-store-1" in detail_data["reverseNotAllowedReason"]
    assert detail_data["reversedByBatchId"] is None
    assert detail_data["reversalChain"] == ["basic-two-row-batch"]

    list_before_reversal = client.get(
        "/api/v1/admin/finance-imports",
        params={"statementMonth": "2026-08", "pageSize": 50},
    )
    listed_batch = next(
        item
        for item in list_before_reversal.json()["data"]["list"]
        if item["batchId"] == "basic-two-row-batch"
    )
    assert listed_batch["canReverse"] is False
    assert listed_batch["reverseNotAllowedCode"] == "REVERSAL_BUSINESS_VERSION_CONFLICT"

    response = client.post(
        "/api/v1/admin/finance-imports/basic-two-row-batch/reversals",
        json={"readVersion": 1, "changeReason": "整批撤销"},
        headers={"Idempotency-Key": "reversal-two-row-conflict"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVERSAL_BUSINESS_VERSION_CONFLICT"
    conflict_audit = db_session.scalar(
        select(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "FINANCE_IMPORT_REVERSAL",
            FinanceOperationAudit.result_status == 2,
        )
    )
    assert conflict_audit is not None
    assert conflict_audit.idempotency_key_hash is None
    assert (
        conflict_audit.after_snapshot["conflictCode"]
        == "REVERSAL_BUSINESS_VERSION_CONFLICT"
    )
    assert db_session.scalar(
        select(func.count())
        .select_from(FinanceImportBatch)
        .where(FinanceImportBatch.reverses_batch_id == "basic-two-row-batch")
    ) == 0
    assert db_session.scalar(
        select(func.count())
        .select_from(StoreFinanceProfile)
        .where(StoreFinanceProfile.store_id == "g2-store-2")
    ) == 1


def test_management_carryforward_applications_version_with_invoice_and_tombstone(
    db_session: Session,
) -> None:
    _seed_management_periods(
        db_session,
        [
            ("management-positive-aug", "2026-08", 1000),
            ("management-negative-sep", "2026-09", -600),
        ],
    )
    periods, applications = dashboard_routes._management_invoiceable_projection(
        db_session, store_id="g2-store-1", through_month="2026-09"
    )
    assert periods[0]["invoiceable_amount_cent"] == 400
    invoice_v1 = InvoiceRecord(
        invoice_id="management-net-v1",
        store_id="g2-store-1",
        statement_month="2026-08",
        statement_id="management-positive-aug",
        fee_direction=2,
        version_no=1,
        is_current=True,
        invoice_number="66345678901234567890",
        invoice_date=date(2026, 9, 20),
        invoice_amount_cent=400,
        invoice_status=3,
        source_type=2,
        import_batch_id="management-net-batch-v1",
        factory_deduction_date=date(2026, 9, 21),
        factory_deduction_amount_cent=400,
        registered_by="system-admin",
    )
    db_session.add(invoice_v1)
    db_session.flush()
    dashboard_routes._synchronize_management_carryforward_applications(
        db_session,
        applications=applications,
        invoice_id_by_statement={"management-positive-aug": invoice_v1.invoice_id},
    )
    db_session.commit()
    current_application = db_session.scalar(
        select(ManagementCarryforwardApplication).where(
            ManagementCarryforwardApplication.is_current.is_(True)
        )
    )
    assert current_application is not None
    assert current_application.invoice_id == invoice_v1.invoice_id
    assert current_application.applied_amount_cent == 600

    locked_periods, locked_applications = dashboard_routes._management_invoiceable_projection(
        db_session, store_id="g2-store-1", through_month="2026-09"
    )
    assert locked_periods[0]["invoiceable_amount_cent"] == 0
    assert locked_applications[0]["invoice_id"] == invoice_v1.invoice_id

    invoice_v1.is_current = False
    invoice_v2 = InvoiceRecord(
        invoice_id="management-net-v2",
        store_id=invoice_v1.store_id,
        statement_month=invoice_v1.statement_month,
        statement_id=invoice_v1.statement_id,
        fee_direction=2,
        version_no=2,
        is_current=True,
        invoice_number="67345678901234567890",
        invoice_date=date(2026, 9, 22),
        invoice_amount_cent=400,
        invoice_status=3,
        source_type=3,
        import_batch_id=None,
        factory_deduction_date=date(2026, 9, 23),
        factory_deduction_amount_cent=400,
        registered_by="system-admin",
    )
    db_session.add(invoice_v2)
    db_session.flush()
    dashboard_routes._synchronize_management_carryforward_applications(
        db_session,
        applications=locked_applications,
        invoice_id_by_statement={"management-positive-aug": invoice_v2.invoice_id},
    )
    db_session.commit()
    versions = list(
        db_session.scalars(
            select(ManagementCarryforwardApplication).order_by(
                ManagementCarryforwardApplication.version_no
            )
        )
    )
    assert [version.is_current for version in versions] == [False, True]
    assert versions[-1].invoice_id == invoice_v2.invoice_id

    invoice_v2.is_current = False
    db_session.add(
        InvoiceRecord(
            invoice_id="management-net-v3-tombstone",
            store_id=invoice_v2.store_id,
            statement_month=invoice_v2.statement_month,
            statement_id=invoice_v2.statement_id,
            fee_direction=2,
            version_no=3,
            is_current=True,
            is_tombstone=True,
            invoice_number=invoice_v2.invoice_number,
            invoice_date=invoice_v2.invoice_date,
            invoice_amount_cent=invoice_v2.invoice_amount_cent,
            invoice_status=invoice_v2.invoice_status,
            source_type=3,
            import_batch_id="management-reversal-batch",
            factory_deduction_date=invoice_v2.factory_deduction_date,
            factory_deduction_amount_cent=invoice_v2.factory_deduction_amount_cent,
            registered_by="system-admin",
        )
    )
    db_session.flush()
    reopened_periods, reopened_applications = dashboard_routes._management_invoiceable_projection(
        db_session, store_id="g2-store-1", through_month="2026-09"
    )
    assert reopened_periods[0]["invoiceable_amount_cent"] == 400
    dashboard_routes._synchronize_management_carryforward_applications(
        db_session, applications=reopened_applications, invoice_id_by_statement={}
    )
    db_session.commit()
    latest = db_session.scalar(
        select(ManagementCarryforwardApplication).where(
            ManagementCarryforwardApplication.is_current.is_(True)
        )
    )
    assert latest is not None and latest.invoice_id is None
    assert latest.version_no == 3


def test_management_carryforward_sync_retires_empty_and_disjoint_scope(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            ManagementCarryforwardApplication(
                application_id="stale-empty-scope",
                store_id="g2-store-1",
                source_statement_id="old-negative",
                source_statement_month="2026-08",
                target_statement_id="old-positive",
                target_statement_month="2026-09",
                applied_amount_cent=100,
                version_no=1,
                is_current=True,
                projection_sha256="a" * 64,
            ),
            ManagementCarryforwardApplication(
                application_id="outside-scope",
                store_id="g2-store-2",
                source_statement_id="outside-negative",
                source_statement_month="2026-08",
                target_statement_id="outside-positive",
                target_statement_month="2026-09",
                applied_amount_cent=100,
                version_no=1,
                is_current=True,
                projection_sha256="b" * 64,
            ),
        ]
    )
    db_session.flush()

    dashboard_routes._synchronize_management_carryforward_applications(
        db_session,
        applications=[],
        invoice_id_by_statement={},
        scope_store_ids={"g2-store-1"},
        scope_through_month="2026-09",
    )
    db_session.flush()
    assert db_session.get(
        ManagementCarryforwardApplication,
        db_session.scalar(
            select(ManagementCarryforwardApplication.id).where(
                ManagementCarryforwardApplication.application_id
                == "stale-empty-scope"
            )
        ),
    ).is_current is False
    assert db_session.scalar(
        select(ManagementCarryforwardApplication.is_current).where(
            ManagementCarryforwardApplication.application_id == "outside-scope"
        )
    ) is True

    stale_disjoint = ManagementCarryforwardApplication(
        application_id="stale-disjoint-scope",
        store_id="g2-store-1",
        source_statement_id="disjoint-old-negative",
        source_statement_month="2026-08",
        target_statement_id="disjoint-old-positive",
        target_statement_month="2026-09",
        applied_amount_cent=100,
        version_no=1,
        is_current=True,
        projection_sha256="c" * 64,
    )
    db_session.add(stale_disjoint)
    db_session.flush()
    materialized = dashboard_routes._synchronize_management_carryforward_applications(
        db_session,
        applications=[
            {
                "store_id": "g2-store-1",
                "source_statement_id": "new-negative",
                "source_statement_month": "2026-08",
                "target_statement_id": "new-positive",
                "target_statement_month": "2026-09",
                "invoice_id": None,
                "applied_amount_cent": 75,
            }
        ],
        invoice_id_by_statement={},
        scope_store_ids={"g2-store-1"},
        scope_through_month="2026-09",
    )
    db_session.flush()
    assert stale_disjoint.is_current is False
    assert len(materialized) == 1
    assert materialized[0].is_current is True


def test_management_carryforward_sync_before_cutoff_keeps_later_application_current(
    db_session: Session,
) -> None:
    earlier = ManagementCarryforwardApplication(
        application_id="carryforward-earlier",
        store_id="g2-store-1",
        source_statement_id="negative-aug",
        source_statement_month="2026-08",
        target_statement_id="positive-sep",
        target_statement_month="2026-09",
        applied_amount_cent=100,
        version_no=1,
        is_current=True,
        projection_sha256="d" * 64,
    )
    later = ManagementCarryforwardApplication(
        application_id="carryforward-later",
        store_id="g2-store-1",
        source_statement_id="negative-aug",
        source_statement_month="2026-08",
        target_statement_id="positive-dec",
        target_statement_month="2026-12",
        applied_amount_cent=200,
        version_no=1,
        is_current=True,
        projection_sha256="e" * 64,
    )
    db_session.add_all([earlier, later])
    db_session.flush()

    dashboard_routes._synchronize_management_carryforward_applications(
        db_session,
        applications=[],
        invoice_id_by_statement={},
        scope_store_ids={"g2-store-1"},
        scope_through_month="2026-09",
    )
    db_session.flush()

    assert earlier.is_current is False
    assert later.is_current is True
    assert db_session.scalar(
        select(func.sum(ManagementCarryforwardApplication.applied_amount_cent)).where(
            ManagementCarryforwardApplication.is_current.is_(True),
            ManagementCarryforwardApplication.store_id == "g2-store-1",
        )
    ) == 200
