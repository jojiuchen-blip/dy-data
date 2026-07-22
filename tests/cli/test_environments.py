from __future__ import annotations

import hashlib

import pytest

from dydata_cli.client import DyDataClient
from dydata_cli.environments import EnvironmentConfigError, resolve_environment


def test_default_environment_is_the_fixed_test_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DYDATA_ENV", raising=False)
    monkeypatch.setenv("DYDATA_API_URL", "https://attacker.example/api/v1")

    environment = resolve_environment()
    client = DyDataClient(environment=environment)

    assert environment.name == "test"
    assert environment.web_url == "https://dy-business-engine.com"
    assert environment.api_url == "https://dy-business-engine.com/api/v1"
    assert environment.mcp_url == "https://dy-business-engine.com/mcp"
    assert environment.credential_account == (
        "env:test:"
        + hashlib.sha256(b"https://dy-business-engine.com").hexdigest()[:16]
    )
    assert str(client._http.base_url) == "https://dy-business-engine.com/api/v1/"


def test_explicit_test_environment_wins_over_process_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DYDATA_ENV", "not-allowed")

    assert resolve_environment("test").name == "test"


@pytest.mark.parametrize("name", ["production", "prod", "dev", "custom", " "])
def test_unknown_environment_fails_closed(name: str) -> None:
    with pytest.raises(EnvironmentConfigError):
        resolve_environment(name)
