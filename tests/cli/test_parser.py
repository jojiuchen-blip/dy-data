from __future__ import annotations

from datetime import date
from copy import deepcopy
import json
import shlex
import argparse

import pytest

from dydata_cli.main import main
from dydata_cli.parser import CliArgumentError, build_parser, parse_args
from dydata_cli.registry import command_catalog


def test_parser_accepts_only_the_approved_command_tree() -> None:
    assert parse_args(["commands", "--json"]).command == "commands"
    terminal_login = parse_args(["auth", "login"])
    browser_login = parse_args(["auth", "login", "--browser"])
    assert terminal_login.command == "auth.login"
    assert terminal_login.browser is False
    assert browser_login.command == "auth.login"
    assert browser_login.browser is True
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


def test_follow_up_stats_normalizes_store_ids_for_request_binding() -> None:
    parsed = parse_args(
        [
            "clues",
            "follow-up-stats",
            "--store-id",
            " store-b ",
            "--store-id",
            "store-a",
            "--store-id",
            "store-b",
        ],
        today=date(2026, 7, 21),
    )

    assert parsed.store_ids == ["store-a", "store-b"]
    assert parsed.output == "json"


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["orders", "list"],
        ["stores", "list", "--json", "--unexpected"],
        ["clues", "follow-up-stats", "--from", "2026-07-01"],
    ],
)
def test_main_serializes_every_argument_error_as_one_json_document(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(argv)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    payload = json.loads(captured.out)
    assert payload["command"] == "unknown"
    assert payload["error"]["code"] == "INVALID_ARGUMENT"
    assert isinstance(payload["error"]["message"], str)
    assert payload["error"]["message"]
    assert payload["ok"] is False
    assert payload["schema_version"] == "1.0"


def test_registered_protected_command_requires_credentials(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class EmptyCredentialStore:
        def load(self) -> None:
            return None

    exit_code = main(
        ["auth", "status", "--json"],
        credential_store=EmptyCredentialStore(),
        client=object(),
    )

    assert exit_code == 3
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "AUTH_REQUIRED"


def _parser_leaf_commands(parser) -> set[str]:
    leaves: set[str] = set()
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for child in action.choices.values():
            if command := child.get_default("command"):
                leaves.add(command)
            leaves.update(_parser_leaf_commands(child))
    return leaves


def test_parser_is_generated_from_registry_examples_without_extra_commands() -> None:
    catalog = command_catalog()

    for item in catalog:
        safe_argv = shlex.split(item["examples"][0])[1:]
        assert parse_args(safe_argv).command == item["command"]
    assert _parser_leaf_commands(build_parser()) == {
        item["command"] for item in catalog
    }


def test_registry_command_name_change_drives_the_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = deepcopy(command_catalog())
    version = next(item for item in catalog if item["command"] == "version")
    version["command"] = "release"
    version["examples"] = ["dydata release --json"]
    monkeypatch.setattr("dydata_cli.parser.command_catalog", lambda: catalog)

    assert parse_args(["release", "--json"]).command == "release"
    with pytest.raises(CliArgumentError):
        parse_args(["version", "--json"])
