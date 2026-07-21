from __future__ import annotations

from zoneinfo import ZoneInfo


CLI_VERSION = "0.1.0"
CLI_SCHEMA_VERSION = "1.0"
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
ERROR_EXIT_CODES = {
    "INVALID_ARGUMENT": 2,
    "AUTH_REQUIRED": 3,
    "AUTH_EXPIRED": 3,
    "SCOPE_DENIED": 4,
    "API_UNAVAILABLE": 5,
    "RATE_LIMITED": 5,
    "SCHEMA_MISMATCH": 6,
    "INTERNAL_ERROR": 6,
}
