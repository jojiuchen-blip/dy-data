"""Stable stdout renderers for machine and aggregate-table output."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from .constants import CLI_SCHEMA_VERSION, ERROR_EXIT_CODES
from .errors import error_retryable, safe_request_id
from .environments import TEST_ENVIRONMENT


def emit_json(payload: Mapping[str, Any], *, stream: TextIO | None = None) -> None:
    """Write exactly one deterministic JSON document to stdout."""
    target = stream or sys.stdout
    document = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    target.write(f"{document}\n")


def error_envelope(
    command: str,
    code: str,
    message: str,
    *,
    retryable: bool | None = None,
    request_id: str | None = None,
    environment: str = TEST_ENVIRONMENT.name,
) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "environment": environment,
        "schema_version": CLI_SCHEMA_VERSION,
        "error": {
            "code": code,
            "message": message,
            "retryable": error_retryable(code, retryable),
            "request_id": safe_request_id(request_id),
        },
    }


def emit_error(
    command: str,
    code: str,
    message: str,
    *,
    retryable: bool | None = None,
    request_id: str | None = None,
    environment: str = TEST_ENVIRONMENT.name,
    stream: TextIO | None = None,
) -> int:
    emit_json(
        error_envelope(
            command,
            code,
            message,
            retryable=retryable,
            request_id=request_id,
            environment=environment,
        ),
        stream=stream,
    )
    return ERROR_EXIT_CODES.get(code, ERROR_EXIT_CODES["INTERNAL_ERROR"])


_AGGREGATE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Store", "store_name"),
    ("Total", "total_count"),
    ("Pending", "pending_count"),
    ("Followed", "followed_count"),
    ("Other", "other_status_count"),
    ("System follow-up rate", "system_follow_up_rate"),
    ("Action follow-up rate", "action_follow_up_rate"),
)


def _rate(value: Any) -> str:
    return f"{float(value or 0):.1%}"


def render_aggregate_table(rows: Sequence[Mapping[str, Any]]) -> str:
    """Render only the approved aggregate fields for follow-up summaries."""
    header = " | ".join(label for label, _ in _AGGREGATE_COLUMNS)
    rendered_rows = [header]
    for row in rows:
        action_rate = row.get("action_follow_up_rate", row.get("action_follow_rate", 0))
        values = (
            str(row.get("store_name", "")),
            str(row.get("total_count", 0)),
            str(row.get("pending_count", 0)),
            str(row.get("followed_count", 0)),
            str(row.get("other_status_count", 0)),
            _rate(row.get("system_follow_up_rate")),
            _rate(action_rate),
        )
        rendered_rows.append(" | ".join(values))
    return "\n".join(rendered_rows)
