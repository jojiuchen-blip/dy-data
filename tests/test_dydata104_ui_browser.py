"""DYDATA-104 production UI + real isolated FastAPI download/month contracts.

Only the explicit 500/network fault branches intercept requests. Successful
downloads, permission denials and retries execute the real API implementation.
The component entry also covers the legacy SKU governance panel without adding
a product route. Test authentication injection does not validate real login.
"""
from __future__ import annotations

import os
import threading
import csv
import re
from datetime import datetime
from io import StringIO
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
import uvicorn
from fastapi import Request
from playwright.sync_api import expect
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker

from test_visual_smoke import (  # reuse lifecycle helpers, not shared state
    browser, find_free_port, stop_process_tree, wait_for_url,
)
from test_dashboard_publication_browser import WEB
from publication_fixture_helpers import publish_fixture
from apps.api.dy_api.dashboard_publications.fee_trial import rows as trial_rows
from apps.api.dy_api.dashboard_publications.finance import build_settlement, dimensions
from dy_api.access_control import ALL_PAGE_KEYS
from dy_api.auth import AuthContext, get_current_user
from dy_api.db import Base
from dy_api.main import create_app
from dy_api.models import (
    DimStore, SettlementProjectionActive, SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest, SettlementMonthlyOverlay, SettlementStatement,
)
from dy_api.routes._data import get_session_dependency


@pytest.fixture(scope="module")
def dy104_api(tmp_path_factory):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path_factory.mktemp('ui104') / 'db.sqlite3'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def settlement_with_october_trial(session, publication_id, cutoff):
        stats = build_settlement(session, publication_id, cutoff)
        session.execute(insert(dimensions).values(publication_id=publication_id,
            kind="fee_trial", key="2026-10", value={
                "schema_version": 1, "scope_unresolved": True,
                "source_success_days": 31, "source_total_days": 31,
            }))
        session.execute(insert(trial_rows), [
            dict(publication_id=publication_id, row_id=f"trial-{direction}", month="2026-10",
                fee_direction=direction, coupon_id="trial-coupon", order_id="trial-order",
                store_id="ui104-store", store_name="月度合成门店", product_type="精诚养车",
                fee_amount_cent=45600, base_amount_cent=456000, fee_rate="0.10",
                record_status="CALCULATED", search_text="月度合成门店 trial-coupon")
            for direction in (1, 2)
        ])
        return stats

    with factory() as session:
        session.add(DimStore(store_id="ui104-store", store_name="月度合成门店", is_active=True))
        session.add(SettlementProjectionGeneration(generation_id="ui104-source", state="published",
                                                  input_fingerprint="ui104"))
        session.flush()
        session.add(SettlementProjectionActive(projection_name="settlement", generation_id="ui104-source"))
        for month, amount in (("2026-08", 12300), ("2026-09", 0), ("2026-10", 45600)):
            session.add(SettlementProjectionPartitionManifest(generation_id="ui104-source", artifact="monthly",
                partition_key=month, source_kind="overlay", data_generation_id="ui104-source"))
            session.add(SettlementMonthlyOverlay(generation_id="ui104-source", partition_key=month,
                month=month, store_id="ui104-store", product_scope="all", product_type="all",
                promotion_net_fee_cent=amount, management_net_fee_cent=amount))
        session.add(SettlementStatement(statement_id="ui104-bill-september", store_id="ui104-store",
            statement_month="2026-09", version_no=1, is_current=True, statement_status=2))
        session.commit()
        publish_fixture(session, "settlement", builder=settlement_with_october_trial)
        publish_fixture(session, "finance")
    previous = os.environ.get("DY_API_CORS_ORIGINS")
    os.environ["DY_API_CORS_ORIGINS"] = "*"
    app = create_app()

    def user(request: Request):
        role = request.cookies.get("dy104_role", "admin")
        return AuthContext(user_id="ui104", username="ui104", display_name="UI104", role=role,
            store_ids=(), auth_type="user" if role == "store" else "env_admin", page_keys=tuple(ALL_PAGE_KEYS))

    def session_dependency():
        with factory() as session:
            yield session

    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_session_dependency] = session_dependency
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    api = f"http://127.0.0.1:{port}"
    try:
        wait_for_url(f"{api}/docs")
        yield api
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()
        if previous is None:
            os.environ.pop("DY_API_CORS_ORIGINS", None)
        else:
            os.environ["DY_API_CORS_ORIGINS"] = previous


@pytest.fixture(scope="module")
def dy104_web(dy104_api, tmp_path_factory):
    import shutil
    import subprocess

    port = find_free_port()
    log_path = tmp_path_factory.mktemp("ui104-vite") / "vite.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
            "--host", "127.0.0.1", "--port", str(port), "--strictPort"], cwd=WEB,
            env={**os.environ, "VITE_USE_MOCKS": "false", "VITE_API_BASE_URL": f"{dy104_api}/api/v1"},
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        url = f"http://127.0.0.1:{port}"
        try:
            wait_for_url(url)
            yield url
        finally:
            stop_process_tree(process)


@pytest.fixture(scope="module")
def dy104_batch(browser, dy104_api):
    context = browser.new_context()
    try:
        response = context.request.post(f"{dy104_api}/api/v1/admin/sku-fee-rule-imports", multipart={
            "file": {"name": "ui104-errors.csv", "mimeType": "text/csv",
                     "buffer": b"invalidHeader\ninvalid-row\n"}, "effectiveDate": "2026-08-01"})
        assert response.ok, response.text()
        batch = response.json()["data"]["batch"]
        assert batch["hasResultFile"]
        return batch
    finally:
        context.close()


def open_surface(page, web, surface, query=""):
    page.clock.set_fixed_time("2026-10-20T02:00:00Z")
    page.goto(f"{web}/tests/dydata104.html?surface={surface}{query}")
    expect(page).to_have_title("DYDATA-104 UI contracts")
    # Dialog renders into a body portal and deliberately leaves #root empty.
    expect(page.get_by_role("button").first).to_be_visible()
    expect(page.locator("vite-error-overlay")).to_have_count(0)


@pytest.mark.parametrize(("direction", "title"), [
    ("PROMOTION", "推广服务费"), ("MANAGEMENT", "管理服务费"),
])
def test_dy104_finance_can_read_and_export_trial_without_october_bills(browser, dy104_web, tmp_path, direction, title):
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    try:
        open_surface(page, dy104_web, "finance", f"&month=2026-10&feeDirection={direction}")
        button = page.get_by_role("button", name="查看内部试算", exact=True)
        expect(button).to_be_visible()
        with page.expect_response(lambda res: "/finance/trial?" in res.url) as response:
            button.click()
        publication_id = response.value.json()["meta"]["publication"]["id"]
        panel = page.get_by_role("region", name="内部月度试算")
        expect(panel.get_by_role("heading", name=f"2026-10 {title}内部试算")).to_be_visible()
        expect(panel.get_by_role("cell", name="月度合成门店")).to_be_visible()
        expect(panel.locator(".metric-card").filter(has_text="已算试算费用")).to_contain_text("456.00")
        with page.expect_download() as result:
            panel.get_by_role("button", name="导出内部试算明细", exact=True).click()
        download = result.value
        assert download.suggested_filename.startswith(f"{title}内部试算_2026-10")
        saved = tmp_path / download.suggested_filename
        download.save_as(saved)
        records = list(csv.DictReader(StringIO(saved.read_text(encoding="utf-8-sig"))))
        assert [(row["试算版本"], row["试算费用（元）"]) for row in records] == [(publication_id, "456.00")]
    finally:
        context.close()


def test_dy104_default_previous_month_and_real_month_switches(browser, dy104_web, tmp_path):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        with page.expect_response(lambda response: "/monthly-settlement?" in response.url
                                  and "month=2026-09" in response.url, timeout=20000) as initial:
            open_surface(page, dy104_web, "settlement")
        assert initial.value.json()["data"]["month"] == "2026-09"
        expect(page.get_by_role("heading", name="单店分账", exact=True)).to_be_visible()
        month_control = page.get_by_role("button", name="账期", exact=True)
        expect(month_control).to_contain_text("2026-09")
        expect(page.locator(".metric-card").filter(has_text="当期推广服务费")).to_contain_text("0.00")
        for month, amount in (("2026-08", 12300), ("2026-09", 0), ("2026-10", 45600), ("2026-08", 12300)):
            month_control.click()
            with page.expect_response(lambda response: "/monthly-settlement?" in response.url
                                      and f"month={month}" in response.url) as received:
                page.get_by_role("option", name=month, exact=True).click()
            data = received.value.json()["data"]
            assert data["month"] == month
            assert data["metrics"]["promotionNetFeeCent"] == amount
            expect(month_control).to_contain_text(month)
            expect(page.locator(".metric-card").filter(has_text="当期推广服务费")).to_contain_text(f"{amount / 100:,.2f}")
        open_surface(page, dy104_web, "settlement", "&month=2026-10")
        expect(month_control).to_contain_text("2026-10")
        expect(page.locator(".metric-card").filter(has_text="当期推广服务费")).to_contain_text("456.00")
        page.screenshot(path=str(tmp_path / "explicit-october.png"))
    finally:
        context.close()


def test_dydata104_store_page_displays_published_bill_window(browser, dy104_web):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        with page.expect_response(lambda response: "/store-settlements?" in response.url
                                  and "month=2026-09" in response.url) as received:
            open_surface(page, dy104_web, "settlement")
        response = received.value
        assert response.ok, response.text()
        statement = response.json()["data"]["list"][0]
        first = datetime.fromisoformat(statement["firstVisibleAt"])
        due = datetime.fromisoformat(statement["confirmationDueAt"])
        shanghai = ZoneInfo("Asia/Shanghai")
        window = page.get_by_text("版本 1 ·", exact=False)
        expect(window).to_contain_text(first.astimezone(shanghai).strftime("%Y-%m-%d %H:%M") + " 起可核对")
        expect(window).to_contain_text("最早 " + due.astimezone(shanghai).strftime("%Y-%m-%d %H:%M") + " 自动确认")
        page.get_by_role("button", name="账期", exact=True).click()
        with page.expect_response(lambda response: "/store-settlements?" in response.url
                                  and "month=2026-08" in response.url):
            page.get_by_role("option", name="2026-08", exact=True).click()
        expect(window).to_have_count(0)
    finally:
        context.close()


DOWNLOADS = [
    ("product", "下载模板", "/admin/sku-product-imports/template", "SKU商品分类导入模板.csv"),
    ("drawer", "下载标准模板", "/admin/sku-fee-rule-imports/template", "SKU服务费率导入模板.csv"),
    ("drawer", "下载结果文件", "result", "SKU费率导入结果_{batch_id}.csv"),
    ("governance", "下载标准模板", "/admin/sku-fee-rule-imports/template", "SKU服务费率导入模板.csv"),
    ("governance", "下载结果文件", "result", "SKU费率导入结果_{batch_id}.csv"),
]

PRODUCT_FIELDS = ["SKU ID", "商品类型"]
FEE_FIELDS = ["SKU名称", "SKU ID", "推广服务费率", "管理服务费率"]
RESULT_FIELDS = FEE_FIELDS + ["校验状态", "错误字段", "错误说明", "生成规则版本"]


def prepare_download(page, web, surface):
    open_surface(page, web, surface)
    if surface == "product":
        page.get_by_role("button", name="批量导入", exact=True).click()
    elif surface == "governance":
        page.get_by_role("button").filter(has_text="ui104-errors.csv").click()


@pytest.mark.parametrize("surface,label,endpoint,filename", DOWNLOADS)
def test_dy104_download_real_bytes_filename_and_busy(browser, dy104_web, dy104_api, dy104_batch,
                                                    surface, label, endpoint, filename, tmp_path):
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    endpoint = f"/admin/sku-fee-rule-imports/{dy104_batch['batchId']}/result-file" if endpoint == "result" else endpoint
    filename = filename.format(batch_id=dy104_batch["batchId"])
    try:
        prepare_download(page, dy104_web, surface)
        button = page.get_by_role("button", name=label, exact=True)
        # Hold a real API response in transit to verify duplicate-click protection.
        pending = []
        pattern = re.compile(rf"^https?://[^/]+/api/v1{re.escape(endpoint)}(?:\?.*)?$")
        page.route(pattern, lambda route: pending.append(route))
        button.click()
        expect(button).to_be_disabled()
        page.wait_for_timeout(100)
        button.evaluate("button => button.click()")
        assert len(pending) == 1
        assert parse_qs(urlsplit(pending[0].request.url).query)["locale"] == ["zh-CN"]
        actual = pending[0].fetch()
        assert actual.ok, actual.text()
        expected = actual.body()
        with page.expect_download() as download:
            pending[0].fulfill(response=actual)
        assert download.value.suggested_filename == filename
        path = tmp_path / filename
        download.value.save_as(path)
        assert path.read_bytes() == expected
        rows = list(csv.reader(StringIO(expected.decode("utf-8-sig"))))
        assert rows[0] == (RESULT_FIELDS if endpoint.endswith("result-file") else
                           PRODUCT_FIELDS if surface == "product" else FEE_FIELDS)
        if endpoint.endswith("result-file"):
            assert len(rows) == 2
            assert rows[1][4:6] == ["校验失败", "template"]
            assert "四个标准业务列" in rows[1][6]
        else:
            assert len(rows) == 1
        expect(button).to_be_enabled()
        expect(page.get_by_role("status").filter(has_text="已下载")).to_be_visible()
        assert errors == []
        page.screenshot(path=str(tmp_path / f"{surface}-{label}.png"))
    finally:
        context.close()


@pytest.mark.parametrize("surface,label,endpoint,filename", DOWNLOADS)
@pytest.mark.parametrize("fault", ["403", "500", "network"])
def test_dy104_download_errors_are_visible_and_retry_real_api(browser, dy104_web, dy104_api,
        dy104_batch, surface, label, endpoint, filename, fault, tmp_path):
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    errors = []
    failed_statuses = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda response: failed_statuses.append(response.status)
            if response.status >= 400 and "/api/v1/admin/sku-" in response.url else None)
    endpoint = f"/admin/sku-fee-rule-imports/{dy104_batch['batchId']}/result-file" if endpoint == "result" else endpoint
    filename = filename.format(batch_id=dy104_batch["batchId"])
    try:
        prepare_download(page, dy104_web, surface)
        button = page.get_by_role("button", name=label, exact=True)
        pattern = re.compile(rf"^https?://[^/]+/api/v1{re.escape(endpoint)}(?:\?.*)?$")
        if fault == "403":
            context.add_cookies([{"name": "dy104_role", "value": "store", "url": dy104_api}])
        else:
            page.route(pattern, lambda route: route.abort() if fault == "network" else
                       route.fulfill(status=500, json={"detail": "Synthetic server failure"}))
        button.click()
        expect(page.get_by_role("alert").filter(has_text="下载失败")).to_be_visible()
        if fault == "403":
            assert 403 in failed_statuses
            expect(page.get_by_role("alert")).to_contain_text("没有执行此操作的权限")
        elif fault == "500":
            assert 500 in failed_statuses
            expect(page.get_by_role("alert")).to_contain_text("服务暂时不可用")
        else:
            expect(page.get_by_role("alert")).to_contain_text("网络连接异常")
        expect(button).to_be_enabled()
        page.unroute(pattern)
        context.clear_cookies()
        expected = context.request.get(f"{dy104_api}/api/v1{endpoint}", params={"locale": "zh-CN"})
        assert expected.ok
        with page.expect_download() as download:
            button.click()
        assert download.value.suggested_filename == filename
        path = tmp_path / filename
        download.value.save_as(path)
        assert path.read_bytes() == expected.body()
        expect(page.get_by_role("alert").filter(has_text="下载失败")).to_have_count(0)
        expect(page.get_by_role("status").filter(has_text="已下载")).to_be_visible()
        assert errors == []
    finally:
        context.close()
