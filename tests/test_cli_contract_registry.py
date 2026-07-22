from __future__ import annotations

import inspect

from apps.api.dy_api import cli_contract
from apps.cli.src.dydata_cli.registry import api_command_mappings


def test_api_cli_contract_derives_path_maps_from_cli_registry() -> None:
    command_by_path, operation_by_path = api_command_mappings()

    assert cli_contract.CLI_COMMANDS_BY_PATH == command_by_path
    assert cli_contract.CLI_OPERATIONS_BY_PATH == operation_by_path
    source = inspect.getsource(cli_contract)
    assert '"/api/v1/auth/cli/device/start"' not in source
    assert '"/api/v1/clues/store-follow-up-summary"' not in source
