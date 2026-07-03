from __future__ import annotations

from pathlib import Path
import zipfile

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimAwemeAccount, DimStore, DimStorePoiMapping, RawAwemeBinding
from apps.worker.browser_exports.backend_aweme import (
    BrowserExportError,
    backend_aweme_api_binding_status,
    export_workbook_search_dirs,
    extract_completed_download_info,
    find_recent_workbook,
    is_relevant_export_response,
    is_valid_poi_id,
    is_login_required,
    normalize_download_file_url,
    normalize_cdp_websocket_url,
    redact_url,
    resolve_playwright_cdp_url,
    records_from_backend_aweme_api_items,
    run_backend_aweme_export,
    upsert_backend_aweme_records,
    workbook_filename,
)
from apps.worker.browser_exports import backend_aweme


def write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["抖音昵称", "抖音id", "所属账户id", "所属账户名称", "所属账户关联poi_id", "抖音号绑定状态"])
    sheet.append(["Owner One", "dy-1", "owner-1", "Store One Account", "poi-1", "认证成功"])
    workbook.save(path)


def force_workbook_dimension_a1(path: Path) -> None:
    temp_path = path.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temp_path, "w") as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                content = content.replace(b'<dimension ref="A1:F2"/>', b'<dimension ref="A1"/>')
            target.writestr(item, content)
    temp_path.replace(path)


def count(session: Session, model: type) -> int:
    value = session.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


def test_backend_aweme_export_requires_cdp_when_no_workbook_path(db_session: Session):
    with pytest.raises(BrowserExportError) as exc_info:
        run_backend_aweme_export(db_session, source_run_id="browser-run", cdp_url="", workbook_path=None)

    assert "BROWSER_CDP_URL" in str(exc_info.value)


def test_backend_aweme_export_detects_login_state():
    assert is_login_required("https://life.douyin.com/login", "") is True
    assert is_login_required("https://life.douyin.com/workbench", "请登录后继续") is True
    assert is_login_required("https://life.douyin.com/workbench", "抖音号明细") is False


def test_backend_aweme_export_rewrites_loopback_cdp_websocket_url():
    websocket_url = "ws://127.0.0.1:9223/devtools/browser/browser-id"

    assert (
        normalize_cdp_websocket_url("http://browser:9222", websocket_url)
        == "ws://browser:9222/devtools/browser/browser-id"
    )


def test_backend_aweme_export_waits_for_cdp_endpoint(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"webSocketDebuggerUrl":"ws://127.0.0.1:9223/devtools/browser/browser-id"}'

    def fake_urlopen(url: str, timeout: int):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise OSError("not ready")
        return Response()

    monkeypatch.setenv("BROWSER_CDP_READY_TIMEOUT_SECONDS", "5")
    monkeypatch.setattr(backend_aweme, "urlopen", fake_urlopen)
    monkeypatch.setattr(backend_aweme.time, "sleep", lambda seconds: None)

    assert (
        resolve_playwright_cdp_url("http://browser:9222")
        == "ws://browser:9222/devtools/browser/browser-id"
    )
    assert len(calls) == 2


def test_backend_aweme_export_extracts_completed_download_file_url():
    payload = {
        "data": {
            "download_infos": [
                {"download_id": "one", "status": 1},
                {
                    "download_id": "two",
                    "status": 2,
                    "file_name": "backend_aweme.xlsx",
                    "file_url": "sf26-sign.douyinstatic.com/download_record/backend_aweme.xlsx",
                },
            ]
        }
    }

    assert extract_completed_download_info(payload) == {
        "file_name": "backend_aweme.xlsx",
        "file_url": "sf26-sign.douyinstatic.com/download_record/backend_aweme.xlsx",
    }
    assert normalize_download_file_url("sf26-sign.douyinstatic.com/download_record/backend_aweme.xlsx").startswith(
        "https://"
    )
    assert workbook_filename("", "https://example.test/files/backend_aweme.xlsx?token=redacted") == "backend_aweme.xlsx"
    assert is_valid_poi_id("poi-1") is True
    assert is_valid_poi_id("0") is False


def test_backend_aweme_export_maps_bind_list_api_items():
    records = records_from_backend_aweme_api_items(
        [
            {
                "account_id": "account-1",
                "scene_id": "account-1",
                "scene_name": "Store One",
                "status": 1,
                "integration_content": {
                    "user_info": {
                        "aweme_id": "dy-1",
                        "nickname": "Owner One",
                        "account_name": "Store One Account",
                    },
                    "subject_info": {"company_name": "Subject One"},
                },
            },
            {
                "account_id": "account-2",
                "scene_id": "poi-2",
                "scene_name": "Store Two",
                "status": 6,
                "integration_content": {
                    "user_info": {
                        "aweme_id": "dy-2",
                        "nickname": "Owner Two",
                    },
                    "subject_info": {"company_name": "Subject Two"},
                },
            },
        ]
    )

    assert records[0]["douyin_id"] == "dy-1"
    assert records[0]["account_id"] == "account-1"
    assert records[0]["poi_id"] is None
    assert records[0]["binding_status"] == "active"
    assert records[0]["certified_subject_name"] == "Subject One"
    assert records[1]["poi_id"] == "poi-2"
    assert records[1]["binding_status"] == "rejected"
    assert backend_aweme_api_binding_status({"status": 2}, {}) == "inactive"


def test_backend_aweme_export_finds_recent_workbook(tmp_path: Path):
    old_workbook = tmp_path / "old.xlsx"
    old_workbook.write_bytes(b"old")
    old_mtime = 1_700_000_000
    new_dir = tmp_path / "Downloads"
    new_dir.mkdir()
    new_workbook = new_dir / "new.xlsx"
    new_workbook.write_bytes(b"new")
    new_mtime = old_mtime + 100
    old_workbook.touch()
    new_workbook.touch()
    import os

    os.utime(old_workbook, (old_mtime, old_mtime))
    os.utime(new_workbook, (new_mtime, new_mtime))

    assert find_recent_workbook([tmp_path], since_epoch=old_mtime + 1) == new_workbook
    assert find_recent_workbook([tmp_path], since_epoch=new_mtime + 1) is None


def test_backend_aweme_export_search_dirs_include_download_env(monkeypatch, tmp_path: Path):
    download_dir = tmp_path / "downloads"
    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setenv("BROWSER_EXPORT_DOWNLOAD_DIR", str(download_dir))
    monkeypatch.setenv("BROWSER_EXPORT_ARTIFACT_DIR", str(artifact_dir))

    search_dirs = export_workbook_search_dirs(tmp_path)

    assert tmp_path.resolve() in search_dirs
    assert download_dir.resolve() in search_dirs
    assert artifact_dir.resolve() in search_dirs


def test_backend_aweme_export_redacts_relevant_response_urls():
    assert is_relevant_export_response("https://life.douyin.com/life/gate/v3/download/mget") is True
    assert is_relevant_export_response("https://example.test/health") is False
    assert redact_url("https://example.test/export?token=secret&file=one.xlsx") == (
        "https://example.test/export?<redacted>"
    )
    assert redact_url("https://example.test/export") == "https://example.test/export"


def test_backend_aweme_export_upserts_parsed_workbook_rows(db_session: Session, tmp_path: Path):
    workbook_path = tmp_path / "backend_aweme.xlsx"
    write_workbook(workbook_path)

    stats = run_backend_aweme_export(db_session, source_run_id="browser-run", workbook_path=workbook_path)

    assert stats.fetched == 1
    assert stats.upserted == 4
    assert count(db_session, RawAwemeBinding) == 1
    assert count(db_session, DimAwemeAccount) == 1
    assert count(db_session, DimStore) == 1
    assert count(db_session, DimStorePoiMapping) == 1

    binding = db_session.scalar(select(RawAwemeBinding).where(RawAwemeBinding.douyin_id == "dy-1"))
    assert binding is not None
    assert binding.douyin_nickname == "Owner One"
    assert binding.binding_key.startswith("owner-1:dy-1:poi-1:")
    assert binding.binding_status == "认证成功"

    account = db_session.get(DimAwemeAccount, "owner-1")
    assert account is not None
    assert account.nickname == "Owner One"
    assert account.store_id == "owner-1"

    store = db_session.get(DimStore, "owner-1")
    assert store is not None
    assert store.store_name == "Store One Account"

    mapping = db_session.get(DimStorePoiMapping, ("owner-1", "poi-1"))
    assert mapping is not None
    assert mapping.mapping_source == "backend_aweme_export"


def test_backend_aweme_export_reads_workbook_with_incorrect_dimension(db_session: Session, tmp_path: Path):
    workbook_path = tmp_path / "backend_aweme_bad_dimension.xlsx"
    write_workbook(workbook_path)
    force_workbook_dimension_a1(workbook_path)

    stats = run_backend_aweme_export(db_session, source_run_id="browser-run", workbook_path=workbook_path)

    assert stats.fetched == 1
    assert stats.upserted == 4


def test_backend_aweme_export_skips_placeholder_poi_and_updates_existing_mapping(db_session: Session):
    first = upsert_backend_aweme_records(
        db_session,
        [
            {
                "douyin_id": "dy-1",
                "douyin_nickname": "Owner One",
                "account_id": "owner-1",
                "account_name": "Store One",
                "certified_subject_name": "Subject One",
                "poi_id": "poi-1",
            },
            {
                "douyin_id": "dy-2",
                "douyin_nickname": "Owner Two",
                "account_id": "owner-2",
                "account_name": "Store Two",
                "poi_id": "0",
            },
        ],
        source_run_id="browser-run",
    )
    second = upsert_backend_aweme_records(
        db_session,
        [
            {
                "douyin_id": "dy-3",
                "douyin_nickname": "Owner Three",
                "account_id": "owner-3",
                "account_name": "Store Three",
                "poi_id": "poi-1",
            }
        ],
        source_run_id="browser-run",
    )

    assert first.fetched == 2
    assert second.fetched == 1
    assert count(db_session, DimStorePoiMapping) == 1
    mapping = db_session.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == "poi-1"))
    assert mapping is not None
    assert mapping.store_id == "owner-3"

    store = db_session.get(DimStore, "owner-1")
    assert store is not None
    assert store.certified_subject_name == "Subject One"


def test_backend_aweme_export_preserves_distinct_binding_status_rows(db_session: Session):
    stats = upsert_backend_aweme_records(
        db_session,
        [
            {
                "douyin_id": "dy-1",
                "douyin_nickname": "Owner One",
                "account_id": "owner-1",
                "account_name": "Store One",
                "poi_id": "poi-1",
                "binding_status": "active",
                "certified_subject_name": "Active Subject",
                "raw_payload": {"account_type": "child"},
            },
            {
                "douyin_id": "dy-1",
                "douyin_nickname": "Owner One",
                "account_id": "owner-1",
                "account_name": "Store One",
                "poi_id": "poi-1",
                "binding_status": "inactive",
                "certified_subject_name": "Inactive Subject",
                "raw_payload": {"account_type": "personal"},
            },
        ],
        source_run_id="browser-run",
    )

    assert stats.fetched == 2
    assert count(db_session, RawAwemeBinding) == 2
    statuses = set(db_session.scalars(select(RawAwemeBinding.binding_status)))
    assert statuses == {"active", "inactive"}

    store = db_session.get(DimStore, "owner-1")
    assert store is not None
    assert store.certified_subject_name == "Active Subject"

    account = db_session.get(DimAwemeAccount, "owner-1")
    assert account is not None
    assert account.binding_status == "active"
