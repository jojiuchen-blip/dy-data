"""Desktop/mobile bulk filtering against actual HTTP routes and synthetic SQL data."""
import csv
import io
from datetime import datetime, timezone
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest
import uvicorn
from playwright.sync_api import expect
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from test_visual_smoke import browser, vite_real_api_base_url, find_free_port, wait_for_url  # noqa: F401
from test_api_clues import _seed_clue_center, _seed_store_two_clue
from apps.api.dy_api.models import Base, ClueAssignmentRound, ClueCenterOrder, DimAwemeAccount, DimStorePoiMapping
from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency


@pytest.fixture()
def bulk_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'bulk.sqlite').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as session:
        _seed_clue_center(session)
        _seed_store_two_clue(session)
        session.add_all([DimAwemeAccount(account_id="00000000000000000123", store_id="store-1"),
                         DimAwemeAccount(account_id="222", store_id="store-1"),
                         DimStorePoiMapping(poi_id="222", store_id="store-2")])
        for i in range(23):
            order_id = f"bulk-extra-{i}"
            when = datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
            session.add(ClueCenterOrder(order_id=order_id, lead_status="active", assigned_at=when,
                assigned_store_id="store-1", assigned_store_name="Store One", product_type="保养",
                current_assignment_round_id=f"{order_id}-1", current_round_status="active_unfollowed"))
            session.add(ClueAssignmentRound(assignment_round_id=f"{order_id}-1", order_id=order_id, round_no=1,
                execution_mode="formal", assigned_at=when, assigned_store_id="store-1", assigned_store_name="Store One",
                round_status="active_unfollowed", follow_result="pending", is_followed=False))
        session.commit()
    requests = []
    commits = []
    def record_commit(_session):
        commits.append(True)
    event.listen(factory, "after_commit", record_commit)
    app = create_app()
    actor = AuthContext(user_id="bulk-browser", username="bulk-browser", display_name="批量筛选测试",
        role="admin", auth_type="user", store_scope_mode="specified", store_ids=("store-1", "store-2"), page_keys=("A01", "A02"))
    app.dependency_overrides[get_current_user] = lambda: actor
    def session_dependency():
        with factory() as session:
            yield session
    app.dependency_overrides[get_session_dependency] = session_dependency
    @app.middleware("http")
    async def record_requests(request, call_next):
        body = await request.json() if request.method == "POST" else None
        requests.append((request.method, request.url.path, body))
        return await call_next(request)
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        wait_for_url(f"{base}/docs")
        yield base, requests, commits
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        event.remove(factory, "after_commit", record_commit)
        engine.dispose()


@pytest.mark.parametrize("width", [1440, 390])
def test_bulk_name_merge_pagination_export_remove_clear_and_zero(browser, vite_real_api_base_url, bulk_backend, tmp_path, width):
    base, requests, commits = bulk_backend
    context = browser.new_context(viewport={"width": width, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    def forward(route):
        parts = urlsplit(route.request.url)
        route.fulfill(response=route.fetch(url=base + parts.path + ("?" + parts.query if parts.query else "")))
    page.route("**/api/v1/**", forward)
    try:
        page.goto(vite_real_api_base_url + "/clues/details?product_type=all")
        expect(page.locator(".result-count")).to_have_text("共 26 条")
        if width < 768:
            page.locator(".clue-filter-toggle").click()
        picker = page.get_by_placeholder("搜索门店名称并多选")
        picker.fill("Store Two")
        page.get_by_role("option", name="Store Two", exact=True).click()
        expect(page.locator(".result-count")).to_have_text("共 1 条")
        page.get_by_role("button", name="批量粘贴 ID", exact=True).click()
        paste = page.get_by_label("所属账户 ID / 门店位置编号（POI ID）")
        paste.fill("０００００００００００００００００１２３；222 / 222\nmissing")
        page.get_by_role("button", name="解析并加入筛选").click()
        expect(page.locator(".clue-store-filter [role=status]")).to_contain_text("重复 1 项")
        expect(page.locator(".clue-store-filter__selected")).to_contain_text("已选 2 家")
        expect(page.locator(".result-count")).to_have_text("共 26 条")
        assert page.locator(".clue-store-filter__selected").evaluate(
            "element => element.scrollWidth <= element.clientWidth + 1"
        )
        if width >= 1380:
            assert page.locator(".clue-store-filter").bounding_box()["width"] >= 240
        page.screenshot(path=str(tmp_path / f"bulk-applied-{width}.png"), full_page=True)
        page.get_by_role("button", name="下一页", exact=True).click()
        expect(page.get_by_role("spinbutton", name="输入页码")).to_have_value("2")
        with page.expect_download() as downloaded:
            page.get_by_role("button", name="导出", exact=True).click()
        path = downloaded.value.path()
        rows = list(csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))
        assert len(rows) == 26
        assert {row["assigned_store_id"] for row in rows} == {"store-1", "store-2"}
        exported = next(body for method, path, body in reversed(requests) if method == "POST" and path.endswith("/export"))
        assert set(exported["filters"]["assigned_store_ids"]) == {"store-1", "store-2"}
        page.get_by_role("button", name="移除门店 Store Two", exact=True).click()
        expect(page.locator(".result-count")).to_have_text("共 25 条")
        expect(page.get_by_role("spinbutton", name="输入页码")).to_have_value("1")
        page.get_by_role("button", name="移除门店 Store One", exact=True).click()
        expect(page.locator(".result-count")).to_have_text("共 0 条")
        page.get_by_role("button", name="清空门店筛选", exact=True).click()
        expect(page.locator(".result-count")).to_have_text("共 26 条")
        page.get_by_role("button", name="批量粘贴 ID", exact=True).click()
        paste.fill("missing-only")
        page.get_by_role("button", name="解析并加入筛选").click()
        expect(page.locator(".result-count")).to_have_text("共 0 条")
        expect(page.locator(".clue-store-filter [role=status]")).to_contain_text("匹配 0 个 ID / 0 家门店")
        page.get_by_role("button", name="批量粘贴 ID", exact=True).click()
        paste.fill(" ".join(str(i) for i in range(1001)))
        page.get_by_role("button", name="解析并加入筛选").click()
        expect(page.get_by_role("alert")).to_contain_text("1000")
        expect(page.locator(".result-count")).to_have_text("共 0 条")
        page.screenshot(path=str(tmp_path / f"bulk-filters-{width}.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        assert commits == []
        assert errors == []
    finally:
        page.unroute_all(behavior="wait")
        context.close()


def test_mobile_collapsed_store_summary_keeps_zero_selection_and_clears_to_unfiltered(
    browser, vite_real_api_base_url, bulk_backend,
):
    base, _requests, commits = bulk_backend
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def forward(route):
        parts = urlsplit(route.request.url)
        route.fulfill(response=route.fetch(url=base + parts.path + ("?" + parts.query if parts.query else "")))

    page.route("**/api/v1/**", forward)
    summary = page.locator(".clue-filter-mobile-summary")

    def clear_summary(label):
        with page.expect_request(lambda request: urlsplit(request.url).path.endswith("/clues/assignment-rounds")) as cleared:
            summary.get_by_role("button", name=label, exact=True).click()
        assert cleared.value.method == "GET"
        assert not {"assigned_store_ids", "assigned_store_id"} & parse_qs(urlsplit(cleared.value.url).query).keys()
        expect(page.locator(".result-count")).to_have_text("共 26 条")
        expect(page.get_by_role("spinbutton", name="输入页码")).to_have_value("1")
        expect(summary.locator(".clue-filter-chips")).to_have_count(0)

    try:
        page.goto(vite_real_api_base_url + "/clues/details?product_type=all")
        expect(page.locator(".result-count")).to_have_text("共 26 条")
        page.locator(".clue-filter-toggle").click()
        picker = page.get_by_placeholder("搜索门店名称并多选")
        picker.fill("Store Two")
        page.get_by_role("option", name="Store Two", exact=True).click()
        expect(page.locator(".result-count")).to_have_text("共 1 条")
        page.get_by_role("button", name="收起筛选", exact=True).click()
        expect(summary.get_by_role("button", name="门店：1家", exact=True)).to_be_visible()
        expect(page.locator(".clue-filter-toggle")).to_have_text("筛选 (1)")

        page.locator(".clue-filter-toggle").click()
        page.get_by_role("button", name="批量粘贴 ID", exact=True).click()
        page.get_by_label("所属账户 ID / 门店位置编号（POI ID）").fill("222")
        page.get_by_role("button", name="解析并加入筛选").click()
        expect(page.locator(".result-count")).to_have_text("共 26 条")
        page.get_by_role("button", name="收起筛选", exact=True).click()
        page.get_by_role("button", name="下一页", exact=True).click()
        expect(page.get_by_role("spinbutton", name="输入页码")).to_have_value("2")
        clear_summary("门店：2家")

        page.locator(".clue-filter-toggle").click()
        page.get_by_role("button", name="批量粘贴 ID", exact=True).click()
        page.get_by_label("所属账户 ID / 门店位置编号（POI ID）").fill("missing-only")
        page.get_by_role("button", name="解析并加入筛选").click()
        expect(page.locator(".result-count")).to_have_text("共 0 条")
        page.get_by_role("button", name="收起筛选", exact=True).click()
        expect(summary.get_by_role("button", name="门店：无匹配", exact=True)).to_be_visible()
        expect(page.locator(".clue-filter-toggle")).to_have_text("筛选 (1)")
        clear_summary("门店：无匹配")
        assert commits == []
        assert errors == []
    finally:
        page.unroute_all(behavior="wait")
        context.close()
