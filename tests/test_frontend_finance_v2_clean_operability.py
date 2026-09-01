import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_finance_imports_uses_independent_server_pagination_with_shared_controls() -> None:
    page = source("apps/web/src/pages/FinanceImportsPage.tsx")
    api = source("apps/api/dy_api/routes/dashboard.py")
    list_contract = api.split('@router.get("/admin/finance-imports")', 1)[1].split(
        '@router.get("/admin/finance-imports/{batch_id}/error-file")', 1
    )[0]
    detail_contract = api.split('@router.get("/admin/finance-imports/{batch_id}")', 1)[1].split(
        '@router.post("/admin/finance-imports/{batch_id}/commits")', 1
    )[0]

    assert 'import { TablePagination } from "../components/TablePagination";' in page
    assert "page, pageSize" in page
    assert "errorPage, errorPageSize, reversalPage, reversalPageSize" in page
    assert "setPage(1)" in page
    assert "setErrorPage(1)" in page
    assert "setReversalPage(1)" in page
    assert page.count("<TablePagination") >= 3
    assert "page_size: int = Query(default=20, ge=1, le=50" in list_contract
    assert "error_page_size: int = Query(" in detail_contract
    assert "reversal_page_size: int = Query(" in detail_contract
    assert detail_contract.count("le=50") == 2
    assert page.count("pageSizeOptions={[20, 50]}") == 3
    assert "pageSizeOptions={[20, 50, 100]}" not in page


def test_finance_import_detail_is_guarded_by_selected_batch_identity() -> None:
    page = source("apps/web/src/pages/FinanceImportsPage.tsx")

    assert "detailResource.data?.data?.batchId === selectedBatchId" in page
    assert "const clearSelectedBatch" in page
    assert page.count("clearSelectedBatch();") >= 3
    assert "onClick={clearSelectedBatch}" in page


def test_finance_order_details_uses_shared_pagination_and_resets_after_size_change() -> None:
    page = source("apps/web/src/pages/FinanceOrderDetailsPage.tsx")

    assert 'import { TablePagination } from "../components/TablePagination";' in page
    assert "onPageSizeChange" in page
    assert "page: 1, pageSize: nextPageSize" in page
    assert "上一页" not in page
    assert "下一页" not in page


def test_finance_refreshing_state_hides_stale_rows_and_blocks_pagination() -> None:
    imports = source("apps/web/src/pages/FinanceImportsPage.tsx")
    order_details = source("apps/web/src/pages/FinanceOrderDetailsPage.tsx")
    data_table = source("apps/web/src/components/DataTable.tsx")

    assert "const listBusy = listResource.loading || listResource.refreshing;" in imports
    assert 'state={listBusy ? "loading" : listResource.error ? "error" : "ready"}' in imports
    assert "loading={listBusy}" in imports
    assert "const resourceBusy = resource.loading || resource.refreshing;" in order_details
    assert 'state={resourceBusy ? "loading" : resource.error ? "error" : "ready"}' in order_details
    assert "loading={resourceBusy}" in order_details
    assert 'const shouldRenderStatus = rows.length === 0 || state !== "ready";' in data_table
    assert data_table.count("shouldRenderStatus ? (") >= 2


def test_finance_enum_tokens_are_presented_by_shared_labels() -> None:
    order_details = source("apps/web/src/pages/FinanceOrderDetailsPage.tsx")
    stores = source("apps/web/src/pages/FinanceStoresPage.tsx")
    imports = source("apps/web/src/pages/FinanceImportsPage.tsx")
    labels = source("apps/web/src/utils/userFacingLabels.ts")

    for presenter in (
        "displayFinanceOrderStatus",
        "displayFinanceOrderRowType",
        "displayFinanceInvoiceStatus",
        "displayFinanceSettlementStatus",
        "displayFinanceAdjustmentType",
        "displayFinanceSaleChannel",
        "displaySapSuggestionStatus",
        "displayFinanceSapStatus",
        "displayFinanceImportReversalEffect",
    ):
        assert f"export function {presenter}" in labels
    assert "displayFinanceOrderStatus(row.orderStatus)" in order_details
    assert "displayFinanceSapStatus(row.sapStatus)" in stores
    assert "displayFinanceImportReversalEffect(row.effectType)" in imports


def test_finance_import_panel_uses_shared_form_primitives_for_every_input() -> None:
    panel = source("apps/web/src/components/FinanceImportActionPanel.tsx")

    assert 'from "./FormControls"' in panel
    assert "<TextField" in panel
    assert panel.count("<TextField") >= 3
    assert '<input disabled value={month}' not in panel
    assert 'type="file"' in panel


def test_dispute_adjustment_uses_one_exact_cent_value_for_ui_handler_and_payload() -> None:
    page = source("apps/web/src/pages/FinanceDisputesPage.tsx")

    assert 'import { parseYuanToCent } from "../utils/money";' in page
    assert "const adjustmentAmountCent = parseYuanToCent(adjustmentYuan);" in page
    assert "adjustmentAmountCent === null" in page
    assert "let validatedAdjustmentAmountCent: number | undefined;" in page
    assert "validatedAdjustmentAmountCent = adjustmentAmountCent;" in page
    assert "adjustmentAmountCent: validatedAdjustmentAmountCent" in page
    assert "Math.round(Number(adjustmentYuan) * 100)" not in page


def test_parse_yuan_to_cent_executes_exact_decimal_contract() -> None:
    script = """
      import { parseYuanToCent } from './apps/web/src/utils/money.ts';
      const values = ['1', '1.2', '1.05', '-1.05', '0.01', '-0.01', '90071992547409.91', '90071992547409.92', '-90071992547409.91', '-90071992547409.92', '', ' ', '0', '0.00', '-0.00', '0.001', '1.005', '1e2', '+1', '.5', '-.5', '1.', 'Infinity'];
      console.log(JSON.stringify(values.map((value) => [value, parseYuanToCent(value)])));
    """
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    parsed = dict(json.loads(result.stdout))

    assert parsed == {
        "1": 100,
        "1.2": 120,
        "1.05": 105,
        "-1.05": -105,
        "0.01": 1,
        "-0.01": -1,
        "90071992547409.91": 9007199254740991,
        "90071992547409.92": None,
        "-90071992547409.91": -9007199254740991,
        "-90071992547409.92": None,
        "": None,
        " ": None,
        "0": None,
        "0.00": None,
        "-0.00": None,
        "0.001": None,
        "1.005": None,
        "1e2": None,
        "+1": None,
        ".5": None,
        "-.5": None,
        "1.": None,
        "Infinity": None,
    }


def test_finance_copy_describes_available_writes_truthfully() -> None:
    imports = source("apps/web/src/pages/FinanceImportsPage.tsx")
    fee = source("apps/web/src/pages/FinanceFeePage.tsx")

    assert "本页只读" not in imports
    assert "金额只读" not in fee
    assert "批次发起撤销" in imports
    assert "金额可编辑" in fee
