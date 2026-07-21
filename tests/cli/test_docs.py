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
        "Agent 可以在用户明确要求后启动 `dydata auth login`",
        "凭据输入和授权确认仅由人工执行",
        "`dydata auth login --browser`",
        "隐藏输入",
        "`INTERACTIVE_REQUIRED`",
        "已有本地凭据",
        "先执行 `dydata auth logout`",
        "不得把账号或密码粘贴到对话",
        "默认终端流程不显示内部 `device_code`",
        "浏览器回退会显示一次性 `user_code`",
        "`human_handoff.agent_may_launch` 是唯一窄例外",
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

    hardening_concepts = (
        "HTTPS is required for remote API URLs",
        "explicit loopback HTTP",
        "Only GET requests are retried automatically",
        "authentication POST requests are single-submission",
        "compare-and-swap",
        "refresh single-flight",
        "lock timeout",
        "operating system releases the lock",
        "transient revoke failure preserves the local credential",
    )
    assert all(concept in guide for concept in hardening_concepts)


def test_readme_links_cli_discovery_and_transport_rules() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "dydata commands --json" in readme
    assert "dydata auth login" in readme
    assert "dydata auth login --browser" in readme
    assert "密码使用终端隐藏输入" in readme
    assert "HTTPS is required for remote API URLs" in readme
    assert "explicit loopback HTTP" in readme


def test_generated_reference_has_no_drift() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
