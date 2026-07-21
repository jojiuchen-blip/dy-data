from __future__ import annotations

import csv
import io
import json
import math
import os
import re
from collections.abc import Generator, Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
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
        ClueAssignmentRound,
        ClueFollowUpRecord,
        DimNonCommissionOwnerAccount,
        DimSkuProductRule,
        ProductTypeVisibilitySetting,
    )
    from apps.api.dy_api.rule_utils import normalize_owner_account_name
except ImportError:  # pragma: no cover - covered only in stripped runtime images.
    ClueAssignmentRound = None  # type: ignore[assignment]
    ClueFollowUpRecord = None  # type: ignore[assignment]
    DimNonCommissionOwnerAccount = None  # type: ignore[assignment]
    DimSkuProductRule = None  # type: ignore[assignment]
    ProductTypeVisibilitySetting = None  # type: ignore[assignment]
    normalize_owner_account_name = None  # type: ignore[assignment]

try:
    from apps.worker.pipeline import build_douyin_client_from_env
except ImportError:  # pragma: no cover - covered only in stripped runtime images.
    build_douyin_client_from_env = None  # type: ignore[assignment]

from apps.worker.clue_follow_up_state import (
    SELF_OWNED_EXECUTION_MODES,
    apply_follow_up_action,
    can_reveal_current_order_phone,
    soft_delete_follow_up_record,
)


SENSITIVE_ERROR_RE = re.compile(
    r"(?i)(cookie|token|secret|password|passwd|authorization|credential)"
)
FILE_PATH_RE = re.compile(
    r"(?:(?:[A-Za-z]:\\|/)(?:Users|home|root|var|tmp|opt|data|mnt)[^\s,;]*)"
)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_SESSION_FACTORY: Any | None = None
FOLLOW_UP_RESULTS = {
    "appointment",
    "further_follow_up",
    "lost",
    "unreachable",
    "request_store_change",
    "success",  # legacy history only
}
CURRENT_OPERABLE_ROUND_STATUSES = {"active_unfollowed", "active_followed"}
CLUE_VERIFICATION_STATUSES = [
    "unverified",
    "self_store_verified",
    "other_store_verified",
]
UTF8_BOM = "\ufeff"
SKU_PRODUCT_CATEGORIES_CSV = Path(__file__).resolve().parents[4] / "sku_product_categories.csv"
_SKU_PRODUCT_CATEGORY_ROWS_CACHE: list[dict[str, str]] | None = None
_SKU_PRODUCT_SCOPE_CACHE: dict[str, str] | None = None
_PRODUCT_SCOPE_TYPE_MAP_CACHE: dict[str, list[str]] | None = None


def _sku_product_category_rows() -> list[dict[str, str]]:
    global _SKU_PRODUCT_CATEGORY_ROWS_CACHE
    if _SKU_PRODUCT_CATEGORY_ROWS_CACHE is not None:
        return _SKU_PRODUCT_CATEGORY_ROWS_CACHE

    rows: list[dict[str, str]] = []
    try:
        with SKU_PRODUCT_CATEGORIES_CSV.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                sku_id = _to_str(row.get("SKU_ID") or row.get("sku_id")).strip()
                product_scope = _to_str(row.get("产品范围")).strip()
                product_type = _to_str(row.get("商品类型") or row.get("商品分类")).strip()
                if sku_id:
                    rows.append(
                        {
                            "sku_id": sku_id,
                            "product_scope": product_scope,
                            "product_type": product_type,
                        }
                    )
    except OSError:
        rows = []

    _SKU_PRODUCT_CATEGORY_ROWS_CACHE = rows
    return rows


def _sku_product_scope_map() -> dict[str, str]:
    global _SKU_PRODUCT_SCOPE_CACHE
    if _SKU_PRODUCT_SCOPE_CACHE is not None:
        return _SKU_PRODUCT_SCOPE_CACHE

    scopes = {
        row["sku_id"]: row["product_scope"]
        for row in _sku_product_category_rows()
        if row["sku_id"] and row["product_scope"]
    }

    _SKU_PRODUCT_SCOPE_CACHE = scopes
    return scopes


def _product_scope_type_map() -> dict[str, list[str]]:
    global _PRODUCT_SCOPE_TYPE_MAP_CACHE
    if _PRODUCT_SCOPE_TYPE_MAP_CACHE is not None:
        return _PRODUCT_SCOPE_TYPE_MAP_CACHE

    scope_types: dict[str, set[str]] = {}
    for row in _sku_product_category_rows():
        product_scope = row["product_scope"]
        product_type = row["product_type"]
        if not product_scope or not product_type:
            continue
        scope_types.setdefault(product_scope, set()).add(product_type)

    _PRODUCT_SCOPE_TYPE_MAP_CACHE = {
        product_scope: sorted(product_types)
        for product_scope, product_types in scope_types.items()
    }
    return _PRODUCT_SCOPE_TYPE_MAP_CACHE


def _product_scope_for_sku(sku_id: str) -> str:
    return _sku_product_scope_map().get(sku_id, "")


def _all_product_scopes() -> list[str]:
    return sorted(_product_scope_type_map())


ALL_MONTHS = "all"
ALL_STORES_OPTION = {"store_id": "", "store_name": "全部门店"}
MAX_SALES_CYCLE_SAMPLE_POINTS = 90


def generated_at() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def with_utf8_bom(csv_text: str) -> str:
    return csv_text if csv_text.startswith(UTF8_BOM) else f"{UTF8_BOM}{csv_text}"


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


def _follow_up_record_payload(record: Any) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "follow_up_record_id": record.follow_up_record_id,
        "order_id": record.order_id,
        "assignment_round_id": record.assignment_round_id,
        "round_no": record.round_no,
        "assigned_store_id": record.assigned_store_id,
        "follow_result": record.follow_result,
        "note": record.note,
        "operator_user_id": record.operator_user_id,
        "operator_username": record.operator_username,
        "created_at": record.created_at,
        "is_deleted": record.deleted_at is not None,
        "deleted_at": record.deleted_at,
    }


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


def _mask_or_masked_phone(value: Any) -> str:
    text_value = _to_str(value).strip()
    if re.fullmatch(r"\d{3}\*{4}\d{4}", text_value):
        return text_value
    return _masked_phone(text_value)


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


def _normalize_product_type_list(values: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        product_type = " ".join(_to_str(value).strip().split())
        if not product_type or product_type == "all" or product_type in seen:
            continue
        normalized.append(product_type)
        seen.add(product_type)
    return normalized


def _normalize_product_scope_list(values: Iterable[Any]) -> list[str]:
    return _normalize_product_type_list(values)


def _normalize_product_type_value(value: Any) -> str:
    product_type = " ".join(_to_str(value, "all").strip().split())
    return product_type or "all"


def _normalize_product_scope_value(value: Any) -> str:
    product_scope = " ".join(_to_str(value, "all").strip().split())
    return product_scope or "all"


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


def _parse_filter_date_end(value: Any) -> datetime | None:
    parsed = _parse_filter_datetime(value)
    if parsed is None:
        return None
    if isinstance(value, datetime):
        return parsed
    raw = _to_str(value).strip()
    if len(raw) == 10:
        return parsed + timedelta(days=1)
    return parsed


def _month_from_datetime(value: Any) -> str:
    parsed = _parse_filter_datetime(value)
    return parsed.strftime("%Y-%m") if parsed is not None else ""


def _matches_dashboard_month(value: Any, month: str) -> bool:
    return not month or month == ALL_MONTHS or _month_from_datetime(value) == month


def _order_identity(row: dict[str, Any]) -> str:
    return _to_str(row.get("order_id")) or _to_str(row.get("coupon_id"))


def _sales_store_matches(row_store_id: str, store_id: str | None) -> bool:
    return store_id is None or row_store_id == store_id


def _is_self_verified_for_store(row: dict[str, Any], store_id: str | None) -> bool:
    sale_store_id = _to_str(row.get("sale_store_id"))
    return (
        bool(row.get("is_verified"))
        and bool(sale_store_id)
        and sale_store_id == _to_str(row.get("verify_store_id"))
        and _sales_store_matches(sale_store_id, store_id)
    )


def _round_metric(value: float) -> float:
    return round(value, 2)


def _cycle_days(row: dict[str, Any]) -> float | None:
    sale_time = _parse_filter_datetime(row.get("sale_time"))
    verify_time = _parse_filter_datetime(row.get("verify_time"))
    if sale_time is None or verify_time is None:
        return None
    return max((verify_time - sale_time).total_seconds() / 86400, 0)


def _percentile(sorted_values: list[float], ratio: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _sample_sales_cycle_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(points) <= MAX_SALES_CYCLE_SAMPLE_POINTS:
        return points
    last_index = len(points) - 1
    return [
        points[round((index * last_index) / (MAX_SALES_CYCLE_SAMPLE_POINTS - 1))]
        for index in range(MAX_SALES_CYCLE_SAMPLE_POINTS)
    ]


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

    def _all_product_types(self) -> list[str]:
        product_types: set[str] = set()
        for sql in (
            "SELECT DISTINCT product_type FROM dim_sku_product_rules WHERE product_type IS NOT NULL",
            "SELECT DISTINCT product_type FROM settlement_order_details WHERE product_type IS NOT NULL",
            "SELECT DISTINCT product_type FROM clue_center_orders WHERE product_type IS NOT NULL",
        ):
            for row in self._execute(sql):
                product_type = _to_str(row.get("product_type")).strip()
                if product_type and product_type != "all":
                    product_types.add(product_type)
        return sorted(product_types)

    def _product_type_visibility_setting(self):
        if self.session is None or ProductTypeVisibilitySetting is None:
            return None
        return self.session.get(ProductTypeVisibilitySetting, "global")

    def _visible_product_types(self) -> tuple[str, ...] | None:
        setting = self._product_type_visibility_setting()
        if setting is None or not setting.enabled:
            return None
        values = setting.visible_product_types
        if isinstance(values, str):
            try:
                values = json.loads(values)
            except json.JSONDecodeError:
                values = []
        if not isinstance(values, list):
            values = []
        return tuple(_normalize_product_type_list(values))

    def _visible_product_type_clause(
        self,
        column: str,
        params: dict[str, Any],
        *,
        prefix: str = "visible_product_type",
    ) -> str:
        visible_product_types = self._visible_product_types()
        if visible_product_types is None:
            return ""
        placeholders, visible_params = _in_clause_params(prefix, visible_product_types)
        if not placeholders:
            return " AND 1 = 0"
        params.update(visible_params)
        return f" AND {column} IN ({placeholders})"

    def _is_product_type_visible(self, product_type: str) -> bool:
        visible_product_types = self._visible_product_types()
        if visible_product_types is None:
            return True
        product_type = _to_str(product_type).strip()
        if not product_type or product_type == "all":
            return True
        return product_type in set(visible_product_types)

    def list_product_types(self) -> list[str]:
        product_types = self._all_product_types()
        visible_product_types = self._visible_product_types()
        if visible_product_types is not None:
            allowed = set(visible_product_types)
            product_types = [product_type for product_type in product_types if product_type in allowed]
        return ["all", *product_types]

    def product_scope_type_map(self) -> dict[str, list[str]]:
        available_product_types = {
            product_type
            for product_type in self.list_product_types()
            if product_type != "all"
        }
        if not available_product_types:
            return {}
        return {
            product_scope: [
                product_type
                for product_type in product_types
                if product_type in available_product_types
            ]
            for product_scope, product_types in _product_scope_type_map().items()
            if any(product_type in available_product_types for product_type in product_types)
        }

    def list_product_scopes(self) -> list[str]:
        return ["all", *sorted(self.product_scope_type_map())]

    def _product_types_for_scope(self, product_scope: str) -> tuple[str, ...] | None:
        requested_product_scope = _normalize_product_scope_value(product_scope)
        if requested_product_scope == "all":
            return None
        return tuple(self.product_scope_type_map().get(requested_product_scope, []))

    def _product_type_filter_values(
        self, *, product_scope: str = "all", product_type: str = "all"
    ) -> tuple[str, ...] | None:
        requested_product_type = _normalize_product_type_value(product_type)
        scope_product_types = self._product_types_for_scope(product_scope)
        visible_product_types = self._visible_product_types()

        if requested_product_type != "all":
            if scope_product_types is not None and requested_product_type not in set(
                scope_product_types
            ):
                return ()
            if not self._is_product_type_visible(requested_product_type):
                return ()
            return (requested_product_type,)

        if scope_product_types is not None:
            if visible_product_types is None:
                return scope_product_types
            visible_set = set(visible_product_types)
            return tuple(
                product_type
                for product_type in scope_product_types
                if product_type in visible_set
            )

        return visible_product_types

    def _product_filter_condition(
        self,
        column: str,
        params: dict[str, Any],
        *,
        product_scope: str = "all",
        product_type: str = "all",
        prefix: str = "product_filter",
    ) -> str:
        values = self._product_type_filter_values(
            product_scope=product_scope, product_type=product_type
        )
        if values is None:
            return ""
        placeholders, product_params = _in_clause_params(prefix, values)
        if not placeholders:
            return "1 = 0"
        params.update(product_params)
        return f"{column} IN ({placeholders})"

    def default_product_type(self) -> str:
        setting = self._product_type_visibility_setting()
        default_product_type = _normalize_product_type_value(
            getattr(setting, "default_product_type", "all") if setting is not None else "all"
        )
        if default_product_type == "all":
            return "all"
        if not self._is_product_type_visible(default_product_type):
            return "all"
        return default_product_type

    def product_type_visibility(self) -> dict[str, Any]:
        setting = self._product_type_visibility_setting()
        visible_product_scopes: list[str] = []
        visible_product_types: list[str] = []
        default_product_type = "all"
        enabled = False
        updated_at = None
        updated_by = None
        if setting is not None:
            enabled = bool(setting.enabled)
            raw_scopes = getattr(setting, "visible_product_scopes", [])
            if isinstance(raw_scopes, str):
                try:
                    raw_scopes = json.loads(raw_scopes)
                except json.JSONDecodeError:
                    raw_scopes = []
            if not isinstance(raw_scopes, list):
                raw_scopes = []
            visible_product_scopes = _normalize_product_scope_list(raw_scopes)
            raw_values = setting.visible_product_types
            if isinstance(raw_values, str):
                try:
                    raw_values = json.loads(raw_values)
                except json.JSONDecodeError:
                    raw_values = []
            if not isinstance(raw_values, list):
                raw_values = []
            visible_product_types = _normalize_product_type_list(raw_values)
            default_product_type = _normalize_product_type_value(
                getattr(setting, "default_product_type", "all")
            )
            updated_at = setting.updated_at
            updated_by = setting.updated_by
        available = sorted(set(self._all_product_types()) | set(visible_product_types))
        available_set = set(available)
        product_scope_type_map = {
            product_scope: [
                product_type
                for product_type in product_types
                if product_type in available_set
            ]
            for product_scope, product_types in _product_scope_type_map().items()
        }
        product_scope_type_map = {
            product_scope: product_types
            for product_scope, product_types in product_scope_type_map.items()
            if product_types
        }
        available_product_scopes = sorted(
            set(product_scope_type_map) | set(visible_product_scopes)
        )
        for product_scope in visible_product_scopes:
            product_scope_type_map.setdefault(product_scope, [])
        if default_product_type != "all" and default_product_type not in available:
            default_product_type = "all"
        if (
            enabled
            and default_product_type != "all"
            and default_product_type not in set(visible_product_types)
        ):
            default_product_type = "all"
        return {
            "enabled": enabled,
            "visible_product_scopes": visible_product_scopes,
            "visible_product_types": visible_product_types,
            "default_product_type": default_product_type,
            "available_product_scopes": available_product_scopes,
            "available_product_types": available,
            "product_scope_type_map": product_scope_type_map,
            "updated_at": updated_at,
            "updated_by": updated_by,
        }

    def save_product_type_visibility(
        self,
        *,
        enabled: bool,
        visible_product_scopes: list[str],
        visible_product_types: list[str],
        default_product_type: str,
        updated_by: str,
    ) -> dict[str, Any]:
        if self.session is None or ProductTypeVisibilitySetting is None:
            return self.product_type_visibility()
        visible_product_scopes = _normalize_product_scope_list(visible_product_scopes)
        visible_product_types = _normalize_product_type_list(visible_product_types)
        default_product_type = _normalize_product_type_value(default_product_type)
        if (
            enabled
            and default_product_type != "all"
            and default_product_type not in set(visible_product_types)
        ):
            default_product_type = "all"
        now = generated_at()
        setting = self.session.get(ProductTypeVisibilitySetting, "global")
        if setting is None:
            setting = ProductTypeVisibilitySetting(
                setting_key="global",
                enabled=enabled,
                visible_product_scopes=visible_product_scopes,
                visible_product_types=visible_product_types,
                default_product_type=default_product_type,
                updated_by=updated_by,
                updated_at=now,
            )
            self.session.add(setting)
        else:
            setting.enabled = enabled
            setting.visible_product_scopes = visible_product_scopes
            setting.visible_product_types = visible_product_types
            setting.default_product_type = default_product_type
            setting.updated_by = updated_by
            setting.updated_at = now
        self.session.flush()
        return self.product_type_visibility()

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
        self,
        *,
        page: int,
        page_size: int,
        q: str | None = None,
        product_scope: str | None = None,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(page_size, 1000))
        offset = (page - 1) * page_size
        params: dict[str, Any] = {"limit": page_size, "offset": offset}
        count_clauses: list[str] = []
        row_clauses: list[str] = []
        query = _to_str(q).strip().lower()
        if query:
            count_clauses.append("lower(sku_id) LIKE :q OR lower(product_name) LIKE :q")
            row_clauses.append(
                "lower(sku_rows.sku_id) LIKE :q OR lower(sku_rows.product_name) LIKE :q"
            )
            params["q"] = f"%{query}%"
        product_scope_query = _to_str(product_scope).strip().lower()
        if product_scope_query:
            scope_sku_ids = [
                sku_id
                for sku_id, scope in _sku_product_scope_map().items()
                if product_scope_query in scope.lower()
            ]
            if not scope_sku_ids:
                return {
                    "rows": [],
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "total": 0,
                        "total_pages": 1,
                    },
                }
            placeholders: list[str] = []
            for index, sku_id in enumerate(scope_sku_ids):
                key = f"product_scope_sku_{index}"
                placeholders.append(f":{key}")
                params[key] = sku_id
            sku_scope_clause = f"sku_id IN ({', '.join(placeholders)})"
            count_clauses.append(sku_scope_clause)
            row_clauses.append(f"sku_rows.{sku_scope_clause}")

        count_where_sql = (
            "WHERE " + " AND ".join(f"({clause})" for clause in count_clauses)
            if count_clauses
            else ""
        )
        row_where_sql = (
            "WHERE " + " AND ".join(f"({clause})" for clause in row_clauses)
            if row_clauses
            else ""
        )

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
        self, *, month: str, product_type: str, limit: int, product_scope: str = "all"
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"month": month, "limit": limit}
        product_sql = self._product_filter_condition(
            "product_type",
            params,
            product_scope=product_scope,
            product_type=product_type,
            prefix="ranking_product",
        )
        if product_sql:
            rows = self._execute(
                f"""
                SELECT store_id,
                       COALESCE(MAX(NULLIF(store_name, '')), store_id) AS store_name,
                       COALESCE(SUM(sales_order_count), 0) AS sales_order_count,
                       COALESCE(SUM(self_sold_self_verified_count), 0)
                           AS self_sold_self_verified_count,
                       COALESCE(SUM(self_sold_other_verified_count), 0)
                           AS self_sold_other_verified_count,
                       COALESCE(SUM(other_sold_self_verified_count), 0)
                           AS other_sold_self_verified_count,
                       COALESCE(SUM(self_verify_income_cent), 0) AS self_verify_income_cent,
                       COALESCE(SUM(effective_commission_income_cent), 0)
                           AS effective_commission_income_cent
                FROM agg_store_ranking
                WHERE month = :month AND {product_sql}
                GROUP BY store_id
                ORDER BY sales_order_count DESC,
                         effective_commission_income_cent DESC,
                         store_id
                LIMIT :limit
                """,
                params,
            )
            return [self._clean_ranking_row(index + 1, row) for index, row in enumerate(rows)]

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
            {"month": month, "product_type": "all", "limit": limit},
        )
        return [self._clean_ranking_row(index + 1, row) for index, row in enumerate(rows)]

    def store_ranking_totals(
        self, *, month: str, product_type: str, product_scope: str = "all"
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"month": month}
        product_sql = self._product_filter_condition(
            "product_type",
            params,
            product_scope=product_scope,
            product_type=product_type,
            prefix="ranking_total_product",
        )
        if not product_sql:
            product_sql = "product_type = :product_type"
            params["product_type"] = "all"

        rows = self._execute(
            f"""
            SELECT COALESCE(SUM(sales_order_count), 0) AS sales_order_count,
                   COALESCE(SUM(self_verify_income_cent), 0) AS self_verify_income_cent,
                   COALESCE(SUM(effective_commission_income_cent), 0)
                       AS effective_commission_income_cent
            FROM agg_store_ranking
            WHERE month = :month AND {product_sql}
            """,
            params,
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
        self,
        *,
        store_id: str,
        month: str,
        product_type: str,
        product_scope: str = "all",
    ) -> dict[str, Any]:
        requested_product_type = _normalize_product_type_value(product_type)
        requested_product_scope = _normalize_product_scope_value(product_scope)
        summary_params: dict[str, Any] = {"store_id": store_id, "month": month}
        summary_product_sql = self._product_filter_condition(
            "product_type",
            summary_params,
            product_scope=requested_product_scope,
            product_type=requested_product_type,
            prefix="monthly_product",
        )
        if not summary_product_sql:
            summary_product_sql = "product_type = :product_type"
            summary_params["product_type"] = "all"

        summary = self._execute(
            f"""
            SELECT COALESCE(SUM(estimated_receivable_commission_cent), 0)
                       AS estimated_receivable_commission_cent,
                   COALESCE(SUM(commissionable_total_cent), 0)
                       AS commissionable_total_cent,
                   COALESCE(SUM(estimated_payable_commission_cent), 0)
                       AS estimated_payable_commission_cent
            FROM agg_store_monthly_settlement
            WHERE store_id = :store_id
              AND month = :month
              AND {summary_product_sql}
            """,
            summary_params,
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
            "product_scope": requested_product_scope,
            "product_type": requested_product_type,
            "metrics": metrics,
            "tables": {
                "receivable_commissions": self._receivable_rows(
                    store_id, month, requested_product_type, requested_product_scope
                ),
                "payable_commissions": self._payable_rows(
                    store_id, month, requested_product_type, requested_product_scope
                ),
                "non_commission_orders": self._non_commission_rows(
                    store_id, month, requested_product_type, requested_product_scope
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
                   is_commissionable, is_refund_excluded, paid_amount_cent, commission_rate,
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

    def sales_dashboard(
        self,
        *,
        store_id: str | None,
        month: str,
        product_type: str,
        product_scope: str = "all",
        trend_months: Iterable[str] = (),
    ) -> dict[str, Any]:
        scoped_store_id = _to_str(store_id).strip() or None
        requested_product_type = _normalize_product_type_value(product_type)
        requested_product_scope = _normalize_product_scope_value(product_scope)
        period = _to_str(month, ALL_MONTHS).strip() or ALL_MONTHS
        rows = self._sales_dashboard_source_rows(
            store_id=scoped_store_id,
            month=period,
            product_type=requested_product_type,
            product_scope=requested_product_scope,
        )
        cleaned_rows = [self._clean_sales_dashboard_row(row) for row in rows]
        ordered_trend_months = [
            value
            for value in dict.fromkeys(
                _to_str(value).strip()
                for value in trend_months
                if _to_str(value).strip() and _to_str(value).strip() != ALL_MONTHS
            )
        ]
        if period != ALL_MONTHS and period not in ordered_trend_months:
            ordered_trend_months.insert(0, period)
        if not ordered_trend_months:
            ordered_trend_months = self._sales_trend_months(
                cleaned_rows,
                store_id=scoped_store_id,
                product_type=requested_product_type,
            )

        return {
            "store": self.get_store(scoped_store_id) if scoped_store_id else ALL_STORES_OPTION,
            "month": period,
            "product_scope": requested_product_scope,
            "product_type": requested_product_type,
            "metrics": self._sales_dashboard_metrics(
                cleaned_rows,
                store_id=scoped_store_id,
                month=period,
                product_type=requested_product_type,
            ),
            "product_rows": self._sales_product_rows(
                cleaned_rows,
                store_id=scoped_store_id,
                month=period,
                product_type=requested_product_type,
            ),
            "trend_rows": self._sales_trend_rows(
                cleaned_rows,
                store_id=scoped_store_id,
                product_type=requested_product_type,
                months=ordered_trend_months,
            ),
            "cycle_rows": self._sales_cycle_rows(
                cleaned_rows,
                store_id=scoped_store_id,
                month=period,
                product_type=requested_product_type,
            ),
            "source_row_count": len(cleaned_rows),
        }

    def _sales_dashboard_source_rows(
        self,
        *,
        store_id: str | None,
        month: str,
        product_type: str,
        product_scope: str = "all",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        clauses = [
            "COALESCE(settlement_order_details.is_refund_excluded, false) = false",
        ]
        if store_id is not None:
            params["store_id"] = store_id
            clauses.append(
                "(settlement_order_details.sale_store_id = :store_id OR settlement_order_details.verify_store_id = :store_id)"
            )

        scope_product_types = self._product_types_for_scope(product_scope)
        if product_type != "all":
            if scope_product_types is not None and product_type not in set(scope_product_types):
                clauses.append("1 = 0")
            elif not self._is_product_type_visible(product_type):
                clauses.append("1 = 0")
            else:
                clauses.append("settlement_order_details.product_type = :product_type")
                params["product_type"] = product_type
        else:
            visible_product_types = self._visible_product_types()
            product_filter_values: tuple[str, ...] | None = None
            if scope_product_types is not None:
                if visible_product_types is not None:
                    visible_set = set(visible_product_types)
                    product_filter_values = tuple(
                        product_type
                        for product_type in scope_product_types
                        if product_type in visible_set
                    )
                else:
                    product_filter_values = scope_product_types
            elif visible_product_types is not None:
                product_filter_values = visible_product_types

            if product_filter_values is not None:
                placeholders, product_params = _in_clause_params(
                    "sales_visible_product", product_filter_values
                )
                if placeholders:
                    clauses.append(
                        f"settlement_order_details.product_type IN ({placeholders})"
                    )
                    params.update(product_params)
                else:
                    clauses.append("1 = 0")

        if month and month != ALL_MONTHS:
            sale_month_expr = self._month_expr("settlement_order_details.sale_time")
            verify_month_expr = self._month_expr("settlement_order_details.verify_time")
            if store_id is not None:
                clauses.append(
                    f"""
                    (
                        (settlement_order_details.sale_store_id = :store_id
                         AND settlement_order_details.sale_time IS NOT NULL
                         AND {sale_month_expr} = :sales_dashboard_month)
                        OR
                        (settlement_order_details.verify_store_id = :store_id
                         AND settlement_order_details.verify_time IS NOT NULL
                         AND {verify_month_expr} = :sales_dashboard_month)
                    )
                    """
                )
            else:
                clauses.append(
                    f"""
                    (
                        (settlement_order_details.sale_time IS NOT NULL
                         AND {sale_month_expr} = :sales_dashboard_month)
                        OR
                        (settlement_order_details.verify_time IS NOT NULL
                         AND {verify_month_expr} = :sales_dashboard_month)
                    )
                    """
                )
            params["sales_dashboard_month"] = month

        where_sql = "WHERE " + " AND ".join(f"({clause})" for clause in clauses)
        return self._execute(
            f"""
            SELECT order_id,
                   coupon_id,
                   product_type,
                   sale_store_id,
                   sale_time,
                   is_verified,
                   verify_store_id,
                   verify_time,
                   paid_amount_cent
            FROM settlement_order_details
            {where_sql}
            ORDER BY sale_time, order_id, coupon_id
            """,
            params,
        )

    def _clean_sales_dashboard_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_id": _to_str(row.get("order_id")),
            "coupon_id": _to_str(row.get("coupon_id")),
            "product_type": _to_str(row.get("product_type")),
            "sale_store_id": _to_str(row.get("sale_store_id")),
            "sale_time": row.get("sale_time"),
            "is_verified": _to_bool(row.get("is_verified")),
            "verify_store_id": _to_str(row.get("verify_store_id")),
            "verify_time": row.get("verify_time"),
            "paid_amount_cent": _to_int(row.get("paid_amount_cent")),
        }

    def _sales_dashboard_metrics(
        self,
        rows: list[dict[str, Any]],
        *,
        store_id: str | None,
        month: str,
        product_type: str,
    ) -> dict[str, Any]:
        sales_orders: set[str] = set()
        self_verify_orders: set[str] = set()
        verify_orders: set[str] = set()
        amount_rows: set[str] = set()
        cycle_days_by_order: dict[str, float] = {}
        actual_verify_amount_cent = 0

        for row in rows:
            if not self._sales_row_matches_product(row, product_type):
                continue
            order_id = _order_identity(row)
            if (
                _sales_store_matches(row["sale_store_id"], store_id)
                and _matches_dashboard_month(row["sale_time"], month)
            ):
                sales_orders.add(order_id)
                if _is_self_verified_for_store(row, store_id):
                    self_verify_orders.add(order_id)

            if (
                row["is_verified"]
                and _sales_store_matches(row["verify_store_id"], store_id)
                and _matches_dashboard_month(row["verify_time"], month)
            ):
                verify_orders.add(order_id)
                amount_key = _to_str(row.get("coupon_id")) or f"{order_id}:{row.get('verify_time')}"
                if amount_key not in amount_rows:
                    amount_rows.add(amount_key)
                    actual_verify_amount_cent += row["paid_amount_cent"]

                cycle_days = _cycle_days(row)
                if cycle_days is not None:
                    existing = cycle_days_by_order.get(order_id)
                    if existing is None or cycle_days < existing:
                        cycle_days_by_order[order_id] = cycle_days

        cycle_values = list(cycle_days_by_order.values())
        return {
            "total_sales_order_count": len(sales_orders),
            "self_verify_order_count": len(self_verify_orders),
            "self_verify_rate": _ratio(len(self_verify_orders), len(sales_orders)),
            "total_verify_order_count": len(verify_orders),
            "actual_verify_amount_cent": actual_verify_amount_cent,
            "avg_verify_cycle_days": (
                _round_metric(sum(cycle_values) / len(cycle_values))
                if cycle_values
                else None
            ),
        }

    def _sales_product_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        store_id: str | None,
        month: str,
        product_type: str,
    ) -> list[dict[str, Any]]:
        product_types: set[str] = set()
        for row in rows:
            if not self._sales_row_matches_product(row, product_type):
                continue
            in_sale_period = _sales_store_matches(
                row["sale_store_id"], store_id
            ) and _matches_dashboard_month(row["sale_time"], month)
            in_verify_period = (
                row["is_verified"]
                and _sales_store_matches(row["verify_store_id"], store_id)
                and _matches_dashboard_month(row["verify_time"], month)
            )
            if in_sale_period or in_verify_period:
                product_types.add(row["product_type"])

        return [
            {
                "product_type": item,
                **self._sales_dashboard_metrics(
                    rows, store_id=store_id, month=month, product_type=item
                ),
            }
            for item in sorted(product_types)
        ]

    def _sales_trend_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        store_id: str | None,
        product_type: str,
        months: list[str],
    ) -> list[dict[str, Any]]:
        trend_rows: list[dict[str, Any]] = []
        for month in months:
            orders: set[str] = set()
            verified_orders: set[str] = set()
            for row in rows:
                if (
                    not self._sales_row_matches_product(row, product_type)
                    or _month_from_datetime(row["sale_time"]) != month
                ):
                    continue
                order_id = _order_identity(row)
                if _sales_store_matches(row["sale_store_id"], store_id):
                    orders.add(order_id)
                if row["is_verified"] and _sales_store_matches(
                    row["verify_store_id"], store_id
                ):
                    verified_orders.add(order_id)
            trend_rows.append(
                {
                    "month": month,
                    "order_count": len(orders),
                    "verify_order_count": len(verified_orders),
                }
            )
        return trend_rows

    def _sales_cycle_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        store_id: str | None,
        month: str,
        product_type: str,
    ) -> list[dict[str, Any]]:
        best_by_order: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if (
                not self._sales_row_matches_product(row, product_type)
                or not row["is_verified"]
                or not _sales_store_matches(row["verify_store_id"], store_id)
                or not _matches_dashboard_month(row["verify_time"], month)
            ):
                continue
            cycle_days = _cycle_days(row)
            if cycle_days is None:
                continue
            product = row["product_type"] or "未映射"
            order_id = _order_identity(row)
            point = {
                "order_id": order_id,
                "cycle_days": _round_metric(cycle_days),
                "sale_time": row["sale_time"],
                "verify_time": row["verify_time"],
            }
            key = (product, order_id)
            existing = best_by_order.get(key)
            if existing is None or point["cycle_days"] < existing["cycle_days"]:
                best_by_order[key] = point

        by_product: dict[str, list[dict[str, Any]]] = {}
        for (product, _order_id), point in best_by_order.items():
            by_product.setdefault(product, []).append(point)

        cycle_rows: list[dict[str, Any]] = []
        for product, points in by_product.items():
            sorted_points = sorted(points, key=lambda item: (item["cycle_days"], item["order_id"]))
            values = [point["cycle_days"] for point in sorted_points]
            cycle_rows.append(
                {
                    "product_type": product,
                    "count": len(values),
                    "min_days": _round_metric(values[0]),
                    "q1_days": _round_metric(_percentile(values, 0.25) or values[0]),
                    "median_days": _round_metric(_percentile(values, 0.5) or values[0]),
                    "q3_days": _round_metric(_percentile(values, 0.75) or values[0]),
                    "max_days": _round_metric(values[-1]),
                    "avg_days": _round_metric(sum(values) / len(values)),
                    "sample_points": _sample_sales_cycle_points(sorted_points),
                }
            )

        return sorted(cycle_rows, key=lambda item: (-item["count"], item["product_type"]))

    def _sales_trend_months(
        self, rows: list[dict[str, Any]], *, store_id: str | None, product_type: str
    ) -> list[str]:
        months: set[str] = set()
        for row in rows:
            if not self._sales_row_matches_product(row, product_type):
                continue
            if _sales_store_matches(
                row["sale_store_id"], store_id
            ) or _sales_store_matches(row["verify_store_id"], store_id):
                month = _month_from_datetime(row["sale_time"])
                if month:
                    months.add(month)
        return sorted(months)

    def _sales_row_matches_product(self, row: dict[str, Any], product_type: str) -> bool:
        return product_type == "all" or row["product_type"] == product_type

    def clue_filters(self, scope_store_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
        round_scope_sql, round_scope_params = self._store_scope_clause(
            "r.assigned_store_id", scope_store_ids
        )
        order_scope_sql = self._order_scope_exists_clause(
            scope_store_ids, order_ref="c.order_id"
        )
        order_scope_params = self._order_scope_params(scope_store_ids)
        round_visibility_params: dict[str, Any] = {}
        round_visibility_sql = self._visible_product_type_clause(
            "c.product_type",
            round_visibility_params,
            prefix="clue_filter_round_product",
        )
        order_visibility_params: dict[str, Any] = {}
        order_visibility_sql = self._visible_product_type_clause(
            "c.product_type",
            order_visibility_params,
            prefix="clue_filter_order_product",
        )
        round_params = {**round_scope_params, **round_visibility_params}
        order_params = {**order_scope_params, **order_visibility_params}
        assigned_stores = [
            {
                "store_id": _to_str(row.get("store_id")),
                "store_name": _to_str(row.get("store_name")),
            }
            for row in self._execute(
                f"""
                SELECT DISTINCT r.assigned_store_id AS store_id,
                                r.assigned_store_name AS store_name
                FROM clue_assignment_rounds r
                JOIN clue_center_orders c ON c.order_id = r.order_id
                WHERE r.assigned_store_id IS NOT NULL
                  AND r.assigned_store_id != ''
                  {round_scope_sql}
                  {round_visibility_sql}
                ORDER BY r.assigned_store_name, r.assigned_store_id
                """,
                round_params,
            )
        ]
        assigned_cities = [
            _to_str(row.get("assigned_city"))
            for row in self._execute(
                f"""
                SELECT DISTINCT c.assigned_city
                FROM clue_center_orders c
                WHERE c.assigned_city IS NOT NULL AND c.assigned_city != ''
                  {order_scope_sql}
                  {order_visibility_sql}
                ORDER BY c.assigned_city
                """,
                order_params,
            )
        ]
        assigned_provinces = [
            _to_str(row.get("assigned_province"))
            for row in self._execute(
                f"""
                SELECT DISTINCT c.assigned_province
                FROM clue_center_orders c
                WHERE c.assigned_province IS NOT NULL AND c.assigned_province != ''
                  {order_scope_sql}
                  {order_visibility_sql}
                ORDER BY c.assigned_province
                """,
                order_params,
            )
        ]
        product_types = [
            _to_str(row.get("product_type"))
            for row in self._execute(
                f"""
                SELECT DISTINCT c.product_type
                FROM clue_center_orders c
                WHERE c.product_type IS NOT NULL AND c.product_type != ''
                  {order_scope_sql}
                  {order_visibility_sql}
                ORDER BY c.product_type
                """,
                order_params,
            )
        ]
        lead_statuses = [
            _to_str(row.get("lead_status"))
            for row in self._execute(
                f"""
                SELECT DISTINCT c.lead_status
                FROM clue_center_orders c
                WHERE c.lead_status IS NOT NULL AND c.lead_status != ''
                  {order_scope_sql}
                  {order_visibility_sql}
                ORDER BY c.lead_status
                """,
                order_params,
            )
        ]
        round_statuses = [
            _to_str(row.get("round_status"))
            for row in self._execute(
                f"""
                SELECT DISTINCT r.round_status
                FROM clue_assignment_rounds r
                JOIN clue_center_orders c ON c.order_id = r.order_id
                WHERE r.round_status IS NOT NULL AND r.round_status != ''
                  {round_scope_sql}
                  {round_visibility_sql}
                ORDER BY r.round_status
                """,
                round_params,
            )
        ]
        return {
            "assigned_stores": assigned_stores,
            "assigned_provinces": assigned_provinces,
            "assigned_cities": assigned_cities,
            "product_types": product_types,
            "default_product_type": self.default_product_type(),
            "lead_statuses": lead_statuses,
            "round_statuses": round_statuses,
            "verification_statuses": CLUE_VERIFICATION_STATUSES,
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
            "verified_count": self_verified,
            "self_store_verify_rate": _ratio(self_verified, total),
            "pending_reassign_count": _to_int(row.get("pending_reassign_count")),
        }

    def clue_store_follow_up_summary(
        self,
        *,
        store_ids: Sequence[str],
        assigned_date_start: str,
        assigned_date_end: str,
    ) -> list[dict[str, Any]]:
        """Return stable per-store assignment-round metrics for an inclusive Shanghai date range."""

        scoped_store_ids = tuple(store_ids)
        stores = self.list_stores(scoped_store_ids)
        if not stores:
            return []

        placeholders, params = _in_clause_params("store_scope", scoped_store_ids)
        if not placeholders:
            return []

        clauses = [f"r.assigned_store_id IN ({placeholders})"]
        assigned_start = _parse_filter_datetime(assigned_date_start)
        if assigned_start is not None:
            clauses.append("r.assigned_at >= :assigned_date_start")
            params["assigned_date_start"] = assigned_start
        assigned_end_exclusive = _parse_filter_date_end(assigned_date_end)
        if assigned_end_exclusive is not None:
            clauses.append("r.assigned_at < :assigned_date_end_exclusive")
            params["assigned_date_end_exclusive"] = assigned_end_exclusive

        display_status_sql = self._store_display_status_sql(include_round=True)
        rows = self._execute(
            f"""
            SELECT r.assigned_store_id,
                   COUNT(*) AS total_count,
                   COALESCE(SUM(CASE WHEN {display_status_sql} = '待跟进'
                       THEN 1 ELSE 0 END), 0) AS pending_count,
                   COALESCE(SUM(CASE WHEN {display_status_sql} = '已跟进'
                       THEN 1 ELSE 0 END), 0) AS followed_count,
                   COALESCE(SUM(CASE WHEN r.is_followed = true THEN 1 ELSE 0 END), 0)
                       AS action_followed_count,
                   COALESCE(SUM(CASE WHEN r.is_follow_success = true THEN 1 ELSE 0 END), 0)
                       AS effective_followed_count
            FROM clue_assignment_rounds r
            JOIN clue_center_orders c ON c.order_id = r.order_id
            WHERE {' AND '.join(clauses)}
            GROUP BY r.assigned_store_id
            """,
            params,
        )
        metrics_by_store = {
            _to_str(row.get("assigned_store_id")): row
            for row in rows
        }
        summary_rows = []
        for store in stores:
            metrics = metrics_by_store.get(store["store_id"], {})
            total = _to_int(metrics.get("total_count"))
            pending = _to_int(metrics.get("pending_count"))
            followed = _to_int(metrics.get("followed_count"))
            action_followed = _to_int(metrics.get("action_followed_count"))
            effective_followed = _to_int(metrics.get("effective_followed_count"))
            summary_rows.append(
                {
                    "store_id": store["store_id"],
                    "store_name": store["store_name"],
                    "total_count": total,
                    "pending_count": pending,
                    "followed_count": followed,
                    "other_status_count": total - pending - followed,
                    "action_followed_count": action_followed,
                    "effective_followed_count": effective_followed,
                    "system_follow_up_rate": _ratio(effective_followed, total),
                    "action_follow_rate": _ratio(action_followed, total),
                }
            )
        return summary_rows

    def clue_assignment_rounds(
        self,
        filters: dict[str, Any],
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
                    r.execution_mode,
                    r.lead_key,
                    lead.current_assignment_round_id AS master_current_assignment_round_id,
                    lead.lifecycle_status AS master_lifecycle_status,
                    lead.normalized_order_status AS master_normalized_order_status,
                    lead.pool_location AS master_pool_location,
                    EXISTS (
                        SELECT 1
                        FROM clue_master_leads headquarters_lead
                        WHERE headquarters_lead.order_id = r.order_id
                          AND headquarters_lead.lifecycle_status = 'active'
                          AND headquarters_lead.pool_location = 'headquarters_pool'
                    ) AS has_headquarters_lead,
                    r.round_status,
                   r.assigned_at,
                   r.expires_at,
                   r.first_sla_expires_at,
                   r.protection_started_at,
                   r.protection_expires_at,
                   r.auto_expiry_enabled,
                   r.first_follow_up_sla_hours,
                   r.protection_days,
                   r.assigned_store_id,
                   r.assigned_store_name,
                   COALESCE(c.phone_masked, '') AS phone_masked,
                   c.product_name,
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
             LEFT JOIN clue_master_leads lead ON lead.lead_key = r.lead_key
            {where_sql}
            ORDER BY r.assigned_at DESC, r.assignment_round_id DESC
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": page_size, "offset": offset},
        )
        cleaned_rows = []
        phone_mask_cache: dict[str, str] = {}
        for row in rows:
            cleaned = self._clean_clue_round_row(row, actor=actor)
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

    def clue_assignment_rounds_export_csv(
        self,
        filters: dict[str, Any],
        actor: dict[str, Any],
    ) -> str:
        where_sql, params = self._clue_where(filters, include_round=True)
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
                   r.execution_mode,
                   r.lead_key,
                   lead.current_assignment_round_id AS master_current_assignment_round_id,
                   lead.lifecycle_status AS master_lifecycle_status,
                   lead.normalized_order_status AS master_normalized_order_status,
                   lead.pool_location AS master_pool_location,
                   EXISTS (
                       SELECT 1
                       FROM clue_master_leads headquarters_lead
                       WHERE headquarters_lead.order_id = r.order_id
                         AND headquarters_lead.lifecycle_status = 'active'
                         AND headquarters_lead.pool_location = 'headquarters_pool'
                   ) AS has_headquarters_lead,
                   r.round_status,
                   r.assigned_at,
                   r.expires_at,
                   r.assigned_store_id,
                   r.assigned_store_name,
                   COALESCE(c.phone_plain, '') AS phone_plain,
                   COALESCE(c.phone_masked, '') AS phone_masked,
                   c.product_name,
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
             LEFT JOIN clue_master_leads lead ON lead.lead_key = r.lead_key
            {where_sql}
            ORDER BY r.assigned_at DESC, r.assignment_round_id DESC
            """,
            params,
        )
        fieldnames = [
            "assignment_round_id",
            "order_id",
            "round_no",
            "store_display_status",
            "lead_status",
            "round_status",
            "assigned_at",
            "expires_at",
            "assigned_store_id",
            "assigned_store_name",
            "phone_plain",
            "phone_masked",
            "product_name",
            "product_type",
            "author_nickname",
            "followed_at",
            "follow_result",
            "reassign_reason",
            "reassigned_at",
            "verified_store_id",
            "verified_store_name",
            "verified_at",
            "is_self_store_verified",
        ]
        buffer = io.StringIO()
        buffer.write("\ufeff")
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            cleaned = self._clean_clue_round_row(row, actor=actor)
            cleaned["phone_plain"] = (
                _to_str(row.get("phone_plain"))
                if self._actor_can_reveal_round_phone(row, actor)
                else ""
            )
            writer.writerow(cleaned)
        return buffer.getvalue()

    def clue_order_detail(
        self,
        order_id: str,
        scope_store_ids: tuple[str, ...] | None = None,
        actor: dict[str, Any] | None = None,
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
                   r.execution_mode,
                   r.lead_key,
                   lead.current_assignment_round_id AS master_current_assignment_round_id,
                   lead.lifecycle_status AS master_lifecycle_status,
                   lead.normalized_order_status AS master_normalized_order_status,
                   lead.pool_location AS master_pool_location,
                   EXISTS (
                       SELECT 1
                       FROM clue_master_leads headquarters_lead
                       WHERE headquarters_lead.order_id = r.order_id
                         AND headquarters_lead.lifecycle_status = 'active'
                         AND headquarters_lead.pool_location = 'headquarters_pool'
                   ) AS has_headquarters_lead,
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
             LEFT JOIN clue_master_leads lead ON lead.lead_key = r.lead_key
            WHERE r.order_id = :order_id
            ORDER BY r.round_no, r.assigned_at, r.assignment_round_id
            """,
            {"order_id": order_id},
        )
        record_rows = self._execute(
            """
            SELECT follow_up_record_id,
                   order_id,
                   assignment_round_id,
                   round_no,
                   assigned_store_id,
                   follow_result,
                   note,
                   operator_user_id,
                   operator_username,
                   created_at,
                   deleted_at,
                   deleted_by_user_id,
                   deleted_by_username,
                   deletion_reason
            FROM clue_follow_up_records
            WHERE order_id = :order_id
              AND (:include_deleted = true OR deleted_at IS NULL)
            ORDER BY created_at, follow_up_record_id
            """,
            {
                "order_id": order_id,
                "include_deleted": bool(actor and actor.get("is_highest_admin")),
            },
        )
        order = orders[0]
        phone_masked = _to_str(order.get("phone_masked")) or self._clue_order_masked_phone(order_id)
        cleaned_rounds = []
        for row in rows:
            cleaned = self._clean_clue_round_row(row, actor=actor)
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
            "follow_up_records": [
                self._clean_follow_up_record(row) for row in record_rows
            ],
        }

    def _clue_order_cached_phone(self, order_id: str) -> str:
        rows = self._execute(
            """
            SELECT phone_plain
            FROM clue_center_orders
            WHERE order_id = :order_id
            LIMIT 1
            """,
            {"order_id": order_id},
        )
        if not rows:
            return ""
        return _normalized_phone(rows[0].get("phone_plain"))

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

    def _decrypted_raw_clue_masked_phone(self, order_id: str) -> str:
        return _masked_phone(self._decrypted_raw_clue_phone(order_id))

    def _clue_order_masked_phone(self, order_id: str) -> str:
        cached = _masked_phone(self._clue_order_cached_phone(order_id))
        if cached:
            return cached
        masked = _masked_phone(self._raw_clue_phone(order_id))
        if masked:
            return masked
        return self._decrypted_raw_clue_masked_phone(order_id)

    def _current_operation_round(self, order_id: str) -> dict[str, Any] | None:
        rows = self._execute(
            """
            SELECT c.order_id,
                   c.lead_status,
                   c.current_assignment_round_id,
                   c.current_round_no,
                   c.current_round_status,
                   c.assigned_store_id AS current_assigned_store_id,
                   r.assignment_round_id,
                   r.round_no,
                   r.assigned_store_id,
                   r.round_status,
                   r.execution_mode,
                   r.lead_key,
                   lead.current_assignment_round_id AS master_current_assignment_round_id,
                   lead.lifecycle_status AS master_lifecycle_status,
                   lead.normalized_order_status AS master_normalized_order_status,
                   lead.pool_location AS master_pool_location,
                   EXISTS (
                       SELECT 1
                       FROM clue_master_leads headquarters_lead
                       WHERE headquarters_lead.order_id = r.order_id
                         AND headquarters_lead.lifecycle_status = 'active'
                         AND headquarters_lead.pool_location = 'headquarters_pool'
                   ) AS has_headquarters_lead
            FROM clue_center_orders c
            JOIN clue_assignment_rounds r
              ON r.order_id = c.order_id
             AND r.assignment_round_id = c.current_assignment_round_id
            LEFT JOIN clue_master_leads lead ON lead.lead_key = r.lead_key
            WHERE c.order_id = :order_id
            LIMIT 1
            """,
            {"order_id": order_id},
        )
        return rows[0] if rows else None

    def _is_current_effective_round(self, row: dict[str, Any]) -> bool:
        assignment_round_id = _to_str(row.get("assignment_round_id"))
        return bool(
            assignment_round_id
            and assignment_round_id == _to_str(row.get("current_assignment_round_id"))
            and _to_str(row.get("lead_status")) == "active"
            and _to_str(row.get("round_status")) in CURRENT_OPERABLE_ROUND_STATUSES
            and _to_str(row.get("current_round_status")) in CURRENT_OPERABLE_ROUND_STATUSES
        )

    def _actor_store_ids(self, actor: dict[str, Any]) -> set[str]:
        return {
            store_id
            for store_id in (_to_str(value).strip() for value in actor.get("store_ids") or ())
            if store_id
        }

    def _actor_can_operate_current_round(
        self,
        row: dict[str, Any],
        actor: dict[str, Any],
    ) -> bool:
        assignment_round_id = _to_str(row.get("assignment_round_id")).strip()
        if not assignment_round_id:
            return False
        if _to_str(row.get("execution_mode")) not in SELF_OWNED_EXECUTION_MODES:
            return False
        if assignment_round_id != _to_str(row.get("master_current_assignment_round_id")):
            return False
        if _to_str(row.get("master_lifecycle_status")) != "active":
            return False
        if _to_str(row.get("master_normalized_order_status")) != "active":
            return False
        if _to_str(row.get("master_pool_location")) != "store_follow_up_pool":
            return False
        if _to_str(row.get("round_status")) not in CURRENT_OPERABLE_ROUND_STATUSES:
            return False
        role = _to_str(actor.get("role"))
        if role == "admin":
            return True
        if role != "store":
            return False
        assigned_store_id = _to_str(
            row.get("current_assigned_store_id") or row.get("assigned_store_id")
        ).strip()
        return bool(assigned_store_id and assigned_store_id in self._actor_store_ids(actor))

    def save_clue_follow_up(
        self,
        order_id: str,
        payload: dict[str, Any],
        actor: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        order_id = _to_str(order_id).strip()
        assignment_round_id = _to_str(payload.get("assignment_round_id")).strip()
        follow_result = _to_str(payload.get("follow_result")).strip()
        note = _to_str(payload.get("note")).strip() or None
        if not order_id or not assignment_round_id:
            return "not_found", None
        if follow_result not in FOLLOW_UP_RESULTS:
            return "conflict", None
        if not self._clue_order_product_visible(order_id):
            return "not_found", None
        if _to_str(actor.get("role")) not in {"admin", "store"}:
            return "forbidden", None
        formal_round = self.session.get(ClueAssignmentRound, assignment_round_id) if ClueAssignmentRound is not None else None
        if formal_round is not None and formal_round.execution_mode in SELF_OWNED_EXECUTION_MODES:
            result = apply_follow_up_action(
                self.session,
                order_id=order_id,
                assignment_round_id=assignment_round_id,
                follow_result=follow_result,
                actor=actor,
                note=note,
                now=generated_at(),
            )
            return result.status, _follow_up_record_payload(result.record)
        # Legacy rounds remain visible for historical reconciliation, but cannot
        # run the M2 state machine without an authoritative master lead.
        return "conflict", None

    def delete_clue_follow_up_record(
        self,
        follow_up_record_id: str,
        actor: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        follow_up_record_id = _to_str(follow_up_record_id).strip()
        if not follow_up_record_id:
            return "not_found", None
        result = soft_delete_follow_up_record(
            self.session,
            follow_up_record_id=follow_up_record_id,
            actor=actor,
            reason="reversed_by_highest_admin",
            now=generated_at(),
        )
        return result.status, _follow_up_record_payload(result.record)

    def _actor_can_reveal_round_phone(
        self,
        row: dict[str, Any],
        actor: dict[str, Any],
    ) -> bool:
        if _to_bool(row.get("has_headquarters_lead")):
            return False
        if _to_str(row.get("execution_mode")) in SELF_OWNED_EXECUTION_MODES:
            return bool(
                self._actor_can_operate_current_round(row, actor)
                and _to_str(row.get("assignment_round_id"))
                == _to_str(row.get("current_assignment_round_id"))
            )
        if _to_str(row.get("lead_key")).strip():
            return False
        return bool(
            self._is_current_effective_round(row)
            and self._actor_can_legacy_current_round(row, actor)
        )

    def _actor_can_legacy_current_round(
        self,
        row: dict[str, Any],
        actor: dict[str, Any],
    ) -> bool:
        role = _to_str(actor.get("role"))
        if role == "admin":
            return True
        if role != "store":
            return False
        assigned_store_id = _to_str(
            row.get("current_assigned_store_id") or row.get("assigned_store_id")
        ).strip()
        return bool(assigned_store_id and assigned_store_id in self._actor_store_ids(actor))

    def clue_order_phone(
        self,
        order_id: str,
        actor: dict[str, Any],
    ) -> dict[str, Any] | None:
        order_id = _to_str(order_id).strip()
        if not order_id:
            return None
        if not self._clue_order_product_visible(order_id):
            return None
        row = self._current_operation_round(order_id)
        if row is None:
            return None
        if not self._actor_can_reveal_round_phone(row, actor):
            return None
        formal_round = self.session.get(ClueAssignmentRound, _to_str(row.get("assignment_round_id"))) if ClueAssignmentRound is not None else None
        if formal_round is not None and formal_round.execution_mode in SELF_OWNED_EXECUTION_MODES:
            if not can_reveal_current_order_phone(self.session, order_id=order_id, actor=actor):
                return None

        phone = (
            self._clue_order_cached_phone(order_id)
            or self._raw_clue_phone(order_id)
            or self._decrypted_raw_clue_phone(order_id)
        )
        if phone:
            return {
                "order_id": order_id,
                "phone": phone,
                "phone_masked": _masked_phone(phone),
            }
        return None

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
                   is_commissionable, is_refund_excluded, paid_amount_cent, commission_rate,
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
        output.write("\ufeff")
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
                "is_refund_excluded",
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
        return json.dumps(clean_filters, ensure_ascii=True, sort_keys=True)

    def _product_type_clause(
        self,
        product_type: str,
        params: dict[str, Any],
        product_scope: str = "all",
    ) -> str:
        product_sql = self._product_filter_condition(
            "product_type",
            params,
            product_scope=product_scope,
            product_type=product_type,
            prefix="monthly_table_product",
        )
        return f" AND {product_sql}" if product_sql else ""

    def _receivable_rows(
        self, store_id: str, month: str, product_type: str, product_scope: str = "all"
    ) -> list[dict[str, Any]]:
        params = {"store_id": store_id, "month": month}
        product_clause = self._product_type_clause(product_type, params, product_scope)
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
        self, store_id: str, month: str, product_type: str, product_scope: str = "all"
    ) -> list[dict[str, Any]]:
        params = {"store_id": store_id, "month": month}
        product_clause = self._product_type_clause(product_type, params, product_scope)
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
        self, store_id: str, month: str, product_type: str, product_scope: str = "all"
    ) -> list[dict[str, Any]]:
        params = {"store_id": store_id, "month": month}
        product_clause = self._product_type_clause(product_type, params, product_scope)
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
        if not self._clue_order_product_visible(order_id):
            return False
        if scope_store_ids is None:
            return True
        if self._clue_order_has_active_headquarters_lead(order_id):
            return False
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

    def _clue_order_has_active_headquarters_lead(self, order_id: str) -> bool:
        rows = self._execute(
            """
            SELECT 1
            FROM clue_master_leads headquarters_lead
            WHERE headquarters_lead.order_id = :order_id
              AND headquarters_lead.lifecycle_status = 'active'
              AND headquarters_lead.pool_location = 'headquarters_pool'
            LIMIT 1
            """,
            {"order_id": order_id},
        )
        return bool(rows)

    def _clue_order_product_visible(self, order_id: str) -> bool:
        visible_product_types = self._visible_product_types()
        if visible_product_types is None:
            return True
        rows = self._execute(
            """
            SELECT product_type
            FROM clue_center_orders
            WHERE order_id = :order_id
            LIMIT 1
            """,
            {"order_id": order_id},
        )
        if not rows:
            return False
        product_type = _to_str(rows[0].get("product_type")).strip()
        return product_type in set(visible_product_types)

    def _detail_where(self, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}

        product_sql = self._product_filter_condition(
            "settlement_order_details.product_type",
            params,
            product_scope=_to_str(filters.get("product_scope"), "all"),
            product_type=_to_str(filters.get("product_type"), "all"),
            prefix="detail_product",
        )
        if product_sql:
            clauses.append(product_sql)

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
            "province": "c.assigned_province",
            "city": "c.assigned_city",
        }
        for key, column in exact_filters.items():
            value = _to_str(filters.get(key)).strip()
            if value and value != "all":
                clauses.append(f"{column} = :{key}")
                params[key] = value
        visible_product_types = self._visible_product_types()
        if visible_product_types is not None:
            placeholders, visible_params = _in_clause_params(
                "clue_visible_product", visible_product_types
            )
            if placeholders:
                clauses.append(f"c.product_type IN ({placeholders})")
                params.update(visible_params)
            else:
                clauses.append("1 = 0")

        store_display_status = _to_str(filters.get("store_display_status")).strip()
        if store_display_status and store_display_status != "all":
            clauses.append(
                f"{self._store_display_status_sql(include_round=include_round)} "
                "= :store_display_status"
            )
            params["store_display_status"] = store_display_status

        round_status = _to_str(filters.get("round_status")).strip()
        if round_status and round_status != "all":
            column = "r.round_status" if include_round else "c.current_round_status"
            clauses.append(f"{column} = :round_status")
            params["round_status"] = round_status

        verification_status = _to_str(filters.get("verification_status")).strip()
        if verification_status and verification_status != "all":
            verified_at_column = "r.verified_at" if include_round else "c.verified_at"
            self_verified_column = (
                "r.is_self_store_verified" if include_round else "c.is_self_store_verified"
            )
            if verification_status == "unverified":
                clauses.append(f"{verified_at_column} IS NULL")
            elif verification_status == "self_store_verified":
                clauses.append(
                    f"{verified_at_column} IS NOT NULL "
                    f"AND {self_verified_column} = true"
                )
            elif verification_status == "other_store_verified":
                clauses.append(
                    f"{verified_at_column} IS NOT NULL "
                    f"AND {self_verified_column} = false"
                )

        assigned_start = _parse_filter_datetime(filters.get("assigned_date_start"))
        if assigned_start is not None:
            column = "r.assigned_at" if include_round else "c.assigned_at"
            clauses.append(f"{column} >= :assigned_date_start")
            params["assigned_date_start"] = assigned_start

        assigned_end = _parse_filter_date_end(filters.get("assigned_date_end"))
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
            order_ref = "r.order_id" if include_round else "c.order_id"
            clauses.append(
                "NOT EXISTS ("
                "SELECT 1 FROM clue_master_leads headquarters_lead "
                f"WHERE headquarters_lead.order_id = {order_ref} "
                "AND headquarters_lead.lifecycle_status = 'active' "
                "AND headquarters_lead.pool_location = 'headquarters_pool'"
                ")"
            )
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

    def _clean_clue_round_row(
        self,
        row: dict[str, Any],
        *,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            "store_display_status": self._store_display_status(row),
            "current_assignment_round_id": current_assignment_round_id or None,
            "current_round_no": _to_int(row.get("current_round_no"), 0),
            "current_round_status": _to_str(row.get("current_round_status")),
            "current_assigned_store_id": row.get("current_assigned_store_id"),
            "current_assigned_store_name": row.get("current_assigned_store_name"),
            "is_current_round": is_current_round,
            "can_operate_current_round": bool(
                actor and self._actor_can_operate_current_round(row, actor)
            ),
            "round_effective_status": "active" if is_current_round else "inactive",
            "round_status": _to_str(row.get("round_status")),
            "assigned_at": row.get("assigned_at"),
            "expires_at": expires_at,
            "first_sla_expires_at": row.get("first_sla_expires_at"),
            "protection_started_at": row.get("protection_started_at"),
            "protection_expires_at": row.get("protection_expires_at"),
            "auto_expiry_enabled": row.get("auto_expiry_enabled"),
            "first_follow_up_sla_hours": row.get("first_follow_up_sla_hours"),
            "protection_days": row.get("protection_days"),
            "remaining_reassign_seconds": _remaining_reassign_seconds(expires_at),
            "assigned_store_id": row.get("assigned_store_id"),
            "assigned_store_name": row.get("assigned_store_name"),
            "phone_masked": _to_str(row.get("phone_masked")),
            "product_name": row.get("product_name"),
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

    def _store_display_status(self, row: dict[str, Any]) -> str:
        lead_status = _to_str(row.get("lead_status"))
        round_status = _to_str(row.get("round_status"))
        follow_result = _to_str(row.get("follow_result"), "pending")
        if lead_status == "converted":
            return "已核销"
        if lead_status == "refunded":
            return "已退款"
        if round_status == "expired_pending_reassign":
            return "超期失效"
        if follow_result == "request_store_change":
            return "客户要求换门店"
        if round_status == "failed_pending_reassign" or follow_result in {"lost", "failed"}:
            return "主动战败"
        if lead_status == "active" and round_status == "active_followed":
            return "已跟进"
        if lead_status == "active" and round_status == "active_unfollowed":
            return "待跟进"
        return "不可跟进"

    def _store_display_status_sql(self, *, include_round: bool) -> str:
        round_status_column = "r.round_status" if include_round else "c.current_round_status"
        follow_result_column = "r.follow_result" if include_round else "c.follow_result"
        return f"""
            CASE
                WHEN c.lead_status = 'converted' THEN '已核销'
                WHEN c.lead_status = 'refunded' THEN '已退款'
                WHEN {round_status_column} = 'expired_pending_reassign' THEN '超期失效'
                WHEN COALESCE({follow_result_column}, 'pending') = 'request_store_change'
                THEN '客户要求换门店'
                WHEN {round_status_column} = 'failed_pending_reassign'
                  OR COALESCE({follow_result_column}, 'pending') IN ('lost', 'failed')
                THEN '主动战败'
                WHEN c.lead_status = 'active'
                  AND {round_status_column} = 'active_followed'
                THEN '已跟进'
                WHEN c.lead_status = 'active'
                  AND {round_status_column} = 'active_unfollowed'
                THEN '待跟进'
                ELSE '不可跟进'
            END
        """

    def _clean_follow_up_record(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "follow_up_record_id": _to_str(row.get("follow_up_record_id")),
            "order_id": _to_str(row.get("order_id")),
            "assignment_round_id": _to_str(row.get("assignment_round_id")),
            "round_no": _to_int(row.get("round_no"), 1),
            "assigned_store_id": row.get("assigned_store_id"),
            "follow_result": _to_str(row.get("follow_result")),
            "note": row.get("note"),
            "operator_user_id": row.get("operator_user_id"),
            "operator_username": row.get("operator_username"),
            "created_at": row.get("created_at"),
            "is_deleted": row.get("deleted_at") is not None,
            "deleted_at": row.get("deleted_at"),
            "deleted_by_user_id": row.get("deleted_by_user_id"),
            "deleted_by_username": row.get("deleted_by_username"),
            "deletion_reason": row.get("deletion_reason"),
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
        sku_id = _to_str(row.get("sku_id"))
        return {
            "sku_id": sku_id,
            "product_name": _to_str(row.get("product_name")),
            "product_scope": _product_scope_for_sku(sku_id),
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
            "is_refund_excluded": _to_bool(row.get("is_refund_excluded")),
            "paid_amount_cent": _to_int(row.get("paid_amount_cent")),
            "commission_rate": _to_float(row.get("commission_rate")),
            "receivable_commission_cent": _to_int(
                row.get("receivable_commission_cent")
            ),
            "payable_commission_cent": _to_int(row.get("payable_commission_cent")),
        }
