from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_visual_clue_onboarding import (
    browser, vite_real_api_base_url, tour_backend,
    connect_backend, close_backend_context,
)


@pytest.mark.parametrize("width", [1440, 390])
def test_verification_store_and_filter(browser, vite_real_api_base_url, tour_backend, tmp_path: Path, width):
    base, store = tour_backend
    original_row = store.row

    def row(order):
        result = original_row(order)
        result.update(store_display_status="已核销", verified_at="2026-09-02T08:00:00Z",
                      verified_store_id="tour-store" if order == "self" else "other-store",
                      verified_store_name="自店测试门店" if order == "self" else "异店测试门店",
                      is_self_store_verified=order == "self")
        return result

    store.row = row

    def rounds(filters, actor):
        store.queries.append(dict(filters))
        rows = [row("self"), row("other")]
        if filters.get("verification_status") == "self_store_verified":
            rows = rows[:1]
        return {"rows": rows, "pagination": {"page": filters["page"], "page_size": filters["page_size"], "total": len(rows), "total_pages": 1}}

    store.clue_assignment_rounds = rounds
    context = browser.new_context(viewport={"width": width, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    connect_backend(page, base)
    try:
        page.goto(f"{vite_real_api_base_url}/clues/details?product_type=all")
        surface = page.locator(".clue-card-list" if width < 768 else ".clue-table-wrap")
        # The desktop container class is resolved from the table to avoid layout coupling.
        if width >= 768:
            surface = page.locator("table.data-table--clues")
        expect(surface).to_contain_text("异店测试门店")
        expect(surface).to_contain_text("自店测试门店")
        if width < 768:
            page.locator(".clue-filter-toggle").click()
        checkbox = page.get_by_role("checkbox", name="仅看自店核销")
        checkbox.check()
        expect(surface).not_to_contain_text("异店测试门店")
        expect(surface).to_contain_text("自店测试门店")
        assert store.queries[-1]["verification_status"] == "self_store_verified"
        assert store.queries[-1]["page"] == 1
        surface.locator(".clue-detail-trigger").first.click()
        expect(page.locator(".clue-detail-modal")).to_contain_text("自店测试门店")
        page.get_by_role("button", name="关闭线索详情").click()
        page.screenshot(path=str(tmp_path / f"clue-verification-{width}.png"), full_page=True)
        page.get_by_role("button", name="清空筛选", exact=True).click()
        expect(checkbox).not_to_be_checked()
        expect(surface).to_contain_text("异店测试门店")
        assert not store.queries[-1].get("verification_status")
        assert not errors
    finally:
        close_backend_context(page, store)
