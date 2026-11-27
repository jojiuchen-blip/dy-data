"""Acceptance for public settlement screens and authorized internal trial exports.

The publication facts and test identities are synthetic. The browser checks
public pages, invoices, history and trial access for authorized administrators.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

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


def decode_csv(raw: bytes) -> tuple[bytes, list[dict[str, str]]]:
    assert raw.startswith(b"\xef\xbb\xbf")
    return raw, list(csv.DictReader(StringIO(raw.decode("utf-8-sig"))))


def read_csv(download) -> tuple[bytes, list[dict[str, str]]]:
    return decode_csv(Path(download.path()).read_bytes())


def request_trial(context, nov20_api, direction, endpoint="trial", **filters):
    response = context.request.get(f"{nov20_api[0]}/api/v1/admin/finance/{endpoint}", params={
        "month": MONTH, "feeDirection": direction, "publication_id": nov20_api[1], **filters,
    })
    assert response.status == 200, response.text()
    return response


def read_trial(context, nov20_api, direction, endpoint="trial", **filters):
    payload = request_trial(context, nov20_api, direction, endpoint, **filters).json()
    assert payload["meta"]["publication"]["id"] == nov20_api[1]
    data = payload["data"]
    assert data["month"] == MONTH and data["feeDirection"] == direction
    return data


def export_trial(context, nov20_api, direction, endpoint="trial/export", **filters):
    response = request_trial(context, nov20_api, direction, endpoint, **filters)
    assert response.headers["x-publication-id"] == nov20_api[1]
    disposition = response.headers["content-disposition"]
    prefix = "attachment; filename*=UTF-8''"
    assert disposition.startswith(prefix), disposition
    filename = unquote(disposition.removeprefix(prefix))
    raw, rows = decode_csv(response.body())
    return filename, raw, rows


def observe_requests(page) -> list[tuple[str, str]]:
    requests = []
    page.on("request", lambda request: requests.append((request.method, request.url)))
    return requests


def assert_no_trial_exposure(page, requests):
    expect(page.get_by_role("main")).not_to_contain_text("内部试算")
    expect(page.get_by_role("region", name="内部月度试算", exact=True)).to_have_count(0)
    expect(page.get_by_role("main")).not_to_contain_text("PUBLICATION_PERIOD_NOT_READY")
    assert not any("/admin/finance/trial" in url for _, url in requests)
    assert all(method in {"GET", "HEAD", "OPTIONS"} for method, _ in requests)


def assert_collapsed_trial(page, requests):
    expect(page.get_by_role("button", name="查看内部试算", exact=True)).to_be_visible()
    expect(page.get_by_role("region", name="内部月度试算", exact=True)).to_have_count(0)
    assert not any("/admin/finance/trial" in url for _, url in requests)


def amount_field(row: dict[str, str], label: str) -> str:
    matches = [key for key in row if key == label or key == f"{label}（元）"]
    assert len(matches) == 1, list(row)
    return matches[0]


def evidence_directory(tmp_path: Path) -> Path:
    directory = Path(os.environ.get("DYDATA_BROWSER_EVIDENCE_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def test_finance_home_opens_formal_billing_and_keeps_submitted_invoices_available(browser, localized_web):
    context = browser.new_context()
    page = context.new_page()
    requests = observe_requests(page)
    page.route("**/api/v1/admin/finance/summary?**", lambda route: route.fulfill(status=503, json={
        "detail": {"code": "PUBLICATION_PERIOD_NOT_READY", "message": "本账期待核对"},
    }))
    try:
        page.clock.set_fixed_time(datetime.fromisoformat("2026-11-24T12:00:00+08:00"))
        with page.expect_response(lambda response: "/admin/finance/trial?" in response.url, timeout=15000):
            page.goto(f"{localized_web}/finance/promotion")
        expect(page.get_by_role("tab", name="正式账单", exact=True)).to_have_attribute("aria-selected", "true")
        expect(page.get_by_label("筛选账期", exact=True)).to_have_value(MONTH)
        notice = page.get_by_text("本账期账单尚未发布，可切换账期查看。", exact=True).filter(visible=True)
        expect(notice).to_be_visible()
        expect(page.get_by_role("region", name="内部月度试算", exact=True)).to_be_visible()

        requests.clear()
        page.get_by_role("tab", name="门店提交发票", exact=True).click()
        region = page.get_by_role("region", name="门店提交的推广费发票", exact=True)
        invoice_number = "25322000001784352171"
        row = region.locator("tbody tr").filter(has_text=invoice_number)
        expect(row).to_be_visible()
        expect(row).to_contain_text("2026-08")
        expect(row).to_contain_text("2026-09")
        expect(row).to_contain_text("发票项目名称不符合开票要求")
        page.get_by_role("searchbox", name="搜索", exact=True).fill(invoice_number)
        expect(region.locator("tbody tr")).to_have_count(1)
        expect(row).to_be_visible()
        with page.expect_download() as downloaded:
            page.get_by_role("button", name="导出发票", exact=True).click()
        _, rows = read_csv(downloaded.value)
        assert len(rows) == 1
        assert rows[0]["发票号码"].removeprefix("'") == invoice_number
        assert rows[0]["原账期"] == "2026-08"
        assert rows[0]["结算归属月"] == "2026-09"
        assert_no_trial_exposure(page, requests)
    finally:
        context.close()


@pytest.mark.parametrize("direction,total_cent", [("PROMOTION", 13045), ("MANAGEMENT", 6232)])
@pytest.mark.parametrize("width", [390, 1440])
def test_finance_pages_offer_trial_and_preserve_internal_csv_with_zero_formal_bills(
    browser, nov20_api, nov20_web, tmp_path, direction, total_cent, width,
):
    context = browser.new_context(viewport={"width": width, "height": 1000})
    page = context.new_page()
    requests = observe_requests(page)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"{nov20_web}/finance/{direction.lower()}?month={MONTH}")
        formal_label = "正式账单推广费总额" if direction == "PROMOTION" else "正式账单管理费总额"
        formal_card = page.locator(".metric-card").filter(
            has=page.locator(".metric-card__label", has_text=formal_label),
        )
        expect(formal_card).to_contain_text("0.00")
        assert_collapsed_trial(page, requests)

        data = read_trial(context, nov20_api, direction)
        summary = data["summary"]
        assert summary["calculatedFeeCent"] == total_cent
        assert summary["candidateCouponCount"] == 5
        assert summary["calculatedCouponCount"] == 2
        assert summary["pendingCouponCount"] == 2
        assert summary["excludedCouponCount"] == 1
        assert data["coverage"]["sourceSuccessDays"] == data["coverage"]["sourceTotalDays"] == 31
        assert data["coverage"]["scopeUnresolved"] is True
        pending = next(item for item in data["list"] if item["couponId"] == "trial-unassigned")
        assert pending["recordStatus"] == "PENDING"
        assert pending["reason"] == "销售门店归属待核验"
        assert pending["feeAmountCent"] is None

        filename, raw, rows = export_trial(context, nov20_api, direction)
        title = "推广服务费" if direction == "PROMOTION" else "管理服务费"
        assert filename.startswith(f"{title}内部试算_{MONTH}_")
        assert len(rows) == data["total"] == 5
        assert {row["试算版本"] for row in rows} == {nov20_api[1]}
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
        (evidence / f"{width}-{filename}").write_bytes(raw)
        page.screenshot(path=str(evidence / f"nov20-{direction}-{width}.png"), full_page=True)
        factory = live_fixture.LIVE_ADMIN_SESSION_FACTORIES[nov20_api[0]]
        with factory() as session:
            assert not session.scalars(select(SettlementStatement).where(
                SettlementStatement.statement_month == MONTH,
            )).all()
        assert errors == []
    finally:
        context.close()


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_internal_trial_api_and_export_enforce_scoped_admin_and_store_role(
    browser, nov20_api, nov20_web, direction,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    requests = observe_requests(page)
    context.add_cookies([{"name": "dy_e2e_role", "value": "admin_restricted", "url": nov20_web}])
    try:
        page.goto(f"{nov20_web}/finance/{direction.lower()}?month={MONTH}")
        expect(page.get_by_label("筛选账期", exact=True)).to_have_value(MONTH)
        assert_collapsed_trial(page, requests)
        data = read_trial(context, nov20_api, direction)
        assert {row["storeId"] for row in data["list"]} == {"store-1"}
        assert data["total"] == 3
        _, _, rows = export_trial(context, nov20_api, direction)
        assert len(rows) == 3
        assert {row["门店ID"].removeprefix("'") for row in rows} == {"store-1"}

        # A previously obtained publication ID does not grant trial access.
        context.add_cookies([{"name": "dy_e2e_role", "value": "store", "url": nov20_web}])
        for endpoint in ("trial", "trial/export", "trial/stores", "trial/stores/export"):
            denied = context.request.get(f"{nov20_api[0]}/api/v1/admin/finance/{endpoint}", params={
                "month": MONTH, "feeDirection": direction, "publication_id": nov20_api[1],
            })
            assert denied.status == 403, denied.text()
        requests.clear()
        page.reload()
        assert_no_trial_exposure(page, requests)
    finally:
        context.close()


def test_authorized_ranking_opens_trial_and_pins_filters_and_download(
    browser, nov20_api, nov20_web,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    requests = observe_requests(page)
    try:
        with page.expect_response(lambda response: "/admin/finance/trial/stores?" in response.url, timeout=15000) as trial:
            with page.expect_response(lambda response: "/dashboard/store-ranking?" in response.url) as formal:
                page.goto(f"{nov20_web}/ranking?periodKey={MONTH}")
        assert formal.value.status == 503
        assert trial.value.json()["meta"]["publication"]["id"] == nov20_api[1]
        notice = page.get_by_text("本账期账单尚未发布，可切换账期查看。", exact=True).filter(visible=True)
        expect(notice).to_be_visible()
        panel = page.get_by_role("region", name="内部月度试算", exact=True)
        expect(panel.get_by_role("heading", name=f"{MONTH} 推广服务费内部试算")).to_be_visible()
        expect(panel.get_by_role("cell", name="深圳临港认证服务店", exact=True)).to_be_visible()
        page.get_by_role("button", name="收起内部试算", exact=True).click()
        page.get_by_role("button", name="查看内部试算", exact=True).click()
        direction_button = panel.get_by_role("button", name="试算费用方向", exact=True)
        direction_button.click()
        panel.get_by_role("option", name="管理服务费", exact=True).click()
        paused_ranking = []

        def pause_ranking_filter(route):
            if parse_qs(urlsplit(route.request.url).query).get("q") == ["深圳临港"]:
                paused_ranking.append(route)
                page.evaluate("console.info('ranking-filter-held')")
            else:
                route.continue_()

        page.route("**/api/v1/dashboard/store-ranking?*", pause_ranking_filter)
        with page.expect_console_message(lambda message: message.text == "ranking-filter-held"):
            page.get_by_placeholder("输入门店名称", exact=True).fill("深圳临港")
        assert len(paused_ranking) == 1
        with page.expect_response(lambda response: "/admin/finance/trial/stores?" in response.url
                                  and parse_qs(urlsplit(response.url).query).get("q") == ["深圳临港"], timeout=15000):
            paused_ranking[0].continue_()
        relevant = [parse_qs(urlsplit(url).query) for _, url in requests if "/admin/finance/trial" in url]
        assert relevant and all(query.get("publication_id") == [nov20_api[1]] for query in relevant)
        expect(panel.get_by_role("heading", name=f"{MONTH} 管理服务费内部试算")).to_be_visible()
        expect(panel.get_by_role("cell", name="深圳临港认证服务店", exact=True)).to_be_visible()
        with page.expect_download() as downloaded:
            panel.get_by_role("button", name="导出门店试算汇总", exact=True).click()
        _, downloaded_rows = read_csv(downloaded.value)
        assert {row["试算版本"] for row in downloaded_rows} == {nov20_api[1]}
        assert {row["门店名称"] for row in downloaded_rows if row["汇总层级"] == "门店"} == {"深圳临港认证服务店"}

        assert read_trial(context, nov20_api, "PROMOTION")["summary"]["calculatedFeeCent"] == 13045
        assert read_trial(context, nov20_api, "MANAGEMENT")["summary"]["calculatedFeeCent"] == 6232
        assert read_trial(context, nov20_api, "MANAGEMENT", q="深圳临港")["total"] == 3
        filters = {"q": "深圳临港", "productType": "养车服务"}
        filtered = read_trial(context, nov20_api, "MANAGEMENT", **filters)
        assert filtered["total"] == 1
        assert filtered["summary"]["calculatedFeeCent"] == 5432
        _, _, rows = export_trial(context, nov20_api, "MANAGEMENT", **filters)
        assert len(rows) == 1
        assert rows[0]["券ID"].removeprefix("'") == filtered["list"][0]["couponId"]
        assert Decimal(rows[0][amount_field(rows[0], "试算费用")]) == Decimal("54.32")
    finally:
        context.close()


@pytest.mark.parametrize("entry", ["headquarters", "finance"])
@pytest.mark.parametrize("role", ["admin", "admin_restricted"])
@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_store_trial_summary_download_matches_coupon_facts_and_keeps_unknown_scope(
    browser, nov20_api, nov20_web, tmp_path, entry, role, direction,
):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_cookies([{"name": "dy_e2e_role", "value": role, "url": nov20_web}])
    page = context.new_page()
    requests = observe_requests(page)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        path, endpoint = (f"/ranking?periodKey={MONTH}", "/dashboard/store-ranking?") if entry == "headquarters" else (
            f"/finance/{direction.lower()}?month={MONTH}", "/admin/finance/summary?",
        )
        with page.expect_response(lambda response: endpoint in response.url):
            page.goto(nov20_web + path)
        if entry == "headquarters":
            expect(page.get_by_role("region", name="内部月度试算", exact=True)).to_be_visible()
        else:
            assert_collapsed_trial(page, requests)

        detail = read_trial(context, nov20_api, direction)
        stores = read_trial(context, nov20_api, direction, "trial/stores")
        assert stores["summary"] == detail["summary"]
        assert sum(item["calculatedFeeCent"] or 0 for item in stores["list"]) == (
            detail["summary"]["calculatedFeeCent"]
        )
        for store in stores["list"]:
            coupons = [item for item in detail["list"] if item["storeId"] == store["storeId"]]
            known = [item for item in coupons if item["recordStatus"] == "CALCULATED"]
            expected_amount = sum(item["feeAmountCent"] for item in known) if known else None
            assert store["calculatedFeeCent"] == expected_amount
            assert store["calculatedCouponCount"] == len({item["couponId"] for item in known})
            assert store["pendingCouponCount"] == len({
                item["couponId"] for item in coupons if item["recordStatus"] == "PENDING"
            })
            assert store["candidateCouponCount"] == len({item["couponId"] for item in coupons})
        if role == "admin_restricted":
            assert {item["storeId"] for item in stores["list"]} == {"store-1"}
        else:
            assert {item["storeId"] for item in stores["list"]} == {"store-1", "store-2", None}
            unknown = next(item for item in stores["list"] if item["storeId"] is None)
            assert unknown["calculatedFeeCent"] is None
            assert unknown["pendingCouponCount"] == 1

        filename, raw, rows = export_trial(context, nov20_api, direction, "trial/stores/export")
        title = "推广服务费" if direction == "PROMOTION" else "管理服务费"
        assert filename.startswith(f"{title}门店试算汇总_{MONTH}_")
        store_rows = [row for row in rows if row["汇总层级"] == "门店"]
        total_rows = [row for row in rows if row["汇总层级"] == "总计"]
        assert len(store_rows) == stores["total"]
        assert len(total_rows) == 1
        assert {row["试算版本"] for row in rows} == {nov20_api[1]}
        assert all(not column.isascii() for column in rows[0])
        amount_column = amount_field(rows[0], "已算费用")
        total = total_rows[0]
        assert total["门店名称"] == "全部筛选范围"
        assert Decimal(total[amount_column]) * 100 == detail["summary"]["calculatedFeeCent"]
        assert sum(Decimal(row[amount_column] or "0") for row in store_rows) == Decimal(total[amount_column])
        assert int(total["候选券数"]) == detail["summary"]["candidateCouponCount"]
        assert int(total["待核券数"]) == detail["summary"]["pendingCouponCount"]
        if role == "admin_restricted":
            assert {row["门店ID"].removeprefix("'") for row in store_rows} == {"store-1"}
        else:
            unknown_csv = next(row for row in store_rows if row["门店名称"] == "归属待核验")
            assert unknown_csv[amount_column] == ""
            assert unknown_csv["门店ID"] == ""

        evidence = evidence_directory(tmp_path)
        label = f"{entry}-{role}-{direction}"
        (evidence / f"{label}-{filename}").write_bytes(raw)
        page.screenshot(path=str(evidence / f"nov20-summary-{label}.png"), full_page=True)
        assert read_trial(context, nov20_api, direction) == detail
        _, _, coupon_rows = export_trial(context, nov20_api, direction)
        assert len(coupon_rows) == detail["total"]
        assert sum(Decimal(row[amount_field(row, "试算费用")] or "0") for row in coupon_rows) == Decimal(total[amount_column])
        assert errors == []
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
    ("/finance/promotion?view=billing", "/admin/finance/summary?", "month", "筛选账期"),
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
def test_explicit_and_manual_month_switch_keep_formal_view_and_internal_export_scoped(
    browser, nov20_web, nov20_api, direction,
):
    context = browser.new_context()
    page = context.new_page()
    requests = observe_requests(page)
    try:
        page.clock.set_fixed_time(datetime.fromisoformat("2026-12-02T00:00:00+08:00"))
        with page.expect_response(lambda response: "/admin/finance/summary?" in response.url) as explicit:
            page.goto(f"{nov20_web}/finance/{direction.lower()}?month={MONTH}")
        assert explicit.value.status == 200
        assert parse_qs(urlsplit(explicit.value.url).query)["month"] == [MONTH]
        month_input = page.get_by_label("筛选账期", exact=True)
        expect(month_input).to_have_value(MONTH)
        for month in ("2026-08", MONTH):
            with page.expect_response(lambda response: "/admin/finance/summary?" in response.url
                                      and f"month={month}" in response.url):
                month_input.fill(month)
            expect(month_input).to_have_value(month)
            assert parse_qs(urlsplit(page.url).query)["month"] == [month]
            if month == "2026-08":
                assert_no_trial_exposure(page, requests)

        assert_collapsed_trial(page, requests)
        restored = read_trial(context, nov20_api, direction)
        _, _, rows = export_trial(context, nov20_api, direction)
        assert len(rows) == restored["total"] == 5
        assert {row["试算版本"] for row in rows} == {nov20_api[1]}
        assert {row["账期"] for row in rows} == {"2026年10月"}
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
