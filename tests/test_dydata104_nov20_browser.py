"""Real HTTP, React and CSV acceptance for the November 20 monthly requirements.

Only the isolated publication's input facts and the authenticated test identity
are synthetic. Successful page reads and downloads use the application routes.
The existing optional PostgreSQL fixture gives CI a disposable schema.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect
from sqlalchemy import insert, select, update

import test_visual_smoke as live_fixture
from publication_fixture_helpers import publish_fixture
from test_finance_download_localization_browser import localized_api, localized_web  # noqa: F401
from test_visual_smoke import browser  # noqa: F401
from apps.api.dy_api.dashboard_publications import finance
from apps.api.dy_api.models import DimSkuProductRule, SettlementStatement


MONTH = "2026-10"
LONG_COUPON_ID = "000012345678901234567890"
LONG_ORDER_ID = "991234567890123456789012"


def trial_facts(publication_id: str) -> list[dict]:
    """Declare known, unassigned and excluded records in both fee directions."""
    records = []
    for direction, first_amount, second_amount in ((1, 12345, 700), (2, 5432, 800)):
        for identity, store_id, store_name, status, amount, reason in (
            (LONG_COUPON_ID, "store-1", "深圳临港认证服务店", "CALCULATED", first_amount, None),
            ("trial-second-store", "store-2", "杭州滨江直营服务店", "CALCULATED", second_amount, None),
            ("trial-known-pending", "store-1", "深圳临港认证服务店", "PENDING", None, "历史商品规格资料待补"),
            ("trial-unassigned", None, None, "PENDING", None, "销售门店归属待核验"),
            ("trial-excluded", "store-1", "深圳临港认证服务店", "EXCLUDED", None, "销售账号明确不符合资格"),
        ):
            records.append({
                "publication_id": publication_id,
                "row_id": f"nov20-{direction}-{identity}",
                "month": MONTH,
                "fee_direction": direction,
                "coupon_id": identity,
                "order_id": LONG_ORDER_ID if identity == LONG_COUPON_ID else f"order-{identity}",
                "store_id": store_id,
                "store_name": store_name,
                "product_type": "养车服务" if status == "CALCULATED" else "unknown",
                "sku_id": "SKU-NOV20" if status == "CALCULATED" else None,
                "fee_amount_cent": amount,
                "base_amount_cent": amount * 10 if amount is not None else None,
                "fee_rate": "0.100000" if amount is not None else None,
                "rule_version": "nov20-frozen-rule" if amount is not None else None,
                "record_status": status,
                "reason_code": f"nov20-{status.lower()}" if reason else None,
                "reason": reason,
                "search_text": " ".join(str(value or "") for value in (identity, store_id, store_name)),
            })
    return records


@pytest.fixture(scope="module")
def nov20_api(localized_api):
    from apps.api.dy_api.dashboard_publications import fee_trial

    factory = live_fixture.LIVE_ADMIN_SESSION_FACTORIES[localized_api]

    def build_trial(session, publication_id, cutoff):
        stats = finance.build_settlement(session, publication_id, cutoff)
        readiness_row = (finance.dimensions.c.publication_id == publication_id) & (
            finance.dimensions.c.kind == "period_readiness"
        )
        readiness = session.scalar(select(finance.dimensions.c.value).where(readiness_row))
        readiness["months"][MONTH] = {
            "ready": False, "success_days": 31, "total_days": 31,
            "revision": "nov20-synthetic-full-source-with-pending-ownership",
        }
        session.execute(update(finance.dimensions).where(readiness_row).values(value=readiness))
        session.execute(insert(fee_trial.rows), trial_facts(publication_id))
        session.execute(insert(finance.dimensions).values(
            publication_id=publication_id, kind="fee_trial", key=MONTH,
            value={
                "schema_version": 1, "source_success_days": 31, "source_total_days": 31,
                "scope_unresolved": True, "source_input_sha256": "nov20-synthetic-source",
            },
        ))
        return stats

    with factory() as session:
        assert not session.scalars(select(SettlementStatement).where(
            SettlementStatement.statement_month == MONTH,
        )).all()
        session.add(DimSkuProductRule(
            sku_id="SKU-NOV20", sku_name="隔离试算规格", product_scope="精诚养车",
            product_type="养车服务",
        ))
        publication = publish_fixture(session, "settlement", builder=build_trial)
    yield localized_api, publication.id


@pytest.fixture(scope="module")
def nov20_web(nov20_api):
    yield from live_fixture.vite_live_admin_api_base_url.__wrapped__(nov20_api[0])


def read_csv(download) -> tuple[bytes, list[dict[str, str]]]:
    raw = Path(download.path()).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    return raw, list(csv.DictReader(StringIO(raw.decode("utf-8-sig"))))


def amount_field(row: dict[str, str], label: str) -> str:
    matches = [key for key in row if key == label or key == f"{label}（元）"]
    assert len(matches) == 1, list(row)
    return matches[0]


def evidence_directory(tmp_path: Path) -> Path:
    directory = Path(os.environ.get("DYDATA_BROWSER_EVIDENCE_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.mark.parametrize("direction,total_cent", [("PROMOTION", 13045), ("MANAGEMENT", 6232)])
@pytest.mark.parametrize("width", [390, 1440])
def test_internal_trial_real_page_and_chinese_download_with_zero_formal_bills(
    browser, nov20_api, nov20_web, tmp_path, direction, total_cent, width,
):
    context = browser.new_context(viewport={"width": width, "height": 1000})
    page = context.new_page()
    writes, errors = [], []
    page.on("request", lambda request: writes.append(request.url)
            if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url) as read:
            page.goto(f"{nov20_web}/finance/{direction.lower()}?month={MONTH}")
        assert read.value.status == 200, read.value.text()
        payload = read.value.json()
        data = payload["data"]
        assert data["month"] == MONTH and data["feeDirection"] == direction
        assert data["summary"]["calculatedFeeCent"] == total_cent
        assert data["summary"]["candidateCouponCount"] == 5
        assert data["summary"]["calculatedCouponCount"] == 2
        assert data["summary"]["pendingCouponCount"] == 2
        assert data["summary"]["excludedCouponCount"] == 1
        assert data["coverage"]["sourceSuccessDays"] == data["coverage"]["sourceTotalDays"] == 31
        assert data["coverage"]["scopeUnresolved"] is True
        publication_id = payload["meta"]["publication"]["id"]
        assert publication_id == nov20_api[1]

        panel = page.get_by_role("region", name="内部月度试算", exact=True)
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("试算")
        expect(panel).to_contain_text(f"{total_cent / 100:,.2f}")
        pending = panel.locator("tbody tr").filter(has_text="trial-unassigned")
        expect(pending).to_contain_text("待核验")
        expect(pending).to_contain_text("销售门店归属待核验")
        expect(pending).not_to_contain_text("0.00")

        with page.expect_response(lambda response: "/admin/finance/trial/export?" in response.url) as exported:
            with page.expect_download() as downloading:
                panel.get_by_role("button", name="导出内部试算明细", exact=True).click()
        assert exported.value.status == 200, exported.value.text()
        query = parse_qs(urlsplit(exported.value.url).query)
        assert query["publication_id"] == [publication_id]
        assert query["month"] == [MONTH]
        assert query["feeDirection"] == [direction]
        download = downloading.value
        title = "推广服务费" if direction == "PROMOTION" else "管理服务费"
        assert download.suggested_filename.startswith(f"{title}内部试算_{MONTH}_")
        raw, rows = read_csv(download)
        assert len(rows) == data["total"] == 5
        assert {row["试算版本"] for row in rows} == {publication_id}
        assert {row["数据状态"] for row in rows} == {"试算／待核验"}
        assert all(not key.isascii() or key == "SKU ID" for key in rows[0])
        fee_column = amount_field(rows[0], "试算费用")
        assert sum(Decimal(row[fee_column] or "0") for row in rows) * 100 == total_cent
        by_coupon = {row["券ID"].removeprefix("'"): row for row in rows}
        assert by_coupon[LONG_COUPON_ID]["订单ID"].removeprefix("'") == LONG_ORDER_ID
        assert by_coupon[LONG_COUPON_ID]["券ID"].startswith("'")
        for coupon in ("trial-known-pending", "trial-unassigned"):
            assert by_coupon[coupon][fee_column] == ""
            assert by_coupon[coupon]["金额说明"] == "金额待核"
            assert by_coupon[coupon]["核对状态"] == "待核验"
        assert by_coupon["trial-excluded"]["核对状态"] == "已明确排除"

        evidence = evidence_directory(tmp_path)
        (evidence / f"{width}-{download.suggested_filename}").write_bytes(raw)
        page.screenshot(path=str(evidence / f"nov20-{direction}-{width}.png"), full_page=True)
        factory = live_fixture.LIVE_ADMIN_SESSION_FACTORIES[nov20_api[0]]
        with factory() as session:
            assert not session.scalars(select(SettlementStatement).where(
                SettlementStatement.statement_month == MONTH,
            )).all()
        assert writes == [] and errors == []
    finally:
        context.close()


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_internal_trial_rechecks_scoped_admin_and_store_role_for_page_and_export(
    browser, nov20_api, nov20_web, direction,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    context.add_cookies([{"name": "dy_e2e_role", "value": "admin_restricted", "url": nov20_web}])
    try:
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url) as read:
            page.goto(f"{nov20_web}/finance/{direction.lower()}?month={MONTH}")
        assert read.value.status == 200, read.value.text()
        data = read.value.json()["data"]
        assert {row["storeId"] for row in data["list"]} == {"store-1"}
        assert data["total"] == 3
        panel = page.get_by_role("region", name="内部月度试算", exact=True)
        expect(panel).not_to_contain_text("杭州滨江直营服务店")
        with page.expect_download() as downloading:
            panel.get_by_role("button", name="导出内部试算明细", exact=True).click()
        _, rows = read_csv(downloading.value)
        assert len(rows) == 3
        assert {row["门店ID"].removeprefix("'") for row in rows} == {"store-1"}

        # The page's existing pin is safe to retain while its identity changes.
        context.add_cookies([{"name": "dy_e2e_role", "value": "store", "url": nov20_web}])
        for endpoint in ("trial", "trial/export"):
            denied = context.request.get(f"{nov20_api[0]}/api/v1/admin/finance/{endpoint}", params={
                "month": MONTH, "feeDirection": direction, "publication_id": nov20_api[1],
            })
            assert denied.status == 403, denied.text()
        page.reload()
        expect(page.get_by_role("region", name="内部月度试算", exact=True)).to_have_count(0)
    finally:
        context.close()


def test_headquarters_trial_filters_direction_and_export_while_formal_ranking_is_blocked(
    browser, nov20_api, nov20_web,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    writes = []
    page.on("request", lambda request: writes.append(request.url)
            if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
    try:
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url) as trial:
            with page.expect_response(lambda response: "/dashboard/store-ranking?" in response.url) as formal:
                page.goto(f"{nov20_web}/ranking?periodKey={MONTH}")
        assert formal.value.status == 503
        assert trial.value.status == 200
        assert trial.value.json()["data"]["summary"]["calculatedFeeCent"] == 13045
        panel = page.get_by_role("region", name="内部月度试算", exact=True)
        expect(panel).to_contain_text("130.45")
        page.get_by_role("button", name="试算费用方向", exact=True).click()
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url
                                  and "feeDirection=MANAGEMENT" in response.url) as management:
            page.get_by_role("option", name="管理服务费", exact=True).click()
        assert management.value.json()["data"]["summary"]["calculatedFeeCent"] == 6232
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url
                                  and parse_qs(urlsplit(response.url).query).get("q") == ["深圳临港"]):
            page.get_by_label("搜索门店", exact=True).fill("深圳临港")
        expect(panel.locator("tbody tr")).to_have_count(3)
        page.get_by_role("button", name="商品类型", exact=True).click()
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url
                                  and parse_qs(urlsplit(response.url).query).get("productType") == ["养车服务"]) as filtered:
            page.get_by_role("option", name="养车服务", exact=True).click()
        assert filtered.value.status == 200
        assert filtered.value.json()["data"]["summary"]["calculatedFeeCent"] == 5432
        expect(panel.locator("tbody tr")).to_have_count(1)
        with page.expect_response(lambda response: "/admin/finance/trial/export?" in response.url) as exported:
            with page.expect_download() as downloading:
                panel.get_by_role("button", name="导出内部试算明细", exact=True).click()
        query = parse_qs(urlsplit(exported.value.url).query)
        assert query["month"] == [MONTH]
        assert query["feeDirection"] == ["MANAGEMENT"]
        assert query["productType"] == ["养车服务"]
        assert query["q"] == ["深圳临港"]
        assert query["publication_id"] == [filtered.value.json()["meta"]["publication"]["id"]]
        _, rows = read_csv(downloading.value)
        assert len(rows) == 1
        assert Decimal(rows[0][amount_field(rows[0], "试算费用")]) == Decimal("54.32")
        assert writes == []
    finally:
        context.close()


@pytest.mark.parametrize("instant,expected_month", [
    ("2026-10-31T16:30:00+00:00", "2026-10"),
    ("2026-11-30T16:30:00+00:00", "2026-11"),
    ("2026-12-31T16:30:00+00:00", "2026-12"),
])
@pytest.mark.parametrize("path,endpoint,month_key,label", [
    ("/ranking", "/dashboard/store-ranking?", "periodKey", "账期"),
    ("/settlement?storeId=store-1", "/monthly-settlement?", "month", "账期"),
    ("/finance/promotion", "/admin/finance/summary?", "month", "筛选账期"),
    ("/finance/management", "/admin/finance/summary?", "month", "筛选账期"),
    ("/settlement/invoice/status?storeId=store-1", "/store-invoice-status?", "month", None),
])
def test_unfinished_previous_shanghai_month_is_retained_across_year_and_local_timezone(
    browser, localized_web, instant, expected_month, path, endpoint, month_key, label,
):
    context = browser.new_context(timezone_id="America/Los_Angeles")
    page = context.new_page()
    try:
        page.clock.set_fixed_time(datetime.fromisoformat(instant))
        with page.expect_response(lambda response: endpoint in response.url) as read:
            page.goto(localized_web + path)
        assert parse_qs(urlsplit(read.value.url).query)[month_key] == [expected_month]
        if label == "筛选账期":
            expect(page.get_by_label(label, exact=True)).to_have_value(expected_month)
        elif label:
            expect(page.get_by_role("button", name=label, exact=True)).to_have_text(expected_month)
        with page.expect_response(lambda response: endpoint in response.url) as reread:
            page.reload()
        assert parse_qs(urlsplit(reread.value.url).query)[month_key] == [expected_month]
    finally:
        context.close()


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_explicit_and_manual_month_switch_keep_trial_page_and_download_in_one_period(
    browser, nov20_web, nov20_api, direction,
):
    context = browser.new_context()
    page = context.new_page()
    writes = []
    page.on("request", lambda request: writes.append(request.url)
            if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
    try:
        page.clock.set_fixed_time(datetime.fromisoformat("2026-12-02T00:00:00+08:00"))
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url) as explicit:
            page.goto(f"{nov20_web}/finance/{direction.lower()}?month={MONTH}")
        assert explicit.value.status == 200
        assert parse_qs(urlsplit(explicit.value.url).query)["month"] == [MONTH]
        with page.expect_response(lambda response: "/admin/finance/summary?" in response.url
                                  and "month=2026-08" in response.url):
            page.get_by_label("筛选账期", exact=True).fill("2026-08")
        expect(page.get_by_label("筛选账期", exact=True)).to_have_value("2026-08")
        assert parse_qs(urlsplit(page.url).query)["month"] == ["2026-08"]
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url
                                  and f"month={MONTH}" in response.url) as restored:
            page.get_by_label("筛选账期", exact=True).fill(MONTH)
        assert restored.value.status == 200
        panel = page.get_by_role("region", name="内部月度试算", exact=True)
        with page.expect_response(lambda response: "/admin/finance/trial/export?" in response.url) as exported:
            with page.expect_download() as downloading:
                panel.get_by_role("button", name="导出内部试算明细", exact=True).click()
        query = parse_qs(urlsplit(exported.value.url).query)
        assert query["month"] == [MONTH] and query["feeDirection"] == [direction]
        assert query["publication_id"] == [restored.value.json()["meta"]["publication"]["id"]]
        _, rows = read_csv(downloading.value)
        assert len(rows) == 5
        assert {row["账期"] for row in rows} == {"2026年10月"}
        assert writes == []
    finally:
        context.close()


def test_confirmed_and_invoiced_formal_bill_survives_refresh_and_returning_from_other_month(
    browser, localized_api, localized_web,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_cookies([{"name": "dy_e2e_role", "value": "store", "url": localized_web}])
    page = context.new_page()
    writes, errors = [], []
    page.on("request", lambda request: writes.append(request.url)
            if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        expected = None
        for month in ("2026-08", MONTH, "2026-08"):
            with page.expect_response(lambda response: "/store-settlements?" in response.url
                                      and f"month={month}" in response.url) as read:
                page.goto(f"{localized_web}/settlement?storeId=store-1&month={month}")
            assert read.value.status == 200, read.value.text()
            if month == MONTH:
                assert read.value.json()["data"]["list"] == []
                continue
            bill = read.value.json()["data"]["list"][0]
            assert bill["statementId"] == "uat-statement-store-1"
            assert bill["promotionAmountCent"] == 12_864_050
            assert bill["managementAmountCent"] == 320_000
            # The existing synthetic dispute freezes 640.50 yuan separately.
            assert bill["promotionConfirmableAmountCent"] == 12_800_000
            assert bill["promotionConfirmation"]["confirmedAt"]
            assert bill["promotionInvoiceStatus"] == "APPROVED_SETTLED"
            if expected is None:
                expected = bill
            else:
                assert bill == expected
            card = page.locator(".store-finance-direction-card").filter(has_text="推广服务费确认")
            expect(card).to_contain_text("128,000.00")
            expect(card).to_contain_text("已确认")
            expect(card).to_contain_text("2026-08-06")
            expect(page.get_by_role("button", name="确认推广服务费", exact=True)).to_have_count(0)
            frozen_metric = page.locator(".metric-card").filter(
                has=page.locator(".metric-card__label", has_text="当期推广服务费"),
            )
            expect(frozen_metric).to_contain_text("128,640.50")
            details = page.get_by_role("region", name="费用明细", exact=True)
            expect(details).to_contain_text("DY2026071900842")
            with page.expect_response(lambda response: "/store-settlements?" in response.url) as refreshed:
                page.reload()
            assert refreshed.value.json()["data"]["list"][0] == expected
        assert writes == [] and errors == []
    finally:
        context.close()
