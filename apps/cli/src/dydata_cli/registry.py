"""The single source of truth for public CLI commands and their metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .constants import ERROR_EXIT_CODES


_COMMAND_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "command": "commands",
        "purpose": "Discover every supported CLI command and its agent contract.",
        "parameters": [{"name": "--json", "required": True, "type": "flag"}],
        "api": [],
        "mcp": None,
        "roles": ["all"],
        "data_scope": "none",
        "side_effect": "none",
        "business_side_effect": "none",
        "risk_level": "low",
        "agent_callable": True,
        "confirmation": "none",
        "output_mode": "json",
        "output_schema": {"data": {"commands": "Command[]"}},
        "sensitive_data": "none",
        "examples": ["dydata commands --json"],
        "errors": ["INTERNAL_ERROR"],
    },
    {
        "command": "auth.login",
        "purpose": (
            "Let a human sign in through secure terminal input, with an "
            "explicit browser fallback."
        ),
        "parameters": [
            {
                "name": "--browser",
                "required": False,
                "type": "flag",
                "default": False,
            }
        ],
        "api": [
            {"path": "/api/v1/auth/cli/device/start", "operation": "device_start"},
            {"path": "/api/v1/auth/cli/device/approve", "operation": "device_approve"},
            {"path": "/api/v1/auth/cli/device/token", "operation": "device_exchange"},
        ],
        "mcp": None,
        "roles": ["all"],
        "data_scope": "none",
        "side_effect": "remote_auth_grant_and_local_credential",
        "business_side_effect": "none",
        "risk_level": "medium",
        "agent_callable": False,
        "confirmation": "human_secure_tty_or_browser",
        "human_handoff": {
            "agent_may_launch": True,
            "agent_must_not_supply_credentials": True,
            "browser_fallback": "dydata auth login --browser",
            "default_mode": "secure_terminal",
            "requires_explicit_user_request": True,
            "requires_user_input": True,
        },
        "output_mode": "text",
        "output_schema": {
            "mode": "text",
            "variants": {
                "terminal": [
                    "Signed in as: <username>",
                    "Role: <role>",
                    "Store scope: <scope>",
                    "Authorization complete.",
                ],
                "browser": [
                    "Open: <url>",
                    "Code: <user_code>",
                    "Authorization complete.",
                ],
                "existing_credential": [
                    "A local CLI credential already exists. Run `dydata auth logout` before signing in as another account."
                ],
            },
        },
        "sensitive_data": "human_entered_credential",
        "examples": ["dydata auth login", "dydata auth login --browser"],
        "errors": [
            "INTERACTIVE_REQUIRED",
            "AUTH_FAILED",
            "AUTH_REQUIRED",
            "AUTH_EXPIRED",
            "INVALID_ARGUMENT",
            "API_UNAVAILABLE",
            "RATE_LIMITED",
            "SCHEMA_MISMATCH",
            "INTERNAL_ERROR",
        ],
    },
    {
        "command": "auth.logout",
        "purpose": "Revoke the refresh family and remove the observed local credential.",
        "parameters": [],
        "api": [
            {"path": "/api/v1/auth/cli/revoke", "operation": "revoke"},
        ],
        "mcp": None,
        "roles": ["all"],
        "data_scope": "none",
        "side_effect": "remote_auth_revoke_and_local_credential",
        "business_side_effect": "none",
        "risk_level": "low",
        "agent_callable": False,
        "confirmation": "interactive",
        "output_mode": "text",
        "output_schema": {"mode": "text", "lines": ["Logged out."]},
        "sensitive_data": "credential",
        "examples": ["dydata auth logout"],
        "errors": [
            "API_UNAVAILABLE",
            "RATE_LIMITED",
            "SCHEMA_MISMATCH",
            "INTERNAL_ERROR",
        ],
    },
    {
        "command": "auth.status",
        "purpose": "Report whether a locally stored CLI credential is usable.",
        "parameters": [{"name": "--json", "required": True, "type": "flag"}],
        "api": [
            {
                "path": "/api/v1/auth/cli/token/refresh",
                "operation": "refresh",
                "command": "auth.refresh",
            },
            {"path": "/api/v1/cli/auth/status", "operation": "auth_status"},
        ],
        "mcp": None,
        "roles": ["all"],
        "data_scope": "current_identity",
        "side_effect": "auth_refresh_possible",
        "business_side_effect": "none",
        "risk_level": "low",
        "agent_callable": True,
        "confirmation": "none",
        "output_mode": "json",
        "output_schema": {"data": {"authenticated": "boolean", "expires_at": "datetime"}},
        "sensitive_data": "credential_metadata",
        "examples": ["dydata auth status --json"],
        "errors": [
            "AUTH_REQUIRED",
            "AUTH_EXPIRED",
            "API_UNAVAILABLE",
            "RATE_LIMITED",
            "SCHEMA_MISMATCH",
            "INTERNAL_ERROR",
        ],
    },
    {
        "command": "stores.list",
        "purpose": "List stores available within the caller's data scope.",
        "parameters": [{"name": "--json", "required": True, "type": "flag"}],
        "api": [
            {"path": "/api/v1/cli/stores", "operation": "stores_list"},
        ],
        "mcp": {"tool": "stores_list", "read_only": True, "arguments": {}},
        "roles": ["store", "admin", "highest_admin"],
        "data_scope": "authorized_stores",
        "side_effect": "auth_refresh_possible",
        "business_side_effect": "none",
        "risk_level": "low",
        "agent_callable": True,
        "confirmation": "none",
        "output_mode": "json",
        "output_schema": {"data": {"stores": "Store[]"}},
        "sensitive_data": "store_identity",
        "examples": ["dydata stores list --json"],
        "errors": [
            "AUTH_REQUIRED",
            "AUTH_EXPIRED",
            "SCOPE_DENIED",
            "API_UNAVAILABLE",
            "RATE_LIMITED",
            "SCHEMA_MISMATCH",
            "INTERNAL_ERROR",
        ],
    },
    {
        "command": "clues.follow-up-stats",
        "purpose": "Summarize clue follow-up results for authorized stores.",
        "parameters": [
            {
                "name": "--from",
                "dest": "date_from_text",
                "normalized_dest": "date_from",
                "required": False,
                "type": "YYYY-MM-DD",
            },
            {
                "name": "--to",
                "dest": "date_to_text",
                "normalized_dest": "date_to",
                "required": False,
                "type": "YYYY-MM-DD",
            },
            {
                "name": "--store-id",
                "dest": "store_ids",
                "required": False,
                "repeatable": True,
                "type": "string",
            },
            {
                "name": "--output",
                "required": False,
                "type": "json|table",
                "choices": ["json", "table"],
                "default": "json",
            },
        ],
        "api": [
            {
                "path": "/api/v1/clues/store-follow-up-summary",
                "operation": "follow_up_stats",
            },
        ],
        "mcp": {
            "tool": "clues_follow_up_stats",
            "read_only": True,
            "arguments": {
                "date_from": "assigned_date_start",
                "date_to": "assigned_date_end",
                "store_ids": "store_ids",
            },
        },
        "date_range": {
            "start": "--from",
            "end": "--to",
            "default_days": 7,
            "max_inclusive_days": 366,
        },
        "roles": ["store", "admin", "highest_admin"],
        "data_scope": "authorized_stores",
        "side_effect": "auth_refresh_possible",
        "business_side_effect": "none",
        "risk_level": "low",
        "agent_callable": True,
        "confirmation": "none",
        "output_mode": "json_or_table",
        "output_schema": {"data": {"stores": "FollowUpStats[]", "totals": "FollowUpStats"}},
        "sensitive_data": "store_metrics",
        "examples": [
            "dydata clues follow-up-stats",
            "dydata clues follow-up-stats --from 2026-07-01 --to 2026-07-07 --store-id store-a --output table",
        ],
        "errors": [
            "AUTH_REQUIRED",
            "AUTH_EXPIRED",
            "SCOPE_DENIED",
            "INVALID_ARGUMENT",
            "API_UNAVAILABLE",
            "RATE_LIMITED",
            "SCHEMA_MISMATCH",
            "INTERNAL_ERROR",
        ],
    },
    {
        "command": "agent.doctor",
        "purpose": "Diagnose the fixed Agent manifest, MCP metadata, and local authorization state.",
        "parameters": [{"name": "--json", "required": True, "type": "flag"}],
        "api": [],
        "mcp": None,
        "roles": ["all"],
        "data_scope": "current_identity_and_authorized_stores",
        "side_effect": "auth_refresh_possible",
        "business_side_effect": "none",
        "risk_level": "low",
        "agent_callable": True,
        "confirmation": "none",
        "output_mode": "json",
        "output_schema": {
            "data": {
                "checks": "DiagnosticCheck[]",
                "credential": "CredentialDiagnostic",
                "next_action": "string",
            }
        },
        "sensitive_data": "credential_metadata_and_store_identity",
        "examples": ["dydata agent doctor --json"],
        "errors": [
            "AUTH_EXPIRED",
            "API_UNAVAILABLE",
            "RATE_LIMITED",
            "SCHEMA_MISMATCH",
            "INTERNAL_ERROR",
        ],
    },
    {
        "command": "version",
        "purpose": "Report the installed CLI and schema versions.",
        "parameters": [{"name": "--json", "required": True, "type": "flag"}],
        "api": [],
        "mcp": None,
        "roles": ["all"],
        "data_scope": "none",
        "side_effect": "none",
        "business_side_effect": "none",
        "risk_level": "low",
        "agent_callable": True,
        "confirmation": "none",
        "output_mode": "json",
        "output_schema": {"data": {"cli_version": "string", "schema_version": "string"}},
        "sensitive_data": "none",
        "examples": ["dydata version --json"],
        "errors": ["INTERNAL_ERROR"],
    },
)


def command_catalog() -> list[dict[str, Any]]:
    """Return a copy so callers cannot mutate the authoritative registry."""
    catalog = deepcopy(list(_COMMAND_CATALOG))
    for item in catalog:
        item["exit_codes"] = {
            code: ERROR_EXIT_CODES[code] for code in item["errors"]
        }
    return catalog


def api_command_mappings() -> tuple[dict[str, str], dict[str, str]]:
    """Build API command and audit-operation maps from the command registry."""
    commands: dict[str, str] = {}
    operations: dict[str, str] = {}
    for item in _COMMAND_CATALOG:
        for binding in item["api"]:
            path = binding["path"]
            if path in commands:
                raise ValueError(f"Duplicate API binding: {path}")
            commands[path] = binding.get("command", item["command"])
            operations[path] = binding["operation"]
    return commands, operations


def mcp_capability_catalog() -> list[dict[str, Any]]:
    """Return the fixed read-only MCP tool bindings in stable order."""
    capabilities: list[dict[str, Any]] = []
    seen_tools: set[str] = set()
    for item in _COMMAND_CATALOG:
        binding = item["mcp"]
        if binding is None:
            continue
        command = str(item["command"])
        if item.get("agent_callable") is not True:
            raise ValueError(f"MCP binding {command} must be agent-callable")
        if item.get("business_side_effect") != "none":
            raise ValueError(f"MCP binding {command} must be side-effect-free")
        if not isinstance(binding, dict) or binding.get("read_only") is not True:
            raise ValueError(f"MCP binding {command} must be read-only")
        tool = binding.get("tool")
        arguments = binding.get("arguments")
        if not isinstance(tool, str) or not tool or tool in seen_tools:
            raise ValueError(f"MCP binding {command} has an invalid or duplicate tool")
        if not isinstance(arguments, dict) or not all(
            isinstance(source, str)
            and source
            and not source.startswith("-")
            and isinstance(target, str)
            and target
            for source, target in arguments.items()
        ):
            raise ValueError(f"MCP binding {command} has an invalid argument mapping")
        if len(set(arguments.values())) != len(arguments):
            raise ValueError(f"MCP binding {command} has duplicate argument targets")
        seen_tools.add(tool)
        capabilities.append(
            {
                "command": command,
                "tool": tool,
                "read_only": True,
                "arguments": deepcopy(arguments),
            }
        )
    return sorted(capabilities, key=lambda item: item["tool"])
