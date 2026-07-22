from __future__ import annotations

import json
import tomllib
from pathlib import Path

from dydata_cli.docs import render_command_reference
from dydata_cli.constants import CLI_VERSION, ERROR_EXIT_CODES
from dydata_cli.main import main
from dydata_cli.registry import (
    api_command_mappings,
    command_catalog,
    mcp_capability_catalog,
)


EXPECTED = {
    "agent.doctor",
    "commands",
    "auth.login",
    "auth.logout",
    "auth.status",
    "stores.list",
    "clues.follow-up-stats",
    "version",
}
ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FIELDS = {
    "command",
    "purpose",
    "parameters",
    "roles",
    "data_scope",
    "side_effect",
    "risk_level",
    "agent_callable",
    "confirmation",
    "output_schema",
    "sensitive_data",
    "examples",
    "errors",
    "exit_codes",
    "output_mode",
    "business_side_effect",
    "api",
    "mcp",
}


def test_registry_is_the_complete_agent_command_catalog() -> None:
    catalog = command_catalog()

    assert {item["command"] for item in catalog} == EXPECTED
    assert len(catalog) == len(EXPECTED)
    assert all(REQUIRED_FIELDS <= item.keys() for item in catalog)
    assert {
        item["command"] for item in catalog if not item["agent_callable"]
    } == {"auth.login", "auth.logout"}
    assert all(
        item["business_side_effect"] == "none"
        for item in catalog
        if item["command"].startswith(("stores.", "clues."))
    )
    assert not any("manager" in item["roles"] for item in catalog)
    login = next(item for item in catalog if item["command"] == "auth.login")
    assert login == {
        **login,
        "side_effect": "remote_auth_grant_and_local_credential",
        "business_side_effect": "none",
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
    }
    assert login["parameters"] == [
        {
            "name": "--browser",
            "required": False,
            "type": "flag",
            "default": False,
        }
    ]
    assert login["confirmation"] == "human_secure_tty_or_browser"
    assert login["human_handoff"] == {
        "agent_may_launch": True,
        "agent_must_not_supply_credentials": True,
        "browser_fallback": "dydata auth login --browser",
        "default_mode": "secure_terminal",
        "requires_explicit_user_request": True,
        "requires_user_input": True,
    }
    assert {"AUTH_FAILED", "INTERACTIVE_REQUIRED"} <= set(login["errors"])
    logout = next(item for item in catalog if item["command"] == "auth.logout")
    assert logout["side_effect"] == "remote_auth_revoke_and_local_credential"
    assert logout["output_mode"] == "text"
    assert logout["output_schema"] == {"mode": "text", "lines": ["Logged out."]}
    for item in catalog:
        assert item["exit_codes"] == {
            code: ERROR_EXIT_CODES[code] for code in item["errors"]
        }
    assert not any(
        forbidden in item["command"]
        for item in catalog
        for forbidden in ("http", "sql", "shell", "script")
    )


def test_reference_is_rendered_from_the_registry() -> None:
    reference = render_command_reference()

    for item in command_catalog():
        assert f"`{item['command']}`" in reference
        assert item["purpose"] in reference
        for example in item["examples"]:
            assert example in reference


def test_temporary_executable_fallback_is_declared_in_registry_and_catalog_json(
    capsys,
) -> None:
    offline_commands = {"commands", "version"}
    expected_temporary = {
        item["command"]
        for item in command_catalog()
        if item["command"] not in offline_commands
    }

    assert all(
        "INTERNAL_ERROR" in item["errors"]
        for item in command_catalog()
        if item["command"] in expected_temporary
    )

    assert main(["commands", "--json"]) == 0
    catalog_json = json.loads(capsys.readouterr().out)["data"]["commands"]
    assert {
        item["command"]
        for item in catalog_json
        if "INTERNAL_ERROR" in item["errors"]
    } >= expected_temporary
    assert all(item["exit_codes"] for item in catalog_json)


def test_reference_exposes_governance_and_exit_metadata() -> None:
    reference = render_command_reference()

    for heading in (
        "### Roles",
        "### Data scope",
        "### Side effects",
        "### Risk and confirmation",
        "### Sensitive data",
        "### Output mode and schema",
        "### Errors and exit codes",
    ):
        assert heading in reference
    assert "`manager`" not in reference
    assert "`SCHEMA_MISMATCH` | `6`" in reference
    assert "### Human handoff" in reference
    assert "dydata auth login --browser" in reference
    assert (
        "An Agent may launch this command only after an explicit user request"
        in reference
    )


def test_package_and_runtime_cli_versions_are_synchronized() -> None:
    package = tomllib.loads(
        (ROOT / "apps" / "cli" / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert CLI_VERSION == "0.3.0"
    assert package["project"]["version"] == CLI_VERSION


def test_windows_package_installs_iana_timezone_data() -> None:
    package = tomllib.loads(
        (ROOT / "apps" / "cli" / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert (
        "tzdata>=2025.2; platform_system == 'Windows'"
        in package["project"]["dependencies"]
    )


def test_registry_is_the_only_api_and_mcp_capability_map() -> None:
    command_by_path, operation_by_path = api_command_mappings()

    assert command_by_path == {
        "/api/v1/auth/cli/device/start": "auth.login",
        "/api/v1/auth/cli/device/approve": "auth.login",
        "/api/v1/auth/cli/device/token": "auth.login",
        "/api/v1/auth/cli/token/refresh": "auth.refresh",
        "/api/v1/auth/cli/revoke": "auth.logout",
        "/api/v1/cli/auth/status": "auth.status",
        "/api/v1/cli/stores": "stores.list",
        "/api/v1/clues/store-follow-up-summary": "clues.follow-up-stats",
    }
    assert set(command_by_path) == set(operation_by_path)
    assert mcp_capability_catalog() == [
        {
            "command": "clues.follow-up-stats",
            "tool": "clues_follow_up_stats",
            "read_only": True,
        },
        {
            "command": "stores.list",
            "tool": "stores_list",
            "read_only": True,
        },
    ]
