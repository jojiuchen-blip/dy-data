from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from apps.worker.browser_exports.backend_aweme_parser import parse_backend_aweme_workbook


def write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "douyin_nickname",
            "douyin_id",
            "account_id",
            "account_name",
            "poi_id",
            "certified_subject_name",
            "binding_status",
        ]
    )
    sheet.append(["Owner One", "dy-1", "owner-1", "Store One Account", "poi-1", "Subject One", "active"])
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
            "certified_subject_name": "Subject One",
            "binding_status": "active",
            "raw_payload": {
                "douyin_nickname": "Owner One",
                "douyin_id": "dy-1",
                "account_id": "owner-1",
                "account_name": "Store One Account",
                "poi_id": "poi-1",
                "certified_subject_name": "Subject One",
                "binding_status": "active",
            },
        }
    ]
