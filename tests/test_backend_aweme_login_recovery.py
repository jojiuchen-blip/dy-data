from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Error as PlaywrightError

from apps.worker.browser_exports import backend_aweme
from apps.worker.pipeline import sanitize_error_message


@pytest.fixture
def browser_page(monkeypatch):
    page = Mock()
    page.url = "https://life.douyin.com/p/liteapp/bc_manage"
    page.content.return_value = "抖音号明细"
    page.expect_download.return_value = nullcontext(SimpleNamespace(value=None))
    context = SimpleNamespace(pages=[page])
    browser = SimpleNamespace(contexts=[context])
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda _: browser))
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: nullcontext(playwright))
    monkeypatch.setattr(backend_aweme, "resolve_playwright_cdp_url", lambda _: "ws://test")
    return page


def test_initial_login_failure_stays_short_and_does_not_try_fallback(browser_page, monkeypatch, tmp_path):
    browser_page.url = "https://life.douyin.com/p/login"
    fallback = Mock()
    monkeypatch.setattr(backend_aweme, "fetch_backend_aweme_records_via_bind_list_api", fallback)
    with pytest.raises(backend_aweme.BrowserExportError, match="^douyin_backend_login_required$") as error:
        backend_aweme.export_backend_aweme_records_via_browser(cdp_url="test", run_dir=tmp_path)
    assert sanitize_error_message(str(error.value)) == "douyin_backend_login_required"
    fallback.assert_not_called()


def test_delayed_login_redirect_takes_priority_over_download_recovery(browser_page, monkeypatch, tmp_path):
    def click(*args, **kwargs):
        browser_page.url = "https://life.douyin.com/p/login"
        raise PlaywrightTimeoutError("button not found")

    recent = Mock(return_value=tmp_path / "unrelated.xlsx")
    fallback = Mock()
    monkeypatch.setattr(backend_aweme, "click_backend_export", click)
    monkeypatch.setattr(backend_aweme, "find_recent_workbook", recent)
    monkeypatch.setattr(backend_aweme, "fetch_backend_aweme_records_via_bind_list_api", fallback)
    with pytest.raises(backend_aweme.BrowserExportError, match="^douyin_backend_login_required$"):
        backend_aweme.export_backend_aweme_records_via_browser(cdp_url="test", run_dir=tmp_path)
    recent.assert_not_called()
    fallback.assert_not_called()


def test_fallback_login_page_does_not_report_missing_api(browser_page, monkeypatch):
    browser_page.url = "https://life.douyin.com/p/login"
    discover = Mock(return_value=None)
    monkeypatch.setattr(backend_aweme, "discover_backend_aweme_bind_list_url", discover)
    with pytest.raises(backend_aweme.BrowserExportError, match="^douyin_backend_login_required$"):
        backend_aweme.fetch_backend_aweme_records_via_bind_list_api(cdp_url="test")
    discover.assert_not_called()


def test_authenticated_missing_api_remains_a_distinct_failure(browser_page, monkeypatch):
    monkeypatch.setattr(backend_aweme, "discover_backend_aweme_bind_list_url", lambda _: None)
    with pytest.raises(backend_aweme.BrowserExportError, match="API URL was not observed"):
        backend_aweme.fetch_backend_aweme_records_via_bind_list_api(cdp_url="test")


def test_authenticated_fallback_still_returns_records(browser_page, monkeypatch):
    monkeypatch.setattr(backend_aweme, "discover_backend_aweme_bind_list_url", lambda _: "https://test/bind/list")
    records = [{"douyin_id": "test-account"}]
    monkeypatch.setattr(backend_aweme, "fetch_backend_aweme_bind_list_records", lambda *args: records)
    assert backend_aweme.fetch_backend_aweme_records_via_bind_list_api(cdp_url="test") == records


def test_login_redirect_during_api_discovery(browser_page, monkeypatch):
    def discover(page):
        page.url = "https://life.douyin.com/p/login"
        return None

    monkeypatch.setattr(backend_aweme, "discover_backend_aweme_bind_list_url", discover)
    with pytest.raises(backend_aweme.BrowserExportError, match="^douyin_backend_login_required$"):
        backend_aweme.fetch_backend_aweme_records_via_bind_list_api(cdp_url="test")


def test_long_child_traceback_preserves_login_reason():
    traceback = "Traceback:\n" + "  ordinary stack frame\n" * 200
    traceback += "apps.worker.browser_exports.backend_aweme.BrowserExportError: douyin_backend_login_required\n"
    assert sanitize_error_message(traceback) == "douyin_backend_login_required"
    assert sanitize_error_message("token=synthetic-secret\n" + traceback) == "douyin_backend_login_required"
    assert sanitize_error_message("token=synthetic-secret") == "[redacted sensitive error]"
    assert sanitize_error_message("other failure" * 300) == ("other failure" * 300)[:1800]


def test_business_page_login_query_is_not_a_login_page():
    assert not backend_aweme.is_login_required(
        "https://life.douyin.com/p/liteapp/bc_manage?redirect=/p/login", "抖音号明细"
    )


def test_content_read_redirect_race_reports_login(browser_page):
    def content():
        browser_page.url = "https://life.douyin.com/p/login"
        raise PlaywrightError("execution context was destroyed")

    browser_page.content.side_effect = content
    with pytest.raises(backend_aweme.BrowserExportError, match="^douyin_backend_login_required$"):
        backend_aweme.raise_if_login_required(browser_page)


def test_authenticated_api_error_is_not_misclassified(browser_page, monkeypatch):
    monkeypatch.setattr(backend_aweme, "discover_backend_aweme_bind_list_url", lambda _: "https://test/bind/list")
    fetch = Mock(side_effect=backend_aweme.BrowserExportError("API failed with HTTP 500"))
    monkeypatch.setattr(backend_aweme, "fetch_backend_aweme_bind_list_records", fetch)
    with pytest.raises(backend_aweme.BrowserExportError, match="HTTP 500"):
        backend_aweme.fetch_backend_aweme_records_via_bind_list_api(cdp_url="test")


def test_file_url_wait_login_redirect_reports_login(browser_page, monkeypatch, tmp_path):
    monkeypatch.setattr(backend_aweme, "click_backend_export", lambda *args, **kwargs: None)

    def wait(*args, **kwargs):
        browser_page.url = "https://life.douyin.com/p/login"
        raise backend_aweme.BrowserExportError("Timed out waiting for backend aweme workbook file URL.")

    monkeypatch.setattr(backend_aweme, "wait_for_completed_download", wait)
    with pytest.raises(backend_aweme.BrowserExportError, match="^douyin_backend_login_required$"):
        backend_aweme.export_workbook_via_browser(cdp_url="test", run_dir=tmp_path)


def test_login_failure_is_persisted_by_worker(db_session, browser_page, monkeypatch, tmp_path):
    from apps.api.dy_api.models import JobRun
    from apps.worker.scheduler import run_browser_export_job

    browser_page.url = "https://life.douyin.com/p/login"

    def runner(session, source_run_id):
        return backend_aweme.export_backend_aweme_records_via_browser(cdp_url="test", run_dir=tmp_path)

    with pytest.raises(backend_aweme.BrowserExportError):
        run_browser_export_job(db_session, job_id="login-expired", runner=runner)
    db_session.commit()
    db_session.expire_all()
    job = db_session.get(JobRun, "login-expired")
    assert job.status == "failed"
    assert job.error_message == "douyin_backend_login_required"
