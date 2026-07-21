from __future__ import annotations

import json

from dydata_cli.docs import render_command_reference
from dydata_cli.main import main
from dydata_cli.registry import command_catalog


EXPECTED = {
    "commands",
    "auth.login",
    "auth.logout",
    "auth.status",
    "stores.list",
    "clues.follow-up-stats",
    "version",
}
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
        item["side_effect"] == "none"
        for item in catalog
        if item["command"].startswith(("stores.", "clues."))
    )
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
