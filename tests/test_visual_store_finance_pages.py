from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, expect

from test_visual_smoke import (
    api_payload,
    browser,
    install_api_routes,
    settlement_filter_meta,
    settlement_monthly_data,
    vite_real_api_base_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
VIEWPORTS = [(390, 844), (768, 1024), (1440, 900)]
PAGES = [
    ("store-ranking", "/ranking?month=2026-08&sortBy=promotionNetFeeCent", "全国门店月度榜单"),
    ("store-settlement", "/settlement?storeId=store_001&month=2026-08", "单店分账"),
    ("store-invoice", "/settlement/invoice?storeId=store_001&month=2026-08", "开票确认"),
    ("invoice-status", "/settlement/invoice/status?storeId=store_001&month=2026-08", "发票状态查看"),
]


def install_store_finance_routes(page) -> None:
    install_api_routes(page)
    statement = {
        "statementId": "STMT-VISUAL-001",
        "storeId": "store_001",
        "storeName": "上海浦东体验中心",
        "month": "2026-08",
        "versionNo": 2,
        "isCurrent": True,
        "supersedesStatementId": "STMT-VISUAL-000",
        "status": "CONFIRMED",
        "promotionAmountCent": 1024,
        "managementAmountCent": 512,
        "promotionConfirmableAmountCent": 1024,
        "managementConfirmableAmountCent": 512,
        "promotionConfirmation": {
            "confirmationId": "CONF-VISUAL-001",
            "status": "CONFIRMED",
            "confirmedAmountCent": 1024,
            "confirmedAt": "2026-08-06T10:00:00+08:00",
        },
        "managementConfirmation": None,
        "promotionInvoiceStatus": "PENDING_INVOICE",
        "promotionInvoiceableAmountCent": 1024,
        "promotionCarryforwardBalanceCent": 0,
        "promotionInvoiceGroupId": "promotion-group-visual-001",
        "promotionRequiredStatementIds": ["STMT-VISUAL-001"],
        "promotionPositiveAmountCent": 1024,
        "promotionNegativeAmountCent": 0,
        "managementInvoiceStatus": "PENDING_INVOICE",
    }
    page.route(
        "**/api/v1/store-settlements?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "list": [statement],
                "promotionInvoiceSummary": {"invoiceAmountCent": 1024, "netAmountCent": 966, "taxAmountCent": 58, "taxRatePercent": 6, "requiredStatementIds": ["STMT-VISUAL-001"]},
                "total": 1,
                "page": 1,
                "pageSize": 50,
                "metricScope": "CUMULATIVE",
                "metrics": {
                    "month": {
                        "promotionAmountCent": 1024,
                        "managementAmountCent": 512,
                    },
                    "cumulative": {
                        "promotionAmountCent": 4096,
                        "managementAmountCent": 2048,
                        "promotionInvoiceableAmountCent": 3072,
                    },
                },
            }),
        ),
    )
    def fulfill_ranking(route) -> None:
        assert parse_qs(urlparse(route.request.url).query)["publication_id"] == ["visual-settlement"]
        is_cumulative = "periodType=CUMULATIVE" in route.request.url
        route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "periodType": "CUMULATIVE" if is_cumulative else "MONTHLY",
                "periodKey": "2026-08",
                "productScope": "all",
                "productType": "all",
                "scopeMode": "AUTHORIZED",
                "totals": {
                    "salesOrderCount": 1,
                    "salesAmountCent": 12800,
                    "verifiedOrderCount": 1,
                    "verifiedAmountCent": 12800,
                    "promotionNetFeeCent": 4096 if is_cumulative else 1024,
                    "managementNetFeeCent": 2048 if is_cumulative else 512,
                    "netSettlementReferenceCent": 2048 if is_cumulative else 512,
                    "salesOrderCountCumulative": 1,
                    "salesAmountCumulativeCent": 12800,
                    "verifiedOrderCountCumulative": 1,
                    "verifiedAmountCumulativeCent": 12800,
                    "promotionMonthFeeCent": 1024,
                    "promotionCumulativeFeeCent": 4096,
                    "managementMonthFeeCent": 512,
                    "managementCumulativeFeeCent": 2048,
                    "netSettlementReferenceMonthCent": 512,
                    "netSettlementReferenceCumulativeCent": 2048,
                },
                "list": [],
                "total": 0,
                "page": 1,
                "pageSize": 20,
            }, publication_module="settlement"),
        )

    page.route("**/api/v1/dashboard/store-ranking?*", fulfill_ranking)
    page.route(
        "**/api/v1/dashboard/publications/settlement/filters*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload(settlement_filter_meta(), publication_module="settlement"),
        ),
    )
    page.route(
        "**/api/v1/meta/filters",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload(settlement_filter_meta()),
        ),
    )
    def fulfill_monthly_settlement(route) -> None:
        assert parse_qs(urlparse(route.request.url).query)["publication_id"] == ["visual-settlement"]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload(
                settlement_monthly_data("store_001", "上海浦东体验中心"),
                publication_module="settlement",
            ),
        )

    page.route(
        "**/api/v1/stores/store_001/monthly-settlement?*",
        fulfill_monthly_settlement,
    )
    page.route(
        "**/api/v1/order-fee-details?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "context": {
                    "storeId": "store_001",
                    "month": "2026-08",
                    "feeDirection": "PROMOTION",
                    "productScope": "all",
                    "productType": "all",
                    "feeRates": [],
                    "ruleVersions": [],
                },
                "list": [{
                    "feeResultId": "FEE-VISUAL-001",
                    "orderId": "ORDER-VISUAL-001",
                    "couponId": "COUPON-VISUAL-001",
                    "feeDirection": "PROMOTION",
                    "originalBusinessMonth": "2026-08",
                    "verifyTime": "2026-08-18T15:30:00+08:00",
                    "skuId": "SKU-VISUAL-001",
                    "productName": "基础保养服务",
                    "productScope": "all",
                    "productType": "all",
                    "saleChannel": "LIVE",
                    "sourceAmountCent": 12800,
                    "refundedAmountCent": 0,
                    "originalBaseCent": 12800,
                    "feeRate": "0.080000",
                    "originalFeeCent": 1024,
                    "adjustmentBaseCent": 0,
                    "adjustmentFeeCent": 0,
                    "adjustedNetBaseCent": 12800,
                    "adjustedNetFeeCent": 1024,
                    "ruleVersion": "V2026.08.1",
                    "resultStatus": "VALID",
                    "adjustments": [],
                }],
                "total": 1,
                "page": 1,
                "pageSize": 50,
            }),
        ),
    )
    page.route(
        "**/api/v1/promotion-invoices/INV-VISUAL-001",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "invoiceId": "INV-VISUAL-001",
                "physicalInvoiceId": "PHYSICAL-VISUAL-001",
                "storeId": "store_001",
                "versionNo": 1,
                "versionKind": "REGISTRATION",
                "isCurrent": True,
                "supersedesInvoiceId": None,
                "replacesInvoiceId": None,
                "invoiceNumber": "12345678901234567890",
                "invoiceDate": "2026-08-08",
                "invoiceAmountCent": 80000,
                "buyerName": "比亚迪汽车销售有限公司",
                "taxRatePercent": 6,
                "status": "REJECTED_REUPLOAD",
                "registeredAt": "2026-08-08T10:00:00+08:00",
                "versions": [],
                "allocations": [{
                    "allocationId": "ALLOC-VISUAL-001",
                    "invoiceId": "INV-VISUAL-001",
                    "statementId": "STMT-VISUAL-001",
                    "statementMonth": "2026-08",
                    "settlementBatchMonth": "2026-09",
                    "allocatedAmountCent": 80000,
                    "isCurrent": True,
                }],
                "statusEvents": [{
                    "eventId": "EVENT-VISUAL-001",
                    "invoiceId": "INV-VISUAL-001",
                    "fromStatus": "SUBMITTED_PENDING_FACTORY_REVIEW",
                    "toStatus": "REJECTED_REUPLOAD",
                    "operatorId": "factory-import",
                    "resultReason": "税率不正确，请按基准资料重新开具。",
                    "occurredAt": "2026-08-10T09:00:00+08:00",
                }],
                "lifecycleEvents": [],
                "replacements": [],
                "replacementChain": [],
            }),
        ),
    )
    page.route(
        "**/api/v1/store-invoice-status?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "month": "2026-08",
                "metrics": {
                    "statementTotalCent": 128000,
                    "confirmedAmountCent": 118000,
                    "pendingInvoiceAmountCent": 38000,
                    "issuedAmountCent": 80000,
                    "settledOrDeductedAmountCent": 60000,
                    "approvedAmountCent": 60000,
                    "hasData": True,
                },
                "promotionInvoices": [{
                    "invoiceId": "INV-VISUAL-001",
                    "storeId": "store_001",
                    "statementId": "STMT-VISUAL-001",
                    "statementMonth": "2026-08",
                    "settlementBatchMonth": "2026-09",
                    "versionNo": 1,
                    "isCurrent": True,
                    "supersedesInvoiceId": None,
                    "replacesInvoiceId": None,
                    "invoiceNumber": "12345678901234567890",
                    "invoiceDate": "2026-08-08",
                    "invoiceAmountCent": 80000,
                    "buyerName": "比亚迪汽车销售有限公司",
                    "taxRatePercent": 6,
                    "status": "REJECTED_REUPLOAD",
                    "registeredAt": "2026-08-08T10:00:00+08:00",
                    "allocatedAmountCent": 80000,
                    "isMultiPeriod": False,
                    "rejectionReason": "税率不正确，请按基准资料重新开具。",
                    "settledAt": None,
                }],
                "promotionTotal": 1,
                "managementInvoices": [{
                    "invoiceId": "MGMT-VISUAL-001",
                    "storeId": "store_001",
                    "statementId": "STMT-VISUAL-001",
                    "statementMonth": "2026-08",
                    "feeDirection": "MANAGEMENT",
                    "versionNo": 1,
                    "isCurrent": True,
                    "invoiceNumber": "22345678901234567890",
                    "invoiceDate": "2026-08-08",
                    "invoiceAmountCent": 51200,
                    "status": "APPROVED_SETTLED",
                    "registeredAt": "2026-08-08T10:00:00+08:00",
                    "factoryDeductionDate": "2026-08-15",
                    "factoryDeductionAmountCent": 51200,
                    "settledAt": "2026-08-15T10:00:00+08:00",
                }],
                "differenceLedger": [{
                    "feeDirection": "MANAGEMENT",
                    "sourceStatementMonth": "2026-07",
                    "targetStatementMonth": "2026-08",
                    "differenceAmountCent": 100,
                    "reason": "管理服务费结转抵扣",
                }],
                "page": 1,
                "pageSize": 20,
            }),
        ),
    )


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize("name,path,heading", PAGES)
def test_store_finance_pages_render_the_formal_flow_at_supported_widths(
    browser: Browser,
    vite_real_api_base_url: str,
    name: str,
    path: str,
    heading: str,
    width: int,
    height: int,
    tmp_path,
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    tmp_path.mkdir(parents=True, exist_ok=True)

    try:
        install_store_finance_routes(page)
        page.goto(f"{vite_real_api_base_url}{path}", wait_until="domcontentloaded")
        page.get_by_role("heading", name=heading, exact=True).wait_for(timeout=10000)
        timeline = page.locator(".store-finance-timeline")
        if name == "store-invoice":
            timeline.wait_for(timeout=10000)
            assert timeline.locator("li").count() == 7
        else:
            assert timeline.count() == 0
        assert page.get_by_text("DYDATA-19 · Mock", exact=True).count() == 0
        assert page.get_by_text("¥NaN", exact=True).count() == 0
        assert page.locator("body").evaluate(
            "node => node.scrollWidth <= node.clientWidth + 1",
        )
        if name == "store-invoice":
            status_style = page.locator(".store-finance-timeline__status").evaluate(
                "node => ({ background: getComputedStyle(node).backgroundColor, border: getComputedStyle(node).borderLeftColor })",
            )
            assert status_style == {
                "background": "rgb(255, 244, 239)",
                "border": "rgb(254, 82, 5)",
            }
        if name == "store-ranking":
            assert page.get_by_label("排行依据").count() == 1
            expect(page.get_by_label("商品类型", exact=True)).to_be_visible()
            expect(page.get_by_label("产品范围", exact=True)).to_have_count(0)
            expect(page.get_by_label("账期", exact=True)).to_have_text("2026-08")
        if name == "store-invoice":
            assert page.locator(".store-finance-invoice-workspace").count() == 1
            assert page.get_by_role("heading", name="购买方开票信息", exact=True).count() == 1
            assert page.get_by_role("heading", name="填写数电专票信息", exact=True).count() == 1
            assert page.get_by_role("button", name="校验并登记发票", exact=True).is_enabled()
            assert page.locator(".store-finance-validation-response").count() == 0
            assert page.get_by_text("数据加载失败，请稍后重试。", exact=True).count() == 0
            assert page.get_by_text("换票候选信息暂不可用，不影响本次开票。", exact=True).count() == 0

        page.screenshot(
            path=tmp_path / f"{name}-{width}x{height}.png",
            full_page=True,
        )
    finally:
        context.close()


def test_invoice_verification_workspace_uses_server_summary_and_reduced_form(
    browser: Browser,
    vite_real_api_base_url: str,
    tmp_path,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    tmp_path.mkdir(parents=True, exist_ok=True)

    try:
        install_store_finance_routes(page)
        page.route("**/api/v1/promotion-invoices", lambda route: route.fulfill(
            status=500, json={"detail": {"message": "Synthetic server unavailable"}}))
        page.goto(
            f"{vite_real_api_base_url}/settlement/invoice?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_text("¥10.24", exact=True).wait_for(timeout=10000)
        assert page.locator(".store-finance-invoice-period").count() == 0
        assert page.get_by_label("系统确定开票账期").count() == 0
        assert page.get_by_role("button", name="选择抵扣组", exact=True).count() == 0
        page.get_by_label("填写人电话").fill("13800138000")
        page.get_by_label("20 位数电专票号码").fill("98765432109876543210")
        page.get_by_label("开票日期").fill("2026-08-08")

        assert page.locator(".store-finance-validation-response").count() == 0
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/promotion-invoices")) as failed:
            page.get_by_role("button", name="校验并登记发票", exact=True).click()
        assert failed.value.status == 500

        feedback = page.locator(".store-finance-validation-response")
        assert feedback.count() == 1
        assert feedback.locator("li").count() == 0
        expect(feedback).to_contain_text("登记未成功，请核对下方错误后重试。")
        expect(feedback).not_to_contain_text("格式校验通过")
        expect(page.get_by_label("20 位数电专票号码", exact=True)).to_have_value("98765432109876543210")
        expect(page.get_by_text("发票信息已登记，状态已更新。", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="校验并登记发票", exact=True)).to_be_enabled()
        assert page.locator("body").evaluate(
            "node => node.scrollWidth <= node.clientWidth + 1",
        )

        page.screenshot(
            path=tmp_path / "store-invoice-verification-1440x900.png",
            full_page=True,
        )
    finally:
        context.close()


@pytest.mark.parametrize("earlier_is_invoiceable", [True, False])
def test_invoice_period_is_locked_and_all_billable_periods_are_presented_without_selection_control(
    browser: Browser,
    vite_real_api_base_url: str,
    earlier_is_invoiceable: bool,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    def statement(month: str, invoiceable: bool) -> dict[str, object]:
        statement_id = f"STMT-{month}"
        return {
            "statementId": statement_id,
            "storeId": "store_001",
            "storeName": "上海浦东体验中心",
            "month": month,
            "versionNo": 1,
            "isCurrent": True,
            "supersedesStatementId": None,
            "status": "CONFIRMED",
            "promotionAmountCent": 1024,
            "managementAmountCent": 512,
            "promotionConfirmableAmountCent": 1024,
            "managementConfirmableAmountCent": 512,
            "promotionConfirmation": {
                "confirmationId": f"CONF-{month}",
                "status": "CONFIRMED",
                "confirmedAmountCent": 1024,
                "confirmedAt": f"{month}-06T10:00:00+08:00",
            },
            "managementConfirmation": None,
            "promotionInvoiceStatus": "PENDING_INVOICE" if invoiceable else "APPROVED",
            "promotionInvoiceableAmountCent": 1024 if invoiceable else 0,
            "promotionCarryforwardBalanceCent": 0,
            "promotionInvoiceGroupId": f"GROUP-{month}" if invoiceable else None,
            "promotionRequiredStatementIds": [statement_id] if invoiceable else [],
            "promotionPositiveAmountCent": 1024 if invoiceable else 0,
            "promotionNegativeAmountCent": 0,
            "managementInvoiceStatus": "PENDING_INVOICE",
        }

    try:
        install_store_finance_routes(page)
        page.unroute("**/api/v1/meta/filters")
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    **settlement_filter_meta(),
                    "statementMonths": ["2026-08", "2026-07"],
                    "formalPeriodStartMonth": "2026-07",
                }),
            ),
        )
        page.unroute("**/api/v1/store-settlements?*")

        def fulfill_statements(route) -> None:
            is_earlier = "month=2026-07" in route.request.url
            row = statement(
                "2026-07" if is_earlier else "2026-08",
                earlier_is_invoiceable if is_earlier else True,
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "list": [row],
                    "promotionInvoiceSummary": {"invoiceAmountCent": 2048 if earlier_is_invoiceable else 1024,
                        "netAmountCent": 1932 if earlier_is_invoiceable else 966,
                        "taxAmountCent": 116 if earlier_is_invoiceable else 58, "taxRatePercent": 6,
                        "requiredStatementIds": ["STMT-2026-07", "STMT-2026-08"] if earlier_is_invoiceable else ["STMT-2026-08"]},
                    "total": 1,
                    "page": 1,
                    "pageSize": 50,
                    "metricScope": "MONTH",
                    "metrics": {
                        "month": {
                            "promotionAmountCent": 1024,
                            "managementAmountCent": 512,
                        },
                        "cumulative": {
                            "promotionAmountCent": 2048,
                            "managementAmountCent": 1024,
                        },
                    },
                }),
            )

        page.route("**/api/v1/store-settlements?*", fulfill_statements)
        detail_requests: list[str] = []

        def fulfill_earlier_statement(route) -> None:
            detail_requests.append("STMT-2026-07")
            route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(statement("2026-07", earlier_is_invoiceable)),
            )

        page.route(
            "**/api/v1/store-settlements/STMT-2026-07",
            fulfill_earlier_statement,
        )
        page.goto(
            f"{vite_real_api_base_url}/settlement/invoice?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )

        assert page.locator(".store-finance-invoice-period").count() == 0
        assert page.get_by_label("系统确定开票账期").count() == 0
        expected_amount = "¥20.48" if earlier_is_invoiceable else "¥10.24"
        page.get_by_text(expected_amount, exact=True).wait_for(timeout=10000)
        assert page.get_by_text("¥19.32" if earlier_is_invoiceable else "¥9.66", exact=True).is_visible()
        assert page.get_by_text("¥1.16" if earlier_is_invoiceable else "¥0.58", exact=True).is_visible()
        assert detail_requests == (["STMT-2026-07"] if earlier_is_invoiceable else [])
        assert page.get_by_role("button", name="选择抵扣组", exact=True).count() == 0
    finally:
        context.close()


def test_store_finance_detail_interactions_use_backend_resources(
    browser: Browser,
    vite_real_api_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_store_finance_routes(page)
        page.goto(
            f"{vite_real_api_base_url}/settlement?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_role("tab", name="管理费明细", exact=True).click()
        page.get_by_role("cell", name="ORDER-VISUAL-001", exact=True).wait_for()
        page.get_by_role("tab", name="推广费明细", exact=True).click()
        assert page.get_by_text("ORDER-VISUAL-001", exact=True).count() > 0

        page.goto(
            f"{vite_real_api_base_url}/settlement/invoice/status?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_role("button", name="查看详情", exact=True).click()
        page.get_by_text("税率不正确，请按基准资料重新开具。", exact=True).first.wait_for()
        page.get_by_text("结算账期分配", exact=True).wait_for()
    finally:
        context.close()


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize("name,path", [
    ("ranking-metrics", "/ranking"),
    ("store-settlement-metrics", "/settlement?storeId=store_001&month=2026-08"),
])
def test_store_summary_metrics_stay_compact_in_one_row(
    browser: Browser,
    vite_real_api_base_url: str,
    name: str,
    path: str,
    width: int,
    height: int,
    tmp_path,
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    tmp_path.mkdir(parents=True, exist_ok=True)

    try:
        install_store_finance_routes(page)
        page.goto(f"{vite_real_api_base_url}{path}", wait_until="domcontentloaded")
        cards = page.locator(".store-summary-metrics .metric-card")
        expected_card_count = 4 if name == "ranking-metrics" else 6
        expect(cards).to_have_count(expected_card_count, timeout=10000)
        expect(page.locator(".store-summary-metrics").get_by_text("当期推广服务费", exact=True)).to_have_count(1, timeout=10000)
        expect(page.locator(".store-summary-metrics").get_by_text("累计推广服务费", exact=True)).to_have_count(1, timeout=10000)
        if name == "ranking-metrics":
            expect(page.locator(".store-summary-metrics").get_by_text("当期管理服务费", exact=True)).to_have_count(0, timeout=10000)
            expect(page.locator(".store-summary-metrics").get_by_text("累计管理服务费", exact=True)).to_have_count(0, timeout=10000)
        else:
            expect(page.locator(".store-summary-metrics").get_by_text("当期管理服务费", exact=True)).to_have_count(1, timeout=10000)
            expect(page.locator(".store-summary-metrics").get_by_text("累计管理服务费", exact=True)).to_have_count(1, timeout=10000)
        assert page.locator(".store-summary-metrics").get_by_text(
            "结算参考净额", exact=True,
        ).count() == 0
        card_tops = [
            round(cards.nth(index).bounding_box()["y"])
            for index in range(expected_card_count)
        ]
        assert len(set(card_tops)) == 1
        assert page.locator("body").evaluate(
            "node => node.scrollWidth <= node.clientWidth + 1",
        )

        page.screenshot(
            path=tmp_path / f"{name}-{width}x{height}.png",
            full_page=True,
        )
    finally:
        context.close()
