"""Explicit maintenance entrypoint for certifying the legacy settlement root."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.dy_api.db import get_session_factory  # noqa: E402
from apps.worker.legacy_projection_bootstrap import (  # noqa: E402
    ResourceGateConfig,
    certify_legacy_null_root,
)


PROTOCOL = "dydata-legacy-root-maintenance-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Certify and atomically publish the deterministic legacy settlement root. "
            "Run only during an authorized low-write maintenance window."
        )
    )
    parser.add_argument("--batch-size", required=True, type=int)
    parser.add_argument("--max-manifest-rows", required=True, type=int)
    parser.add_argument("--max-estimated-write-bytes", required=True, type=int)
    parser.add_argument("--max-estimated-wal-bytes", required=True, type=int)
    parser.add_argument("--observed-disk-headroom-bytes", required=True, type=int)
    parser.add_argument("--min-disk-headroom-bytes", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run legacy-root certification and emit one credential-free JSON result."""

    args = _parser().parse_args(argv)
    limits = ResourceGateConfig(
        max_manifest_rows=args.max_manifest_rows,
        max_estimated_write_bytes=args.max_estimated_write_bytes,
        max_estimated_wal_bytes=args.max_estimated_wal_bytes,
        observed_disk_headroom_bytes=args.observed_disk_headroom_bytes,
        min_disk_headroom_bytes=args.min_disk_headroom_bytes,
    )
    factory = get_session_factory()
    if factory is None:
        print(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "status": "error",
                    "error_type": "database_not_configured",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    try:
        result = certify_legacy_null_root(
            factory,
            batch_size=args.batch_size,
            resource_limits=limits,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "status": "error",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {"protocol": PROTOCOL, **asdict(result)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 3 if result.status == "resource_guard" else 0


if __name__ == "__main__":
    raise SystemExit(main())
