from __future__ import annotations

from zoneinfo import ZoneInfo


CLI_VERSION = "0.1.0"
CLI_SCHEMA_VERSION = "1.0"
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
ERROR_CONTRACTS = {
    "INVALID_ARGUMENT": {
        "exit_code": 2,
        "retryable": False,
        "message": "The request arguments are invalid.",
    },
    "AUTH_REQUIRED": {
        "exit_code": 3,
        "retryable": False,
        "message": "CLI authentication is required.",
    },
    "AUTH_EXPIRED": {
        "exit_code": 3,
        "retryable": False,
        "message": "CLI authentication is invalid or expired.",
    },
    "SCOPE_DENIED": {
        "exit_code": 4,
        "retryable": False,
        "message": "The requested scope is not permitted.",
    },
    "API_UNAVAILABLE": {
        "exit_code": 5,
        "retryable": True,
        "message": "The dydata API is unavailable.",
    },
    "RATE_LIMITED": {
        "exit_code": 5,
        "retryable": True,
        "message": "The dydata API rate limit was reached.",
    },
    "SCHEMA_MISMATCH": {
        "exit_code": 6,
        "retryable": False,
        "message": "The dydata API schema is incompatible.",
    },
    "INTERNAL_ERROR": {
        "exit_code": 6,
        "retryable": False,
        "message": "The request could not be completed.",
    },
}
ERROR_EXIT_CODES = {
    code: int(contract["exit_code"]) for code, contract in ERROR_CONTRACTS.items()
}
