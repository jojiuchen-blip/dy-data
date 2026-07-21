"""Safe correlation and retry metadata for stable CLI errors."""

from __future__ import annotations

import re
from uuid import uuid4

from .constants import ERROR_CONTRACTS

RETRYABLE_ERROR_CODES = {
    code for code, contract in ERROR_CONTRACTS.items() if contract["retryable"]
}
_CANONICAL_REQUEST_ID = re.compile(r"^req_[0-9a-f]{32}$")


def is_canonical_request_id(value: object) -> bool:
    """Return whether a value has the one permitted local correlation-ID shape."""
    return isinstance(value, str) and _CANONICAL_REQUEST_ID.fullmatch(value) is not None


def safe_request_id(value: str | None = None) -> str:
    """Preserve a canonical ID or create a fresh local correlation ID."""
    if is_canonical_request_id(value):
        assert isinstance(value, str)
        return value
    return f"req_{uuid4().hex}"


def error_retryable(code: str, value: bool | None = None) -> bool:
    """Use explicit trusted metadata, otherwise derive it from the stable code."""
    if isinstance(value, bool):
        return value
    return code in RETRYABLE_ERROR_CODES


def error_message(code: str) -> str:
    """Return the sanitized message from the authoritative public error table."""
    contract = ERROR_CONTRACTS.get(code, ERROR_CONTRACTS["INTERNAL_ERROR"])
    return str(contract["message"])
