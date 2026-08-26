from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_finance_imports_uses_independent_server_pagination_with_shared_controls() -> None:
    page = source("apps/web/src/pages/FinanceImportsPage.tsx")

    assert 'import { TablePagination } from "../components/TablePagination";' in page
    assert "page, pageSize" in page
    assert "errorPage, errorPageSize, reversalPage, reversalPageSize" in page
    assert "setPage(1)" in page
    assert "setErrorPage(1)" in page
    assert "setReversalPage(1)" in page
    assert page.count("<TablePagination") >= 3


def test_finance_order_details_uses_shared_pagination_and_resets_after_size_change() -> None:
    page = source("apps/web/src/pages/FinanceOrderDetailsPage.tsx")

    assert 'import { TablePagination } from "../components/TablePagination";' in page
    assert "onPageSizeChange" in page
    assert "page: 1, pageSize: nextPageSize" in page
    assert "上一页" not in page
    assert "下一页" not in page


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
        "displayFinanceImportReversalEffect",
    ):
        assert f"export function {presenter}" in labels
    assert "displayFinanceOrderStatus(row.orderStatus)" in order_details
    assert "displaySapSuggestionStatus(row.status)" in stores
    assert "displayFinanceImportReversalEffect(row.effectType)" in imports


def test_finance_import_panel_uses_shared_form_primitives_for_every_input() -> None:
    panel = source("apps/web/src/components/FinanceImportActionPanel.tsx")

    assert 'from "./FormControls"' in panel
    assert "<TextField" in panel
    assert panel.count("<TextField") >= 3
    assert '<input disabled value={month}' not in panel
    assert 'type="file"' in panel


def test_dispute_adjustment_requires_finite_nonzero_value_in_ui_and_handler() -> None:
    page = source("apps/web/src/pages/FinanceDisputesPage.tsx")

    assert "function isValidAdjustmentYuan" in page
    assert "Number.isFinite(amount) && amount !== 0" in page
    assert "if (targetStatus === \"ACCEPTED_WITH_ADJUSTMENT\" && !isValidAdjustmentYuan(adjustmentYuan))" in page
    assert "const adjustmentIsValid" in page
    assert "!adjustmentIsValid" in page


def test_finance_copy_describes_available_writes_truthfully() -> None:
    imports = source("apps/web/src/pages/FinanceImportsPage.tsx")
    fee = source("apps/web/src/pages/FinanceFeePage.tsx")

    assert "本页只读" not in imports
    assert "金额只读" not in fee
    assert "批次发起撤销" in imports
    assert "金额可编辑" in fee
