"""Real FastAPI + Chromium regression for independent month/cumulative readiness.

The database and collection evidence are synthetic and isolated. HTTP readers,
publication pinning, React pages and shared selection controls are production code.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from unittest.mock import patch

import pytest
import uvicorn
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from test_visual_smoke import browser, find_free_port, stop_process_tree, wait_for_url
from test_dashboard_publication_browser import WEB
from publication_fixture_helpers import publish_fixture, ready_periods_fixture
from dy_api.access_control import ALL_PAGE_KEYS
from dy_api.auth import AuthContext, get_current_user
from dy_api.db import Base
from dy_api.main import create_app
from dy_api.models import (
    DimStore, SettlementMonthlyOverlay, SettlementProjectionActive,
    SettlementProjectionGeneration, SettlementProjectionPartitionManifest,
    SettlementRankingOverlay, SettlementStatement,
)
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.dashboard_publications import finance


@pytest.fixture(scope="module")
def availability_api(request, tmp_path_factory):
    complete = request.param == "complete"
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path_factory.mktemp('monthly-availability') / 'db.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as session:
        session.add(SettlementProjectionGeneration(generation_id="monthly-source", state="published",
                                                   input_fingerprint="monthly-availability"))
        session.flush()
        session.add(SettlementProjectionActive(projection_name="settlement", generation_id="monthly-source"))
        for kind, partition in (("monthly", "2026-09"), ("ranking", "monthly:2026-09"),
                                ("ranking", "cumulative:2026-09")):
            session.add(SettlementProjectionPartitionManifest(generation_id="monthly-source", artifact=kind,
                partition_key=partition, source_kind="overlay", data_generation_id="monthly-source"))
        for store_id, amount in (("fee-store", 12345), ("zero-store", 0)):
            session.add(DimStore(store_id=store_id, store_name=store_id, is_active=True))
            session.add(SettlementMonthlyOverlay(generation_id="monthly-source", partition_key="2026-09",
                month="2026-09", store_id=store_id, product_scope="all", product_type="all",
                promotion_net_fee_cent=amount, management_net_fee_cent=amount))
            for period_type, partition in ((1, "monthly:2026-09"), (2, "cumulative:2026-09")):
                session.add(SettlementRankingOverlay(generation_id="monthly-source", partition_key=partition,
                    period_type=period_type, period_key="2026-09", month="2026-09", store_id=store_id,
                    store_name=store_id, promotion_net_fee_cent=amount, management_net_fee_cent=amount))
            session.add(SettlementStatement(statement_id=f"bill-{store_id}", store_id=store_id,
                statement_month="2026-09", version_no=1, is_current=True, statement_status=1,
                promotion_original_fee_cent=amount, promotion_net_fee_cent=amount,
                management_original_fee_cent=amount, management_net_fee_cent=amount))

        def build_with_evidence(session, publication_id, cutoff):
            evidence = ready_periods_fixture(session, cutoff)
            evidence["months"]["2026-08"]["ready"] = complete
            with patch.object(finance.period_readiness, "capture", return_value=evidence):
                return finance.build_settlement(session, publication_id, cutoff)

        publication = publish_fixture(session, "settlement", builder=build_with_evidence)
    previous = os.environ.get("DY_API_CORS_ORIGINS")
    os.environ["DY_API_CORS_ORIGINS"] = "*"
    app = create_app()

    def user():
        return AuthContext(user_id="monthly-ui", username="monthly-ui", display_name="Monthly UI",
            role="admin", store_ids=(), store_scope_mode="all", auth_type="env_admin",
            page_keys=tuple(ALL_PAGE_KEYS))

    def database():
        with factory() as session:
            yield session

    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_session_dependency] = database
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for_url(f"{url}/docs")
        yield url, publication.id
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()
        if previous is None:
            os.environ.pop("DY_API_CORS_ORIGINS", None)
        else:
            os.environ["DY_API_CORS_ORIGINS"] = previous


@pytest.fixture(scope="module")
def availability_web(availability_api, tmp_path_factory):
    port = find_free_port()
    with (tmp_path_factory.mktemp("monthly-vite") / "vite.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
             "--host", "127.0.0.1", "--port", str(port), "--strictPort"], cwd=WEB,
            env={**os.environ, "VITE_USE_MOCKS": "false", "VITE_API_BASE_URL": f"{availability_api[0]}/api/v1"},
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        url = f"http://127.0.0.1:{port}"
        try:
            wait_for_url(url)
            yield url
        finally:
            stop_process_tree(process)


def metric(page, label):
    return page.locator(".metric-card").filter(has=page.locator(".metric-card__label", has_text=label))


@pytest.mark.parametrize("availability_api", ["mixed"], indirect=True)
@pytest.mark.parametrize("viewport", [(390, 844), (768, 1024), (1440, 1000)])
def test_month_ready_pages_show_fees_nulls_and_keep_billing_actions(
    browser, availability_web, availability_api, tmp_path, viewport,
):
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        with page.expect_response(lambda r: "/store-ranking?" in r.url) as response:
            page.goto(f"{availability_web}/ranking?periodKey=2026-09")
        assert response.value.status == 200
        data = response.value.json()["data"]
        assert data["periodAvailability"] == {
            "monthlyReady": True, "cumulativeReady": False, "incompleteMonths": ["2026-08"],
        }
        assert data["totals"]["promotionMonthFeeCent"] == 12345
        assert data["totals"]["promotionCumulativeFeeCent"] is None
        expect(metric(page, "当期推广服务费")).to_contain_text("123.45")
        expect(metric(page, "累计推广服务费")).to_contain_text("暂不可用")
        expect(metric(page, "销售金额（累计）")).to_contain_text("暂不可用")
        expect(metric(page, "销售金额（累计）")).not_to_contain_text("0.00")
        expect(page.get_by_role("status").filter(has_text="本月数据已完整")).to_contain_text("2026-08")
        expect(page.locator("tbody tr").filter(has_text="fee-store")).to_contain_text("暂不可用")
        page.get_by_role("button", name="排行依据", exact=True).click()
        expect(page.get_by_role("option", name="累计推广服务费", exact=True)).to_be_disabled()
        expect(page.get_by_role("option", name="当期推广服务费", exact=True)).to_be_enabled()
        page.keyboard.press("Escape")
        page.get_by_role("button", name="统计方式", exact=True).click()
        expect(page.get_by_role("option", name="正式累计", exact=True)).to_be_disabled()
        page.keyboard.press("Escape")
        page.screenshot(path=str(tmp_path / "monthly-ranking-partial-cumulative.png"))

        with page.expect_response(lambda r: "/monthly-settlement?" in r.url) as response:
            page.goto(f"{availability_web}/settlement?storeId=fee-store&month=2026-09")
        assert response.value.status == 200
        assert response.value.json()["data"]["computedCumulative"] == {
            "promotionNetFeeCent": None, "managementNetFeeCent": None,
        }
        for label in ("当期推广服务费", "当期管理服务费"):
            expect(metric(page, label)).to_contain_text("123.45")
        for label in ("累计推广服务费", "累计管理服务费"):
            expect(metric(page, label)).to_contain_text("暂不可用")
        expect(page.get_by_role("button", name="确认推广服务费", exact=True)).to_be_enabled()
        expect(page.get_by_role("button", name="确认管理服务费", exact=True)).to_be_enabled()
        expect(page.get_by_role("button", name="发起账单异议", exact=True)).to_be_enabled()
        page.screenshot(path=str(tmp_path / "monthly-settlement-partial-cumulative.png"))
        assert errors == []
    finally:
        context.close()


@pytest.mark.parametrize("availability_api", ["mixed"], indirect=True)
def test_unsupported_cumulative_deep_link_recovers_to_monthly_on_same_publication(
    browser, availability_web, availability_api,
):
    context = browser.new_context()
    page = context.new_page()
    try:
        with page.expect_response(lambda r: "/store-ranking?" in r.url) as response:
            page.goto(f"{availability_web}/ranking?periodKey=2026-09&rankingBasis=PROMOTION_FEE_CUMULATIVE")
        assert response.value.status == 503
        assert response.value.json()["error"]["code"] == "PUBLICATION_PERIOD_NOT_READY"
        expect(page.get_by_role("alert").filter(has_text="所选账期尚未完成")).to_be_visible()
        basis = page.get_by_role("button", name="排行依据", exact=True)
        expect(basis).to_be_enabled()
        basis.click()
        with page.expect_response(lambda r: "/store-ranking?" in r.url and "periodType=MONTHLY" in r.url) as response:
            page.get_by_role("option", name="当期推广服务费", exact=True).click()
        assert response.value.status == 200
        assert response.value.json()["meta"]["publication"]["id"] == availability_api[1]
        assert "rankingBasis=PROMOTION_FEE_MONTH" in response.value.url
        expect(metric(page, "当期推广服务费")).to_contain_text("123.45")
        expect(page.get_by_role("button", name="统计方式", exact=True)).to_contain_text("月度")
        expect(page.get_by_role("alert")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.parametrize("availability_api", ["complete"], indirect=True)
def test_complete_prefix_keeps_numeric_zero_and_cumulative_switching(browser, availability_web):
    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(f"{availability_web}/ranking?periodKey=2026-09")
        expect(metric(page, "累计推广服务费")).to_contain_text("123.45")
        expect(page.locator("tbody tr").filter(has_text="zero-store")).to_contain_text("0.00")
        expect(page.get_by_text("暂不可用", exact=True)).to_have_count(0)
        page.get_by_role("button", name="排行依据", exact=True).click()
        with page.expect_response(lambda r: "/store-ranking?" in r.url and "periodType=CUMULATIVE" in r.url) as response:
            page.get_by_role("option", name="累计推广服务费", exact=True).click()
        assert response.value.status == 200
        expect(metric(page, "累计推广服务费")).to_contain_text("123.45")
        page.goto(f"{availability_web}/settlement?storeId=zero-store&month=2026-09")
        expect(metric(page, "累计推广服务费")).to_contain_text("0.00")
        expect(metric(page, "累计管理服务费")).to_contain_text("0.00")
        expect(page.get_by_text("暂不可用", exact=True)).to_have_count(0)
    finally:
        context.close()
