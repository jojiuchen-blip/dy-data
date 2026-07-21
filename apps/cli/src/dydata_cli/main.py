"""Console entry point for the strict read-only dydata CLI."""

from __future__ import annotations

from collections.abc import Sequence

from .client import DyDataClient
from .commands import execute_command
from .credentials import CredentialStore
from .output import emit_error
from .parser import CliArgumentError, parse_args


def main(
    argv: Sequence[str] | None = None,
    *,
    credential_store: CredentialStore | None = None,
    client: DyDataClient | None = None,
) -> int:
    """Parse and execute one approved CLI command."""
    try:
        parsed = parse_args(argv)
    except CliArgumentError:
        return emit_error(
            "unknown", "INVALID_ARGUMENT", "Invalid command arguments."
        )
    return execute_command(
        parsed,
        credential_store=credential_store,
        client=client,
    )


if __name__ == "__main__":
    raise SystemExit(main())
