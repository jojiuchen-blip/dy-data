from __future__ import annotations

from typing import Any

import pytest

from dy_api.cli_audit import CliAuditUnavailable, DatabaseCliAuditSink


def audit_event() -> dict[str, Any]:
    return {
        "event": "cli_request",
        "operation": "stores_list",
        "request_id": "req_" + "a" * 32,
        "user_id": "user-1",
        "auth_type": "user",
        "cli_version": "0.1.0",
        "command": "stores.list",
        "schema_version": "1.0",
        "date_range": None,
        "requested_store_ids": [],
        "effective_store_ids": ["store-1"],
        "returned_store_count": 1,
        "result": 200,
        "error_code": None,
        "duration_ms": 1.25,
    }


class FakeSession:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.added: list[Any] = []
        self.flushed = False
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def add(self, value: Any) -> None:
        if self.fail_at == "add":
            raise RuntimeError("add failed")
        self.added.append(value)

    def flush(self) -> None:
        if self.fail_at == "flush":
            raise RuntimeError("flush failed")
        self.flushed = True

    def commit(self) -> None:
        if self.fail_at == "commit":
            raise RuntimeError("commit failed")
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_database_audit_sink_confirms_flush_and_commit() -> None:
    session = FakeSession()
    sink = DatabaseCliAuditSink(session_factory=lambda: session)

    sink.record(audit_event())

    assert len(session.added) == 1
    record = session.added[0]
    assert record.command == "stores.list"
    assert record.request_id == "req_" + "a" * 32
    assert record.effective_store_ids == ["store-1"]
    assert session.flushed is True
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


@pytest.mark.parametrize("fail_at", ["add", "flush", "commit"])
def test_database_audit_sink_rolls_back_and_reports_write_failures(
    fail_at: str,
) -> None:
    session = FakeSession(fail_at=fail_at)
    sink = DatabaseCliAuditSink(session_factory=lambda: session)

    with pytest.raises(CliAuditUnavailable):
        sink.record(audit_event())

    assert session.rolled_back is True
    assert session.closed is True


def test_database_audit_sink_rejects_missing_session_factory() -> None:
    sink = DatabaseCliAuditSink(session_factory=lambda: None)

    with pytest.raises(CliAuditUnavailable):
        sink.record(audit_event())
