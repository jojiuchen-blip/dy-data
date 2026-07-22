from __future__ import annotations

import json
from datetime import datetime, timezone
import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dydata_cli.credentials import CredentialState, CredentialStore


class ProcessKeyring:
    def __init__(self, values) -> None:
        self.values = values

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


class ProcessRefreshClient:
    def __init__(self, refresh_count) -> None:
        self.refresh_count = refresh_count

    def refresh(self, refresh_token: str):
        assert refresh_token == "old-refresh-secret"
        with self.refresh_count.get_lock():
            self.refresh_count.value += 1
        time.sleep(0.4)
        return {
            "access_token": "winner-access-secret",
            "refresh_token": "winner-refresh-secret",
            "access_token_expires_at": "2026-07-21T13:00:00Z",
        }


def _refresh_worker(values, lock_path, refresh_count, start, results) -> None:
    from dydata_cli.commands import _usable_access_token

    store = CredentialStore(
        keyring_backend=ProcessKeyring(values), lock_path=Path(lock_path)
    )
    start.wait(5)
    try:
        token, _ = _usable_access_token(
            store,
            ProcessRefreshClient(refresh_count),
            now=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
        )
        results.put(("ok", token))
    except Exception as exc:  # pragma: no cover - failure detail crosses process.
        results.put(("error", type(exc).__name__))


def _crash_with_credential_lock(lock_path: str, ready) -> None:
    from dydata_cli.credentials import _InterProcessFileLock

    with _InterProcessFileLock(Path(lock_path), timeout=2):
        ready.set()
        os._exit(0)


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def credential_state() -> CredentialState:
    return CredentialState(
        access_token="access-secret",
        access_token_expires_at=datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc),
        refresh_token="refresh-secret",
    )


def test_credential_store_uses_one_keyring_json_value() -> None:
    keyring = FakeKeyring()
    store = CredentialStore(keyring_backend=keyring)

    store.save(credential_state())

    assert set(keyring.values) == {("dydata-cli", "default")}
    payload = json.loads(keyring.values[("dydata-cli", "default")])
    assert payload == {
        "access_token": "access-secret",
        "access_token_expires_at": "2026-07-21T12:30:00+00:00",
        "refresh_token": "refresh-secret",
    }
    assert store.load() == credential_state()


def test_credential_store_clear_removes_only_keyring_value() -> None:
    keyring = FakeKeyring()
    store = CredentialStore(keyring_backend=keyring)
    store.save(credential_state())

    store.clear()

    assert store.load() is None


def test_credential_store_clears_invalid_state_without_echoing_it() -> None:
    keyring = FakeKeyring()
    keyring.values[("dydata-cli", "default")] = "not-json-access-secret"
    store = CredentialStore(keyring_backend=keyring)

    assert store.load() is None
    assert keyring.values == {}


def test_credential_state_repr_never_contains_tokens() -> None:
    rendered = repr(credential_state())

    assert "access-secret" not in rendered
    assert "refresh-secret" not in rendered
    assert "redacted" in rendered.lower()


def test_compare_and_delete_does_not_remove_a_newer_credential() -> None:
    keyring = FakeKeyring()
    store = CredentialStore(keyring_backend=keyring)
    original = credential_state()
    newer = CredentialState(
        access_token="new-access-secret",
        access_token_expires_at=datetime(2026, 7, 21, 13, 0, tzinfo=timezone.utc),
        refresh_token="new-refresh-secret",
    )
    store.save(original)
    store.save(newer)

    removed = store.clear(expected=original)

    assert removed is False
    assert store.load() == newer


def test_compare_and_save_only_replaces_the_observed_credential() -> None:
    keyring = FakeKeyring()
    store = CredentialStore(keyring_backend=keyring)
    original = credential_state()
    concurrently_saved = CredentialState(
        access_token="parallel-access-secret",
        access_token_expires_at=datetime(2026, 7, 21, 13, 0, tzinfo=timezone.utc),
        refresh_token="parallel-refresh-secret",
    )
    replacement = CredentialState(
        access_token="replacement-access-secret",
        access_token_expires_at=datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc),
        refresh_token="replacement-refresh-secret",
    )
    store.save(original)
    store.save(concurrently_saved)

    replaced = store.save(replacement, expected=original)

    assert replaced is False
    assert store.load() == concurrently_saved


class BlockingKeyring(FakeKeyring):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def set_password(self, service: str, account: str, value: str) -> None:
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            super().set_password(service, account, value)
        finally:
            with self.guard:
                self.active -= 1


def test_two_store_instances_serialize_keyring_writes_with_shared_process_lock(
    tmp_path: Path,
) -> None:
    keyring = BlockingKeyring()
    lock_path = tmp_path / "credentials.lock"
    first = CredentialStore(keyring_backend=keyring, lock_path=lock_path)
    second = CredentialStore(keyring_backend=keyring, lock_path=lock_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(store.save, credential_state())
            for store in (first, second)
        ]
        for future in futures:
            future.result()

    assert keyring.max_active == 1


def test_expired_refresh_is_single_flight_across_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    lock_path = tmp_path / "credentials.lock"
    with context.Manager() as manager:
        values = manager.dict()
        store = CredentialStore(
            keyring_backend=ProcessKeyring(values), lock_path=lock_path
        )
        store.save(
            CredentialState(
                access_token="old-access-secret",
                access_token_expires_at=datetime(
                    2026, 7, 21, 11, 59, tzinfo=timezone.utc
                ),
                refresh_token="old-refresh-secret",
            )
        )
        refresh_count = context.Value("i", 0)
        start = context.Event()
        results = context.Queue()
        workers = [
            context.Process(
                target=_refresh_worker,
                args=(values, str(lock_path), refresh_count, start, results),
            )
            for _ in range(2)
        ]
        for worker in workers:
            worker.start()
        start.set()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0

        outcomes = [results.get(timeout=2) for _ in workers]

    assert outcomes == [
        ("ok", "winner-access-secret"),
        ("ok", "winner-access-secret"),
    ]
    assert refresh_count.value == 1
    assert b"secret" not in lock_path.read_bytes().lower()


def test_credential_lock_is_released_when_owner_process_crashes(
    tmp_path: Path,
) -> None:
    from dydata_cli.credentials import _InterProcessFileLock

    context = multiprocessing.get_context("spawn")
    lock_path = tmp_path / "credentials.lock"
    ready = context.Event()
    worker = context.Process(
        target=_crash_with_credential_lock,
        args=(str(lock_path), ready),
    )
    worker.start()
    assert ready.wait(5)
    worker.join(5)
    assert worker.exitcode == 0

    with _InterProcessFileLock(lock_path, timeout=2):
        pass
    assert b"secret" not in lock_path.read_bytes().lower()
