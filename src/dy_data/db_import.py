from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, create_engine, delete, insert
from sqlalchemy.engine import Engine


AWEME_FIELD_MAP = {
    "douyin_nickname": ["抖音昵称", "抖音号昵称", "昵称"],
    "douyin_id": ["抖音id", "抖音ID", "抖音号", "aweme_id"],
    "account_type": ["账号类型"],
    "account_name": ["所属账户名称", "所属账户名"],
    "account_id": ["所属账户id", "所属账户ID", "account_id"],
    "poi_id": ["所属账户关联poi_id", "所属账户关联POI_ID", "poi_id"],
    "auth_type": ["认证类别"],
    "auth_info": ["认证信息"],
    "auth_subject": ["认证主体"],
    "binding_status": ["抖音号绑定状态", "绑定状态"],
}


def database_url() -> str:
    value = os.getenv("DY_DATA_DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DY_DATA_DATABASE_URL is required for database import.")
    return value


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), future=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def metadata_with_tables() -> tuple[MetaData, Table, Table]:
    metadata = MetaData()
    raw_aweme_bindings = Table(
        "raw_aweme_bindings",
        metadata,
        Column("binding_key", String(128), primary_key=True),
        Column("row_hash", String(64), nullable=False),
        Column("douyin_nickname", Text),
        Column("douyin_id", String(64)),
        Column("account_type", String(64)),
        Column("account_name", Text),
        Column("account_id", String(64)),
        Column("poi_id", String(64)),
        Column("auth_type", String(64)),
        Column("auth_info", Text),
        Column("auth_subject", Text),
        Column("binding_status", String(64)),
        Column("raw_payload_json", Text, nullable=False),
        Column("source_run_id", String(64), nullable=False),
        Column("source_page_url", Text),
        Column("source_file_name", Text),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    job_runs = Table(
        "job_runs",
        metadata,
        Column("job_id", String(64), primary_key=True),
        Column("job_name", String(128), nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False),
        Column("finished_at", DateTime(timezone=True)),
        Column("status", String(32), nullable=False),
        Column("success_count", Integer, nullable=False, default=0),
        Column("failed_count", Integer, nullable=False, default=0),
        Column("error_message", Text),
        Column("metadata_json", Text),
    )
    return metadata, raw_aweme_bindings, job_runs


def ensure_tables(engine: Engine) -> tuple[Table, Table]:
    metadata, raw_aweme_bindings, job_runs = metadata_with_tables()
    metadata.create_all(engine)
    return raw_aweme_bindings, job_runs


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def pick(row: dict[str, Any], candidates: Iterable[str]) -> str:
    for name in candidates:
        if name in row:
            return clean(row.get(name))
    return ""


def stable_hash(parts: Iterable[str]) -> str:
    text = "\x1f".join(parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_aweme_row(
    row: dict[str, Any],
    *,
    source_run_id: str,
    source_page_url: str = "",
    source_file_name: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = {name: pick(row, fields) for name, fields in AWEME_FIELD_MAP.items()}
    row_hash = stable_hash([json.dumps(row, ensure_ascii=False, sort_keys=True)])
    key_parts = [
        normalized["douyin_id"],
        normalized["account_id"],
        normalized["poi_id"],
        normalized["douyin_nickname"],
    ]
    binding_key = stable_hash(key_parts)[:64] if any(key_parts) else row_hash[:64]
    timestamp = now or utc_now()
    return {
        "binding_key": binding_key,
        "row_hash": row_hash,
        **normalized,
        "raw_payload_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
        "source_run_id": source_run_id,
        "source_page_url": source_page_url,
        "source_file_name": source_file_name,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def import_backend_aweme_rows(
    rows: list[dict[str, Any]],
    *,
    source_run_id: str,
    source_page_url: str = "",
    source_file_name: str = "",
    engine: Engine | None = None,
) -> dict[str, Any]:
    active_engine = engine or make_engine()
    raw_aweme_bindings, job_runs = ensure_tables(active_engine)
    now = utc_now()
    job_id = source_run_id
    normalized_by_key = {}
    for row in rows:
        normalized = normalize_aweme_row(
            row,
            source_run_id=source_run_id,
            source_page_url=source_page_url,
            source_file_name=source_file_name,
            now=now,
        )
        normalized_by_key[normalized["binding_key"]] = normalized
    normalized_rows = list(normalized_by_key.values())
    keys = [row["binding_key"] for row in normalized_rows]

    with active_engine.begin() as conn:
        conn.execute(
            insert(job_runs).values(
                {
                    "job_id": job_id,
                    "job_name": "backend_aweme_edge_export",
                    "started_at": now,
                    "finished_at": None,
                    "status": "running",
                    "success_count": 0,
                    "failed_count": 0,
                    "error_message": "",
                    "metadata_json": json.dumps(
                        {
                            "source_page_url": source_page_url,
                            "source_file_name": source_file_name,
                            "row_count": len(rows),
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        )

        for start in range(0, len(keys), 500):
            chunk = keys[start : start + 500]
            if chunk:
                conn.execute(delete(raw_aweme_bindings).where(raw_aweme_bindings.c.binding_key.in_(chunk)))

        if normalized_rows:
            conn.execute(insert(raw_aweme_bindings), normalized_rows)

        conn.execute(
            job_runs.update()
            .where(job_runs.c.job_id == job_id)
            .values(
                {
                    "finished_at": utc_now(),
                    "status": "success",
                    "success_count": len(normalized_rows),
                    "failed_count": 0,
                }
            )
        )

    return {
        "table": "raw_aweme_bindings",
        "job_id": job_id,
        "rows_received": len(rows),
        "rows_imported": len(normalized_rows),
    }
