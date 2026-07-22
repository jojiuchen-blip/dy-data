"""Persistent OAuth 2.1 provider for the isolated read-only MCP channel."""

from __future__ import annotations

import hmac
import json
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from fastapi import HTTPException
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.cli_auth import (
    _current_auth,
    _environment_authorization_fingerprint,
    _environment_cli_subject,
    hash_cli_secret,
)
from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import (
    McpAccessToken,
    McpAuthorizationRequest,
    McpOAuthClient,
    McpRefreshToken,
    User,
    utcnow,
)
from apps.cli.src.dydata_cli.environments import TEST_ENVIRONMENT
from dy_api.auth import AuthContext


MCP_ACCESS_SCOPE = "mcp:read"
MCP_ACCESS_TTL_SECONDS = 30 * 60
MCP_REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60
MCP_AUTHORIZATION_TTL_SECONDS = 10 * 60
TEST_ISSUER_URL = TEST_ENVIRONMENT.web_url
MCP_RESOURCE_URL = TEST_ENVIRONMENT.mcp_url
MCP_ENVIRONMENT = TEST_ENVIRONMENT.name
PKCE_CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
DCR_MAX_METADATA_BYTES = 16 * 1024
LOOPBACK_REDIRECT_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


class McpAuthorizationRequestError(ValueError):
    """The browser approval request is absent, expired, or already consumed."""


class McpAccessAuthorizationError(RuntimeError):
    """An MCP token became invalid after transport authentication completed."""


class DyDataAuthorizationCode(AuthorizationCode):
    authorization_request_id: str


class DyDataRefreshToken(RefreshToken):
    refresh_token_id: str
    family_id: str
    resource: str
    environment: str
    revoked: bool = False


class DyDataAccessToken(AccessToken):
    access_token_id: str
    family_id: str
    environment: str


def _utc(value: datetime | None = None) -> datetime:
    current = value or utcnow()
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _is_safe_oauth_redirect_uri(redirect_uri: str) -> bool:
    if (
        not redirect_uri
        or "#" in redirect_uri
        or "\\" in redirect_uri
        or any(
            ord(character) <= 0x20 or ord(character) == 0x7F
            for character in redirect_uri
        )
    ):
        return False
    try:
        parsed = urlsplit(redirect_uri)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    if (
        not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return True
    return scheme == "http" and hostname.lower() in LOOPBACK_REDIRECT_HOSTNAMES


def _metadata_has_safe_redirect_uris(metadata: object) -> bool:
    if not isinstance(metadata, dict):
        return False
    redirect_uris = metadata.get("redirect_uris")
    return (
        isinstance(redirect_uris, list)
        and bool(redirect_uris)
        and all(
            isinstance(redirect_uri, str)
            and _is_safe_oauth_redirect_uri(redirect_uri)
            for redirect_uri in redirect_uris
        )
    )


def _redirect_with_params(url: str, **params: str | None) -> str:
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


class DatabaseMcpOAuthProvider(
    OAuthAuthorizationServerProvider[
        DyDataAuthorizationCode,
        DyDataRefreshToken,
        DyDataAccessToken,
    ]
):
    """Store public clients and opaque MCP credentials as database digests."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._session_factory = session_factory

    def _factory(self) -> sessionmaker[Session]:
        factory = self._session_factory or get_session_factory()
        if factory is None:
            raise RuntimeError("Database is not available for MCP authorization")
        return factory

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Open a provider-owned transaction for an authenticated MCP call."""
        with session_scope(self._factory()) as session:
            yield session

    async def authorization_request_details(self, request_id: str) -> dict:
        """Return only the safe fields required by the human consent screen."""
        with session_scope(self._factory()) as session:
            grant = session.execute(
                select(McpAuthorizationRequest).where(
                    McpAuthorizationRequest.request_token_hash
                    == hash_cli_secret(request_id)
                )
            ).scalar_one_or_none()
            if (
                grant is None
                or grant.environment != MCP_ENVIRONMENT
                or grant.resource != MCP_RESOURCE_URL
                or grant.scopes != [MCP_ACCESS_SCOPE]
                or grant.status != "pending"
                or grant.code_hash is not None
                or _utc(grant.expires_at) <= _utc()
            ):
                raise McpAuthorizationRequestError(
                    "Authorization request is invalid or expired"
                )
            client = session.get(McpOAuthClient, grant.client_id)
            if (
                client is None
                or client.environment != MCP_ENVIRONMENT
                or not _metadata_has_safe_redirect_uris(client.metadata_json)
                or not _is_safe_oauth_redirect_uri(grant.redirect_uri)
            ):
                raise McpAuthorizationRequestError(
                    "Authorization request is invalid or expired"
                )
            return {
                "request_id": request_id,
                "agent_name": str(
                    client.metadata_json.get("client_name") or "Unknown Agent"
                ),
                "redirect_uri": grant.redirect_uri,
                "scopes": list(grant.scopes),
                "environment": grant.environment,
                "resource": grant.resource,
                "expires_at": _utc(grant.expires_at).isoformat(),
            }

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with session_scope(self._factory()) as session:
            stored = session.get(McpOAuthClient, client_id)
            if stored is None or stored.environment != MCP_ENVIRONMENT:
                return None
            if not _metadata_has_safe_redirect_uris(stored.metadata_json):
                return None
            try:
                return OAuthClientInformationFull.model_validate(stored.metadata_json)
            except ValueError:
                return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if (
            client_info.client_id is None
            or client_info.token_endpoint_auth_method != "none"
            or client_info.client_secret is not None
        ):
            raise RegistrationError(
                "invalid_client_metadata",
                "Only public clients with token_endpoint_auth_method=none are supported",
            )
        if set(client_info.grant_types) != {"authorization_code", "refresh_token"}:
            raise RegistrationError(
                "invalid_client_metadata",
                "Only authorization_code and refresh_token grants are supported",
            )
        if client_info.response_types != ["code"]:
            raise RegistrationError(
                "invalid_client_metadata", "Only the code response type is supported"
            )
        if client_info.scope != MCP_ACCESS_SCOPE:
            raise RegistrationError(
                "invalid_client_metadata", f"Scope must be {MCP_ACCESS_SCOPE}"
            )
        client_name = client_info.client_name or ""
        redirect_uris = list(client_info.redirect_uris or [])
        contacts = list(client_info.contacts or [])
        if len(client_name) > 128:
            raise RegistrationError(
                "invalid_client_metadata", "client_name must not exceed 128 characters"
            )
        if (
            not redirect_uris
            or len(redirect_uris) > 10
            or any(len(str(uri)) > 2048 for uri in redirect_uris)
            or any(
                not _is_safe_oauth_redirect_uri(str(uri)) for uri in redirect_uris
            )
        ):
            raise RegistrationError(
                "invalid_client_metadata", "redirect_uris is invalid or unsafe"
            )
        if client_info.jwks is not None or client_info.jwks_uri is not None:
            raise RegistrationError(
                "invalid_client_metadata",
                "JWKS metadata is not supported for public clients",
            )
        if len(contacts) > 5 or any(len(str(contact)) > 254 for contact in contacts):
            raise RegistrationError(
                "invalid_client_metadata", "contacts exceeds the supported limit"
            )

        metadata = client_info.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"client_secret", "client_secret_expires_at"},
        )
        if len(
            json.dumps(
                metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ) > DCR_MAX_METADATA_BYTES:
            raise RegistrationError(
                "invalid_client_metadata", "Client metadata is too large"
            )
        registration_error: RegistrationError | None = None
        with session_scope(self._factory()) as session:
            if session.get(McpOAuthClient, client_info.client_id) is not None:
                registration_error = RegistrationError(
                    "invalid_client_metadata", "Client ID is already registered"
                )
            else:
                session.add(
                    McpOAuthClient(
                        client_id=client_info.client_id,
                        environment=MCP_ENVIRONMENT,
                        metadata_json=metadata,
                        created_at=utcnow(),
                    )
                )
        if registration_error is not None:
            raise registration_error

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if client.client_id is None or client.token_endpoint_auth_method != "none":
            raise AuthorizeError("unauthorized_client", "Public client is required")
        redirect_uri = str(params.redirect_uri)
        if not _is_safe_oauth_redirect_uri(redirect_uri):
            raise AuthorizeError(
                "invalid_request", "redirect_uri is invalid or unsafe"
            )
        scopes = params.scopes or [MCP_ACCESS_SCOPE]
        if scopes != [MCP_ACCESS_SCOPE]:
            raise AuthorizeError("invalid_scope", f"Scope must be {MCP_ACCESS_SCOPE}")
        if params.resource != MCP_RESOURCE_URL:
            raise AuthorizeError(
                "invalid_request", f"Resource must be {MCP_RESOURCE_URL}"
            )
        if PKCE_CHALLENGE_PATTERN.fullmatch(params.code_challenge) is None:
            raise AuthorizeError(
                "invalid_request", "PKCE S256 code_challenge is malformed"
            )

        request_id = secrets.token_urlsafe(32)
        current_time = utcnow()
        with session_scope(self._factory()) as session:
            session.add(
                McpAuthorizationRequest(
                    authorization_request_id=uuid4().hex,
                    request_token_hash=hash_cli_secret(request_id),
                    client_id=client.client_id,
                    environment=MCP_ENVIRONMENT,
                    redirect_uri=redirect_uri,
                    redirect_uri_provided_explicitly=(
                        params.redirect_uri_provided_explicitly
                    ),
                    state=params.state,
                    scopes=scopes,
                    code_challenge=params.code_challenge,
                    resource=params.resource,
                    status="pending",
                    created_at=current_time,
                    expires_at=current_time
                    + timedelta(seconds=MCP_AUTHORIZATION_TTL_SECONDS),
                )
            )
        return _redirect_with_params(
            f"{TEST_ISSUER_URL}/auth/mcp/authorize", request_id=request_id
        )

    def _snapshot_auth(
        self, session: Session, auth: AuthContext
    ) -> tuple[AuthContext, str, str, int | None]:
        if auth.auth_type == "user":
            current = _current_auth(
                session,
                username=auth.username,
                auth_type="user",
                user_id=auth.user_id,
            )
            user = session.get(User, current.user_id) if current.user_id else None
            if user is None:
                raise McpAuthorizationRequestError("Authorization identity is invalid")
            return current, user.cli_subject, "", user.auth_generation
        if auth.auth_type == "env_admin":
            current = _current_auth(
                None, username=auth.username, auth_type="env_admin"
            )
            return (
                current,
                _environment_cli_subject(current.username),
                _environment_authorization_fingerprint(current),
                None,
            )
        raise McpAuthorizationRequestError("Authorization identity is invalid")

    async def approve_authorization(
        self, request_id: str, auth: AuthContext
    ) -> str:
        """Bind one pending browser handoff to the current Web identity."""
        current_time = utcnow()
        raw_code = secrets.token_urlsafe(48)
        with session_scope(self._factory()) as session:
            grant = session.execute(
                select(McpAuthorizationRequest)
                .where(
                    McpAuthorizationRequest.request_token_hash
                    == hash_cli_secret(request_id)
                )
                .with_for_update()
            ).scalar_one_or_none()
            if (
                grant is None
                or grant.environment != MCP_ENVIRONMENT
                or grant.resource != MCP_RESOURCE_URL
                or grant.scopes != [MCP_ACCESS_SCOPE]
                or grant.status != "pending"
                or grant.code_hash is not None
                or _utc(grant.expires_at) <= _utc(current_time)
                or not _is_safe_oauth_redirect_uri(grant.redirect_uri)
            ):
                raise McpAuthorizationRequestError(
                    "Authorization request is invalid or expired"
                )
            try:
                current, subject, fingerprint, generation = self._snapshot_auth(
                    session, auth
                )
            except HTTPException as exc:
                raise McpAuthorizationRequestError(
                    "Authorization identity is invalid"
                ) from exc
            grant.status = "approved"
            grant.code_hash = hash_cli_secret(raw_code)
            grant.subject = subject
            grant.user_id = current.user_id
            grant.username = current.username
            grant.auth_type = current.auth_type
            grant.authorization_fingerprint = fingerprint
            grant.issued_auth_generation = generation
            grant.approved_at = current_time
            redirect_uri = grant.redirect_uri
            state = grant.state
        return _redirect_with_params(redirect_uri, code=raw_code, state=state)

    async def deny_authorization(self, request_id: str) -> str:
        """Consume one pending request without granting an authorization code."""
        current_time = utcnow()
        with session_scope(self._factory()) as session:
            grant = session.execute(
                select(McpAuthorizationRequest)
                .where(
                    McpAuthorizationRequest.request_token_hash
                    == hash_cli_secret(request_id)
                )
                .with_for_update()
            ).scalar_one_or_none()
            if (
                grant is None
                or grant.environment != MCP_ENVIRONMENT
                or grant.resource != MCP_RESOURCE_URL
                or grant.scopes != [MCP_ACCESS_SCOPE]
                or grant.status != "pending"
                or grant.code_hash is not None
                or _utc(grant.expires_at) <= _utc(current_time)
                or not _is_safe_oauth_redirect_uri(grant.redirect_uri)
            ):
                raise McpAuthorizationRequestError(
                    "Authorization request is invalid or expired"
                )
            grant.status = "denied"
            grant.consumed_at = current_time
            redirect_uri = grant.redirect_uri
            state = grant.state
        return _redirect_with_params(
            redirect_uri, error="access_denied", state=state
        )

    def current_auth_for_access_token(
        self, session: Session, token: DyDataAccessToken
    ) -> AuthContext:
        """Revalidate the persisted token subject inside the tool transaction."""
        stored = session.get(McpAccessToken, token.access_token_id)
        if (
            stored is None
            or stored.token_hash != hash_cli_secret(token.token)
            or stored.environment != MCP_ENVIRONMENT
            or stored.resource != MCP_RESOURCE_URL
            or stored.scopes != [MCP_ACCESS_SCOPE]
            or stored.revoked_at is not None
            or _utc(stored.expires_at) <= _utc()
        ):
            raise McpAccessAuthorizationError("Authorization is no longer valid")
        try:
            return self._reload_auth(
                session,
                user_id=stored.user_id,
                username=stored.username,
                auth_type=stored.auth_type,
                authorization_fingerprint=stored.authorization_fingerprint,
                issued_auth_generation=stored.issued_auth_generation,
                subject=stored.subject,
            )
        except TokenError as exc:
            raise McpAccessAuthorizationError(
                "Authorization is no longer valid"
            ) from exc

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> DyDataAuthorizationCode | None:
        with session_scope(self._factory()) as session:
            grant = session.execute(
                select(McpAuthorizationRequest).where(
                    McpAuthorizationRequest.code_hash
                    == hash_cli_secret(authorization_code)
                )
            ).scalar_one_or_none()
            if (
                grant is None
                or grant.client_id != client.client_id
                or grant.environment != MCP_ENVIRONMENT
                or grant.status != "approved"
                or grant.consumed_at is not None
                or not grant.subject
            ):
                return None
            return DyDataAuthorizationCode(
                code=authorization_code,
                scopes=list(grant.scopes),
                expires_at=_utc(grant.expires_at).timestamp(),
                client_id=grant.client_id,
                code_challenge=grant.code_challenge,
                redirect_uri=grant.redirect_uri,
                redirect_uri_provided_explicitly=(
                    grant.redirect_uri_provided_explicitly
                ),
                resource=grant.resource,
                subject=grant.subject,
                authorization_request_id=grant.authorization_request_id,
            )

    def _reload_auth(
        self,
        session: Session,
        *,
        user_id: str | None,
        username: str,
        auth_type: str,
        authorization_fingerprint: str,
        issued_auth_generation: int | None,
        subject: str,
    ) -> AuthContext:
        try:
            current = _current_auth(
                session if auth_type == "user" else None,
                username=username,
                auth_type=auth_type,
                user_id=user_id,
            )
        except HTTPException as exc:
            raise TokenError("invalid_grant", "Authorization is no longer valid") from exc
        if auth_type == "user":
            user = session.get(User, user_id) if user_id else None
            if (
                user is None
                or issued_auth_generation is None
                or user.auth_generation != issued_auth_generation
                or not hmac.compare_digest(user.cli_subject, subject)
            ):
                raise TokenError("invalid_grant", "Authorization is no longer valid")
        elif auth_type == "env_admin":
            if not hmac.compare_digest(
                authorization_fingerprint,
                _environment_authorization_fingerprint(current),
            ):
                raise TokenError("invalid_grant", "Authorization is no longer valid")
        else:
            raise TokenError("invalid_grant", "Authorization is no longer valid")
        return current

    def _issue_pair(
        self,
        session: Session,
        *,
        client_id: str,
        family_id: str,
        subject: str,
        auth: AuthContext,
        authorization_fingerprint: str,
        issued_auth_generation: int | None,
        scopes: list[str],
        now: datetime,
        refresh_token_id: str | None = None,
    ) -> OAuthToken:
        raw_access = secrets.token_urlsafe(48)
        raw_refresh = secrets.token_urlsafe(48)
        access_expires = now + timedelta(seconds=MCP_ACCESS_TTL_SECONDS)
        refresh_expires = now + timedelta(seconds=MCP_REFRESH_TTL_SECONDS)
        session.add_all(
            [
                McpAccessToken(
                    access_token_id=uuid4().hex,
                    family_id=family_id,
                    token_hash=hash_cli_secret(raw_access),
                    client_id=client_id,
                    environment=MCP_ENVIRONMENT,
                    subject=subject,
                    user_id=auth.user_id,
                    username=auth.username,
                    auth_type=auth.auth_type,
                    authorization_fingerprint=authorization_fingerprint,
                    issued_auth_generation=issued_auth_generation,
                    scopes=scopes,
                    resource=MCP_RESOURCE_URL,
                    created_at=now,
                    expires_at=access_expires,
                ),
                McpRefreshToken(
                    refresh_token_id=refresh_token_id or uuid4().hex,
                    family_id=family_id,
                    token_hash=hash_cli_secret(raw_refresh),
                    client_id=client_id,
                    environment=MCP_ENVIRONMENT,
                    subject=subject,
                    user_id=auth.user_id,
                    username=auth.username,
                    auth_type=auth.auth_type,
                    authorization_fingerprint=authorization_fingerprint,
                    issued_auth_generation=issued_auth_generation,
                    scopes=scopes,
                    resource=MCP_RESOURCE_URL,
                    created_at=now,
                    expires_at=refresh_expires,
                ),
            ]
        )
        session.flush()
        return OAuthToken(
            access_token=raw_access,
            token_type="Bearer",
            expires_in=MCP_ACCESS_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=raw_refresh,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: DyDataAuthorizationCode,
    ) -> OAuthToken:
        current_time = utcnow()
        failure: TokenError | None = None
        tokens: OAuthToken | None = None
        with session_scope(self._factory()) as session:
            grant = session.execute(
                select(McpAuthorizationRequest)
                .where(
                    McpAuthorizationRequest.authorization_request_id
                    == authorization_code.authorization_request_id
                )
                .with_for_update()
            ).scalar_one_or_none()
            if (
                grant is None
                or grant.code_hash != hash_cli_secret(authorization_code.code)
                or grant.client_id != client.client_id
                or grant.status != "approved"
                or grant.consumed_at is not None
                or grant.resource != MCP_RESOURCE_URL
                or grant.scopes != [MCP_ACCESS_SCOPE]
                or not grant.subject
                or not grant.username
                or not grant.auth_type
                or _utc(grant.expires_at) <= _utc(current_time)
            ):
                failure = TokenError(
                    "invalid_grant", "Authorization code is invalid"
                )
            else:
                try:
                    auth = self._reload_auth(
                        session,
                        user_id=grant.user_id,
                        username=grant.username,
                        auth_type=grant.auth_type,
                        authorization_fingerprint=(
                            grant.authorization_fingerprint or ""
                        ),
                        issued_auth_generation=grant.issued_auth_generation,
                        subject=grant.subject,
                    )
                except TokenError as exc:
                    grant.status = "invalidated"
                    grant.consumed_at = current_time
                    failure = exc
                else:
                    grant.status = "consumed"
                    grant.consumed_at = current_time
                    tokens = self._issue_pair(
                        session,
                        client_id=grant.client_id,
                        family_id=uuid4().hex,
                        subject=grant.subject,
                        auth=auth,
                        authorization_fingerprint=(
                            grant.authorization_fingerprint or ""
                        ),
                        issued_auth_generation=grant.issued_auth_generation,
                        scopes=list(grant.scopes),
                        now=current_time,
                    )
        if failure is not None:
            raise failure
        if tokens is None:
            raise RuntimeError("OAuth authorization exchange invariant failed")
        return tokens

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> DyDataRefreshToken | None:
        with session_scope(self._factory()) as session:
            stored = session.execute(
                select(McpRefreshToken).where(
                    McpRefreshToken.token_hash == hash_cli_secret(refresh_token)
                )
            ).scalar_one_or_none()
            if (
                stored is None
                or stored.client_id != client.client_id
                or stored.environment != MCP_ENVIRONMENT
            ):
                return None
            return DyDataRefreshToken(
                token=refresh_token,
                client_id=stored.client_id,
                scopes=list(stored.scopes),
                expires_at=int(_utc(stored.expires_at).timestamp()),
                subject=stored.subject,
                refresh_token_id=stored.refresh_token_id,
                family_id=stored.family_id,
                resource=stored.resource,
                environment=stored.environment,
                revoked=stored.revoked_at is not None,
            )

    def _revoke_family(
        self, session: Session, family_id: str, current_time: datetime
    ) -> None:
        session.execute(
            update(McpAccessToken)
            .where(
                McpAccessToken.family_id == family_id,
                McpAccessToken.revoked_at.is_(None),
            )
            .values(revoked_at=current_time)
        )
        session.execute(
            update(McpRefreshToken)
            .where(
                McpRefreshToken.family_id == family_id,
                McpRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=current_time)
        )
        session.flush()

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: DyDataRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        current_time = utcnow()
        failure: TokenError | None = None
        tokens: OAuthToken | None = None
        with session_scope(self._factory()) as session:
            family = session.scalars(
                select(McpRefreshToken)
                .where(McpRefreshToken.family_id == refresh_token.family_id)
                .order_by(McpRefreshToken.created_at, McpRefreshToken.refresh_token_id)
                .with_for_update()
            ).all()
            stored = next(
                (
                    row
                    for row in family
                    if row.refresh_token_id == refresh_token.refresh_token_id
                ),
                None,
            )
            if (
                stored is None
                or stored.token_hash != hash_cli_secret(refresh_token.token)
                or stored.client_id != client.client_id
                or stored.environment != MCP_ENVIRONMENT
                or stored.resource != MCP_RESOURCE_URL
                or stored.scopes != [MCP_ACCESS_SCOPE]
                or scopes != [MCP_ACCESS_SCOPE]
                or stored.revoked_at is not None
                or stored.replaced_by_token_id is not None
                or _utc(stored.expires_at) <= _utc(current_time)
            ):
                if stored is not None:
                    stored.last_used_at = current_time
                    self._revoke_family(session, stored.family_id, current_time)
                failure = TokenError("invalid_grant", "Refresh token is invalid")
            else:
                try:
                    auth = self._reload_auth(
                        session,
                        user_id=stored.user_id,
                        username=stored.username,
                        auth_type=stored.auth_type,
                        authorization_fingerprint=stored.authorization_fingerprint,
                        issued_auth_generation=stored.issued_auth_generation,
                        subject=stored.subject,
                    )
                except TokenError as exc:
                    stored.last_used_at = current_time
                    self._revoke_family(session, stored.family_id, current_time)
                    failure = exc
                else:
                    self._revoke_family(session, stored.family_id, current_time)
                    replacement_id = uuid4().hex
                    stored.last_used_at = current_time
                    stored.replaced_by_token_id = replacement_id
                    tokens = self._issue_pair(
                        session,
                        client_id=stored.client_id,
                        family_id=stored.family_id,
                        subject=stored.subject,
                        auth=auth,
                        authorization_fingerprint=stored.authorization_fingerprint,
                        issued_auth_generation=stored.issued_auth_generation,
                        scopes=list(stored.scopes),
                        now=current_time,
                        refresh_token_id=replacement_id,
                    )
        if failure is not None:
            raise failure
        if tokens is None:
            raise RuntimeError("OAuth refresh exchange invariant failed")
        return tokens

    async def load_access_token(self, token: str) -> DyDataAccessToken | None:
        current_time = utcnow()
        with session_scope(self._factory()) as session:
            stored = session.execute(
                select(McpAccessToken).where(
                    McpAccessToken.token_hash == hash_cli_secret(token)
                )
            ).scalar_one_or_none()
            if (
                stored is None
                or stored.environment != MCP_ENVIRONMENT
                or stored.resource != MCP_RESOURCE_URL
                or stored.scopes != [MCP_ACCESS_SCOPE]
                or stored.revoked_at is not None
                or _utc(stored.expires_at) <= _utc(current_time)
            ):
                return None
            try:
                self._reload_auth(
                    session,
                    user_id=stored.user_id,
                    username=stored.username,
                    auth_type=stored.auth_type,
                    authorization_fingerprint=stored.authorization_fingerprint,
                    issued_auth_generation=stored.issued_auth_generation,
                    subject=stored.subject,
                )
            except TokenError:
                self._revoke_family(session, stored.family_id, current_time)
                session.commit()
                return None
            return DyDataAccessToken(
                token=token,
                client_id=stored.client_id,
                scopes=list(stored.scopes),
                expires_at=int(_utc(stored.expires_at).timestamp()),
                resource=stored.resource,
                subject=stored.subject,
                claims={
                    "user_id": stored.user_id,
                    "username": stored.username,
                    "auth_type": stored.auth_type,
                    "environment": stored.environment,
                },
                access_token_id=stored.access_token_id,
                family_id=stored.family_id,
                environment=stored.environment,
            )

    async def revoke_token(
        self, token: DyDataAccessToken | DyDataRefreshToken
    ) -> None:
        current_time = utcnow()
        with session_scope(self._factory()) as session:
            if isinstance(token, DyDataAccessToken):
                stored = session.execute(
                    select(McpAccessToken).where(
                        McpAccessToken.token_hash == hash_cli_secret(token.token)
                    )
                ).scalar_one_or_none()
            else:
                stored = session.execute(
                    select(McpRefreshToken).where(
                        McpRefreshToken.token_hash == hash_cli_secret(token.token)
                    )
                ).scalar_one_or_none()
            if stored is not None:
                self._revoke_family(session, stored.family_id, current_time)
