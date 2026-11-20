from __future__ import annotations

from pathlib import Path
from datetime import timedelta

from openpyxl import Workbook
import pytest

from apps.worker.browser_exports.backend_aweme_parser import parse_backend_aweme_workbook
from apps.worker.browser_exports.backend_aweme import upsert_backend_aweme_records
from apps.worker import account_qualification as qualification
from apps.api.dy_api.models import AccountQualificationSnapshot, RawAwemeBinding


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


def test_literal_names_survive_workbook_ingestion_and_month_end_freeze(db_session, tmp_path: Path):
    workbook = Workbook()
    workbook.active.append(["抖音昵称", "抖音号", "账户所属ID", "所属账户名称", "所属账户关联poi_id",
                            "认证主体", "抖音号绑定状态", "账号类型", "备注"])
    workbook.active.append(["Sales.0", "000042", 123.0, "Store.0", "000007", "Company.0",
                            "认证成功", "子机构门店号", "Literal.0"])
    path = tmp_path / "literal-source.xlsx"
    workbook.save(path)
    records = parse_backend_aweme_workbook(path)
    row = records[0]
    assert row["douyin_nickname"] == row["raw_payload"]["抖音昵称"] == "Sales.0"
    assert row["account_name"] == row["raw_payload"]["所属账户名称"] == "Store.0"
    assert row["certified_subject_name"] == row["raw_payload"]["认证主体"] == "Company.0"
    assert row["raw_payload"]["备注"] == "Literal.0"
    assert row["account_id"] == row["raw_payload"]["账户所属ID"] == "123"
    assert row["douyin_id"] == row["raw_payload"]["抖音号"] == "000042"
    assert row["poi_id"] == row["raw_payload"]["所属账户关联poi_id"] == "000007"
    upsert_backend_aweme_records(db_session, records, source_run_id="literal-workbook")
    binding = db_session.get(RawAwemeBinding, "123:000042:000007:认证成功:子机构门店号")
    assert binding.douyin_nickname == "Sales.0"
    _, cutoff = qualification.month_bounds("2026-10")
    observation_id = qualification.start_observation(db_session, source_run_id="literal-workbook",
                                                      started_at=cutoff - timedelta(minutes=45))
    # Synthetic completeness proof isolates this regression from task download
    # certification, which has separate exact-task provenance tests.
    records.proof["complete"] = True
    qualification.complete_observation(db_session, observation_id, records,
                                        ended_at=cutoff - timedelta(minutes=40))
    version = qualification.freeze_month(db_session, "2026-10", now=cutoff)
    snapshot = db_session.get(AccountQualificationSnapshot, version.content_sha256)
    frozen = snapshot.records_json[0]
    assert frozen["douyin_nickname"] == frozen["raw_payload"]["抖音昵称"] == "Sales.0"
    assert frozen["raw_payload"]["所属账户名称"] == "Store.0"
    assert frozen["raw_payload"]["备注"] == "Literal.0"
    assert frozen["douyin_id"] == "000042"
    assert frozen["poi_id"] == "000007"
