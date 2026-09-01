from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_store_settlement_confirmation_uses_the_versioned_idempotent_contract() -> None:
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")

    assert "export interface StoreBillingConfirmationPayload" in types
    assert "export interface StoreBillingConfirmationResult" in types
    assert "promotionConfirmableAmountCent: number" in types
    assert "managementConfirmableAmountCent: number" in types
    assert "export function confirmStoreBillingStatement" in client

    confirmation_client = client.split("export function confirmStoreBillingStatement", 1)[1]
    assert "sendJson<StoreBillingConfirmationResult>" in confirmation_client
    assert "`/store-settlements/${encodeURIComponent(statementId)}/confirmations`" in confirmation_client
    assert 'headers: { "Idempotency-Key": idempotencyKey }' in confirmation_client


def test_store_settlement_page_loads_and_refreshes_real_direction_confirmations() -> None:
    page = read_source("pages/StoreSettlementPage.tsx")

    assert "fetchStoreBillingStatements" in page
    assert 'metricScope: "MONTH"' in page
    assert "const statementCandidate = billingResource.data?.data.list[0]" in page
    assert "statementCandidate.storeId === activeStoreId" in page
    assert "statementCandidate.month === activeMonth" in page
    assert "!billingResource.loading" in page
    assert "!billingResource.refreshing" in page
    assert "!billingError" in page
    assert "statementCandidateKey !== invalidatedStatementKey" in page
    assert "promotionConfirmation" in page
    assert "managementConfirmation" in page
    assert "confirmStoreBillingStatement" in page
    assert "feeDirection: direction" in page
    assert "confirmedAmountCent: amount" in page
    assert "readVersion: statement.versionNo" in page
    assert "statement.promotionConfirmableAmountCent" in page
    assert "statement.managementConfirmableAmountCent" in page
    assert "statement.promotionAmountCent" not in page
    assert "statement.managementAmountCent" not in page
    assert "crypto.randomUUID()" in page
    assert "await billingResource.reload()" in page
    assert "error instanceof ApiRequestError && error.status === 409" in page
    assert "setInvalidatedStatementKey" in page
    assert "setConfirmationDirection(null)" in page
    assert "pendingDirection === direction" in page
    assert 'useState<"idle" | "success" | "error">("idle")' in page
    assert 'role={confirmationState === "error" ? "alert" : "status"}' in page


def test_store_settlement_page_exposes_collapsed_dispute_intake_without_fake_submission() -> None:
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")
    page = read_source("pages/StoreSettlementPage.tsx")

    assert "DYDATA-82" not in page
    assert "fetchStoreBillingDisputes" in page
    assert "submitStoreBillingDispute" not in page
    assert "账单异议" in page
    assert "发起账单异议" in page
    assert "异议类型" in page
    assert "RATE_ERROR" in page
    assert "DATA_MISSING" in page
    assert "AMOUNT_ERROR" in page
    assert "OTHER" in page
    assert "StoreBillingDisputePayload" in types
    assert "/disputes" in client
    assert 'className="store-finance-dispute-entry"' in page
    assert 'open={disputeOpen}' in page
    assert 'form="store-dispute-form"' not in page
    assert "受控证明对象键" not in page
    assert 'type="file"' in page
    assert "证明材料受控上传尚未开放，当前不能提交异议。" in page
    assert "disabled" in page
    assert "window.confirm" not in page
    assert "window.alert" not in page
