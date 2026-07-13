from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_store_location_import_cli_documents_input_and_safe_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/import_store_locations.py", "--help"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0
    assert "--input" in result.stdout
    assert "--enable-participation" in result.stdout
    assert "--dry-run" in result.stdout


def test_store_score_refresh_cli_documents_manual_refresh_controls() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/refresh_store_scores.py", "--help"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0
    assert "--lookback-days" in result.stdout
    assert "--min-samples" in result.stdout
    assert "--dry-run" in result.stdout
