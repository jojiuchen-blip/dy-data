from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimAwemeAccount, RawAwemeBinding
from apps.worker.browser_exports.backend_aweme import (
    BrowserExportError,
    is_login_required,
    normalize_cdp_websocket_url,
    run_backend_aweme_export,
)


def write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["抖音昵称", "抖音id", "所属账户id", "所属账户名称", "所属账户关联poi_id", "抖音号绑定状态"])
    sheet.append(["Owner One", "dy-1", "owner-1", "Store One Account", "poi-1", "认证成功"])
    workbook.save(path)


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


def test_backend_aweme_export_upserts_parsed_workbook_rows(db_session: Session, tmp_path: Path):
    workbook_path = tmp_path / "backend_aweme.xlsx"
    write_workbook(workbook_path)

    stats = run_backend_aweme_export(db_session, source_run_id="browser-run", workbook_path=workbook_path)

    assert stats.fetched == 1
    assert stats.upserted == 2
    assert count(db_session, RawAwemeBinding) == 1
    assert count(db_session, DimAwemeAccount) == 1

    binding = db_session.get(RawAwemeBinding, "owner-1:dy-1:poi-1")
    assert binding is not None
    assert binding.douyin_nickname == "Owner One"
    assert binding.binding_status == "认证成功"

    account = db_session.get(DimAwemeAccount, "owner-1")
    assert account is not None
    assert account.nickname == "Owner One"
