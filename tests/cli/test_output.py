from __future__ import annotations

import io
import json

from dydata_cli.constants import ERROR_EXIT_CODES
from dydata_cli.output import emit_error, emit_json, render_aggregate_table


def test_emit_json_writes_one_deterministic_unicode_document() -> None:
    stream = io.StringIO()

    emit_json({"z": 1, "name": "北京门店"}, stream=stream)

    assert stream.getvalue() == '{"name":"北京门店","z":1}\n'
    assert json.loads(stream.getvalue()) == {"name": "北京门店", "z": 1}


def test_emit_error_uses_a_stable_json_envelope() -> None:
    stream = io.StringIO()

    exit_code = emit_error(
        "clues.follow-up-stats",
        "INVALID_ARGUMENT",
        "Date range is invalid",
        retryable=False,
        request_id="req_" + "a" * 32,
        stream=stream,
    )

    assert exit_code == 2
    assert json.loads(stream.getvalue()) == {
        "command": "clues.follow-up-stats",
        "error": {
            "code": "INVALID_ARGUMENT",
            "message": "Date range is invalid",
            "retryable": False,
            "request_id": "req_" + "a" * 32,
        },
        "ok": False,
        "schema_version": "1.0",
    }


def test_error_exit_codes_match_the_public_contract() -> None:
    assert ERROR_EXIT_CODES == {
        "INVALID_ARGUMENT": 2,
        "AUTH_REQUIRED": 3,
        "AUTH_EXPIRED": 3,
        "SCOPE_DENIED": 4,
        "API_UNAVAILABLE": 5,
        "RATE_LIMITED": 5,
        "SCHEMA_MISMATCH": 6,
        "INTERNAL_ERROR": 6,
    }

    for code, expected_exit in ERROR_EXIT_CODES.items():
        assert emit_error("commands", code, "contract", stream=io.StringIO()) == expected_exit


def test_local_error_generates_a_safe_request_id_and_retryability() -> None:
    stream = io.StringIO()

    emit_error("stores.list", "API_UNAVAILABLE", "safe", stream=stream)

    error = json.loads(stream.getvalue())["error"]
    assert error["retryable"] is True
    assert error["request_id"].startswith("req_")
    assert len(error["request_id"]) == 36


def test_noncanonical_request_id_is_replaced_without_echoing_it() -> None:
    stream = io.StringIO()

    emit_error(
        "stores.list",
        "SCOPE_DENIED",
        "safe",
        request_id="refresh-token-like-secret",
        stream=stream,
    )

    output = stream.getvalue()
    error = json.loads(output)["error"]
    assert error["request_id"].startswith("req_")
    assert len(error["request_id"]) == 36
    assert set(error["request_id"][4:]) <= set("0123456789abcdef")
    assert "refresh-token-like-secret" not in output


def test_aggregate_table_has_only_the_approved_summary_columns() -> None:
    rendered = render_aggregate_table(
        [
            {
                "store_id": "store-a",
                "store_name": "北京门店",
                "total_count": 10,
                "pending_count": 2,
                "followed_count": 5,
                "other_status_count": 3,
                "system_follow_up_rate": 0.5,
                "action_follow_up_rate": 0.4,
            }
        ]
    )

    assert rendered.splitlines()[0].split(" | ") == [
        "Store",
        "Total",
        "Pending",
        "Followed",
        "Other",
        "System follow-up rate",
        "Action follow-up rate",
    ]
    assert "store-a" not in rendered
    assert "50.0%" in rendered
