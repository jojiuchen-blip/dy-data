from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
import inspect
import json
import math
import os
import re
import threading
import time
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

PRODUCTION_APP_ID = "aws9nunf0av2egfw"
PRODUCTION_DOUYIN_APP_ID = PRODUCTION_APP_ID
DEFAULT_REQUEST_SLEEP_SECONDS = 0.5
SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")

ENDPOINT_ORDERS = "orders"
ENDPOINT_VERIFY_RECORDS = "verify_records"
ENDPOINT_CERTIFICATES = "certificates"
ENDPOINT_REFUNDS = "refunds"
ENDPOINT_SHOP_POIS = "shop_pois"
ENDPOINT_CLUES = "clues"
ENDPOINT_PRODUCT_LIST = "product_list"
ENDPOINT_PRODUCT_DETAIL = "product_detail"


class DouyinApiError(RuntimeError):
    """Base error for the Douyin client and its request governor."""


class QuotaConfigurationError(ValueError):
    """Raised when quota configuration cannot be interpreted safely."""


class QuotaStoreError(RuntimeError):
    """Raised when a durable quota reservation cannot be completed."""


class DouyinQuotaExceeded(DouyinApiError):
    """A daily soft quota rejected a request before transport."""

    error_code = "douyin_rate_limited"

    def __init__(self, endpoint: str, retry_after_seconds: float | int) -> None:
        self.endpoint = sanitize_endpoint(endpoint)
        self.retry_after_seconds = max(1, int(math.ceil(float(retry_after_seconds))))
        self.retry_after_marker = f"retry_after_seconds={self.retry_after_seconds}"
        super().__init__(
            "Douyin API quota exhausted: error_code=2119003, 请求太过频繁, "
            f"endpoint={self.endpoint}, {self.retry_after_marker}"
        )


# Names used by callers that prefer a generic quota-error term.
DouyinQuotaError = DouyinQuotaExceeded
QuotaExceededError = DouyinQuotaExceeded


@dataclass(frozen=True)
class EndpointLimit:
    """An upstream quota and the soft value used by the local governor."""

    requests_per_window: float
    window_seconds: float
    soft_quota: float | None = None
    daily_quota: int | None = None

    def __post_init__(self) -> None:
        if self.requests_per_window <= 0:
            raise QuotaConfigurationError("requests_per_window must be positive")
        if self.window_seconds <= 0:
            raise QuotaConfigurationError("window_seconds must be positive")
        if self.soft_quota is not None and (
            self.soft_quota <= 0 or self.soft_quota > self.requests_per_window
        ):
            raise QuotaConfigurationError("soft_quota must be between 0 and the platform quota")
        if self.daily_quota is not None and (
            self.daily_quota <= 0 or self.daily_quota > self.effective_quota
        ):
            raise QuotaConfigurationError("daily_quota must be between 0 and the effective quota")

    @property
    def platform_quota(self) -> float:
        return self.requests_per_window

    @property
    def quota(self) -> float:
        return self.requests_per_window

    @property
    def effective_quota(self) -> float:
        return self.soft_quota if self.soft_quota is not None else self.requests_per_window

    @property
    def interval_seconds(self) -> float:
        # Daily budgets are enforced by the durable ledger. Spreading them
        # uniformly across 24 hours would turn a multi-page pull into a
        # day-long job without providing additional quota safety.
        if self.daily_quota is not None and self.window_seconds >= 86400:
            return 0.0
        return self.window_seconds / self.effective_quota


@dataclass(frozen=True)
class DouyinEndpointProfile:
    """Application-specific endpoint limits with a conservative fallback."""

    app_id: str
    endpoints: Mapping[str, EndpointLimit]
    default_interval_seconds: float = DEFAULT_REQUEST_SLEEP_SECONDS

    def __post_init__(self) -> None:
        if self.default_interval_seconds < 0:
            raise QuotaConfigurationError("default request interval cannot be negative")
        normalized = {
            sanitize_endpoint(key): value
            for key, value in self.endpoints.items()
        }
        object.__setattr__(self, "endpoints", MappingProxyType(normalized))

    @property
    def endpoint_limits(self) -> Mapping[str, EndpointLimit]:
        return self.endpoints

    @property
    def limits(self) -> Mapping[str, EndpointLimit]:
        return self.endpoints

    def limit_for(self, endpoint_key: str) -> EndpointLimit | None:
        return self.endpoints.get(sanitize_endpoint(endpoint_key))


PRODUCTION_ENDPOINT_LIMITS: Mapping[str, EndpointLimit] = MappingProxyType(
    {
        ENDPOINT_ORDERS: EndpointLimit(requests_per_window=20, window_seconds=1),
        ENDPOINT_VERIFY_RECORDS: EndpointLimit(requests_per_window=100, window_seconds=1),
        ENDPOINT_CERTIFICATES: EndpointLimit(requests_per_window=35, window_seconds=1),
        ENDPOINT_REFUNDS: EndpointLimit(
            requests_per_window=100,
            window_seconds=86400,
            soft_quota=90,
            daily_quota=90,
        ),
        ENDPOINT_SHOP_POIS: EndpointLimit(requests_per_window=400, window_seconds=1),
        ENDPOINT_CLUES: EndpointLimit(
            requests_per_window=100,
            window_seconds=60,
            soft_quota=90,
        ),
        ENDPOINT_PRODUCT_LIST: EndpointLimit(requests_per_window=20, window_seconds=1),
        ENDPOINT_PRODUCT_DETAIL: EndpointLimit(requests_per_window=20, window_seconds=1),
    }
)

PRODUCTION_ENDPOINT_PROFILE = PRODUCTION_ENDPOINT_LIMITS
DOUYIN_ENDPOINT_LIMITS = PRODUCTION_ENDPOINT_LIMITS


_KNOWN_ENDPOINT_PATHS: Mapping[str, str] = MappingProxyType(
    {
        "/oauth/client_token": "oauth_client_token",
        "/goodlife/v1/trade/order/query": ENDPOINT_ORDERS,
        "/goodlife/v1/fulfilment/certificate/verify_record/query": ENDPOINT_VERIFY_RECORDS,
        "/goodlife/v1/fulfilment/certificate/query": ENDPOINT_CERTIFICATES,
        "/goodlife/v1/akte/after_sale/order/query": ENDPOINT_REFUNDS,
        "/goodlife/v1/shop/poi/query": ENDPOINT_SHOP_POIS,
        "/goodlife/v2/craftsman_openapi/merchat/craftsman/bind_info/all": "craftsman_bind_info",
        "/goodlife/v1/open_api/crm/clue/query": ENDPOINT_CLUES,
        "/goodlife/v1/goods/product/online/query": ENDPOINT_PRODUCT_LIST,
        "/goodlife/v1/goods/product/online/get": ENDPOINT_PRODUCT_DETAIL,
        "/goodlife/v1/open/common_biz/crypto/decrypt/batch": "cipher_decrypt",
        "/goodlife/v1/open/common_biz/crypto/decrypt_mask/batch": "cipher_decrypt_mask",
    }
)


def sanitize_endpoint(endpoint: Any) -> str:
    """Keep endpoint diagnostics free of query values and control characters."""

    value = str(endpoint or "").strip()
    try:
        parsed = urlsplit(value)
        if "://" in value or value.startswith("//"):
            value = f"{parsed.hostname or ''}{parsed.path or '/'}"
        else:
            value = value.split("?", 1)[0].split("#", 1)[0]
    except ValueError:
        value = value.split("?", 1)[0].split("#", 1)[0]
    value = re.sub(r"[^A-Za-z0-9._:/-]+", "_", value)
    return value[:240] or "unknown"


def _normalized_path(url: str) -> str:
    try:
        parsed = urlsplit(str(url))
        path = parsed.path or "/"
    except ValueError:
        path = str(url).split("?", 1)[0].split("#", 1)[0]
    segments = [segment for segment in path.split("/") if segment]
    return "/" + "/".join(segments)


def stable_endpoint_key(url: str, method: str | None = None) -> str:
    """Return a deterministic key without query, body, or credential data."""

    path = _normalized_path(url)
    known = _KNOWN_ENDPOINT_PATHS.get(path)
    if known:
        return known
    try:
        host = (urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        host = ""
    prefix = f"{host}{path}" if host else path
    return sanitize_endpoint(f"unknown:{prefix}")


endpoint_key_for_url = stable_endpoint_key
get_endpoint_key = stable_endpoint_key


def endpoint_profile_for_app(
    app_id: str | None,
    *,
    default_interval_seconds: float | None = None,
    limits_json: str | Mapping[str, Any] | None = None,
) -> DouyinEndpointProfile:
    """Build one profile, applying explicit environment-style overrides."""

    app_id_value = str(app_id or "").strip()
    default_interval = _resolve_default_interval(default_interval_seconds)
    base_limits = dict(PRODUCTION_ENDPOINT_LIMITS) if app_id_value == PRODUCTION_APP_ID else {}
    overrides = _parse_limits_json(limits_json)
    merged = _merge_limit_overrides(base_limits, overrides)
    return DouyinEndpointProfile(
        app_id=app_id_value,
        endpoints=merged,
        default_interval_seconds=default_interval,
    )


get_endpoint_profile = endpoint_profile_for_app
build_endpoint_profile = endpoint_profile_for_app


def _resolve_default_interval(value: float | None) -> float:
    if value is not None:
        return _positive_or_zero_float(value, "default request interval")
    raw = os.getenv("DOUYIN_REQUEST_SLEEP_SECONDS")
    if raw in (None, ""):
        return DEFAULT_REQUEST_SLEEP_SECONDS
    return _positive_or_zero_float(raw, "DOUYIN_REQUEST_SLEEP_SECONDS")


def _positive_or_zero_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise QuotaConfigurationError(f"{label} must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise QuotaConfigurationError(f"{label} must be a finite non-negative number")
    return parsed


def _parse_limits_json(value: str | Mapping[str, Any] | None) -> Mapping[str, Any]:
    raw: Any = value
    if raw is None:
        raw = os.getenv("DOUYIN_API_LIMITS_JSON")
    if raw in (None, ""):
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QuotaConfigurationError("DOUYIN_API_LIMITS_JSON must be valid JSON") from exc
    if not isinstance(raw, Mapping):
        raise QuotaConfigurationError("DOUYIN_API_LIMITS_JSON must be a JSON object")
    endpoints = raw.get("endpoints", raw)
    if not isinstance(endpoints, Mapping):
        raise QuotaConfigurationError("quota endpoints configuration must be an object")
    return endpoints


def _merge_limit_overrides(
    base_limits: Mapping[str, EndpointLimit],
    overrides: Mapping[str, Any],
) -> dict[str, EndpointLimit]:
    merged = dict(base_limits)
    for raw_key, raw_value in overrides.items():
        key = sanitize_endpoint(raw_key)
        if not isinstance(raw_value, Mapping):
            raise QuotaConfigurationError(f"quota configuration for {key} must be an object")
        existing = merged.get(key)
        if existing is None:
            raise QuotaConfigurationError(
                f"cannot configure unverified endpoint {key}; add it to the reviewed app profile first"
            )
        requests_per_window = _override_number(
            raw_value,
            "requests_per_window",
            "quota",
            "max_requests",
            default=existing.requests_per_window if existing else None,
        )
        window_seconds = _override_number(
            raw_value,
            "window_seconds",
            "window",
            default=existing.window_seconds if existing else None,
        )
        if requests_per_window is None or window_seconds is None:
            raise QuotaConfigurationError(
                f"quota configuration for {key} requires requests_per_window and window_seconds"
            )
        soft_quota = _override_number(
            raw_value,
            "soft_quota",
            "effective_quota",
            default=existing.soft_quota if existing else None,
            allow_none=True,
        )
        daily_quota_raw = raw_value.get("daily_quota", existing.daily_quota if existing else None)
        daily_quota = _optional_positive_int(daily_quota_raw, f"daily_quota for {key}")
        merged[key] = EndpointLimit(
            requests_per_window=requests_per_window,
            window_seconds=window_seconds,
            soft_quota=soft_quota,
            daily_quota=daily_quota,
        )
        configured = merged[key]
        if configured.requests_per_window > existing.requests_per_window:
            raise QuotaConfigurationError(f"quota override for {key} cannot raise requests_per_window")
        if configured.window_seconds < existing.window_seconds:
            raise QuotaConfigurationError(f"quota override for {key} cannot shorten window_seconds")
        if configured.effective_quota > existing.effective_quota:
            raise QuotaConfigurationError(f"quota override for {key} cannot raise effective quota")
        if existing.daily_quota is not None and (
            configured.daily_quota is None or configured.daily_quota > existing.daily_quota
        ):
            raise QuotaConfigurationError(f"quota override for {key} cannot raise or remove daily_quota")
    return merged


def _override_number(
    value: Mapping[str, Any],
    *keys: str,
    default: float | None,
    allow_none: bool = False,
) -> float | None:
    selected = next((value[key] for key in keys if key in value), default)
    if selected is None and allow_none:
        return None
    if selected is None:
        return None
    try:
        parsed = float(selected)
    except (TypeError, ValueError) as exc:
        raise QuotaConfigurationError(f"{keys[0]} must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise QuotaConfigurationError(f"{keys[0]} must be a positive finite number")
    return parsed


def _optional_positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise QuotaConfigurationError(f"{label} must be a positive integer") from exc
    if parsed <= 0 or str(value).strip() not in {str(parsed), f"{parsed}.0"}:
        raise QuotaConfigurationError(f"{label} must be a positive integer")
    return parsed


class MonotonicRequestGovernor:
    """Process-local pacing governor using an injectable monotonic clock."""

    def __init__(
        self,
        profile: DouyinEndpointProfile | Mapping[str, EndpointLimit] | None = None,
        *,
        default_interval_seconds: float | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if profile is None:
            profile = DouyinEndpointProfile(
                app_id="",
                endpoints={},
                default_interval_seconds=_resolve_default_interval(default_interval_seconds),
            )
        elif isinstance(profile, DouyinEndpointProfile):
            if default_interval_seconds is not None:
                profile = DouyinEndpointProfile(
                    app_id=profile.app_id,
                    endpoints=profile.endpoints,
                    default_interval_seconds=_resolve_default_interval(default_interval_seconds),
                )
        else:
            profile = DouyinEndpointProfile(
                app_id="",
                endpoints=profile,
                default_interval_seconds=_resolve_default_interval(default_interval_seconds),
            )
        self.profile = profile
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self._next_allowed_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, endpoint_key: str) -> None:
        endpoint = sanitize_endpoint(endpoint_key)
        limit = self.profile.limit_for(endpoint)
        interval = self.profile.default_interval_seconds
        if limit is not None:
            interval = max(interval, limit.interval_seconds)
        if interval <= 0:
            return
        now = float(self.clock())
        with self._lock:
            wait_seconds = max(0.0, self._next_allowed_at.get(endpoint, now) - now)
            self._next_allowed_at[endpoint] = max(now, self._next_allowed_at.get(endpoint, now)) + interval
        if wait_seconds > 0:
            self.sleep(wait_seconds)


ProcessLocalRequestGovernor = MonotonicRequestGovernor


class RequestGovernor(MonotonicRequestGovernor):
    """Pace requests and reserve configured durable daily quotas."""

    def __init__(
        self,
        profile: DouyinEndpointProfile | Mapping[str, EndpointLimit] | None = None,
        *,
        app_id: str = "",
        account_id: str = "",
        environment: str = "default",
        quota_store: Any | None = None,
        default_interval_seconds: float | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        wall_clock: Callable[[], datetime | float | int] | None = None,
    ) -> None:
        self.app_id = str(app_id or "").strip()
        self.account_id = str(account_id or "").strip()
        self.environment = str(environment or "default").strip() or "default"
        if profile is None:
            profile = endpoint_profile_for_app(
                self.app_id,
                default_interval_seconds=default_interval_seconds,
            )
        super().__init__(
            profile,
            default_interval_seconds=default_interval_seconds,
            clock=clock,
            sleep=sleep,
        )
        self.quota_store = quota_store
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))

    def acquire(self, endpoint_key: str) -> None:
        endpoint = sanitize_endpoint(endpoint_key)
        limit = self.profile.limit_for(endpoint)
        if limit is not None and limit.daily_quota is not None and self.quota_store is not None:
            now = _coerce_wall_datetime(self.wall_clock())
            allowed = _reserve_quota(
                self.quota_store,
                environment=self.environment,
                app_id=self.app_id,
                account_id=self.account_id,
                endpoint_key=endpoint,
                business_date=now.astimezone(SHANGHAI_TIMEZONE).date(),
                quota=limit.daily_quota,
                now=now,
            )
            if not allowed:
                raise DouyinQuotaExceeded(endpoint, seconds_until_next_shanghai_day(now))
        super().acquire(endpoint)


QuotaRequestGovernor = RequestGovernor
DouyinRequestGovernor = RequestGovernor


def _reserve_quota(store: Any, **kwargs: Any) -> bool:
    reserve = getattr(store, "try_reserve", None) or getattr(store, "reserve", None)
    if reserve is None and callable(store):
        reserve = store
    if reserve is None:
        raise QuotaStoreError("quota_store must provide reserve()")
    try:
        result = _call_reserver(reserve, kwargs)
    except DouyinQuotaExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed around the persistence boundary.
        retry_after = getattr(exc, "retry_after_seconds", None)
        if retry_after is not None:
            endpoint = getattr(exc, "endpoint", None) or getattr(exc, "endpoint_key", kwargs["endpoint_key"])
            raise DouyinQuotaExceeded(endpoint, retry_after) from exc
        raise QuotaStoreError("durable Douyin quota reservation failed") from exc
    if hasattr(result, "allowed"):
        return bool(result.allowed)
    return bool(result)


def _call_reserver(reserve: Callable[..., Any], kwargs: Mapping[str, Any]) -> Any:
    """Adapt the local store protocol to the worker ledger's richer protocol."""

    try:
        parameters = inspect.signature(reserve).parameters
    except (TypeError, ValueError):
        return reserve(**kwargs)
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return reserve(**kwargs)

    accepted = {key: value for key, value in kwargs.items() if key in parameters}
    if "quota" in parameters:
        accepted["quota"] = kwargs["quota"]
    elif "effective_limit" in parameters:
        accepted["effective_limit"] = kwargs["quota"]
    elif "limit" in parameters:
        accepted["limit"] = kwargs["quota"]
    return reserve(**accepted)


def seconds_until_next_shanghai_day(value: datetime | float | int) -> int:
    now = _coerce_wall_datetime(value).astimezone(SHANGHAI_TIMEZONE)
    next_day = datetime.combine(
        now.date() + timedelta(days=1),
        datetime_time.min,
        tzinfo=SHANGHAI_TIMEZONE,
    )
    return max(1, int(math.ceil((next_day - now).total_seconds())))


def _coerce_wall_datetime(value: datetime | float | int) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise QuotaConfigurationError("wall_clock must return a datetime or Unix timestamp") from exc


class InMemoryDailyQuotaStore:
    """Deterministic quota store for tests and local dry runs."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str, str, str, date], int] = {}
        self._lock = threading.Lock()

    def reserve(
        self,
        *,
        environment: str,
        app_id: str,
        account_id: str,
        endpoint_key: str,
        business_date: date,
        quota: int,
    ) -> bool:
        key = (environment, app_id, account_id, endpoint_key, business_date)
        with self._lock:
            current = self._counts.get(key, 0)
            if current >= quota:
                return False
            self._counts[key] = current + 1
            return True

    def count(
        self,
        *,
        environment: str,
        app_id: str,
        account_id: str,
        endpoint_key: str,
        business_date: date,
    ) -> int:
        return self._counts.get((environment, app_id, account_id, endpoint_key, business_date), 0)


def build_request_governor(
    *,
    app_id: str,
    account_id: str,
    environment: str | None = None,
    quota_store: Any | None = None,
    default_interval_seconds: float | None = None,
    limits_json: str | Mapping[str, Any] | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    wall_clock: Callable[[], datetime | float | int] | None = None,
) -> RequestGovernor:
    """Construct the client-injectable governor without opening a database."""

    profile = endpoint_profile_for_app(
        app_id,
        default_interval_seconds=default_interval_seconds,
        limits_json=limits_json,
    )
    return RequestGovernor(
        profile,
        app_id=app_id,
        account_id=account_id,
        environment=environment or os.getenv("DY_ENVIRONMENT", "default"),
        quota_store=quota_store,
        clock=clock,
        sleep=sleep,
        wall_clock=wall_clock,
    )


build_douyin_request_governor = build_request_governor
create_request_governor = build_request_governor


__all__ = [
    "DEFAULT_REQUEST_SLEEP_SECONDS",
    "DOUYIN_ENDPOINT_LIMITS",
    "DouyinApiError",
    "DouyinEndpointProfile",
    "DouyinQuotaError",
    "DouyinQuotaExceeded",
    "DouyinRequestGovernor",
    "ENDPOINT_CERTIFICATES",
    "ENDPOINT_CLUES",
    "ENDPOINT_ORDERS",
    "ENDPOINT_PRODUCT_DETAIL",
    "ENDPOINT_PRODUCT_LIST",
    "ENDPOINT_REFUNDS",
    "ENDPOINT_SHOP_POIS",
    "ENDPOINT_VERIFY_RECORDS",
    "EndpointLimit",
    "InMemoryDailyQuotaStore",
    "MonotonicRequestGovernor",
    "ProcessLocalRequestGovernor",
    "PRODUCTION_APP_ID",
    "PRODUCTION_DOUYIN_APP_ID",
    "PRODUCTION_ENDPOINT_LIMITS",
    "PRODUCTION_ENDPOINT_PROFILE",
    "QuotaConfigurationError",
    "QuotaExceededError",
    "QuotaRequestGovernor",
    "QuotaStoreError",
    "RequestGovernor",
    "build_douyin_request_governor",
    "build_endpoint_profile",
    "build_request_governor",
    "create_request_governor",
    "endpoint_key_for_url",
    "endpoint_profile_for_app",
    "get_endpoint_key",
    "get_endpoint_profile",
    "sanitize_endpoint",
    "seconds_until_next_shanghai_day",
    "stable_endpoint_key",
]
