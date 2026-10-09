"""Real FastAPI + SQLite + Vite ranking regression; no intercepted API responses.

Only authentication is injected, using the existing live-browser fixture pattern.
The production route builds business snapshots from four isolated source orders.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
import uvicorn
from playwright.sync_api import Browser, expect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from test_visual_smoke import (
    HOST,
    browser,
    find_free_port,
    vite_live_admin_api_base_url,
    wait_for_url,
)
from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.models import (
    Base,
    ClueAssignmentRound,
    ClueFollowUpRecord,
    DimAwemeAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
)
from apps.api.dy_api.ranking_configuration import DATA_START, publish_configuration
from apps.api.dy_api.ranking_schema_v1 import metadata


def seed_ranking_orders(session):
    assigned_at = datetime(2026, 9, 8, 2, tzinfo=timezone.utc)
    session.add(DimStore(store_id="ranking-store", store_name="联调门店", service_store_code="RANKING-TEST", is_active=True))
    session.flush()
    session.add_all([
        DimStorePoiMapping(store_id="ranking-store", poi_id="RANKING-POI", is_primary=True),
        DimAwemeAccount(account_id="ranking-account", store_id="ranking-store", binding_status="active"),
        DimSkuProductRule(sku_id="ranking-sku", product_id="ranking-product", product_scope="精诚养车"),
    ])
    publish_configuration(session, organizations=[dict(
        store_id="ranking-store", service_store_code="RANKING-TEST", store_name="联调门店",
        group_name="联调集团", service_center_name="联调中心", district_name="联调大区", area_name="联调区域",
    )], eligible_codes=["RANKING-TEST"], effective_from=DATA_START)
    for order_id, refund_hour in [("active", None), ("early-refund", 4), ("late-refund", 30), ("late-verify", None)]:
        payload = {} if refund_hour is None else {"certificate": [{
            "item_status": 301,
            "refund_time": int((assigned_at + timedelta(hours=refund_hour)).timestamp()),
        }]}
        session.add(RawDouyinOrder(
            order_id=order_id, sku_id="ranking-sku", owner_account_id="ranking-account",
            sale_time=assigned_at, pay_time=assigned_at,
            order_status="已支付" if refund_hour is None else "退款", raw_payload=payload,
            source_observed_at=assigned_at + timedelta(hours=48),
        ))
        session.add(ClueAssignmentRound(
            assignment_round_id=f"round-{order_id}", order_id=order_id, round_no=1,
            assigned_store_id="ranking-store", assigned_at=assigned_at,
            execution_mode="formal", round_status="active_unfollowed",
        ))
    session.add(ClueFollowUpRecord(
        follow_up_record_id="manual-action", order_id="active", assignment_round_id="round-active",
        round_no=1, assigned_store_id="ranking-store", follow_result="connected",
        created_at=assigned_at + timedelta(hours=2),
    ))
    session.flush()
    session.add(RawDouyinOrderCoupon(coupon_id="late-coupon", order_id="late-verify"))
    session.flush()
    session.add(RawDouyinVerifyRecord(
        verify_id="late-verification", coupon_id="late-coupon", poi_id="RANKING-POI",
        sku_id="ranking-sku", verify_status="success", verify_time=assigned_at + timedelta(hours=30),
    ))
    session.commit()


@pytest.fixture(scope="session")
def live_admin_fastapi_base_url(tmp_path_factory):
    """Override only this module's backend; reuse the existing Vite fixture."""
    database_path = tmp_path_factory.mktemp("ranking-live-api") / "ranking.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as session:
        seed_ranking_orders(session)
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("DY_API_CORS_ORIGINS", "*")
        environment.setenv("DY_API_TEST_MODE", "true")
        app = create_app()

        def current_user():
            return AuthContext(user_id="ranking-browser", username="ranking-browser", display_name="Ranking QA",
                role="admin", store_ids=(), auth_type="env_admin", store_scope_mode="all", page_keys=("A03",))

        def session_dependency():
            with factory() as session:
                yield session

        app.dependency_overrides[get_current_user] = current_user
        app.dependency_overrides[get_session_dependency] = session_dependency
        port = find_free_port()
        server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base_url = f"http://{HOST}:{port}"
        try:
            wait_for_url(f"{base_url}/docs")
            yield base_url
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            app.dependency_overrides.clear()
            engine.dispose()


@pytest.mark.parametrize("width", [1440, 390])
def test_ranking_live_api_independent_follow_rates_and_empty_filter(
    browser: Browser, vite_live_admin_api_base_url, live_admin_fastapi_base_url, tmp_path, width,
):
    context = browser.new_context(viewport={"width": width, "height": 1000}, has_touch=width == 390)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    def ranking_response(response):
        return response.url.startswith(f"{live_admin_fastapi_base_url}/api/v1/dashboard/douyin-ranking?")
    try:
        with page.expect_response(ranking_response) as received:
            page.goto(f"{vite_live_admin_api_base_url}/metrics/douyin-ranking?periodStart=2026-09-07&periodEnd=2026-09-10", wait_until="domcontentloaded")
        response = received.value
        assert response.status == 200, response.text()
        data = response.json()["data"]
        assert data["dataMode"] == "business"
        assert data["snapshotId"].startswith("business-")
        assert data["total"] == 1
        for metrics in (data["totals"], data["rows"][0]):
            assert (metrics["followNumerator"], metrics["followDenominator"]) == (1, 3)
            assert metrics["follow24hRate"] == pytest.approx(1 / 3, abs=1e-6)
            assert (metrics["followAnyNumerator"], metrics["followAnyDenominator"], metrics["followRate"]) == (2, 2, 1)
            assert (metrics["followActionNumerator"], metrics["followActionDenominator"], metrics["followActionRate"]) == (1, 4, .25)
        card = page.locator(".metric-card").filter(has_text="线索24小时有效跟进率")
        expect(card).to_contain_text("33.33%")
        expect(card).to_contain_text("有效 1 / 分配 3")
        expect(card).to_contain_text("100%（2/2）")
        expect(card).to_contain_text("25%（1/4）")
        row = page.locator("tbody tr").first if width == 1440 else page.locator(".data-table-mobile-card").first
        expect(row).to_contain_text("33.33%（1/3）")
        expect(row).to_contain_text("100%（2/2）")
        expect(row).to_contain_text("25%（1/4）")
        help_button = row.get_by_role("button", name="跟进动作率口径说明", exact=True)
        if width == 390:
            help_button.tap()
        else:
            help_button.focus()
        tooltip = page.locator('[role="tooltip"]:popover-open')
        expect(tooltip).to_contain_text("系统自动核销不算人工动作")
        page.keyboard.press("Escape")
        expect(tooltip).to_have_count(0)
        page.screenshot(path=str(tmp_path / f"ranking-live-{width}.png"), full_page=True)
        with page.expect_response(ranking_response) as empty_received:
            page.get_by_label("集团", exact=True).fill("不存在的联调集团")
        assert empty_received.value.status == 200
        empty = empty_received.value.json()["data"]
        assert empty["total"] == 0
        assert empty["rows"] == []
        for rate_key, denominator_key in [("follow24hRate", "followDenominator"), ("followRate", "followAnyDenominator"), ("followActionRate", "followActionDenominator")]:
            assert empty["totals"][rate_key] is None
            assert empty["totals"][denominator_key] == 0
        expect(page.get_by_text("当前统计范围没有可展示数据，请检查筛选范围及快照更新状态。", exact=True)).to_be_visible()
        expect(card.locator(".metric-card__value")).to_have_text("暂无样本")
        expect(card.locator(".ranking-follow-auxiliary small").nth(0)).to_contain_text("暂无样本（0/0）")
        expect(card.locator(".ranking-follow-auxiliary small").nth(1)).to_contain_text("暂无样本（0/0）")
        assert not errors
    finally:
        context.close()
