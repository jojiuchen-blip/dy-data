from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_store_settlement_confirmation_uses_the_versioned_idempotent_contract() -> None:
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")

    assert "export interface StoreBillingConfirmationPayload" in types
    assert "export interface StoreBillingConfirmationResult" in types
    assert "export function confirmStoreBillingStatement" in client

    confirmation_client = client.split("export function confirmStoreBillingStatement", 1)[1]
    assert "sendJson<StoreBillingConfirmationResult>" in confirmation_client
    assert "`/store-settlements/${encodeURIComponent(statementId)}/confirmations`" in confirmation_client
    assert 'headers: { "Idempotency-Key": idempotencyKey }' in confirmation_client


def test_store_settlement_page_loads_and_refreshes_real_direction_confirmations() -> None:
    page = read_source("pages/StoreSettlementPage.tsx")

    assert "fetchStoreBillingStatements" in page
    assert 'metricScope: "MONTH"' in page
    assert "const statement = billingResource.data?.data.list[0]" in page
    assert "promotionConfirmation" in page
    assert "managementConfirmation" in page
    assert "confirmStoreBillingStatement" in page
    assert "feeDirection: direction" in page
    assert "confirmedAmountCent: amount" in page
    assert "readVersion: statement.versionNo" in page
    assert "Math.max(statement.managementAmountCent, 0)" in page
    assert "crypto.randomUUID()" in page
    assert "await billingResource.reload()" in page
    assert "pendingDirection === direction" in page
    assert 'useState<"idle" | "success" | "error">("idle")' in page
    assert 'role={confirmationState === "error" ? "alert" : "status"}' in page


def test_store_settlement_page_keeps_dispute_submission_unavailable_pending_dydata_82() -> None:
    page = read_source("pages/StoreSettlementPage.tsx")

    assert "DYDATA-82" in page
    assert "证据上传能力尚未接入" in page
    assert "disabled" in page
    assert "window.confirm" not in page
    assert "window.alert" not in page
