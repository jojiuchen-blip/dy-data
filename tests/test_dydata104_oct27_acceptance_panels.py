"""Every actual finance import panel downloads its real validation errors."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect

from test_finance_export_browser import ERROR_FILE_FIELDS
from test_visual_smoke import (
    browser,  # noqa: F401
    live_admin_fastapi_base_url,  # noqa: F401
    vite_live_admin_api_base_url,  # noqa: F401
)

# Error batches belong to this module and cannot affect other browser modules.
live_admin_fastapi_base_url = pytest.fixture(scope="module")(live_admin_fastapi_base_url.__wrapped__)
vite_live_admin_api_base_url = pytest.fixture(scope="module")(vite_live_admin_api_base_url.__wrapped__)


@pytest.mark.parametrize("kind,path,open_label,header", [
    ("BASIC_INFO", "/finance/stores", "导入门店基础信息",
     "storeId,storeName,sapCode,importedAt"),
    ("SAP_CONFIRMATION", "/finance/stores?tab=sap", "导入最终确认 SAP 编码",
     "storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,factoryConfirmationResult,confirmedAt"),
    ("PROMOTION_FACTORY_RESULT", "/finance/promotion", "导入推广服务费厂家信息",
     "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent"),
    ("MANAGEMENT_FACTORY_RESULT", "/finance/management", "导入管理服务费厂家信息",
     "storeId,statementMonth,storeName,invoiceNumber,invoiceDate,deductionDate,deductionAmountCent"),
])
def test_all_four_panel_error_downloads_real_rows(
    browser: Browser, vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str, tmp_path: Path,
    kind: str, path: str, open_label: str, header: str,
) -> None:
    """Upload invalid synthetic rows; save, parse and match the full error file."""
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    try:
        separator = "&" if "?" in path else "?"
        page.goto(f"{vite_live_admin_api_base_url}{path}{separator}month=2026-08")
        page.get_by_role("button", name=open_label, exact=True).click()
        page.get_by_label("文件", exact=True).set_input_files({
            "name": f"{kind}-synthetic-errors.csv", "mimeType": "text/csv",
            "buffer": (header + "\nmissing-invalid-row\n").encode("utf-8"),
        })
        with page.expect_response(lambda response: response.request.method == "POST"
                                  and response.url.endswith("/admin/finance-imports")) as upload:
            page.get_by_role("button", name="上传并预览", exact=True).click()
        assert upload.value.status == 200, upload.value.text()
        batch = upload.value.json()["data"]
        assert batch["scenario"] == "BATCH_VALIDATION_FAILED"
        assert batch["errorRows"] == 1
        expect(page.get_by_role("button", name="确认提交", exact=True)).to_be_disabled()
        detail = context.request.get(
            f"{live_admin_fastapi_base_url}/api/v1/admin/finance-imports/{batch['batchId']}",
        )
        assert detail.status == 200, detail.text()
        errors = detail.json()["data"]["errors"]
        assert errors["total"] >= 1
        with page.expect_download() as downloaded:
            page.get_by_role("button", name="下载全部错误", exact=True).click()
        file_path = tmp_path / f"{kind}-errors.csv"
        downloaded.value.save_as(file_path)
        raw = file_path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        assert rows[0] == ERROR_FILE_FIELDS
        assert len(rows) - 1 == errors["total"]
        assert all(row[0] == "2" and row[4] and row[5] for row in rows[1:])
        expect(page.get_by_role("status").filter(has_text="已下载")).to_be_visible()
        page.screenshot(path=str(tmp_path / f"{kind}-errors.png"), full_page=True)
    finally:
        context.close()
