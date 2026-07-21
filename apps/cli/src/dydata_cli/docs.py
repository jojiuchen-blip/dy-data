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
        lines.extend(("", "### Output schema", "", f"`{_json(item['output_schema'])}`"))
        lines.extend(("", "### Errors", "", ", ".join(f"`{code}`" for code in item["errors"])))
        lines.extend(("", "### Examples", ""))
        lines.extend(f"`{example}`" for example in item["examples"])
    return "\n".join(lines) + "\n"
