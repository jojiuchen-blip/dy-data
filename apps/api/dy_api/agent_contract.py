"""Public, generated Agent discovery contracts for the test environment."""

from __future__ import annotations

from typing import Any

from apps.cli.src.dydata_cli.constants import CLI_SCHEMA_VERSION, CLI_VERSION
from apps.cli.src.dydata_cli.environments import TEST_ENVIRONMENT
from apps.cli.src.dydata_cli.registry import command_catalog, mcp_capability_catalog


AGENT_MANIFEST_VERSION = "1.0"
AGENT_CAPABILITY_SCHEMA_VERSION = "1.0"
CLI_INSTALL_SPEC = (
    "git+https://github.com/jojiuchen-blip/dy-data.git@main#subdirectory=apps/cli"
)


def agent_manifest() -> dict[str, Any]:
    """Build the stable machine entrypoint from fixed environment constants."""
    base_url = TEST_ENVIRONMENT.web_url
    return {
        "name": "dydata-agent",
        "manifest_version": AGENT_MANIFEST_VERSION,
        "environment": TEST_ENVIRONMENT.name,
        "read_only": True,
        "service": {
            "base_url": base_url,
            "capabilities_url": f"{base_url}/api/v1/agent/capabilities",
            "agent_guide_url": f"{base_url}/agent.md",
            "skill_url": f"{base_url}/agent/SKILL.md",
        },
        "cli": {
            "version": CLI_VERSION,
            "schema_version": CLI_SCHEMA_VERSION,
            "install_spec": CLI_INSTALL_SPEC,
            "discovery_command": "dydata commands --json",
            "doctor_command": "dydata agent doctor --json",
        },
        "mcp": {
            "url": TEST_ENVIRONMENT.mcp_url,
            "transport": "streamable-http",
            "oauth_issuer": base_url,
            "protected_resource_metadata": (
                f"{base_url}/.well-known/oauth-protected-resource/mcp"
            ),
        },
        "authorization": {
            "user_handoff_required": True,
            "agent_must_not_handle_credentials": True,
            "scope": "mcp:read",
        },
    }


def agent_capabilities() -> dict[str, Any]:
    """Build the Agent capability list from the authoritative CLI registry."""
    commands = {item["command"]: item for item in command_catalog()}
    capabilities = [
        {
            "command": binding["command"],
            "mcp_tool": binding["tool"],
            "purpose": commands[binding["command"]]["purpose"],
            "data_scope": commands[binding["command"]]["data_scope"],
            "business_side_effect": commands[binding["command"]][
                "business_side_effect"
            ],
        }
        for binding in mcp_capability_catalog()
    ]
    return {
        "schema_version": AGENT_CAPABILITY_SCHEMA_VERSION,
        "environment": TEST_ENVIRONMENT.name,
        "read_only": True,
        "capabilities": capabilities,
    }


def render_agent_guide() -> str:
    """Render the shortest platform-neutral Agent decision flow."""
    manifest_url = f"{TEST_ENVIRONMENT.web_url}/.well-known/dydata-agent.json"
    capabilities_url = f"{TEST_ENVIRONMENT.web_url}/api/v1/agent/capabilities"
    tools = ", ".join(
        f"`{item['tool']}`" for item in mcp_capability_catalog()
    )
    return f"""# dydata Agent 接入

环境：`test`，即当前已部署的腾讯云测试环境。本服务只提供只读查询。企业内网生产服务器尚未部署，在 DYDATA-46 完成切换前不得尝试或声称存在可用的 `production` 入口。

1. 先读取机器清单：{manifest_url}
2. 支持远程 MCP 时，添加 `{TEST_ENVIRONMENT.mcp_url}`，由用户在 dydata 官方页面完成 OAuth 授权。
3. 需要 CLI fallback 时，按清单的 `cli.install_spec` 安装，再执行 `dydata agent doctor --json`。
4. CLI 尚未授权时，只能在用户明确要求后启动 `dydata auth login` 或 `dydata auth login --browser`，并立即把终端或浏览器交还用户。
5. 每次调用前读取能力清单：{capabilities_url}；当前 MCP 工具仅为 {tools}。

安全边界：不得索取、读取、转发或保存用户的账号、密码、Cookie 或 Token。不得猜测未声明命令、扩大门店范围或调用写操作。
"""


def render_agent_skill() -> str:
    """Render a generic Markdown Skill that references machine contracts."""
    manifest_url = f"{TEST_ENVIRONMENT.web_url}/.well-known/dydata-agent.json"
    capabilities_url = f"{TEST_ENVIRONMENT.web_url}/api/v1/agent/capabilities"
    tools = "\n".join(
        f"- `{item['tool']}` -> `{item['command']}`"
        for item in mcp_capability_catalog()
    )
    return f"""---
name: dydata-read-only
description: 查询当前账号授权门店及门店线索跟进统计。
---

# dydata read-only Agent Skill

## Source of truth

- Manifest: {manifest_url}
- Capabilities: {capabilities_url}
- MCP: {TEST_ENVIRONMENT.mcp_url}
- CLI diagnostic: `dydata agent doctor --json`

当前端点属于腾讯云测试环境。企业内网生产服务器尚未部署；在 DYDATA-46 完成整体切换前，不得把当前地址当作 `production`，也不得猜测生产入口。

## Allowed tools

{tools}

## Workflow

先读取 manifest 和 capabilities。支持 MCP 时优先连接 manifest 中的 MCP URL，并让用户在官方页面授权；否则使用 CLI fallback。先确认账号身份和 `stores_list` 范围，再查询 `clues_follow_up_stats`。

## Safety

不得索取、读取、转发或保存用户的账号、密码、Cookie 或 Token。不得使用未在 capabilities 中声明的能力，不得扩大门店或日期范围，不得执行写操作。
"""
