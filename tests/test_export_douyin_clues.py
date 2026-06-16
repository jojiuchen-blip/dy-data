from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.exports.export_douyin_clues import export_clues, sanitize_text


class FakeClueClient:
    def __init__(self, payloads: list[dict[str, Any] | Exception]):
        self.payloads = payloads
        self.calls: list[dict[str, Any]] = []

    def query_clues(self, start: datetime, end: datetime, *, page: int, page_size: int) -> dict[str, Any]:
        self.calls.append({"start": start, "end": end, "page": page, "page_size": page_size})
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_export_writes_clue_data_as_jsonl(tmp_path: Path):
    client = FakeClueClient(
        [
            {
                "data": {
                    "clue_data": [
                        {
                            "clue_id": "clue-1",
                            "create_time_detail": "2026-06-01 00:15:00",
                            "telephone": "13800000000",
                        }
                    ]
                }
            }
        ]
    )

    summary = export_clues(
        client=client,
        start=datetime(2026, 6, 1, 0, 0, 0),
        end=datetime(2026, 6, 1, 1, 0, 0),
        out_dir=tmp_path,
        window_hours=1,
        page_size=100,
    )

    jsonl_path = tmp_path / "clues_20260601000000_20260601010000.jsonl"
    rows = read_jsonl(jsonl_path)
    assert summary["total_rows"] == 1
    assert rows == [
        {
            "source_window_start": "2026-06-01 00:00:00",
            "source_window_end": "2026-06-01 01:00:00",
            "fetched_at": rows[0]["fetched_at"],
            "raw_payload": {
                "clue_id": "clue-1",
                "create_time_detail": "2026-06-01 00:15:00",
                "telephone": "13800000000",
            },
        }
    ]
    assert (tmp_path / "summary.json").exists()


def test_export_merges_multiple_pages(tmp_path: Path):
    client = FakeClueClient(
        [
            {"data": {"clue_data": [{"clue_id": "c1"}, {"clue_id": "c2"}]}},
            {"data": {"clue_data": [{"clue_id": "c3"}]}},
        ]
    )

    summary = export_clues(
        client=client,
        start=datetime(2026, 6, 1),
        end=datetime(2026, 6, 1, 1),
        out_dir=tmp_path,
        window_hours=1,
        page_size=2,
    )

    assert summary["total_rows"] == 3
    assert summary["pages_fetched"] == 2
    assert [call["page"] for call in client.calls] == [1, 2]
    assert len(read_jsonl(tmp_path / "clues_20260601000000_20260601010000.jsonl")) == 3


def test_empty_window_writes_summary(tmp_path: Path):
    client = FakeClueClient([{"data": {"clue_data": []}}])

    summary = export_clues(
        client=client,
        start=datetime(2026, 6, 1),
        end=datetime(2026, 6, 1, 1),
        out_dir=tmp_path,
        window_hours=1,
        page_size=100,
    )

    assert summary["total_rows"] == 0
    assert summary["windows"][0]["rows"] == 0
    assert summary["failed_windows"] == []
    assert read_jsonl(tmp_path / "clues_20260601000000_20260601010000.jsonl") == []


def test_missing_clue_id_is_preserved_and_counted(tmp_path: Path):
    client = FakeClueClient(
        [
            {
                "data": {
                    "clue_data": [
                        {"clue_id": "c1", "create_time_detail": "2026-06-01 00:01:00"},
                        {"name": "missing id", "create_time_detail": "2026-06-01 00:02:00"},
                    ]
                }
            }
        ]
    )

    summary = export_clues(
        client=client,
        start=datetime(2026, 6, 1),
        end=datetime(2026, 6, 1, 1),
        out_dir=tmp_path,
        window_hours=1,
        page_size=100,
    )

    rows = read_jsonl(tmp_path / "clues_20260601000000_20260601010000.jsonl")
    assert rows[1]["raw_payload"] == {"name": "missing id", "create_time_detail": "2026-06-01 00:02:00"}
    assert summary["field_presence_counts"]["clue_id"] == {"present": 1, "missing": 1}
    assert summary["unique_clue_ids"] == 1
    assert summary["duplicate_clue_ids"] == 0


def test_failed_window_summary_sanitizes_secret_and_access_token(tmp_path: Path):
    client = FakeClueClient([RuntimeError("bad secret-1 access-token token-1")])

    summary = export_clues(
        client=client,
        start=datetime(2026, 6, 1),
        end=datetime(2026, 6, 1, 1),
        out_dir=tmp_path,
        window_hours=1,
        page_size=100,
        secrets=["secret-1", "token-1"],
    )

    error = summary["failed_windows"][0]["error"]
    assert "secret-1" not in error
    assert "token-1" not in error
    assert "[redacted]" in error
    assert sanitize_text("secret-1 token-1", secrets=["secret-1", "token-1"]) == "[redacted] [redacted]"


def test_local_exports_is_gitignored():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "local_exports/" in gitignore
