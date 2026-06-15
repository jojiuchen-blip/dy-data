from __future__ import annotations

import csv
import io
import json
import math
import os
import re
from collections.abc import Generator, Iterable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends

try:
    from sqlalchemy import text
except ImportError:  # pragma: no cover - covered only in stripped runtime images.
    text = None


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

    def list_stores(self) -> list[dict[str, Any]]:
        return [
            {
                "store_id": _to_str(row.get("store_id")),
                "store_name": _to_str(row.get("store_name")),
            }
            for row in self._execute(
                """
                SELECT store_id, store_name
                FROM dim_stores
                ORDER BY store_name, store_id
                """
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

    def latest_job(self) -> dict[str, Any] | None:
        rows = self.recent_jobs(1)
        return rows[0] if rows else None

    def recent_jobs(self, limit: int) -> list[dict[str, Any]]:
        rows = self._execute(
            """
            SELECT job_id, job_name, status, started_at, finished_at,
                   success_count, failed_count, error_message
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
            SELECT order_id, coupon_id, sku_id, owner_account_id,
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

    def order_details_export_csv(self, filters: dict[str, Any]) -> str:
        where_sql, params = self._detail_where(filters)
        rows = self._execute(
            f"""
            SELECT order_id, coupon_id, sku_id, owner_account_id,
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

        if not clauses:
            return "", params
        return "WHERE " + " AND ".join(f"({clause})" for clause in clauses), params

    def _clean_job(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": _to_str(row.get("job_id")),
            "job_name": _to_str(row.get("job_name")),
            "status": _to_str(row.get("status"), "failed"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "success_count": _to_int(row.get("success_count")),
            "failed_count": _to_int(row.get("failed_count")),
            "error_message": sanitize_error_message(row.get("error_message")),
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
