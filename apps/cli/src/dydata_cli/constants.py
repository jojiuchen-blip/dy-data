from __future__ import annotations

from zoneinfo import ZoneInfo


CLI_VERSION = "0.1.0"
CLI_SCHEMA_VERSION = "1.0"
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
ERROR_EXIT_CODES = {
    "INTERNAL_ERROR": 1,
    "INVALID_ARGUMENT": 2,
    "NOT_IMPLEMENTED": 3,
}
