import pytest
from playwright.sync_api import Browser, expect

from test_visual_smoke import api_payload, browser, vite_base_url, install_api_routes  # noqa: F401
from test_visual_smoke import live_admin_fastapi_base_url, vite_live_admin_api_base_url  # noqa: F401


@pytest.mark.parametrize("viewport", [(1440, 900), (768, 1024), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_store_tour_replays_without_changing_filters_or_writing(browser: Browser, vite_base_url: str, viewport: tuple[int, int], theme: str):
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, color_scheme=theme)
    context.add_init_script(f"window.localStorage.setItem('dydata.theme.preference', '{theme}')")
    page = context.new_page()
    writes = []
    try:
        install_api_routes(page)
        page.on("request", lambda request: writes.append(request.url)
                if "/api/v1/" in request.url and request.method not in ("GET", "HEAD", "OPTIONS") else None)
        page.goto(f"{vite_base_url}/settlement", wait_until="networkidle")
        expect(page.get_by_role("heading", name="单店分账", exact=True)).to_be_visible()
        initial_url = page.url
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_be_visible(timeout=5000)
        page.get_by_role("button", name="新手引导", exact=True).click()
        for title in ["选择账期和门店", "核对两方向金额", "查看订单费用明细", "分别确认账单", "异议与后续开票"]:
            expect(page.locator(".guided-tour").get_by_role("heading", name=title)).to_be_visible()
            page.locator(".guided-tour").get_by_role("button", name="完成引导" if title == "异议与后续开票" else "下一步", exact=True).click()
        expect(page.locator(".guided-tour")).to_have_count(0)
        assert page.url == initial_url
        assert writes == []
        page.get_by_role("button", name="新手引导", exact=True).click()
        expect(page.locator(".guided-tour")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator(".guided-tour")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.parametrize("viewport", [(1440, 900), (768, 1024), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("route", "heading", "titles"), [
    ("/admin/product-types?view=configured", "商品口径", ["先看配置状态", "找到需要配置的商品", "选择单条或批量设置", "保留原值并核对结果"]),
    ("/admin/rules", "商品分账规则管理", ["查询并选择 SKU", "设置双费率与生效条件", "应用比例后检查预选", "核对后自行确认发布", "查看已启用商品", "核对发布记录与重算结果"]),
    ("/admin/accounts", "账号管理", ["选择要管理的账号", "填写或核对账号资料", "按职责选择角色", "核对门店数据范围", "区分页面权限与门店范围", "自行保存并核对记录"]),
])
def test_admin_tour_can_exit_without_business_writes(browser: Browser, vite_base_url: str, route: str, heading: str, titles: list[str], viewport: tuple[int, int], theme: str):
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, color_scheme=theme)
    context.add_init_script(f"window.localStorage.setItem('dydata.theme.preference', '{theme}')")
    page = context.new_page()
    writes = []
    tour_requests = []
    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}{route}", wait_until="networkidle")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        if route == "/admin/accounts":
            page.get_by_label("显示名称", exact=True).fill("待保存的测试草稿")
        elif route == "/admin/rules":
            page.get_by_label("变更原因", exact=True).fill("尚未发布的测试原因")
        initial_url = page.url
        fields = page.locator("input:not([type=password]):not([type=file]), textarea")
        initial_fields = fields.evaluate_all("els => els.map(el => [el.value, el.checked ?? null])")
        page.on("request", lambda request: writes.append(request.url)
                if "/api/v1/" in request.url and request.method not in ("GET", "HEAD", "OPTIONS") else None)
        page.on("request", lambda request: tour_requests.append(request.url) if "/api/v1/" in request.url else None)
        page.get_by_role("button", name="新手引导", exact=True).click(timeout=5000)
        for index, title in enumerate(titles):
            expect(page.locator(".guided-tour").get_by_role("heading", name=title, exact=True)).to_be_visible()
            page.locator(".guided-tour").get_by_role("button", name="完成引导" if index == len(titles) - 1 else "下一步", exact=True).click()
        expect(page.locator(".guided-tour")).to_have_count(0)
        assert fields.evaluate_all("els => els.map(el => [el.value, el.checked ?? null])") == initial_fields
        page.get_by_role("button", name="新手引导", exact=True).click()
        expect(page.locator(".guided-tour")).to_be_visible()
        page.keyboard.press("Tab")
        assert page.locator(".guided-tour").evaluate("el => el.contains(document.activeElement)")
        page.keyboard.press("Shift+Tab")
        assert page.locator(".guided-tour").evaluate("el => el.contains(document.activeElement)")
        page.keyboard.press("Escape")
        expect(page.locator(".guided-tour")).to_have_count(0)
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_be_focused()
        assert page.url == initial_url
        assert writes == []
        assert tour_requests == []
    finally:
        context.close()


def test_tour_invitation_is_persistent_and_isolated_by_page_and_account(browser: Browser, vite_base_url: str):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/admin/product-types", wait_until="networkidle")
        invitation = page.get_by_role("region", name="商品口径新手引导邀请")
        expect(invitation).to_be_visible()
        invitation.get_by_role("button", name="稍后再看").click()
        page.reload(wait_until="networkidle")
        expect(invitation).to_have_count(0)
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_be_visible()
        page.goto(f"{vite_base_url}/admin/accounts", wait_until="networkidle")
        expect(page.get_by_role("region", name="账号管理新手引导邀请")).to_be_visible()
        second_user = {
            "username": "visual-second", "user_id": "visual-second", "display_name": "Second Admin",
            "role": "highest_admin", "is_highest_admin": True, "status": "active", "is_initialized": True,
            "store_ids": [], "store_scope_mode": "all", "page_keys": ["D01", "D02", "D04"],
        }
        page.route("**/api/v1/auth/me", lambda route: route.fulfill(status=200, content_type="application/json", body=api_payload(second_user)))
        page.goto(f"{vite_base_url}/admin/product-types", wait_until="networkidle")
        expect(invitation).to_be_visible()
    finally:
        context.close()


@pytest.mark.parametrize("scenario", ["missing-target", "storage-denied"])
def test_tour_degraded_environment_remains_dismissible(browser: Browser, vite_base_url: str, scenario: str):
    context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    if scenario == "storage-denied":
        context.add_init_script("""for (const method of ['getItem', 'setItem']) {
            const original = Storage.prototype[method];
            Storage.prototype[method] = function(key, ...args) {
                if (key.startsWith('dy-data:page-onboarding:')) throw new DOMException('Denied', 'SecurityError');
                return original.call(this, key, ...args);
            };
        }""")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        install_api_routes(page)
        page.goto(f"{vite_base_url}/admin/product-types", wait_until="networkidle")
        if scenario == "missing-target":
            page.locator(".product-types-tabs").evaluate("el => el.remove()")
        page.get_by_role("button", name="新手引导", exact=True).click()
        expect(page.locator(".guided-tour")).to_be_visible()
        if scenario == "missing-target":
            page.locator(".guided-tour").get_by_role("button", name="结束引导", exact=True).click(timeout=12000)
        else:
            page.keyboard.press("Escape")
        expect(page.locator(".guided-tour")).to_have_count(0)
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_be_focused()
        expect(page.get_by_role("region", name="商品口径新手引导邀请")).to_have_count(0)
        page.get_by_role("button", name="新手引导", exact=True).click()
        expect(page.locator(".guided-tour")).to_be_visible()
        page.keyboard.press("Escape")
        assert errors == []
    finally:
        context.close()


@pytest.mark.parametrize(("role", "route", "heading", "step_count"), [
    ("admin", "/admin/product-types", "商品口径", 4),
    ("admin", "/admin/accounts", "账号管理", 6),
    ("admin", "/admin/rules", "商品分账规则管理", 6),
    ("store", "/settlement?storeId=store-1&month=2026-08", "单店分账", 5),
])
def test_tours_use_live_api_without_business_actions(browser: Browser, live_admin_fastapi_base_url: str, vite_live_admin_api_base_url: str, role: str, route: str, heading: str, step_count: int):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies([{"name": "dy_e2e_role", "value": role, "url": live_admin_fastapi_base_url}])
    page = context.new_page()
    requests = []
    failed_responses = []
    page.on("response", lambda response: failed_responses.append((response.status, response.url)) if "/api/v1/" in response.url and response.status >= 400 else None)
    try:
        page.goto(f"{vite_live_admin_api_base_url}{route}", wait_until="networkidle")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        page.on("request", lambda request: requests.append((request.method, request.url)) if "/api/v1/" in request.url else None)
        page.get_by_role("button", name="新手引导", exact=True).click()
        for index in range(step_count):
            expect(page.locator(".guided-tour__progress")).to_contain_text(f"第 {index + 1} / {step_count} 步")
            page.locator(".guided-tour").get_by_role("button", name="完成引导" if index == step_count - 1 else "下一步", exact=True).click()
        expect(page.locator(".guided-tour")).to_have_count(0)
        assert requests == []
        assert failed_responses == []
    finally:
        context.close()


def test_store_cannot_enter_admin_onboarding(browser: Browser, live_admin_fastapi_base_url: str, vite_live_admin_api_base_url: str):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies([{"name": "dy_e2e_role", "value": "store", "url": live_admin_fastapi_base_url}])
    page = context.new_page()
    try:
        for route in ["/admin/rules", "/admin/accounts", "/admin/product-types"]:
            page.goto(f"{vite_live_admin_api_base_url}{route}", wait_until="networkidle")
            expect(page.get_by_role("button", name="新手引导", exact=True)).to_have_count(0)
        response = context.request.get(f"{live_admin_fastapi_base_url}/api/v1/admin/sku-fee-rules")
        assert response.status == 403
    finally:
        context.close()
