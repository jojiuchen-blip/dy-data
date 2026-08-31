from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from test_visual_smoke import HOST, WEB_DIR, browser, find_free_port, wait_for_url


REPO_ROOT = Path(__file__).resolve().parents[1]
UAT_SCREENSHOT_DIR = REPO_ROOT / "pwScreenShot" / "dydata-81-store-finance" / "uat"
UAT_VIEWPORTS = [(390, 844), (768, 1024), (1440, 900)]
UAT_PAGES = [
    ("ranking", "/uat.html#/ranking", "全国门店月度榜单"),
    ("settlement", "/uat.html#/settlement", "单店分账"),
    ("invoice", "/uat.html#/settlement/invoice", "开票确认"),
    ("invoice-status", "/uat.html#/settlement/invoice/status", "发票状态查看"),
]


@pytest.fixture(scope="session")
def vite_uat_base_url() -> Generator[str]:
    node = shutil.which("node")
    vite_script = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    config = WEB_DIR / "vite.uat.config.ts"
    if node is None or not vite_script.exists() or not config.exists():
        pytest.skip("Node.js, Vite and the isolated UAT entrypoint are required")

    port = find_free_port()
    env = os.environ.copy()
    env["VITE_USE_MOCKS"] = "false"
    process = subprocess.Popen(
        [node, str(vite_script), "--config", str(config), "--host", HOST, "--port", str(port)],
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
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            process.terminate()
        process.wait(timeout=10)


@pytest.mark.parametrize("viewport", UAT_VIEWPORTS)
@pytest.mark.parametrize("name,path,heading", UAT_PAGES)
def test_uat_preview_renders_the_frozen_pages_at_supported_widths(
    browser: Browser,
    vite_uat_base_url: str,
    viewport: tuple[int, int],
    name: str,
    path: str,
    heading: str,
) -> None:
    width, height = viewport
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    UAT_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.goto(f"{vite_uat_base_url}{path}", wait_until="domcontentloaded")
        page.get_by_role("heading", name=heading, exact=True).wait_for()
        assert page.locator("body").evaluate(
            "node => node.scrollWidth <= node.clientWidth + 1",
        )
        assert (
            page.get_by_text("暂无数据", exact=True).count()
            + page.get_by_text("尚未生成", exact=True).count()
            > 0
        )
        if name == "ranking":
            page.get_by_label("排行依据").click()
            page.get_by_role("option", name="销售金额（累计）", exact=True).click()
        elif name == "settlement":
            page.get_by_role("tab", name="管理费明细", exact=True).click()
            page.get_by_role("tab", name="推广费明细", exact=True).click()
            page.get_by_role("button", name="发起账单异议", exact=True).click()
            page.get_by_role("button", name="确认发起", exact=True).click()
            page.get_by_role("heading", name="发起推广服务费账单异议", exact=True).wait_for()
        elif name == "invoice":
            assert page.locator(".uat-invoice-rhythm__step.is-current").inner_text().startswith("发票提交")
            assert page.get_by_label("填写人电话").count() == 1
        else:
            for column in ("账期", "发票号码", "发票状态", "审核结果", "原因", "结算归属"):
                assert page.get_by_role("columnheader", name=column, exact=True).count() > 0
        page.screenshot(path=UAT_SCREENSHOT_DIR / f"{name}-{width}x{height}.png", full_page=True)
    finally:
        context.close()
