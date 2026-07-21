"""Shared transport URL policy for API and browser-verification endpoints."""

from __future__ import annotations

from ipaddress import ip_address
import re
from urllib.parse import unquote, urlsplit, urlunsplit


_LOOPBACK_HTTP_HOSTS = {"127.0.0.1", "::1", "localhost"}
_DNS_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$"
)


def normalize_safe_url(
    value: str,
    *,
    allow_query: bool = False,
    trailing_slash: bool = False,
) -> str:
    """Return a canonical URL allowed by the CLI transport policy."""
    candidate = value.strip()
    if (
        not candidate
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
        or "\\" in candidate
    ):
        raise ValueError("unsafe URL")
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("unsafe URL") from None
    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or (parsed.query and not allow_query)
        or parsed.fragment
        or port == 0
    ):
        raise ValueError("unsafe URL")

    normalized_host = hostname.lower()
    if normalized_host != "localhost":
        try:
            ip_address(normalized_host)
        except ValueError:
            if not _DNS_HOSTNAME.fullmatch(normalized_host):
                raise ValueError("unsafe URL") from None
    if scheme == "http" and (
        normalized_host not in _LOOPBACK_HTTP_HOSTS or port is None
    ):
        raise ValueError("unsafe URL")

    decoded_path = unquote(parsed.path)
    trimmed_path = decoded_path.rstrip("/")
    if (
        "\\" in decoded_path
        or any(ord(character) < 32 or ord(character) == 127 for character in decoded_path)
        or "//" in trimmed_path
        or any(segment in {".", ".."} for segment in trimmed_path.split("/"))
    ):
        raise ValueError("unsafe URL")

    path = parsed.path.rstrip("/") + "/" if trailing_slash else parsed.path
    host_for_netloc = (
        f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    )
    netloc = host_for_netloc if port is None else f"{host_for_netloc}:{port}"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))
