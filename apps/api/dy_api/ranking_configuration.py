"""Append-only ranking configuration; callers resolve and validate upload IDs."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.ranking_schema_v1 import org_history, eligibility


# Shared by configuration publishers and snapshot publishers to serialize pins.
RANKING_WRITE_LOCK = 7342091101
DATA_START = datetime(2026, 8, 31, 16, tzinfo=timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def publish_configuration(
    session: Session, *, organizations: list[dict], eligible_codes: list[str],
    effective_from: datetime,
) -> dict[str, str]:
    """Validate the complete configuration before any inserts; caller commits.

    The first approved baseline may start at the campaign data floor. Later
    changes must advance time and never update prior organization/eligibility
    rows or first-assignment pins. Upload endpoints must use server time for
    subsequent versions, rather than accepting client-selected backdating.
    """
    effective = _utc(effective_from)
    if effective < DATA_START:
        raise ValueError("名单生效时间不能早于2026-09-01")
    if not organizations or len(organizations) > 20000:
        raise ValueError("组织名单须包含1至20000家门店")
    normalized, stores, codes = [], set(), set()
    code_groups = {}
    for source in organizations:
        row = {field: _text(source.get(field)) for field in (
            "store_id", "service_store_code", "store_name", "group_name",
            "service_center_name", "district_name", "area_name")}
        if not all(row.values()):
            raise ValueError("门店编码、名称及集团/服务中心/大区/区域不能为空")
        if row["store_id"] in stores:
            raise ValueError("组织名单存在重复门店")
        stores.add(row["store_id"])
        codes.add(row["service_store_code"])
        center, district, area = (row[name] for name in (
            "service_center_name", "district_name", "area_name"))
        row.update(group_key=_text(source.get("group_key")) or _json([row["group_name"]]),
                   service_center_key=_json([center]), district_key=_json([center, district]),
                   area_key=_json([center, district, area]))
        normalized.append(row)
        code_groups.setdefault(row["service_store_code"], []).append(row)
    normalized.sort(key=lambda row: row["store_id"])
    approved = [_text(code) for code in eligible_codes]
    if not approved or not all(approved) or len(set(approved)) != len(approved):
        raise ValueError("资格名单不能为空或含重复编码")
    if set(approved) - codes:
        raise ValueError("资格名单存在未匹配组织表的服务店编码")
    for code, entries in code_groups.items():
        if len(entries) < 2:
            continue
        signatures = {_json({key: value for key, value in row.items() if key != "store_id"}) for row in entries}
        if code in approved or len(signatures) != 1:
            raise ValueError("重复服务店编码涉及适用名单或组织冲突，请先确认门店唯一归属")
    approved.sort()
    org_hash = sha256(_json(normalized).encode()).hexdigest()
    eligibility_hash = sha256(_json(approved).encode()).hexdigest()

    # Use the database transaction lock across workers, not a process mutex.
    if session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": RANKING_WRITE_LOCK})
    latest_org = session.execute(select(org_history).order_by(
        org_history.c.effective_from.desc()).limit(1)).mappings().first()
    latest_elig = session.execute(select(eligibility).where(
        eligibility.c.product_scope == "精诚养车").order_by(
        eligibility.c.effective_from.desc()).limit(1)).mappings().first()
    org_changed = not latest_org or latest_org["source_hash"] != org_hash
    eligibility_changed = not latest_elig or latest_elig["source_hash"] != eligibility_hash
    if org_changed or eligibility_changed:
        if any(row and effective <= _utc(row["effective_from"]) for row in (latest_org, latest_elig)):
            raise ValueError("新名单生效时间必须晚于已有版本，不能改写历史")
    org_version = "org-" + uuid4().hex if org_changed else latest_org["mapping_version"]
    elig_version = "elig-" + uuid4().hex if eligibility_changed else latest_elig["eligibility_version"]
    if org_changed:
        session.execute(org_history.insert(), [dict(row, mapping_version=org_version,
            effective_from=effective, source_hash=org_hash) for row in normalized])
    if eligibility_changed:
        session.execute(eligibility.insert(), [dict(eligibility_version=elig_version,
            service_store_code=code, product_scope="精诚养车", effective_from=effective,
            source_hash=eligibility_hash) for code in approved])
    return {"mapping_version": org_version, "eligibility_version": elig_version}
