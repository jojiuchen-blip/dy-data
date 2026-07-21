"""Documentation rendered from the command registry, never a copied command list."""

from __future__ import annotations

import json
from typing import Any

from .constants import CLI_SCHEMA_VERSION, CLI_VERSION
from .registry import command_catalog


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_command_reference() -> str:
    """Render the command reference from the authoritative registry."""
    lines = [
        "# dydata command reference",
        "",
        f"CLI version: `{CLI_VERSION}`. Schema version: `{CLI_SCHEMA_VERSION}`.",
        "",
        "| Command | Purpose | Agent callable |",
        "| --- | --- | --- |",
    ]
    for item in command_catalog():
        lines.append(
            f"| `{item['command']}` | {item['purpose']} | {str(item['agent_callable']).lower()} |"
        )
    for item in command_catalog():
        lines.extend(("", f"## `{item['command']}`", "", item["purpose"], ""))
        lines.extend(("### Parameters", "", "| Name | Required | Type |", "| --- | --- | --- |"))
        parameters = item["parameters"] or [{"name": "None", "required": False, "type": "-"}]
        for parameter in parameters:
            lines.append(
                f"| `{parameter['name']}` | {str(parameter['required']).lower()} | `{parameter['type']}` |"
            )
        lines.extend(("", "### Roles", "", ", ".join(f"`{role}`" for role in item["roles"])))
        lines.extend(("", "### Data scope", "", f"`{item['data_scope']}`"))
        lines.extend(
            (
                "",
                "### Side effects",
                "",
                f"Authentication/local: `{item['side_effect']}`. Business data: `{item['business_side_effect']}`.",
            )
        )
        lines.extend(
            (
                "",
                "### Risk and confirmation",
                "",
                f"Risk: `{item['risk_level']}`. Confirmation: `{item['confirmation']}`. Agent callable: `{str(item['agent_callable']).lower()}`.",
            )
        )
        lines.extend(("", "### Sensitive data", "", f"`{item['sensitive_data']}`"))
        lines.extend(
            (
                "",
                "### Output mode and schema",
                "",
                f"Mode: `{item['output_mode']}`.",
                "",
                f"`{_json(item['output_schema'])}`",
            )
        )
        lines.extend(
            (
                "",
                "### Errors and exit codes",
                "",
                "| Error | Exit code |",
                "| --- | --- |",
            )
        )
        lines.extend(
            f"| `{code}` | `{item['exit_codes'][code]}` |" for code in item["errors"]
        )
        lines.extend(("", "### Examples", ""))
        lines.extend(f"`{example}`" for example in item["examples"])
    return "\n".join(lines) + "\n"
