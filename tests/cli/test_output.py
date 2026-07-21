from __future__ import annotations

import io
import json

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
        stream=stream,
    )

    assert exit_code == 2
    assert json.loads(stream.getvalue()) == {
        "command": "clues.follow-up-stats",
        "error": {"code": "INVALID_ARGUMENT", "message": "Date range is invalid"},
        "ok": False,
        "schema_version": "1.0",
    }


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
