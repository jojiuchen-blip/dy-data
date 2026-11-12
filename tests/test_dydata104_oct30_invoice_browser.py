"""Real invoice API/browser regressions for month selection and group loading.

Only explicitly injected transport failures use route interception. All amounts,
confirmations and group membership come from the isolated production API.
"""
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect
from sqlalchemy import delete, select

from apps.api.dy_api.models import AggStoreMonthlySettlement, SettlementStatement, SettlementStatementConfirmation
from publication_fixture_helpers import publish_fixture
from test_dydata104_oct23_invoice_browser import browser, invoice_api, invoice_web


def _confirm(factory, *, zero=False):
    with factory.begin() as session:
        bill = session.scalar(select(SettlementStatement))
        if zero:
            bill.promotion_original_fee_cent = bill.promotion_net_fee_cent = 0
        session.add(SettlementStatementConfirmation(confirmation_id="oct30-synthetic-confirmation",
            statement_id=bill.statement_id, fee_direction=1, confirmed_amount_cent=bill.promotion_net_fee_cent,
            confirmed_by="synthetic-test-admin", confirmed_at=datetime(2026, 10, 2, tzinfo=timezone.utc)))


@pytest.fixture()
def page(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.clock.install(time=datetime(2026, 10, 30, tzinfo=timezone.utc))
    try:
        yield page
    finally:
        context.close()


def test_default_ignores_unfinished_latest_metadata_month(page, invoice_web, invoice_api):
    with invoice_api[1].begin() as session:
        session.add(AggStoreMonthlySettlement(month="2026-10", store_id="oct23-store", product_scope="all", product_type="all"))
    with invoice_api[1]() as session:
        publish_fixture(session, "settlement")
    _confirm(invoice_api[1])
    requests = []
    page.on("request", lambda request: requests.append(request.url) if "/store-settlements?" in request.url else None)
    page.goto(f"{invoice_web}/settlement/invoice?storeId=oct23-store")
    expect(page.locator(".store-finance-invoice-info")).to_contain_text("106.01")
    months = [parse_qs(urlparse(url).query)["month"][0] for url in requests]
    assert months and set(months) == {"2026-09"}


def test_explicit_url_month_is_primary_read_and_unrelated_month_failure_is_unused(page, invoice_web, invoice_api):
    _confirm(invoice_api[1])
    months = []
    def inspect(route):
        month = parse_qs(urlparse(route.request.url).query)["month"][0]
        months.append(month)
        if month == "2026-08":
            route.fulfill(status=503, content_type="application/json", body='{"error":{"message":"synthetic unavailable historical month"}}')
        else:
            route.continue_()
    page.route("**/api/v1/store-settlements?*", inspect)
    page.goto(f"{invoice_web}/settlement/invoice?storeId=oct23-store&month=2026-09")
    expect(page.locator(".store-finance-invoice-info")).to_contain_text("106.01")
    assert months == ["2026-09"]


def test_explicit_older_url_month_loads_required_later_group_by_id(page, invoice_web, invoice_api):
    _confirm(invoice_api[1])
    requests = []
    page.on("request", lambda request: requests.append(request.url) if "/store-settlements" in request.url else None)
    page.goto(f"{invoice_web}/settlement/invoice?storeId=oct23-store&month=2026-08")
    expect(page.locator(".store-finance-invoice-info")).to_contain_text("106.01")
    list_reads = [url for url in requests if "/store-settlements?" in url]
    assert list_reads and all(parse_qs(urlparse(url).query)["month"] == ["2026-08"] for url in list_reads)
    assert any(urlparse(url).path.endswith("/store-settlements/oct23-bill") for url in requests)


@pytest.mark.parametrize("failure", ["missing", "denied", "group_changed"])
def test_required_member_failure_cannot_show_or_submit_old_amount(page, invoice_web, invoice_api, failure):
    _confirm(invoice_api[1])
    def detail(route):
        if failure in ("missing", "denied"):
            route.fulfill(status=404 if failure == "missing" else 403,
                content_type="application/json", body='{"error":{"message":"synthetic required member failure"}}')
            return
        with invoice_api[1].begin() as session:
            session.scalar(select(SettlementStatementConfirmation)).confirmation_status = 2
        route.continue_()
    page.route("**/api/v1/store-settlements/oct23-bill", detail)
    page.goto(f"{invoice_web}/settlement/invoice?storeId=oct23-store&month=2026-08")
    info = page.locator(".store-finance-invoice-info")
    expect(info).to_contain_text("账单金额读取失败，请重试")
    expect(info).not_to_contain_text("106.01")
    page.get_by_role("button", name="校验并登记发票", exact=True).click()
    expect(page.get_by_text("发票信息已登记，状态已更新。", exact=True)).to_have_count(0)


@pytest.mark.parametrize("kind,message", [
    ("pending", "账单待确认，尚不可开票"),
    ("zero", "本期金额为0，无需开票"),
    ("empty", "所选账期尚无账单"),
])
def test_no_group_has_a_specific_business_reason(page, invoice_web, invoice_api, kind, message):
    if kind == "zero":
        _confirm(invoice_api[1], zero=True)
    if kind == "empty":
        with invoice_api[1].begin() as session:
            session.execute(delete(SettlementStatement))
    page.goto(f"{invoice_web}/settlement/invoice?storeId=oct23-store&month=2026-09")
    expect(page.locator(".store-finance-invoice-info")).to_contain_text(message)
    expect(page.locator(".store-finance-invoice-info")).not_to_contain_text("尚未生成")
