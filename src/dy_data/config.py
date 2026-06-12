from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .sku import DEFAULT_SKU_TYPE_MAP


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE_ROOT = REPO_ROOT
DEFAULT_SCRIPT_ROOT = REPO_ROOT
DEFAULT_BROWSER_DOWNLOADS = REPO_ROOT / "runs" / "browser_downloads"


DEFAULT_CONFIG: dict[str, Any] = {
    "paths": {
        "workspace_root": str(DEFAULT_WORKSPACE_ROOT),
        "script_root": str(DEFAULT_SCRIPT_ROOT),
        "python_exe": "python",
        "browser_downloads": str(DEFAULT_BROWSER_DOWNLOADS),
    },
    "douyin": {
        "app_id": "",
        "app_secret": "",
        "account_id": "",
        "poi_ids": [],
        "poi_name_map": {},
        "page_size": 100,
        "request_sleep_seconds": 0.5,
    },
    "sku": {"type_map": DEFAULT_SKU_TYPE_MAP},
    "settlement": {
        "commission_rate": 0.1,
        "excluded_owner_names": ["比亚迪汽车销售有限公司"],
        "today": "",
    },
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _candidate_config_paths() -> list[Path]:
    explicit = os.getenv("DY_DATA_CONFIG", "").strip()
    if explicit:
        return [Path(explicit)]
    return [REPO_ROOT / "config.local.json", REPO_ROOT / "config.json"]


def load_config() -> dict[str, Any]:
    for path in _candidate_config_paths():
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                return _deep_merge(DEFAULT_CONFIG, json.load(file))
    return deepcopy(DEFAULT_CONFIG)


CONFIG = load_config()


def config_value(*keys: str, default: Any = None) -> Any:
    value: Any = CONFIG
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def env_or_config(env_name: str, *keys: str, default: Any = None) -> Any:
    value = os.getenv(env_name)
    if value not in (None, ""):
        return value
    return config_value(*keys, default=default)


def as_bool(value: Any, default: bool = False) -> bool:
    if value in ("", None):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_path(value: Any) -> Path:
    text = os.path.expandvars(str(value)).strip()
    path = Path(text).expanduser()
    if not path.is_absolute():
        return REPO_ROOT / path
    return path


def workspace_root() -> Path:
    return _clean_path(config_value("paths", "workspace_root", default=str(DEFAULT_WORKSPACE_ROOT)))


def script_root() -> Path:
    return _clean_path(config_value("paths", "script_root", default=str(DEFAULT_SCRIPT_ROOT)))


def browser_downloads() -> Path:
    return _clean_path(config_value("paths", "browser_downloads", default=str(DEFAULT_BROWSER_DOWNLOADS)))


def path_value(name: str, env_name: str | None = None, default: Any = None) -> Path:
    if env_name:
        env_value = os.getenv(env_name)
        if env_value:
            return _clean_path(env_value)

    explicit = config_value("paths", name)
    if explicit not in (None, ""):
        return _clean_path(explicit)

    base = workspace_root()
    field_probe = base / "field_probe"
    settlement = base / "settlement"
    derived: dict[str, Path] = {
        "python_exe": base / "runtime" / "python" / "python.exe",
        "base_table": base / "data" / "看板基础表.csv",
        "raw_order_save_dir": base / "output",
        "verify_save_dir": base / "exports" / "verify",
        "refund_save_dir": base / "exports" / "refund",
        "refund_order_save_dir": script_root() / "output_refund",
        "supplement_run_dir": base / "supplement",
        "supplement_seed_table": base / "runs" / "20260602_103004" / "抖音订单_2025年05月到2026年05月_总表_含券状态.csv",
        "field_probe_dir": field_probe,
        "craftsman_table": field_probe / "职人绑定信息列表_测试.csv",
        "backend_aweme_csv": field_probe / "来客后台抖音号明细_XML解析.csv",
        "backend_aweme_xlsx": browser_downloads() / "抖音号明细-2026-06-09.xlsx",
        "settlement_dir": settlement,
        "verify_records_dir": settlement / "verify_records_180d_days",
        "verify_by_selected_pois_test_dir": settlement / "verify_by_selected_pois_test",
        "recent_matched_sales_pois": settlement / "recent_matched_sales_pois.json",
        "may_verify_dir": settlement / "may2026_verify_by_poi",
        "may_settlement_dashboard_dir": settlement / "may2026_settlement_dashboard",
        "tmp_xlsx_sheet_xml": base / "tmp_xlsx_inspect" / "xl" / "worksheets" / "sheet1.xml",
    }
    value = derived.get(name, default)
    if value in (None, ""):
        raise KeyError(f"Unknown configured path: {name}")
    return _clean_path(value)


def sku_type_map() -> dict[str, str]:
    value = config_value("sku", "type_map", default=DEFAULT_SKU_TYPE_MAP)
    return {str(key): str(item) for key, item in dict(value).items()}


def product_types() -> list[str]:
    seen: list[str] = []
    for value in sku_type_map().values():
        if value and value not in seen:
            seen.append(value)
    return seen


def douyin_app_id() -> str | None:
    return env_or_config("DOUYIN_APP_ID", "douyin", "app_id", default=None)


def douyin_app_secret() -> str | None:
    return env_or_config("DOUYIN_APP_SECRET", "douyin", "app_secret", default=None)


def douyin_account_id(default: str | None = None) -> str | None:
    return env_or_config("DOUYIN_ACCOUNT_ID", "douyin", "account_id", default=default)


def douyin_poi_ids() -> list[str]:
    env_value = os.getenv("DOUYIN_POI_IDS", "").strip()
    if env_value:
        return [item.strip() for item in env_value.split(",") if item.strip()]
    value = config_value("douyin", "poi_ids", default=[])
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def douyin_poi_name_map() -> dict[str, str]:
    env_value = os.getenv("DOUYIN_POI_NAME_MAP", "").strip()
    if env_value:
        return json.loads(env_value)
    value = config_value("douyin", "poi_name_map", default={})
    return {str(key): str(item) for key, item in dict(value).items()}


def configured_today(default: datetime | None = None) -> datetime:
    value = env_or_config("SETTLEMENT_TODAY", "settlement", "today", default="")
    if value:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    return default or datetime.now()

