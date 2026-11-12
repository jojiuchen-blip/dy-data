from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.worker.browser_exports import backend_aweme


TARGET_URL = "https://life.douyin.com/p/liteapp/bc_manage"


class Page:
    def __init__(self, url=TARGET_URL, content="商家号管理 导出数据"):
        self.url = url
        self.content = Mock(return_value=content)
        self.locator = Mock(return_value=SimpleNamespace(inner_text=Mock(return_value=content)))
        self.close = Mock()
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    def remove_listener(self, event, handler):
        assert self.handlers.pop(event) is handler


def test_reuses_matching_business_page_without_touching_other_tabs():
    unrelated = Page("https://example.test/work")
    blank = Page("about:blank")
    matching = Page(TARGET_URL + "?tab=personal")
    context = SimpleNamespace(pages=[blank, unrelated, matching], new_page=Mock())

    with backend_aweme.managed_backend_aweme_page(context, TARGET_URL) as page:
        assert page is matching

    context.new_page.assert_not_called()
    for existing in context.pages:
        existing.close.assert_not_called()
    assert matching.handlers == {}


@pytest.mark.parametrize("url", [
    "http://life.douyin.com/p/liteapp/bc_manage",
    "https://life.douyin.com:444/p/liteapp/bc_manage",
    "https://life.douyin.com/p/liteapp/other",
    "https://life.douyin.com.evil.test/p/liteapp/bc_manage",
])
def test_unrelated_origin_or_route_gets_a_temporary_owned_page(url):
    existing = Page(url)
    created = Page()
    context = SimpleNamespace(pages=[existing], new_page=Mock(return_value=created))

    with backend_aweme.managed_backend_aweme_page(context, TARGET_URL) as page:
        assert page is created

    created.close.assert_called_once_with()
    existing.close.assert_not_called()


def test_default_root_entry_reuses_known_business_page():
    matching = Page()
    context = SimpleNamespace(pages=[Page("about:blank"), matching], new_page=Mock())
    with backend_aweme.managed_backend_aweme_page(context, backend_aweme.DEFAULT_EXPORT_URL) as page:
        assert page is matching
    context.new_page.assert_not_called()


def test_failed_new_business_page_remains_for_api_fallback():
    created = Page()
    context = SimpleNamespace(pages=[], new_page=Mock(return_value=created))
    with pytest.raises(RuntimeError, match="download timed out"):
        with backend_aweme.managed_backend_aweme_page(context, TARGET_URL):
            raise RuntimeError("download timed out")
    created.close.assert_not_called()
    assert created.handlers == {}


@pytest.mark.parametrize("url,content", [
    ("https://life.douyin.com/p/login", "扫码登录"),
    (TARGET_URL, "登录状态已过期，请重新登录"),
    (TARGET_URL, "请完成安全验证"),
    (TARGET_URL, "请填写验证码"),
    (TARGET_URL, "Verify you are human"),
])
def test_interactive_pages_are_preserved_even_when_owned(url, content):
    created = Page(url, content)
    context = SimpleNamespace(pages=[], new_page=Mock(return_value=created))
    with backend_aweme.managed_backend_aweme_page(context, TARGET_URL):
        pass
    created.close.assert_not_called()


@pytest.mark.parametrize("failed", [False, True])
def test_only_current_export_business_popups_are_closed(failed):
    existing = Page()
    existing_other = Page()
    business_popup = Page(TARGET_URL + "?tab=personal")
    login_popup = Page("https://passport.douyin.com/login", "扫码登录")
    captcha_popup = Page(TARGET_URL, "拖动滑块完成验证")
    unrelated_popup = Page("https://example.test/download")
    context = SimpleNamespace(pages=[existing, existing_other], new_page=Mock())

    def run_export():
        with backend_aweme.managed_backend_aweme_page(context, TARGET_URL) as page:
            for popup in (business_popup, login_popup, captcha_popup, unrelated_popup, existing_other):
                page.handlers["popup"](popup)
            if failed:
                raise RuntimeError("download failed")

    if failed:
        with pytest.raises(RuntimeError, match="download failed"):
            run_export()
    else:
        run_export()
    business_popup.close.assert_called_once_with()
    for preserved in (existing, existing_other, login_popup, captcha_popup, unrelated_popup):
        preserved.close.assert_not_called()
    assert existing.handlers == {}


def test_cleanup_failure_preserves_original_export_failure():
    from playwright.sync_api import Error as PlaywrightError

    existing = Page()
    popup = Page()
    popup.content.side_effect = PlaywrightError("target closed")
    context = SimpleNamespace(pages=[existing], new_page=Mock())
    with pytest.raises(RuntimeError, match="original failure"):
        with backend_aweme.managed_backend_aweme_page(context, TARGET_URL) as page:
            page.handlers["popup"](popup)
            raise RuntimeError("original failure")
    popup.close.assert_not_called()


def test_hidden_challenge_assets_do_not_keep_completed_owned_pages_open():
    created = Page()
    created.content.return_value = '<script src="/captcha.js"></script><body>导出完成</body>'
    context = SimpleNamespace(pages=[], new_page=Mock(return_value=created))
    with backend_aweme.managed_backend_aweme_page(context, TARGET_URL):
        pass
    created.close.assert_called_once_with()


def test_stale_login_page_does_not_block_a_fresh_business_navigation():
    stale_login = Page("https://life.douyin.com/p/login", "扫码登录")
    created = Page()
    context = SimpleNamespace(pages=[stale_login], new_page=Mock(return_value=created))
    with backend_aweme.managed_backend_aweme_page(context, TARGET_URL) as page:
        assert page is created
    stale_login.close.assert_not_called()
    created.close.assert_called_once_with()


def test_fallback_never_creates_a_blank_page():
    context = SimpleNamespace(pages=[Page("about:blank")], new_page=Mock())
    with pytest.raises(backend_aweme.BrowserExportError, match="business page is not available"):
        with backend_aweme.managed_backend_aweme_page(context, TARGET_URL, create_if_missing=False):
            pytest.fail("missing business page must fail before yielding")
    context.new_page.assert_not_called()


def test_failed_owned_blank_page_is_closed():
    created = Page("about:blank", "")
    context = SimpleNamespace(pages=[], new_page=Mock(return_value=created))
    with pytest.raises(RuntimeError, match="navigation failed"):
        with backend_aweme.managed_backend_aweme_page(context, TARGET_URL):
            raise RuntimeError("navigation failed")
    created.close.assert_called_once_with()


def test_real_chromium_repeated_exports_keep_existing_tabs_and_close_owned_popups():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Chromium is not installed")
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.route("**/*", lambda route: route.fulfill(
            content_type="text/html", body="<body>商家号管理 导出数据</body>",
        ))
        blank = context.new_page()
        business = context.new_page()
        business.goto(TARGET_URL)
        stale_login = context.new_page()
        stale_login.goto("https://life.douyin.com/p/login")
        existing_pages = list(context.pages)
        for _ in range(4):
            with backend_aweme.managed_backend_aweme_page(context, TARGET_URL) as page:
                assert page is business
                with page.expect_popup() as opened:
                    page.evaluate("url => window.open(url)", TARGET_URL)
                popup = opened.value
                popup.wait_for_load_state("domcontentloaded")
            assert popup.is_closed()
            assert context.pages == existing_pages
        assert not blank.is_closed() and not stale_login.is_closed()

        # A crash/close while exporting must retain the original failure.
        with pytest.raises(RuntimeError, match="original export failure"):
            with backend_aweme.managed_backend_aweme_page(context, TARGET_URL) as page:
                page.close()
                raise RuntimeError("original export failure")
        browser.close()


def test_still_navigating_blank_popup_is_preserved():
    existing = Page()
    popup = Page("about:blank", "")
    context = SimpleNamespace(pages=[existing], new_page=Mock())
    with backend_aweme.managed_backend_aweme_page(context, TARGET_URL) as page:
        page.handlers["popup"](popup)
    popup.close.assert_not_called()


def test_failed_export_removes_both_response_and_popup_listeners(monkeypatch, tmp_path):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    page = Page()
    page.goto = Mock(side_effect=PlaywrightTimeoutError("navigation timeout"))
    context = SimpleNamespace(pages=[page])
    browser = SimpleNamespace(contexts=[context])
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda _: browser))
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: nullcontext(playwright))
    monkeypatch.setattr(backend_aweme, "resolve_playwright_cdp_url", lambda _: "ws://synthetic")
    with pytest.raises(backend_aweme.BrowserExportError, match="Timed out waiting"):
        backend_aweme.export_workbook_via_browser(cdp_url="synthetic", export_url=TARGET_URL, run_dir=tmp_path)
    assert page.handlers == {}
    page.close.assert_not_called()
