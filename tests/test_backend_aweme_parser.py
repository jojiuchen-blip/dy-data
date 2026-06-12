from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from apps.worker.browser_exports.backend_aweme_parser import parse_backend_aweme_workbook


def write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["抖音昵称", "抖音id", "所属账户id", "所属账户名称", "所属账户关联poi_id", "抖音号绑定状态"])
    sheet.append(["Owner One", "dy-1", "owner-1", "Store One Account", "poi-1", "认证成功"])
    workbook.save(path)


def test_parse_backend_aweme_workbook_normalizes_expected_fields(tmp_path: Path):
    workbook_path = tmp_path / "backend_aweme.xlsx"
    write_workbook(workbook_path)

    records = parse_backend_aweme_workbook(workbook_path)

    assert records == [
        {
            "douyin_nickname": "Owner One",
            "douyin_id": "dy-1",
            "account_id": "owner-1",
            "account_name": "Store One Account",
            "poi_id": "poi-1",
            "binding_status": "认证成功",
            "raw_payload": {
                "抖音昵称": "Owner One",
                "抖音id": "dy-1",
                "所属账户id": "owner-1",
                "所属账户名称": "Store One Account",
                "所属账户关联poi_id": "poi-1",
                "抖音号绑定状态": "认证成功",
            },
        }
    ]
