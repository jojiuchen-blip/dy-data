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
        if "human_handoff" in item:
            lines.extend(
                (
                    "",
                    "### Human handoff",
                    "",
                    (
                        "An Agent may launch this command only after an explicit "
                        "user request and must hand credential input to the user; "
                        "it is not autonomously agent-callable."
                    ),
                    "",
                    f"`{_json(item['human_handoff'])}`",
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
    lines.extend((
        "", "## Human product management console", "",
        "`dydata-products manage` is a separate, human-only command in the same package.",
        "It uses a fresh Web login cookie held in memory and requires a secure interactive terminal,",
        "item-by-item server preview and explicit typed confirmation. It does not use or expand",
        "the read-only `dydata` / Agent / MCP registry, token audience, capabilities or API allowlist.",
        "", "Supported changes: product lists, rule field patches, explicit business-authorized",
        "enable/disable, and product manager grants for full-scope administrators.",
        "`dydata-products shared-rule` previews and publishes the Jingcheng shared rule base.",
        "Explicitly authorized Jingcheng project maintainers can use that command without product grants.",
        "`dydata-products shared-rule-grants` lets full-scope administrators preview and replace maintainers.",
        "List/rule publication never automatically enables product routing.",
        "", "See [human product console](cli-human-products.md) for input files, selection,",
        "partial failure retry, audit receipts and credential handling.",
    ))
    return "\n".join(lines) + "\n"
