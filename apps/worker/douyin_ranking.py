from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimStoreOrgAssignment, utcnow


def _text(value: object) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def import_store_org_assignments(
    session: Session,
    workbook_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Import service-center/district/area ownership keyed by service-store code.

    Duplicate rows with identical organization values are ignored. Conflicting
    duplicate rows never overwrite an existing assignment and are reported for
    manual review. The uploaded file is treated as the current snapshot: rows
    absent from it are retained for auditability but marked inactive.
    """
    imported_at = now or utcnow()
    suffix = workbook_path.suffix.lower()
    if suffix == ".csv":
        with workbook_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                raise ValueError("store organization CSV has no header row")
            data_rows = list(enumerate(reader, start=2))
    elif suffix in {".xlsx", ".xlsm"}:
        workbook = load_workbook(workbook_path, read_only=True, data_only=True, keep_links=False)
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            raise ValueError("store organization workbook has no header row")
        data_rows = ((row_number, row) for row_number, row in enumerate(rows, start=2))
    else:
        raise ValueError("store organization mapping must be a .csv or .xlsx file")

    normalized_headers = {
        str(value).strip().lstrip("\ufeff"): index
        for index, value in enumerate(header)
        if _text(value)
    }
    aliases = {
        "code": ("服务店编码",),
        "store_name": ("服务店名称",),
        "group_code": ("集团编码",),
        "group_name": ("所属集团", "集团"),
        "service_center": ("所属服务中心", "服务中心"),
        "district": ("所属大区", "大区"),
        "area": ("所属区域", "区域"),
    }
    resolved: dict[str, int | None] = {}
    for field, names in aliases.items():
        resolved[field] = next(
            (normalized_headers[name] for name in names if name in normalized_headers),
            None,
        )
    missing = [field for field in ("code", "service_center", "district", "area") if resolved[field] is None]
    if missing:
        display_names = {
            "code": "服务店编码",
            "service_center": "服务中心/所属服务中心",
            "district": "大区/所属大区",
            "area": "区域/所属区域",
        }
        raise ValueError(
            "store organization mapping missing required columns: "
            + ", ".join(display_names[field] for field in missing)
        )

    stats = {
        "rows": 0,
        "updated": 0,
        "duplicates": 0,
        "conflicts": 0,
        "missing_code": 0,
        "deactivated": 0,
    }
    seen: dict[
        str,
        tuple[str | None, str | None, str | None, str | None, str | None, str | None],
    ] = {}
    for row_number, row in data_rows:
        if not row:
            continue
        stats["rows"] += 1
        code = _text(row[resolved["code"]])
        if not code:
            stats["missing_code"] += 1
            continue
        values = (
            _text(row[resolved["store_name"]]) if resolved["store_name"] is not None and resolved["store_name"] < len(row) else None,
            _text(row[resolved["group_code"]]) if resolved["group_code"] is not None and resolved["group_code"] < len(row) else None,
            _text(row[resolved["group_name"]]) if resolved["group_name"] is not None and resolved["group_name"] < len(row) else None,
            _text(row[resolved["service_center"]]),
            _text(row[resolved["district"]]),
            _text(row[resolved["area"]]),
        )
        previous = seen.get(code)
        if previous is not None:
            if previous == values:
                stats["duplicates"] += 1
            else:
                stats["conflicts"] += 1
            continue
        seen[code] = values

        assignment = session.get(DimStoreOrgAssignment, code)
        if assignment is not None:
            current = (
                assignment.service_store_name,
                assignment.group_code,
                assignment.group_name,
                assignment.service_center_name,
                assignment.district_name,
                assignment.area_name,
            )
            if current != values:
                stats["conflicts"] += 1
                continue
        else:
            assignment = DimStoreOrgAssignment(service_store_code=code)
            session.add(assignment)

        assignment.service_store_name = values[0]
        assignment.group_code = values[1]
        assignment.group_name = values[2]
        assignment.service_center_name = values[3]
        assignment.district_name = values[4]
        assignment.area_name = values[5]
        assignment.source_workbook = workbook_path.name
        assignment.source_row_number = row_number
        assignment.imported_at = imported_at
        assignment.is_active = True
        stats["updated"] += 1

    for assignment in session.scalars(select(DimStoreOrgAssignment)).all():
        if assignment.service_store_code not in seen and assignment.is_active:
            assignment.is_active = False
            assignment.updated_at = imported_at
            stats["deactivated"] += 1

    session.flush()
    return stats
