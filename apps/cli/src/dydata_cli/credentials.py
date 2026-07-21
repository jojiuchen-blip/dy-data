"""Store CLI credentials exclusively in the operating-system keyring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import keyring


class KeyringBackend(Protocol):
    """Minimal keyring interface used by the credential store."""

    def get_password(self, service: str, account: str) -> str | None: ...

    def set_password(self, service: str, account: str, value: str) -> None: ...

    def delete_password(self, service: str, account: str) -> None: ...


@dataclass(frozen=True, repr=False)
class CredentialState:
    """Short-lived access and rotating refresh credentials."""

    access_token: str
    access_token_expires_at: datetime
    refresh_token: str

    def __repr__(self) -> str:
        """Return a representation that never exposes credential material."""
        return "CredentialState(<redacted>)"


class CredentialStore:
    """Persist one atomic JSON credential state in the OS keyring."""

    service = "dydata-cli"
    account = "default"

    def __init__(self, *, keyring_backend: KeyringBackend | None = None) -> None:
        self._keyring = keyring_backend or keyring

    def load(self) -> CredentialState | None:
        """Load the current credential state, clearing malformed data."""
        raw_state = self._keyring.get_password(self.service, self.account)
        if raw_state is None:
            return None
        try:
            payload = json.loads(raw_state)
            access_token = payload["access_token"]
            expires_at_text = payload["access_token_expires_at"]
            refresh_token = payload["refresh_token"]
            if (
                not isinstance(access_token, str)
                or not access_token
                or not isinstance(expires_at_text, str)
                or not expires_at_text
                or not isinstance(refresh_token, str)
                or not refresh_token
            ):
                raise ValueError("invalid credential state")
            return CredentialState(
                access_token=access_token,
                access_token_expires_at=datetime.fromisoformat(
                    expires_at_text.replace("Z", "+00:00")
                ),
                refresh_token=refresh_token,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self.clear()
            return None

    def save(self, state: CredentialState) -> None:
        """Atomically replace the keyring value with a complete state."""
        payload = {
            "access_token": state.access_token,
            "access_token_expires_at": state.access_token_expires_at.isoformat(),
            "refresh_token": state.refresh_token,
        }
        self._keyring.set_password(
            self.service,
            self.account,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )

    def clear(self) -> None:
        """Remove the locally stored credential state when present."""
        if self._keyring.get_password(self.service, self.account) is not None:
            self._keyring.delete_password(self.service, self.account)
