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
    extract_completed_download_info,
    is_valid_poi_id,
    is_login_required,
    normalize_download_file_url,
    normalize_cdp_websocket_url,
    run_backend_aweme_export,
    upsert_backend_aweme_records,
    workbook_filename,
)


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

    binding = db_session.get(RawAwemeBinding, "owner-1:dy-1:poi-1")
    assert binding is not None
    assert binding.douyin_nickname == "Owner One"
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
