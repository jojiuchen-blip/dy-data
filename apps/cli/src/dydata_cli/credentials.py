"""Store CLI credentials exclusively in the operating-system keyring."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tempfile
import time
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Protocol

import keyring


_UNSET = object()


class _InterProcessFileLock:
    """Small cross-platform exclusive file lock containing no credentials."""

    def __init__(self, path: Path, *, timeout: float = 10.0) -> None:
        self._path = path
        self._timeout = timeout
        self._handle = None

    def __enter__(self) -> "_InterProcessFileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise RuntimeError("Credential lock is unavailable") from None
                time.sleep(0.05)
        self._handle = handle
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None


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

    def __init__(
        self,
        *,
        keyring_backend: KeyringBackend | None = None,
        lock_path: Path | None = None,
        lock_timeout: float = 30.0,
    ) -> None:
        self._keyring = keyring_backend or keyring
        self._lock_path = lock_path or (
            Path(tempfile.gettempdir()) / "dydata-cli" / "credentials.lock"
        )
        self._lock_timeout = lock_timeout

    @contextmanager
    def _locked(self) -> Iterator["_LockedCredentialStore"]:
        """Hold the process lock across a complete credential operation cycle."""
        with _InterProcessFileLock(
            self._lock_path, timeout=self._lock_timeout
        ):
            yield _LockedCredentialStore(self)

    def load(self) -> CredentialState | None:
        """Load the current credential state, clearing malformed data."""
        with self._locked() as locked:
            return locked.load()

    def save(
        self,
        state: CredentialState,
        *,
        expected: CredentialState | None | object = _UNSET,
    ) -> bool:
        """Replace credentials only when the observed state still matches."""
        with self._locked() as locked:
            return locked.save(state, expected=expected)

    def clear(
        self, *, expected: CredentialState | None | object = _UNSET
    ) -> bool:
        """Compare-and-delete credentials without removing a newer state."""
        with self._locked() as locked:
            return locked.clear(expected=expected)

    @staticmethod
    def _serialize(state: CredentialState) -> str:
        return json.dumps(
            {
                "access_token": state.access_token,
                "access_token_expires_at": state.access_token_expires_at.isoformat(),
                "refresh_token": state.refresh_token,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _expected_raw(cls, expected: CredentialState | None | object) -> str | None:
        if expected is None:
            return None
        if not isinstance(expected, CredentialState):
            raise TypeError("expected credential state is invalid")
        return cls._serialize(expected)

    @staticmethod
    def _deserialize(raw_state: str) -> CredentialState | None:
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
            expires_at = datetime.fromisoformat(
                expires_at_text.replace("Z", "+00:00")
            )
            if expires_at.tzinfo is None:
                raise ValueError("timezone-aware expiry is required")
            return CredentialState(
                access_token=access_token,
                access_token_expires_at=expires_at,
                refresh_token=refresh_token,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None


class _LockedCredentialStore:
    """Credential operations that assume the owning OS lock is already held."""

    def __init__(self, store: CredentialStore) -> None:
        self._store = store

    def load(self) -> CredentialState | None:
        raw_state = self._store._keyring.get_password(
            self._store.service, self._store.account
        )
        if raw_state is None:
            return None
        state = self._store._deserialize(raw_state)
        if state is None:
            self._store._keyring.delete_password(
                self._store.service, self._store.account
            )
        return state

    def save(
        self,
        state: CredentialState,
        *,
        expected: CredentialState | None | object = _UNSET,
    ) -> bool:
        current = self._store._keyring.get_password(
            self._store.service, self._store.account
        )
        if expected is not _UNSET and current != self._store._expected_raw(expected):
            return False
        self._store._keyring.set_password(
            self._store.service,
            self._store.account,
            self._store._serialize(state),
        )
        return True

    def clear(
        self, *, expected: CredentialState | None | object = _UNSET
    ) -> bool:
        current = self._store._keyring.get_password(
            self._store.service, self._store.account
        )
        if expected is not _UNSET and current != self._store._expected_raw(expected):
            return False
        if current is None:
            return False
        self._store._keyring.delete_password(
            self._store.service, self._store.account
        )
        return True
