"""Offline command-shell entry point; service execution is added in Task 7."""

from __future__ import annotations

from collections.abc import Sequence

from .constants import CLI_SCHEMA_VERSION, CLI_VERSION
from .output import emit_error, emit_json
from .parser import CliArgumentError, parse_args
from .registry import command_catalog


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parsed = parse_args(argv)
    except CliArgumentError as exc:
        return emit_error("unknown", "INVALID_ARGUMENT", str(exc))

    if parsed.command == "commands":
        emit_json(
            {
                "ok": True,
                "command": "commands",
                "schema_version": CLI_SCHEMA_VERSION,
                "data": {"commands": command_catalog()},
            }
        )
        return 0
    if parsed.command == "version":
        emit_json(
            {
                "ok": True,
                "command": "version",
                "schema_version": CLI_SCHEMA_VERSION,
                "data": {"cli_version": CLI_VERSION, "schema_version": CLI_SCHEMA_VERSION},
            }
        )
        return 0
    return emit_error(
        parsed.command,
        "NOT_IMPLEMENTED",
        "This command is registered but offline execution is not available yet.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
