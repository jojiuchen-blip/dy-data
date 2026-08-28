from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from collections.abc import Generator
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Thread

import pytest
from fastapi import Request
from playwright.sync_api import Browser, Page, expect, sync_playwright
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import uvicorn


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "apps" / "web"
DESIGN_SYSTEM_HTML = REPO_ROOT / "docs" / "design-system" / "index.html"
COMMISSION_MOCK_HTML = REPO_ROOT / "docs" / "commission-dashboard-navigation-mock.html"
HOST = "127.0.0.1"
VIEWPORTS = [
    (390, 844),
    (768, 1024),
    (1440, 900),
]

RUNTIME_SURFACES = [
    ("home", "/", "抖音经营数据引擎", "heading"),
    ("ranking", "/ranking", "全国门店月度榜单", "heading"),
    ("sales", "/sales", "核销表现", "heading"),
    ("clues", "/clues", "经营线索概览", "text"),
    ("clue-details", "/clues/details", "线索跟进列表", "text"),
    ("settlement", "/settlement", "单店分账", "heading"),
    ("order-details", "/details", "推广费订单明细", "heading"),
    ("admin-home", "/admin", "抖音经营中枢后台", "heading"),
    ("admin-accounts", "/admin/accounts", "账号管理", "heading"),
    ("admin-rules", "/admin/rules", "商品分账规则管理", "heading"),
    ("admin-sync", "/admin/sync", "数据同步管理", "text"),
    ("admin-clue-allocation", "/admin/clue-allocation", "线索分配", "heading"),
    (
        "admin-clue-allocation-rules",
        "/admin/clue-allocation/rules",
        "线索分配",
        "heading",
    ),
    (
        "admin-clue-allocation-trial",
        "/admin/clue-allocation/trial",
        "线索分配",
        "heading",
    ),
    (
        "admin-clue-allocation-records",
        "/admin/clue-allocation/records",
        "线索分配",
        "heading",
    ),
    (
        "admin-clue-allocation-headquarters",
        "/admin/clue-allocation/headquarters",
        "线索分配",
        "heading",
    ),
    ("admin-feedback", "/admin/feedback", "用户建议", "heading"),
    (
        "admin-product-types",
        "/admin/product-types",
        "商品口径",
        "heading",
    ),
]

sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
from dy_api.auth import AuthContext, get_current_user  # noqa: E402
from dy_api.access_control import ALL_PAGE_KEYS, STORE_DEFAULT_PAGE_KEYS  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes import admin as admin_routes  # noqa: E402
from dy_api.routes._data import get_data_store, get_session_dependency  # noqa: E402
from apps.api.dy_api.models import Base, DimSkuProductRule, JobRun  # noqa: E402


class LiveSettlementStore:
    """Deterministic reporting source served through the real FastAPI stack."""

    stores = [
        {"store_id": "store_001", "store_name": "上海浦东体验中心"},
        {"store_id": "store_002", "store_name": "上海虹桥服务中心"},
    ]

    def list_stores(self, scope_store_ids=None):
        if scope_store_ids is None:
            return self.stores
        allowed = set(scope_store_ids)
        return [store for store in self.stores if store["store_id"] in allowed]

    def commission_rules_summary(self):
        return {"non_commission_owner_accounts": [], "commission_skus": []}

    def list_product_types(self):
        return ["all", "basic_service"]

    def list_product_scopes(self):
        return ["all", "精诚养车"]

    def product_scope_type_map(self):
        return {"精诚养车": ["basic_service"]}

    def list_sale_months(self):
        return ["2026-08"]

    def list_verify_months(self):
        return ["2026-08"]

    def list_statement_months(self):
        return ["2026-08"]

    def store_exists(self, store_id: str):
        return any(store["store_id"] == store_id for store in self.stores)

    def monthly_settlement_context_exists(self, store_id: str, month: str):
        return self.store_exists(store_id) and month == "2026-08"

    def store_ranking_report(self, filters: dict):
        row = {
            "rank": 1,
            "store_id": "store_001",
            "store_name": "上海浦东体验中心",
            "sales_order_count": 3,
            "sales_amount_cent": 30000,
            "verified_order_count": 2,
            "verified_amount_cent": 20000,
            "promotion_net_fee_cent": 1600,
            "management_net_fee_cent": 900,
            "net_settlement_reference_cent": 700,
        }
        return {
            "period_type": filters["period_type"],
            "period_key": filters["period_key"],
            "product_scope": filters["product_scope"],
            "product_type": filters["product_type"],
            "formal_period_start_month": "2026-08",
            "scope_mode": filters["scope_mode"],
            "totals": {key: value for key, value in row.items() if key not in {"rank", "store_id", "store_name"}},
            "list": [row],
            "total": 1,
            "page": filters["page"],
            "page_size": filters["page_size"],
        }

    def monthly_settlement_report(self, filters: dict):
        return {
            "store": {"store_id": filters["store_id"], "store_name": "上海浦东体验中心"},
            "month": filters["month"],
            "product_scope": filters["product_scope"],
            "product_type": filters["product_type"],
            "is_formal_period": True,
            "statement": None,
            "metrics": {
                "sales_order_count": 3,
                "sales_amount_cent": 30000,
                "verified_order_count": 2,
                "verified_amount_cent": 20000,
                "promotion_base_cent": 21000,
                "promotion_original_fee_cent": 1680,
                "promotion_adjustment_fee_cent": -80,
                "promotion_net_fee_cent": 1600,
                "management_base_cent": 10000,
                "management_original_fee_cent": 1000,
                "management_adjustment_fee_cent": -100,
                "management_net_fee_cent": 900,
                "net_settlement_reference_cent": 700,
            },
            "lines": [
                {
                    "statement_line_id": None,
                    "fee_direction": "PROMOTION",
                    "product_scope": "精诚养车",
                    "product_type": "basic_service",
                    "original_entry_count": 1,
                    "adjustment_entry_count": 1,
                    "original_base_cent": 22000,
                    "adjustment_base_cent": -1000,
                    "net_base_cent": 21000,
                    "original_fee_cent": 1680,
                    "adjustment_fee_cent": -80,
                    "net_fee_cent": 1600,
                    "min_fee_rate": "0.080000",
                    "max_fee_rate": "0.080000",
                    "rule_version_count": 1,
                    "fee_rates": ["0.080000"],
                    "rule_versions": ["rule-v1"],
                },
                {
                    "statement_line_id": None,
                    "fee_direction": "MANAGEMENT",
                    "product_scope": "精诚养车",
                    "product_type": "basic_service",
                    "original_entry_count": 1,
                    "adjustment_entry_count": 0,
                    "original_base_cent": 10000,
                    "adjustment_base_cent": 0,
                    "net_base_cent": 10000,
                    "original_fee_cent": 1000,
                    "adjustment_fee_cent": 0,
                    "net_fee_cent": 1000,
                    "min_fee_rate": "0.100000",
                    "max_fee_rate": "0.100000",
                    "rule_version_count": 1,
                    "fee_rates": ["0.100000"],
                    "rule_versions": ["rule-v1"],
                },
            ],
        }

    def order_fee_details(self, filters: dict):
        from fastapi import HTTPException

        if filters.get("statement_id") == "expired":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "SOURCE_CONTEXT_EXPIRED",
                    "message": "来源上下文已过期",
                    "errors": [],
                    "requestId": "req-live-expired",
                },
            )
        rows = [] if filters.get("q") == "missing" else [{
            "fee_result_id": "fee-live-1",
            "statement_entry_id": None,
            "order_id": "ORDER-LIVE-001",
            "coupon_id": "COUPON-LIVE-001",
            "order_status": "paid",
            "coupon_status": "verified",
            "fee_direction": filters["fee_direction"],
            "original_business_month": "2026-08",
            "sale_month": "2026-08",
            "verify_month": "2026-08",
            "rule_match_date": "2026-08-02",
            "sale_time": "2026-08-02T08:00:00+08:00",
            "verify_time": "2026-08-03T08:00:00+08:00",
            "sale_store_id": "store_001",
            "sale_store_name": "上海浦东体验中心",
            "verify_store_id": "store_001",
            "verify_store_name": "上海浦东体验中心",
            "sku_id": "sku_live_001",
            "sku_name": "基础养护 SKU",
            "product_name": "基础养护",
            "product_scope": "精诚养车",
            "product_type": "basic_service",
            "sale_channel": "LIVE",
            "source_amount_cent": 10000,
            "refunded_amount_cent": 1000,
            "original_base_cent": 10000,
            "fee_rate": "0.080000",
            "original_fee_cent": 800,
            "adjustment_base_cent": -1000,
            "adjustment_fee_cent": -80,
            "adjusted_net_base_cent": 9000,
            "adjusted_net_fee_cent": 720,
            "rule_version": "rule-v1",
            "result_status": "VALID",
            "data_status": "ADJUSTED",
            "statement_id": None,
            "statement_line_id": None,
            "statement_status": None,
            "adjustments": [],
        }]
        return {
            "context": {
                "statement_id": filters.get("statement_id"),
                "statement_line_id": filters.get("statement_line_id"),
                "store_id": filters.get("store_id"),
                "month": filters.get("month"),
                "fee_direction": filters["fee_direction"],
                "product_scope": filters["product_scope"],
                "product_type": filters["product_type"],
                "fee_rates": filters.get("fee_rates", []),
                "rule_versions": filters.get("rule_versions", []),
                "statement_status": None,
            },
            "list": rows,
            "total": len(rows),
            "page": filters["page"],
            "page_size": filters["page_size"],
        }

    def order_fee_details_export_csv(self, filters: dict):
        if filters.get("q") == "export-empty":
            return ""
        return "订单ID,券ID,费用方向,规则版本\r\nORDER-LIVE-001,COUPON-LIVE-001,PROMOTION,rule-v1\r\n"

    def export_filter_header(self, filters: dict):
        return json.dumps(
            {key: value for key, value in filters.items() if value not in (None, "", "all") and key not in {"page", "page_size"}},
            ensure_ascii=True,
            sort_keys=True,
        )


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def wait_for_url(url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception as error:  # pragma: no cover - only used for diagnostics
            last_error = error
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


@pytest.fixture(scope="session")
def vite_base_url() -> Generator[str]:
    node = shutil.which("node")
    vite_script = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite_script.exists():
        pytest.skip("Node.js and Vite are required for visual smoke tests")

    port = find_free_port()
    env = os.environ.copy()
    env["VITE_USE_MOCKS"] = "true"
    process = subprocess.Popen(
        [
            node,
            str(vite_script),
            "--host",
            HOST,
            "--port",
            str(port),
        ],
        cwd=WEB_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines: deque[str] = deque(maxlen=200)

    def drain_output() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            output_lines.append(line.rstrip())

    output_thread = Thread(target=drain_output, name="vite-output-drain", daemon=True)
    output_thread.start()

    base_url = f"http://{HOST}:{port}"
    try:
        wait_for_url(base_url)
        yield base_url
    except Exception:
        output = "\n".join(output_lines)
        raise RuntimeError(f"Vite dev server did not start.\n{output}") from None
    finally:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            process.wait(timeout=10)
        else:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        output_thread.join(timeout=1)


@pytest.fixture(scope="session")
def vite_real_api_base_url() -> Generator[str]:
    node = shutil.which("node")
    vite_script = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite_script.exists():
        pytest.skip("Node.js and Vite are required for visual smoke tests")

    port = find_free_port()
    env = os.environ.copy()
    env["VITE_USE_MOCKS"] = "false"
    process = subprocess.Popen(
        [
            node,
            str(vite_script),
            "--host",
            HOST,
            "--port",
            str(port),
        ],
        cwd=WEB_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    base_url = f"http://{HOST}:{port}"
    try:
        wait_for_url(base_url)
        yield base_url
    except Exception:
        output = ""
        if process.stdout is not None:
            output = process.stdout.read()
        raise RuntimeError(f"Vite dev server did not start.\n{output}") from None
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture(scope="session")
def vite_clue_demo_base_url() -> Generator[str]:
    node = shutil.which("node")
    vite_script = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite_script.exists():
        pytest.skip("Node.js and Vite are required for clue demo browser tests")

    port = find_free_port()
    env = os.environ.copy()
    env["VITE_USE_MOCKS"] = "false"
    env["VITE_DEMO_MODE"] = "true"
    process = subprocess.Popen(
        [node, str(vite_script), "--host", HOST, "--port", str(port)],
        cwd=WEB_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    base_url = f"http://{HOST}:{port}"
    try:
        wait_for_url(base_url)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture(scope="session")
def live_fastapi_base_url() -> Generator[str]:
    port = find_free_port()
    previous_cors = os.environ.get("DY_API_CORS_ORIGINS")
    os.environ["DY_API_CORS_ORIGINS"] = "*"
    app = create_app()
    live_store = LiveSettlementStore()

    def current_user(request: Request):
        role = request.cookies.get("dy_e2e_role", "admin")
        return AuthContext(
            user_id=f"live-{role}",
            username=f"live-{role}",
            display_name=f"Live {role.title()}",
            role=role,
            store_ids=("store_001",) if role == "store" else (),
            auth_type="user" if role == "store" else "env_admin",
            store_scope_mode="specified" if role == "store" else "all",
            page_keys=(
                tuple(STORE_DEFAULT_PAGE_KEYS)
                if role == "store"
                else tuple(ALL_PAGE_KEYS)
            ),
        )

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_data_store] = lambda: live_store
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
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
        if previous_cors is None:
            os.environ.pop("DY_API_CORS_ORIGINS", None)
        else:
            os.environ["DY_API_CORS_ORIGINS"] = previous_cors


@pytest.fixture(scope="session")
def vite_live_api_base_url(live_fastapi_base_url: str) -> Generator[str]:
    node = shutil.which("node")
    vite_script = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite_script.exists():
        pytest.skip("Node.js and Vite are required for live API browser tests")

    port = find_free_port()
    env = os.environ.copy()
    env["VITE_USE_MOCKS"] = "false"
    env["VITE_API_BASE_URL"] = f"{live_fastapi_base_url}/api/v1"
    process = subprocess.Popen(
        [
            node,
            str(vite_script),
            "--host",
            HOST,
            "--port",
            str(port),
        ],
        cwd=WEB_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    base_url = f"http://{HOST}:{port}"
    try:
        wait_for_url(base_url)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture(scope="session")
def live_admin_fastapi_base_url() -> Generator[str]:
    port = find_free_port()
    previous_cors = os.environ.get("DY_API_CORS_ORIGINS")
    os.environ["DY_API_CORS_ORIGINS"] = "*"
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with factory() as session:
        session.add_all([
            DimSkuProductRule(
                sku_id=f"SKU-LIVE-ADMIN-{index:03d}",
                sku_name=f"真实联调保养 SKU {index}",
                product_id=f"PRODUCT-LIVE-{index:03d}",
                product_name=f"真实联调基础保养 {index}",
                spu_id=f"SPU-LIVE-{index:03d}",
                product_scope="正式产品范围" if index == 5 else "原产品范围",
                product_type="正式商品类型" if index == 5 else "原商品类型",
                is_service_product=False,
                creator_account_id="creator-live-001",
                creator_account_name="创建账号",
                owner_account_id="owner-live-001",
                owner_account_name="归属商户",
                product_status_normalized="ACTIVE",
                is_active_product=True,
            )
            for index in range(1, 6)
        ])
        session.commit()

    original_product_sync_job = admin_routes.run_product_sync_job
    sync_threads: list[threading.Thread] = []

    def deterministic_product_sync_job(*, job_id: str) -> None:
        def finalize() -> None:
            time.sleep(0.35)
            with factory() as session:
                job = session.get(JobRun, job_id)
                if job is None:
                    return
                metadata = dict(job.metadata_json or {})
                reason = str(metadata.get("reason") or "")
                metadata.update({
                    "observed_count": 3,
                    "inserted_count": 1,
                    "updated_count": 1,
                    "unchanged_count": 1,
                    "phase_counts": {"fetch": 3, "validate": 3, "snapshot": 3, "current": 2},
                    "next_cursor_masked": "sha256:live-browser",
                })
                job.finished_at = datetime.now(timezone.utc)
                if "失败" in reason:
                    job.status = "failed"
                    job.failed_count = 3
                    job.error_message = "上游商品服务暂时不可用，请稍后重试"
                    metadata.update({"error_code": "DOUYIN_UPSTREAM_FAILED", "retryable": True})
                elif "部分" in reason:
                    job.status = "partial"
                    job.success_count = 2
                    job.failed_count = 1
                    job.error_message = "1 个 SKU 校验失败，其他快照已提交"
                    metadata.update({"error_code": "PRODUCT_SYNC_PARTIAL", "retryable": True})
                else:
                    job.status = "success"
                    job.success_count = 3
                    job.failed_count = 0
                    job.error_message = None
                    metadata.update({"error_code": None, "retryable": False})
                job.metadata_json = metadata
                session.commit()

        worker = threading.Thread(target=finalize, daemon=True)
        sync_threads.append(worker)
        worker.start()

    admin_routes.run_product_sync_job = deterministic_product_sync_job
    app = create_app()

    def current_user(request: Request):
        role = request.cookies.get("dy_e2e_role", "admin")
        is_store = role == "store"
        return AuthContext(
            user_id=f"live-{role}",
            username=f"live-{role}",
            display_name=f"Live {role.title()}",
            role=role,
            store_ids=("store-1",) if is_store else (),
            auth_type="user" if is_store else "env_admin",
            store_scope_mode="specified" if is_store else "all",
            page_keys=(
                tuple(STORE_DEFAULT_PAGE_KEYS)
                if is_store
                else tuple(ALL_PAGE_KEYS)
            ),
        )

    def session_dependency():
        with factory() as session:
            yield session

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_session_dependency] = session_dependency
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://{HOST}:{port}"
    try:
        wait_for_url(f"{base_url}/docs")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        for sync_thread in sync_threads:
            sync_thread.join(timeout=5)
        admin_routes.run_product_sync_job = original_product_sync_job
        app.dependency_overrides.clear()
        engine.dispose()
        if previous_cors is None:
            os.environ.pop("DY_API_CORS_ORIGINS", None)
        else:
            os.environ["DY_API_CORS_ORIGINS"] = previous_cors


@pytest.fixture(scope="session")
def vite_live_admin_api_base_url(live_admin_fastapi_base_url: str) -> Generator[str]:
    node = shutil.which("node")
    vite_script = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite_script.exists():
        pytest.skip("Node.js and Vite are required for live admin API browser tests")
    port = find_free_port()
    env = os.environ.copy()
    env["VITE_USE_MOCKS"] = "false"
    env["VITE_API_BASE_URL"] = f"{live_admin_fastapi_base_url}/api/v1"
    process = subprocess.Popen(
        [node, str(vite_script), "--host", HOST, "--port", str(port)],
        cwd=WEB_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    base_url = f"http://{HOST}:{port}"
    try:
        wait_for_url(base_url)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture(scope="session")
def browser() -> Generator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


def api_payload(data: object) -> str:
    return json.dumps(
        {
            "data": data,
            "meta": {
                "generated_at": "2026-06-25T00:00:00Z",
                "source": "visual-smoke",
            },
        },
        ensure_ascii=False,
    )


def record_console_error(message: object, errors: list[str]) -> None:
    message_type = getattr(message, "type", "")
    message_text = str(getattr(message, "text", ""))
    if message_type == "error" and not message_text.startswith(
        "Failed to load resource:",
    ):
        errors.append(message_text)


def record_unexpected_http_failure(response: object, errors: list[str]) -> None:
    status = int(getattr(response, "status", 0))
    url = str(getattr(response, "url", ""))
    if status >= 400 and "/api/v1/" not in url:
        errors.append(f"{status} {url}")


def rgb_channels(value: str) -> tuple[int, int, int]:
    channels = [int(part) for part in re.findall(r"\d+", value)[:3]]
    if len(channels) != 3:
        raise AssertionError(f"Expected an RGB color, received {value!r}")
    return channels[0], channels[1], channels[2]


def relative_luminance(value: str) -> float:
    def normalize(channel: int) -> float:
        component = channel / 255
        return component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4

    red, green, blue = rgb_channels(value)
    return 0.2126 * normalize(red) + 0.7152 * normalize(green) + 0.0722 * normalize(blue)


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def install_api_routes(page: Page) -> None:
    admin_user = {
        "username": "visual-admin",
        "user_id": "visual-admin",
        "display_name": "Visual Admin",
        "role": "highest_admin",
        "is_highest_admin": True,
        "status": "active",
        "is_initialized": True,
        "store_ids": [],
        "store_scope_mode": "all",
        "page_keys": [
            "A01", "A02", "B01", "B02", "B03", "C01",
            "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10",
        ],
    }
    empty_pagination = {
        "page": 1,
        "page_size": 50,
        "total": 0,
        "total_pages": 0,
    }
    sync_job = {
        "job_id": "visual-sync-001",
        "job_name": "orders",
        "status": "success",
        "started_at": "2026-06-25T08:00:00Z",
        "finished_at": "2026-06-25T08:05:00Z",
        "success_count": 128,
        "failed_count": 0,
        "error_message": None,
        "metadata_json": {
            "source_window": {
                "start": "2026-06-24T00:00:00Z",
                "end": "2026-06-25T00:00:00Z",
                "timezone": "Asia/Shanghai",
            },
            "phases": {
                "orders": {
                    "name": "orders",
                    "fetched": 128,
                    "upserted": 128,
                },
            },
        },
    }
    failed_sync_job = {
        **sync_job,
        "job_id": "visual-sync-002",
        "status": "failed",
        "success_count": 0,
        "failed_count": 1,
        "error_message": "open api returned 0 rows",
    }
    sync_admin = {
        "config": {
            "history_start": "2026-06-01",
            "history_end": "2026-06-25",
            "history_chunk_days": 7,
            "rolling_days": 30,
            "interval_seconds": 3600,
            "auto_sync_enabled": True,
            "backfill_skip_completed": True,
        },
        "progress": {
            "total_windows": 10,
            "completed_windows": 8,
            "running_jobs": 0,
            "failed_jobs": 0,
            "latest_completed_window": {
                "start": "2026-06-24T00:00:00Z",
                "end": "2026-06-25T00:00:00Z",
                "timezone": "Asia/Shanghai",
            },
        },
        "schedule": {
            "auto_sync_enabled": True,
            "latest_successful_sync_at": "2026-06-25T08:05:00Z",
            "next_scheduled_sync_at": "2026-06-25T09:05:00Z",
        },
        "worker_status": {
            "mode": "collect_and_settle",
            "auto_sync_enabled": True,
            "interval_seconds": 3600,
            "rolling_days": 30,
            "history_chunk_days": 7,
            "run_on_start": False,
            "run_once": False,
            "chunk_max_attempts": 3,
            "disabled_poll_seconds": 300,
            "active_job": None,
            "latest_success": sync_job,
            "latest_failure": failed_sync_job,
            "next_scheduled_sync_at": "2026-06-25T09:05:00Z",
        },
        "jobs": [sync_job, failed_sync_job],
    }
    sku_product = {
        "skuId": "SKU-VISUAL-001",
        "skuName": "基础保养 SKU",
        "productId": "PRODUCT-VISUAL-001",
        "productName": "精诚养车基础保养",
        "spuId": "SPU-VISUAL-001",
        "productScope": "精诚养车",
        "productType": "基础保养",
        "configurationStatus": "CONFIGURED",
        "isServiceProduct": True,
        "creatorAccountId": "creator-001",
        "creatorAccountName": "商品创建账号",
        "ownerAccountId": "owner-001",
        "ownerAccountName": "商品归属商户",
        "productStatus": "ACTIVE",
        "isActiveProduct": True,
        "lastSyncedAt": "2026-07-20T08:00:00Z",
        "manualModifiedAt": "2026-07-20T09:00:00Z",
        "manualModifiedBy": "visual-admin",
    }
    fee_rule = {
        "ruleVersion": "SFR-20260801-VISUAL",
        "skuId": "SKU-VISUAL-001",
        "skuName": "基础保养 SKU",
        "productScope": "精诚养车",
        "productType": "基础保养",
        "promotionServiceFeeRate": "0.080000",
        "managementServiceFeeRate": "0.100000",
        "effectiveDate": "2026-08-01",
        "effectiveAt": "2026-08-01T00:00:00+08:00",
        "ruleStatus": "ACTIVE",
        "previousRuleVersion": None,
        "createdBy": "visual-admin",
        "changeReason": "首批正式双费率",
        "publishedAt": "2026-07-20T10:00:00Z",
    }
    import_batch = {
        "batchId": "IMPORT-VISUAL-001",
        "fileName": "sku-fee-rules.csv",
        "batchStatus": "PENDING_COMMIT",
        "commitMode": "ATOMIC",
        "effectiveDate": "2026-08-01",
        "totalCount": 1,
        "validCount": 1,
        "successCount": 0,
        "failedCount": 0,
        "uploadedBy": "visual-admin",
        "validatedAt": "2026-07-20T10:10:00Z",
        "committedAt": None,
        "hasResultFile": True,
    }
    product_sync_run = {
        "syncRunId": "PRODUCT-SYNC-VISUAL-001",
        "mode": "INCREMENTAL",
        "status": "SUCCESS",
        "startedAt": "2026-07-20T08:00:00Z",
        "finishedAt": "2026-07-20T08:02:00Z",
        "observedCount": 12,
        "insertedCount": 2,
        "updatedCount": 5,
        "unchangedCount": 5,
        "failedCount": 0,
        "latestSuccessfulSyncedAt": "2026-07-20T08:02:00Z",
        "nextCursorMasked": "***next",
        "errorCode": None,
        "errorMessage": None,
    }

    page.route(
        "**/api/v1/auth/me",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload(admin_user),
        ),
    )
    page.route(
        "**/api/v1/admin/sync",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload(sync_admin),
        ),
    )
    page.route(
        "**/api/v1/admin/sku-products?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "list": [sku_product],
                "total": 1,
                "page": 1,
                "pageSize": 50,
                "statusCounts": {"unconfigured": 0, "partial": 0, "configured": 1},
            }),
        ),
    )
    page.route(
        "**/api/v1/admin/sku-rules?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "rows": [{
                    "sku_id": "SKU-VISUAL-001",
                    "product_name": "精诚养车基础保养",
                    "product_scope": "精诚养车",
                    "product_type": "基础保养",
                    "commission_rate": 0.1,
                    "is_service_product": True,
                    "order_count": 12,
                    "verified_coupon_count": 8,
                }],
                "pagination": {"page": 1, "page_size": 500, "total": 1, "total_pages": 1},
            }),
        ),
    )
    page.route(
        "**/api/v1/admin/sku-rules/lookup",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "rows": [{
                    "sku_id": "SKU-VISUAL-001",
                    "product_name": "精诚养车基础保养",
                    "product_scope": "精诚养车",
                    "product_type": "基础保养",
                    "commission_rate": 0.1,
                    "is_service_product": True,
                    "order_count": 12,
                    "verified_coupon_count": 8,
                }],
                "missing_sku_ids": [],
            }),
        ),
    )
    page.route(
        "**/api/v1/admin/non-commission-owner-accounts",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({"rows": []}),
        ),
    )
    page.route(
        "**/api/v1/admin/sku-fee-rules?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({"list": [fee_rule], "total": 1, "page": 1, "pageSize": 20}),
        ),
    )
    page.route(
        "**/api/v1/admin/sku-fee-rule-imports?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({"list": [import_batch], "total": 1, "page": 1, "pageSize": 10}),
        ),
    )
    page.route(
        "**/api/v1/admin/product-sync-runs?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "list": [product_sync_run],
                "page": 1,
                "pageSize": 20,
                "total": 1,
            }),
        ),
    )
    page.route(
        "**/api/v1/admin/product-sync-runs/PRODUCT-SYNC-VISUAL-001",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "run": product_sync_run,
                "phaseCounts": {"fetch": 12, "snapshot": 12},
                "affectedSkuSample": ["SKU-VISUAL-001"],
                "dataQualityIssueCount": 0,
                "retryable": False,
            }),
        ),
    )
    for endpoint in (
        "eligible-leads",
        "headquarters-pool",
        "cycles",
        "audit-logs",
        "rules",
        "decisions",
    ):
        page.route(
            f"**/api/v1/admin/clue-allocation/{endpoint}*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({"rows": [], "pagination": empty_pagination}),
            ),
        )
    billing_metrics = {
        "statement_total_cent": 128000,
        "confirmed_amount_cent": 118000,
        "pending_invoice_amount_cent": 38000,
        "issued_amount_cent": 80000,
        "settled_or_deducted_amount_cent": 60000,
    }
    statement = {
        "statement_id": "STMT-VISUAL-001",
        "store_id": "store_001",
        "store_name": "上海浦东体验中心",
        "month": "2026-08",
        "version_no": 2,
        "is_current": True,
        "supersedes_statement_id": "STMT-VISUAL-000",
        "status": "CONFIRMED",
        "promotion_amount_cent": 38000,
        "management_amount_cent": 9000,
        "promotion_confirmation": {
            "confirmation_id": "CONF-VISUAL-001",
            "status": "CONFIRMED",
            "confirmed_amount_cent": 38000,
            "confirmed_at": "2026-08-06T10:00:00+08:00",
        },
        "management_confirmation": None,
        "promotion_invoice_status": "PENDING_INVOICE",
        "management_invoice_status": "PENDING_INVOICE",
    }
    invoice = {
        "invoice_id": "INV-VISUAL-001",
        "store_id": "store_001",
        "statement_id": "STMT-VISUAL-000",
        "statement_month": "2026-08",
        "fee_direction": "PROMOTION",
        "version_no": 1,
        "is_current": True,
        "supersedes_invoice_id": None,
        "invoice_number": "12345678901234567890",
        "invoice_date": "2026-08-08",
        "invoice_amount_cent": 80000,
        "allocated_amount_cent": 80000,
        "status": "SUBMITTED_PENDING_FACTORY_REVIEW",
        "registered_at": "2026-08-08T10:00:00+08:00",
        "settled_at": None,
    }
    billing_metrics = {
        "statementTotalCent": 128000,
        "confirmedAmountCent": 118000,
        "pendingInvoiceAmountCent": 38000,
        "issuedAmountCent": 80000,
        "settledOrDeductedAmountCent": 60000,
    }
    statement = {
        "statementId": "STMT-VISUAL-001",
        "storeId": "store_001",
        "storeName": "上海浦东体验中心",
        "month": "2026-08",
        "versionNo": 2,
        "isCurrent": True,
        "supersedesStatementId": "STMT-VISUAL-000",
        "status": "CONFIRMED",
        "promotionAmountCent": 38000,
        "managementAmountCent": 9000,
        "promotionConfirmation": {
            "confirmationId": "CONF-VISUAL-001",
            "status": "CONFIRMED",
            "confirmedAmountCent": 38000,
            "confirmedAt": "2026-08-06T10:00:00+08:00",
        },
        "managementConfirmation": None,
        "promotionInvoiceStatus": "PENDING_INVOICE",
        "promotionInvoiceableAmountCent": 38000,
        "promotionCarryforwardBalanceCent": 0,
        "promotionInvoiceGroupId": "promotion-group-visual-001",
        "promotionRequiredStatementIds": ["STMT-VISUAL-001"],
        "promotionPositiveAmountCent": 38000,
        "promotionNegativeAmountCent": 0,
        "managementInvoiceStatus": "PENDING_INVOICE",
    }
    invoice = {
        "invoiceId": "INV-VISUAL-001",
        "storeId": "store_001",
        "statementId": "STMT-VISUAL-000",
        "statementMonth": "2026-08",
        "feeDirection": "PROMOTION",
        "versionNo": 1,
        "isCurrent": True,
        "supersedesInvoiceId": None,
        "invoiceNumber": "12345678901234567890",
        "invoiceDate": "2026-08-08",
        "invoiceAmountCent": 80000,
        "buyerName": "比亚迪汽车销售有限公司",
        "taxRatePercent": 6,
        "allocatedAmountCent": 80000,
        "settlementBatchMonth": "2026-07",
        "status": "SUBMITTED_PENDING_FACTORY_REVIEW",
        "registeredAt": "2026-08-08T10:00:00+08:00",
        "settledAt": None,
    }
    page.route(
        "**/api/v1/store-settlements?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload({
            "list": [statement], "total": 1, "page": 1, "page_size": 50,
            "metric_scope": "MONTHLY", "metrics": billing_metrics,
            "pageSize": 50, "metricScope": "MONTH",
            "metrics": {"month": {"promotionAmountCent": 38000, "managementAmountCent": 9000}},
        })),
    )
    page.route(
        "**/api/v1/promotion-invoices?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload({
            "list": [invoice], "total": 1, "page": 1, "page_size": 50,
            "pageSize": 50,
        })),
    )
    page.route(
        "**/api/v1/admin/finance/summary?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload({
            "month": "2026-08", "store_id": None, "fee_direction": "PROMOTION",
            "metric_scope": "MONTHLY", "metrics": billing_metrics,
            "storeId": None, "feeDirection": "PROMOTION", "metricScope": "MONTH",
        })),
    )
    page.route(
        "**/api/v1/admin/finance/invoices?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload({
            "list": [invoice], "total": 1, "page": 1, "page_size": 50,
            "pageSize": 50,
        })),
    )
    page.route(
        "**/api/v1/admin/finance/order-details?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload({
            "list": [{
                "statement_entry_id": "ENTRY-VISUAL-001", "statement_id": "STMT-VISUAL-001",
                "store_id": "store_001", "statement_month": "2026-08", "fee_direction": "PROMOTION",
                "order_id": "ORDER-VISUAL-001", "coupon_id": "COUPON-VISUAL-001",
                "original_business_month": "2026-07", "statement_posting_month": "2026-08",
                "base_amount_cent": 10000, "fee_amount_cent": 800,
                "statementEntryId": "ENTRY-VISUAL-001", "statementId": "STMT-VISUAL-001",
                "storeId": "store_001", "statementMonth": "2026-08", "feeDirection": "PROMOTION",
                "orderId": "ORDER-VISUAL-001", "couponId": "COUPON-VISUAL-001",
                "originalBusinessMonth": "2026-07", "statementPostingMonth": "2026-08",
                "baseAmountCent": 10000, "feeAmountCent": 800,
            }], "total": 1, "page": 1, "page_size": 500,
            "pageSize": 500,
        })),
    )
    page.route(
        "**/api/v1/admin/finance/stores?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload({
            "list": [{
                "store_id": "store_001", "store_name": "上海浦东体验中心", "sap_code": "SAP-001",
                "updated_at": "2026-08-08T10:00:00+08:00", "summary": billing_metrics,
                "storeId": "store_001", "storeName": "上海浦东体验中心", "sapCode": "SAP-001",
                "updatedAt": "2026-08-08T10:00:00+08:00", **billing_metrics,
            }], "total": 1, "page": 1, "page_size": 50,
            "pageSize": 50,
        })),
    )
    page.route(
        "**/api/v1/admin/disputes?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload({
            "list": [{
                "dispute_id": "DSP-VISUAL-001", "statement_id": "STMT-VISUAL-001",
                "store_id": "store_001", "statement_month": "2026-08", "fee_direction": "PROMOTION",
                "dispute_type": "AMOUNT_ERROR", "status": "PENDING", "disputed_amount_cent": 800,
                "description": "订单金额与门店凭证不一致", "contact_name": "张先生",
                "contact_phone_masked": "138****0000", "evidence": ["evidence-001"], "orders": [],
                "submitted_at": "2026-08-08T10:00:00+08:00", "resolution_note": None,
                "result_statement_id": None,
                "disputeId": "DSP-VISUAL-001", "statementId": "STMT-VISUAL-001",
                "storeId": "store_001", "statementMonth": "2026-08", "feeDirection": "PROMOTION",
                "disputeType": "AMOUNT_ERROR", "disputedAmountCent": 800,
                "contactName": "张先生", "contactPhoneMasked": "138****0000",
                "submittedAt": "2026-08-08T10:00:00+08:00", "resolutionNote": None,
                "resultStatementId": None,
            }], "total": 1, "page": 1, "page_size": 50,
            "pageSize": 50,
        })),
    )
    page.route(
        "**/api/v1/admin/finance-imports?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload({
            "list": [{
                "batch_id": "FIN-IMPORT-VISUAL-001", "import_type": "PROMOTION_FACTORY_RESULT",
                "statement_month": "2026-08", "file_name": "promotion-review.csv", "scenario": "FIRST_IMPORT_READY",
                "read_version": 0, "current_version": 1, "content_changed": True,
                "total_rows": 120, "success_rows": 118, "error_rows": 2,
                "submitted_by": "visual-admin", "submitted_at": "2026-08-08T10:00:00+08:00",
                "committed_by": None, "committed_at": None,
                "batchId": "FIN-IMPORT-VISUAL-001", "importType": "PROMOTION_FACTORY_RESULT",
                "statementMonth": "2026-08", "fileName": "promotion-review.csv",
                "readVersion": 0, "currentVersion": 1, "contentChanged": True,
                "totalRows": 120, "successRows": 118, "errorRows": 2,
                "submittedBy": "visual-admin", "submittedAt": "2026-08-08T10:00:00+08:00",
                "committedBy": None, "committedAt": None,
            }], "total": 1, "page": 1, "page_size": 50,
            "pageSize": 50,
        })),
    )
    page.route(
        "**/api/v1/admin/clue-allocation/store-scores*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({"run": None, "rows": [], "pagination": empty_pagination}),
        ),
    )


def settlement_filter_meta() -> dict[str, object]:
    return {
        "stores": [{"storeId": "store_001", "storeName": "上海浦东体验中心"}],
        "productScopes": ["all"],
        "productScopeTypeMap": {},
        "productTypes": ["all"],
        "defaultProductType": "all",
        "saleMonths": ["2026-08"],
        "verifyMonths": ["2026-08"],
        "statementMonths": ["2026-08"],
        "periodTypes": ["MONTHLY", "CUMULATIVE"],
        "feeDirections": ["PROMOTION", "MANAGEMENT"],
        "formalPeriodStartMonth": "2026-08",
        "timezone": "Asia/Shanghai",
    }


def settlement_monthly_data(
    store_id: str,
    store_name: str,
    month: str = "2026-08",
) -> dict[str, object]:
    return {
        "store": {"storeId": store_id, "storeName": store_name},
        "month": month,
        "productScope": "all",
        "productType": "all",
        "isFormalPeriod": True,
        "statement": {
            "statementId": f"STMT-{store_id}",
            "statementStatus": "PENDING_CONFIRMATION",
        },
        "metrics": {
            "salesOrderCount": 1,
            "salesAmountCent": 12800,
            "verifiedOrderCount": 1,
            "verifiedAmountCent": 12800,
            "promotionBaseCent": 12800,
            "promotionOriginalFeeCent": 1024,
            "promotionAdjustmentFeeCent": 0,
            "promotionNetFeeCent": 1024,
            "managementBaseCent": 12800,
            "managementOriginalFeeCent": 512,
            "managementAdjustmentFeeCent": 0,
            "managementNetFeeCent": 512,
            "netSettlementReferenceCent": 512,
        },
        "lines": [],
    }


def billing_statement_data(
    store_id: str,
    store_name: str,
    *,
    version: int = 2,
    management_amount_cent: int = 9000,
) -> dict[str, object]:
    return {
        "statementId": f"STMT-{store_id}-V{version}",
        "storeId": store_id,
        "storeName": store_name,
        "month": "2026-08",
        "versionNo": version,
        "isCurrent": True,
        "supersedesStatementId": None,
        "status": "PENDING_CONFIRMATION",
        "promotionAmountCent": 38000,
        "managementAmountCent": management_amount_cent,
        "promotionConfirmableAmountCent": 38000,
        "managementConfirmableAmountCent": management_amount_cent,
        "promotionConfirmation": None,
        "managementConfirmation": None,
        "promotionInvoiceStatus": "PENDING_INVOICE",
        "promotionInvoiceableAmountCent": 38000,
        "promotionCarryforwardBalanceCent": 0,
        "promotionInvoiceGroupId": None,
        "promotionRequiredStatementIds": [],
        "promotionPositiveAmountCent": 38000,
        "promotionNegativeAmountCent": 0,
        "managementInvoiceStatus": "PENDING_INVOICE",
    }


def order_fee_details_data(*, empty: bool = False) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    if not empty:
        rows.append(
            {
                "feeResultId": "fee-visual-001",
                "orderId": "ORDER-VISUAL-001",
                "couponId": "COUPON-VISUAL-001",
                "feeDirection": "PROMOTION",
                "originalBusinessMonth": "2026-08",
                "saleMonth": "2026-08",
                "verifyMonth": "2026-08",
                "saleTime": "2026-08-12T10:00:00+08:00",
                "verifyTime": "2026-08-18T15:30:00+08:00",
                "saleStoreId": "store_001",
                "saleStoreName": "上海浦东体验中心",
                "verifyStoreId": "store_002",
                "verifyStoreName": "上海虹桥服务中心",
                "skuId": "SKU-VISUAL-001",
                "productName": "精诚养车基础保养服务",
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
                "dataStatus": "VALID",
                "adjustments": [],
            }
        )
    return {
        "context": {
            "storeId": "store_001",
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "productScope": "all",
            "productType": "all",
            "feeRates": ["0.080000"],
            "ruleVersions": ["V2026.08.1"],
        },
        "list": rows,
        "total": len(rows),
        "page": 1,
        "pageSize": 50,
    }


def install_settlement_user_route(page: Page, role: str) -> None:
    page.route(
        "**/api/v1/auth/me",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload(
                {
                    "username": f"visual-{role}",
                    "user_id": f"visual-{role}",
                    "display_name": f"Visual {role.title()}",
                    "role": role,
                    "is_highest_admin": role == "admin",
                    "status": "active",
                    "is_initialized": True,
                    "store_ids": [] if role == "admin" else ["store_001"],
                    "store_scope_mode": "all" if role == "admin" else "specified",
                    "page_keys": ["B01", "B02", "B03"],
                }
            ),
        ),
    )


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize(
    ("name", "url_path", "expected_text", "ready_target"),
    [
        ("store-invoice", "/settlement/invoice?storeId=store_001&month=2026-08", "开票确认", "heading"),
        ("finance-promotion", "/finance/promotion?month=2026-08", "推广服务费", "heading"),
        ("finance-management", "/finance/management?month=2026-08", "管理服务费", "heading"),
        ("finance-orders-promotion", "/finance/orders/promotion?month=2026-08", "推广服务费订单明细", "heading"),
        ("finance-orders-management", "/finance/orders/management?month=2026-08", "管理服务费订单明细", "heading"),
        ("finance-stores", "/finance/stores?month=2026-08", "门店基础信息", "heading"),
        ("finance-disputes", "/finance/disputes?month=2026-08", "账单异议", "heading"),
        ("finance-imports", "/finance/imports", "导入记录", "heading"),
        (
            "design-system",
            DESIGN_SYSTEM_HTML.as_uri(),
                "dy-data 界面设计规范 V0.2.1",
            "heading",
        ),
        (
            "commission-dashboard-mock",
            COMMISSION_MOCK_HTML.as_uri(),
            "全国门店榜单",
            "heading",
        ),
        ("home", "/", "抖音经营数据引擎", "heading"),
        ("ranking", "/ranking", "全国门店月度榜单", "heading"),
        ("sales", "/sales", "核销表现", "heading"),
        ("clues", "/clues", "经营线索概览", "text"),
        ("clue-details", "/clues/details", "线索跟进列表", "text"),
        ("settlement", "/settlement", "单店分账", "heading"),
        ("order-details", "/details", "推广费订单明细", "heading"),
        ("invoice", "/invoice", "开票确认", "heading"),
        ("admin-home", "/admin", "抖音经营中枢后台", "heading"),
        ("admin-accounts", "/admin/accounts", "账号管理", "heading"),
        ("admin-rules", "/admin/rules", "商品分账规则管理", "heading"),
        ("admin-sync", "/admin/sync", "数据同步管理", "text"),
        ("admin-clue-allocation", "/admin/clue-allocation", "线索分配", "heading"),
        (
            "admin-clue-allocation-rules",
            "/admin/clue-allocation/rules",
            "线索分配",
            "heading",
        ),
        (
            "admin-clue-allocation-trial",
            "/admin/clue-allocation/trial",
            "线索分配",
            "heading",
        ),
        (
            "admin-clue-allocation-records",
            "/admin/clue-allocation/records",
            "线索分配",
            "heading",
        ),
        (
            "admin-clue-allocation-headquarters",
            "/admin/clue-allocation/headquarters",
            "线索分配",
            "heading",
        ),
        ("admin-feedback", "/admin/feedback", "用户建议", "heading"),
        (
            "admin-product-types",
            "/admin/product-types",
            "商品口径",
            "heading",
        ),
    ],
)
def test_key_ui_surfaces_render_without_layout_smoke_failures(
    browser: Browser,
    vite_base_url: str,
    tmp_path: Path,
    name: str,
    url_path: str,
    expected_text: str,
    ready_target: str,
    width: int,
    height: int,
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    http_errors: list[str] = []
    page.on("console", lambda message: record_console_error(message, console_errors))
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "response",
        lambda response: record_unexpected_http_failure(response, http_errors),
    )

    try:
        install_api_routes(page)
        url = url_path if url_path.startswith("file:") else f"{vite_base_url}{url_path}"
        page.goto(url, wait_until="domcontentloaded")
        if ready_target == "heading":
            page.get_by_role("heading", name=expected_text, exact=True).wait_for(timeout=10000)
        else:
            page.get_by_text(expected_text, exact=False).first.wait_for(timeout=10000)
        page.screenshot(path=tmp_path / f"{name}-{width}.png", full_page=True)

        text_length = page.evaluate("() => document.body.innerText.trim().length")
        horizontal_overflow = page.evaluate(
            "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth",
        )

        assert text_length > 20
        assert horizontal_overflow <= 2
        assert page.locator("h1").count() == 1
        assert console_errors == []
        assert page_errors == []
        assert http_errors == []

        if name == "store-invoice" or name.startswith("finance-"):
            body_text = page.locator("body").inner_text()
            for internal_value in [
                "SUBMITTED_PENDING_FACTORY_REVIEW",
                "PROMOTION_FACTORY_RESULT",
                "MANAGEMENT_FACTORY_RESULT",
                "FIRST_IMPORT_READY",
                "PENDING_ADMIN_APPROVAL",
                "AMOUNT_ERROR",
            ]:
                assert internal_value not in body_text

        if width == 390:
            mobile_targets = page.locator(
                ".mobile-bottom-nav a, .mobile-bottom-nav button",
            )
            for index in range(mobile_targets.count()):
                box = mobile_targets.nth(index).bounding_box()
                assert box is not None
                assert box["height"] >= 44

            shared_buttons = page.locator(
                ".ui-button:visible, .ui-icon-button:visible",
            )
            for index in range(shared_buttons.count()):
                target = shared_buttons.nth(index)
                box = target.bounding_box()
                assert box is not None
                assert box["height"] >= 44
                if "ui-icon-button" in (target.get_attribute("class") or ""):
                    assert box["width"] >= 44
    finally:
        context.close()


def test_settlement_desktop_subnav_keeps_every_item_visible(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/invoice", wait_until="domcontentloaded")
        nav = page.locator(".workspace-subnav--desktop")
        nav.wait_for(timeout=10000)

        assert nav.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        nav_box = nav.bounding_box()
        assert nav_box is not None
        links = nav.locator("a")
        assert links.count() == 4
        assert links.all_inner_texts() == [
            "全国门店榜单",
            "单店分账",
            "订单费用明细",
            "开票确认",
        ]
        for index in range(links.count()):
            link_box = links.nth(index).bounding_box()
            assert link_box is not None
            assert link_box["x"] >= nav_box["x"] - 1
            assert link_box["x"] + link_box["width"] <= nav_box["x"] + nav_box["width"] + 1
    finally:
        context.close()


def test_admin_product_types_drawers_open_without_runtime_errors(
    browser: Browser,
    vite_base_url: str,
    tmp_path: Path,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/admin/product-types?view=configured", wait_until="domcontentloaded")
        page.get_by_role("heading", name="商品口径", exact=True).wait_for(timeout=10000)
        page.get_by_role("button", name="设置", exact=True).click()
        drawer = page.get_by_role("dialog", name="设置商品口径")
        drawer.wait_for(timeout=10000)
        assert drawer.get_by_text("保持原值", exact=True).count() == 2
        page.screenshot(path=tmp_path / "admin-product-types-drawer.png", full_page=True)
        page.get_by_role("button", name="取消", exact=True).click()
        page.get_by_role("button", name="批量导入", exact=True).click()
        page.get_by_role("dialog", name="批量导入商品口径").wait_for(timeout=10000)
        assert page.get_by_role("button", name="下载模板", exact=True).is_visible()
        assert page_errors == []
    finally:
        context.close()


def test_design_system_catalog_examples_render_and_table_allows_scroll_chaining(
    browser: Browser,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        page.goto(DESIGN_SYSTEM_HTML.as_uri(), wait_until="domcontentloaded")
        catalog_frame = page.locator("[data-runtime-catalog-frame]")
        catalog_frame.scroll_into_view_if_needed()
        catalog = page.frame_locator("[data-runtime-catalog-frame]")

        searchable = catalog.locator(
            "#catalog-searchable-store-select .searchable-store-select",
        )
        searchable.wait_for(timeout=10000)
        searchable_input = searchable.locator("input")
        searchable_box = searchable.bounding_box()
        input_box = searchable_input.bounding_box()
        assert searchable_box is not None
        assert input_box is not None
        assert input_box["width"] >= searchable_box["width"] - 2
        assert input_box["height"] >= 38

        text_fields = catalog.locator("#catalog-text-fields")
        text_fields.scroll_into_view_if_needed()
        assert text_fields.locator(".ui-field").count() >= 5
        assert text_fields.locator(".ui-checkbox-field").count() == 1
        assert text_fields.locator(".ui-field__control").count() >= 5

        selection_controls = catalog.locator("#catalog-selection-controls")
        selection_controls.scroll_into_view_if_needed()
        tabs = selection_controls.locator('[role="tablist"]')
        summary_filter = selection_controls.locator(".ui-summary-filter")
        assert tabs.count() >= 2
        assert summary_filter.count() == 1
        first_tab = tabs.first.locator('[role="tab"]').first
        second_tab = tabs.first.locator('[role="tab"]').nth(1)
        first_tab.focus()
        first_tab.press("ArrowRight")
        assert second_tab.get_attribute("aria-selected") == "true"

        theme_picker = catalog.locator("#catalog-theme-picker .theme-picker")
        theme_picker.scroll_into_view_if_needed()
        assert theme_picker.get_by_role("button").count() == 3

        table = catalog.locator("#catalog-data-table .table-wrap")
        table.scroll_into_view_if_needed()
        assert catalog.locator("#catalog-data-table tbody tr").count() >= 6
        table_box = table.bounding_box()
        assert table_box is not None

        catalog_body = catalog.locator("body")
        scroll_before = catalog_body.evaluate("() => window.scrollY")
        page.mouse.move(
            table_box["x"] + table_box["width"] / 2,
            table_box["y"] + min(120, table_box["height"] / 2),
        )
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(250)
        scroll_after = catalog_body.evaluate("() => window.scrollY")

        assert scroll_after > scroll_before
    finally:
        context.close()


def test_design_system_chart_gallery_renders_without_nested_scroll_trap(
    browser: Browser,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        page.goto(DESIGN_SYSTEM_HTML.as_uri(), wait_until="domcontentloaded")
        gallery_frame = page.locator("[data-chart-gallery-frame]")
        gallery_frame.scroll_into_view_if_needed()
        page.wait_for_function(
            """() => {
              const frame = document.querySelector('[data-chart-gallery-frame]');
              return frame && frame.getBoundingClientRect().height > 3000;
            }""",
            timeout=15000,
        )

        gallery = page.frame_locator("[data-chart-gallery-frame]")
        gallery_handle = gallery_frame.element_handle()
        assert gallery_handle is not None
        gallery_page = gallery_handle.content_frame()
        assert gallery_page is not None
        gallery_page.wait_for_function(
            "() => document.querySelectorAll('svg > *').length >= 100",
            timeout=15000,
        )
        assert gallery.locator("svg > *").count() >= 100

        basics_button = page.locator(
            '[data-chart-gallery-page="basics-gallery.html"]'
        )
        basics_button.click()
        assert basics_button.get_attribute("aria-pressed") == "true"
        page.wait_for_function(
            """() => document.querySelector('[data-chart-gallery-frame]')
              ?.src.includes('basics-gallery.html')""",
            timeout=15000,
        )
        assert "v=20260727-1" in gallery_frame.get_attribute("src")
        gallery_page.wait_for_function(
            "() => document.querySelectorAll('svg > *').length >= 100",
            timeout=15000,
        )
        assert gallery.locator("svg > *").count() >= 100

        gallery_search = page.locator("#chart-gallery-search")
        gallery_search.fill("三十天")
        page.wait_for_function(
            """() => document.querySelector('#chart-gallery-count')
              ?.textContent.includes('1 / 12')""",
            timeout=15000,
        )

        frame_box = gallery_frame.bounding_box()
        assert frame_box is not None
        scroll_before = page.evaluate("() => window.scrollY")
        page.mouse.move(
            frame_box["x"] + frame_box["width"] / 2,
            max(40, min(450, frame_box["y"] + 240)),
        )
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(250)
        scroll_after = page.evaluate("() => window.scrollY")

        assert scroll_after - scroll_before >= 500
    finally:
        context.close()


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_sales_charts_keep_keyboard_accessible_names_and_readable_type(
    browser: Browser,
    vite_base_url: str,
    width: int,
    height: int,
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/sales", wait_until="domcontentloaded")
        page.get_by_role("heading", name="核销表现", exact=True).wait_for(timeout=10000)
        figures = page.locator(".sales-echart")
        assert figures.count() == 2

        rainfall = figures.first
        accessible_name = rainfall.get_attribute("aria-label") or ""
        assert accessible_name == "月度下单与核销趋势图"
        assert "mock_sales" not in accessible_name
        assert len(accessible_name) < 40
        assert rainfall.get_attribute("aria-keyshortcuts") is not None

        rainfall.focus()
        page.keyboard.press("Enter")
        inspector = page.locator(".sales-chart-inspector").first
        assert "已锁定" in inspector.inner_text()

        initial_text = inspector.inner_text()
        page.keyboard.press("ArrowRight")
        assert inspector.inner_text() != initial_text
        page.keyboard.press("Escape")
        assert "方向键" in inspector.inner_text()

        font_sizes = figures.locator("svg text").evaluate_all(
            "elements => elements.map(element => parseFloat(getComputedStyle(element).fontSize))"
        )
        assert font_sizes
        assert min(font_sizes) >= 11
    finally:
        context.close()


def test_settlement_mock_filter_and_statement_use_the_same_store(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/settlement", wait_until="domcontentloaded")
        page.get_by_role("heading", name="单店分账", exact=True).wait_for(timeout=10000)

        expect(page.get_by_role("combobox", name="门店")).to_have_value(
            "上海浦东体验中心",
            timeout=10000,
        )
        page.get_by_role("region", name="账单状态").get_by_text(
            "上海浦东体验中心",
            exact=True,
        ).wait_for(timeout=10000)
    finally:
        context.close()


@pytest.mark.parametrize("filter_kind", ["store", "month"])
def test_settlement_does_not_offer_stale_statement_while_filter_refresh_is_pending(
    browser: Browser,
    vite_real_api_base_url: str,
    filter_kind: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    pending_billing_routes: list[object] = []
    try:
        install_settlement_user_route(page, "admin")
        meta = settlement_filter_meta()
        meta["stores"] = [
            {"storeId": "store_001", "storeName": "上海浦东体验中心"},
            {"storeId": "store_002", "storeName": "上海虹桥服务中心"},
        ]
        meta["statementMonths"] = ["2026-08", "2026-09"]
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(meta),
            ),
        )

        def fulfill_monthly(route) -> None:
            store_id = "store_002" if "/stores/store_002/" in route.request.url else "store_001"
            store_name = "上海虹桥服务中心" if store_id == "store_002" else "上海浦东体验中心"
            month = "2026-09" if "month=2026-09" in route.request.url else "2026-08"
            route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_monthly_data(store_id, store_name, month)),
            )

        def fulfill_billing(route) -> None:
            if "storeId=store_002" in route.request.url or "month=2026-09" in route.request.url:
                pending_billing_routes.append(route)
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "list": [billing_statement_data("store_001", "上海浦东体验中心")],
                    "total": 1,
                    "page": 1,
                    "pageSize": 1,
                    "metricScope": "MONTH",
                    "metrics": {"month": {"promotionAmountCent": 38000, "managementAmountCent": 9000}},
                }),
            )

        page.route("**/api/v1/stores/*/monthly-settlement?*", fulfill_monthly)
        page.route("**/api/v1/store-settlements?*", fulfill_billing)
        page.goto(
            f"{vite_real_api_base_url}/settlement?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_role("button", name="确认管理服务费", exact=True).wait_for(timeout=10000)

        if filter_kind == "store":
            store_filter = page.get_by_role("combobox", name="门店")
            store_filter.click()
            page.get_by_role("option", name="上海虹桥服务中心", exact=True).click()
        else:
            page.get_by_label("账期", exact=True).click()
            page.get_by_role("option", name="2026-09", exact=True).click()

        page.wait_for_timeout(100)
        assert len(pending_billing_routes) == 1

        assert page.get_by_role("button", name="确认管理服务费", exact=True).count() == 0
    finally:
        for pending_route in pending_billing_routes:
            pending_route.abort()
        context.close()


def test_settlement_version_conflict_closes_dialog_and_refreshes_statement(
    browser: Browser,
    vite_real_api_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    billing_requests = 0
    conflict_seen = False
    pending_billing_routes: list[object] = []
    try:
        install_settlement_user_route(page, "admin")
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_filter_meta()),
            ),
        )
        page.route(
            "**/api/v1/stores/store_001/monthly-settlement?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_monthly_data("store_001", "上海浦东体验中心")),
            ),
        )

        def fulfill_billing(route) -> None:
            nonlocal billing_requests
            billing_requests += 1
            if conflict_seen:
                pending_billing_routes.append(route)
                return
            version = 3 if conflict_seen else 2
            amount = 9000 if version == 2 else 9500
            route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "list": [billing_statement_data(
                        "store_001",
                        "上海浦东体验中心",
                        version=version,
                        management_amount_cent=amount,
                    )],
                    "total": 1,
                    "page": 1,
                    "pageSize": 1,
                    "metricScope": "MONTH",
                    "metrics": {"month": {"promotionAmountCent": 38000, "managementAmountCent": amount}},
                }),
            )

        page.route("**/api/v1/store-settlements?*", fulfill_billing)

        def reject_confirmation(route) -> None:
            nonlocal conflict_seen
            conflict_seen = True
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({
                    "detail": {
                        "code": "VERSION_CONFLICT",
                        "message": "账单版本已变化",
                        "requestId": "req-confirm-409",
                    }
                }, ensure_ascii=False),
            )

        page.route(
            "**/api/v1/store-settlements/*/confirmations",
            reject_confirmation,
        )
        page.goto(
            f"{vite_real_api_base_url}/settlement?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_role("button", name="确认管理服务费", exact=True).click()
        requests_before_confirmation = billing_requests
        dialog = page.get_by_role("dialog", name="确认管理服务费")
        with page.expect_response(
            lambda response: response.url.endswith("/confirmations"),
            timeout=10000,
        ) as conflict_response:
            dialog.get_by_role("button", name="确认提交", exact=True).click()

        assert conflict_response.value.status == 409
        expect(dialog).to_be_hidden(timeout=10000)
        page.wait_for_timeout(100)
        assert len(pending_billing_routes) == 1
        assert page.get_by_role("button", name="确认管理服务费", exact=True).count() == 0

        pending_billing_routes.pop().fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "list": [billing_statement_data(
                    "store_001",
                    "上海浦东体验中心",
                    version=3,
                    management_amount_cent=9500,
                )],
                "total": 1,
                "page": 1,
                "pageSize": 1,
                "metricScope": "MONTH",
                "metrics": {"month": {"promotionAmountCent": 38000, "managementAmountCent": 9500}},
            }),
        )
        expect(page.get_by_text("当前金额 ¥95.00", exact=False)).to_be_visible(timeout=10000)
        assert billing_requests > requests_before_confirmation
    finally:
        for pending_route in pending_billing_routes:
            pending_route.abort()
        context.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_sales_chart_tokens_keep_runtime_contrast(
    browser: Browser,
    vite_base_url: str,
    theme: str,
) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        color_scheme=theme,
    )
    context.add_init_script(
        f"window.localStorage.setItem('dydata.theme.preference', '{theme}')",
    )
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/sales", wait_until="domcontentloaded")
        page.locator(".sales-echart").first.wait_for(timeout=10000)
        colors = page.evaluate(
            """
            () => {
              const probe = document.createElement('span');
              document.body.append(probe);
              const read = (name) => {
                probe.style.color = `var(${name})`;
                return getComputedStyle(probe).color;
              };
              const result = {
                axisText: read('--chart-axis-text'),
                dataNeutralSoft: read('--chart-data-neutral-soft'),
                primary: read('--chart-primary'),
                surface: read('--chart-surface'),
              };
              probe.remove();
              return result;
            }
            """,
        )
        assert contrast_ratio(colors["axisText"], colors["surface"]) >= 4.5
        assert contrast_ratio(colors["dataNeutralSoft"], colors["surface"]) >= 3
        assert contrast_ratio(colors["primary"], colors["surface"]) >= 3
    finally:
        context.close()


def test_ranking_uses_backend_enum_contract_and_latest_sale_month(
    browser: Browser,
    vite_real_api_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    ranking_urls: list[str] = []
    try:
        install_settlement_user_route(page, "admin")
        meta = settlement_filter_meta()
        meta["saleMonths"] = ["2026-07"]
        meta["statementMonths"] = ["2026-08"]
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(meta),
            ),
        )

        def fulfill_ranking(route: object) -> None:
            request = getattr(route, "request")
            ranking_urls.append(str(request.url))
            getattr(route, "fulfill")(
                status=200,
                content_type="application/json",
                body=api_payload(
                    {
                        "periodType": "MONTHLY",
                        "periodKey": "2026-07",
                        "productScope": "all",
                        "productType": "all",
                        "scopeMode": "AUTHORIZED",
                        "totals": {
                            "salesOrderCount": 1,
                            "salesAmountCent": 10000,
                            "verifiedOrderCount": 1,
                            "verifiedAmountCent": 10000,
                            "promotionNetFeeCent": 800,
                            "managementNetFeeCent": 400,
                            "netSettlementReferenceCent": 400,
                        },
                        "list": [],
                        "total": 0,
                        "page": 1,
                        "pageSize": 20,
                    }
                ),
            )

        page.route("**/api/v1/dashboard/store-ranking?*", fulfill_ranking)
        page.goto(f"{vite_real_api_base_url}/ranking", wait_until="domcontentloaded")
        page.get_by_text("当前筛选下没有门店结果。", exact=True).wait_for(timeout=10000)

        assert ranking_urls
        request_url = ranking_urls[-1]
        assert "periodKey=2026-07" in request_url
        assert "sortBy=NET_SETTLEMENT_REFERENCE" in request_url
        assert "sortOrder=DESC" in request_url
    finally:
        context.close()


def test_order_details_direct_url_loads_authorized_default_scope(
    browser: Browser,
    vite_real_api_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    order_detail_requests: list[str] = []
    try:
        install_settlement_user_route(page, "admin")
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_filter_meta()),
            ),
        )

        def record_request(route: object) -> None:
            request = getattr(route, "request")
            order_detail_requests.append(str(request.url))
            payload = order_fee_details_data(empty=True)
            payload["context"] = {
                **payload["context"],
                "storeId": None,
                "month": None,
            }
            getattr(route, "fulfill")(
                status=200,
                content_type="application/json",
                body=api_payload(payload),
            )

        page.route("**/api/v1/order-fee-details*", record_request)
        page.goto(
            f"{vite_real_api_base_url}/details?feeRates=0.990000&ruleVersions=stale-rule",
            wait_until="domcontentloaded",
        )
        page.get_by_text("当前筛选下没有费用记录。", exact=True).wait_for(timeout=10000)
        assert page.get_by_text("当前账号授权范围", exact=False).first.is_visible()
        assert page.get_by_role("button", name="返回单店分账", exact=True).count() == 0
        assert page.get_by_role("button", name="管理服务费", exact=True).is_enabled()
        assert order_detail_requests
        assert len(order_detail_requests) <= 2
        assert len(set(order_detail_requests)) == 1
        for request_url in order_detail_requests:
            assert "feeDirection=PROMOTION" in request_url
            assert "storeId=" not in request_url
            assert "month=" not in request_url
            assert "feeRates=" not in request_url
            assert "ruleVersions=" not in request_url
    finally:
        context.close()


def test_order_details_direct_export_omits_source_rate_context(
    browser: Browser,
    vite_real_api_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    export_requests: list[str] = []
    try:
        install_settlement_user_route(page, "admin")
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_filter_meta()),
            ),
        )

        def fulfill_export(route: object) -> None:
            request = getattr(route, "request")
            export_requests.append(str(request.url))
            getattr(route, "fulfill")(
                status=200,
                content_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="order-fees.csv"'},
                body="orderId,feeDirection\nORDER-VISUAL-001,PROMOTION\n",
            )

        def fulfill_details(route: object) -> None:
            payload = order_fee_details_data()
            payload["context"] = {
                **payload["context"],
                "storeId": None,
                "month": None,
            }
            getattr(route, "fulfill")(
                status=200,
                content_type="application/json",
                body=api_payload(payload),
            )

        page.route("**/api/v1/order-fee-details/export*", fulfill_export)
        page.route("**/api/v1/order-fee-details?*", fulfill_details)
        page.goto(f"{vite_real_api_base_url}/details", wait_until="domcontentloaded")
        page.get_by_text("ORDER-VISUAL-001", exact=True).first.wait_for(timeout=10000)

        with page.expect_download(timeout=10000):
            page.get_by_role("button", name="导出", exact=True).click()

        assert len(export_requests) == 1
        assert "storeId=" not in export_requests[0]
        assert "month=" not in export_requests[0]
        assert "feeRates=" not in export_requests[0]
        assert "ruleVersions=" not in export_requests[0]
    finally:
        context.close()


def test_order_fee_details_displays_structured_request_id(
    browser: Browser,
    vite_real_api_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_settlement_user_route(page, "admin")
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_filter_meta()),
            ),
        )
        page.route(
            "**/api/v1/order-fee-details*",
            lambda route: route.fulfill(
                status=422,
                content_type="application/json",
                body=json.dumps(
                    {
                        "detail": {
                            "code": "VALIDATION_FAILED",
                            "message": "请求字段校验失败",
                            "errors": [],
                            "requestId": "req-visual-422",
                        }
                    }
                ),
            ),
        )
        page.goto(
            f"{vite_real_api_base_url}/details?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_text("请求编号：req-visual-422", exact=False).first.wait_for(timeout=10000)
    finally:
        context.close()


@pytest.mark.parametrize(
    ("status", "expected_text"),
    [
        (403, "当前账号没有查看或导出该门店明细的权限。"),
        (409, "当前筛选没有可导出的记录。"),
        (422, "来源上下文已变化，请返回单店分账重新进入。"),
    ],
)
def test_order_fee_details_exposes_real_api_error_states(
    browser: Browser,
    vite_real_api_base_url: str,
    status: int,
    expected_text: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_api_routes(page)
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_filter_meta()),
            ),
        )
        page.route(
            "**/api/v1/order-fee-details*",
            lambda route: route.fulfill(
                status=status,
                content_type="application/json",
                body=json.dumps({"detail": f"visual error {status}"}),
            ),
        )
        page.goto(
            f"{vite_real_api_base_url}/details?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )

        page.locator("h1").wait_for(timeout=10000)
        page.wait_for_timeout(1500)
        body_text = page.locator("body").inner_text()
        assert expected_text in body_text, body_text
    finally:
        context.close()


@pytest.mark.parametrize("role", ["admin", "store"])
def test_order_fee_details_real_api_success_and_export_by_role(
    browser: Browser,
    vite_real_api_base_url: str,
    role: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_settlement_user_route(page, role)
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_filter_meta()),
            ),
        )
        page.route(
            "**/api/v1/order-fee-details/export*",
            lambda route: route.fulfill(
                status=200,
                content_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="order-fees.csv"'},
                body="orderId,feeDirection\nORDER-VISUAL-001,PROMOTION\n",
            ),
        )
        page.route(
            "**/api/v1/order-fee-details?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(order_fee_details_data()),
            ),
        )
        page.goto(
            f"{vite_real_api_base_url}/details?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )

        page.get_by_text("ORDER-VISUAL-001", exact=True).first.wait_for(timeout=10000)
        with page.expect_download(timeout=10000) as download_info:
            page.get_by_role("button", name="导出", exact=True).click()
        assert download_info.value.suggested_filename == "order-fees.csv"
    finally:
        context.close()


def test_order_fee_details_real_api_empty_state(
    browser: Browser,
    vite_real_api_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_settlement_user_route(page, "store")
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_filter_meta()),
            ),
        )
        page.route(
            "**/api/v1/order-fee-details?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(order_fee_details_data(empty=True)),
            ),
        )
        page.goto(
            f"{vite_real_api_base_url}/details?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )

        page.get_by_text("当前筛选下没有费用记录。", exact=True).wait_for(timeout=10000)
        assert page.get_by_role("button", name="导出", exact=True).is_disabled()
    finally:
        context.close()


def test_order_fee_details_export_surfaces_conflict(
    browser: Browser,
    vite_real_api_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_settlement_user_route(page, "admin")
        page.route(
            "**/api/v1/meta/filters",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(settlement_filter_meta()),
            ),
        )
        page.route(
            "**/api/v1/order-fee-details/export*",
            lambda route: route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"detail": "no export rows"}),
            ),
        )
        page.route(
            "**/api/v1/order-fee-details?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload(order_fee_details_data()),
            ),
        )
        page.goto(
            f"{vite_real_api_base_url}/details?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )

        page.get_by_text("ORDER-VISUAL-001", exact=True).first.wait_for(timeout=10000)
        page.get_by_role("button", name="导出", exact=True).click()
        page.get_by_text("当前筛选没有可导出的记录。", exact=True).wait_for(timeout=10000)
    finally:
        context.close()


def test_settlement_pages_connect_to_live_fastapi_for_roles_and_error_states(
    browser: Browser,
    vite_live_api_base_url: str,
    live_fastapi_base_url: str,
) -> None:
    admin_context = browser.new_context(viewport={"width": 1440, "height": 900})
    admin_context.add_cookies(
        [{"name": "dy_e2e_role", "value": "admin", "url": live_fastapi_base_url}]
    )
    admin_page = admin_context.new_page()
    try:
        admin_page.goto(f"{vite_live_api_base_url}/ranking", wait_until="domcontentloaded")
        admin_page.get_by_text("上海浦东体验中心", exact=True).first.wait_for(timeout=10000)
        assert "全国门店月度榜单" in admin_page.locator("body").inner_text()
    finally:
        admin_context.close()

    store_context = browser.new_context(viewport={"width": 1440, "height": 900})
    store_context.add_cookies(
        [{"name": "dy_e2e_role", "value": "store", "url": live_fastapi_base_url}]
    )
    page = store_context.new_page()
    try:
        details_url = f"{vite_live_api_base_url}/details?storeId=store_001&month=2026-08"
        page.goto(details_url, wait_until="domcontentloaded")
        page.get_by_text("ORDER-LIVE-001", exact=True).first.wait_for(timeout=10000)
        page.get_by_text("已支付 / 已核销", exact=True).first.wait_for(timeout=10000)
        with page.expect_download(timeout=10000):
            page.get_by_role("button", name="导出", exact=True).click()

        page.goto(f"{details_url}&q=missing", wait_until="domcontentloaded")
        page.get_by_text("当前筛选下没有费用记录。", exact=True).wait_for(timeout=10000)

        page.goto(
            f"{vite_live_api_base_url}/details?storeId=store_002&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_text("当前账号没有查看或导出该门店明细的权限。", exact=False).first.wait_for(timeout=10000)

        page.goto(
            f"{vite_live_api_base_url}/details?statementId=expired&statementLineId=line-live-1&feeDirection=PROMOTION",
            wait_until="domcontentloaded",
        )
        page.get_by_text("请求编号：req-live-expired", exact=False).first.wait_for(timeout=10000)

        page.goto(f"{details_url}&q=export-empty", wait_until="domcontentloaded")
        page.get_by_text("ORDER-LIVE-001", exact=True).first.wait_for(timeout=10000)
        page.get_by_role("button", name="导出", exact=True).click()
        page.get_by_text("当前筛选没有可导出的记录。", exact=False).first.wait_for(timeout=10000)
    finally:
        store_context.close()


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize(
    ("name", "url_path", "expected_text", "ready_target"),
    RUNTIME_SURFACES,
)
def test_all_runtime_surfaces_render_in_dark_theme(
    browser: Browser,
    vite_base_url: str,
    tmp_path: Path,
    name: str,
    url_path: str,
    expected_text: str,
    ready_target: str,
    width: int,
    height: int,
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme="dark",
    )
    context.add_init_script(
        "window.localStorage.setItem('dydata.theme.preference', 'dark')",
    )
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    http_errors: list[str] = []
    page.on("console", lambda message: record_console_error(message, console_errors))
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "response",
        lambda response: record_unexpected_http_failure(response, http_errors),
    )

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}{url_path}", wait_until="domcontentloaded")
        if ready_target == "heading":
            page.get_by_role("heading", name=expected_text, exact=True).wait_for(
                timeout=10000,
            )
        else:
            page.get_by_text(expected_text, exact=False).first.wait_for(timeout=10000)

        page.screenshot(
            path=tmp_path / f"{name}-dark-{width}.png",
            full_page=True,
        )
        metrics = page.evaluate(
            """() => ({
              bodyBackground: getComputedStyle(document.body).backgroundColor,
              horizontalOverflow:
                Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
                window.innerWidth,
              textLength: document.body.innerText.trim().length,
              theme: document.documentElement.dataset.theme,
              preference: document.documentElement.dataset.themePreference,
            })""",
        )

        assert metrics["theme"] == "dark"
        assert metrics["preference"] == "dark"
        assert metrics["bodyBackground"] == "rgb(16, 17, 15)"
        assert metrics["textLength"] > 20
        assert metrics["horizontalOverflow"] <= 2
        assert page.locator("h1").count() == 1
        assert console_errors == []
        assert page_errors == []
        assert http_errors == []
    finally:
        context.close()


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_commission_dashboard_mock_peer_routes_and_cumulative_state(
    browser: Browser,
    width: int,
    height: int,
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda message: record_console_error(message, console_errors))
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    try:
        page.goto(COMMISSION_MOCK_HTML.as_uri(), wait_until="domcontentloaded")
        for route, heading in (
            ("ranking", "全国门店榜单"),
            ("store", "单店分账"),
            ("orders", "订单费用明细"),
            ("invoice", "开票确认"),
        ):
            page.locator(f'.peer-nav a[data-route="{route}"]').click()
            page.get_by_role("heading", name=heading, exact=True).wait_for()
            assert (
                page.locator(f'.peer-nav a[data-route="{route}"]')
                .get_attribute("aria-current")
                == "page"
            )
            horizontal_overflow = page.evaluate(
                "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth"
            )
            assert horizontal_overflow <= 2

        page.locator('.peer-nav a[data-route="ranking"]').click()
        page.get_by_label("日期范围").select_option("all")
        page.get_by_role("heading", name="全国门店累计销售情况榜单").wait_for()
        page.get_by_text("累计排名将在 2026-08 正式账期启用", exact=False).wait_for()
        assert console_errors == []
        assert page_errors == []
    finally:
        context.close()


def test_commission_dashboard_mock_fee_links_keep_context_and_focus_workbench(
    browser: Browser,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        page.goto(
            f"{COMMISSION_MOCK_HTML.as_uri()}#/store",
            wait_until="domcontentloaded",
        )
        promotion_link = page.get_by_role("link", name="查看订单").first
        promotion_link.click()
        page.get_by_role("heading", name="推广费订单明细", exact=True).wait_for()
        assert page.locator('button[data-direction="promotion"]').get_attribute(
            "aria-pressed"
        ) == "true"
        for key in (
            "month=2026-07",
            "store=ST-SH-001",
            "product_scope=",
            "product_type=",
            "direction=promotion",
            "ratio=",
            "version=V2026.07.1",
            "focus=workbench",
        ):
            assert key in page.url
        page.wait_for_function("() => window.scrollY > 0")
        assert page.evaluate("() => window.scrollY") > 0

        page.goto(
            f"{COMMISSION_MOCK_HTML.as_uri()}#/store",
            wait_until="domcontentloaded",
        )
        management_link = page.get_by_role("link", name="查看订单").last
        management_link.click()
        page.get_by_role("heading", name="管理服务费订单明细", exact=True).wait_for()
        assert page.locator('button[data-direction="management"]').get_attribute(
            "aria-pressed"
        ) == "true"
        assert "direction=management" in page.url

        page.goto(
            f"{COMMISSION_MOCK_HTML.as_uri()}#/orders?month=%22%5D&direction=management&focus=workbench",
            wait_until="domcontentloaded",
        )
        page.get_by_role("heading", name="管理服务费订单明细", exact=True).wait_for()
        assert page.locator('button[data-direction="management"]').get_attribute(
            "aria-pressed"
        ) == "true"
        assert page_errors == []
    finally:
        context.close()


@pytest.mark.parametrize(
    ("url_path", "current_label"),
    [
        ("/admin/clue-allocation/rules", "分配规则"),
        ("/admin/clue-allocation/trial", "分配试运行"),
        ("/admin/clue-allocation/records", "分配记录"),
        ("/admin/clue-allocation/headquarters", "总部线索池"),
    ],
)
def test_clue_allocation_tertiary_navigation_uses_stable_routes_and_v02_state(
    browser: Browser,
    vite_base_url: str,
    url_path: str,
    current_label: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}{url_path}", wait_until="domcontentloaded")
        page.get_by_role("heading", name="线索分配", exact=True).wait_for(timeout=10000)

        navigation = page.get_by_role("navigation", name="线索分配功能")
        links = navigation.locator("a.tertiary-nav__item")
        links.first.wait_for(state="visible", timeout=10000)
        current = navigation.locator('a.tertiary-nav__item[aria-current="page"]')
        assert links.count() == 4
        assert navigation.locator("svg").count() == 0
        assert current.inner_text() == current_label
        assert current.get_attribute("aria-current") == "page"

        metrics = current.evaluate(
            """(node) => {
              const style = getComputedStyle(node);
              const rect = node.getBoundingClientRect();
              return {
                borderBottomColor: style.borderBottomColor,
                height: rect.height,
              };
            }"""
        )
        assert metrics["borderBottomColor"] == "rgb(254, 82, 5)"
        assert metrics["height"] >= 38
    finally:
        context.close()


@pytest.mark.parametrize(
    "url_path,current_label",
    [
        ("/admin/clue-allocation/rules", "分配规则"),
        ("/admin/clue-allocation/trial", "分配试运行"),
        ("/admin/clue-allocation/records", "分配记录"),
        ("/admin/clue-allocation/headquarters", "总部线索池"),
    ],
)
def test_clue_demo_admin_allocation_uses_demo_identity_without_api_requests(
    browser: Browser,
    vite_clue_demo_base_url: str,
    url_path: str,
    current_label: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api_requests: list[str] = []
    page.on(
        "request",
        lambda request: api_requests.append(request.url)
        if "/api/v1/" in request.url
        else None,
    )
    page.route("**/api/v1/**", lambda route: route.abort())
    try:
        page.goto(
            f"{vite_clue_demo_base_url}{url_path}",
            wait_until="domcontentloaded",
        )
        page.get_by_role("heading", name="线索分配", exact=True).wait_for(timeout=10000)
        page.get_by_role("navigation", name="线索分配功能").get_by_role(
            "link",
            name=current_label,
            exact=True,
        ).wait_for(timeout=10000)
        assert api_requests == []
    finally:
        context.close()


@pytest.mark.parametrize(
    "url_path",
    ["/finance/promotion", "/settlement", "/admin/accounts"],
)
def test_clue_demo_keeps_non_clue_routes_on_live_identity_and_api(
    browser: Browser,
    vite_clue_demo_base_url: str,
    url_path: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.route("**/api/v1/auth/me", lambda route: route.abort())
    try:
        with page.expect_request("**/api/v1/auth/me", timeout=10000):
            page.goto(
                f"{vite_clue_demo_base_url}{url_path}",
                wait_until="domcontentloaded",
            )
    finally:
        context.close()


def test_clue_secondary_navigation_marks_only_the_most_specific_route_current(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/clues/details", wait_until="domcontentloaded")
        page.get_by_text("线索跟进列表", exact=False).first.wait_for(timeout=10000)

        navigation = page.get_by_role("navigation", name="线索中心导航")
        current_links = navigation.locator('a[aria-current="page"]')

        assert current_links.count() == 1
        assert current_links.first.inner_text() == "线索明细"
        assert (
            navigation.get_by_role("link", name="线索看板", exact=True).get_attribute(
                "aria-current"
            )
            is None
        )
    finally:
        context.close()


@pytest.mark.parametrize("width,height", [*VIEWPORTS, (949, 466)])
def test_finance_primary_navigation_precedes_admin_and_has_exclusive_current_state(
    browser: Browser,
    vite_base_url: str,
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()

    try:
        page.set_default_navigation_timeout(60000)
        install_api_routes(page)
        page.goto(f"{vite_base_url}/finance/promotion", wait_until="domcontentloaded")
        page.get_by_role("heading", name="推广服务费", exact=True).wait_for(timeout=30000)

        navigation_name = "一级导航" if width <= 920 else None
        navigation = (
            page.get_by_role("navigation", name=navigation_name)
            if navigation_name
            else page.locator(".rail-nav")
        )
        labels = [
            text.splitlines()[0]
            for text in navigation.locator("a").all_inner_texts()
        ]
        assert labels.index("财务") + 1 == labels.index("后台")
        for label in ("财务", "后台"):
            link_box = navigation.locator("a").nth(labels.index(label)).bounding_box()
            assert link_box is not None
            assert link_box["y"] >= 0
            assert link_box["y"] + link_box["height"] <= height
        current_labels = [
            text.splitlines()[0]
            for text in navigation.locator('a[aria-current="page"]').all_inner_texts()
        ]
        assert current_labels == ["财务"]
        page.screenshot(
            path=tmp_path / f"dydata-81-finance-navigation-{width}x{height}.png",
            full_page=False,
        )

        page.goto(f"{vite_base_url}/admin", wait_until="domcontentloaded")
        page.get_by_role("heading", name="抖音经营中枢后台", exact=True).wait_for(timeout=30000)
        current_labels = [
            text.splitlines()[0]
            for text in navigation.locator('a[aria-current="page"]').all_inner_texts()
        ]
        assert current_labels == ["后台"]
    finally:
        context.close()


def test_store_navigation_hides_finance_and_sap_and_direct_finance_store_is_forbidden(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_settlement_user_route(page, "store")
        page.goto(f"{vite_base_url}/settlement", wait_until="domcontentloaded")
        primary_navigation = page.locator(".rail-nav")
        primary_navigation.wait_for(timeout=10000)
        assert primary_navigation.get_by_role("link", name="财务", exact=True).count() == 0

        settlement_navigation = page.get_by_role(
            "navigation",
            name="订单分佣结算中心导航",
        )
        assert settlement_navigation.get_by_role("link", name="SAP 建议", exact=True).count() == 0

        page.goto(f"{vite_base_url}/finance/stores", wait_until="domcontentloaded")
        page.get_by_role(
            "heading",
            name="当前账号没有此页面权限",
            exact=True,
        ).wait_for(timeout=10000)
        assert primary_navigation.get_by_role("link", name="财务", exact=True).count() == 0
    finally:
        context.close()


def test_audited_internal_values_are_presented_as_user_facing_chinese(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/admin/sync", wait_until="domcontentloaded")
        page.get_by_text("数据同步管理", exact=False).first.wait_for(timeout=10000)
        sync_text = page.locator("body").inner_text()
        assert "订单数据同步" in sync_text
        assert "订单数据：拉取" in sync_text
        assert "开放接口未返回数据" in sync_text
        assert "open api returned 0 rows" not in sync_text
        assert "Worker" not in sync_text
        assert "worker" not in sync_text
        assert not re.search(r"\borders\b", sync_text)

        page.goto(f"{vite_base_url}/clues/details", wait_until="domcontentloaded")
        page.get_by_text("线索跟进列表", exact=False).first.wait_for(timeout=10000)
        page.get_by_role("button", name="查看详情").first.click()
        dialog = page.get_by_role("dialog", name="线索跟进详情")
        dialog.wait_for(timeout=10000)
        detail_text = dialog.inner_text()
        assert "履约中" in detail_text
        assert "fulfilling" not in detail_text
        assert not re.search(r"\bactive\b", detail_text)
        assert "protected" not in detail_text

        dialog.get_by_role("button", name="下一条线索").click()
        dialog.get_by_text("跟进有效期内", exact=True).wait_for(timeout=10000)
        next_detail_text = dialog.inner_text()
        assert "跟进保护期内" in next_detail_text
        assert "核销保护期内" in next_detail_text
        assert "fulfilling" not in next_detail_text
        assert not re.search(r"\bactive\b", next_detail_text)
        assert "protected" not in next_detail_text
    finally:
        context.close()


def test_admin_rules_renders_product_fee_and_atomic_import_workflow(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/admin/rules", wait_until="domcontentloaded")
        page.get_by_role("heading", name="商品分账规则管理", exact=True).wait_for(timeout=10000)
        page.get_by_role("heading", name="1. SKU 查询与批量选择", exact=True).wait_for(timeout=10000)
        body = page.locator("body").inner_text()
        assert "商品人工分类" not in body
        assert "旧单费率兼容区" not in body
        assert "SKU-ID分佣比例确认" in body
        assert "8%" in body
        assert "2%" in body
        assert "已启用分佣商品列表" in body
        page.get_by_role("button", name="批量导入设置", exact=True).click()
        page.get_by_role("heading", name="批量导入设置", exact=True).wait_for(timeout=10000)
        assert "待原子提交" in page.locator("body").inner_text()
        assert "PENDING_COMMIT" not in body
    finally:
        context.close()


def test_admin_rules_invalid_import_explains_atomic_zero_write(
    browser: Browser,
    vite_base_url: str,
    tmp_path: Path,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    invalid_batch = {
        "batchId": "IMPORT-VISUAL-INVALID",
        "fileName": "invalid.csv",
        "batchStatus": "VALIDATION_FAILED",
        "commitMode": "ATOMIC",
        "effectiveDate": "2026-08-01",
        "totalCount": 1,
        "validCount": 0,
        "successCount": 0,
        "failedCount": 1,
        "uploadedBy": "visual-admin",
        "validatedAt": "2026-07-20T10:10:00Z",
        "committedAt": None,
        "hasResultFile": True,
    }
    try:
        install_api_routes(page)
        page.route(
            "**/api/v1/admin/sku-fee-rule-imports",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "batch": invalid_batch,
                    "errorPreview": [{
                        "rowNumber": 2,
                        "skuName": "错误商品",
                        "skuId": "SKU-INVALID",
                        "promotionServiceFeeRate": "2",
                        "managementServiceFeeRate": None,
                        "validationStatus": "INVALID",
                        "errors": [
                            {"field": "promotionServiceFeeRate", "code": "OUT_OF_RANGE", "message": "必须在 0 到 1 之间"},
                            {"field": "managementServiceFeeRate", "code": "REQUIRED", "message": "不能为空"},
                        ],
                        "createdRuleVersion": None,
                    }],
                    "hasMoreErrors": False,
                }),
            ),
        )
        file_path = tmp_path / "invalid.csv"
        file_path.write_text(
            "skuName,skuId,promotionServiceFeeRate,managementServiceFeeRate\n错误商品,SKU-INVALID,2,\n",
            encoding="utf-8",
        )
        page.goto(f"{vite_base_url}/admin/rules", wait_until="domcontentloaded")
        page.get_by_role("button", name="批量导入设置", exact=True).click()
        page.get_by_role("heading", name="批量导入设置", exact=True).wait_for(timeout=10000)
        page.locator('input[type="file"]').set_input_files(str(file_path))
        page.get_by_role("button", name="上传并预校验", exact=True).click()
        page.get_by_text("整批未写入", exact=False).first.wait_for(timeout=10000)
        body = page.locator("body").inner_text()
        assert "第 2 行" in body
        assert "promotionServiceFeeRate：必须在 0 到 1 之间" in body
        assert "managementServiceFeeRate：不能为空" in body
        assert page.get_by_role("button", name="确认原子提交", exact=True).is_disabled()
    finally:
        context.close()


def test_admin_rules_switching_import_batch_replaces_stale_row_errors(
    browser: Browser,
    vite_base_url: str,
    tmp_path: Path,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    uploaded_batch = {
        "batchId": "IMPORT-UPLOADED-INVALID",
        "fileName": "uploaded-invalid.csv",
        "batchStatus": "VALIDATION_FAILED",
        "commitMode": "ATOMIC",
        "effectiveDate": "2026-08-01",
        "totalCount": 1,
        "validCount": 0,
        "successCount": 0,
        "failedCount": 1,
        "uploadedBy": "visual-admin",
        "validatedAt": "2026-07-20T10:10:00Z",
        "committedAt": None,
        "hasResultFile": True,
    }
    historical_batch = {
        **uploaded_batch,
        "batchId": "IMPORT-HISTORICAL-INVALID",
        "fileName": "historical-invalid.csv",
    }
    try:
        install_api_routes(page)
        page.route(
            "**/api/v1/admin/sku-fee-rule-imports",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "batch": uploaded_batch,
                    "errorPreview": [{
                        "rowNumber": 2,
                        "skuName": "旧错误商品",
                        "skuId": "SKU-OLD-ERROR",
                        "promotionServiceFeeRate": "2",
                        "managementServiceFeeRate": "0.1",
                        "validationStatus": "INVALID",
                        "errors": [{"field": "skuId", "code": "OLD_ERROR", "message": "旧批次错误"}],
                        "createdRuleVersion": None,
                    }],
                    "hasMoreErrors": False,
                }),
            ),
        )
        page.route(
            "**/api/v1/admin/sku-fee-rule-imports?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({"list": [historical_batch], "total": 1, "page": 1, "pageSize": 10}),
            ) if route.request.method == "GET" else route.fallback(),
        )
        page.route(
            "**/api/v1/admin/sku-fee-rule-imports/IMPORT-HISTORICAL-INVALID?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "batch": historical_batch,
                    "rows": {
                        "list": [{
                            "rowNumber": 7,
                            "skuName": "新错误商品",
                            "skuId": "SKU-NEW-ERROR",
                            "promotionServiceFeeRate": "0.08",
                            "managementServiceFeeRate": None,
                            "validationStatus": "INVALID",
                            "errors": [{"field": "managementServiceFeeRate", "code": "NEW_ERROR", "message": "新批次错误"}],
                            "createdRuleVersion": None,
                        }],
                        "total": 1,
                        "page": 1,
                        "pageSize": 200,
                    },
                }),
            ),
        )
        file_path = tmp_path / "uploaded-invalid.csv"
        file_path.write_text(
            "skuName,skuId,promotionServiceFeeRate,managementServiceFeeRate\n旧错误商品,SKU-OLD-ERROR,2,0.1\n",
            encoding="utf-8",
        )
        page.goto(f"{vite_base_url}/admin/rules", wait_until="domcontentloaded")
        page.get_by_role("button", name="批量导入设置", exact=True).click()
        page.locator('input[type="file"]').set_input_files(str(file_path))
        page.get_by_role("button", name="上传并预校验", exact=True).click()
        page.get_by_text("旧批次错误", exact=False).wait_for(timeout=10000)
        page.get_by_role("button", name="historical-invalid.csv", exact=False).click()
        page.get_by_text("新批次错误", exact=False).wait_for(timeout=10000)
        assert page.get_by_text("旧批次错误", exact=False).count() == 0
    finally:
        context.close()


def test_admin_fee_publish_reuses_idempotency_key_after_uncertain_network_failure(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    observed_keys: list[str] = []
    attempts = 0

    def handle_publish(route) -> None:
        nonlocal attempts
        attempts += 1
        observed_keys.append(route.request.headers.get("idempotency-key", ""))
        if attempts == 1:
            route.abort("timedout")
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "ruleVersion": "SFR-RETRY-VISUAL",
                "skuId": "SKU-VISUAL-001",
                "skuName": "精诚养车基础保养",
                "productScope": "精诚养车",
                "productType": "基础保养",
                "promotionServiceFeeRate": "0.080000",
                "managementServiceFeeRate": "0.100000",
                "effectiveDate": "2026-08-02",
                "effectiveAt": "2026-08-02T00:00:00+08:00",
                "ruleStatus": "ACTIVE",
                "previousRuleVersion": "SFR-20260801-VISUAL",
                "createdBy": "visual-admin",
                "changeReason": "网络不确定重试",
                "publishedAt": "2026-07-20T10:20:00Z",
            }),
        )

    try:
        install_api_routes(page)
        page.route("**/api/v1/admin/sku-fee-rules", handle_publish)
        page.goto(f"{vite_base_url}/admin/rules", wait_until="domcontentloaded")
        selection_section = page.get_by_role(
            "heading", name="1. SKU 查询与批量选择", exact=True
        ).locator("xpath=ancestor::section")
        selection_section.get_by_label("SKU ID", exact=True).fill("SKU-VISUAL-001")
        selection_section.get_by_role("button", name="查询并选择", exact=True).click()
        section = page.get_by_role("heading", name="2. SKU-ID分佣比例确认", exact=True).locator("xpath=ancestor::section")
        section.get_by_label("两项费率一致", exact=True).uncheck()
        section.get_by_label("推广服务费比例（%）", exact=True).fill("8")
        section.get_by_label("管理服务费比例（%）", exact=True).fill("10")
        section.get_by_label("生效日期", exact=True).fill("2026-08-02")
        section.get_by_label("变更原因", exact=True).fill("网络不确定重试")
        section.get_by_role("button", name="应用比例并检查预选", exact=True).click()
        page.get_by_role("button", name="确认发布", exact=True).first.click()
        dialog = page.get_by_role("dialog", name="分佣规则发布确认")
        dialog.get_by_role("button", name="确认发布", exact=True).click()
        page.get_by_text("发布中断", exact=False).wait_for(timeout=10000)
        dialog.get_by_role("button", name="确认发布", exact=True).click()
        page.get_by_text("已发布 1 个 SKU", exact=False).wait_for(timeout=10000)
        assert len(observed_keys) == 2
        assert len(observed_keys[0]) >= 16
        assert observed_keys[0] == observed_keys[1]
    finally:
        context.close()


def test_admin_sync_renders_safe_product_sync_history(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/admin/sync", wait_until="domcontentloaded")
        page.get_by_role("heading", name="商品主数据同步", exact=True).wait_for(timeout=10000)
        page.get_by_role("button", name="查看详情", exact=True).click()
        page.get_by_role("heading", name="运行详情", exact=True).wait_for(timeout=10000)
        body = page.locator("body").inner_text()
        assert "增量同步" in body
        assert "成功" in body
        assert "最近成功同步" in body
        assert "数据质量问题" in body
        assert "受影响 SKU 样例" in body
        assert "nextCursorMasked" not in body
        assert "cookie" not in body.lower()
        assert "token" not in body.lower()
    finally:
        context.close()


def test_admin_sync_displays_stable_code_and_sanitized_error_summary(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    failed_run = {
        "syncRunId": "PRODUCT-SYNC-VISUAL-FAILED",
        "mode": "INCREMENTAL",
        "status": "FAILED",
        "startedAt": "2026-07-20T08:00:00Z",
        "finishedAt": "2026-07-20T08:01:00Z",
        "observedCount": 3,
        "insertedCount": 0,
        "updatedCount": 0,
        "unchangedCount": 0,
        "failedCount": 3,
        "latestSuccessfulSyncedAt": "2026-07-19T08:00:00Z",
        "nextCursorMasked": None,
        "errorCode": "DOUYIN_UPSTREAM_FAILED",
        "errorMessage": "上游商品服务暂时不可用，请稍后重试",
    }
    try:
        install_api_routes(page)
        page.route(
            "**/api/v1/admin/product-sync-runs?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({"list": [failed_run], "total": 1, "page": 1, "pageSize": 20}),
            ),
        )
        page.route(
            "**/api/v1/admin/product-sync-runs/PRODUCT-SYNC-VISUAL-FAILED",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "run": failed_run,
                    "phaseCounts": {"fetch": 3},
                    "affectedSkuSample": [],
                    "dataQualityIssueCount": 3,
                    "retryable": True,
                }),
            ),
        )
        page.goto(f"{vite_base_url}/admin/sync", wait_until="domcontentloaded")
        page.get_by_role("button", name="查看详情", exact=True).click()
        page.get_by_text("DOUYIN_UPSTREAM_FAILED", exact=True).wait_for(timeout=10000)
        page.get_by_text("上游商品服务暂时不可用，请稍后重试", exact=True).wait_for(timeout=10000)
        body = page.locator("body").inner_text().lower()
        assert "cookie" not in body
        assert "token" not in body
    finally:
        context.close()


def test_admin_rules_uses_live_fastapi_for_save_reload_publish_and_conflict(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies(
        [{"name": "dy_e2e_role", "value": "admin", "url": live_admin_fastapi_base_url}]
    )
    page = context.new_page()
    try:
        page.goto(
            f"{vite_live_admin_api_base_url}/admin/rules",
            wait_until="domcontentloaded",
        )
        page.get_by_role("tab", name="未启用分佣商品列表", exact=False).click()
        selection_section = page.get_by_role(
            "heading", name="1. SKU 查询与批量选择", exact=True
        ).locator("xpath=ancestor::section")
        selection_section.get_by_label("SKU ID", exact=True).fill("SKU-LIVE-ADMIN-001")
        selection_section.get_by_role("button", name="查询并选择", exact=True).click()
        fee_section = page.get_by_role(
            "heading", name="2. SKU-ID分佣比例确认", exact=True
        ).locator("xpath=ancestor::section")
        fee_section.get_by_label("两项费率一致", exact=True).uncheck()
        fee_section.get_by_label("推广服务费比例（%）", exact=True).fill("8")
        fee_section.get_by_label("管理服务费比例（%）", exact=True).fill("10")
        fee_section.get_by_label("生效日期", exact=True).fill("2026-08-02")
        fee_section.get_by_label("变更原因", exact=True).fill("真实 FastAPI 首次发布")
        fee_section.get_by_role("button", name="应用比例并检查预选", exact=True).click()
        page.get_by_role("button", name="确认发布", exact=True).first.click()
        dialog = page.get_by_role("dialog", name="分佣规则发布确认")
        dialog.get_by_role("button", name="确认发布", exact=True).click()
        page.get_by_text("已发布 1 个 SKU", exact=False).wait_for(timeout=10000)

        page.get_by_role("tab", name="已启用分佣商品列表", exact=False).click()
        selection_section.get_by_role("button", name="查询并选择", exact=True).click()
        fee_section.get_by_label("变更原因", exact=True).fill("重复生效日冲突验证")
        fee_section.get_by_role("button", name="应用比例并检查预选", exact=True).click()
        page.get_by_role("button", name="确认发布", exact=True).first.click()
        dialog = page.get_by_role("dialog", name="分佣规则发布确认")
        dialog.get_by_role("button", name="确认发布", exact=True).click()
        page.get_by_text("该生效日期已存在版本", exact=False).wait_for(timeout=10000)
    finally:
        context.close()


def _write_fee_import_file(
    path: Path,
    rows: list[tuple[str, str, str, str]],
) -> None:
    headers = [
        "skuName",
        "skuId",
        "promotionServiceFeeRate",
        "managementServiceFeeRate",
    ]
    if path.suffix == ".csv":
        lines = [",".join(headers)]
        lines.extend(",".join(row) for row in rows)
        path.write_text("\ufeff" + "\n".join(lines) + "\n", encoding="utf-8")
        return
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(list(row))
    output = BytesIO()
    workbook.save(output)
    path.write_bytes(output.getvalue())


@pytest.mark.parametrize(
    ("extension", "valid_index", "invalid_index", "effective_date"),
    [
        (".csv", 2, 4, "2026-08-03"),
        (".xlsx", 3, 5, "2026-08-04"),
    ],
)
def test_admin_rules_uses_live_fastapi_for_atomic_import_and_result_file(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
    tmp_path: Path,
    extension: str,
    valid_index: int,
    invalid_index: int,
    effective_date: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies(
        [{"name": "dy_e2e_role", "value": "admin", "url": live_admin_fastapi_base_url}]
    )
    page = context.new_page()
    valid_sku = f"SKU-LIVE-ADMIN-{valid_index:03d}"
    invalid_sku = f"SKU-LIVE-ADMIN-{invalid_index:03d}"
    try:
        page.goto(
            f"{vite_live_admin_api_base_url}/admin/rules",
            wait_until="domcontentloaded",
        )
        page.get_by_role("button", name="批量导入设置", exact=True).click()
        section = page.get_by_role("dialog", name="批量导入设置")
        valid_file = tmp_path / f"valid{extension}"
        _write_fee_import_file(
            valid_file,
            [(f"真实联调保养 SKU {valid_index}", valid_sku, "0.08", "0.10")],
        )
        section.get_by_label("整批生效日期", exact=True).fill(effective_date)
        section.locator('input[type="file"]').set_input_files(str(valid_file))
        section.get_by_role("button", name="上传并预校验", exact=True).click()
        page.get_by_text("全量预校验通过", exact=False).wait_for(timeout=10000)
        section.get_by_label("提交变更原因", exact=True).fill(f"真实 {extension} 原子导入")
        section.get_by_role("button", name="确认原子提交", exact=True).click()
        page.get_by_text("整批已原子写入 1 条规则", exact=False).wait_for(timeout=10000)

        invalid_file = tmp_path / f"invalid{extension}"
        _write_fee_import_file(
            invalid_file,
            [(f"真实联调保养 SKU {invalid_index}", invalid_sku, "2", "0.10")],
        )
        section.get_by_label("整批生效日期", exact=True).fill(effective_date)
        section.locator('input[type="file"]').set_input_files(str(invalid_file))
        section.get_by_role("button", name="上传并预校验", exact=True).click()
        page.get_by_text("整批未写入", exact=False).first.wait_for(timeout=10000)
        assert section.get_by_role("button", name="确认原子提交", exact=True).is_disabled()
        with page.expect_download(timeout=10000):
            section.get_by_role("button", name="下载结果文件", exact=True).click()

        valid_response = json.loads(
            urllib.request.urlopen(
                f"{live_admin_fastapi_base_url}/api/v1/admin/sku-fee-rules?skuId={valid_sku}",
                timeout=10,
            ).read()
        )
        invalid_response = json.loads(
            urllib.request.urlopen(
                f"{live_admin_fastapi_base_url}/api/v1/admin/sku-fee-rules?skuId={invalid_sku}",
                timeout=10,
            ).read()
        )
        assert valid_response["data"]["total"] == 1
        assert invalid_response["data"]["total"] == 0
    finally:
        context.close()


def test_admin_sync_uses_live_fastapi_for_queued_success_failed_and_partial(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies(
        [{"name": "dy_e2e_role", "value": "admin", "url": live_admin_fastapi_base_url}]
    )
    page = context.new_page()
    try:
        page.goto(
            f"{vite_live_admin_api_base_url}/admin/sync",
            wait_until="domcontentloaded",
        )
        section = page.get_by_role(
            "heading", name="商品主数据同步", exact=True
        ).locator("xpath=ancestor::section")

        section.get_by_label("触发原因", exact=True).fill("真实浏览器成功同步")
        section.get_by_role("button", name="触发商品同步", exact=True).click()
        section.locator(".resource-notice").get_by_text("已入队", exact=False).wait_for(timeout=10000)
        section.get_by_text("成功", exact=True).first.wait_for(timeout=15000)

        section.get_by_label("触发原因", exact=True).fill("真实浏览器失败同步")
        section.get_by_role("button", name="触发商品同步", exact=True).click()
        section.locator(".resource-notice").get_by_text("已入队", exact=False).wait_for(timeout=10000)
        section.get_by_text("失败", exact=True).first.wait_for(timeout=15000)
        section.get_by_role("button", name="查看详情", exact=True).first.click()
        section.get_by_text("DOUYIN_UPSTREAM_FAILED", exact=True).wait_for(timeout=10000)
        section.get_by_text("上游商品服务暂时不可用，请稍后重试", exact=True).wait_for(timeout=10000)

        section.get_by_label("触发原因", exact=True).fill("真实浏览器部分同步")
        section.get_by_role("button", name="触发商品同步", exact=True).click()
        section.locator(".resource-notice").get_by_text("已入队", exact=False).wait_for(timeout=10000)
        section.get_by_text("部分成功", exact=True).first.wait_for(timeout=15000)
        section.get_by_role("button", name="查看详情", exact=True).first.click()
        section.get_by_text("PRODUCT_SYNC_PARTIAL", exact=True).wait_for(timeout=10000)
        section.get_by_text("1 个 SKU 校验失败，其他快照已提交", exact=True).wait_for(timeout=10000)

        body = section.inner_text().lower()
        assert "cookie" not in body
        assert "token" not in body
        assert "raw_payload" not in body
    finally:
        context.close()


def install_unauthenticated_route(page: Page) -> None:
    page.route(
        "**/api/v1/auth/me",
        lambda route: route.fulfill(
            status=401,
            content_type="application/json",
            body=json.dumps({"detail": "Not authenticated"}),
        ),
    )


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize(
    ("url_path", "expected_heading"),
    [
        ("/login", "账号登录"),
        ("/auth/activate", "账号激活"),
        ("/auth/reset-password", "重置密码"),
    ],
)
def test_auth_surfaces_follow_the_v02_visual_contract(
    browser: Browser,
    vite_base_url: str,
    url_path: str,
    expected_heading: str,
    width: int,
    height: int,
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    http_errors: list[str] = []
    page.on("console", lambda message: record_console_error(message, console_errors))
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "response",
        lambda response: record_unexpected_http_failure(response, http_errors),
    )

    try:
        install_unauthenticated_route(page)
        page.goto(f"{vite_base_url}{url_path}", wait_until="domcontentloaded")
        page.get_by_role("heading", name=expected_heading, exact=True).wait_for(
            timeout=10000,
        )

        horizontal_overflow = page.evaluate(
            "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth",
        )
        assert page.locator("h1").count() == 1
        assert horizontal_overflow <= 2
        assert console_errors == []
        assert page_errors == []
        assert http_errors == []
    finally:
        context.close()


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize(
    ("url_path", "expected_heading", "authenticated"),
    [
        ("/login", "账号登录", False),
        ("/auth/activate", "账号激活", False),
        ("/auth/reset-password", "重置密码", False),
        ("/auth/cli/authorize", "缺少授权码", True),
        ("/auth/mcp/authorize", "无法继续授权", True),
    ],
)
def test_auth_and_authorization_surfaces_render_dark_signature_contract(
    browser: Browser,
    vite_base_url: str,
    tmp_path: Path,
    url_path: str,
    expected_heading: str,
    authenticated: bool,
    width: int,
    height: int,
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme="dark",
    )
    context.add_init_script(
        "window.localStorage.setItem('dydata.theme.preference', 'dark')",
    )
    page = context.new_page()

    try:
        if authenticated:
            install_api_routes(page)
        else:
            install_unauthenticated_route(page)

        page.goto(f"{vite_base_url}{url_path}", wait_until="domcontentloaded")
        page.get_by_role("heading", name=expected_heading, exact=True).wait_for(
            timeout=10000,
        )
        signature = page.get_by_role("img", name="Powered by SPACE AI Native")
        signature.wait_for(timeout=10000)
        signature_contract = signature.evaluate(
            """(node) => {
              const copy = node.querySelector(
                '.dc-brand-attribution__copy .dc-brand-attribution__glyph',
              );
              const native = node.querySelector(
                '.dc-brand-attribution__native .dc-brand-attribution__glyph',
              );
              const ai = node.querySelector(
                '.dc-brand-attribution__ai .dc-brand-attribution__glyph',
              );
              const identity = node.querySelector('.dc-brand-attribution__mark');
              return {
                copyMask: copy ? getComputedStyle(copy).webkitMaskImage : "",
                nativeMask: native ? getComputedStyle(native).webkitMaskImage : "",
                aiColor: ai ? getComputedStyle(ai).backgroundColor : "",
                nativeColor: native ? getComputedStyle(native).backgroundColor : "",
                identityWidth: identity ? Math.round(identity.getBoundingClientRect().width) : 0,
                material: node.dataset.material ?? "",
                accentScope: node.dataset.accentScope ?? "",
                variant: node.dataset.variant ?? "",
                textContent: node.textContent?.trim() ?? "",
              };
            }""",
        )
        horizontal_overflow = page.evaluate(
            "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth",
        )

        page.screenshot(
            path=tmp_path / f"auth-dark-{expected_heading}-{width}.png",
            full_page=True,
        )
        assert page.locator("html").get_attribute("data-theme") == "dark"
        assert signature_contract["textContent"] == ""
        assert signature_contract["copyMask"] != "none"
        assert signature_contract["nativeMask"] != "none"
        assert signature_contract["aiColor"] == "rgb(254, 82, 5)"
        assert signature_contract["nativeColor"] == "rgb(183, 185, 177)"
        assert signature_contract["identityWidth"] == 108
        assert signature_contract["material"] == "flat"
        assert signature_contract["accentScope"] == "orbit-only"
        assert signature_contract["variant"] == "compact-horizontal"
        assert horizontal_overflow <= 2
        assert page.locator("h1").count() == 1
    finally:
        context.close()


@pytest.mark.parametrize(
    ("url_path", "expected_text", "selector"),
    [
        ("/clues/details", "线索跟进列表", ".clue-filter-bar"),
        ("/details", "推广费订单明细", ".detail-filter-bar--single-line"),
    ],
)
def test_detail_filter_bars_fit_one_desktop_row(
    browser: Browser,
    vite_base_url: str,
    url_path: str,
    expected_text: str,
    selector: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}{url_path}", wait_until="domcontentloaded")
        page.get_by_text(expected_text, exact=False).first.wait_for(timeout=10000)

        metrics = page.locator(selector).evaluate(
            """(node) => {
              const children = Array.from(node.children).filter(
                (child) => getComputedStyle(child).display !== "none",
              );
              const rows = new Set(
                children.map((child) => Math.round(child.getBoundingClientRect().bottom)),
              );
              return {
                childCount: children.length,
                clientWidth: node.clientWidth,
                rowCount: rows.size,
                scrollWidth: node.scrollWidth,
              };
            }""",
        )

        assert metrics["childCount"] > 0
        assert metrics["rowCount"] == 1
        assert metrics["scrollWidth"] - metrics["clientWidth"] <= 2
    finally:
        context.close()


def test_clue_filter_collapse_action_is_hidden_in_desktop_layout(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/clues/details", wait_until="domcontentloaded")
        page.get_by_text("线索跟进列表", exact=False).first.wait_for(timeout=10000)

        assert not page.get_by_role("button", name="收起筛选", exact=True).is_visible()
    finally:
        context.close()


def test_clue_filter_collapse_action_closes_the_narrow_filter_panel(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/clues/details", wait_until="domcontentloaded")
        page.get_by_text("线索跟进列表", exact=False).first.wait_for(timeout=10000)

        toggle = page.locator(".clue-filter-toggle")
        panel = page.locator("#clue-filter-panel")
        collapse = page.get_by_role("button", name="收起筛选", exact=True)

        assert toggle.get_attribute("aria-expanded") == "false"
        assert not panel.is_visible()
        toggle.click()
        assert toggle.get_attribute("aria-expanded") == "true"
        assert panel.is_visible()
        assert collapse.is_visible()

        collapse.click()
        assert toggle.get_attribute("aria-expanded") == "false"
        assert not panel.is_visible()
    finally:
        context.close()


def test_sales_metric_cards_share_one_white_card_treatment(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/sales", wait_until="domcontentloaded")
        page.get_by_role("heading", name="核销表现", exact=True).wait_for(timeout=10000)

        cards = page.locator(".metric-card")
        assert cards.count() == 6
        treatments = cards.evaluate_all(
            """(nodes) => nodes.map((node) => {
              const style = getComputedStyle(node);
              const accent = getComputedStyle(node, "::before");
              return {
                backgroundColor: style.backgroundColor,
                borderColor: style.borderColor,
                borderRadius: style.borderRadius,
                boxShadow: style.boxShadow,
                accentContent: accent.content,
                accentHeight: accent.height,
              };
            })""",
        )

        assert {item["backgroundColor"] for item in treatments} == {"rgb(255, 255, 255)"}
        assert len({item["borderColor"] for item in treatments}) == 1
        assert {item["borderRadius"] for item in treatments} == {"8px"}
        assert len({item["boxShadow"] for item in treatments}) == 1
        assert {item["accentContent"] for item in treatments} == {"none"}
        assert {item["accentHeight"] for item in treatments} == {"auto"}
    finally:
        context.close()


def test_workspace_global_actions_stay_at_the_topbar_inline_end(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/sales", wait_until="domcontentloaded")
        page.get_by_role("heading", name="核销表现", exact=True).wait_for(timeout=10000)

        topbar = page.locator(".workspace-topbar")
        actions = page.locator(".workspace-actions")
        identity = page.locator(".account-cluster__identity")
        command_buttons = page.locator(".account-cluster .utility-button")
        topbar_box = topbar.bounding_box()
        actions_box = actions.bounding_box()

        assert topbar_box is not None
        assert actions_box is not None
        assert actions_box["x"] > topbar_box["x"] + topbar_box["width"] / 2
        assert abs(
            (actions_box["x"] + actions_box["width"])
            - (topbar_box["x"] + topbar_box["width"] - 28)
        ) <= 1

        identity_treatment = identity.evaluate(
            """(node) => {
              const style = getComputedStyle(node);
              return { height: style.height, borderRadius: style.borderRadius };
            }""",
        )
        command_treatments = command_buttons.evaluate_all(
            """(nodes) => nodes.map((node) => {
              const style = getComputedStyle(node);
              return { height: style.height, borderRadius: style.borderRadius };
            })""",
        )

        assert identity_treatment == {"height": "38px", "borderRadius": "6px"}
        assert command_treatments
        assert all(
            treatment == identity_treatment for treatment in command_treatments
        )
    finally:
        context.close()


@pytest.mark.parametrize(
    ("url_path", "expected_text"),
    [
        ("/clues/details", "线索跟进列表"),
        ("/details?storeId=ST-SH-001&month=2026-08", "推广费订单明细"),
    ],
)
def test_desktop_detail_pages_keep_pagination_visible_and_scroll_table_region(
    browser: Browser,
    vite_base_url: str,
    url_path: str,
    expected_text: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}{url_path}", wait_until="domcontentloaded")
        page.get_by_text(expected_text, exact=False).first.wait_for(timeout=10000)

        metrics = page.evaluate(
            """() => {
              const frame = document.querySelector(".page-frame--data-workspace");
              const section = document.querySelector(".content-section--data-workspace");
              const tableWrap = document.querySelector(
                ".content-section--data-workspace .table-wrap--contained-sticky",
              );
              const pagination = document.querySelector(
                ".content-section--data-workspace .table-pagination",
              );
              if (!frame || !section || !tableWrap || !pagination) {
                return null;
              }
              const frameRect = frame.getBoundingClientRect();
              const sectionRect = section.getBoundingClientRect();
              const tableRect = tableWrap.getBoundingClientRect();
              const paginationRect = pagination.getBoundingClientRect();
              return {
                frameWidth: frameRect.width,
                rootVerticalOverflow:
                  Math.max(document.documentElement.scrollHeight, document.body.scrollHeight) -
                  window.innerHeight,
                sectionBottom: sectionRect.bottom,
                tableHeight: tableRect.height,
                paginationBottom: paginationRect.bottom,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
              };
            }""",
        )

        assert metrics is not None
        assert metrics["frameWidth"] >= metrics["viewportWidth"] - 120
        assert metrics["rootVerticalOverflow"] <= 2
        assert metrics["tableHeight"] >= 180
        assert metrics["paginationBottom"] <= metrics["viewportHeight"]
        assert metrics["sectionBottom"] <= metrics["viewportHeight"]
    finally:
        context.close()


def test_finance_pages_use_live_fastapi_for_admin_empty_and_store_forbidden(
    browser: Browser,
    vite_live_admin_api_base_url: str,
    live_admin_fastapi_base_url: str,
) -> None:
    admin_context = browser.new_context(viewport={"width": 1440, "height": 900})
    admin_page = admin_context.new_page()
    finance_responses: list[int] = []
    admin_page.on(
        "response",
        lambda response: finance_responses.append(response.status)
        if "/api/v1/admin/finance/" in response.url
        else None,
    )
    try:
        admin_page.goto(
            f"{vite_live_admin_api_base_url}/finance/promotion?month=2026-08",
            wait_until="domcontentloaded",
        )
        admin_page.get_by_role("heading", name="推广服务费", exact=True).wait_for(timeout=10000)
        admin_page.get_by_text("¥0.00", exact=True).first.wait_for(timeout=10000)
        assert finance_responses and all(status == 200 for status in finance_responses)
        assert admin_page.locator(".resource-notice--error").count() == 0
    finally:
        admin_context.close()

    store_context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        store_context.add_cookies([
            {
                "name": "dy_e2e_role",
                "value": "store",
                "url": live_admin_fastapi_base_url,
            }
        ])
        forbidden = store_context.request.get(
            f"{live_admin_fastapi_base_url}/api/v1/admin/finance/summary",
            params={
                "month": "2026-08",
                "feeDirection": "PROMOTION",
                "metricScope": "MONTH",
            },
        )
        assert forbidden.status == 403
        assert forbidden.json()["detail"]["code"] == "DATA_SCOPE_FORBIDDEN"
    finally:
        store_context.close()


def test_store_invoice_preserves_422_input_then_reads_back_success(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    posted_payloads: list[dict[str, object]] = []
    attempts = 0

    def register_invoice(route) -> None:
        nonlocal attempts
        attempts += 1
        posted_payloads.append(route.request.post_data_json)
        if attempts == 1:
            route.fulfill(
                status=422,
                content_type="application/json",
                body=json.dumps({
                    "detail": {
                        "code": "VALIDATION_FAILED",
                        "message": "发票信息校验失败，请核对后重试",
                        "errors": [{"field": "invoiceNumber", "reason": "发票号码已存在"}],
                        "requestId": "req-invoice-422",
                    }
                }, ensure_ascii=False),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "invoiceId": "INV-REGISTERED-001",
                "storeId": "store_001",
                "versionNo": 1,
                "isCurrent": True,
                "supersedesInvoiceId": None,
                "invoiceNumber": "12345678901234567890",
                "invoiceDate": "2026-08-08",
                "invoiceAmountCent": 38000,
                "buyerName": "比亚迪汽车销售有限公司",
                "taxRatePercent": 6,
                "status": "SUBMITTED_PENDING_FACTORY_REVIEW",
                "registeredAt": "2026-08-08T10:00:00+08:00",
                "statementId": "STMT-VISUAL-001",
                "statementMonth": "2026-08",
                "settlementBatchMonth": "2026-07",
                "allocatedAmountCent": 38000,
            }),
        )

    try:
        install_api_routes(page)
        page.route("**/api/v1/promotion-invoices", register_invoice)
        page.goto(
            f"{vite_base_url}/settlement/invoice?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_role("button", name="选择抵扣组").click()
        number = page.get_by_label("20 位数电专票号码")
        invoice_date = page.get_by_label("开票日期")
        number.fill("12345678901234567890")
        invoice_date.fill("2026-08-08")
        page.get_by_role("button", name="登记并提交").click()
        page.get_by_text("提交内容未通过校验，请检查后重试。", exact=True).wait_for(timeout=10000)
        assert number.input_value() == "12345678901234567890"
        assert invoice_date.input_value() == "2026-08-08"

        page.get_by_role("button", name="登记并提交").click()
        page.get_by_text("发票信息已登记，状态已更新。", exact=True).wait_for(timeout=10000)
        assert page.get_by_label("20 位数电专票号码").count() == 0
        assert posted_payloads[-1]["buyerName"] == "比亚迪汽车销售有限公司"
        assert posted_payloads[-1]["taxRatePercent"] == 6
        assert posted_payloads[-1]["invoiceAmountCent"] == 38000
        assert posted_payloads[-1]["allocations"][0]["readVersion"] == 2
    finally:
        context.close()


def test_store_invoice_recovers_terminated_history_and_refreshes_chain_after_replacement(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.set_default_timeout(60000)
    registered_payloads: list[dict[str, object]] = []
    store_user = {
        "username": "store_001-user",
        "user_id": "store_001-user",
        "display_name": "Store User",
        "role": "store",
        "is_highest_admin": False,
        "status": "active",
        "is_initialized": True,
        "store_ids": ["store_001"],
        "store_scope_mode": "assigned",
        "page_keys": ["A01", "B01", "B02", "D01", "D02", "D03"],
    }
    statement = {
        "statementId": "STMT-VISUAL-001",
        "storeId": "store_001",
        "storeName": "上海浦东体验中心",
        "month": "2026-08",
        "versionNo": 2,
        "isCurrent": True,
        "supersedesStatementId": "STMT-VISUAL-000",
        "status": "CONFIRMED",
        "promotionAmountCent": 38000,
        "managementAmountCent": 9000,
        "promotionConfirmation": {
            "confirmationId": "CONF-VISUAL-001",
            "status": "CONFIRMED",
            "confirmedAmountCent": 38000,
            "confirmedAt": "2026-08-06T10:00:00+08:00",
        },
        "managementConfirmation": None,
        "promotionInvoiceStatus": "REJECTED_REUPLOAD",
        "promotionInvoiceableAmountCent": 38000,
        "promotionCarryforwardBalanceCent": 0,
        "promotionInvoiceGroupId": "promotion-group-visual-001",
        "promotionRequiredStatementIds": ["STMT-VISUAL-001"],
        "promotionPositiveAmountCent": 38000,
        "promotionNegativeAmountCent": 0,
        "managementInvoiceStatus": "PENDING_INVOICE",
    }
    old_header = {
        "invoiceId": "INV-TERMINATED-001",
        "physicalInvoiceId": "PHYSICAL-TERMINATED-001",
        "storeId": "store_001",
        "versionNo": 1,
        "versionKind": "REGISTRATION",
        "isCurrent": False,
        "supersedesInvoiceId": None,
        "replacesInvoiceId": None,
        "invoiceNumber": "12345678901234567890",
        "invoiceDate": "2026-08-08",
        "invoiceAmountCent": 38000,
        "buyerName": "比亚迪汽车销售有限公司",
        "taxRatePercent": 6,
        "status": "REJECTED_REUPLOAD",
        "registeredAt": "2026-08-08T10:00:00+08:00",
    }
    lifecycle_event = {
        "lifecycleEventId": "LIFECYCLE-001",
        "physicalInvoiceId": "PHYSICAL-TERMINATED-001",
        "invoiceId": "INV-TERMINATED-001",
        "invoiceVersion": 1,
        "eventType": "VOIDED",
        "reason": "系统外已作废",
        "readVersion": 1,
        "isCurrent": True,
        "operatorId": "store_001-user",
        "occurredAt": "2026-08-20T10:00:00+08:00",
    }

    def register_replacement(route) -> None:
        registered_payloads.append(route.request.post_data_json)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                **old_header,
                "invoiceId": "INV-REPLACEMENT-001",
                "physicalInvoiceId": "PHYSICAL-REPLACEMENT-001",
                "isCurrent": True,
                "replacesInvoiceId": "INV-TERMINATED-001",
                "invoiceNumber": "12345678901234567891",
                "invoiceDate": "2026-08-21",
                "status": "SUBMITTED_PENDING_FACTORY_REVIEW",
                "allocations": [{
                    "statementId": "STMT-VISUAL-001",
                    "statementMonth": "2026-08",
                    "settlementBatchMonth": "2026-08",
                    "allocatedAmountCent": 38000,
                }],
            }),
        )

    try:
        install_api_routes(page)
        page.unroute("**/api/v1/auth/me")
        page.unroute("**/api/v1/store-settlements?*")
        page.unroute("**/api/v1/promotion-invoices?*")
        page.route(
            "**/api/v1/auth/me",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=api_payload(store_user),
            ),
        )
        page.route(
            "**/api/v1/store-settlements?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "list": [statement], "total": 1, "page": 1, "pageSize": 50,
                    "metricScope": "MONTH",
                    "metrics": {"month": {"promotionAmountCent": 38000, "managementAmountCent": 9000}},
                }),
            ),
        )
        page.route(
            "**/api/v1/promotion-invoices/replacement-candidates?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    "list": [{
                        "invoice": old_header,
                        "lifecycleEvent": lifecycle_event,
                        "releasedStatementMonths": ["2026-08"],
                    }],
                    "total": 1,
                }),
            ),
        )
        page.route(
            "**/api/v1/promotion-invoices/INV-TERMINATED-001",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=api_payload({
                    **old_header,
                    "versions": [old_header],
                    "allocations": [],
                    "statusEvents": [],
                    "lifecycleEvents": [lifecycle_event],
                    "replacements": [{
                        **old_header,
                        "invoiceId": "INV-REPLACEMENT-001",
                        "physicalInvoiceId": "PHYSICAL-REPLACEMENT-001",
                        "invoiceNumber": "12345678901234567891",
                        "replacesInvoiceId": "INV-TERMINATED-001",
                    }],
                    "replacementChain": [old_header, {
                        **old_header,
                        "invoiceId": "INV-REPLACEMENT-001",
                        "physicalInvoiceId": "PHYSICAL-REPLACEMENT-001",
                        "invoiceNumber": "12345678901234567891",
                        "replacesInvoiceId": "INV-TERMINATED-001",
                    }],
                }),
            ),
        )
        page.route("**/api/v1/promotion-invoices", register_replacement)
        page.goto(
            f"{vite_base_url}/settlement/invoice?storeId=store_001&month=2026-08",
            wait_until="domcontentloaded",
        )
        page.get_by_role("button", name="恢复替换").click()
        page.get_by_text("替换原发票 12345678901234567890", exact=False).wait_for()
        page.reload(wait_until="domcontentloaded")
        page.get_by_text("替换原发票 12345678901234567890", exact=False).wait_for()
        page.get_by_label("20 位数电专票号码").fill("12345678901234567891")
        page.get_by_label("开票日期").fill("2026-08-21")
        page.get_by_role("button", name="登记并提交").click()
        page.get_by_text("替换链：12345678901234567890 → 12345678901234567891", exact=True).wait_for()
        assert registered_payloads[-1]["replacesInvoiceId"] == "INV-TERMINATED-001"
    finally:
        context.close()


def test_finance_import_clears_stale_preview_after_409(
    browser: Browser,
    vite_base_url: str,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    commit_attempts = 0

    def upload_preview(route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "batchId": "FIN-PREVIEW-001",
                "importType": "PROMOTION_FACTORY_RESULT",
                "statementMonth": "2026-08",
                "fileName": "promotion-review.csv",
                "scenario": "FIRST_IMPORT_READY",
                "readVersion": 0,
                "currentVersion": 0,
                "contentChanged": True,
                "totalRows": 1,
                "successRows": 1,
                "errorRows": 0,
                "submittedBy": "visual-admin",
                "submittedAt": "2026-08-08T10:00:00+08:00",
                "committedBy": None,
                "committedAt": None,
            }),
        )

    def commit_preview(route) -> None:
        nonlocal commit_attempts
        commit_attempts += 1
        if commit_attempts == 1:
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({
                    "detail": {
                        "code": "VERSION_CONFLICT",
                        "message": "预览版本已过期，请刷新后重新预览",
                        "errors": [],
                        "requestId": "req-import-409",
                    }
                }, ensure_ascii=False),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=api_payload({
                "batchId": "FIN-PREVIEW-001",
                "status": "COMMITTED",
                "readVersion": 0,
                "currentVersion": 1,
                "totalRows": 1,
                "successRows": 1,
                "errorRows": 0,
                "committedBy": "visual-admin",
                "committedAt": "2026-08-08T10:01:00+08:00",
            }),
        )

    try:
        install_api_routes(page)
        page.route("**/api/v1/admin/finance-imports", upload_preview)
        page.route("**/api/v1/admin/finance-imports/FIN-PREVIEW-001/commits", commit_preview)
        page.goto(
            f"{vite_base_url}/finance/promotion?month=2026-08",
            wait_until="domcontentloaded",
        )
        file_input = page.get_by_label("文件")
        file_input.wait_for(state="visible", timeout=10000)
        file_input.set_input_files({
            "name": "promotion-review.csv",
            "mimeType": "text/csv",
            "buffer": b"invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n12345678901234567890,APPROVED,,2026-08-08,38000\n",
        })
        upload_button = page.get_by_role("button", name="上传并预览")
        expect(upload_button).to_be_enabled(timeout=10000)
        upload_button.click()
        page.get_by_text("整批校验通过，请核对版本和变更原因后提交。", exact=True).wait_for(timeout=10000)
        page.get_by_role("button", name="确认提交").click()
        page.get_by_text("数据已发生变化，请刷新后重新操作。", exact=True).wait_for(timeout=10000)
        assert page.get_by_text("首次导入，待确认", exact=True).count() == 0
        assert commit_attempts == 1
    finally:
        context.close()
