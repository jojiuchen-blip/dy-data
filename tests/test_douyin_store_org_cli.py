from __future__ import annotations

import os
import subprocess
import sys


def test_douyin_store_org_import_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/import_douyin_store_org.py", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert result.returncode == 0
    assert "Douyin leaderboard store organization" in result.stdout
