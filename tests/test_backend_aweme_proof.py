from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook
import pytest

from apps.worker.browser_exports import backend_aweme as backend
from apps.worker.browser_exports.backend_aweme_parser import parse_backend_aweme_workbook
from apps.worker.browser_exports.backend_aweme_proof import (
    BackendExportTask, EXPORT_START_PATH, apply_export_task_proof,
)


START_URL = "https://life.douyin.com" + EXPORT_START_PATH + "?root_life_account_id=synthetic-context"


def start(task, *, identity="our-task", method="POST", request=None, url=START_URL):
    task.observe_start(method=method, url=url, request_json={} if request is None else request,
        response={"status_code": 0, "data": {"status": 1, "download_id": identity}})


def poll(task, **changes):
    info = {"download_id": "our-task", "download_type": 120, "status": 2,
            "generate_start_time": 1793084035, "generate_complete_time": 1793084040,
            "file_name": "source.xlsx", "file_url": "https://example.test/source.xlsx?token=never-store-in-proof"}
    info.update(changes)
    task.observe_poll({"data": {"download_infos": [info]}})


def workbook_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["账号类型", "抖音号绑定状态", "所属账户id", "抖音id"])
    sheet.append(["子机构门店号", "认证成功", "qualified-account", "qualified-handle"])
    sheet.append(["个人号", "未知状态", None, None])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_exact_unfiltered_task_and_file_certify_complete_workbook(tmp_path):
    task = BackendExportTask()
    start(task)
    poll(task, status=1, generate_complete_time=0)
    assert task.file_info() is None
    poll(task)
    path = tmp_path / "source.xlsx"
    path.write_bytes(workbook_bytes())
    bound = task.bind_file(path)
    rows = apply_export_task_proof(parse_backend_aweme_workbook(bound), bound)
    assert rows.proof["complete"] and rows.proof["record_count"] == 2
    assert rows.proof["scope"] == "unfiltered_download_bc_empty_request"
    assert rows.proof["export_task"]["completed_task"]["download_id"] == "our-task"
    assert "never-store-in-proof" not in str(rows.proof)


@pytest.mark.parametrize("changes", [
    {"method": "GET"}, {"request": {"account_type": 20}},
    {"url": START_URL + "&filter_status=1"}, {"identity": ""},
])
def test_filtered_or_unverified_start_cannot_produce_success(changes, tmp_path):
    task = BackendExportTask()
    start(task, **changes)
    poll(task)
    assert task.file_info() is None and task.error_code
    with pytest.raises(ValueError):
        task.bind_file(tmp_path / "source.xlsx")


@pytest.mark.parametrize("changes", [
    {"download_type": 999}, {"generate_complete_time": 0},
    {"generate_start_time": True}, {"file_url": ""}, {"file_name": ""},
])
def test_invalid_completed_task_metadata_fails_closed(changes):
    task = BackendExportTask()
    start(task)
    poll(task, **changes)
    assert task.file_info() is None and task.error_code


def test_unrelated_completed_task_is_never_the_requested_export():
    task = BackendExportTask()
    start(task)
    poll(task, download_id="an-older-task")
    assert task.file_info() is None
    poll(task)
    assert task.file_info()


def test_multiple_start_or_changed_completion_is_not_silently_reused():
    task = BackendExportTask()
    start(task)
    start(task, identity="another-task")
    poll(task)
    assert task.file_info() is None
    task = BackendExportTask()
    start(task)
    poll(task)
    poll(task, generate_complete_time=1793084050)
    assert task.file_info() is None


def test_file_name_or_bytes_cannot_be_substituted_after_task_binding(tmp_path):
    task = BackendExportTask()
    start(task)
    poll(task)
    wrong = tmp_path / "another.xlsx"
    wrong.write_bytes(workbook_bytes())
    with pytest.raises(ValueError, match="name_mismatch"):
        task.bind_file(wrong)
    path = tmp_path / "source.xlsx"
    path.write_bytes(workbook_bytes())
    bound = task.bind_file(path)
    rows = parse_backend_aweme_workbook(bound)
    rows.proof["workbook_sha256"] = "0" * 64
    assert not apply_export_task_proof(rows, bound).proof["complete"]


def test_reset_dimensions_reads_full_official_file_with_header_only_dimensions(tmp_path):
    original = workbook_bytes()
    result = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(result, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b'<dimension ref="A1:D3"', b'<dimension ref="A1:D1"')
            target.writestr(item, data)
    path = tmp_path / "dimension-bug.xlsx"
    path.write_bytes(result.getvalue())
    rows = parse_backend_aweme_workbook(path)
    assert len(rows) == 2 and rows.proof["file_complete"]


def test_browser_flow_uses_exact_task_file_without_list_scope_or_mtime_fallback(monkeypatch, tmp_path):
    page = Mock()
    page.url = "https://life.douyin.com/p/liteapp/bc_manage"
    page.content.return_value = "商家号管理 登录人 导出数据"
    page.locator.return_value.inner_text.return_value = page.content.return_value
    events = {}
    page.on.side_effect = lambda name, handler: events.update({name: handler})
    request = Mock()
    request.get.return_value = SimpleNamespace(ok=True, body=workbook_bytes)
    context = SimpleNamespace(pages=[page], request=request)
    browser = SimpleNamespace(contexts=[context])
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda _: browser))
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: nullcontext(playwright))
    monkeypatch.setattr(backend, "resolve_playwright_cdp_url", lambda _: "ws://synthetic")
    def click(*args, **kwargs):
        events["response"](SimpleNamespace(url=START_URL, status=200,
            request=SimpleNamespace(method="POST", post_data_json={}),
            json=lambda: {"status_code": 0, "data": {"status": 1, "download_id": "our-task"}}))
        payload = {"data": {"download_infos": [{"download_id": "our-task", "download_type": 120,
            "status": 2, "generate_start_time": 1793084035, "generate_complete_time": 1793084040,
            "file_name": "source.xlsx", "file_url": "https://example.test/source.xlsx"}]}}
        events["response"](SimpleNamespace(url="https://life.douyin.com/life/gate/v3/download/mget", status=200, json=lambda: payload))
    monkeypatch.setattr(backend, "click_backend_export", click)
    unrelated_list = Mock(side_effect=AssertionError("a different list scope must not certify this export"))
    recent = Mock(side_effect=AssertionError("mtime is not exact task evidence"))
    monkeypatch.setattr(backend, "fetch_backend_aweme_records_via_bind_list_api", unrelated_list)
    monkeypatch.setattr(backend, "find_recent_workbook", recent)
    rows = backend.export_backend_aweme_records_via_browser(cdp_url="test", run_dir=tmp_path)
    assert rows.proof["complete"] and len(rows) == 2
    unrelated_list.assert_not_called()
    recent.assert_not_called()
    request.get.assert_called_once()
    assert list(tmp_path.iterdir()) == []
