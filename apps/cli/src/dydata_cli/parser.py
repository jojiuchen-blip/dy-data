"""Strict argument parsing for the approved read-only command tree."""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from .constants import BEIJING_TIMEZONE
from .registry import command_catalog


class CliArgumentError(ValueError):
    """A user argument error that the CLI can serialize as JSON."""


class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliArgumentError(message)


def beijing_today() -> date:
    return datetime.now(BEIJING_TIMEZONE).date()


def _command_tree(catalog: Sequence[dict[str, Any]]) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for metadata in catalog:
        node = tree
        for segment in metadata["command"].split("."):
            node = node.setdefault(segment, {})
        node["_metadata"] = metadata
    return tree


def _add_declared_parameter(
    parser: argparse.ArgumentParser, parameter: dict[str, Any]
) -> None:
    kwargs: dict[str, Any] = {"required": parameter.get("required", False)}
    if "dest" in parameter:
        kwargs["dest"] = parameter["dest"]
    if "default" in parameter:
        kwargs["default"] = parameter["default"]
    if "choices" in parameter:
        kwargs["choices"] = parameter["choices"]
    if parameter["type"] == "flag":
        kwargs["action"] = "store_true"
    elif parameter.get("repeatable"):
        kwargs["action"] = "append"
        kwargs.setdefault("default", [])
    parser.add_argument(parameter["name"], **kwargs)


def _add_command_tree(
    parser: argparse.ArgumentParser, tree: dict[str, Any], *, depth: int
) -> None:
    subparsers = parser.add_subparsers(dest=f"_command_path_{depth}", required=True)
    for segment, node in tree.items():
        command_parser = subparsers.add_parser(
            segment, allow_abbrev=False, add_help=False
        )
        metadata = node.get("_metadata")
        if metadata is not None:
            for parameter in metadata["parameters"]:
                _add_declared_parameter(command_parser, parameter)
            command_parser.set_defaults(command=metadata["command"])
        children = {key: value for key, value in node.items() if key != "_metadata"}
        if children:
            _add_command_tree(command_parser, children, depth=depth + 1)


def build_parser(
    catalog: Sequence[dict[str, Any]] | None = None,
) -> argparse.ArgumentParser:
    parser = CliArgumentParser(prog="dydata", allow_abbrev=False, add_help=False)
    _add_command_tree(parser, _command_tree(catalog or command_catalog()), depth=0)
    return parser


def _parse_iso_date(value: str, *, option: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CliArgumentError(f"{option} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CliArgumentError(f"{option} must use YYYY-MM-DD") from exc


def _declared_parameter(metadata: dict[str, Any], name: str) -> dict[str, Any]:
    return next(parameter for parameter in metadata["parameters"] if parameter["name"] == name)


def _apply_date_range(
    namespace: argparse.Namespace, metadata: dict[str, Any], *, today: date
) -> None:
    range_metadata = metadata.get("date_range")
    if range_metadata is None:
        return
    start = _declared_parameter(metadata, range_metadata["start"])
    end = _declared_parameter(metadata, range_metadata["end"])
    date_from_text = getattr(namespace, start["dest"])
    date_to_text = getattr(namespace, end["dest"])
    if bool(date_from_text) != bool(date_to_text):
        raise CliArgumentError(
            f"{start['name']} and {end['name']} must be provided together"
        )
    if date_from_text is None:
        setattr(namespace, end["normalized_dest"], today)
        setattr(
            namespace,
            start["normalized_dest"],
            today - timedelta(days=range_metadata["default_days"] - 1),
        )
        return

    date_from = _parse_iso_date(date_from_text, option=start["name"])
    date_to = _parse_iso_date(date_to_text, option=end["name"])
    if date_from > date_to:
        raise CliArgumentError(f"{start['name']} must not be after {end['name']}")
    if (date_to - date_from).days + 1 > range_metadata["max_inclusive_days"]:
        raise CliArgumentError(
            "The date range must not exceed "
            f"{range_metadata['max_inclusive_days']} inclusive days"
        )
    setattr(namespace, start["normalized_dest"], date_from)
    setattr(namespace, end["normalized_dest"], date_to)


def parse_args(
    argv: Sequence[str] | None = None, *, today: date | None = None
) -> argparse.Namespace:
    """Parse the only supported command tree and validate date invariants."""
    catalog = command_catalog()
    namespace = build_parser(catalog).parse_args(argv)
    metadata = next(item for item in catalog if item["command"] == namespace.command)
    _apply_date_range(namespace, metadata, today=today or beijing_today())
    return namespace
