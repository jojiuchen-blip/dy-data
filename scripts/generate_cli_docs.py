"""Generate the CLI command reference from the runtime command registry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = ROOT / "apps" / "cli" / "src"
REFERENCE = ROOT / "docs" / "cli-command-reference.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="return nonzero when the generated reference has drifted",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(CLI_SOURCE))
    from dydata_cli.docs import render_command_reference

    expected = render_command_reference()
    actual = REFERENCE.read_text(encoding="utf-8") if REFERENCE.exists() else None
    if args.check:
        if actual == expected:
            return 0
        print(f"CLI command reference has drifted: {REFERENCE}", file=sys.stderr)
        return 1

    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
