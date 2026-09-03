"""Durable daily quota reservations for Douyin OpenAPI requests."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
import re
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DouyinApiQuotaUsage


SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
SHANGHAI_TIMEZONE_NAME = "Asia/Shanghai"
PRODUCTION_DOUYIN_APP_ID = "aws9nunf0av2egfw"
REFUND_DAILY_SOFT_LIMIT = 90
DEFAULT_DAILY_LIMITS = {"refunds": REFUND_DAILY_SOFT_LIMIT}

SessionFactory = Callable[[], Session]
SessionSource = Session | SessionFactory

_IDENTITY_COLUMNS = (
    "environment",
    "app_id",
    "account_id",
    "endpoint_key",
    "business_date",
)
_RETURN_COLUMNS = (
    "endpoint_key",
    "business_date",
    "request_count",
    "effective_limit",
    "reset_at",
)


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    """Outcome of one atomic daily reservation attempt."""

    endpoint_key: str
    business_date: date
    request_count: int
    effective_limit: int
    reset_at: datetime
    remaining: int
    reserved: bool
    retry_after_seconds: int | None = None

    @property
    def granted(self) -> bool:
        return self.reserved

    @property
    def allowed(self) -> bool:
        return self.reserved

    @property
    def remaining_requests(self) -> int:
        return self.remaining

    @property
    def retry_after(self) -> int | None:
        return self.retry_after_seconds


class DouyinQuotaExceeded(RuntimeError):
    """Raised before transport when a daily endpoint quota is exhausted."""

    def __init__(self, reservation: QuotaReservation) -> None:
        self.reservation = reservation
        self.endpoint_key = _safe_endpoint_key(reservation.endpoint_key)
        self.business_date = reservation.business_date
        self.request_count = reservation.request_count
        self.effective_limit = reservation.effective_limit
        self.reset_at = reservation.reset_at
        self.retry_after_seconds = int(reservation.retry_after_seconds or 0)
        super().__init__(
            "Douyin daily quota exhausted (2119003): "
            f"endpoint={self.endpoint_key}; "
            f"retry_after_seconds={self.retry_after_seconds}"
        )


# Keep descriptive aliases available to callers that use either naming style.
DouyinApiQuotaExceeded = DouyinQuotaExceeded
DouyinQuotaExceededError = DouyinQuotaExceeded
QuotaExceededError = DouyinQuotaExceeded


def _safe_endpoint_key(value: object) -> str:
    endpoint = str(value or "").strip().split("?", 1)[0].split("#", 1)[0]
    sanitized = re.sub(r"[^A-Za-z0-9._:/-]+", "_", endpoint)
    return sanitized[:128] or "unknown"


class DouyinApiQuotaLedger:
    """Open a short transaction for each reservation using a session factory."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self.session_factory = session_factory

    def reserve(
        self,
        *,
        environment: str,
        app_id: str,
        account_id: str,
        endpoint_key: str,
        effective_limit: int | None = None,
        limit: int | None = None,
        business_date: date | datetime | str | None = None,
        now: datetime | None = None,
    ) -> QuotaReservation:
        return reserve_daily_quota(
            session_factory=self.session_factory,
            environment=environment,
            app_id=app_id,
            account_id=account_id,
            endpoint_key=endpoint_key,
            effective_limit=effective_limit,
            limit=limit,
            business_date=business_date,
            now=now,
        )

    def try_reserve(
        self,
        *,
        environment: str,
        app_id: str,
        account_id: str,
        endpoint_key: str,
        effective_limit: int | None = None,
        limit: int | None = None,
        business_date: date | datetime | str | None = None,
        now: datetime | None = None,
    ) -> QuotaReservation:
        return try_reserve_daily_quota(
            session_factory=self.session_factory,
            environment=environment,
            app_id=app_id,
            account_id=account_id,
            endpoint_key=endpoint_key,
            effective_limit=effective_limit,
            limit=limit,
            business_date=business_date,
            now=now,
        )


def reserve_daily_quota(
    session: Session | SessionFactory | None = None,
    environment: str | None = None,
    app_id: str | None = None,
    account_id: str | None = None,
    endpoint_key: str | None = None,
    effective_limit: int | None = None,
    *,
    session_factory: SessionFactory | None = None,
    limit: int | None = None,
    business_date: date | datetime | str | None = None,
    now: datetime | None = None,
    raise_on_exhausted: bool = True,
) -> QuotaReservation:
    """Atomically reserve one request from one Shanghai business day.

    Passing a ``Session`` executes one statement in the caller's transaction.
    Passing a session factory opens and commits a short transaction, which is
    the preferred boundary before making an upstream HTTP request.
    """

    source = session_factory if session_factory is not None else session
    if source is None:
        raise TypeError("a SQLAlchemy Session or session_factory is required")

    identity, values, observed_at = _reservation_inputs(
        environment=environment,
        app_id=app_id,
        account_id=account_id,
        endpoint_key=endpoint_key,
        effective_limit=effective_limit,
        limit=limit,
        business_date=business_date,
        now=now,
    )

    if isinstance(source, Session):
        reservation = _reserve_in_session(
            source,
            identity=identity,
            values=values,
            observed_at=observed_at,
        )
    else:
        if not callable(source):
            raise TypeError("session must be a SQLAlchemy Session or callable factory")
        with _short_session(source) as managed_session:
            reservation = _reserve_in_session(
                managed_session,
                identity=identity,
                values=values,
                observed_at=observed_at,
            )

    if not reservation.reserved and raise_on_exhausted:
        raise DouyinQuotaExceeded(reservation)
    return reservation


def try_reserve_daily_quota(
    session: Session | SessionFactory | None = None,
    environment: str | None = None,
    app_id: str | None = None,
    account_id: str | None = None,
    endpoint_key: str | None = None,
    effective_limit: int | None = None,
    *,
    session_factory: SessionFactory | None = None,
    limit: int | None = None,
    business_date: date | datetime | str | None = None,
    now: datetime | None = None,
) -> QuotaReservation:
    """Return a non-raising result for callers that need to inspect denial."""

    return reserve_daily_quota(
        session,
        environment,
        app_id,
        account_id,
        endpoint_key,
        effective_limit,
        session_factory=session_factory,
        limit=limit,
        business_date=business_date,
        now=now,
        raise_on_exhausted=False,
    )


reserve_quota = reserve_daily_quota


def _reserve_in_session(
    session: Session,
    *,
    identity: dict[str, object],
    values: dict[str, object],
    observed_at: datetime,
) -> QuotaReservation:
    table = DouyinApiQuotaUsage.__table__
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        insert_builder = postgresql_insert(table)
    elif dialect_name == "sqlite":
        insert_builder = sqlite_insert(table)
    else:
        raise RuntimeError(
            "Douyin API quota reservations require PostgreSQL or SQLite"
        )

    insert_statement = insert_builder.values(**values)
    excluded = insert_statement.excluded
    statement = insert_statement.on_conflict_do_update(
        index_elements=[table.c[column] for column in _IDENTITY_COLUMNS],
        set_={
            "request_count": table.c.request_count + 1,
            "effective_limit": excluded.effective_limit,
            "reset_at": excluded.reset_at,
            "updated_at": excluded.updated_at,
        },
        where=table.c.request_count < excluded.effective_limit,
    ).returning(*(table.c[column] for column in _RETURN_COLUMNS))
    row = session.execute(statement).mappings().first()

    if row is not None:
        return _reservation_from_row(
            row,
            reserved=True,
            observed_at=observed_at,
        )

    existing = session.execute(
        select(*(table.c[column] for column in _RETURN_COLUMNS)).where(
            *(table.c[column] == identity[column] for column in _IDENTITY_COLUMNS)
        )
    ).mappings().one_or_none()
    if existing is None:
        raise RuntimeError("quota reservation row disappeared during atomic reserve")
    return _reservation_from_row(
        existing,
        reserved=False,
        observed_at=observed_at,
    )


def _reservation_inputs(
    *,
    environment: str | None,
    app_id: str | None,
    account_id: str | None,
    endpoint_key: str | None,
    effective_limit: int | None,
    limit: int | None,
    business_date: date | datetime | str | None,
    now: datetime | None,
) -> tuple[dict[str, object], dict[str, object], datetime]:
    clean_environment = _required_text(environment, "environment")
    clean_app_id = _required_text(app_id, "app_id")
    clean_account_id = _required_text(account_id, "account_id")
    clean_endpoint_key = _safe_endpoint_key(_required_text(endpoint_key, "endpoint_key"))
    clean_limit = _effective_limit(effective_limit, limit)
    local_now = _as_shanghai(now)
    clean_business_date = _business_date(business_date, local_now=local_now)
    reset_at = _next_reset_at(clean_business_date)
    observed_at = local_now.astimezone(UTC)
    identity = {
        "environment": clean_environment,
        "app_id": clean_app_id,
        "account_id": clean_account_id,
        "endpoint_key": clean_endpoint_key,
        "business_date": clean_business_date,
    }
    values = {
        **identity,
        "request_count": 1,
        "effective_limit": clean_limit,
        "reset_at": reset_at,
        "created_at": observed_at,
        "updated_at": observed_at,
    }
    return identity, values, observed_at


def _reservation_from_row(
    row: Any,
    *,
    reserved: bool,
    observed_at: datetime,
) -> QuotaReservation:
    endpoint_key = str(row["endpoint_key"])
    business_day = row["business_date"]
    if not isinstance(business_day, date):
        business_day = date.fromisoformat(str(business_day))
    request_count = int(row["request_count"])
    effective_limit = int(row["effective_limit"])
    reset_at = _as_shanghai(row["reset_at"])
    retry_after = (
        None
        if reserved
        else _retry_after_seconds(reset_at, observed_at)
    )
    return QuotaReservation(
        endpoint_key=endpoint_key,
        business_date=business_day,
        request_count=request_count,
        effective_limit=effective_limit,
        reset_at=reset_at,
        remaining=max(effective_limit - request_count, 0),
        reserved=reserved,
        retry_after_seconds=retry_after,
    )


@contextmanager
def _short_session(session_factory: SessionFactory) -> Iterator[Session]:
    managed_session = session_factory()
    transaction = (
        nullcontext(managed_session)
        if managed_session.in_transaction()
        else managed_session.begin()
    )
    try:
        with transaction:
            yield managed_session
    finally:
        managed_session.close()


def _required_text(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


def _effective_limit(effective_limit: int | None, limit: int | None) -> int:
    if effective_limit is not None and limit is not None and effective_limit != limit:
        raise ValueError("effective_limit and limit must match when both are provided")
    value = effective_limit if effective_limit is not None else limit
    if value is None:
        raise ValueError("effective_limit is required")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("effective_limit must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError("effective_limit must be a positive integer")
    return normalized


def _as_shanghai(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(SHANGHAI_TIMEZONE)
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TIMEZONE)
    return value.astimezone(SHANGHAI_TIMEZONE)


def _business_date(
    value: date | datetime | str | None,
    *,
    local_now: datetime,
) -> date:
    if value is None:
        return local_now.date()
    if isinstance(value, datetime):
        return _as_shanghai(value).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("business_date must be an ISO date") from exc


def _next_reset_at(business_day: date) -> datetime:
    return datetime.combine(
        business_day + timedelta(days=1),
        time.min,
        tzinfo=SHANGHAI_TIMEZONE,
    )


def _retry_after_seconds(reset_at: datetime, observed_at: datetime) -> int:
    seconds = (reset_at - observed_at.astimezone(SHANGHAI_TIMEZONE)).total_seconds()
    return max(1, int(ceil(seconds)))
