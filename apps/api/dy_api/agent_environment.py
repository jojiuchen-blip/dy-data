"""Deployment guard for a registered dydata Agent environment."""

from __future__ import annotations

import os

from apps.cli.src.dydata_cli.environments import (
    EnvironmentConfig,
    EnvironmentConfigError,
    resolve_environment,
)


def current_agent_environment() -> EnvironmentConfig:
    """Return the registered Agent environment selected for this process."""
    configured = os.getenv("DY_AGENT_ENVIRONMENT")
    try:
        environment = resolve_environment(configured)
    except EnvironmentConfigError as exc:
        raise RuntimeError("DY_AGENT_ENVIRONMENT is not registered") from exc
    web_base_url = os.getenv("DY_WEB_BASE_URL", "").strip().rstrip("/")
    if web_base_url and web_base_url != environment.web_url:
        raise RuntimeError(
            f"DY_WEB_BASE_URL must be {environment.web_url} "
            f"in the {environment.name} Agent environment"
        )
    return environment


def validate_agent_environment() -> None:
    """Fail startup when Agent environment configuration is not registered."""
    current_agent_environment()
