from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.dy_api.models import DimStore, DimStorePoiMapping
from apps.api.dy_api.ranking_schema_v1 import eligibility, metadata, org_history


BASELINE_AT = datetime(2026, 8, 31, 16, tzinfo=timezone.utc)
ORG_HEADERS = (
    "门店名称",
    "所属账户关联poi_ID",
    "服务店编码",
    "服务店名称",
    "是否为直营店",
    "所属集团",
    "集团编码",
    "服务中心",
    "大区",
    "区域",
    "数据来源",
)
ELIGIBILITY_HEADERS = ("所属账户关联poi_ID", "门店名称")


def _organization_row(
    poi_id: str,
    service_store_code: str,
    *,
    center: str = "服务中心甲",
) -> tuple[str, ...]:
    return (
        f"抖音门店{poi_id}",
        poi_id,
        service_store_code,
        f"服务门店{poi_id}",
        "否",
        "精诚养车集团",
        "JC",
        center,
        "华东大区",
        "上海区域",
        "测试",
    )


def _write_xlsx(path: Path, headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    workbook = Workbook()
    try:
        worksheet = workbook.active
        worksheet.append(headers)
        for row in rows:
            worksheet.append(row)
        workbook.save(path)
    finally:
        workbook.close()


def _write_csv(path: Path, headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)


@pytest.fixture
def upload_db(db_session: Session) -> Session:
    metadata.create_all(db_session.bind)
    stores = [
        DimStore(store_id="store-a", store_name="源门店甲"),
        DimStore(store_id="store-b", store_name="源门店乙"),
        DimStore(store_id="store-c", store_name="源门店丙"),
    ]
    db_session.add_all(stores)
    db_session.flush()
    db_session.add_all(
        [
            DimStorePoiMapping(store_id="store-a", poi_id="10001"),
            DimStorePoiMapping(store_id="store-b", poi_id="10002"),
            DimStorePoiMapping(store_id="store-c", poi_id="10003"),
        ]
    )
    db_session.flush()
    return db_session


def _import_files(
    session: Session,
    organization_path: Path | None,
    eligibility_path: Path | None,
    now: datetime,
) -> dict:
    from apps.api.dy_api.ranking_configuration_upload import import_configuration_files

    return import_configuration_files(
        session,
        organization_path=organization_path,
        eligibility_path=eligibility_path,
        now=now,
    )


def test_initial_import_uses_real_headers_exact_poi_and_fixed_beijing_baseline(
    upload_db: Session, tmp_path: Path
) -> None:
    organization_path = tmp_path / "organization.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(
        organization_path,
        ORG_HEADERS,
        [_organization_row("10001", "CODE-A"), _organization_row("10002", "CODE-B")],
    )
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10002", "任意展示名")])

    result = _import_files(
        upload_db,
        organization_path,
        eligibility_path,
        datetime(2026, 9, 11, 3, tzinfo=timezone.utc),
    )

    assert result["change_status"] == "created"
    assert result["store_count"] == 2
    assert result["eligible_store_count"] == 1
    assert result["eligibility_count"] == 1
    assert result["changed"] is True
    assert result["organization_changed"] is True
    assert result["eligibility_changed"] is True
    assert result["effective_from"] == BASELINE_AT.isoformat()
    assert result["organization_effective_from"] == BASELINE_AT.isoformat()
    assert result["eligibility_effective_from"] == BASELINE_AT.isoformat()
    assert result["mapping_version"].startswith("org-")
    assert result["eligibility_version"].startswith("elig-")
    assert upload_db.scalar(
        select(org_history.c.store_id).where(org_history.c.service_store_code == "CODE-B")
    ) == "store-b"
    assert upload_db.scalar(select(eligibility.c.service_store_code)) == "CODE-B"
    assert upload_db.get(DimStore, "store-b").service_store_code is None


def test_import_accepts_reordered_required_columns_extras_optional_columns_and_xlsm(
    upload_db: Session, tmp_path: Path
) -> None:
    organization_headers = (
        "区域",
        "导出备注",
        "所属集团",
        "门店名称",
        "所属账户关联poi_ID",
        "大区",
        "服务中心",
        "服务店编码",
    )
    organization_path = tmp_path / "organization.xlsm"
    eligibility_path = tmp_path / "eligibility.csv"
    _write_xlsx(
        organization_path,
        organization_headers,
        [("上海区域", 1.25, "精诚养车集团", "门店甲", "10001", "华东大区", "中心甲", "CODE-A")],
    )
    _write_csv(
        eligibility_path,
        ("备注", "所属账户关联poi_ID"),
        [("忽略", "10001")],
    )

    result = _import_files(upload_db, organization_path, eligibility_path, BASELINE_AT)

    assert result["changed"] is True
    assert result["store_count"] == 1
    assert result["eligible_store_count"] == 1
    assert upload_db.scalar(select(org_history.c.store_name)) == "门店甲"


def test_each_file_can_be_updated_alone_and_other_latest_version_is_reused(
    upload_db: Session, tmp_path: Path
) -> None:
    initial_org = tmp_path / "organization.xlsx"
    initial_eligibility = tmp_path / "eligibility.xlsx"
    _write_xlsx(
        initial_org,
        ORG_HEADERS,
        [_organization_row("10001", "CODE-A"), _organization_row("10002", "CODE-B")],
    )
    _write_xlsx(initial_eligibility, ELIGIBILITY_HEADERS, [("10001", "展示名")])
    first = _import_files(upload_db, initial_org, initial_eligibility, BASELINE_AT)

    changed_at = datetime(2026, 9, 10, 4, 30, tzinfo=timezone.utc)
    changed_org = tmp_path / "organization.csv"
    _write_csv(
        changed_org,
        ORG_HEADERS,
        [
            _organization_row("10001", "CODE-A", center="服务中心乙"),
            _organization_row("10002", "CODE-B", center="服务中心乙"),
        ],
    )
    second = _import_files(upload_db, changed_org, None, changed_at)

    assert second["change_status"] == "updated"
    assert second["changed"] is True
    assert second["mapping_version"] != first["mapping_version"]
    assert second["eligibility_version"] == first["eligibility_version"]
    assert second["organization_changed"] is True
    assert second["eligibility_changed"] is False
    assert second["organization_effective_from"] == changed_at.isoformat()
    assert second["eligibility_effective_from"] == BASELINE_AT.isoformat()

    eligibility_changed_at = changed_at + timedelta(hours=1)
    changed_eligibility = tmp_path / "eligibility.csv"
    _write_csv(changed_eligibility, ELIGIBILITY_HEADERS, [("10002", "名称不参与匹配")])
    third = _import_files(upload_db, None, changed_eligibility, eligibility_changed_at)

    assert third["mapping_version"] == second["mapping_version"]
    assert third["eligibility_version"] != second["eligibility_version"]
    assert third["organization_changed"] is False
    assert third["eligibility_changed"] is True
    assert third["organization_effective_from"] == changed_at.isoformat()
    assert third["eligibility_effective_from"] == eligibility_changed_at.isoformat()
    assert upload_db.scalar(select(func.count()).select_from(org_history)) == 4
    assert upload_db.scalar(select(func.count()).select_from(eligibility)) == 2
    assert upload_db.scalar(
        select(org_history.c.service_center_name).where(
            org_history.c.mapping_version == first["mapping_version"],
            org_history.c.store_id == "store-a",
        )
    ) == "服务中心甲"


def test_initial_import_requires_both_files(upload_db: Session, tmp_path: Path) -> None:
    organization_path = tmp_path / "organization.xlsx"
    _write_xlsx(organization_path, ORG_HEADERS, [_organization_row("10001", "CODE-A")])

    with pytest.raises(ValueError, match="首次导入必须同时提供"):
        _import_files(upload_db, organization_path, None, BASELINE_AT)

    assert upload_db.scalar(select(func.count()).select_from(org_history)) == 0
    assert upload_db.scalar(select(func.count()).select_from(eligibility)) == 0


def test_duplicate_code_with_identical_organization_is_allowed_when_not_eligible(
    upload_db: Session, tmp_path: Path
) -> None:
    first_duplicate = list(_organization_row("10001", "DUPLICATE-CODE"))
    second_duplicate = list(_organization_row("10002", "DUPLICATE-CODE"))
    first_duplicate[3] = second_duplicate[3] = "同一服务门店"
    organization_path = tmp_path / "organization.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(
        organization_path,
        ORG_HEADERS,
        [tuple(first_duplicate), tuple(second_duplicate), _organization_row("10003", "CODE-C")],
    )
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10003", "适用门店")])

    result = _import_files(upload_db, organization_path, eligibility_path, BASELINE_AT)

    assert result["store_count"] == 3
    assert result["eligible_store_count"] == 1
    assert upload_db.scalar(select(eligibility.c.service_store_code)) == "CODE-C"
    assert upload_db.scalar(select(func.count()).select_from(org_history)) == 3


def test_duplicate_code_is_rejected_when_that_code_is_eligible(
    upload_db: Session, tmp_path: Path
) -> None:
    first_duplicate = list(_organization_row("10001", "DUPLICATE-CODE"))
    second_duplicate = list(_organization_row("10002", "DUPLICATE-CODE"))
    first_duplicate[3] = second_duplicate[3] = "同一服务门店"
    organization_path = tmp_path / "organization.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(
        organization_path,
        ORG_HEADERS,
        [tuple(first_duplicate), tuple(second_duplicate), _organization_row("10003", "CODE-C")],
    )
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10001", "适用门店")])

    with pytest.raises(ValueError):
        _import_files(upload_db, organization_path, eligibility_path, BASELINE_AT)

    assert upload_db.scalar(select(func.count()).select_from(org_history)) == 0
    assert upload_db.scalar(select(func.count()).select_from(eligibility)) == 0


def test_missing_group_district_and_area_are_kept_as_explicit_pending_assignment(
    upload_db: Session, tmp_path: Path
) -> None:
    incomplete = list(_organization_row("10001", "CODE-A"))
    incomplete[5] = ""
    incomplete[6] = "UNKNOWN-GROUP-CODE"
    incomplete[8] = ""
    incomplete[9] = ""
    organization_path = tmp_path / "organization.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(organization_path, ORG_HEADERS, [tuple(incomplete)])
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10001", "适用门店")])

    result = _import_files(upload_db, organization_path, eligibility_path, BASELINE_AT)

    assert result["store_count"] == 1
    assert result["eligible_store_count"] == 1
    assert result["missing_organization_count"] == 1
    stored = upload_db.execute(select(org_history)).mappings().one()
    assert stored["store_id"] == "store-a"
    assert stored["service_store_code"] == "CODE-A"
    assert stored["store_name"] == "服务门店10001"
    assert stored["service_center_name"] == "服务中心甲"
    assert stored["group_name"] == "待补充归属"
    assert stored["district_name"] == "待补充归属"
    assert stored["area_name"] == "待补充归属"
    assert stored["group_key"] != "UNKNOWN-GROUP-CODE"
    assert upload_db.scalar(select(eligibility.c.service_store_code)) == "CODE-A"


@pytest.mark.parametrize("column_index", [1, 2, 3])
def test_poi_code_and_store_name_remain_required(
    upload_db: Session, tmp_path: Path, column_index: int
) -> None:
    invalid = list(_organization_row("10001", "CODE-A"))
    invalid[column_index] = ""
    organization_path = tmp_path / f"missing-{column_index}.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(organization_path, ORG_HEADERS, [tuple(invalid)])
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10001", "适用门店")])

    with pytest.raises(ValueError):
        _import_files(upload_db, organization_path, eligibility_path, BASELINE_AT)

    assert upload_db.scalar(select(func.count()).select_from(org_history)) == 0
    assert upload_db.scalar(select(func.count()).select_from(eligibility)) == 0


@pytest.mark.parametrize("case", ["duplicate_poi", "duplicate_code", "empty", "bad_headers", "unmatched"])
def test_invalid_organization_rejects_whole_update_without_partial_version(
    upload_db: Session, tmp_path: Path, case: str
) -> None:
    initial_org = tmp_path / "initial-org.xlsx"
    initial_eligibility = tmp_path / "initial-eligibility.xlsx"
    _write_xlsx(initial_org, ORG_HEADERS, [_organization_row("10001", "CODE-A")])
    _write_xlsx(initial_eligibility, ELIGIBILITY_HEADERS, [("10001", "展示名")])
    _import_files(upload_db, initial_org, initial_eligibility, BASELINE_AT)
    before_org_count = upload_db.scalar(select(func.count()).select_from(org_history))
    before_eligibility_count = upload_db.scalar(select(func.count()).select_from(eligibility))

    invalid_path = tmp_path / f"invalid-{case}.xlsx"
    headers = ORG_HEADERS
    rows: list[tuple[object, ...]] = [_organization_row("10001", "CODE-A")]
    if case == "duplicate_poi":
        rows.append(_organization_row("10001", "CODE-B"))
    elif case == "duplicate_code":
        rows.append(_organization_row("10002", "CODE-A"))
    elif case == "empty":
        rows = []
    elif case == "bad_headers":
        headers = tuple("错误服务店编码" if value == "服务店编码" else value for value in headers)
    else:
        rows = [_organization_row("not-mapped", "CODE-X")]
    _write_xlsx(invalid_path, headers, rows)

    with pytest.raises(ValueError):
        _import_files(upload_db, invalid_path, None, BASELINE_AT + timedelta(days=1))

    assert upload_db.scalar(select(func.count()).select_from(org_history)) == before_org_count
    assert upload_db.scalar(select(func.count()).select_from(eligibility)) == before_eligibility_count


def test_conflicting_database_poi_mapping_is_rejected(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE dim_store_poi_mappings (store_id TEXT, poi_id TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO dim_store_poi_mappings (store_id, poi_id) VALUES "
            "('store-a', 'conflict-poi'), ('store-b', 'conflict-poi')"
        )
    organization_path = tmp_path / "organization.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(
        organization_path,
        ORG_HEADERS,
        [_organization_row("conflict-poi", "CODE-A")],
    )
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("conflict-poi", "展示名")])

    with Session(engine) as session:
        with pytest.raises(ValueError, match="多个门店"):
            _import_files(session, organization_path, eligibility_path, BASELINE_AT)
        assert session.scalar(select(func.count()).select_from(org_history)) == 0
        assert session.scalar(select(func.count()).select_from(eligibility)) == 0


def test_identical_upload_is_unchanged_and_keeps_original_effective_time(
    upload_db: Session, tmp_path: Path
) -> None:
    organization_path = tmp_path / "organization.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(organization_path, ORG_HEADERS, [_organization_row("10001", "CODE-A")])
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10001", "展示名")])
    first = _import_files(upload_db, organization_path, eligibility_path, BASELINE_AT)

    second = _import_files(
        upload_db,
        organization_path,
        eligibility_path,
        BASELINE_AT + timedelta(days=2),
    )

    assert second["change_status"] == "unchanged"
    assert second["changed"] is False
    assert second["mapping_version"] == first["mapping_version"]
    assert second["eligibility_version"] == first["eligibility_version"]
    assert second["effective_from"] == BASELINE_AT.isoformat()
    assert upload_db.scalar(select(func.count()).select_from(org_history)) == 1
    assert upload_db.scalar(select(func.count()).select_from(eligibility)) == 1


def test_postgres_import_locks_before_reading_versions_for_single_file_reuse(
    upload_db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.dy_api.ranking_configuration import RANKING_WRITE_LOCK

    organization_path = tmp_path / "organization.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(organization_path, ORG_HEADERS, [_organization_row("10001", "CODE-A")])
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10001", "展示名")])
    _import_files(upload_db, organization_path, eligibility_path, BASELINE_AT)
    upload_db.commit()

    changed_org = tmp_path / "changed-organization.xlsx"
    _write_xlsx(
        changed_org,
        ORG_HEADERS,
        [_organization_row("10001", "CODE-A", center="服务中心乙")],
    )
    engine = upload_db.bind
    lock_keys: list[int] = []
    raw_connection = engine.raw_connection()
    try:
        raw_connection.driver_connection.create_function(
            "pg_advisory_xact_lock", 1, lambda key: lock_keys.append(key) or key
        )
    finally:
        raw_connection.close()
    statements: list[str] = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        result = _import_files(
            upload_db,
            changed_org,
            None,
            BASELINE_AT + timedelta(days=1),
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert result["changed"] is True
    assert "pg_advisory_xact_lock" in statements[0]
    assert lock_keys[0] == RANKING_WRITE_LOCK


def test_file_and_xlsx_expansion_limits_are_enforced(
    upload_db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import apps.api.dy_api.ranking_configuration_upload as upload

    organization_path = tmp_path / "organization.xlsx"
    eligibility_path = tmp_path / "eligibility.xlsx"
    _write_xlsx(organization_path, ORG_HEADERS, [_organization_row("10001", "CODE-A")])
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10001", "展示名")])

    monkeypatch.setattr(upload, "MAX_IMPORT_BYTES", 1)
    with pytest.raises(ValueError, match="10 MiB"):
        upload.import_configuration_files(
            upload_db,
            organization_path=organization_path,
            eligibility_path=eligibility_path,
            now=BASELINE_AT,
        )

    monkeypatch.setattr(upload, "MAX_IMPORT_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(upload, "MAX_XLSX_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(ValueError, match="100 MiB"):
        upload.import_configuration_files(
            upload_db,
            organization_path=organization_path,
            eligibility_path=eligibility_path,
            now=BASELINE_AT,
        )


def test_csv_parser_error_is_reported_as_value_error(
    upload_db: Session, tmp_path: Path
) -> None:
    organization_path = tmp_path / "organization.csv"
    eligibility_path = tmp_path / "eligibility.xlsx"
    oversized_field = "x" * (csv.field_size_limit() + 1)
    row = list(_organization_row("10001", "CODE-A"))
    row[-1] = oversized_field
    _write_csv(organization_path, ORG_HEADERS, [tuple(row)])
    _write_xlsx(eligibility_path, ELIGIBILITY_HEADERS, [("10001", "适用门店")])

    with pytest.raises(ValueError, match="CSV文件无法解析"):
        _import_files(upload_db, organization_path, eligibility_path, BASELINE_AT)

    assert upload_db.scalar(select(func.count()).select_from(org_history)) == 0
    assert upload_db.scalar(select(func.count()).select_from(eligibility)) == 0
