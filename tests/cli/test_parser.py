from __future__ import annotations

from datetime import date

import pytest

from dydata_cli.parser import CliArgumentError, parse_args


def test_parser_accepts_only_the_approved_command_tree() -> None:
    assert parse_args(["commands", "--json"]).command == "commands"
    assert parse_args(["auth", "login"]).command == "auth.login"
    assert parse_args(["auth", "logout"]).command == "auth.logout"
    assert parse_args(["auth", "status", "--json"]).command == "auth.status"
    assert parse_args(["stores", "list", "--json"]).command == "stores.list"
    assert parse_args(["version", "--json"]).command == "version"

    with pytest.raises(CliArgumentError):
        parse_args(["orders", "list"])


def test_follow_up_stats_defaults_to_the_last_seven_beijing_days() -> None:
    parsed = parse_args(
        ["clues", "follow-up-stats"], today=date(2026, 7, 21)
    )

    assert parsed.command == "clues.follow-up-stats"
    assert parsed.date_from == date(2026, 7, 15)
    assert parsed.date_to == date(2026, 7, 21)
    assert parsed.store_ids == []
    assert parsed.output == "json"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["clues", "follow-up-stats", "--from", "2026-07-01"], "together"),
        (
            [
                "clues",
                "follow-up-stats",
                "--from",
                "2026-07-03",
                "--to",
                "2026-07-02",
            ],
            "must not be after",
        ),
        (
            [
                "clues",
                "follow-up-stats",
                "--from",
                "2025-01-01",
                "--to",
                "2026-01-02",
            ],
            "366",
        ),
        (
            [
                "clues",
                "follow-up-stats",
                "--from",
                "20260701",
                "--to",
                "20260707",
            ],
            "YYYY-MM-DD",
        ),
    ],
)
def test_follow_up_stats_rejects_invalid_date_ranges(
    argv: list[str], message: str
) -> None:
    with pytest.raises(CliArgumentError, match=message):
        parse_args(argv)


def test_follow_up_stats_preserves_repeatable_store_ids_and_table_output() -> None:
    parsed = parse_args(
        [
            "clues",
            "follow-up-stats",
            "--from",
            "2026-07-01",
            "--to",
            "2026-07-07",
            "--store-id",
            "store-a",
            "--store-id",
            "store-b",
            "--output",
            "table",
        ]
    )

    assert parsed.store_ids == ["store-a", "store-b"]
    assert parsed.output == "table"
