from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "apps" / "web"
DESIGN_SYSTEM_HTML = REPO_ROOT / "docs" / "design-system" / "index.html"
HOST = "127.0.0.1"
VIEWPORTS = [
    (390, 844),
    (768, 1024),
    (1440, 900),
]


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
    npm = shutil.which("npm")
    if npm is None:
        pytest.skip("npm is required for visual smoke tests")

    port = find_free_port()
    env = os.environ.copy()
    env["VITE_USE_MOCKS"] = "true"
    process = subprocess.Popen(
        [
            npm,
            "--prefix",
            str(WEB_DIR),
            "run",
            "dev",
            "--",
            "--host",
            HOST,
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
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


def install_api_routes(page: Page) -> None:
    admin_user = {
        "username": "visual-admin",
        "user_id": "visual-admin",
        "display_name": "Visual Admin",
        "role": "admin",
        "status": "active",
        "is_initialized": True,
        "store_ids": [],
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
            "latest_failure": None,
            "next_scheduled_sync_at": "2026-06-25T09:05:00Z",
        },
        "jobs": [sync_job],
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


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize(
    ("name", "url_path", "expected_text"),
    [
        (
            "design-system",
            DESIGN_SYSTEM_HTML.as_uri(),
            "抖音经营数据引擎 UI 设计规范",
        ),
        ("clues", "/clues", "经营线索概览"),
        ("settlement", "/settlement", "单店月度分账看板"),
        ("admin-sync", "/admin/sync", "数据同步管理"),
    ],
)
def test_key_ui_surfaces_render_without_layout_smoke_failures(
    browser: Browser,
    vite_base_url: str,
    tmp_path: Path,
    name: str,
    url_path: str,
    expected_text: str,
    width: int,
    height: int,
) -> None:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )

    try:
        install_api_routes(page)
        url = url_path if url_path.startswith("file:") else f"{vite_base_url}{url_path}"
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text(expected_text, exact=False).first.wait_for(timeout=10000)
        page.screenshot(path=tmp_path / f"{name}-{width}.png", full_page=True)

        text_length = page.evaluate("() => document.body.innerText.trim().length")
        horizontal_overflow = page.evaluate(
            "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth",
        )

        assert text_length > 20
        assert horizontal_overflow <= 2
        assert console_errors == []
    finally:
        context.close()
