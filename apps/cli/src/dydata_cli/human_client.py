"""Fixed Web-session HTTP operations used only by the interactive human console."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from .client import CliError
from .environments import EnvironmentConfig, resolve_environment
from .human_contracts import product_snapshot, require_ids, require_text, validate_results, validate_rule_patch
from .url_security import normalize_safe_url


_PRODUCTS_PATH = "admin/clue-routing/products"


class HumanProductSession:
    """Keep a fresh human Web cookie only in memory, never in the CLI keyring."""

    def __init__(
        self, *, environment: EnvironmentConfig | None = None,
        transport: httpx.BaseTransport | None = None, timeout: float = 30.0,
    ) -> None:
        self.environment = environment or resolve_environment()
        self._http = httpx.Client(
            base_url=normalize_safe_url(self.environment.api_url, trailing_slash=True),
            transport=transport, timeout=timeout, follow_redirects=False, trust_env=False,
            headers={"User-Agent": "dydata-products/human"},
        )
        self._authenticated = False
        self.request_id: str | None = None
        self.server_request_id: str | None = None

    def __enter__(self) -> HumanProductSession:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def login(self, username: str, password: str) -> dict[str, str]:
        """Sign in through the existing Web endpoint, without obtaining Agent tokens."""
        data = self._request("POST", "auth/login", body={
            "username": username, "password": password,
        })
        identity = {
            key: require_text(data.get(key))
            for key in ("username", "role", "store_scope_mode")
        }
        if (
            identity["role"] not in {"admin", "highest_admin", "store"}
            or identity["store_scope_mode"] not in {"all", "specified", "none", "organization"}
            or data.get("status") != "active"
            or data.get("is_initialized") is not True
            or not self._http.cookies
        ):
            raise CliError("AUTH_FAILED")
        self._authenticated = True
        return identity

    def list_products(
        self, *, q: str, product_scope: str, page: int, page_size: int,
    ) -> dict[str, Any]:
        """Discover only the products visible to the signed-in human."""
        data = self._request("GET", _PRODUCTS_PATH, params={
            "q": q, "product_scope": product_scope, "page": page, "page_size": page_size,
        })
        if not isinstance(data.get("rows"), list):
            raise CliError("SCHEMA_MISMATCH")
        rows = [product_snapshot(row) for row in data["rows"]]
        require_ids([row["product_id"] for row in rows])
        for key in ("total", "page", "page_size"):
            if type(data.get(key)) is not int or data[key] < (0 if key == "total" else 1):
                raise CliError("SCHEMA_MISMATCH")
        if data["page"] != page or data["page_size"] != page_size:
            raise CliError("SCHEMA_MISMATCH")
        for key in ("can_manage_grants", "can_manage_shared_rule"):
            if type(data.get(key)) is not bool:
                raise CliError("SCHEMA_MISMATCH")
        return {"rows": rows, **{
            key: data[key] for key in ("total", "page", "page_size", "can_manage_grants", "can_manage_shared_rule")
        }}

    def batch(self, body: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        """Preview or submit one exact batch once; writes are never auto-retried."""
        data = self._request(
            "POST", f"{_PRODUCTS_PATH}/batch", body=body,
            headers={"Idempotency-Key": idempotency_key},
        )
        results = validate_results(data.get("results"), preview=body["preview"])
        if not body.get("all_matching"):
            if set(row["product_id"] for row in results) != set(body["product_ids"]):
                raise CliError("SCHEMA_MISMATCH")
        return {"results": results, "request_id": self.request_id, "server_request_id": self.server_request_id}

    def get_grants(self, product_id: str) -> dict[str, Any]:
        """Read the current grant set and server-authorized available users."""
        data = self._request("GET", self._grants_path(product_id))
        return self._validate_grants(data, product_id)

    def set_grants(self, product_id: str, user_ids: list[str]) -> dict[str, Any]:
        """Replace one product's explicit human managers, with server authorization."""
        data = self._request("PUT", self._grants_path(product_id), body={"user_ids": user_ids})
        return self._validate_grants(data, product_id)

    def get_shared_rule_grants(self) -> dict[str, Any]:
        """Read shared-base maintainers and available users as a full-scope admin."""
        data = self._request("GET", "admin/clue-routing/shared-rule/grants")
        return self._validate_user_grants(data)

    def set_shared_rule_grants(self, user_ids: list[str]) -> dict[str, Any]:
        """Replace shared-base maintainers through the separate authorized endpoint."""
        data = self._request("PUT", "admin/clue-routing/shared-rule/grants", body={"user_ids": user_ids})
        return self._validate_user_grants(data)

    def shared_rule(self, *, rules: dict[str, Any], preview: bool) -> dict[str, Any]:
        """Preview or publish the shared Jingcheng base without switching product rules."""
        data = self._request("PUT", "admin/clue-routing/shared-rule", body={
            "rules": rules, "preview": preview,
        })
        if data.get("status") != ("preview" if preview else "success"):
            raise CliError("SCHEMA_MISMATCH")
        snapshots = {}
        for key in ("before", "after"):
            snapshot = data.get(key)
            if not isinstance(snapshot, dict) or snapshot.get("can_manage") is not True:
                raise CliError("SCHEMA_MISMATCH")
            version = snapshot.get("rule_version_id")
            if version is not None and type(version) is not int:
                version = require_text(version)
            try:
                patch = validate_rule_patch({
                    "first_follow_up_sla_hours": snapshot.get("first_follow_up_sla_hours"),
                    "follow_up_policy": snapshot.get("follow_up_policy"),
                })
            except CliError:
                raise CliError("SCHEMA_MISMATCH") from None
            snapshots[key] = {
                "rule_version_id": version, "can_manage": True,
                "first_follow_up_sla_hours": patch.pop("first_follow_up_sla_hours"),
                "follow_up_policy": patch,
            }
        return {"status": data["status"], **snapshots, "request_id": self.request_id,
                "server_request_id": self.server_request_id}

    def close(self) -> None:
        """End the temporary Web session and clear its in-memory cookie on every exit."""
        if self._http.is_closed:
            return
        try:
            if self._authenticated:
                self._request("POST", "auth/logout")
        except CliError:
            pass  # A logout failure must not retain cookies or obscure a published result.
        finally:
            self._authenticated = False
            self._http.cookies.clear()
            self._http.close()

    @staticmethod
    def _grants_path(product_id: str) -> str:
        if product_id in {".", ".."} or "/" in product_id or "\\" in product_id:
            raise CliError("INVALID_ARGUMENT")
        return f"{_PRODUCTS_PATH}/{quote(product_id, safe='')}/grants"

    @staticmethod
    def _validate_grants(data: dict[str, Any], product_id: str) -> dict[str, Any]:
        if data.get("product_id") != product_id:
            raise CliError("SCHEMA_MISMATCH")
        return {"product_id": product_id, **HumanProductSession._validate_user_grants(data)}

    @staticmethod
    def _validate_user_grants(data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data.get("users"), list):
            raise CliError("SCHEMA_MISMATCH")
        users = []
        for user in data["users"]:
            if not isinstance(user, dict):
                raise CliError("SCHEMA_MISMATCH")
            users.append({key: require_text(user.get(key), empty=key == "display_name")
                          for key in ("user_id", "username", "display_name")})
        require_ids([user["user_id"] for user in users])
        return {"user_ids": require_ids(data.get("user_ids")), "users": users}

    def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_id = f"req_{uuid4().hex}"
        self.request_id = request_id
        self.server_request_id = None
        try:
            response = self._http.request(
                method, path, json=body, params=params,
                headers={"X-Request-ID": request_id, **(headers or {})},
            )
        except httpx.RequestError:
            raise CliError("API_UNAVAILABLE", request_id=request_id) from None
        if not 200 <= response.status_code < 300:
            code = {
                401: "AUTH_FAILED" if path == "auth/login" else "AUTH_EXPIRED",
                403: "SCOPE_DENIED", 429: "RATE_LIMITED",
            }.get(response.status_code, "API_UNAVAILABLE" if response.status_code >= 500 else "INVALID_ARGUMENT")
            raise CliError(code, request_id=request_id) from None
        try:
            payload = response.json()
        except ValueError:
            raise CliError("SCHEMA_MISMATCH", request_id=request_id) from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise CliError("SCHEMA_MISMATCH", request_id=request_id)
        meta = payload.get("meta")
        server_request_id = meta.get("request_id") if isinstance(meta, dict) else None
        if isinstance(server_request_id, str) and re.fullmatch(r"(?:req_)?[0-9a-f]{32}", server_request_id):
            self.server_request_id = server_request_id
        return payload["data"]
