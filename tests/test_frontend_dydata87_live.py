"""Isolated HTTP/browser checks; no production facts or shared fixture edits."""
import os
import threading
from datetime import datetime, timezone

import pytest
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from playwright.sync_api import expect
from apps.api.dy_api.models import AggStoreMonthlySettlement

from test_visual_smoke import (
    browser, vite_live_admin_api_base_url, find_free_port, wait_for_url,
    create_app, get_current_user, get_session_dependency, AuthContext,
    ALL_PAGE_KEYS, Base, DimStore, SettlementStatement,
)


@pytest.fixture(scope="session")
def live_admin_fastapi_base_url(tmp_path_factory):
    # Reuse the existing Vite/browser harness, but own all database state here.
    previous = os.environ.get("DY_API_CORS_ORIGINS")
    os.environ["DY_API_CORS_ORIGINS"] = "*"
    database_path = tmp_path_factory.mktemp("r87-browser") / "isolated.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as session:
        session.add(DimStore(store_id="r87-store", store_name="R87 isolated store", is_active=True))
        session.add(AggStoreMonthlySettlement(month="2026-08", store_id="r87-store",
                                             product_scope="all", product_type="all"))
        session.add(SettlementStatement(
            statement_id="r87-bill", store_id="r87-store", statement_month="2026-08",
            version_no=1, is_current=True, statement_status=1,
            promotion_original_fee_cent=10600, promotion_adjustment_fee_cent=0,
            promotion_net_fee_cent=10600, management_original_fee_cent=10600,
            management_adjustment_fee_cent=0, management_net_fee_cent=10600,
            created_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        ))
        session.commit()
    app = create_app()
    def user():
        return AuthContext(user_id="r87-user", username="r87-user", display_name="R87",
                           role="admin", store_ids=(), auth_type="env_admin",
                           store_scope_mode="all", page_keys=tuple(ALL_PAGE_KEYS))
    def database():
        with factory() as session:
            yield session
    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_session_dependency] = database
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for_url(f"{url}/docs")
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()
        if previous is None:
            os.environ.pop("DY_API_CORS_ORIGINS", None)
        else:
            os.environ["DY_API_CORS_ORIGINS"] = previous


def test_confirm_register_conflict_and_query_context(browser, vite_live_admin_api_base_url,
                                                    live_admin_fastapi_base_url):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        page.goto(f"{vite_live_admin_api_base_url}/settlement?storeId=r87-store&month=2026-08")
        confirm = page.get_by_role("button", name="确认推广服务费", exact=True)
        expect(confirm).to_be_enabled(timeout=20000)
        confirm.click()
        with page.expect_response(lambda response: response.request.method == "POST"
                                  and "/confirmations" in response.url) as confirmation:
            page.get_by_role("button", name="确认提交", exact=True).click()
        assert confirmation.value.status == 200, confirmation.value.text()
        page.get_by_role("link", name="进入推广费开票").click()
        expect(page.get_by_label("购买方名称")).to_be_visible(timeout=15000)
        expect(page.locator(".store-finance-invoice-info")).to_contain_text("106.00", timeout=15000)
        page.get_by_label("购买方名称").fill("比亚迪汽车销售有限公司")
        page.get_by_label("填写人电话").fill("13800000000")
        page.get_by_label("税率", exact=True).fill("6")
        page.get_by_label("开票日期").fill("2026-08-08")
        page.get_by_label("20 位数电专票号码").fill("12345678901234567890")
        page.get_by_label("不含税金额", exact=True).fill("100")
        page.get_by_label("税额", exact=True).fill("6")
        page.get_by_label("价税合计", exact=True).fill("106")

        # Trigger a genuine server version conflict, not a fabricated response.
        def stale_version(route):
            payload = route.request.post_data_json
            for allocation in payload["allocations"]:
                allocation["readVersion"] += 1
            import json
            route.continue_(post_data=json.dumps(payload))
        page.route("**/api/v1/promotion-invoices", stale_version)
        with page.expect_response(lambda response: response.request.method == "POST"
                                  and response.url.endswith("/promotion-invoices")) as registration:
            page.get_by_role("button", name="核验并登记发票").click()
        assert registration.value.status == 409, registration.value.text()
        expect(page.get_by_label("20 位数电专票号码")).to_have_value("12345678901234567890")
        records = context.request.get(f"{live_admin_fastapi_base_url}/api/v1/promotion-invoices",
                                      params={"storeId": "r87-store", "month": "2026-08"})
        assert records.status == 200
        assert records.json()["data"]["list"] == []
        page.unroute("**/api/v1/promotion-invoices", stale_version)
        with page.expect_response(lambda response: "/store-invoice-status" in response.url) as query:
            page.goto(f"{vite_live_admin_api_base_url}/settlement/invoice/status?storeId=r87-store&month=2026-08")
        assert query.value.status == 200, query.value.text()
        assert "storeId=r87-store" in query.value.url
        assert "month=2026-08" in query.value.url
    finally:
        context.close()
