from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from threading import Event, Thread
from urllib.parse import urlsplit

import pytest
import uvicorn
from fastapi import HTTPException, Request
from playwright.sync_api import Browser, Page, Route, expect

from test_visual_smoke import (
    AuthContext,
    browser,  # noqa: F401 -- shared Playwright fixture
    create_app,
    find_free_port,
    get_current_user,
    get_data_store,
    vite_real_api_base_url,  # noqa: F401 -- mocks disabled
    wait_for_url,
)
from dy_api.auth import _enforce_page_permission


class TourDataStore:
    """Synthetic records behind the application's real FastAPI routes/schemas."""

    available = True

    def __init__(self) -> None:
        self.mode = "normal"
        self.username = "tour-store-a"
        self.page_keys = ("A01", "A02")
        self.release_detail = Event()
        self.requests: list[tuple[str, str]] = []
        self.queries: list[dict] = []
        self.records: list[dict] = []
        self.commits = 0
        self.session = self

    def commit(self):
        self.commits += 1

    def row(self, order: str) -> dict:
        pending = order == "tour-pending"
        writable = self.mode != "readonly"
        return {
            "assignment_round_id": f"{order}-1", "order_id": order, "round_no": 1,
            "lead_status": "active", "order_current_status": "active",
            "store_display_status": "待跟进" if pending else "已跟进",
            "current_assignment_round_id": f"{order}-1", "current_round_no": 1,
            "round_status": "active_unfollowed" if pending else "active_followed",
            "is_current_round": True, "can_operate_current_round": writable,
            "round_effective_status": "active", "assigned_store_id": "tour-store",
            "assigned_store_name": "引导演示门店", "phone_masked": "190****0000",
            "product_name": "引导测试保养服务", "product_type": "保养",
            "assigned_at": "2026-09-01T08:00:00Z", "follow_result": "pending",
        }

    def clue_filters(self, scope, *, include_assigned_stores=True):
        return {
            "assigned_stores": [], "assigned_provinces": [], "assigned_cities": [],
            "product_types": ["保养"], "default_product_type": "all",
            "lead_statuses": ["active"], "round_statuses": ["active_unfollowed"],
            "verification_statuses": [],
        }

    def clue_overview(self, filters):
        return {"total_clues": 2, "active_clues": 2}

    def clue_assignment_rounds(self, filters, actor):
        self.queries.append(dict(filters))
        if self.mode == "list-error":
            raise HTTPException(503, "列表测试失败")
        rows = [] if self.mode == "empty" else [self.row("tour-followed"), self.row("tour-pending")]
        status_filter = filters.get("store_display_status")
        if status_filter:
            rows = [row for row in rows if row["store_display_status"] == status_filter]
        return {
            "rows": rows,
            "pagination": {"page": 1, "page_size": filters["page_size"], "total": len(rows), "total_pages": 1},
        }

    def clue_order_detail(self, order, scope, actor):
        if self.mode == "detail-loading":
            self.release_detail.wait(timeout=15)
        if self.mode == "detail-error":
            return None
        return {
            "order_id": order, "lead_status": "active", "phone_masked": "190****0000",
            "product_name": "引导测试保养服务", "product_type": "保养",
            "rounds": [] if self.mode == "missing-round" else [self.row(order)],
            "follow_up_records": self.records,
        }

    def save_clue_follow_up(self, order, payload, actor):
        record = {
            **payload, "order_id": order, "round_no": 1,
            "follow_up_record_id": "tour-manual-record", "created_at": "2026-09-07T08:00:00Z",
        }
        self.records.append(record)
        return "success", record


@pytest.fixture()
def tour_backend() -> Generator[tuple[str, TourDataStore]]:
    app = create_app()
    store = TourDataStore()

    def current_user(request: Request):
        user = AuthContext(
            user_id=store.username, username=store.username, display_name="引导测试账号",
            role="store", store_ids=("tour-store",), auth_type="user",
            store_scope_mode="specified", page_keys=store.page_keys,
        )
        _enforce_page_permission(request, user)
        return user

    @app.middleware("http")
    async def record_requests(request: Request, call_next):
        store.requests.append((request.method, str(request.url.path)))
        return await call_next(request)

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_data_store] = lambda: store
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        wait_for_url(f"{base}/docs")
        yield base, store
    finally:
        store.release_detail.set()
        server.should_exit = True
        thread.join(timeout=10)


def connect_backend(page: Page, base: str) -> None:
    def forward(route: Route):
        url = urlsplit(route.request.url)
        response = route.fetch(url=f"{base}{url.path}" + (f"?{url.query}" if url.query else ""))
        route.fulfill(response=response)
    page.route("**/api/v1/**", forward)


def tour_at(page: Page, step: str):
    marker = page.locator(f'[data-clue-tour-step="{step}"]')
    expect(marker).to_be_visible()
    return page.locator(".guided-tour")


def advance(page: Page, step: str):
    page.locator(".guided-tour").get_by_role("button", name="下一步", exact=True).click()
    return tour_at(page, step)


def assert_geometry(page: Page) -> None:
    # Wait for scrolling and ResizeObserver positioning, then verify containment and separation.
    page.wait_for_function("""() => {
      const panel = document.querySelector('.guided-tour');
      const light = document.querySelector('.guided-tour__spotlight');
      if (!panel || !light) return false;
      const a = panel.getBoundingClientRect(), b = light.getBoundingClientRect();
      const visible = [a,b].every(r => r.width > 0 && r.height > 0 &&
        r.left >= 0 && r.top >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1);
      const separate = a.right <= b.left + 1 || b.right <= a.left + 1 ||
        a.bottom <= b.top + 1 || b.bottom <= a.top + 1;
      const selector = light.getAttribute('data-tour-target');
      const targets = selector ? [...document.querySelectorAll(selector)] : [];
      const hit = targets.some(e => { const r=e.getBoundingClientRect(); return (
        r.width > 0 && r.height > 0 && r.left < b.right && r.right > b.left &&
        r.top < b.bottom && r.bottom > b.top); });
      return visible && separate && hit;
    }""", timeout=10_000)


def save_evidence(page: Page, tmp_path: Path, name: str) -> None:
    target = Path(os.environ.get("DYDATA_TOUR_ARTIFACT_DIR", str(tmp_path)))
    target.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(target / f"{name}.png"))


def assert_read_only_tour(store: TourDataStore) -> None:
    assert store.commits == 0
    assert store.records == []
    assert all(method == "GET" for method, _ in store.requests)
    assert not any("/phone" in path or "/export" in path for _, path in store.requests)


@pytest.mark.parametrize("viewport", [(1440, 900), (768, 1024), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_seven_step_tour_with_real_api_and_no_business_writes(
    browser: Browser, vite_real_api_base_url: str, tour_backend, tmp_path: Path, viewport, theme,
):
    base, store = tour_backend
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, color_scheme=theme)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues?product_type=保养")
        expect(page.get_by_role("heading", name="经营线索概览")).to_be_visible()
        page.get_by_role("button", name="开始引导", exact=True).click()
        tour_at(page, "navigation")
        assert_geometry(page)
        advance(page, "status")
        assert "/clues/details?" in page.url
        assert_geometry(page)
        advance(page, "detail")
        assert_geometry(page)
        advance(page, "contact")
        expect(page.locator(".guided-tour").get_by_role("button", name="下一步", exact=True)).to_be_enabled()
        assert_geometry(page)
        assert any(path.endswith("/orders/tour-pending") for _, path in store.requests)
        assert page.locator(".clue-detail-modal").evaluate("e => e.closest('.ui-dialog-backdrop').inert")
        assert page.locator("#root").evaluate("e => e.inert")
        for _ in range(9):
            page.keyboard.press("Tab")
            assert page.locator(".guided-tour").evaluate("e => e.contains(document.activeElement)")
        save_evidence(page, tmp_path, f"{theme}-{viewport[0]}-contact")
        advance(page, "follow-up")
        assert_geometry(page)
        save_evidence(page, tmp_path, f"{theme}-{viewport[0]}-follow-up")
        advance(page, "save")
        assert_geometry(page)
        advance(page, "history")
        assert_geometry(page)
        page.locator(".guided-tour").get_by_role("button", name="上一步").click()
        tour_at(page, "save")
        advance(page, "history")
        page.locator(".guided-tour").get_by_role("button", name="完成引导").click()
        expect(page.locator(".guided-tour")).to_have_count(0)
        expect(page.locator(".clue-detail-modal")).to_have_count(0)
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_be_focused()
        assert not page.locator("#root").evaluate("e => e.inert")
        assert all(query["product_type"] == "保养" and not query["store_display_status"] for query in store.queries)
        assert_read_only_tour(store)
        assert errors == []
    finally:
        context.close()


def test_back_escape_replay_drafts_and_manual_save(browser: Browser, vite_real_api_base_url: str, tour_backend, tmp_path: Path):
    base, store = tour_backend
    context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = context.new_page()
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues/details?store_display_status=待跟进")
        page.get_by_role("button", name="开始引导").click()
        advance(page, "status")
        advance(page, "detail")
        advance(page, "contact")
        expect(page.locator(".guided-tour").get_by_role("button", name="下一步")).to_be_enabled()
        assert_geometry(page)
        save_evidence(page, tmp_path, "reduced-motion-390-contact")
        page.locator(".guided-tour").get_by_role("button", name="上一步").click()
        tour_at(page, "detail")
        expect(page.locator(".clue-detail-modal")).to_have_count(0)
        advance(page, "contact")
        page.keyboard.press("Escape")
        expect(page.locator(".ui-dialog-backdrop")).to_have_count(0)
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_be_focused()
        assert not page.locator("#root").evaluate("e => e.inert")
        assert all(query["store_display_status"] == "待跟进" for query in store.queries)
        assert_read_only_tour(store)
        page.reload()
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="开始引导")).to_have_count(0)
        page.get_by_role("button", name="新手引导", exact=True).click()
        tour_at(page, "navigation")
        page.locator(".guided-tour").get_by_role("button", name="跳过引导").click()
        page.locator('.clue-card-list .clue-detail-trigger').first.click()
        detail = page.locator(".clue-detail-modal")
        note = detail.get_by_role("textbox", name="本次跟进结论/备注")
        note.fill("客户约定周五到店")
        expect(page.locator(".clue-onboarding-heading-actions button")).to_be_disabled()
        expect(note).to_have_value("客户约定周五到店")
        detail.get_by_role("button", name="保存本次跟进").click()
        expect(detail.locator(".clue-followup-history")).to_contain_text("客户约定周五到店")
        assert store.commits == 1
        detail.get_by_role("button", name="关闭线索详情").click()
        assert not page.locator("#root").evaluate("e => e.inert")
    finally:
        context.close()


@pytest.mark.parametrize("mode", ["empty", "readonly", "list-error", "detail-error", "missing-round"])
def test_unavailable_data_has_a_short_exitable_tour(browser: Browser, vite_real_api_base_url: str, tour_backend, mode):
    base, store = tour_backend
    store.mode = mode
    context = browser.new_context(viewport={"width": 768, "height": 1024})
    page = context.new_page()
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues/details")
        page.get_by_role("button", name="开始引导").click()
        advance(page, "status")
        advance(page, "detail")
        if mode in ("empty", "list-error"):
            expect(page.locator(".guided-tour")).to_contain_text("3 / 3" if mode == "empty" else "加载失败")
        else:
            advance(page, "contact")
        if mode == "readonly":
            expect(page.locator(".guided-tour")).to_contain_text("不可编辑")
            expect(page.locator(".clue-followup-form")).to_have_count(0)
            advance(page, "history")
            expect(page.locator(".guided-tour")).to_contain_text("5 / 5")
            page.locator(".guided-tour").get_by_role("button", name="完成引导").click()
        else:
            page.locator(".guided-tour").get_by_role("button", name="结束引导").click()
        expect(page.locator(".ui-dialog-backdrop")).to_have_count(0)
        assert not page.locator("#root").evaluate("e => e.inert")
        assert_read_only_tour(store)
    finally:
        context.close()


def test_preferences_are_per_account_and_storage_failure_is_safe(browser: Browser, vite_real_api_base_url: str, tour_backend):
    base, store = tour_backend
    context = browser.new_context()
    page = context.new_page()
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues/details")
        page.get_by_role("button", name="稍后再看").click()
        page.reload()
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="开始引导")).to_have_count(0)
        store.username = "tour-store-b"
        page.reload()
        expect(page.get_by_role("button", name="开始引导")).to_be_visible()
        page.add_init_script("""(() => {
          const get = Storage.prototype.getItem, set = Storage.prototype.setItem;
          Storage.prototype.getItem = function(key) {
            if(key.startsWith('dy-data:clue-onboarding:')) throw new Error('storage blocked');
            return get.call(this,key);
          };
          Storage.prototype.setItem = function(key,value) {
            if(key.startsWith('dy-data:clue-onboarding:')) throw new Error('storage blocked');
            return set.call(this,key,value);
          };
        })()""")
        page.reload()
        page.get_by_role("button", name="稍后再看").click()
        page.get_by_role("button", name="新手引导", exact=True).click()
        tour_at(page, "navigation")
        page.keyboard.press("Escape")
        expect(page.locator(".guided-tour")).to_have_count(0)
        expect(page.get_by_role("button", name="开始引导")).to_have_count(0)
        assert not page.locator("#root").evaluate("e => e.inert")
    finally:
        context.close()


def test_no_detail_permission_has_no_invitation_or_navigation(browser: Browser, vite_real_api_base_url: str, tour_backend):
    base, store = tour_backend
    store.page_keys = ("A01",)
    context = browser.new_context()
    page = context.new_page()
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues")
        expect(page.get_by_role("heading", name="经营线索概览")).to_be_visible()
        expect(page.get_by_role("button", name="新手引导", exact=True)).to_have_count(0)
        expect(page.locator('[data-clue-tour="navigation"]')).to_have_count(0)
        assert page.request.get(f"{base}/api/v1/clues/assignment-rounds").status == 403
    finally:
        context.close()


def test_missing_target_and_slow_detail_can_exit(browser: Browser, vite_real_api_base_url: str, tour_backend):
    base, store = tour_backend
    context = browser.new_context()
    page = context.new_page()
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues/details")
        page.get_by_role("button", name="开始引导").click()
        tour_at(page, "navigation")
        page.locator('[data-clue-tour="navigation"]').evaluate_all("items => items.forEach(e => e.removeAttribute('data-clue-tour'))")
        page.locator(".guided-tour").get_by_role("button", name="结束引导").click(timeout=12_000)
        expect(page.locator(".guided-tour")).to_have_count(0)
        page.reload()
        store.mode = "detail-loading"
        page.get_by_role("button", name="新手引导", exact=True).click()
        advance(page, "status")
        advance(page, "detail")
        # Stall the browser response without blocking its event dispatcher.
        held_routes = []
        page.route("**/api/v1/clues/orders/*", lambda route: held_routes.append(route))
        advance(page, "contact")
        page.locator(".guided-tour").get_by_role("button", name="结束引导").click(timeout=12_000)
        expect(page.locator(".ui-dialog-backdrop")).to_have_count(0)
        assert not page.locator("#root").evaluate("e => e.inert")
        for route in held_routes:
            route.abort()
        assert_read_only_tour(store)
    finally:
        context.close()


def test_resize_switches_to_visible_targets(browser: Browser, vite_real_api_base_url: str, tour_backend, tmp_path: Path):
    base, store = tour_backend
    context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues/details")
        page.get_by_role("button", name="开始引导").click()
        tour_at(page, "navigation")
        page.set_viewport_size({"width": 390, "height": 844})
        assert_geometry(page)
        advance(page, "status")
        assert_geometry(page)
        advance(page, "detail")
        assert_geometry(page)
        advance(page, "contact")
        expect(page.locator(".guided-tour").get_by_role("button", name="下一步")).to_be_enabled()
        advance(page, "follow-up")
        page.set_viewport_size({"width": 768, "height": 1024})
        assert_geometry(page)
        save_evidence(page, tmp_path, "reduced-motion-resize-768-follow-up")
        page.set_viewport_size({"width": 1440, "height": 900})
        assert_geometry(page)
        page.keyboard.press("Escape")
        expect(page.locator(".ui-dialog-backdrop")).to_have_count(0)
        assert not page.locator("#root").evaluate("e => e.inert")
        assert_read_only_tour(store)
    finally:
        context.close()


def test_tour_waits_for_current_filter_refresh(browser: Browser, vite_real_api_base_url: str, tour_backend):
    base, store = tour_backend
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues/details")
        expect(page.locator(".clue-table-view .clue-detail-trigger:visible")).to_have_count(2)
        held_routes: list[Route] = []
        page.route("**/api/v1/clues/assignment-rounds?*", lambda route: held_routes.append(route))
        page.locator("#clue-status-filter").click()
        page.get_by_role("option", name="待跟进", exact=True).click()
        page.get_by_role("button", name="开始引导").click()
        advance(page, "status")
        advance(page, "detail")
        expect(page.locator(".guided-tour")).to_contain_text("正在加载当前筛选结果")
        expect(page.locator(".guided-tour").get_by_role("button", name="下一步", exact=True)).to_be_disabled()
        assert not any("/clues/orders/" in path for _, path in store.requests)
        assert held_routes
        for route in held_routes:
            url = urlsplit(route.request.url)
            route.fulfill(response=route.fetch(url=f"{base}{url.path}?{url.query}"))
        expect(page.locator(".guided-tour").get_by_role("button", name="下一步", exact=True)).to_be_enabled()
        advance(page, "contact")
        expect(page.locator(".guided-tour").get_by_role("button", name="下一步", exact=True)).to_be_enabled()
        assert any(path.endswith("/orders/tour-pending") for _, path in store.requests)
        assert not any(path.endswith("/orders/tour-followed") for _, path in store.requests)
        page.keyboard.press("Escape")
        assert_read_only_tour(store)
    finally:
        context.close()
