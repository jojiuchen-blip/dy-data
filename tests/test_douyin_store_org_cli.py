from __future__ import annotations

import subprocess
import sys


def test_douyin_store_org_import_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/import_douyin_store_org.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Douyin leaderboard store organization" in result.stdout
