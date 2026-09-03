from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import Base, DouyinApiQuotaUsage
from apps.worker.douyin_api_quota import (
    DouyinQuotaExceeded,
    SHANGHAI_TIMEZONE,
    reserve_daily_quota,
    try_reserve_daily_quota,
)


def test_quota_model_declares_daily_identity_and_no_sensitive_columns() -> None:
    table = Base.metadata.tables["douyin_api_quota_usage"]
    assert {
        "environment",
        "app_id",
        "account_id",
        "endpoint_key",
        "business_date",
        "request_count",
        "effective_limit",
        "reset_at",
        "created_at",
        "updated_at",
    }.issubset(table.columns.keys())
    assert {
        "secret",
        "app_secret",
        "token",
        "payload",
        "phone",
        "telephone",
    }.isdisjoint(table.columns.keys())
    assert (
        "environment",
        "app_id",
        "account_id",
        "endpoint_key",
        "business_date",
    ) in {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }


def test_reserve_is_atomic_and_persists_through_a_short_factory_transaction(tmp_path) -> None:
    database_path = tmp_path / "douyin-quota.sqlite"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, future=True)
    observed_at = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)

    first = reserve_daily_quota(
        session_factory=factory,
        environment="production",
        app_id="app-1",
        account_id="account-1",
        endpoint_key="refunds",
        effective_limit=2,
        now=observed_at,
    )
    second = reserve_daily_quota(
        factory,
        "production",
        "app-1",
        "account-1",
        "refunds",
        2,
        now=observed_at,
    )

    assert (first.reserved, first.request_count, first.remaining) == (True, 1, 1)
    assert (second.reserved, second.request_count, second.remaining) == (True, 2, 0)
    with factory() as session:
        row = session.scalar(select(DouyinApiQuotaUsage))
        assert row is not None
        assert (row.request_count, row.business_date, row.effective_limit) == (
            2,
            date(2026, 9, 3),
            2,
        )


def test_exhausted_daily_quota_returns_next_shanghai_day_delay_without_reserving(
    db_session: Session,
) -> None:
    observed_at = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    for _ in range(2):
        reserve_daily_quota(
            db_session,
            environment="production",
            app_id="app-1",
            account_id="account-1",
            endpoint_key="refunds",
            effective_limit=2,
            now=observed_at,
        )

    with pytest.raises(DouyinQuotaExceeded) as raised:
        reserve_daily_quota(
            db_session,
            environment="production",
            app_id="app-1",
            account_id="account-1",
            endpoint_key="refunds",
            effective_limit=2,
            now=observed_at,
        )

    error = raised.value
    assert error.retry_after_seconds == 60 * 60
    assert error.reset_at == datetime(2026, 9, 4, tzinfo=SHANGHAI_TIMEZONE)
    assert "secret" not in str(error).lower()
    assert db_session.scalar(select(DouyinApiQuotaUsage.request_count)) == 2

    denied = try_reserve_daily_quota(
        db_session,
        environment="production",
        app_id="app-1",
        account_id="account-1",
        endpoint_key="refunds",
        effective_limit=2,
        now=observed_at,
    )
    assert (denied.reserved, denied.remaining, denied.retry_after_seconds) == (
        False,
        0,
        60 * 60,
    )
    assert db_session.scalar(select(DouyinApiQuotaUsage.request_count)) == 2


def test_quota_exception_sanitizes_endpoint_key(db_session: Session) -> None:
    observed_at = datetime(2026, 9, 3, 15, 0, tzinfo=UTC)
    endpoint_key = "refunds?token=top secret"
    reserve_daily_quota(
        db_session,
        environment="production",
        app_id="app-1",
        account_id="account-1",
        endpoint_key=endpoint_key,
        effective_limit=1,
        now=observed_at,
    )

    with pytest.raises(DouyinQuotaExceeded) as raised:
        reserve_daily_quota(
            db_session,
            environment="production",
            app_id="app-1",
            account_id="account-1",
            endpoint_key=endpoint_key,
            effective_limit=1,
            now=observed_at,
        )

    assert "secret" not in str(raised.value).lower()
    assert "secret" not in str(
        db_session.scalar(select(DouyinApiQuotaUsage.endpoint_key))
    ).lower()

def test_business_date_changes_at_shanghai_midnight(db_session: Session) -> None:
    reservation = reserve_daily_quota(
        db_session,
        environment="production",
        app_id="app-1",
        account_id="account-1",
        endpoint_key="refunds",
        effective_limit=90,
        now=datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
    )

    assert reservation.business_date == date(2026, 9, 4)
    assert reservation.reset_at == datetime(2026, 9, 5, tzinfo=SHANGHAI_TIMEZONE)


@pytest.mark.skipif(
    not os.getenv("DY_TEST_POSTGRES_URL"),
    reason="set DY_TEST_POSTGRES_URL to run PostgreSQL concurrency coverage",
)
def test_postgres_concurrent_reservations_never_exceed_final_slot() -> None:
    database_url = os.environ["DY_TEST_POSTGRES_URL"]
    engine = create_engine(database_url, future=True)
    DouyinApiQuotaUsage.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(bind=engine, autoflush=False, future=True)
    endpoint_key = f"concurrency-{uuid4().hex}"
    barrier = Barrier(2)

    def reserve_once() -> tuple[bool, int | None]:
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                result = reserve_daily_quota(
                    session,
                    environment="test",
                    app_id="app-concurrency",
                    account_id="account-concurrency",
                    endpoint_key=endpoint_key,
                    effective_limit=1,
                    now=datetime(2026, 9, 3, 15, 0, tzinfo=UTC),
                )
            except DouyinQuotaExceeded as error:
                session.rollback()
                return False, error.request_count
            session.commit()
            return result.reserved, result.request_count

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: reserve_once(), range(2)))

    assert sum(1 for reserved, _count in outcomes if reserved) == 1
    with factory() as session:
        row = session.scalar(
            select(DouyinApiQuotaUsage).where(
                DouyinApiQuotaUsage.endpoint_key == endpoint_key
            )
        )
        assert row is not None and row.request_count == 1
