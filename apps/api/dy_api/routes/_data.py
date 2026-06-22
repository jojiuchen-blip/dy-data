from __future__ import annotations

import csv
import io
import json
import math
import os
import re
from collections.abc import Generator, Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends

try:
    from sqlalchemy import select, text
except ImportError:  # pragma: no cover - covered only in stripped runtime images.
    select = None  # type: ignore[assignment]
    text = None

try:
    from apps.api.dy_api.models import (
        ClueReassignRuleSetting,
        DimNonCommissionOwnerAccount,
        DimSkuProductRule,
    )
    from apps.api.dy_api.rule_utils import normalize_owner_account_name
except ImportError:  # pragma: no cover - covered only in stripped runtime images.
    ClueReassignRuleSetting = None  # type: ignore[assignment]
    DimNonCommissionOwnerAccount = None  # type: ignore[assignment]
    DimSkuProductRule = None  # type: ignore[assignment]
    normalize_owner_account_name = None  # type: ignore[assignment]

try:
    from apps.worker.pipeline import build_douyin_client_from_env
except ImportError:  # pragma: no cover - covered only in stripped runtime images.
    build_douyin_client_from_env = None  # type: ignore[assignment]


SENSITIVE_ERROR_RE = re.compile(
    r"(?i)(cookie|token|secret|password|passwd|authorization|credential)"
)
FILE_PATH_RE = re.compile(
    r"(?:(?:[A-Za-z]:\\|/)(?:Users|home|root|var|tmp|opt|data|mnt)[^\s,;]*)"
)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_SESSION_FACTORY: Any | None = None


def generated_at() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def sanitize_error_message(message: str | None) -> str | None:
    if not message:
        return message
    if SENSITIVE_ERROR_RE.search(message):
        return "[redacted sensitive error]"
    return FILE_PATH_RE.sub("[path redacted]", message)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_db_get_session():
    try:
        from dy_api.db import get_session
    except ImportError:
        get_session = None
    if get_session is not None:
        return get_session

    try:
        from dy_api import db
    except ImportError:
        return None

    database_url = db.get_database_url(required=False)
    if not database_url:
        return None

    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        engine = db.make_engine(database_url)
        _SESSION_FACTORY = db.make_session_factory(engine)

    # Compatibility path for the DB slice before it exposes a FastAPI dependency.
    def session_dependency():
        with db.session_scope(_SESSION_FACTORY) as session:
            yield session

    return session_dependency


def get_session_dependency() -> Generator[Any | None, None, None]:
    dependency = _load_db_get_session()
    if dependency is None:
        yield None
        return

    value = dependency()
    if hasattr(value, "__next__"):
        generator = value
        try:
            yield next(generator)
        finally:
            generator.close()
        return

    if hasattr(value, "__enter__") and hasattr(value, "__exit__"):
        with value as session:
            yield session
        return

    yield value


def get_data_store(session: Any | None = Depends(get_session_dependency)):
    return DashboardDataStore(session)


def _as_dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _to_float(value: Any, default: float = 0) -> float:
    if value is None:
        return default
    return float(value)


def _to_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalized_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", _to_str(value))
    if len(digits) < 11:
        return ""
    return digits[-11:]


def _masked_phone(value: Any) -> str:
    phone = _normalized_phone(value)
    if not phone:
        return ""
    return f"{phone[:3]}****{phone[-4:]}"


def _phone_from_clue_payload(row: dict[str, Any]) -> str:
    phone = _normalized_phone(row.get("telephone"))
    if phone:
        return phone
    payload = _json_object(row.get("raw_payload"))
    for key in (
        "telephone",
        "tel_addr",
        "phone",
        "mobile",
        "phone_number",
        "customer_phone",
        "contact_phone",
    ):
        phone = _normalized_phone(payload.get(key))
        if phone:
            return phone
    return ""


def _encrypted_phone_from_clue_payload(row: dict[str, Any]) -> str:
    for key in ("enc_telephone", "encrypted_telephone", "telephone"):
        value = _to_str(row.get(key)).strip()
        if _is_online_cipher(value):
            return value
    payload = _json_object(row.get("raw_payload"))
    for key in (
        "enc_telephone",
        "encrypted_telephone",
        "telephone",
        "tel_addr",
        "phone",
        "mobile",
        "phone_number",
        "customer_phone",
        "contact_phone",
    ):
        value = _to_str(payload.get(key)).strip()
        if _is_online_cipher(value):
            return value
    return ""


def _is_online_cipher(value: str) -> bool:
    return value.startswith("Enc.")


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _total_pages(total: int, page_size: int) -> int:
    if total <= 0:
        return 0
    return math.ceil(total / page_size)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0
    return round(numerator / denominator, 4)


def _in_clause_params(prefix: str, values: Iterable[str]) -> tuple[str, dict[str, Any]]:
    cleaned = [value for value in dict.fromkeys(_to_str(value).strip() for value in values) if value]
    params = {f"{prefix}_{index}": value for index, value in enumerate(cleaned)}
    return ", ".join(f":{key}" for key in params), params


def _parse_filter_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(SHANGHAI_TZ) if value.tzinfo else value.replace(tzinfo=SHANGHAI_TZ)
    raw = _to_str(value).strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            parsed = datetime.fromisoformat(raw)
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(SHANGHAI_TZ) if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI_TZ)


def _remaining_reassign_seconds(expires_at: Any) -> int | None:
    expires = _parse_filter_datetime(expires_at)
    if expires is None:
        return None
    return max(0, int((expires - generated_at()).total_seconds()))


class DashboardDataStore:
    def __init__(self, session: Any | None):
        self.session = session

    @property
    def available(self) -> bool:
        return self.session is not None and text is not None

    def _dialect_name(self) -> str:
        if self.session is None:
            return ""
        try:
            bind = self.session.get_bind()
            return bind.dialect.name
        except Exception:
            return ""

    def _month_expr(self, column: str) -> str:
        if self._dialect_name() == "sqlite":
            return f"substr(CAST({column} AS TEXT), 1, 7)"
        return f"to_char({column} AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM')"

    def _execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self.available:
            return []
        try:
            result = self.session.execute(text(sql), params or {})
            return _as_dicts(result.mappings().all())
        except Exception:
            if _truthy(os.getenv("DY_API_ALLOW_EMPTY_ON_DB_ERROR")):
                return []
            raise

    def list_stores(self, scope_store_ids: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        where_sql = ""
        if scope_store_ids is not None:
            placeholders, params = _in_clause_params("store_scope", scope_store_ids)
            if not placeholders:
                return []
            where_sql = f"WHERE store_id IN ({placeholders})"
        return [
            {
                "store_id": _to_str(row.get("store_id")),
                "store_name": _to_str(row.get("store_name")),
            }
            for row in self._execute(
                f"""
                SELECT store_id, store_name
                FROM dim_stores
                {where_sql}
                ORDER BY store_name, store_id
                """,
                params,
            )
        ]

    def list_product_types(self) -> list[str]:
        product_types: set[str] = set()
        for sql in (
            "SELECT DISTINCT product_type FROM dim_sku_product_rules WHERE product_type IS NOT NULL",
            "SELECT DISTINCT product_type FROM settlement_order_details WHERE product_type IS NOT NULL",
        ):
            for row in self._execute(sql):
                product_type = _to_str(row.get("product_type")).strip()
                if product_type and product_type != "all":
                    product_types.add(product_type)
        return ["all", *sorted(product_types)]

    def list_sale_months(self) -> list[str]:
        expr = self._month_expr("sale_time")
        rows = self._execute(
            f"""
            SELECT DISTINCT {expr} AS month
            FROM settlement_order_details
            WHERE sale_time IS NOT NULL
            ORDER BY month DESC
            """
        )
        return [_to_str(row.get("month")) for row in rows if row.get("month")]

    def list_verify_months(self) -> list[str]:
        expr = self._month_expr("verify_time")
        rows = self._execute(
            f"""
            SELECT DISTINCT {expr} AS month
            FROM settlement_order_details
            WHERE verify_time IS NOT NULL
            ORDER BY month DESC
            """
        )
        return [_to_str(row.get("month")) for row in rows if row.get("month")]

    def _sku_rule_source_cte(self) -> str:
        return """
            WITH sku_source AS (
                SELECT sku_id,
                       product_name,
                       order_id,
                       NULL AS coupon_id
                FROM raw_douyin_orders
                WHERE sku_id IS NOT NULL AND sku_id != ''
                UNION ALL
                SELECT sku_id,
                       product_name,
                       NULL AS order_id,
                       coupon_id
                FROM raw_douyin_verify_records
                WHERE sku_id IS NOT NULL AND sku_id != ''
                UNION ALL
                SELECT sku_id,
                       product_name,
                       NULL AS order_id,
                       NULL AS coupon_id
                FROM dim_sku_product_rules
                WHERE sku_id IS NOT NULL AND sku_id != ''
            ),
            sku_rows AS (
                SELECT sku_id,
                       COALESCE(MAX(NULLIF(product_name, '')), '') AS product_name,
                       COUNT(DISTINCT order_id) AS order_count,
                       COUNT(DISTINCT coupon_id) AS verified_coupon_count
                FROM sku_source
                GROUP BY sku_id
            )
        """

    def list_sku_rules(
        self, *, page: int, page_size: int, q: str | None = None
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(page_size, 1000))
        offset = (page - 1) * page_size
        params: dict[str, Any] = {"limit": page_size, "offset": offset}
        count_where_sql = ""
        row_where_sql = ""
        query = _to_str(q).strip().lower()
        if query:
            count_where_sql = "WHERE lower(sku_id) LIKE :q OR lower(product_name) LIKE :q"
            row_where_sql = (
                "WHERE lower(sku_rows.sku_id) LIKE :q "
                "OR lower(sku_rows.product_name) LIKE :q"
            )
            params["q"] = f"%{query}%"

        source_cte = self._sku_rule_source_cte()
        total_rows = self._execute(
            f"""
            {source_cte}
            SELECT COUNT(*) AS total
            FROM sku_rows
            {count_where_sql}
            """,
            params,
        )
        rows = self._execute(
            f"""
            {source_cte}
            SELECT sku_rows.sku_id,
                   COALESCE(NULLIF(rules.product_name, ''), sku_rows.product_name, '') AS product_name,
                   COALESCE(rules.product_type, '') AS product_type,
                   COALESCE(rules.commission_rate, 0) AS commission_rate,
                   COALESCE(rules.is_service_product, true) AS is_service_product,
                   sku_rows.order_count,
                   sku_rows.verified_coupon_count
            FROM sku_rows
            LEFT JOIN dim_sku_product_rules rules ON rules.sku_id = sku_rows.sku_id
            {row_where_sql}
            ORDER BY sku_rows.sku_id
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        total = _to_int(total_rows[0].get("total"), 0) if total_rows else 0
        return {
            "rows": [self._clean_sku_rule_row(row) for row in rows],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": _total_pages(total, page_size),
            },
        }

    def lookup_sku_rules(self, sku_ids: list[str]) -> dict[str, Any]:
        requested: list[str] = []
        seen: set[str] = set()
        duplicate_seen: set[str] = set()
        duplicate_sku_ids: list[str] = []
        for value in sku_ids:
            sku_id = _to_str(value).strip()
            if not sku_id:
                continue
            if sku_id in seen:
                if sku_id not in duplicate_seen:
                    duplicate_sku_ids.append(sku_id)
                    duplicate_seen.add(sku_id)
                continue
            requested.append(sku_id)
            seen.add(sku_id)

        if not requested:
            return {"rows": [], "missing_sku_ids": [], "duplicate_sku_ids": duplicate_sku_ids}

        params = {f"sku_{index}": sku_id for index, sku_id in enumerate(requested)}
        placeholders = ", ".join(f":sku_{index}" for index in range(len(requested)))
        rows = self._execute(
            f"""
            {self._sku_rule_source_cte()}
            SELECT sku_rows.sku_id,
                   COALESCE(NULLIF(rules.product_name, ''), sku_rows.product_name, '') AS product_name,
                   COALESCE(rules.product_type, '') AS product_type,
                   COALESCE(rules.commission_rate, 0) AS commission_rate,
                   COALESCE(rules.is_service_product, true) AS is_service_product,
                   sku_rows.order_count,
                   sku_rows.verified_coupon_count
            FROM sku_rows
            LEFT JOIN dim_sku_product_rules rules ON rules.sku_id = sku_rows.sku_id
            WHERE sku_rows.sku_id IN ({placeholders})
            """,
            params,
        )
        rows_by_sku = {
            cleaned["sku_id"]: cleaned
            for cleaned in (self._clean_sku_rule_row(row) for row in rows)
        }
        return {
            "rows": [rows_by_sku[sku_id] for sku_id in requested if sku_id in rows_by_sku],
            "missing_sku_ids": [sku_id for sku_id in requested if sku_id not in rows_by_sku],
            "duplicate_sku_ids": duplicate_sku_ids,
        }

    def upsert_sku_rules(self, rules: list[dict[str, Any]]) -> int:
        if self.session is None or DimSkuProductRule is None:
            return 0
        updated = 0
        for rule in rules:
            sku_id = _to_str(rule.get("sku_id")).strip()
            product_type = _to_str(rule.get("product_type")).strip()
            if not sku_id or not product_type:
                continue
            existing_name = self._sku_product_name(sku_id)
            self.session.merge(
                DimSkuProductRule(
                    sku_id=sku_id,
                    product_type=product_type,
                    product_name=existing_name,
                    commission_rate=Decimal(str(rule.get("commission_rate") or 0)),
                    is_service_product=_to_bool(rule.get("is_service_product")),
                )
            )
            updated += 1
        self.session.flush()
        return updated

    def list_non_commission_owner_accounts(
        self, *, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        where_sql = "" if include_inactive else "WHERE is_active = true"
        rows = self._execute(
            f"""
            SELECT owner_account_name, normalized_owner_account_name,
                   is_active, updated_at, updated_by
            FROM dim_non_commission_owner_accounts
            {where_sql}
            ORDER BY owner_account_name
            """
        )
        return [self._clean_non_commission_owner_account_row(row) for row in rows]

    def replace_non_commission_owner_accounts(
        self,
        accounts: list[str],
        *,
        updated_by: str,
    ) -> dict[str, Any]:
        if (
            self.session is None
            or DimNonCommissionOwnerAccount is None
            or normalize_owner_account_name is None
            or select is None
        ):
            return {"rows": [], "updated_count": 0}

        deduped: dict[str, str] = {}
        for account in accounts:
            account_name = _to_str(account).strip()
            normalized = normalize_owner_account_name(account_name)
            if not account_name or not normalized:
                continue
            deduped[normalized] = account_name

        now = generated_at()
        for normalized, account_name in deduped.items():
            self.session.merge(
                DimNonCommissionOwnerAccount(
                    normalized_owner_account_name=normalized,
                    owner_account_name=account_name,
                    is_active=True,
                    updated_by=updated_by,
                    updated_at=now,
                )
            )

        for row in self.session.scalars(select(DimNonCommissionOwnerAccount)).all():
            if row.normalized_owner_account_name not in deduped and row.is_active:
                row.is_active = False
                row.updated_by = updated_by
                row.updated_at = now

        self.session.flush()
        return {
            "rows": self.list_non_commission_owner_accounts(),
            "updated_count": len(deduped),
        }

    def commission_rules_summary(self) -> dict[str, Any]:
        sku_rows = self._execute(
            """
            SELECT sku_id, COALESCE(product_name, '') AS product_name, commission_rate
            FROM dim_sku_product_rules
            WHERE is_service_product = true
              AND commission_rate > 0
            ORDER BY sku_id
            """
        )
        return {
            "non_commission_owner_accounts": [
                row["owner_account_name"]
                for row in self.list_non_commission_owner_accounts()
            ],
            "commission_skus": [
                {
                    "sku_id": _to_str(row.get("sku_id")),
                    "product_name": _to_str(row.get("product_name")),
                    "commission_rate": _to_float(row.get("commission_rate")),
                }
                for row in sku_rows
            ],
        }

    def _sku_product_name(self, sku_id: str) -> str | None:
        rows = self._execute(
            """
            SELECT product_name
            FROM (
                SELECT product_name FROM raw_douyin_orders WHERE sku_id = :sku_id
                UNION ALL
                SELECT product_name FROM raw_douyin_verify_records WHERE sku_id = :sku_id
                UNION ALL
                SELECT product_name FROM dim_sku_product_rules WHERE sku_id = :sku_id
            ) names
            WHERE product_name IS NOT NULL AND product_name != ''
            LIMIT 1
            """,
            {"sku_id": sku_id},
        )
        return _to_str(rows[0].get("product_name")) if rows else None

    def latest_job(self) -> dict[str, Any] | None:
        rows = self.recent_jobs(1)
        return rows[0] if rows else None

    def recent_jobs(self, limit: int) -> list[dict[str, Any]]:
        rows = self._execute(
            """
            SELECT job_id, job_name, status, started_at, finished_at,
                   success_count, failed_count, error_message, metadata_json
            FROM job_runs
            ORDER BY started_at DESC, job_id DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        return [self._clean_job(row) for row in rows]

    def store_ranking(
        self, *, month: str, product_type: str, limit: int
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            """
            SELECT store_id, store_name, sales_order_count,
                   self_sold_self_verified_count,
                   self_sold_other_verified_count,
                   other_sold_self_verified_count,
                   self_verify_income_cent,
                   effective_commission_income_cent
            FROM agg_store_ranking
            WHERE month = :month AND product_type = :product_type
            ORDER BY sales_order_count DESC,
                     effective_commission_income_cent DESC,
                     store_id
            LIMIT :limit
            """,
            {"month": month, "product_type": product_type, "limit": limit},
        )
        return [self._clean_ranking_row(index + 1, row) for index, row in enumerate(rows)]

    def store_ranking_totals(self, *, month: str, product_type: str) -> dict[str, Any]:
        rows = self._execute(
            """
            SELECT COALESCE(SUM(sales_order_count), 0) AS sales_order_count,
                   COALESCE(SUM(self_verify_income_cent), 0) AS self_verify_income_cent,
                   COALESCE(SUM(effective_commission_income_cent), 0)
                       AS effective_commission_income_cent
            FROM agg_store_ranking
            WHERE month = :month AND product_type = :product_type
            """,
            {"month": month, "product_type": product_type},
        )
        row = rows[0] if rows else {}
        return {
            "sales_order_count": _to_int(row.get("sales_order_count")),
            "self_verify_income_cent": _to_int(row.get("self_verify_income_cent")),
            "effective_commission_income_cent": _to_int(
                row.get("effective_commission_income_cent")
            ),
        }

    def get_store(self, store_id: str) -> dict[str, Any]:
        rows = self._execute(
            """
            SELECT store_id, store_name
            FROM dim_stores
            WHERE store_id = :store_id
            LIMIT 1
            """,
            {"store_id": store_id},
        )
        if rows:
            return {
                "store_id": _to_str(rows[0].get("store_id")),
                "store_name": _to_str(rows[0].get("store_name")),
            }
        return {"store_id": store_id, "store_name": store_id}

    def monthly_settlement(
        self, *, store_id: str, month: str, product_type: str
    ) -> dict[str, Any]:
        summary = self._execute(
            """
            SELECT estimated_receivable_commission_cent,
                   commissionable_total_cent,
                   estimated_payable_commission_cent
            FROM agg_store_monthly_settlement
            WHERE store_id = :store_id
              AND month = :month
              AND product_type = :product_type
            LIMIT 1
            """,
            {"store_id": store_id, "month": month, "product_type": product_type},
        )
        metrics = (
            self._clean_metrics(summary[0])
            if summary
            else {
                "estimated_receivable_commission_cent": 0,
                "commissionable_total_cent": 0,
                "estimated_payable_commission_cent": 0,
            }
        )

        return {
            "store": self.get_store(store_id),
            "month": month,
            "product_type": product_type,
            "metrics": metrics,
            "tables": {
                "receivable_commissions": self._receivable_rows(
                    store_id, month, product_type
                ),
                "payable_commissions": self._payable_rows(
                    store_id, month, product_type
                ),
                "non_commission_orders": self._non_commission_rows(
                    store_id, month, product_type
                ),
            },
        }

    def order_details(self, filters: dict[str, Any]) -> dict[str, Any]:
        page = _to_int(filters.get("page"), 1)
        page_size = _to_int(filters.get("page_size"), 50)
        where_sql, params = self._detail_where(filters)
        total_rows = self._execute(
            f"SELECT COUNT(*) AS total FROM settlement_order_details {where_sql}",
            params,
        )
        total = _to_int(total_rows[0].get("total"), 0) if total_rows else 0
        offset = (page - 1) * page_size
        rows = self._execute(
            f"""
            SELECT settlement_order_details.order_id,
                   settlement_order_details.coupon_id,
                   COALESCE(
                       (
                           SELECT NULLIF(product_name, '')
                           FROM dim_sku_product_rules
                           WHERE sku_id = settlement_order_details.sku_id
                       ),
                       (
                           SELECT NULLIF(product_name, '')
                           FROM raw_douyin_orders
                           WHERE order_id = settlement_order_details.order_id
                       ),
                       (
                           SELECT NULLIF(product_name, '')
                           FROM raw_douyin_verify_records
                           WHERE verify_id = settlement_order_details.verify_id
                       ),
                       ''
                   ) AS product_name,
                   settlement_order_details.sku_id, owner_account_id,
                   owner_account_name, product_type, sale_store_id,
                   sale_store_name, sale_store.certified_subject_name AS sale_store_subject_name,
                   sale_time, is_verified, verify_store_id,
                   verify_store_name, verify_store.certified_subject_name AS verify_store_subject_name,
                   verify_time, relation_type,
                   is_commissionable, paid_amount_cent, commission_rate,
                   receivable_commission_cent, payable_commission_cent
            FROM settlement_order_details
            LEFT JOIN dim_stores sale_store ON sale_store.store_id = settlement_order_details.sale_store_id
            LEFT JOIN dim_stores verify_store ON verify_store.store_id = settlement_order_details.verify_store_id
            {where_sql}
            ORDER BY sale_time DESC, order_id, coupon_id
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": page_size, "offset": offset},
        )
        return {
            "rows": [self._clean_order_row(row) for row in rows],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": _total_pages(total, page_size),
            },
        }

    def clue_filters(self, scope_store_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
        round_scope_sql, round_scope_params = self._store_scope_clause(
            "assigned_store_id", scope_store_ids
        )
        order_scope_sql = self._order_scope_exists_clause(scope_store_ids)
        order_scope_params = self._order_scope_params(scope_store_ids)
        assigned_stores = [
            {
                "store_id": _to_str(row.get("store_id")),
                "store_name": _to_str(row.get("store_name")),
            }
            for row in self._execute(
                f"""
                SELECT DISTINCT assigned_store_id AS store_id,
                                assigned_store_name AS store_name
                FROM clue_assignment_rounds
                WHERE assigned_store_id IS NOT NULL
                  AND assigned_store_id != ''
                  {round_scope_sql}
                ORDER BY assigned_store_name, assigned_store_id
                """,
                round_scope_params,
            )
        ]
        assigned_cities = [
            _to_str(row.get("assigned_city"))
            for row in self._execute(
                f"""
                SELECT DISTINCT assigned_city
                FROM clue_center_orders
                WHERE assigned_city IS NOT NULL AND assigned_city != ''
                  {order_scope_sql}
                ORDER BY assigned_city
                """,
                order_scope_params,
            )
        ]
        product_types = [
            _to_str(row.get("product_type"))
            for row in self._execute(
                f"""
                SELECT DISTINCT product_type
                FROM clue_center_orders
                WHERE product_type IS NOT NULL AND product_type != ''
                  {order_scope_sql}
                ORDER BY product_type
                """,
                order_scope_params,
            )
        ]
        lead_statuses = [
            _to_str(row.get("lead_status"))
            for row in self._execute(
                f"""
                SELECT DISTINCT lead_status
                FROM clue_center_orders
                WHERE lead_status IS NOT NULL AND lead_status != ''
                  {order_scope_sql}
                ORDER BY lead_status
                """,
                order_scope_params,
            )
        ]
        round_statuses = [
            _to_str(row.get("round_status"))
            for row in self._execute(
                f"""
                SELECT DISTINCT round_status
                FROM clue_assignment_rounds
                WHERE round_status IS NOT NULL AND round_status != ''
                  {round_scope_sql}
                ORDER BY round_status
                """,
                round_scope_params,
            )
        ]
        return {
            "assigned_stores": assigned_stores,
            "assigned_cities": assigned_cities,
            "product_types": product_types,
            "lead_statuses": lead_statuses,
            "round_statuses": round_statuses,
        }

    def clue_overview(self, filters: dict[str, Any]) -> dict[str, Any]:
        where_sql, params = self._clue_where(filters, include_round=True)
        rows = self._execute(
            f"""
            SELECT COUNT(*) AS total_clues,
                   COALESCE(SUM(CASE
                       WHEN r.assignment_round_id = c.current_assignment_round_id
                         AND r.round_status IN ('active_unfollowed', 'active_followed')
                       THEN 1 ELSE 0 END), 0) AS active_clues,
                   COALESCE(SUM(CASE WHEN r.is_followed = true THEN 1 ELSE 0 END), 0)
                       AS followed_clues,
                   COALESCE(SUM(CASE WHEN r.is_follow_success = true THEN 1 ELSE 0 END), 0)
                       AS successful_follow_clues,
                   COALESCE(SUM(CASE
                       WHEN r.is_follow_success = true AND r.is_self_store_verified = true
                       THEN 1 ELSE 0 END), 0) AS self_store_verified_clues,
                   COALESCE(SUM(CASE
                       WHEN r.assignment_round_id = c.current_assignment_round_id
                         AND (c.lead_status = 'pending_reassign'
                         OR r.round_status IN (
                            'failed_pending_reassign',
                            'expired_pending_reassign'
                         ))
                       THEN 1 ELSE 0 END), 0) AS pending_reassign_count
            FROM clue_assignment_rounds r
            JOIN clue_center_orders c ON c.order_id = r.order_id
            {where_sql}
            """,
            params,
        )
        row = rows[0] if rows else {}
        total = _to_int(row.get("total_clues"))
        followed = _to_int(row.get("followed_clues"))
        successful = _to_int(row.get("successful_follow_clues"))
        self_verified = _to_int(row.get("self_store_verified_clues"))
        return {
            "total_clues": total,
            "active_clues": _to_int(row.get("active_clues")),
            "follow_rate": _ratio(followed, total),
            "follow_success_rate": _ratio(successful, total),
            "self_store_verify_rate": _ratio(self_verified, total),
            "pending_reassign_count": _to_int(row.get("pending_reassign_count")),
        }

    def clue_assignment_rounds(self, filters: dict[str, Any]) -> dict[str, Any]:
        page = max(1, _to_int(filters.get("page"), 1))
        page_size = max(1, min(_to_int(filters.get("page_size"), 20), 100))
        offset = (page - 1) * page_size
        where_sql, params = self._clue_where(filters, include_round=True)
        total_rows = self._execute(
            f"""
            SELECT COUNT(*) AS total
            FROM clue_assignment_rounds r
            JOIN clue_center_orders c ON c.order_id = r.order_id
            {where_sql}
            """,
            params,
        )
        total = _to_int(total_rows[0].get("total"), 0) if total_rows else 0
        rows = self._execute(
            f"""
            SELECT r.assignment_round_id,
                   r.order_id,
                   r.round_no,
                   c.lead_status,
                   c.current_assignment_round_id,
                   c.current_round_no,
                   c.current_round_status,
                   c.assigned_store_id AS current_assigned_store_id,
                   c.assigned_store_name AS current_assigned_store_name,
                   r.round_status,
                   r.assigned_at,
                   r.expires_at,
                   r.assigned_store_id,
                   r.assigned_store_name,
                   COALESCE(c.phone_masked, '') AS phone_masked,
                   c.product_type,
                   c.author_nickname,
                   r.followed_at,
                   r.follow_result,
                   r.reassign_reason,
                   r.reassigned_at,
                   r.verified_store_id,
                   r.verified_store_name,
                   r.verified_at,
                   r.is_self_store_verified
            FROM clue_assignment_rounds r
            JOIN clue_center_orders c ON c.order_id = r.order_id
            {where_sql}
            ORDER BY r.assigned_at DESC, r.assignment_round_id DESC
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": page_size, "offset": offset},
        )
        cleaned_rows = []
        phone_mask_cache: dict[str, str] = {}
        for row in rows:
            cleaned = self._clean_clue_round_row(row)
            if not cleaned["phone_masked"]:
                row_order_id = cleaned["order_id"]
                if row_order_id not in phone_mask_cache:
                    phone_mask_cache[row_order_id] = self._clue_order_masked_phone(row_order_id)
                cleaned["phone_masked"] = phone_mask_cache[row_order_id]
            cleaned_rows.append(cleaned)

        return {
            "rows": cleaned_rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": _total_pages(total, page_size),
            },
        }

    def clue_order_detail(
        self,
        order_id: str,
        scope_store_ids: tuple[str, ...] | None = None,
    ) -> dict[str, Any] | None:
        order_id = _to_str(order_id).strip()
        if not order_id:
            return None
        if not self._clue_order_allowed(order_id, scope_store_ids):
            return None
        orders = self._execute(
            """
            SELECT order_id,
                   canonical_clue_id,
                   lead_status,
                   COALESCE(phone_masked, '') AS phone_masked,
                   product_id,
                   product_name,
                   product_type,
                   author_nickname,
                   assigned_city,
                   assigned_province
            FROM clue_center_orders
            WHERE order_id = :order_id
            LIMIT 1
            """,
            {"order_id": order_id},
        )
        if not orders:
            return None

        rows = self._execute(
            """
            SELECT r.assignment_round_id,
                   r.order_id,
                   r.round_no,
                   c.lead_status,
                   c.current_assignment_round_id,
                   c.current_round_no,
                   c.current_round_status,
                   c.assigned_store_id AS current_assigned_store_id,
                   c.assigned_store_name AS current_assigned_store_name,
                   r.round_status,
                   r.assigned_at,
                   r.expires_at,
                   r.assigned_store_id,
                   r.assigned_store_name,
                   COALESCE(c.phone_masked, '') AS phone_masked,
                   c.product_type,
                   c.author_nickname,
                   r.followed_at,
                   r.follow_result,
                   r.reassign_reason,
                   r.reassigned_at,
                   r.verified_store_id,
                   r.verified_store_name,
                   r.verified_at,
                   r.is_self_store_verified
            FROM clue_assignment_rounds r
            JOIN clue_center_orders c ON c.order_id = r.order_id
            WHERE r.order_id = :order_id
            ORDER BY r.round_no, r.assigned_at, r.assignment_round_id
            """,
            {"order_id": order_id},
        )
        order = orders[0]
        phone_masked = _to_str(order.get("phone_masked")) or self._clue_order_masked_phone(order_id)
        cleaned_rounds = []
        for row in rows:
            cleaned = self._clean_clue_round_row(row)
            if not cleaned["phone_masked"]:
                cleaned["phone_masked"] = phone_masked
            cleaned_rounds.append(cleaned)

        return {
            "order_id": _to_str(order.get("order_id")),
            "canonical_clue_id": order.get("canonical_clue_id"),
            "lead_status": _to_str(order.get("lead_status")),
            "phone_masked": phone_masked,
            "product_id": order.get("product_id"),
            "product_name": order.get("product_name"),
            "product_type": order.get("product_type"),
            "author_nickname": order.get("author_nickname"),
            "assigned_city": order.get("assigned_city"),
            "assigned_province": order.get("assigned_province"),
            "rounds": cleaned_rounds,
        }

    def _raw_clue_phone(self, order_id: str) -> str:
        rows = self._execute(
            """
            SELECT telephone,
                   enc_telephone,
                   raw_payload
            FROM raw_douyin_clues
            WHERE order_id = :order_id
            ORDER BY create_time_detail, clue_row_key
            """,
            {"order_id": order_id},
        )
        for row in rows:
            phone = _phone_from_clue_payload(row)
            if phone:
                return phone
        return ""

    def _raw_clue_encrypted_phone(self, order_id: str) -> str:
        rows = self._execute(
            """
            SELECT telephone,
                   enc_telephone,
                   raw_payload
            FROM raw_douyin_clues
            WHERE order_id = :order_id
            ORDER BY create_time_detail, clue_row_key
            """,
            {"order_id": order_id},
        )
        for row in rows:
            cipher_text = _encrypted_phone_from_clue_payload(row)
            if cipher_text:
                return cipher_text
        return ""

    def _decrypted_raw_clue_phone(self, order_id: str) -> str:
        cipher_text = self._raw_clue_encrypted_phone(order_id)
        if not cipher_text or build_douyin_client_from_env is None:
            return ""
        try:
            client = build_douyin_client_from_env()
            decrypted = client.decrypt_cipher_texts([cipher_text]).get(cipher_text, "")
        except Exception:
            return ""
        return _normalized_phone(decrypted)

    def _clue_order_masked_phone(self, order_id: str) -> str:
        return _masked_phone(self._raw_clue_phone(order_id))

    def clue_order_phone(
        self,
        order_id: str,
        scope_store_ids: tuple[str, ...] | None = None,
    ) -> dict[str, Any] | None:
        order_id = _to_str(order_id).strip()
        if not order_id:
            return None
        if not self._clue_order_allowed(order_id, scope_store_ids):
            return None

        phone = self._raw_clue_phone(order_id) or self._decrypted_raw_clue_phone(order_id)
        if phone:
            return {
                "order_id": order_id,
                "phone": phone,
                "phone_masked": _masked_phone(phone),
            }
        return None

    def get_clue_reassign_rule(self) -> dict[str, Any]:
        if self.session is None or ClueReassignRuleSetting is None:
            return {
                "reassign_sla_hours": None,
                "updated_at": None,
                "updated_by": None,
            }
        setting = self.session.get(ClueReassignRuleSetting, "global")
        if setting is None:
            return {
                "reassign_sla_hours": None,
                "updated_at": None,
                "updated_by": None,
            }
        return {
            "reassign_sla_hours": setting.reassign_sla_hours,
            "updated_at": setting.updated_at,
            "updated_by": setting.updated_by,
        }

    def save_clue_reassign_rule(
        self, *, reassign_sla_hours: int | None, updated_by: str
    ) -> dict[str, Any]:
        if self.session is None or ClueReassignRuleSetting is None:
            return {
                "reassign_sla_hours": None,
                "updated_at": None,
                "updated_by": None,
            }
        setting = self.session.get(ClueReassignRuleSetting, "global")
        if setting is None:
            setting = ClueReassignRuleSetting(setting_key="global")
        setting.reassign_sla_hours = reassign_sla_hours
        setting.updated_by = updated_by
        setting.updated_at = generated_at()
        self.session.merge(setting)
        self.session.flush()
        return self.get_clue_reassign_rule()

    def order_details_export_csv(self, filters: dict[str, Any]) -> str:
        where_sql, params = self._detail_where(filters)
        rows = self._execute(
            f"""
            SELECT settlement_order_details.order_id,
                   settlement_order_details.coupon_id,
                   COALESCE(
                       (
                           SELECT NULLIF(product_name, '')
                           FROM dim_sku_product_rules
                           WHERE sku_id = settlement_order_details.sku_id
                       ),
                       (
                           SELECT NULLIF(product_name, '')
                           FROM raw_douyin_orders
                           WHERE order_id = settlement_order_details.order_id
                       ),
                       (
                           SELECT NULLIF(product_name, '')
                           FROM raw_douyin_verify_records
                           WHERE verify_id = settlement_order_details.verify_id
                       ),
                       ''
                   ) AS product_name,
                   settlement_order_details.sku_id, owner_account_id,
                   owner_account_name, product_type, sale_store_id,
                   sale_store_name, sale_store.certified_subject_name AS sale_store_subject_name,
                   sale_time, is_verified, verify_store_id,
                   verify_store_name, verify_store.certified_subject_name AS verify_store_subject_name,
                   verify_time, relation_type,
                   is_commissionable, paid_amount_cent, commission_rate,
                   receivable_commission_cent, payable_commission_cent
            FROM settlement_order_details
            LEFT JOIN dim_stores sale_store ON sale_store.store_id = settlement_order_details.sale_store_id
            LEFT JOIN dim_stores verify_store ON verify_store.store_id = settlement_order_details.verify_store_id
            {where_sql}
            ORDER BY sale_time DESC, order_id, coupon_id
            """,
            params,
        )
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "order_id",
                "coupon_id",
                "product_name",
                "sku_id",
                "owner_account_id",
                "owner_account_name",
                "product_type",
                "sale_store_id",
                "sale_store_name",
                "sale_store_subject_name",
                "sale_time",
                "is_verified",
                "verify_store_id",
                "verify_store_name",
                "verify_store_subject_name",
                "verify_time",
                "relation_type",
                "is_commissionable",
                "paid_amount_cent",
                "commission_rate",
                "receivable_commission_cent",
                "payable_commission_cent",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(self._clean_order_row(row))
        return output.getvalue()

    def export_filter_header(self, filters: dict[str, Any]) -> str:
        clean_filters = {
            key: value
            for key, value in filters.items()
            if value not in (None, "", "all") and key not in {"page", "page_size"}
        }
        return json.dumps(clean_filters, ensure_ascii=False, sort_keys=True)

    def _product_type_clause(
        self, product_type: str, params: dict[str, Any]
    ) -> str:
        if product_type and product_type != "all":
            params["product_type"] = product_type
            return " AND product_type = :product_type"
        return ""

    def _receivable_rows(
        self, store_id: str, month: str, product_type: str
    ) -> list[dict[str, Any]]:
        params = {"store_id": store_id, "month": month}
        product_clause = self._product_type_clause(product_type, params)
        month_expr = self._month_expr("verify_time")
        rows = self._execute(
            f"""
            SELECT product_type,
                   COUNT(*) AS verified_coupon_count,
                   COALESCE(SUM(paid_amount_cent), 0) AS paid_amount_cent,
                   COALESCE(AVG(commission_rate), 0) AS commission_rate,
                   COALESCE(SUM(paid_amount_cent), 0) AS commissionable_total_cent,
                   COALESCE(SUM(receivable_commission_cent), 0)
                       AS estimated_receivable_commission_cent
            FROM settlement_order_details
            WHERE sale_store_id = :store_id
              AND is_verified = true
              AND relation_type = 'cross_store'
              AND is_commissionable = true
              AND {month_expr} = :month
              {product_clause}
            GROUP BY product_type
            ORDER BY product_type
            """,
            params,
        )
        return [self._clean_receivable_row(row) for row in rows]

    def _payable_rows(
        self, store_id: str, month: str, product_type: str
    ) -> list[dict[str, Any]]:
        params = {"store_id": store_id, "month": month}
        product_clause = self._product_type_clause(product_type, params)
        month_expr = self._month_expr("verify_time")
        rows = self._execute(
            f"""
            SELECT product_type,
                   COUNT(*) AS verified_coupon_count,
                   COALESCE(SUM(paid_amount_cent), 0) AS paid_amount_cent,
                   COALESCE(AVG(commission_rate), 0) AS commission_rate,
                   COALESCE(SUM(payable_commission_cent), 0)
                       AS payable_commission_cent
            FROM settlement_order_details
            WHERE verify_store_id = :store_id
              AND is_verified = true
              AND relation_type = 'cross_store'
              AND is_commissionable = true
              AND {month_expr} = :month
              {product_clause}
            GROUP BY product_type
            ORDER BY product_type
            """,
            params,
        )
        return [self._clean_payable_row(row) for row in rows]

    def _non_commission_rows(
        self, store_id: str, month: str, product_type: str
    ) -> list[dict[str, Any]]:
        params = {"store_id": store_id, "month": month}
        product_clause = self._product_type_clause(product_type, params)
        month_expr = self._month_expr("verify_time")
        rows = self._execute(
            f"""
            SELECT product_type,
                   COUNT(*) AS verified_coupon_count,
                   COALESCE(SUM(paid_amount_cent), 0) AS paid_amount_cent
            FROM settlement_order_details
            WHERE sale_store_id = :store_id
              AND verify_store_id = :store_id
              AND is_verified = true
              AND relation_type = 'same_store'
              AND is_commissionable = false
              AND {month_expr} = :month
              {product_clause}
            GROUP BY product_type
            ORDER BY product_type
            """,
            params,
        )
        return [self._clean_non_commission_row(row) for row in rows]

    def _store_scope_clause(
        self,
        column: str,
        scope_store_ids: tuple[str, ...] | None,
        *,
        prefix: str = "scope_store",
    ) -> tuple[str, dict[str, Any]]:
        if scope_store_ids is None:
            return "", {}
        placeholders, params = _in_clause_params(prefix, scope_store_ids)
        if not placeholders:
            return " AND 1 = 0", {}
        return f" AND {column} IN ({placeholders})", params

    def _order_scope_params(
        self, scope_store_ids: tuple[str, ...] | None
    ) -> dict[str, Any]:
        if scope_store_ids is None:
            return {}
        _, params = _in_clause_params("order_scope_store", scope_store_ids)
        return params

    def _order_scope_exists_clause(
        self,
        scope_store_ids: tuple[str, ...] | None,
        *,
        order_ref: str = "clue_center_orders.order_id",
    ) -> str:
        if scope_store_ids is None:
            return ""
        placeholders, _params = _in_clause_params("order_scope_store", scope_store_ids)
        if not placeholders:
            return " AND 1 = 0"
        return (
            " AND EXISTS ("
            "SELECT 1 FROM clue_assignment_rounds scope_round "
            f"WHERE scope_round.order_id = {order_ref} "
            f"AND scope_round.assigned_store_id IN ({placeholders})"
            ")"
        )

    def _clue_order_allowed(
        self,
        order_id: str,
        scope_store_ids: tuple[str, ...] | None,
    ) -> bool:
        if scope_store_ids is None:
            return True
        placeholders, params = _in_clause_params("detail_scope_store", scope_store_ids)
        if not placeholders:
            return False
        rows = self._execute(
            f"""
            SELECT 1
            FROM clue_assignment_rounds
            WHERE order_id = :order_id
              AND assigned_store_id IN ({placeholders})
            LIMIT 1
            """,
            {"order_id": order_id, **params},
        )
        return bool(rows)

    def _detail_where(self, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}

        product_type = _to_str(filters.get("product_type"))
        if product_type and product_type != "all":
            clauses.append("product_type = :product_type")
            params["product_type"] = product_type

        for key in ("sale_store_id", "verify_store_id", "relation_type"):
            value = filters.get(key)
            if value:
                clauses.append(f"{key} = :{key}")
                params[key] = value

        for key in ("exclude_sale_store_id", "exclude_verify_store_id"):
            value = filters.get(key)
            if value:
                column = key.removeprefix("exclude_")
                clauses.append(f"({column} IS NULL OR {column} != :{key})")
                params[key] = value

        if filters.get("sale_month"):
            clauses.append(f"{self._month_expr('sale_time')} = :sale_month")
            params["sale_month"] = filters["sale_month"]

        if filters.get("verify_month"):
            clauses.append(
                f"verify_time IS NOT NULL AND {self._month_expr('verify_time')} = :verify_month"
            )
            params["verify_month"] = filters["verify_month"]

        for key in ("is_verified", "is_commissionable"):
            value = _optional_bool(filters.get(key))
            if value is not None:
                clauses.append(f"{key} = :{key}")
                params[key] = value

        query = _to_str(filters.get("q")).strip().lower()
        if query:
            clauses.append("(lower(order_id) LIKE :q OR lower(coupon_id) LIKE :q)")
            params["q"] = f"%{query}%"

        scope_store_ids = filters.get("scope_store_ids")
        if scope_store_ids is not None:
            placeholders, scope_params = _in_clause_params("detail_scope_store", scope_store_ids)
            if placeholders:
                clauses.append(
                    f"(sale_store_id IN ({placeholders}) OR verify_store_id IN ({placeholders}))"
                )
                params.update(scope_params)
            else:
                clauses.append("1 = 0")

        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(f"({clause})" for clause in clauses), params

    def _clue_where(
        self, filters: dict[str, Any], *, include_round: bool
    ) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}

        exact_filters = {
            "assigned_store_id": "r.assigned_store_id" if include_round else "c.assigned_store_id",
            "lead_status": "c.lead_status",
            "product_type": "c.product_type",
            "city": "c.assigned_city",
        }
        for key, column in exact_filters.items():
            value = _to_str(filters.get(key)).strip()
            if value and value != "all":
                clauses.append(f"{column} = :{key}")
                params[key] = value

        round_status = _to_str(filters.get("round_status")).strip()
        if round_status and round_status != "all":
            column = "r.round_status" if include_round else "c.current_round_status"
            clauses.append(f"{column} = :round_status")
            params["round_status"] = round_status

        assigned_start = _parse_filter_datetime(filters.get("assigned_date_start"))
        if assigned_start is not None:
            column = "r.assigned_at" if include_round else "c.assigned_at"
            clauses.append(f"{column} >= :assigned_date_start")
            params["assigned_date_start"] = assigned_start

        assigned_end = _parse_filter_datetime(filters.get("assigned_date_end"))
        if assigned_end is not None:
            column = "r.assigned_at" if include_round else "c.assigned_at"
            clauses.append(f"{column} < :assigned_date_end")
            params["assigned_date_end"] = assigned_end

        query = _to_str(filters.get("q")).strip().lower()
        if query:
            clauses.append(
                "(lower(c.order_id) LIKE :q OR lower(c.assigned_store_name) LIKE :q)"
            )
            params["q"] = f"%{query}%"

        scope_store_ids = filters.get("scope_store_ids")
        if scope_store_ids is not None:
            if include_round:
                placeholders, scope_params = _in_clause_params("clue_scope_store", scope_store_ids)
                if placeholders:
                    clauses.append(f"r.assigned_store_id IN ({placeholders})")
                    params.update(scope_params)
                else:
                    clauses.append("1 = 0")
            else:
                scope_sql = self._order_scope_exists_clause(scope_store_ids, order_ref="c.order_id")
                scope_sql = scope_sql.removeprefix(" AND ")
                if scope_sql:
                    clauses.append(scope_sql)
                    params.update(self._order_scope_params(scope_store_ids))

        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(f"({clause})" for clause in clauses), params

    def _clean_clue_round_row(self, row: dict[str, Any]) -> dict[str, Any]:
        expires_at = row.get("expires_at")
        assignment_round_id = _to_str(row.get("assignment_round_id"))
        current_assignment_round_id = _to_str(row.get("current_assignment_round_id"))
        is_current_round = bool(
            assignment_round_id
            and current_assignment_round_id
            and assignment_round_id == current_assignment_round_id
        )
        return {
            "assignment_round_id": assignment_round_id,
            "order_id": _to_str(row.get("order_id")),
            "round_no": _to_int(row.get("round_no"), 1),
            "lead_status": _to_str(row.get("lead_status")),
            "order_current_status": _to_str(row.get("lead_status")),
            "current_assignment_round_id": current_assignment_round_id or None,
            "current_round_no": _to_int(row.get("current_round_no"), 0),
            "current_round_status": _to_str(row.get("current_round_status")),
            "current_assigned_store_id": row.get("current_assigned_store_id"),
            "current_assigned_store_name": row.get("current_assigned_store_name"),
            "is_current_round": is_current_round,
            "round_effective_status": "active" if is_current_round else "inactive",
            "round_status": _to_str(row.get("round_status")),
            "assigned_at": row.get("assigned_at"),
            "expires_at": expires_at,
            "remaining_reassign_seconds": _remaining_reassign_seconds(expires_at),
            "assigned_store_id": row.get("assigned_store_id"),
            "assigned_store_name": row.get("assigned_store_name"),
            "phone_masked": _to_str(row.get("phone_masked")),
            "product_type": row.get("product_type"),
            "author_nickname": row.get("author_nickname"),
            "followed_at": row.get("followed_at"),
            "follow_result": _to_str(row.get("follow_result"), "pending"),
            "reassign_reason": row.get("reassign_reason"),
            "reassigned_at": row.get("reassigned_at"),
            "verified_store_id": row.get("verified_store_id"),
            "verified_store_name": row.get("verified_store_name"),
            "verified_at": row.get("verified_at"),
            "is_self_store_verified": _to_bool(row.get("is_self_store_verified")),
        }

    def _clean_job(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata_json") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        return {
            "job_id": _to_str(row.get("job_id")),
            "job_name": _to_str(row.get("job_name")),
            "status": _to_str(row.get("status"), "failed"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "success_count": _to_int(row.get("success_count")),
            "failed_count": _to_int(row.get("failed_count")),
            "error_message": sanitize_error_message(row.get("error_message")),
            "metadata_json": metadata if isinstance(metadata, dict) else {},
        }

    def _clean_sku_rule_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "sku_id": _to_str(row.get("sku_id")),
            "product_name": _to_str(row.get("product_name")),
            "product_type": _to_str(row.get("product_type")),
            "commission_rate": _to_float(row.get("commission_rate")),
            "is_service_product": _to_bool(row.get("is_service_product")),
            "order_count": _to_int(row.get("order_count")),
            "verified_coupon_count": _to_int(row.get("verified_coupon_count")),
        }

    def _clean_non_commission_owner_account_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "owner_account_name": _to_str(row.get("owner_account_name")),
            "normalized_owner_account_name": _to_str(row.get("normalized_owner_account_name")),
            "is_active": _to_bool(row.get("is_active")),
            "updated_at": row.get("updated_at"),
            "updated_by": row.get("updated_by"),
        }

    def _clean_ranking_row(self, rank: int, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "rank": rank,
            "store_id": _to_str(row.get("store_id")),
            "store_name": _to_str(row.get("store_name")),
            "sales_order_count": _to_int(row.get("sales_order_count")),
            "self_sold_self_verified_count": _to_int(
                row.get("self_sold_self_verified_count")
            ),
            "self_sold_other_verified_count": _to_int(
                row.get("self_sold_other_verified_count")
            ),
            "other_sold_self_verified_count": _to_int(
                row.get("other_sold_self_verified_count")
            ),
            "self_verify_income_cent": _to_int(row.get("self_verify_income_cent")),
            "effective_commission_income_cent": _to_int(
                row.get("effective_commission_income_cent")
            ),
        }

    def _clean_metrics(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "estimated_receivable_commission_cent": _to_int(
                row.get("estimated_receivable_commission_cent")
            ),
            "commissionable_total_cent": _to_int(
                row.get("commissionable_total_cent")
            ),
            "estimated_payable_commission_cent": _to_int(
                row.get("estimated_payable_commission_cent")
            ),
        }

    def _clean_receivable_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "product_type": _to_str(row.get("product_type")),
            "verified_coupon_count": _to_int(row.get("verified_coupon_count")),
            "paid_amount_cent": _to_int(row.get("paid_amount_cent")),
            "commission_rate": _to_float(row.get("commission_rate")),
            "commissionable_total_cent": _to_int(
                row.get("commissionable_total_cent")
            ),
            "estimated_receivable_commission_cent": _to_int(
                row.get("estimated_receivable_commission_cent")
            ),
        }

    def _clean_payable_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "product_type": _to_str(row.get("product_type")),
            "verified_coupon_count": _to_int(row.get("verified_coupon_count")),
            "paid_amount_cent": _to_int(row.get("paid_amount_cent")),
            "commission_rate": _to_float(row.get("commission_rate")),
            "payable_commission_cent": _to_int(row.get("payable_commission_cent")),
        }

    def _clean_non_commission_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "product_type": _to_str(row.get("product_type")),
            "verified_coupon_count": _to_int(row.get("verified_coupon_count")),
            "paid_amount_cent": _to_int(row.get("paid_amount_cent")),
        }

    def _clean_order_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_id": _to_str(row.get("order_id")),
            "coupon_id": _to_str(row.get("coupon_id")),
            "product_name": _to_str(row.get("product_name")),
            "sku_id": _to_str(row.get("sku_id")),
            "owner_account_id": _to_str(row.get("owner_account_id")),
            "owner_account_name": _to_str(row.get("owner_account_name")),
            "product_type": _to_str(row.get("product_type")),
            "sale_store_id": _to_str(row.get("sale_store_id")),
            "sale_store_name": _to_str(row.get("sale_store_name")),
            "sale_store_subject_name": _to_str(row.get("sale_store_subject_name")),
            "sale_time": row.get("sale_time"),
            "is_verified": _to_bool(row.get("is_verified")),
            "verify_store_id": _to_str(row.get("verify_store_id")),
            "verify_store_name": _to_str(row.get("verify_store_name")),
            "verify_store_subject_name": _to_str(row.get("verify_store_subject_name")),
            "verify_time": row.get("verify_time"),
            "relation_type": _to_str(row.get("relation_type")),
            "is_commissionable": _optional_bool(row.get("is_commissionable")),
            "paid_amount_cent": _to_int(row.get("paid_amount_cent")),
            "commission_rate": _to_float(row.get("commission_rate")),
            "receivable_commission_cent": _to_int(
                row.get("receivable_commission_cent")
            ),
            "payable_commission_cent": _to_int(row.get("payable_commission_cent")),
        }
