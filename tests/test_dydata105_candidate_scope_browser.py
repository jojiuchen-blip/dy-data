"""Real candidate APIs; routing only delays a request or injects 401/403.

The module owns two synthetic terminated invoices in a disposable API/database.
Successful responses are always forwarded to the actual local FastAPI service.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect
from sqlalchemy import func, select

from test_visual_smoke import (
    LIVE_ADMIN_SESSION_FACTORIES, browser, live_admin_fastapi_base_url,
    vite_live_admin_api_base_url,
)
from dy_api.models import (
    DimStore, PromotionInvoice, PromotionInvoiceAllocation,
    PromotionInvoiceLifecycleEvent, PromotionInvoiceNumberRegistry,
    SettlementStatement,
)

live_admin_fastapi_base_url = pytest.fixture(scope="module")(live_admin_fastapi_base_url.__wrapped__)
vite_live_admin_api_base_url = pytest.fixture(scope="module")(vite_live_admin_api_base_url.__wrapped__)


@pytest.fixture(scope="module")
def candidate_stores(live_admin_fastapi_base_url):
    """Seed coherent terminated facts; module teardown disposes their database."""
    factory = LIVE_ADMIN_SESSION_FACTORIES[live_admin_fastapi_base_url]
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    with factory() as session:
        for index, suffix in enumerate(("A", "B")):
            key = "R105-SCOPE-" + suffix
            number = f"8105{index:016d}"
            session.add(DimStore(store_id=key, store_name="合成候选门店" + suffix, is_active=True))
            session.add(SettlementStatement(statement_id=key, store_id=key, statement_month="2026-09",
                version_no=1, is_current=True, statement_status=2,
                promotion_original_fee_cent=12345, promotion_adjustment_fee_cent=0, promotion_net_fee_cent=12345,
                management_original_fee_cent=0, management_adjustment_fee_cent=0, management_net_fee_cent=0,
                store_name_snapshot="合成候选门店" + suffix, sap_code_snapshot="SYNTHETIC",
                store_snapshot_status="LIVE_CAPTURED"))
            session.add(PromotionInvoice(invoice_id=key, physical_invoice_id=key, store_id=key,
                version_no=1, version_kind=1, is_current=False, invoice_number=number,
                invoice_date=date(2026, 9, 1), invoice_amount_cent=12345,
                buyer_name="比亚迪汽车销售有限公司", tax_rate_percent=6, invoice_status=4,
                registered_by="synthetic", registered_at=now))
            session.add(PromotionInvoiceNumberRegistry(invoice_number=number, physical_invoice_id=key,
                first_invoice_id=key, store_id=key))
            session.add(PromotionInvoiceAllocation(allocation_id=key, invoice_id=key, store_id=key,
                statement_id=key, statement_month="2026-09", settlement_batch_month="2026-09",
                allocated_amount_cent=12345, is_current=False))
            session.add(PromotionInvoiceLifecycleEvent(lifecycle_event_id=key, physical_invoice_id=key,
                invoice_id=key, invoice_version=1, event_type=2, reason="合成系统外作废",
                read_version=1, is_current=True, operator_id="synthetic",
                idempotency_key_hash=f"{index + 1:064x}", request_payload_sha256=f"{index + 3:064x}", occurred_at=now))
        session.commit()
    return factory


@pytest.mark.parametrize("response_status", [200, 401, 403])
def test_candidate_store_change_clears_old_action_while_pending_and_after_denial(
    browser, candidate_stores, live_admin_fastapi_base_url, vite_live_admin_api_base_url,
    response_status, tmp_path,
):
    """Changing only storeId must immediately make A's candidate unavailable."""
    factory = candidate_stores
    models = (PromotionInvoice, PromotionInvoiceAllocation, PromotionInvoiceLifecycleEvent)
    with factory() as session:
        before = tuple(session.scalar(select(func.count()).select_from(model)) for model in models)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    held = []
    try:
        page.goto(vite_live_admin_api_base_url + "/settlement/invoice/status?storeId=R105-SCOPE-A&month=2026-09")
        old_action = page.get_by_role("button", name="重新开票 81050000000000000000", exact=True)
        expect(old_action).to_be_visible(timeout=20000)

        def delay_b(route):
            if parse_qs(urlparse(route.request.url).query).get("storeId") == ["R105-SCOPE-B"]:
                held.append(route)
            else:
                route.continue_()

        page.route("**/promotion-invoices/replacement-candidates?*", delay_b)
        with page.expect_request(lambda request: "/replacement-candidates?" in request.url and "storeId=R105-SCOPE-B" in request.url):
            page.evaluate("history.pushState(null, '', '/settlement/invoice/status?storeId=R105-SCOPE-B&month=2026-09'); dispatchEvent(new PopStateEvent('popstate'))")
        # A DOM read yields to route dispatch without resolving the held API.
        expect(page.get_by_role("heading", name="发票状态查看", exact=True)).to_be_visible()
        assert held, "B candidate request must still be intercepted and pending"
        expect(old_action).to_have_count(0)
        expect(page.get_by_text("81050000000000000000", exact=True)).to_have_count(0)
        candidates = page.get_by_role("region", name="待重新开票", exact=True)
        expect(candidates.get_by_role("status").filter(has_text="正在加载最新数据...")).to_be_visible()
        expect(candidates.get_by_role("status").filter(has_text="正在加载数据...")).to_be_visible()
        page.screenshot(path=tmp_path / "candidate-b-pending.png", full_page=True)
        assert not held[0].request.post_data

        with page.expect_response(lambda response: "/replacement-candidates?" in response.url and "storeId=R105-SCOPE-B" in response.url) as pending:
            route = held.pop()
            if response_status == 200:
                route.continue_()  # The real API supplies every successful byte.
            else:
                route.fulfill(status=response_status, content_type="application/json",
                    json={"detail": {"message": "Synthetic authorization denial"}})
        assert pending.value.status == response_status
        if response_status == 200:
            result = pending.value.json()["data"]["list"]
            assert [item["invoice"]["storeId"] for item in result] == ["R105-SCOPE-B"]
            assert [item["invoice"]["invoiceAmountCent"] for item in result] == [12345]
            expect(page.get_by_role("button", name="重新开票 81050000000000000001", exact=True)).to_be_visible()
        else:
            expect(page.get_by_role("button", name="重新开票 81050000000000000001", exact=True)).to_have_count(0)
            expect(candidates.get_by_role("alert").filter(has_text="数据加载失败，请稍后重试。")).to_be_visible()
            expect(candidates.get_by_role("alert").filter(has_text="数据暂不可用")).to_be_visible()
        expect(old_action).to_have_count(0)
        page.screenshot(path=tmp_path / f"candidate-b-{response_status}.png", full_page=True)
        with factory() as session:
            assert tuple(session.scalar(select(func.count()).select_from(model)) for model in models) == before
            invoices = list(session.scalars(select(PromotionInvoice).where(PromotionInvoice.invoice_id.in_(
                ("R105-SCOPE-A", "R105-SCOPE-B")))))
            assert len(invoices) == 2 and all(not row.is_current and row.invoice_amount_cent == 12345 for row in invoices)
    finally:
        for route in held:
            route.abort()
        context.close()
