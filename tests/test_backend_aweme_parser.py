from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
import pytest

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


def test_export_poi_column_preserves_original_case_and_provenance(tmp_path: Path):
    workbook = Workbook()
    workbook.active.append(["账户所属ID", "所属账户关联POI_id", "scene_id"])
    workbook.active.append(["account", "explicit-poi", "unverified-scene"])
    path = tmp_path / "explicit.xlsx"
    workbook.save(path)
    records = parse_backend_aweme_workbook(path)
    assert records[0]["poi_id"] == "explicit-poi"
    assert records[0]["raw_payload"]["scene_id"] == "unverified-scene"
    assert records.proof["source_columns"]["poi_id"] == ["所属账户关联POI_id"]


def test_export_conflicting_poi_columns_fail_without_silent_precedence(tmp_path: Path):
    workbook = Workbook()
    workbook.active.append(["账户所属ID", "所属账户关联poi_id", "poi_id"])
    workbook.active.append(["account", "poi-a", "poi-b"])
    path = tmp_path / "conflicting.xlsx"
    workbook.save(path)
    with pytest.raises(ValueError, match="conflicting_backend_aweme_source_fields:poi_id"):
        parse_backend_aweme_workbook(path)
