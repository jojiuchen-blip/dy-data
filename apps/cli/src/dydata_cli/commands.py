"""Execute the fixed dydata command registry without exposing generic actions."""

from __future__ import annotations

import argparse
import getpass
import math
import sys
import time
import warnings
import webbrowser
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, TextIO

from .client import CliError, DyDataClient
from .constants import CLI_SCHEMA_VERSION, CLI_VERSION, ERROR_EXIT_CODES
from .contracts import (
    ContractError,
    validate_auth_status,
    validate_follow_up_stats,
    validate_stores,
)
from .credentials import CredentialState, CredentialStore
from .environments import EnvironmentConfig, resolve_environment
from .interactive_auth import InteractiveAuthSession, LoginIdentity
from .output import emit_error, emit_json, render_aggregate_table
from .registry import command_catalog


_REFRESH_EARLY_SECONDS = 60
_AUTH_ERROR_CODES = {"AUTH_REQUIRED", "AUTH_EXPIRED"}


def _standard_streams_are_tty() -> bool:
    streams = (sys.stdin, sys.stdout, sys.stderr)
    try:
        return all(stream.isatty() for stream in streams)
    except (AttributeError, OSError):
        return False


def execute_command(
    parsed: argparse.Namespace,
    *,
    credential_store: CredentialStore | None = None,
    client: DyDataClient | None = None,
    browser_open: Callable[[str], Any] = webbrowser.open,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    stream: TextIO | None = None,
    interactive_auth_factory: Callable[[], InteractiveAuthSession] = (
        InteractiveAuthSession
    ),
    text_input: Callable[[str], str] = input,
    password_input: Callable[[str], str] = getpass.getpass,
    is_interactive_terminal: Callable[[], bool] = _standard_streams_are_tty,
    environment: EnvironmentConfig | None = None,
) -> int:
    """Execute one parsed command and return its stable process exit code."""
    selected_environment = environment or resolve_environment()
    try:
        if parsed.command == "commands":
            emit_json(
                {
                    "ok": True,
                    "command": "commands",
                    "environment": selected_environment.name,
                    "schema_version": CLI_SCHEMA_VERSION,
                    "data": {"commands": command_catalog()},
                    "meta": {"channel": "cli"},
                },
                stream=stream,
            )
            return 0
        if parsed.command == "version":
            emit_json(
                {
                    "ok": True,
                    "command": "version",
                    "environment": selected_environment.name,
                    "schema_version": CLI_SCHEMA_VERSION,
                    "data": {
                        "cli_version": CLI_VERSION,
                        "schema_version": CLI_SCHEMA_VERSION,
                    },
                    "meta": {"channel": "cli"},
                },
                stream=stream,
            )
            return 0

        store = credential_store or CredentialStore(environment=selected_environment)
        api_client = client or DyDataClient(environment=selected_environment)
        if parsed.command == "agent.doctor":
            return _doctor(
                store,
                api_client,
                environment=selected_environment,
                now=now(),
                stream=stream,
            )
        if parsed.command == "auth.login":
            return _login(
                store,
                api_client,
                browser=parsed.browser,
                browser_open=browser_open,
                sleep=sleep,
                stream=stream,
                interactive_auth_factory=interactive_auth_factory,
                text_input=text_input,
                password_input=password_input,
                is_interactive_terminal=is_interactive_terminal,
            )
        if parsed.command == "auth.logout":
            return _logout(store, api_client, stream=stream)

        access_token, observed_state = _usable_access_token(
            store,
            api_client,
            now=now(),
        )
        if parsed.command == "auth.status":
            response = _protected_call(
                store,
                observed_state,
                lambda: api_client.auth_status(access_token),
            )
            emit_json(_validated(response, validate_auth_status), stream=stream)
            return 0
        if parsed.command == "stores.list":
            response = _protected_call(
                store,
                observed_state,
                lambda: api_client.list_stores(access_token),
            )
            emit_json(_validated(response, validate_stores), stream=stream)
            return 0
        if parsed.command == "clues.follow-up-stats":
            response = _protected_call(
                store,
                observed_state,
                lambda: api_client.follow_up_stats(
                    access_token,
                    date_from=parsed.date_from,
                    date_to=parsed.date_to,
                    store_ids=parsed.store_ids,
                ),
            )
            response = _validated(
                response,
                lambda payload: validate_follow_up_stats(
                    payload,
                    expected_store_ids=parsed.store_ids,
                    expected_date_start=parsed.date_from,
                    expected_date_end=parsed.date_to,
                ),
            )
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
            environment=selected_environment.name,
            stream=stream,
        )
    except Exception:
        return emit_error(
            parsed.command,
            "INTERNAL_ERROR",
            "The command could not be completed.",
            environment=selected_environment.name,
            stream=stream,
        )


def _doctor(
    store: CredentialStore,
    client: DyDataClient,
    *,
    environment: EnvironmentConfig,
    now: datetime,
    stream: TextIO | None,
) -> int:
    """Diagnose public discovery and the current environment credential."""
    manifest = client.get_agent_manifest()
    client.get_mcp_resource_metadata()
    checks: list[dict[str, str]] = [
        {
            "name": "agent_manifest",
            "status": "pass",
            "message": "The Agent manifest is reachable and compatible.",
        },
        {
            "name": "mcp_protected_resource_metadata",
            "status": "pass",
            "message": "MCP OAuth resource metadata is reachable and compatible.",
        },
    ]
    state = store.load()
    if state is None:
        credential: dict[str, Any] = {
            "status": "not_configured",
            "identity": None,
            "stores": [],
        }
        checks.append(
            {
                "name": "credential",
                "status": "not_configured",
                "message": "No credential exists for this environment.",
            }
        )
        next_action = "dydata auth login"
    else:
        try:
            access_token, observed_state = _usable_access_token(
                store,
                client,
                now=now,
            )
            status_response = _protected_call(
                store,
                observed_state,
                lambda: client.auth_status(access_token),
            )
            stores_response = _protected_call(
                store,
                observed_state,
                lambda: client.list_stores(access_token),
            )
        except CliError as exc:
            if exc.code not in _AUTH_ERROR_CODES:
                raise
            credential = {
                "status": "not_configured",
                "identity": None,
                "stores": [],
            }
            checks.append(
                {
                    "name": "credential",
                    "status": "not_configured",
                    "message": "The stored authorization is no longer usable.",
                }
            )
            next_action = "dydata auth login"
        else:
            status_data = status_response["data"]
            credential = {
                "status": "authenticated",
                "identity": {
                    "user_id": status_data["user_id"],
                    "username": status_data["username"],
                    "display_name": status_data["display_name"],
                    "role": status_data["role"],
                },
                "stores": stores_response["data"]["stores"],
            }
            checks.append(
                {
                    "name": "credential",
                    "status": "pass",
                    "message": "The current authorization and store scope are usable.",
                }
            )
            next_action = "none"
    emit_json(
        {
            "ok": True,
            "command": "agent.doctor",
            "environment": environment.name,
            "schema_version": CLI_SCHEMA_VERSION,
            "data": {
                "cli_version": CLI_VERSION,
                "manifest_version": manifest["manifest_version"],
                "public_urls": {
                    "base_url": environment.web_url,
                    "manifest": (
                        f"{environment.web_url}/.well-known/dydata-agent.json"
                    ),
                    "mcp": environment.mcp_url,
                    "capabilities": (
                        f"{environment.web_url}/api/v1/agent/capabilities"
                    ),
                },
                "checks": checks,
                "credential": credential,
                "next_action": next_action,
            },
            "meta": {"channel": "cli"},
        },
        stream=stream,
    )
    return 0


def _login(
    store: CredentialStore,
    client: DyDataClient,
    *,
    browser: bool,
    browser_open: Callable[[str], Any],
    sleep: Callable[[float], None],
    stream: TextIO | None,
    interactive_auth_factory: Callable[[], InteractiveAuthSession],
    text_input: Callable[[str], str],
    password_input: Callable[[str], str],
    is_interactive_terminal: Callable[[], bool],
) -> int:
    target = stream or sys.stdout
    if store.load() is not None:
        target.write(
            "A local CLI credential already exists. Run `dydata auth logout` "
            "before signing in as another account.\n"
        )
        return 0
    if browser:
        return _browser_login(
            store,
            client,
            browser_open=browser_open,
            sleep=sleep,
            stream=stream,
        )
    if not is_interactive_terminal():
        raise CliError("INTERACTIVE_REQUIRED")
    return _terminal_login(
        store,
        client,
        sleep=sleep,
        stream=stream,
        interactive_auth_factory=interactive_auth_factory,
        text_input=text_input,
        password_input=password_input,
    )


def _browser_login(
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

    state = _poll_for_credential(
        client,
        device_code=device_code,
        expires_in=expires_in,
        interval=interval,
        sleep=sleep,
    )
    _save_new_credential(store, client, state)
    target.write("Authorization complete.\n")
    return 0


def _terminal_login(
    store: CredentialStore,
    client: DyDataClient,
    *,
    sleep: Callable[[float], None],
    stream: TextIO | None,
    interactive_auth_factory: Callable[[], InteractiveAuthSession],
    text_input: Callable[[str], str],
    password_input: Callable[[str], str],
) -> int:
    username = _read_interactive_text("Username: ", text_input).strip()
    if not username:
        raise CliError("INVALID_ARGUMENT")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = password_input("Password: ")
    except (EOFError, getpass.GetPassWarning):
        raise CliError("INTERACTIVE_REQUIRED") from None
    if not isinstance(password, str) or not password:
        raise CliError("AUTH_FAILED")

    target = stream or sys.stdout
    with interactive_auth_factory() as auth_session:
        try:
            identity = auth_session.login(username, password)
        finally:
            del password
        _write_identity_summary(identity, stream=target)
        confirmation = _read_interactive_text(
            "Authorize this CLI credential? [y/N]: ", text_input
        ).strip().lower()
        if confirmation not in {"y", "yes"}:
            target.write("Authorization cancelled.\n")
            return ERROR_EXIT_CODES["AUTH_FAILED"]
        start = client.start_device_authorization()
        device_code = _required_text(start, "device_code")
        user_code = _required_text(start, "user_code")
        expires_in = _required_positive_integer(start, "expires_in")
        interval = _required_positive_integer(start, "interval")
        auth_session.approve_device_authorization(user_code)

    state = _poll_for_credential(
        client,
        device_code=device_code,
        expires_in=expires_in,
        interval=interval,
        sleep=sleep,
    )
    _save_new_credential(store, client, state)
    target.write("Authorization complete.\n")
    return 0


def _read_interactive_text(
    prompt: str, reader: Callable[[str], str]
) -> str:
    try:
        value = reader(prompt)
    except EOFError:
        raise CliError("INTERACTIVE_REQUIRED") from None
    if not isinstance(value, str):
        raise CliError("INTERACTIVE_REQUIRED")
    return value


def _write_identity_summary(identity: LoginIdentity, *, stream: TextIO) -> None:
    if identity.store_scope_mode == "all":
        store_scope = "all stores"
    elif identity.store_scope_mode == "specified":
        store_count = len(identity.store_ids)
        store_scope = f"{store_count} store" if store_count == 1 else f"{store_count} stores"
    else:
        store_scope = "no stores"
    stream.write(f"Signed in as: {identity.username}\n")
    stream.write(f"Role: {identity.role}\n")
    stream.write(f"Store scope: {store_scope}\n")


def _poll_for_credential(
    client: DyDataClient,
    *,
    device_code: str,
    expires_in: int,
    interval: int,
    sleep: Callable[[float], None],
) -> CredentialState:
    poll_count = max(1, math.ceil(expires_in / interval))
    for poll_index in range(poll_count):
        response = client.poll_device_token(device_code)
        if response.get("status") == "authorization_pending":
            if poll_index + 1 < poll_count:
                sleep(interval)
            continue
        return _credential_state_from_response(response)
    raise CliError("AUTH_EXPIRED")


def _save_new_credential(
    store: CredentialStore,
    client: DyDataClient,
    state: CredentialState,
) -> None:
    try:
        saved = store.save(state, expected=None)
    except Exception:
        _best_effort_revoke(client, state.refresh_token)
        raise
    if saved:
        return
    _best_effort_revoke(client, state.refresh_token)
    raise CliError("AUTH_FAILED")


def _best_effort_revoke(client: DyDataClient, refresh_token: str) -> None:
    try:
        client.revoke(refresh_token)
    except Exception:
        # A cleanup failure must not mask the original local-save/CAS outcome.
        return


def _logout(
    store: CredentialStore,
    client: DyDataClient,
    *,
    stream: TextIO | None,
) -> int:
    state = store.load()
    if state is not None:
        try:
            client.revoke(state.refresh_token)
        except CliError as exc:
            if exc.code not in _AUTH_ERROR_CODES:
                raise
        store.clear(expected=state)
    target = stream or sys.stdout
    target.write("Logged out.\n")
    return 0


def _usable_access_token(
    store: CredentialStore,
    client: DyDataClient,
    *,
    now: datetime,
) -> tuple[str, CredentialState]:
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
        return state.access_token, state
    with store._locked() as locked:
        state = locked.load()
        if state is None:
            raise CliError("AUTH_REQUIRED")
        expires_at = state.access_token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at.astimezone(timezone.utc) > refresh_at:
            return state.access_token, state
        try:
            refreshed = client.refresh(state.refresh_token)
            new_state = _credential_state_from_response(refreshed)
            saved = locked.save(new_state, expected=state)
        except CliError as exc:
            if exc.code in _AUTH_ERROR_CODES:
                locked.clear(expected=state)
            raise
        if not saved:
            concurrent_state = locked.load()
            if concurrent_state is None:
                raise CliError("AUTH_REQUIRED")
            return concurrent_state.access_token, concurrent_state
        return new_state.access_token, new_state


def _protected_call(
    store: CredentialStore,
    observed_state: CredentialState,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        return operation()
    except CliError as exc:
        if exc.code in _AUTH_ERROR_CODES:
            store.clear(expected=observed_state)
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
