from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apps.worker.collectors.normalizers import data_items, first, next_cursor, text
from apps.worker.collectors.types import PhaseStats
from apps.worker.repositories import upsert_aweme_account, upsert_aweme_binding


def collect_aweme_bindings(session: Session, client: Any, *, source_run_id: str, page_size: int = 50) -> PhaseStats:
    stats = PhaseStats(name="aweme_bindings")
    cursor: str | None = "0"
    seen_cursors: set[str | None] = set()
    while cursor not in seen_cursors:
        seen_cursors.add(cursor)
        payload = client.query_craftsman_bind_info(cursor=cursor, size=page_size)
        rows = data_items(payload, "openapi_merchat_craftsman_info", "items", "list")
        for item in rows:
            stats.fetched += 1
            douyin_id = text(first(item, "douyin_id", "aweme_short_id", "aweme_id"))
            nickname = text(first(item, "douyin_nickname", "nickname"))
            account_id = text(first(item, "account_id_for_settlement", "craftsman_uid", "account_id"))
            poi_id = text(first(item, "poi_id"))
            if not (account_id or douyin_id):
                stats.skipped += 1
                continue

            binding_key = _binding_key(account_id, douyin_id, poi_id)
            binding_status = text(first(item, "binding_status", "bind_status"))
            upsert_aweme_binding(
                session,
                binding_key,
                douyin_id=douyin_id,
                douyin_nickname=nickname,
                account_id=account_id,
                account_name=text(first(item, "account_name", "poi_account_name")),
                poi_id=poi_id,
                binding_status=binding_status,
                raw_payload=item,
                source_run_id=source_run_id,
            )
            stats.upserted += 1

            if account_id:
                upsert_aweme_account(
                    session,
                    account_id,
                    nickname=nickname,
                    binding_status=binding_status,
                )
                stats.upserted += 1
        cursor = next_cursor(payload)
        if not cursor:
            break
    return stats


def _binding_key(account_id: str | None, douyin_id: str | None, poi_id: str | None) -> str:
    return ":".join(part or "-" for part in (account_id, douyin_id, poi_id))
