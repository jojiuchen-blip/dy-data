"""Deployment guard for the fixed DYDATA-45 test Agent environment."""

from __future__ import annotations

import os

from apps.cli.src.dydata_cli.environments import TEST_ENVIRONMENT


def validate_agent_environment() -> None:
    """Fail startup when an explicitly configured image drifts from test."""
    configured = os.getenv("DY_AGENT_ENVIRONMENT")
    if configured is None:
        return
    if configured.strip() != TEST_ENVIRONMENT.name:
        raise RuntimeError(
            "DY_AGENT_ENVIRONMENT must remain test until DYDATA-46 production cutover"
        )
    web_base_url = os.getenv("DY_WEB_BASE_URL", "").strip().rstrip("/")
    if web_base_url != TEST_ENVIRONMENT.web_url:
        raise RuntimeError(
            f"DY_WEB_BASE_URL must be {TEST_ENVIRONMENT.web_url} in the test Agent environment"
        )
