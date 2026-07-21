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
from collections.abc import Generator
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import Request
from playwright.sync_api import Browser, Page, sync_playwright
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

sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
from dy_api.auth import AuthContext, get_current_user  # noqa: E402
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
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


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
                product_scope="原产品范围",
                product_type="原商品类型",
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

    def current_user(_request: Request):
        return AuthContext(
            user_id="live-admin",
            username="live-admin",
            display_name="Live Admin",
            role="admin",
            store_ids=(),
            auth_type="env_admin",
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


def install_api_routes(page: Page) -> None:
    admin_user = {
        "username": "visual-admin",
        "user_id": "visual-admin",
        "display_name": "Visual Admin",
        "role": "admin",
        "is_highest_admin": True,
        "status": "active",
        "is_initialized": True,
        "store_ids": [],
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
        "isServiceProduct": True,
        "creatorAccountId": "creator-001",
        "creatorAccountName": "商品创建账号",
        "ownerAccountId": "owner-001",
        "ownerAccountName": "商品归属商户",
        "productStatus": "ACTIVE",
        "isActiveProduct": True,
        "lastSyncedAt": "2026-07-20T08:00:00Z",
        "manualModifiedAt": "2026-07-20T09:00:00Z",
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
            body=api_payload({"list": [sku_product], "total": 1, "page": 1, "pageSize": 50}),
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
                }
            ),
        ),
    )


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize(
    ("name", "url_path", "expected_text", "ready_target"),
    [
        (
            "design-system",
            DESIGN_SYSTEM_HTML.as_uri(),
            "dy-data UI 设计规范 V0.2",
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
            "商品口径控制",
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
        for index in range(links.count()):
            link_box = links.nth(index).bounding_box()
            assert link_box is not None
            assert link_box["x"] >= nav_box["x"] - 1
            assert link_box["x"] + link_box["width"] <= nav_box["x"] + nav_box["width"] + 1
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

        assert page.get_by_role("combobox", name="门店").input_value() == "上海浦东体验中心"
        page.get_by_role("region", name="账单状态").get_by_text(
            "上海浦东体验中心",
            exact=True,
        ).wait_for(timeout=10000)
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


def test_order_details_direct_url_requires_a_source_context(
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
            getattr(route, "fulfill")(
                status=500,
                content_type="application/json",
                body=json.dumps({"detail": "should not be called"}),
            )

        page.route("**/api/v1/order-fee-details*", record_request)
        page.goto(f"{vite_real_api_base_url}/details", wait_until="domcontentloaded")
        page.get_by_text("请从单店分账中的推广服务费或管理服务费汇总行进入。", exact=False).first.wait_for(timeout=10000)
        assert page.get_by_role("button", name="返回单店分账", exact=True).is_visible()
        assert order_detail_requests == []
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
        links = navigation.get_by_role("link")
        current = navigation.get_by_role("link", name=current_label, exact=True)
        assert links.count() == 4
        assert navigation.locator("svg").count() == 0
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
        page.get_by_role("heading", name="商品人工分类", exact=True).wait_for(timeout=10000)
        page.get_by_text("商品归属商户", exact=True).first.wait_for(timeout=10000)
        body = page.locator("body").inner_text()
        assert "商品归属商户" in body
        assert "商品创建账号" in body
        assert "双费率版本发布" in body
        assert "8%" in body
        assert "10%" in body
        assert "批量导入与原子提交" in body
        assert "待原子提交" in body
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
        page.get_by_role("heading", name="批量导入与原子提交", exact=True).wait_for(timeout=10000)
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
        section = page.get_by_role("heading", name="双费率版本发布", exact=True).locator("xpath=ancestor::section")
        section.get_by_label("SKU ID", exact=True).fill("SKU-VISUAL-001")
        section.get_by_label("两项费率一致", exact=True).uncheck()
        section.get_by_label("推广服务费比例（%）", exact=True).fill("8")
        section.get_by_label("管理服务费比例（%）", exact=True).fill("10")
        section.get_by_label("生效自然日", exact=True).fill("2026-08-02")
        section.get_by_label("变更原因", exact=True).fill("网络不确定重试")
        section.get_by_role("button", name="发布新版本", exact=True).click()
        page.get_by_text("费率版本发布失败", exact=False).wait_for(timeout=10000)
        section.get_by_role("button", name="发布新版本", exact=True).click()
        page.get_by_text("历史版本不会被覆盖", exact=False).wait_for(timeout=10000)
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
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(
            f"{vite_live_admin_api_base_url}/admin/rules",
            wait_until="domcontentloaded",
        )
        product_section = page.get_by_role(
            "heading", name="商品人工分类", exact=True
        ).locator("xpath=ancestor::section")
        product_row = product_section.get_by_role("row").filter(
            has_text="真实联调基础保养 1"
        )
        product_row.wait_for(timeout=10000)
        product_row.get_by_role("button", name="编辑人工字段", exact=True).click()
        product_section.get_by_label("产品范围", exact=True).fill("正式产品范围")
        product_section.get_by_label("商品类型", exact=True).fill("正式商品类型")
        product_section.get_by_label("服务类商品", exact=True).check()
        product_section.get_by_role("button", name="保存并重新加载", exact=True).click()
        page.get_by_text("人工分类已保存并重新加载回显", exact=False).wait_for(timeout=10000)
        assert product_section.get_by_label("产品范围", exact=True).input_value() == "正式产品范围"
        assert product_section.get_by_label("商品类型", exact=True).input_value() == "正式商品类型"

        fee_section = page.get_by_role(
            "heading", name="双费率版本发布", exact=True
        ).locator("xpath=ancestor::section")
        fee_section.get_by_label("两项费率一致", exact=True).uncheck()
        fee_section.get_by_label("推广服务费比例（%）", exact=True).fill("8")
        fee_section.get_by_label("管理服务费比例（%）", exact=True).fill("10")
        fee_section.get_by_label("变更原因", exact=True).fill("真实 FastAPI 首次发布")
        fee_section.get_by_role("button", name="发布新版本", exact=True).click()
        page.get_by_text("历史版本不会被覆盖", exact=False).wait_for(timeout=10000)
        fee_section.get_by_role("cell", name="8%", exact=True).wait_for(timeout=10000)
        fee_section.get_by_role("cell", name="10%", exact=True).wait_for(timeout=10000)

        fee_section.get_by_label("变更原因", exact=True).fill("重复生效日冲突验证")
        fee_section.get_by_role("button", name="发布新版本", exact=True).click()
        page.get_by_text("已有版本，请选择其他自然日", exact=False).wait_for(timeout=10000)
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
    page = context.new_page()
    valid_sku = f"SKU-LIVE-ADMIN-{valid_index:03d}"
    invalid_sku = f"SKU-LIVE-ADMIN-{invalid_index:03d}"
    try:
        page.goto(
            f"{vite_live_admin_api_base_url}/admin/rules",
            wait_until="domcontentloaded",
        )
        section = page.get_by_role(
            "heading", name="批量导入与原子提交", exact=True
        ).locator("xpath=ancestor::section")
        valid_file = tmp_path / f"valid{extension}"
        _write_fee_import_file(
            valid_file,
            [(f"真实联调保养 SKU {valid_index}", valid_sku, "0.08", "0.10")],
        )
        section.get_by_label("整批生效自然日", exact=True).fill(effective_date)
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
        section.get_by_label("整批生效自然日", exact=True).fill(effective_date)
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
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
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
