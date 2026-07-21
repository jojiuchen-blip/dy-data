from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dydata_cli.docs import render_command_reference


ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "cli-agent-guide.md"
REFERENCE = ROOT / "docs" / "cli-command-reference.md"
GENERATOR = ROOT / "scripts" / "generate_cli_docs.py"


def test_command_reference_matches_registry() -> None:
    expected = render_command_reference()
    actual = REFERENCE.read_text(encoding="utf-8")

    assert actual == expected


def test_agent_guide_covers_safe_agent_workflow() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    required_concepts = (
        "`dydata commands --json`",
        "仅由人工执行 `dydata auth login`",
        "实时权限",
        "`system_follow_up_rate`",
        "`action_follow_rate`",
        "全成全败",
        "不得自动扩大门店范围",
        "不接收、读取、传递、保存或展示凭据",
        "不得伪造、补全或跨门店重试",
        "退出码",
    )

    assert all(concept in guide for concept in required_concepts)


def test_generated_reference_has_no_drift() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
