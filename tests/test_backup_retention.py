from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.backup_retention as retention
from scripts.backup_retention import (
    RetentionApplyError,
    RetentionBlocked,
    RetentionError,
    _write_report,
    apply_plan,
    build_parser,
    main,
    make_plan,
    scan_backups,
)


UTC = timezone.utc


def _name(value: str) -> str:
    return f"pre-migrate-{value}.dump"


def _write_dump(root: Path, stamp: str, *, valid: bool = True) -> Path:
    path = root / _name(stamp)
    path.write_bytes(b"PGDMP\x01test" if valid else b"not-a-dump")
    return path


def _always_valid(path: Path) -> tuple[bool, str]:
    return True, "test validator passed"


def _as_of() -> datetime:
    return datetime(2026, 10, 9, tzinfo=UTC)


def test_cli_is_dry_run_by_default() -> None:
    args = build_parser().parse_args([])

    assert args.apply is False
    assert args.latest == 3
    assert args.daily_days == 7
    assert args.weekly_weeks == 4


def test_scan_manages_only_exact_ordinary_dumps_and_preserves_special_files(tmp_path: Path) -> None:
    ordinary = _write_dump(tmp_path, "20261009T000000Z")
    _write_dump(tmp_path, "20261008T000000Z", valid=False)
    (tmp_path / "pre-migrate-20261009T000000Z.dump.partial").write_bytes(b"partial")
    (tmp_path / "pre-production-cutover-20261009T000000Z.env").write_text("secret", encoding="utf-8")
    (tmp_path / "manual-baseline.dump").write_bytes(b"PGDMP\x01test")

    records = scan_backups(tmp_path, validator=_always_valid)

    assert [record.name for record in records] == [
        "pre-migrate-20261008T000000Z.dump",
        "pre-migrate-20261009T000000Z.dump",
    ]
    assert ordinary.name in {record.name for record in records}
    assert (tmp_path / "pre-migrate-20261009T000000Z.dump.partial").exists()
    assert (tmp_path / "pre-production-cutover-20261009T000000Z.env").exists()
    assert (tmp_path / "manual-baseline.dump").exists()


def test_validator_command_adapter_streams_dump_to_stdin(tmp_path: Path) -> None:
    _write_dump(tmp_path, "20261009T000000Z")
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import sys\n"
        "if sys.argv[1:] != ['--list']:\n"
        "    raise SystemExit(3)\n"
        "raise SystemExit(0 if sys.stdin.buffer.read(5) == b'PGDMP' else 4)\n",
        encoding="utf-8",
    )

    records = scan_backups(
        tmp_path,
        validator_command=(sys.executable, str(validator)),
    )

    assert records[0].valid is True
    assert records[0].validation_reason == "pg_restore --list passed"


def test_deploy_backup_functions_write_atomic_partial_and_use_validator_preflight(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for deployment integration test")
    deploy_script = Path(__file__).parents[1] / "deploy" / "tencent" / "deploy.sh"
    source_prefix = deploy_script.read_text(encoding="utf-8").replace("\r\n", "\n").split(
        "trap on_error ERR", 1
    )[0]
    harness = f"""
{source_prefix}
compose() {{
  case "$*" in
    *"pg_restore --version"*) return 0 ;;
    *"pg_restore --list"*) cat >/dev/null; return 0 ;;
    *"pg_dump"*) printf 'PGDMP\\001test'; return 0 ;;
    *) return 0 ;;
  esac
}}
check_backup_validator
check_backup_capacity
backup_database
test -n "$(find "$BACKUP_DIR" -maxdepth 1 -name 'pre-migrate-*.dump' -print -quit)"
test -z "$(find "$BACKUP_DIR" -maxdepth 1 -name '*.partial' -print -quit)"
"""
    app_dir = str(deploy_script.parents[2])
    backup_dir = str(tmp_path / "backups")
    if os.name == "nt":
        cygpath = shutil.which("cygpath")
        if cygpath is None:
            pytest.skip("cygpath is required to run the Bash integration test on Windows")
        app_dir = subprocess.check_output([cygpath, "-u", app_dir], text=True).strip()
        backup_dir = subprocess.check_output([cygpath, "-u", backup_dir], text=True).strip()
    environment = os.environ.copy()
    environment.update(
        {
            "APP_DIR": app_dir,
            "BACKUP_DIR": backup_dir,
            "LOG_DIR": str(tmp_path / "logs"),
            "BACKUP_PG_RESTORE_BIN": "",
            "BACKUP_MIN_FREE_BYTES": "1",
            "BACKUP_MIN_FREE_PERCENT": "1",
            "BACKUP_SIZE_SAFETY_PERCENT": "150",
        }
    )
    result = subprocess.run(
        [bash],
        input=harness,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    dumps = list((tmp_path / "backups").glob("pre-migrate-*.dump"))
    assert len(dumps) == 1
    assert dumps[0].read_bytes().startswith(b"PGDMP")
    assert not list((tmp_path / "backups").glob("*.partial"))


def test_deploy_defaults_to_container_validator_and_estimates_next_backup_capacity() -> None:
    deploy_script = (Path(__file__).parents[1] / "deploy" / "tencent" / "deploy.sh").read_text(
        encoding="utf-8"
    )

    validator_preflight = deploy_script.index("check_backup_validator")
    capacity_gate = deploy_script.index("check_backup_capacity")
    pg_dump = deploy_script.index("pg_dump")
    assert validator_preflight < capacity_gate < pg_dump
    assert 'BACKUP_PG_RESTORE_BIN="${BACKUP_PG_RESTORE_BIN:-}"' in deploy_script
    assert "compose exec -T postgres pg_restore --version" in deploy_script
    assert 'validator_args=(--validator-command "$(backup_validator_command)")' in deploy_script
    assert 'BACKUP_SIZE_SAFETY_PERCENT="${BACKUP_SIZE_SAFETY_PERCENT:-150}"' in deploy_script
    assert "estimated_next_backup_bytes" in deploy_script
    assert "umask 077" in deploy_script
    assert 'partial_file="$backup_file.partial"' in deploy_script
    assert 'mv -- "$partial_file" "$backup_file"' in deploy_script


def test_container_validator_command_round_trips_paths_with_spaces() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for deployment integration test")
    deploy_script = Path(__file__).parents[1] / "deploy" / "tencent" / "deploy.sh"
    source_prefix = deploy_script.read_text(encoding="utf-8").replace("\r\n", "\n").split(
        "trap on_error ERR", 1
    )[0]
    environment = os.environ.copy()
    environment.update(
        {
            "ENV_FILE": "/srv/dy data/production.env",
            "COMPOSE_FILE": "/srv/dy data/compose.yaml",
            "APT_MIRROR": "http://mirror.example",
            "DY_WEB_BASE_URL": "https://app.example",
        }
    )
    result = subprocess.run(
        [bash],
        input=f"{source_prefix}\nbackup_validator_command\n",
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    command = shlex.split(result.stdout.strip())
    assert command == [
        "sudo",
        "APT_MIRROR=http://mirror.example",
        "DY_WEB_BASE_URL=https://app.example",
        "docker",
        "compose",
        "--env-file",
        "/srv/dy data/production.env",
        "-f",
        "/srv/dy data/compose.yaml",
        "exec",
        "-T",
        "postgres",
        "pg_restore",
    ]


def test_pinned_manifest_and_sidecar_are_kept(tmp_path: Path) -> None:
    manifest_pinned = _write_dump(tmp_path, "20260901T000000Z")
    marker_pinned = _write_dump(tmp_path, "20260902T000000Z")
    _write_dump(tmp_path, "20260903T000000Z")
    (tmp_path / f"{marker_pinned.name}.pin").write_text("", encoding="utf-8")
    pin_file = tmp_path / "pins.txt"
    pin_file.write_text(f"{manifest_pinned.name}\n", encoding="utf-8")

    records = scan_backups(tmp_path, validator=_always_valid, pin_file=pin_file)

    assert {record.name for record in records if record.pinned} == {
        manifest_pinned.name,
        marker_pinned.name,
    }
    plan = make_plan(
        tmp_path,
        records,
        as_of=_as_of(),
        daily_days=0,
        weekly_weeks=0,
    )
    assert manifest_pinned.name in {record.name for record in plan.kept}
    assert marker_pinned.name in {record.name for record in plan.kept}
    assert all(record.name not in {manifest_pinned.name, marker_pinned.name} for record in plan.deletable)


def test_retention_keeps_latest_three_daily_weekly_and_earliest(tmp_path: Path) -> None:
    stamps = [
        "20260801T000000Z",  # earliest baseline
        "20260906T000000Z",  # four weeks before the reference week
        "20260913T000000Z",
        "20260920T000000Z",
        "20260927T000000Z",  # weekly bucket
        "20261001T000000Z",
        "20261002T000000Z",
        "20261003T000000Z",
        "20261004T000000Z",
        "20261005T000000Z",
        "20261006T000000Z",
        "20261007T000000Z",
        "20261008T000000Z",
        "20261009T000000Z",
    ]
    for stamp in stamps:
        _write_dump(tmp_path, stamp)

    records = scan_backups(tmp_path, validator=_always_valid)
    plan = make_plan(tmp_path, records, as_of=_as_of())
    kept = {record.name for record in plan.kept}

    assert _name("20261009T000000Z") in kept
    assert _name("20261008T000000Z") in kept
    assert _name("20261007T000000Z") in kept
    for stamp in ("20261003T000000Z", "20260927T000000Z", "20260920T000000Z"):
        assert _name(stamp) in kept
    assert _name("20260801T000000Z") in kept
    assert _name("20260906T000000Z") not in kept
    assert _name("20260906T000000Z") in {record.name for record in plan.deletable}


def test_invalid_ordinary_backup_blocks_all_deletions(tmp_path: Path) -> None:
    _write_dump(tmp_path, "20261007T000000Z")
    _write_dump(tmp_path, "20261008T000000Z")
    _write_dump(tmp_path, "20261009T000000Z", valid=False)

    records = scan_backups(tmp_path, validator=lambda path: (path.read_bytes().startswith(b"PGDMP"), "fixture"))
    plan = make_plan(tmp_path, records, as_of=_as_of(), daily_days=0, weekly_weeks=0)

    assert plan.blocked is True
    with pytest.raises(RetentionBlocked):
        apply_plan(plan, validator=lambda path: (path.read_bytes().startswith(b"PGDMP"), "fixture"))
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        (_name("20261007T000000Z"), _name("20261008T000000Z"), _name("20261009T000000Z"))
    )


def test_changed_file_is_detected_before_any_delete(tmp_path: Path) -> None:
    _write_dump(tmp_path, "20261007T000000Z")
    changed = _write_dump(tmp_path, "20261008T000000Z")
    _write_dump(tmp_path, "20261009T000000Z")

    records = scan_backups(tmp_path, validator=_always_valid)
    plan = make_plan(
        tmp_path,
        records,
        as_of=_as_of(),
        latest_count=1,
        daily_days=0,
        weekly_weeks=0,
    )
    changed.write_bytes(b"PGDMP\x01changed")

    with pytest.raises(RetentionBlocked):
        apply_plan(plan, validator=_always_valid)
    assert all(path.exists() for path in tmp_path.glob("pre-migrate-*.dump"))


def test_apply_rechecks_pin_protection_before_delete(tmp_path: Path) -> None:
    for stamp in ("20261007T000000Z", "20261008T000000Z", "20261009T000000Z", "20261010T000000Z"):
        _write_dump(tmp_path, stamp)
    pin_file = tmp_path / "pins.txt"
    pin_file.write_text("", encoding="utf-8")

    records = scan_backups(tmp_path, validator=_always_valid, pin_file=pin_file)
    plan = make_plan(
        tmp_path,
        records,
        as_of=_as_of(),
        latest_count=1,
        daily_days=0,
        weekly_weeks=0,
    )
    newly_pinned = plan.deletable[0].name
    pin_file.write_text(f"{newly_pinned}\n", encoding="utf-8")

    with pytest.raises(RetentionBlocked, match="protection changed"):
        apply_plan(plan, validator=_always_valid, pin_file=pin_file)
    assert (tmp_path / newly_pinned).exists()


def test_apply_reports_files_deleted_before_partial_unlink_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for stamp in (
        "20261006T000000Z",
        "20261007T000000Z",
        "20261008T000000Z",
        "20261009T000000Z",
        "20261010T000000Z",
    ):
        _write_dump(tmp_path, stamp)

    records = scan_backups(tmp_path, validator=_always_valid)
    plan = make_plan(
        tmp_path,
        records,
        as_of=_as_of(),
        latest_count=1,
        daily_days=0,
        weekly_weeks=0,
    )
    real_unlink = retention.os.unlink
    calls = 0

    def flaky_unlink(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated unlink failure")
        real_unlink(path)

    monkeypatch.setattr(retention.os, "unlink", flaky_unlink)
    with pytest.raises(RetentionApplyError) as caught:
        apply_plan(plan, validator=_always_valid)

    assert caught.value.deleted == (plan.deletable[0].name,)
    assert caught.value.skipped == (
        {"name": plan.deletable[1].name, "reason": "delete failed: simulated unlink failure"},
    )
    assert not (tmp_path / plan.deletable[0].name).exists()
    assert (tmp_path / plan.deletable[1].name).exists()


def test_report_target_cannot_overwrite_backup_pin_or_alias(tmp_path: Path) -> None:
    backup = _write_dump(tmp_path, "20261007T000000Z")
    pin_file = tmp_path / "pins.json"
    pin_file.write_text("[]", encoding="utf-8")

    with pytest.raises(RetentionError, match=".json suffix"):
        _write_report(backup, {"phase": "planned"}, backup_root=tmp_path, pin_file=pin_file)
    with pytest.raises(RetentionError, match="pin file"):
        _write_report(pin_file, {"phase": "planned"}, backup_root=tmp_path, pin_file=pin_file)

    alias = tmp_path.parent / "backup-report.json"
    try:
        alias.hardlink_to(backup)
    except (OSError, NotImplementedError):
        pytest.skip("hard links are unavailable on this platform")
    with pytest.raises(RetentionError, match="aliases a backup"):
        _write_report(alias, {"phase": "planned"}, backup_root=tmp_path, pin_file=pin_file)
    assert backup.read_bytes().startswith(b"PGDMP")


def test_report_target_rejects_existing_json_and_pin_hardlink_alias(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-report-targets"
    outside.mkdir()
    existing_json = outside / "config.json"
    existing_json.write_text('{"setting": true}', encoding="utf-8")

    with pytest.raises(RetentionError, match="new or an existing"):
        _write_report(
            existing_json,
            {"mode": "dry-run", "root": str(tmp_path), "scanned": [], "would_delete": []},
            backup_root=tmp_path,
            pin_file=None,
        )

    pin_file = outside / "pins.json"
    pin_file.write_text("pre-migrate-20261007T000000Z.dump\n", encoding="utf-8")
    pin_alias = outside / "pin-report.json"
    try:
        pin_alias.hardlink_to(pin_file)
    except (OSError, NotImplementedError):
        pytest.skip("hard links are unavailable on this platform")
    with pytest.raises(RetentionError, match="aliases the pin"):
        _write_report(
            pin_alias,
            {"mode": "dry-run", "root": str(tmp_path), "scanned": [], "would_delete": []},
            backup_root=tmp_path,
            pin_file=pin_file,
        )


def test_report_is_exclusive_private_and_can_be_refreshed(tmp_path: Path) -> None:
    report = tmp_path / "backup-retention-report.json"
    _write_report(report, {"mode": "apply", "root": str(tmp_path), "scanned": [], "would_delete": [], "phase": "planned"}, backup_root=tmp_path, pin_file=None)

    mode = stat.S_IMODE(report.stat().st_mode)
    if os.name != "nt":
        assert mode == 0o600
    assert not list(tmp_path.glob(".backup-retention-report.json.*.partial"))

    _write_report(report, {"mode": "apply", "root": str(tmp_path), "scanned": [], "would_delete": [], "phase": "complete"}, backup_root=tmp_path, pin_file=None)
    assert json.loads(report.read_text(encoding="utf-8"))["phase"] == "complete"


def test_report_collision_does_not_remove_existing_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = tmp_path / "backup-retention-report.json"
    partial = tmp_path / ".backup-retention-report.json.fixed.partial"
    partial.write_text("keep me", encoding="utf-8")

    class FixedUuid:
        hex = "fixed"

    monkeypatch.setattr(retention.uuid, "uuid4", lambda: FixedUuid())
    with pytest.raises(FileExistsError):
        _write_report(
            report,
            {"mode": "dry-run", "root": str(tmp_path), "scanned": [], "would_delete": []},
            backup_root=tmp_path,
            pin_file=None,
        )
    assert partial.read_text(encoding="utf-8") == "keep me"


def test_apply_rejects_report_target_before_deleting(tmp_path: Path) -> None:
    for stamp in ("20261007T000000Z", "20261008T000000Z", "20261009T000000Z"):
        _write_dump(tmp_path, stamp)
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import sys\n"
        "if sys.argv[1:] != ['--list', '-']:\n"
        "    raise SystemExit(3)\n"
        "raise SystemExit(0 if sys.stdin.buffer.read(5) == b'PGDMP' else 4)\n",
        encoding="utf-8",
    )
    report_target = tmp_path / _name("20261008T000000Z")
    before = sorted(path.name for path in tmp_path.glob("*.dump"))

    result = main(
        [
            "--backup-dir",
            str(tmp_path),
            "--apply",
            "--latest",
            "1",
            "--daily-days",
            "0",
            "--weekly-weeks",
            "0",
            "--validator-command",
            shlex.join([sys.executable, str(validator)]),
            "--report-file",
            str(report_target),
        ]
    )

    assert result == 1
    assert sorted(path.name for path in tmp_path.glob("*.dump")) == before


def test_apply_without_report_file_writes_unique_default_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for stamp in ("20261007T000000Z", "20261008T000000Z", "20261009T000000Z"):
        _write_dump(tmp_path, stamp)
    validator = tmp_path / "validator.py"
    validator.write_text(
        "import sys\n"
        "if sys.argv[1:] not in (['--list', '-'], ['--list']):\n"
        "    raise SystemExit(3)\n"
        "raise SystemExit(0 if sys.stdin.buffer.read(5) == b'PGDMP' else 4)\n",
        encoding="utf-8",
    )

    result = main(
        [
            "--backup-dir",
            str(tmp_path),
            "--apply",
            "--latest",
            "1",
            "--daily-days",
            "0",
            "--weekly-weeks",
            "0",
            "--validator-command",
            shlex.join([sys.executable, str(validator)]),
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    report = Path(output["report_file"])
    assert report.parent == tmp_path.resolve()
    assert report.name.startswith("backup-retention-")
    assert report.suffix == ".json"
    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert persisted["phase"] == "complete"
    assert persisted["deleted"] == output["deleted"]
    assert not list(tmp_path.glob(".backup-retention-*.partial"))


def test_symlink_candidate_is_invalid_and_never_deleted(tmp_path: Path) -> None:
    target = tmp_path / "outside.dump"
    target.write_bytes(b"PGDMP\x01outside")
    link = tmp_path / _name("20260901T000000Z")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    records = scan_backups(tmp_path, validator=_always_valid)

    assert len(records) == 1
    assert records[0].valid is False
    assert records[0].pinned is False
    assert link.is_symlink()
