#!/usr/bin/env python3
"""Safely retain and remove PostgreSQL database backup files.

The command is deliberately dry-run by default.  Only files with the exact
``pre-migrate-YYYYMMDDTHHMMSSZ.dump`` name are managed; environment backups,
partial files, manually pinned files, and other artifacts are left alone.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


BACKUP_NAME_RE = re.compile(r"^pre-migrate-(?P<stamp>\d{8}T\d{6}Z)\.dump$")
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
DEFAULT_LATEST = 3
DEFAULT_DAILY_DAYS = 7
DEFAULT_WEEKLY_WEEKS = 4
DEFAULT_VALIDATION_TIMEOUT_SECONDS = 60


class RetentionError(RuntimeError):
    """Raised when the retention operation cannot safely proceed."""


class RetentionBlocked(RetentionError):
    """Raised when validation or a pre-delete safety check fails."""


@dataclass(frozen=True)
class FileFingerprint:
    """The file identity and metadata that must remain unchanged before delete."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    mode: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "FileFingerprint":
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            size=value.st_size,
            mtime_ns=value.st_mtime_ns,
            mode=stat.S_IMODE(value.st_mode),
        )


@dataclass(frozen=True)
class BackupRecord:
    path: Path
    timestamp: datetime | None
    fingerprint: FileFingerprint | None
    valid: bool
    validation_reason: str
    pinned: bool

    @property
    def name(self) -> str:
        return self.path.name

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "valid": self.valid,
            "validation_reason": self.validation_reason,
            "pinned": self.pinned,
            "size": self.fingerprint.size if self.fingerprint else None,
        }


@dataclass(frozen=True)
class RetentionPlan:
    root: Path
    records: tuple[BackupRecord, ...]
    kept: tuple[BackupRecord, ...]
    deletable: tuple[BackupRecord, ...]
    invalid: tuple[BackupRecord, ...]
    blocked_reasons: tuple[str, ...]
    reference: datetime | None

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_reasons)

    def report(self, *, apply: bool, deleted: Sequence[str] = (), skipped: Sequence[dict[str, str]] = ()) -> dict[str, object]:
        return {
            "root": str(self.root),
            "mode": "apply" if apply else "dry-run",
            "blocked": self.blocked,
            "blocked_reasons": list(self.blocked_reasons),
            "reference": self.reference.isoformat() if self.reference else None,
            "scanned": [record.as_json() for record in self.records],
            "kept": [record.name for record in self.kept],
            "would_delete": [record.name for record in self.deletable],
            "deleted": list(deleted),
            "skipped": list(skipped),
        }


Validator = Callable[[Path], tuple[bool, str]]


def _resolve_root(value: Path) -> Path:
    root = Path(value)
    if root.is_symlink():
        raise RetentionError(f"backup directory must not be a symlink: {root}")
    if not root.exists() or not root.is_dir():
        raise RetentionError(f"backup directory does not exist or is not a directory: {root}")
    resolved = root.resolve(strict=True)
    if resolved.is_symlink():
        raise RetentionError(f"backup directory must not resolve through a symlink: {root}")
    return resolved


def _safe_direct_child(root: Path, path: Path) -> bool:
    """Return true only for a direct, non-traversing child of ``root``."""

    try:
        if path.parent.resolve(strict=True) != root:
            return False
    except OSError:
        return False
    return True


def _fingerprint(path: Path, root: Path) -> FileFingerprint:
    if not _safe_direct_child(root, path):
        raise RetentionError(f"backup path escapes backup directory: {path}")
    value = path.lstat()
    if stat.S_ISLNK(value.st_mode):
        raise RetentionError(f"backup path must not be a symlink: {path}")
    if not stat.S_ISREG(value.st_mode):
        raise RetentionError(f"backup path must be a regular file: {path}")
    return FileFingerprint.from_stat(value)


def _parse_timestamp(name: str) -> datetime | None:
    match = BACKUP_NAME_RE.fullmatch(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("stamp"), TIMESTAMP_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def validate_backup_file(
    path: Path,
    *,
    pg_restore: str = "pg_restore",
    validator_command: Sequence[str] | None = None,
    timeout_seconds: int = DEFAULT_VALIDATION_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Validate a custom-format PostgreSQL dump before it can be deleted.

    The header check provides a useful early diagnostic.  ``pg_restore --list``
    is still required, so an unavailable validator fails closed.
    """

    try:
        fingerprint = path.lstat()
    except OSError as exc:
        return False, f"cannot stat backup: {exc}"
    if stat.S_ISLNK(fingerprint.st_mode):
        return False, "symlink backup is not eligible"
    if not stat.S_ISREG(fingerprint.st_mode):
        return False, "backup is not a regular file"
    if fingerprint.st_size <= 0:
        return False, "backup is empty"

    try:
        with path.open("rb") as stream:
            header = stream.read(5)
    except OSError as exc:
        return False, f"cannot read backup: {exc}"
    if header != b"PGDMP":
        return False, "backup is not a PostgreSQL custom-format dump"

    try:
        if validator_command:
            with path.open("rb") as stream:
                result = subprocess.run(
                    [*validator_command, "--list", "-"],
                    check=False,
                    stdin=stream,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
        else:
            executable = (
                shutil.which(pg_restore)
                if os.path.basename(pg_restore) == pg_restore
                else pg_restore
            )
            if not executable or (
                os.path.basename(pg_restore) == pg_restore
                and shutil.which(pg_restore) is None
            ):
                return False, f"validator not found: {pg_restore}"
            result = subprocess.run(
                [executable, "--list", str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"pg_restore validation failed: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = detail[-1] if detail else f"exit={result.returncode}"
        return False, f"pg_restore validation failed: {suffix[-500:]}"
    return True, "pg_restore --list passed"


def _read_pin_names(pin_file: Path | None) -> set[str]:
    if pin_file is None:
        return set()
    if pin_file.is_symlink():
        raise RetentionError(f"pin file must not be a symlink: {pin_file}")
    if not pin_file.is_file():
        raise RetentionError(f"pin file does not exist or is not a regular file: {pin_file}")
    names: set[str] = set()
    for line_number, raw_line in enumerate(pin_file.read_text(encoding="utf-8").splitlines(), 1):
        name = raw_line.split("#", 1)[0].strip()
        if not name:
            continue
        candidate = Path(name)
        if candidate.name != name or name in {".", ".."} or ".." in candidate.parts:
            raise RetentionError(
                f"pin file entry must be a backup basename (line {line_number}): {name}"
            )
        names.add(name)
    return names


def _has_pin_marker(path: Path) -> bool:
    marker_names = (
        f"{path.name}.pin",
        f"{path.name}.pinned",
        f"{path.stem}.pin",
    )
    for marker_name in marker_names:
        marker = path.with_name(marker_name)
        if marker.is_symlink():
            return True
        if marker.is_file():
            return True
    return False


def scan_backups(
    root: Path,
    *,
    validator: Validator | None = None,
    pg_restore: str = "pg_restore",
    validator_command: Sequence[str] | None = None,
    pin_file: Path | None = None,
) -> tuple[BackupRecord, ...]:
    """Inspect exact ordinary backup candidates without following symlinks."""

    resolved_root = _resolve_root(root)
    pin_names = _read_pin_names(pin_file)
    records: list[BackupRecord] = []
    for entry in sorted(resolved_root.iterdir(), key=lambda item: item.name):
        timestamp = _parse_timestamp(entry.name)
        if timestamp is None:
            continue
        pinned = entry.name in pin_names or _has_pin_marker(entry)
        try:
            fingerprint = _fingerprint(entry, resolved_root)
        except (OSError, RetentionError) as exc:
            records.append(
                BackupRecord(
                    path=entry,
                    timestamp=timestamp,
                    fingerprint=None,
                    valid=False,
                    validation_reason=str(exc),
                    pinned=pinned,
                )
            )
            continue
        if validator is None:
            valid, reason = validate_backup_file(
                entry,
                pg_restore=pg_restore,
                validator_command=validator_command,
            )
        else:
            try:
                valid, reason = validator(entry)
            except Exception as exc:  # fail closed for custom validators
                valid, reason = False, f"validator raised: {exc}"
        records.append(
            BackupRecord(
                path=entry,
                timestamp=timestamp,
                fingerprint=fingerprint,
                valid=bool(valid),
                validation_reason=str(reason),
                pinned=pinned,
            )
        )
    return tuple(records)


def _week_key(value: date) -> tuple[int, int]:
    iso = value.isocalendar()
    return iso.year, iso.week


def _latest_in(records: Iterable[BackupRecord]) -> BackupRecord | None:
    values = list(records)
    if not values:
        return None
    return max(values, key=lambda record: record.timestamp or datetime.min.replace(tzinfo=timezone.utc))


def make_plan(
    root: Path,
    records: Sequence[BackupRecord],
    *,
    as_of: datetime | None = None,
    latest_count: int = DEFAULT_LATEST,
    daily_days: int = DEFAULT_DAILY_DAYS,
    weekly_weeks: int = DEFAULT_WEEKLY_WEEKS,
) -> RetentionPlan:
    """Build a fail-closed retention plan from scanned backup records."""

    if latest_count < 1 or daily_days < 0 or weekly_weeks < 0:
        raise RetentionError("retention counts must be non-negative; latest_count must be positive")
    valid = sorted(
        (record for record in records if record.valid and record.timestamp is not None),
        key=lambda record: record.timestamp or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    invalid = tuple(record for record in records if not record.valid)
    reference = as_of or (valid[0].timestamp if valid else None)
    if reference is not None and reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    keep_names: set[str] = {record.name for record in records if record.pinned}
    keep_names.update(record.name for record in valid[:latest_count])
    if valid:
        keep_names.add(valid[-1].name)  # earliest valid baseline

    if reference is not None:
        for offset in range(daily_days):
            day = reference.date() - timedelta(days=offset)
            selected = _latest_in(record for record in valid if record.timestamp.date() == day)
            if selected:
                keep_names.add(selected.name)
        reference_week = _week_key(reference.date())
        week_keys: list[tuple[int, int]] = []
        cursor = reference.date()
        for _ in range(weekly_weeks):
            key = _week_key(cursor)
            if key not in week_keys:
                week_keys.append(key)
            cursor -= timedelta(days=7)
        for key in week_keys:
            selected = _latest_in(record for record in valid if _week_key(record.timestamp.date()) == key)
            if selected:
                keep_names.add(selected.name)

    kept = tuple(record for record in records if record.name in keep_names)
    potential_deletions = tuple(
        record
        for record in valid
        if record.name not in keep_names and not record.pinned
    )
    blocked_reasons: list[str] = []
    if invalid:
        blocked_reasons.append(
            "one or more ordinary timestamped backups failed validation; no files will be deleted"
        )
    return RetentionPlan(
        root=_resolve_root(root),
        records=tuple(records),
        kept=tuple(sorted(kept, key=lambda record: record.name)),
        deletable=tuple(sorted(potential_deletions, key=lambda record: record.name)),
        invalid=tuple(sorted(invalid, key=lambda record: record.name)),
        blocked_reasons=tuple(blocked_reasons),
        reference=reference,
    )


def _same_fingerprint(path: Path, expected: FileFingerprint, root: Path) -> bool:
    try:
        current = _fingerprint(root, path)
    except (OSError, RetentionError):
        return False
    return current == expected


def apply_plan(
    plan: RetentionPlan,
    *,
    validator: Validator | None = None,
    pg_restore: str = "pg_restore",
    validator_command: Sequence[str] | None = None,
) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    """Delete only unchanged, revalidated files; return deleted and skipped names."""

    if plan.blocked:
        raise RetentionBlocked("; ".join(plan.blocked_reasons))

    failures: list[dict[str, str]] = []
    for record in plan.deletable:
        if record.fingerprint is None or not _same_fingerprint(record.path, record.fingerprint, plan.root):
            failures.append({"name": record.name, "reason": "file changed or became unsafe before delete"})
            continue
        if validator is None:
            valid, reason = validate_backup_file(
                record.path,
                pg_restore=pg_restore,
                validator_command=validator_command,
            )
        else:
            try:
                valid, reason = validator(record.path)
            except Exception as exc:
                valid, reason = False, f"validator raised: {exc}"
        if not valid:
            failures.append({"name": record.name, "reason": f"revalidation failed: {reason}"})

    if failures:
        raise RetentionBlocked(
            "pre-delete safety check failed: "
            + "; ".join(f"{item['name']}: {item['reason']}" for item in failures)
        )

    deleted: list[str] = []
    for record in plan.deletable:
        try:
            os.unlink(record.path)
        except OSError as exc:
            raise RetentionError(f"failed to delete {record.name}: {exc}") from exc
        deleted.append(record.name)
    return tuple(deleted), ()


def _parse_as_of(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("as-of must be ISO-8601, for example 2026-10-09T00:00:00Z") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _write_report(path: Path, payload: dict[str, object]) -> None:
    if path.is_symlink():
        raise RetentionError(f"report path must not be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    if temporary.is_symlink():
        raise RetentionError(f"report temporary path must not be a symlink: {temporary}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path(os.environ.get("DY_BACKUP_DIR", "./backups")),
        help="directory containing backups (default: DY_BACKUP_DIR or ./backups)",
    )
    parser.add_argument("--apply", action="store_true", help="delete eligible files; default is dry-run")
    parser.add_argument("--pin-file", type=Path, help="optional file containing pinned backup basenames")
    parser.add_argument(
        "--pg-restore",
        default=os.environ.get("PG_RESTORE_BIN", "pg_restore"),
        help="pg_restore executable used to validate custom dumps",
    )
    parser.add_argument(
        "--validator-command",
        help="command used as pg_restore adapter; receives '--list -' and the dump on stdin",
    )
    parser.add_argument("--as-of", type=_parse_as_of, help="reference time for retention buckets")
    parser.add_argument("--report-file", type=Path, help="write JSON evidence to this path")
    parser.add_argument("--latest", type=int, default=DEFAULT_LATEST, help=f"latest versions to keep (default: {DEFAULT_LATEST})")
    parser.add_argument("--daily-days", type=int, default=DEFAULT_DAILY_DAYS, help=f"daily buckets to keep (default: {DEFAULT_DAILY_DAYS})")
    parser.add_argument("--weekly-weeks", type=int, default=DEFAULT_WEEKLY_WEEKS, help=f"weekly buckets to keep (default: {DEFAULT_WEEKLY_WEEKS})")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        try:
            validator_command = shlex.split(args.validator_command) if args.validator_command else None
        except ValueError as exc:
            raise RetentionError(f"invalid validator command: {exc}") from exc
        records = scan_backups(
            args.backup_dir,
            pg_restore=args.pg_restore,
            validator_command=validator_command,
            pin_file=args.pin_file,
        )
        plan = make_plan(
            args.backup_dir,
            records,
            as_of=args.as_of,
            latest_count=args.latest,
            daily_days=args.daily_days,
            weekly_weeks=args.weekly_weeks,
        )
        if args.apply:
            if plan.blocked:
                payload = plan.report(apply=True)
                if args.report_file:
                    _write_report(args.report_file, payload)
                print(json.dumps(payload, ensure_ascii=False))
                return 2
            try:
                deleted, skipped = apply_plan(
                    plan,
                    pg_restore=args.pg_restore,
                    validator_command=validator_command,
                )
            except RetentionBlocked as exc:
                payload = plan.report(apply=True)
                payload["blocked"] = True
                payload["blocked_reasons"] = [*plan.blocked_reasons, str(exc)]
                if args.report_file:
                    _write_report(args.report_file, payload)
                print(json.dumps(payload, ensure_ascii=False))
                return 2
            payload = plan.report(apply=True, deleted=deleted, skipped=skipped)
        else:
            payload = plan.report(apply=False)
        if args.report_file:
            _write_report(args.report_file, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except RetentionBlocked as exc:
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "blocked": True, "error": str(exc)}, ensure_ascii=False))
        return 2
    except RetentionError as exc:
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
