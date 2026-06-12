from __future__ import annotations

from datetime import datetime

from apps.worker.collect_once import parse_args, resolve_window_from_args


def test_collect_once_args_map_to_collection_window():
    args = parse_args(
        [
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-03T12:00:00+08:00",
            "--settlement-only",
            "--skip-browser-export",
        ]
    )

    window = resolve_window_from_args(args, now=datetime.fromisoformat("2026-06-12T10:00:00+08:00"))

    assert window.start.isoformat() == "2026-01-01T00:00:00+08:00"
    assert window.end.isoformat() == "2026-01-03T12:00:00+08:00"
    assert args.settlement_only is True
    assert args.skip_browser_export is True
