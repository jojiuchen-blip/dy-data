"""A runtime without Git may only write reports physically outside repositories."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import convert_jingcheng_product_types as command


def git(directory, *arguments):
    return subprocess.run(["git", "-C", str(directory), *arguments], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    (root / ".gitignore").write_text("private/\n", encoding="utf-8")
    (root / "tracked.json").write_text("{}", encoding="utf-8")
    git(root, "add", ".gitignore", "tracked.json")
    git(root, "-c", "user.name=Report Path Test", "-c", "user.email=report@example.invalid",
        "commit", "-m", "report path fixture")
    (root / "private").mkdir()
    return root


@pytest.fixture
def without_git(monkeypatch):
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git executable unavailable")

    return lambda: monkeypatch.setattr(command.subprocess, "run", unavailable)


def test_without_git_allows_physical_external_report(tmp_path, without_git):
    report = tmp_path / "private.json"
    without_git()
    assert command._private_report_path(report) == report.resolve()


@pytest.mark.parametrize("relative", ["tracked.json", "new.json", "private/report.json"])
def test_without_git_refuses_repository_even_if_report_is_ignored(repository, without_git, relative):
    without_git()
    with pytest.raises(command.ConversionError, match="cannot verify"):
        command._private_report_path(repository / relative)


def test_without_git_refuses_linked_worktree(repository, tmp_path, without_git):
    worktree = tmp_path / "worktree"
    git(repository, "worktree", "add", "--detach", str(worktree), "HEAD")
    assert (worktree / ".git").is_file()
    without_git()
    with pytest.raises(command.ConversionError, match="cannot verify"):
        command._private_report_path(worktree / "new.json")


def test_without_git_refuses_bare_repository(tmp_path, without_git):
    root = tmp_path / "bare"
    root.mkdir()
    git(root, "init", "--bare")
    without_git()
    with pytest.raises(command.ConversionError, match="cannot verify"):
        command._private_report_path(root / "objects" / "report.json")


def test_without_git_resolves_symlink_into_repository(repository, tmp_path, without_git):
    link = tmp_path / "linked-private"
    try:
        link.symlink_to(repository / "private", target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    without_git()
    with pytest.raises(command.ConversionError, match="cannot verify"):
        command._private_report_path(link / "report.json")


def test_without_git_refuses_dangling_git_marker(tmp_path, without_git):
    try:
        (tmp_path / ".git").symlink_to(tmp_path / "missing-git-dir", target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    without_git()
    with pytest.raises(command.ConversionError, match="cannot verify"):
        command._private_report_path(tmp_path / "report.json")


def test_without_git_refuses_unreadable_metadata(tmp_path, without_git, monkeypatch):
    original = Path.lstat

    def unreadable(path, *args, **kwargs):
        if path == tmp_path / ".git":
            raise PermissionError("metadata unavailable")
        return original(path, *args, **kwargs)

    without_git()
    monkeypatch.setattr(Path, "lstat", unreadable)
    with pytest.raises(command.ConversionError, match="cannot verify"):
        command._private_report_path(tmp_path / "report.json")


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"])
def test_without_git_refuses_repository_environment(tmp_path, without_git, monkeypatch, variable):
    without_git()
    monkeypatch.setenv(variable, "unverifiable-location")
    with pytest.raises(command.ConversionError, match="cannot verify"):
        command._private_report_path(tmp_path / "report.json")


def test_with_git_keeps_tracked_and_ignore_checks(repository, tmp_path):
    for relative in ("tracked.json", "unignored.json"):
        with pytest.raises(command.ConversionError, match="outside Git"):
            command._private_report_path(repository / relative)
    assert command._private_report_path(repository / "private/report.json") == repository / "private/report.json"
    assert command._private_report_path(tmp_path / "external.json") == tmp_path / "external.json"


def test_cli_without_git_refuses_repository_before_database(repository, without_git, monkeypatch, capsys):
    report = repository / "private/report.json"
    without_git()
    monkeypatch.setattr(command, "make_engine", lambda: pytest.fail("database must not be called"))
    monkeypatch.setattr(command.sys, "argv", [
        "convert-jingcheng", "--report", str(report), "--actor", "ops:report-test",
        "--change-reason", "report path test", "--idempotency-key", "report-path-test",
    ])
    assert command.main() == 1
    assert "cannot verify" in capsys.readouterr().err
    assert not report.exists()


def test_git_disappearing_after_repository_discovery_still_refuses(repository, monkeypatch):
    original = subprocess.run
    calls = []

    def disappears(arguments, **kwargs):
        calls.append(arguments)
        if len(calls) > 1:
            raise FileNotFoundError("git disappeared")
        return original(arguments, **kwargs)

    monkeypatch.setattr(command.subprocess, "run", disappears)
    with pytest.raises(OSError):
        command._private_report_path(repository / "private/report.json")


@pytest.mark.parametrize("inside_repository", [False, True])
def test_real_process_without_git(repository, tmp_path, inside_repository):
    report = repository / "private/report.json" if inside_repository else tmp_path / "external.json"
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"}}
    environment["PATH"] = str(tmp_path / "no-tools")
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run([
        sys.executable, "-c",
        "import shutil, sys; assert shutil.which('git') is None; "
        "from pathlib import Path; "
        "from scripts.convert_jingcheng_product_types import _private_report_path; "
        "print(_private_report_path(Path(sys.argv[1])))",
        str(report),
    ], cwd=Path(__file__).resolve().parents[1], env=environment,
       capture_output=True, text=True, encoding="utf-8")
    if inside_repository:
        assert result.returncode == 1 and "cannot verify" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert Path(result.stdout.strip()) == report.resolve()
    assert not report.exists()
