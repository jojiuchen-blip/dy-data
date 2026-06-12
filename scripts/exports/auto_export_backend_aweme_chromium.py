"""Run the Linux Chromium backend-aweme export path with job_run tracking.

This adapter owns the production wrapper concerns only:
- require a configured PostgreSQL job_runs table before exporting;
- create an isolated download run directory;
- run the concrete browser automation command supplied by apps/worker;
- mark failed job_runs instead of letting browser failures disappear;
- remove temporary downloads after a successful run.

The Douyin page workflow remains in apps/worker or a supplied command.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


DEFAULT_JOB_NAME = "backend_aweme_chromium_export"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", default="", help="Existing or caller-provided job_runs.job_id.")
    parser.add_argument("--job-name", default=DEFAULT_JOB_NAME)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="PostgreSQL URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--cdp-url",
        default=os.environ.get("BROWSER_CDP_URL", "http://browser:9222"),
        help="Chromium DevTools endpoint exposed on the Docker network.",
    )
    parser.add_argument(
        "--download-dir",
        default=os.environ.get("BROWSER_EXPORT_DOWNLOAD_DIR", "/home/browser/Downloads/job-runs"),
        help="Shared temp download directory mounted into browser and worker containers.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=os.environ.get("BROWSER_EXPORT_ARTIFACT_DIR", "/data/browser-exports"),
        help="Durable artifact directory for the concrete export command.",
    )
    parser.add_argument(
        "--command",
        default=os.environ.get("BROWSER_EXPORT_COMMAND", ""),
        help="Shell command for the concrete export automation.",
    )
    parser.add_argument(
        "--skip-cdp-check",
        action="store_true",
        help="Skip the Chromium /json/version readiness check.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Local-only escape hatch. Production should not use this.",
    )
    parser.add_argument("command_args", nargs=argparse.REMAINDER)
    return parser.parse_args()


def sanitize_message(message: str, paths: list[Path]) -> str:
    sanitized = message
    for path in paths:
        value = str(path)
        if value:
            sanitized = sanitized.replace(value, "<runtime-path>")
    home = os.environ.get("HOME")
    if home:
        sanitized = sanitized.replace(home, "<home>")
    return sanitized[:1800]


def connect(database_url: str):
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for production browser exports.")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install psycopg[binary] so browser exports can record job_runs.") from exc
    return psycopg.connect(database_url)


def insert_running_job(database_url: str, payload: dict[str, Any]) -> None:
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_runs (
                    job_id,
                    job_name,
                    status,
                    started_at,
                    success_count,
                    failed_count,
                    metadata_json
                )
                VALUES (%s, %s, 'running', %s, 0, 0, %s::jsonb)
                ON CONFLICT (job_id) DO UPDATE
                SET status = EXCLUDED.status,
                    started_at = EXCLUDED.started_at,
                    finished_at = NULL,
                    success_count = 0,
                    failed_count = 0,
                    error_message = NULL,
                    metadata_json = EXCLUDED.metadata_json
                """,
                (
                    payload["job_id"],
                    payload["job_name"],
                    payload["started_at"],
                    json.dumps(payload["metadata"], ensure_ascii=False),
                ),
            )


def finish_job(database_url: str, job_id: str, status: str, error_message: str = "") -> None:
    success_count = 1 if status == "success" else 0
    failed_count = 0 if status == "success" else 1
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE job_runs
                SET status = %s,
                    finished_at = %s,
                    success_count = %s,
                    failed_count = %s,
                    error_message = NULLIF(%s, '')
                WHERE job_id = %s
                """,
                (status, utc_now(), success_count, failed_count, error_message, job_id),
            )


def check_cdp(cdp_url: str) -> None:
    version_url = cdp_url.rstrip("/") + "/json/version"
    try:
        with urlopen(version_url, timeout=10) as response:
            if response.status >= 400:
                raise RuntimeError(f"Chromium CDP check failed with HTTP {response.status}.")
    except URLError as exc:
        raise RuntimeError(f"Chromium CDP is not reachable at {version_url}.") from exc


def build_command(args: argparse.Namespace) -> tuple[str | list[str], bool]:
    remainder = list(args.command_args)
    if remainder and remainder[0] == "--":
        remainder = remainder[1:]

    if args.command:
        return args.command, True
    if remainder:
        return remainder, False
    raise RuntimeError("Provide --command or command arguments after -- for the concrete export workflow.")


def run_export(command: str | list[str], shell: bool, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        shell=shell,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def main() -> int:
    args = parse_args()
    job_id = args.job_id or f"{args.job_name}-{uuid.uuid4().hex}"
    download_root = Path(args.download_dir)
    artifact_dir = Path(args.artifact_dir)
    run_dir = download_root / job_id
    paths_to_hide = [download_root, artifact_dir, run_dir]

    started_at = utc_now()
    metadata = {
        "adapter": "scripts/exports/auto_export_backend_aweme_chromium.py",
        "cdp_url": args.cdp_url,
        "download_dir": "<runtime-path>",
        "artifact_dir": "<runtime-path>",
    }
    job_inserted = False

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        if not args.skip_db:
            insert_running_job(
                args.database_url,
                {
                    "job_id": job_id,
                    "job_name": args.job_name,
                    "started_at": started_at,
                    "metadata": metadata,
                },
            )
            job_inserted = True

        command, shell = build_command(args)

        if not args.skip_cdp_check:
            check_cdp(args.cdp_url)

        child_env = os.environ.copy()
        child_env.update(
            {
                "JOB_RUN_ID": job_id,
                "BROWSER_CDP_URL": args.cdp_url,
                "BROWSER_EXPORT_RUN_DIR": str(run_dir),
                "BROWSER_EXPORT_DOWNLOAD_DIR": str(download_root),
                "BROWSER_EXPORT_ARTIFACT_DIR": str(artifact_dir),
            }
        )

        result = run_export(command, shell, child_env)
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)

        if result.returncode != 0:
            message = sanitize_message(
                f"Export command exited with {result.returncode}. Check worker logs for details.",
                paths_to_hide,
            )
            if not args.skip_db:
                finish_job(args.database_url, job_id, "failed", message)
            return result.returncode

        if not args.skip_db:
            finish_job(args.database_url, job_id, "success")
        shutil.rmtree(run_dir, ignore_errors=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI adapter must record unexpected failures.
        message = sanitize_message(str(exc), paths_to_hide)
        if job_inserted and not args.skip_db and args.database_url:
            try:
                finish_job(args.database_url, job_id, "failed", message)
            except Exception as db_exc:  # noqa: BLE001
                sys.stderr.write(f"Could not update failed job_run {job_id}: {db_exc}\n")
        sys.stderr.write(message + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
