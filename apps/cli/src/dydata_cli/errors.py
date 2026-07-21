"""Safe correlation and retry metadata for stable CLI errors."""

from __future__ import annotations

import re
from uuid import uuid4


RETRYABLE_ERROR_CODES = {"API_UNAVAILABLE", "RATE_LIMITED"}
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def safe_request_id(value: str | None = None) -> str:
    """Preserve a bounded safe ID or create a fresh local correlation ID."""
    if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return f"req_{uuid4().hex}"


def error_retryable(code: str, value: bool | None = None) -> bool:
    """Use explicit trusted metadata, otherwise derive it from the stable code."""
    if isinstance(value, bool):
        return value
    return code in RETRYABLE_ERROR_CODES
