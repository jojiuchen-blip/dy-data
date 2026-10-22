"""Synthetic real API/browser pagination and complete-download acceptance.

Browser plugin not available; reuse the repository's Playwright fixtures.
No successful response is intercepted and no production database is used.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest
from playwright.sync_api import expect
from sqlalchemy import delete, select

from test_visual_smoke import (
    LIVE_ADMIN_SESSION_FACTORIES,
    browser,
    live_admin_fastapi_base_url,
    vite_live_admin_api_base_url,
)
from dy_api.models import (
    DimStore, SapSuggestion, SettlementDispute, SettlementStatement,
    StoreFinanceProfile,
)
from publication_fixture_helpers import publish_fixture

PREFIX = "B105-"
MONTH = "2026-09"


@pytest.fixture(scope="module")
def finance_scale(live_admin_fastapi_base_url):
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    with factory() as session:
        for index in range(61):
            key = f"{PREFIX}{index:03d}"
            session.add(DimStore(store_id=key, store_name=f"验收分页门店{index:03d}", is_active=True))
            session.add(StoreFinanceProfile(
                profile_id=key, store_id=key, profile_type=1, source_type=3,
                version_no=1, is_current=True, store_name_snapshot=f"验收分页门店{index:03d}",
                sap_code=f"SAP{index:07d}", created_at=now, updated_at=now,
            ))
            session.add(SapSuggestion(
                suggestion_id=key, store_id=key, version_no=1, is_current=True,
                suggested_sap_code=f"OLD{index:07d}", suggestion_status=1,
                suggestion_note="合成SAP差异",
                submitted_by="synthetic", submitted_at=now,
            ))
            session.add(SettlementStatement(
                statement_id=key, store_id=key, statement_month=MONTH, version_no=1,
                is_current=True, statement_status=1,
                promotion_original_fee_cent=10001 + index,
                promotion_adjustment_fee_cent=0, promotion_net_fee_cent=10001 + index,
                management_original_fee_cent=20001 + index,
                management_adjustment_fee_cent=0, management_net_fee_cent=20001 + index,
                store_name_snapshot=f"验收分页门店{index:03d}",
                sap_code_snapshot=f"SAP{index:07d}", store_snapshot_status="LIVE_CAPTURED",
                created_at=now,
            ))
            session.add(SettlementDispute(
                dispute_id=key, statement_id=key, store_id=key, statement_month=MONTH,
                fee_direction=1, dispute_type=3, status=1, disputed_amount_cent=101 + index,
                description="合成分页验收", contact_name="合成联系人",
                contact_phone_ciphertext="synthetic", evidence_json=[],
                submitted_by="synthetic", submitted_at=now,
            ))
        session.commit()
        publication = publish_fixture(session, "finance")
    yield factory, publication
    with factory() as session:
        for model, field in (
            (SettlementDispute, SettlementDispute.dispute_id),
            (SettlementStatement, SettlementStatement.statement_id),
            (SapSuggestion, SapSuggestion.suggestion_id),
            (StoreFinanceProfile, StoreFinanceProfile.profile_id),
            (DimStore, DimStore.store_id),
        ):
            session.execute(delete(model).where(field.startswith(PREFIX)))
        session.commit()
        publish_fixture(session, "finance")


CASES = [
    ("promotion", "/finance/promotion", "推广服务费", "验收分页门店", "/admin/finance/invoices", "导出当前筛选结果"),
    ("management", "/finance/management", "管理服务费", "验收分页门店", "/admin/finance/invoices", "导出当前筛选结果"),
    ("stores", "/finance/stores", "门店基础信息", PREFIX, "/admin/finance/stores", "导出门店基础信息"),
    ("sap", "/finance/stores", "门店基础信息", PREFIX, "/admin/finance/stores", "导出 SAP 编码差异清单"),
    ("disputes", "/finance/disputes", "账单异议", "", "/admin/disputes", "导出账单异议"),
]


@pytest.mark.parametrize("name,path,title,query,endpoint,export_label", CASES)
def test_dydata105_real_pagination_and_all_rows_download(
    browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url,
    finance_scale, tmp_path, name, path, title, query, endpoint, export_label,
):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        suffix = f"?month={MONTH}&q={query}" + ("&tab=sap" if name == "sap" else "")
        page.goto(vite_live_admin_api_base_url + path + suffix)
        expect(page.get_by_role("heading", name=title, exact=True, level=1)).to_be_visible()
        pagination = page.get_by_role("navigation", name="表格分页")
        expect(pagination).to_contain_text("共 61 条", timeout=20000)
        expect(pagination).to_contain_text("第 1 / 2 页")
        pagination.get_by_role("button", name="下一页", exact=True).click()
        expect(pagination).to_contain_text("显示 51-61", timeout=20000)
        params = {"month": MONTH, "page": 2, "pageSize": 50}
        if name != "disputes":
            params.update(q=query, feeDirection="MANAGEMENT" if name == "management" else "PROMOTION", metricScope="MONTH")
        if name == "sap":
            params["sapDiscrepanciesOnly"] = "true"
        listed = context.request.get(live_admin_fastapi_base_url + "/api/v1" + endpoint, params=params)
        assert listed.status == 200, listed.text()
        data = listed.json()["data"]
        assert data["total"] == 61 and len(data["list"]) == 11
        with page.expect_download() as download_info:
            page.get_by_role("button", name=export_label, exact=True).click()
        download = download_info.value
        content = Path(download.path()).read_bytes()
        assert content.startswith(b"\xef\xbb\xbf")
        records = list(csv.DictReader(StringIO(content.decode("utf-8-sig"))))
        assert len(records) == 61
        key = "dispute_id" if name == "disputes" else "store_id"
        assert {row[key] for row in records} == {f"{PREFIX}{index:03d}" for index in range(61)}
        if name in {"promotion", "management"}:
            base = 20001 if name == "management" else 10001
            assert sum(int(row["statement_amount_cent"]) for row in records) == sum(base + index for index in range(61))
        if name == "disputes":
            assert sum(int(row["disputed_amount_cent"]) for row in records) == sum(101 + index for index in range(61))
        pagination.get_by_label("每页条数", exact=True).click()
        page.get_by_role("option", name="每页 20 条", exact=True).click()
        expect(pagination).to_contain_text("第 1 / 4 页", timeout=20000)
        pagination.get_by_label("输入页码", exact=True).fill("4")
        pagination.get_by_role("button", name="跳转", exact=True).click()
        expect(pagination).to_contain_text("显示 61-61", timeout=20000)
        # Each live filter must reset an old last page immediately.
        if name in {"promotion", "management"}:
            page.get_by_label("搜索", exact=True).fill("验收分页门店060")
        elif name in {"stores", "sap"}:
            page.get_by_label("搜索门店", exact=True).fill(f"{PREFIX}060")
        else:
            page.get_by_label("门店 ID", exact=True).fill(f"{PREFIX}060")
        expect(pagination).to_contain_text("显示 1-1 / 共 1 条", timeout=20000)
        if name in {"promotion", "management"}:
            page.get_by_role("button", name="重置筛选", exact=True).click()
            expect(page.get_by_label("搜索", exact=True)).to_have_value("")
            # Restore the frozen fixture month independently of the current calendar.
            page.get_by_label("筛选账期", exact=True).fill(MONTH)
            expect(pagination).to_contain_text("共 61 条", timeout=20000)
            pagination.get_by_role("button", name="下一页", exact=True).click()
            if name == "management":
                page.get_by_role("button", name="查看历史版本", exact=True).click()
                expect(pagination).to_contain_text("第 1 / 4 页", timeout=20000)
                page.get_by_role("button", name="仅看当前版本", exact=True).click()
        elif name in {"stores", "sap"}:
            page.get_by_label("搜索门店", exact=True).fill(PREFIX)
            expect(pagination).to_contain_text("共 61 条", timeout=20000)
            pagination.get_by_role("button", name="下一页", exact=True).click()
            page.get_by_role("tab", name="基础信息" if name == "sap" else "SAP异议处理", exact=True).click()
            expect(pagination).to_contain_text("第 1 / 4 页", timeout=20000)
        else:
            page.get_by_label("门店 ID", exact=True).fill("")
            expect(pagination).to_contain_text("共 61 条", timeout=20000)
            pagination.get_by_role("button", name="下一页", exact=True).click()
            page.get_by_label("处理状态", exact=True).click()
            page.get_by_role("option", name="不成立", exact=True).click()
            expect(pagination).to_contain_text("共 0 条", timeout=20000)
        assert errors == []
        page.screenshot(path=tmp_path / f"{name}-filtered.png", full_page=True)
    finally:
        context.close()
