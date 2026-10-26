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
from io import StringIO

import pytest
import uvicorn
from fastapi import Request
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from test_visual_smoke import (  # reuse lifecycle helpers, not shared state
    browser, find_free_port, stop_process_tree, wait_for_url,
)
from test_dashboard_publication_browser import WEB
from publication_fixture_helpers import publish_fixture
from dy_api.access_control import ALL_PAGE_KEYS
from dy_api.auth import AuthContext, get_current_user
from dy_api.db import Base
from dy_api.main import create_app
from dy_api.models import (
    DimStore, SettlementProjectionActive, SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest, SettlementMonthlyOverlay,
)
from dy_api.routes._data import get_session_dependency


@pytest.fixture(scope="module")
def dy104_api(tmp_path_factory):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path_factory.mktemp('ui104') / 'db.sqlite3'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
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
        session.commit()
        publish_fixture(session, "settlement")
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


def test_dy104_default_previous_month_and_real_month_switches(browser, dy104_web, tmp_path):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    responses = []
    page.on("response", lambda response: responses.append(response)
            if "/monthly-settlement?" in response.url else None)
    try:
        open_surface(page, dy104_web, "settlement")
        expect(page.get_by_role("heading", name="单店分账", exact=True)).to_be_visible()
        month_control = page.get_by_role("button", name="账期", exact=True)
        expect(month_control).to_contain_text("2026-09")
        expect(page.locator(".metric-card").filter(has_text="当期推广服务费")).to_contain_text("0.00")
        assert responses[0].json()["data"]["month"] == "2026-09"
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


DOWNLOADS = [
    ("product", "下载模板", "/admin/sku-product-imports/template", "sku-product-template.csv"),
    ("drawer", "下载标准模板", "/admin/sku-fee-rule-imports/template", "sku-fee-rule-template.csv"),
    ("drawer", "下载结果文件", "result", "ui104-errors-result.csv"),
    ("governance", "下载标准模板", "/admin/sku-fee-rule-imports/template", "sku-fee-rule-template.csv"),
    ("governance", "下载结果文件", "result", "ui104-errors-result.csv"),
]

PRODUCT_FIELDS = ["skuId", "productType"]
FEE_FIELDS = ["skuName", "skuId", "promotionServiceFeeRate", "managementServiceFeeRate"]
RESULT_FIELDS = FEE_FIELDS + ["validationStatus", "errorFields", "errorMessages", "createdRuleVersion"]


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
    try:
        prepare_download(page, dy104_web, surface)
        button = page.get_by_role("button", name=label, exact=True)
        # Hold a real API response in transit to verify duplicate-click protection.
        pending = []
        page.route(f"**/api/v1{endpoint}", lambda route: pending.append(route))
        button.click()
        expect(button).to_be_disabled()
        page.wait_for_timeout(100)
        button.evaluate("button => button.click()")
        assert len(pending) == 1
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
            assert rows[1][4:6] == ["INVALID", "template"]
            assert "四个标准业务列" in rows[1][6]
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
    try:
        prepare_download(page, dy104_web, surface)
        button = page.get_by_role("button", name=label, exact=True)
        pattern = f"**/api/v1{endpoint}"
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
        expected = context.request.get(f"{dy104_api}/api/v1{endpoint}")
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
