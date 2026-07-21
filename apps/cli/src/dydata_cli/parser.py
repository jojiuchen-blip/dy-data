"""Strict argument parsing for the approved read-only command tree."""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta
from typing import Sequence

from .constants import BEIJING_TIMEZONE


class CliArgumentError(ValueError):
    """A user argument error that the CLI can serialize as JSON."""


class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliArgumentError(message)


def beijing_today() -> date:
    return datetime.now(BEIJING_TIMEZONE).date()


def build_parser() -> argparse.ArgumentParser:
    parser = CliArgumentParser(prog="dydata", allow_abbrev=False, add_help=True)
    commands = parser.add_subparsers(dest="group", required=True)

    commands_catalog = commands.add_parser("commands", allow_abbrev=False)
    commands_catalog.add_argument("--json", action="store_true", required=True)
    commands_catalog.set_defaults(command="commands")

    auth = commands.add_parser("auth", allow_abbrev=False)
    auth_actions = auth.add_subparsers(dest="auth_action", required=True)
    for action in ("login", "logout"):
        auth_action = auth_actions.add_parser(action, allow_abbrev=False)
        auth_action.set_defaults(command=f"auth.{action}")
    auth_status = auth_actions.add_parser("status", allow_abbrev=False)
    auth_status.add_argument("--json", action="store_true", required=True)
    auth_status.set_defaults(command="auth.status")

    stores = commands.add_parser("stores", allow_abbrev=False)
    stores_actions = stores.add_subparsers(dest="stores_action", required=True)
    stores_list = stores_actions.add_parser("list", allow_abbrev=False)
    stores_list.add_argument("--json", action="store_true", required=True)
    stores_list.set_defaults(command="stores.list")

    clues = commands.add_parser("clues", allow_abbrev=False)
    clues_actions = clues.add_subparsers(dest="clues_action", required=True)
    follow_up_stats = clues_actions.add_parser("follow-up-stats", allow_abbrev=False)
    follow_up_stats.add_argument("--from", dest="date_from_text")
    follow_up_stats.add_argument("--to", dest="date_to_text")
    follow_up_stats.add_argument("--store-id", dest="store_ids", action="append", default=[])
    follow_up_stats.add_argument("--output", choices=("json", "table"), default="json")
    follow_up_stats.set_defaults(command="clues.follow-up-stats")

    version = commands.add_parser("version", allow_abbrev=False)
    version.add_argument("--json", action="store_true", required=True)
    version.set_defaults(command="version")
    return parser


def _parse_iso_date(value: str, *, option: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CliArgumentError(f"{option} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CliArgumentError(f"{option} must use YYYY-MM-DD") from exc


def _apply_follow_up_date_range(namespace: argparse.Namespace, *, today: date) -> None:
    date_from_text = namespace.date_from_text
    date_to_text = namespace.date_to_text
    if bool(date_from_text) != bool(date_to_text):
        raise CliArgumentError("--from and --to must be provided together")
    if date_from_text is None:
        namespace.date_to = today
        namespace.date_from = today - timedelta(days=6)
        return

    namespace.date_from = _parse_iso_date(date_from_text, option="--from")
    namespace.date_to = _parse_iso_date(date_to_text, option="--to")
    if namespace.date_from > namespace.date_to:
        raise CliArgumentError("--from must not be after --to")
    if (namespace.date_to - namespace.date_from).days + 1 > 366:
        raise CliArgumentError("The date range must not exceed 366 inclusive days")


def parse_args(
    argv: Sequence[str] | None = None, *, today: date | None = None
) -> argparse.Namespace:
    """Parse the only supported command tree and validate date invariants."""
    namespace = build_parser().parse_args(argv)
    if namespace.command == "clues.follow-up-stats":
        _apply_follow_up_date_range(namespace, today=today or beijing_today())
    return namespace
