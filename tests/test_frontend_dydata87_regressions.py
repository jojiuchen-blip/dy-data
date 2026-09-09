from pathlib import Path
import subprocess

SRC = Path(__file__).resolve().parents[1] / "apps/web/src"


def test_new_sku_rules_default_to_equal_rates_but_allow_explicit_independent_rates():
    page = (SRC / "pages/AdminSkuRulesPage.tsx").read_text(encoding="utf-8")
    assert 'const [sameRate, setSameRate] = useState(true)' in page
    assert 'const [promotionRate, setPromotionRate] = useState("8")' in page
    assert 'const [managementRate, setManagementRate] = useState("8")' in page
    assert 'setSameRate(event.target.checked)' in page
    assert 'disabled={sameRate}' in page


def test_invoice_conflict_invalidates_selection_and_reloads_before_retry():
    page = (SRC / "pages/StoreInvoicePage.tsx").read_text(encoding="utf-8")
    assert 'error instanceof ApiRequestError && error.status === 409' in page
    catch = page.split('} catch (error) {')[-1]
    assert 'setSelectedStatements([])' in catch
    assert 'statementResource.reload()' in catch
    assert 'invoiceResource.reload()' in catch


def test_invoice_submission_uses_synchronous_inflight_guard():
    page = (SRC / "pages/StoreInvoicePage.tsx").read_text(encoding="utf-8")
    handler = page.split('const handleSubmit = async')[1].split('return (')[0]
    assert 'if (submitInFlight.current) return' in handler
    assert 'submitInFlight.current = true' in handler
    assert 'submitInFlight.current = false' in handler


def test_store_dispute_can_submit_without_attachment_gate():
    page = (SRC / "pages/StoreSettlementPage.tsx").read_text(encoding="utf-8")
    assert 'await submitStoreBillingDispute(' in page
    assert 'evidence: []' in page
    assert 'readVersion: statement.versionNo' in page
    assert 'type="file"' not in page
    assert 'disputeInFlight.current' in page


def test_invoice_status_preserves_authorized_store_and_month_deep_link():
    page = (SRC / "pages/StoreInvoiceStatusPage.tsx").read_text(encoding="utf-8")
    assert 'searchParams.get("storeId")' in page
    assert 'currentUser.store_ids.includes(requestedStoreId)' in page
    assert 'searchParams.get("month")' in page


def test_store_cumulative_uses_published_computation_not_formal_billing():
    page = (SRC / "pages/StoreSettlementPage.tsx").read_text(encoding="utf-8")
    assert 'const cumulativeMetrics = view?.computedCumulative' in page
    assert 'cumulativeMetrics?.promotionNetFeeCent' in page
    assert 'cumulativeMetrics?.managementNetFeeCent' in page
    assert 'cumulativeBillingResource' not in page


def test_pending_request_key_reuses_uncertain_payload_and_resets_after_success():
    utility = SRC / "utils/pendingRequestKey.ts"
    assert utility.exists(), "missing in-memory retry identity"
    script = """
const fs = require('fs');
const ts = require('./apps/web/node_modules/typescript');
const assert = require('node:assert/strict');
const code = ts.transpileModule(fs.readFileSync(process.argv[1], 'utf8'), {
 compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
}).outputText;
const moduleObj = {exports: {}};
new Function('exports', 'module', code)(moduleObj.exports, moduleObj);
let sequence = 0;
const pending = moduleObj.exports.createPendingRequestKey(() => String(++sequence));
const a = pending.forRequest('statement-1', {readVersion: 1, amount: 10});
assert.equal(pending.forRequest('statement-1', {readVersion: 1, amount: 10}), a);
assert.notEqual(pending.forRequest('statement-1', {readVersion: 2, amount: 10}), a);
const b = pending.forRequest('statement-2', {readVersion: 2, amount: 10});
assert.equal(sequence, 3);
assert.notEqual(pending.forRequest('statement-2', {readVersion: 2, amount: 11}), b);
pending.clear();
pending.forRequest('statement-2', {readVersion: 2, amount: 11});
assert.equal(sequence, 5);
// The server commits, but the first response is lost. Retry must replay one fact.
const committed = new Map();
const payload = {readVersion: 3, description: 'synthetic dispute'};
const firstKey = pending.forRequest('statement-3', payload);
committed.set(firstKey, {id: 'one-dispute'});
const retryKey = pending.forRequest('statement-3', {...payload});
if (!committed.has(retryKey)) committed.set(retryKey, {id: 'duplicate'});
assert.equal(committed.size, 1);
assert.equal(committed.get(retryKey).id, 'one-dispute');
"""
    subprocess.run(["node", "-e", script, str(utility)], cwd=SRC.parents[2], check=True)


def test_financial_forms_keep_retry_keys_until_success():
    settlement = (SRC / "pages/StoreSettlementPage.tsx").read_text(encoding="utf-8")
    invoice = (SRC / "pages/StoreInvoicePage.tsx").read_text(encoding="utf-8")
    for page, names in ((settlement, ("confirmationRequest", "disputeRequest")),
                        (invoice, ("invoiceRequest",))):
        for name in names:
            assert f'{name}.current.forRequest(' in page
            assert f'{name}.current.clear()' in page
        assert 'crypto.randomUUID()' not in page
