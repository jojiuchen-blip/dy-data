"""Execute the fixed dydata command registry without exposing generic actions."""

from __future__ import annotations

import argparse
import math
import sys
import time
import webbrowser
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, TextIO

from .client import CliError, DyDataClient
from .constants import CLI_SCHEMA_VERSION, CLI_VERSION
from .contracts import (
    ContractError,
    validate_auth_status,
    validate_follow_up_stats,
    validate_stores,
)
from .credentials import CredentialState, CredentialStore
from .output import emit_error, emit_json, render_aggregate_table
from .registry import command_catalog


_REFRESH_EARLY_SECONDS = 60
_AUTH_ERROR_CODES = {"AUTH_REQUIRED", "AUTH_EXPIRED"}


def execute_command(
    parsed: argparse.Namespace,
    *,
    credential_store: CredentialStore | None = None,
    client: DyDataClient | None = None,
    browser_open: Callable[[str], Any] = webbrowser.open,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    stream: TextIO | None = None,
) -> int:
    """Execute one parsed command and return its stable process exit code."""
    try:
        if parsed.command == "commands":
            emit_json(
                {
                    "ok": True,
                    "command": "commands",
                    "schema_version": CLI_SCHEMA_VERSION,
                    "data": {"commands": command_catalog()},
                },
                stream=stream,
            )
            return 0
        if parsed.command == "version":
            emit_json(
                {
                    "ok": True,
                    "command": "version",
                    "schema_version": CLI_SCHEMA_VERSION,
                    "data": {
                        "cli_version": CLI_VERSION,
                        "schema_version": CLI_SCHEMA_VERSION,
                    },
                },
                stream=stream,
            )
            return 0

        store = credential_store or CredentialStore()
        api_client = client or DyDataClient()
        if parsed.command == "auth.login":
            return _login(
                store,
                api_client,
                browser_open=browser_open,
                sleep=sleep,
                stream=stream,
            )
        if parsed.command == "auth.logout":
            return _logout(store, api_client, stream=stream)

        access_token = _usable_access_token(
            store,
            api_client,
            now=now(),
        )
        if parsed.command == "auth.status":
            response = _protected_call(
                store, lambda: api_client.auth_status(access_token)
            )
            emit_json(_validated(response, validate_auth_status), stream=stream)
            return 0
        if parsed.command == "stores.list":
            response = _protected_call(
                store, lambda: api_client.list_stores(access_token)
            )
            emit_json(_validated(response, validate_stores), stream=stream)
            return 0
        if parsed.command == "clues.follow-up-stats":
            response = _protected_call(
                store,
                lambda: api_client.follow_up_stats(
                    access_token,
                    date_from=parsed.date_from,
                    date_to=parsed.date_to,
                    store_ids=parsed.store_ids,
                ),
            )
            response = _validated(response, validate_follow_up_stats)
            if parsed.output == "json":
                emit_json(response, stream=stream)
            else:
                rows = response.get("data", {}).get("stores", [])
                if not isinstance(rows, list):
                    raise CliError("SCHEMA_MISMATCH")
                target = stream or sys.stdout
                target.write(f"{render_aggregate_table(rows)}\n")
            return 0
        raise CliError("INVALID_ARGUMENT")
    except CliError as exc:
        return emit_error(
            parsed.command,
            exc.code,
            str(exc),
            retryable=exc.retryable,
            request_id=exc.request_id,
            stream=stream,
        )
    except Exception:
        return emit_error(
            parsed.command,
            "INTERNAL_ERROR",
            "The command could not be completed.",
            stream=stream,
        )


def _login(
    store: CredentialStore,
    client: DyDataClient,
    *,
    browser_open: Callable[[str], Any],
    sleep: Callable[[float], None],
    stream: TextIO | None,
) -> int:
    start = client.start_device_authorization()
    device_code = _required_text(start, "device_code")
    user_code = _required_text(start, "user_code")
    verification_uri = _required_text(start, "verification_uri_complete")
    expires_in = _required_positive_integer(start, "expires_in")
    interval = _required_positive_integer(start, "interval")
    target = stream or sys.stdout
    target.write(f"Open: {verification_uri}\n")
    target.write(f"Code: {user_code}\n")
    browser_open(verification_uri)

    poll_count = max(1, math.ceil(expires_in / interval))
    for poll_index in range(poll_count):
        response = client.poll_device_token(device_code)
        if response.get("status") == "authorization_pending":
            if poll_index + 1 < poll_count:
                sleep(interval)
            continue
        state = _credential_state_from_response(response)
        store.save(state)
        target.write("Authorization complete.\n")
        return 0
    raise CliError("AUTH_EXPIRED")


def _logout(
    store: CredentialStore,
    client: DyDataClient,
    *,
    stream: TextIO | None,
) -> int:
    revoke_confirmed = True
    try:
        state = store.load()
        if state is not None:
            client.revoke(state.refresh_token)
    except Exception:
        revoke_confirmed = False
    finally:
        store.clear()
    target = stream or sys.stdout
    if revoke_confirmed:
        target.write("Logged out.\n")
    else:
        target.write("Local credentials cleared; server revocation was not confirmed.\n")
    return 0


def _usable_access_token(
    store: CredentialStore,
    client: DyDataClient,
    *,
    now: datetime,
) -> str:
    state = store.load()
    if state is None:
        raise CliError("AUTH_REQUIRED")
    expires_at = state.access_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    refresh_at = now.astimezone(timezone.utc) + timedelta(
        seconds=_REFRESH_EARLY_SECONDS
    )
    if expires_at.astimezone(timezone.utc) > refresh_at:
        return state.access_token
    try:
        refreshed = client.refresh(state.refresh_token)
        new_state = _credential_state_from_response(refreshed)
        store.save(new_state)
    except Exception:
        store.clear()
        raise
    return new_state.access_token


def _protected_call(
    store: CredentialStore,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        return operation()
    except CliError as exc:
        if exc.code in _AUTH_ERROR_CODES:
            store.clear()
        raise


def _credential_state_from_response(response: dict[str, Any]) -> CredentialState:
    access_token = _required_text(response, "access_token")
    refresh_token = _required_text(response, "refresh_token")
    expires_at_text = _required_text(response, "access_token_expires_at")
    try:
        expires_at = datetime.fromisoformat(expires_at_text.replace("Z", "+00:00"))
    except ValueError:
        raise CliError("SCHEMA_MISMATCH") from None
    if expires_at.tzinfo is None:
        raise CliError("SCHEMA_MISMATCH")
    return CredentialState(
        access_token=access_token,
        access_token_expires_at=expires_at,
        refresh_token=refresh_token,
    )


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise CliError("SCHEMA_MISMATCH")
    return value


def _required_positive_integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CliError("SCHEMA_MISMATCH")
    return value


def _validated(
    response: dict[str, Any],
    validator: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    try:
        return validator(response)
    except ContractError:
        raise CliError("SCHEMA_MISMATCH") from None
