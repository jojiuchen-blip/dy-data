"""Named dydata service environments and their credential identities."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


class EnvironmentConfigError(ValueError):
    """The requested named environment is not in the fixed registry."""


@dataclass(frozen=True)
class EnvironmentConfig:
    """Immutable endpoints and credential identity for one named environment."""

    name: str
    web_url: str
    api_url: str
    mcp_url: str

    @property
    def credential_account(self) -> str:
        """Return a keyring account isolated by name and server identity."""
        identity = self.web_url.rstrip("/").encode("utf-8")
        identity_hash = hashlib.sha256(identity).hexdigest()[:16]
        return f"env:{self.name}:{identity_hash}"


TEST_ENVIRONMENT = EnvironmentConfig(
    name="test",
    web_url="https://dy-business-engine.com",
    api_url="https://dy-business-engine.com/api/v1",
    mcp_url="https://dy-business-engine.com/mcp",
)

_ENVIRONMENTS = {TEST_ENVIRONMENT.name: TEST_ENVIRONMENT}


def resolve_environment(name: str | None = None) -> EnvironmentConfig:
    """Resolve a fixed environment name, defaulting to the test service."""
    selected = os.getenv("DYDATA_ENV", "test") if name is None else name
    normalized = selected.strip().lower()
    try:
        return _ENVIRONMENTS[normalized]
    except KeyError:
        raise EnvironmentConfigError("Unknown dydata environment") from None
