"""Opt-in PostgreSQL concurrency evidence for incremental settlement.

Only ``DYDATA_T12_TEST_DATABASE_URL`` is read.  The fixture validates that URL
points at the dedicated loopback container and uses an isolated schema so the
test cannot touch application tables or any generic database URL.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, event, func, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import normalize_database_url
from apps.api.dy_api.models import (
    Base,
    DataQualityIssue,
    DimAwemeAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    DouyinRefundEvent,
    JobImpact,
    RawAwemeBinding,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementScopeRule,
    SkuFeeRule,
)
from apps.worker.settlement import settle_impacted_coupons


POSTGRES_ENV_NAME = "DYDATA_T12_TEST_DATABASE_URL"
POSTGRES_URL = os.getenv(POSTGRES_ENV_NAME)
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason=f"set {POSTGRES_ENV_NAME} to the dedicated disposable PostgreSQL database",
)


def _validated_postgres_url(raw_url: str) -> URL:
    url = make_url(normalize_database_url(raw_url))
    if not url.drivername.startswith("postgresql+"):
        raise RuntimeError("settlement PostgreSQL evidence requires a PostgreSQL driver")
    if url.host != "127.0.0.1":
        raise RuntimeError("settlement test database must use a loopback host")
    if url.port != 55432:
        raise RuntimeError("settlement test database must use the dedicated port 55432")
    if url.database != "dydata_t12":
        raise RuntimeError("settlement test database must be named dydata_t12")
    if url.username != "dydata_t12":
        raise RuntimeError("settlement test database must use the dedicated test role")
    return url


@pytest.fixture(scope="module")
def postgres_stack() -> tuple[object, sessionmaker[Session]]:
    assert POSTGRES_URL is not None
    url = _validated_postgres_url(POSTGRES_URL)
    schema = f"t33_settlement_{uuid4().hex[:12]}"
    admin_engine = create_engine(url, future=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            url,
            connect_args={
                "options": (
                    f"-c search_path={schema} "
                    "-c lock_timeout=1000 "
                    "-c statement_timeout=10000"
                )
            },
            future=True,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        yield engine, factory
    finally:
        admin_engine.dispose()
        if "engine" in locals():
            engine.dispose()
        cleanup_engine = create_engine(url, future=True)
        with cleanup_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        cleanup_engine.dispose()


@pytest.fixture(scope="module")
def postgres_migration_schema() -> tuple[object, str, Config]:
    """Run the real online 0033 -> 0034 -> 0033 roundtrip in an isolated schema."""

    assert POSTGRES_URL is not None
    url = _validated_postgres_url(POSTGRES_URL)
    schema = f"t33_migration_{uuid4().hex[:12]}"
    admin_engine = create_engine(url, future=True)
    migration_url = url.set(
        query={
            **dict(url.query),
            "options": f"-c search_path={schema}",
        }
    )
    migration_url_text = migration_url.render_as_string(hide_password=False)
    previous_dy_url = os.environ.get("DY_DATABASE_URL")
    engine = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            # The dedicated T12 database may already have a public
            # alembic_version. Seed an empty version table inside the random
            # schema so the online command cannot silently reuse public history.
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".alembic_version '
                    '(version_num VARCHAR(32) NOT NULL)'
                )
            )
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option(
            "script_location",
            str(Path(__file__).resolve().parents[1] / "alembic"),
        )
        config.set_main_option("path_separator", "os")
        config.set_main_option(
            "sqlalchemy.url",
            migration_url_text.replace("%", "%%"),
        )
        os.environ["DY_DATABASE_URL"] = migration_url_text
        command.upgrade(config, "20260806_0033")
        command.upgrade(config, "20260806_0034")
        engine = create_engine(
            migration_url,
            connect_args={"options": f"-c search_path={schema}"},
            future=True,
        )
        yield engine, schema, config
    finally:
        admin_engine.dispose()
        if engine is not None:
            try:
                with engine.connect() as connection:
                    current_revision = connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one_or_none()
                if current_revision == "20260806_0034":
                    command.downgrade(config, "20260806_0033")
            except Exception:
                # Always drop the isolated schema even if migration cleanup
                # itself fails; pytest still reports the original assertion.
                pass
        if previous_dy_url is None:
            os.environ.pop("DY_DATABASE_URL", None)
        else:
            os.environ["DY_DATABASE_URL"] = previous_dy_url
        if engine is not None:
            engine.dispose()
        cleanup_engine = create_engine(url, future=True)
        with cleanup_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        cleanup_engine.dispose()


def test_postgres_online_0034_roundtrip_schema_parity(
    postgres_migration_schema: tuple[object, str, Config],
) -> None:
    engine, schema, config = postgres_migration_schema
    inspector = inspect(engine)
    result_columns = {
        column["name"]: column["nullable"]
        for column in inspector.get_columns("settlement_fee_result", schema=schema)
    }
    adjustment_columns = {
        column["name"]: column["nullable"]
        for column in inspector.get_columns("settlement_fee_adjustment", schema=schema)
    }
    assert result_columns["input_fingerprint"] is True
    assert {
        "uk_settlement_fee_result_calculation_run",
        "uk_settlement_fee_adjustment_refund_result_direction",
    } <= {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "settlement_fee_result", schema=schema
        )
    } | {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "settlement_fee_adjustment", schema=schema
        )
    }
    assert {
        "ix_job_impacts_source_run_id_id",
        "ix_raw_douyin_orders_intention_poi_id_order_id",
        "ix_raw_douyin_order_coupons_order_id_coupon_id",
        "ix_raw_douyin_verify_records_poi_id_coupon_id",
    } <= {
        index["name"]
        for table in (
            "job_impacts",
            "raw_douyin_orders",
            "raw_douyin_order_coupons",
            "raw_douyin_verify_records",
        )
        for index in inspector.get_indexes(table, schema=schema)
    }
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260806_0034"

    assert adjustment_columns["refund_event_id"] is True

    command.downgrade(config, "20260806_0033")
    downgraded = inspect(engine)
    assert "input_fingerprint" not in {
        column["name"]
        for column in downgraded.get_columns("settlement_fee_result", schema=schema)
    }
    assert "uk_settlement_fee_result_calculation_run" not in {
        constraint["name"]
        for constraint in downgraded.get_unique_constraints(
            "settlement_fee_result", schema=schema
        )
    }
    assert "uk_settlement_fee_adjustment_refund_result_direction" not in {
        constraint["name"]
        for constraint in downgraded.get_unique_constraints(
            "settlement_fee_adjustment", schema=schema
        )
    }
    downgraded_indexes = {
        index["name"]
        for table in (
            "job_impacts",
            "raw_douyin_orders",
            "raw_douyin_order_coupons",
            "raw_douyin_verify_records",
        )
        for index in downgraded.get_indexes(table, schema=schema)
    }
    assert {
        "ix_job_impacts_source_run_id_id",
        "ix_raw_douyin_orders_intention_poi_id_order_id",
        "ix_raw_douyin_order_coupons_order_id_coupon_id",
        "ix_raw_douyin_verify_records_poi_id_coupon_id",
    }.isdisjoint(downgraded_indexes)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260806_0033"


@pytest.fixture(autouse=True)
def clear_postgres_settlement_rows(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    with factory.begin() as session:
        for model in (
            SettlementFeeAdjustment,
            SettlementFeeResultCurrent,
            SettlementFeeResult,
            DataQualityIssue,
            JobImpact,
            DouyinRefundEvent,
            RawDouyinVerifyRecord,
            RawDouyinOrderCoupon,
            RawDouyinOrder,
            RawAwemeBinding,
            SkuFeeRule,
            SettlementScopeRule,
            DimSkuProductRule,
            DimStorePoiMapping,
            DimAwemeAccount,
            DimStore,
        ):
            session.execute(delete(model))
    yield
    with factory.begin() as session:
        for model in (
            SettlementFeeAdjustment,
            SettlementFeeResultCurrent,
            SettlementFeeResult,
            DataQualityIssue,
            JobImpact,
            DouyinRefundEvent,
            RawDouyinVerifyRecord,
            RawDouyinOrderCoupon,
            RawDouyinOrder,
            RawAwemeBinding,
            SkuFeeRule,
            SettlementScopeRule,
            DimSkuProductRule,
            DimStorePoiMapping,
            DimAwemeAccount,
            DimStore,
        ):
            session.execute(delete(model))


def _seed_coupon(session: Session, coupon_id: str = "pg-coupon") -> None:
    observed = datetime(2026, 8, 7, 10, tzinfo=timezone.utc)
    session.add_all(
        [
            DimStore(store_id="pg-store-sale", store_name="Sale"),
            DimStore(store_id="pg-store-verify", store_name="Verify"),
        ]
    )
    session.flush()
    session.add_all(
        [
            DimAwemeAccount(
                account_id="pg-owner-sale",
                nickname="Sale owner",
                store_id="pg-store-sale",
                binding_status="active",
            ),
            RawAwemeBinding(
                binding_key="pg-binding-owner-sale",
                douyin_nickname="Sale owner",
                account_id="pg-owner-sale",
                account_name="Sale owner",
                binding_status="active",
            ),
            DimStorePoiMapping(
                store_id="pg-store-verify",
                poi_id="pg-poi-verify",
                poi_name="Verify",
            ),
            DimSkuProductRule(
                sku_id="pg-sku-service",
                product_type="service",
                product_scope="service",
                is_service_product=True,
                is_active_product=True,
                owner_account_id="pg-owner-product",
                commission_rate=Decimal("0.1000"),
            ),
            SettlementScopeRule(
                scope_rule_version="pg-scope-v1",
                idempotency_key_hash="pg-scope-idempotency",
                request_payload_sha256="a" * 64,
                effective_month="2026-08",
                owner_account_id="pg-owner-product",
                sale_channel_normalized="live",
                is_active=True,
                created_by="test",
                change_reason="test",
            ),
            SkuFeeRule(
                rule_version="pg-fee-v1",
                idempotency_key_hash="pg-fee-idempotency",
                request_payload_sha256="b" * 64,
                sku_id="pg-sku-service",
                sku_name_snapshot="Service",
                product_scope_snapshot="service",
                product_type_snapshot="service",
                promotion_service_fee_rate=Decimal("0.100000"),
                management_service_fee_rate=Decimal("0.050000"),
                effective_date=date(2026, 8, 1),
                effective_at=observed,
                rule_status=1,
                created_by="test",
                change_reason="test",
                published_at=observed,
            ),
        ]
    )
    session.flush()
    order_id = f"pg-order-{coupon_id}"
    session.add(
        RawDouyinOrder(
            order_id=order_id,
            order_status="paid",
            order_status_normalized="paid",
            sku_id="pg-sku-service",
            product_name="Service",
            sale_channel="live",
            sale_channel_normalized="live",
            pay_time=observed,
            sale_time=observed,
            create_order_time=observed,
            paid_amount_cent=10000,
            order_paid_amount_cent=10000,
            owner_account_id="pg-owner-sale",
            owner_account_name="Sale owner",
        )
    )
    session.flush()
    session.add(
        RawDouyinOrderCoupon(
            coupon_id=coupon_id,
            order_id=order_id,
            raw_order_id=session.scalar(
                select(RawDouyinOrder.id).where(RawDouyinOrder.order_id == order_id)
            ),
            coupon_status="fulfilled",
            coupon_status_normalized="fulfilled",
            coupon_paid_amount_cent=10000,
        )
    )
    session.add(
        RawDouyinVerifyRecord(
            verify_id=f"pg-verify-{coupon_id}",
            coupon_id=coupon_id,
            verify_status="valid",
            verify_time=observed,
            poi_id="pg-poi-verify",
            sku_id="pg-sku-service",
            paid_amount_cent=10000,
        )
    )


def _seed_impact(session: Session, *, run_id: str, coupon_id: str) -> None:
    session.add(
        JobImpact(
            impact_key=f"pg-impact-{run_id}",
            entity_type="coupon",
            entity_key=coupon_id,
            source_run_id=run_id,
            affected_closure_json={"coupon_ids": [coupon_id]},
            new_values_json={"coupon_id": coupon_id},
        )
    )


def _concurrent_settle(
    engine: object,
    *,
    run_id: str,
    coupon_id: str,
) -> list[dict[str, object]]:
    barrier = Barrier(2)

    def worker() -> dict[str, object]:
        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        barrier.wait(timeout=10)
        return settle_impacted_coupons(
            factory,
            source_run_id=run_id,
            page_fence=lambda _session: True,
            impact_batch_size=1,
            coupon_batch_size=1,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        return [future.result(timeout=20) for future in futures]


def test_postgres_real_settlement_coupon_lock_competition_is_observed_before_release(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    engine, factory = postgres_stack
    coupon_id = "pg-real-lock-hook"
    run_id = "pg-real-lock-run"
    with factory.begin() as session:
        _seed_coupon(session, coupon_id)
        _seed_impact(session, run_id=run_id, coupon_id=coupon_id)

    first_lock_returned = Event()
    second_lock_entered = Event()
    second_done = Event()
    release_first = Event()
    first_thread_id: dict[str, int] = {}

    def observe_settlement_lock(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        normalized = statement.lower()
        if "for update" in normalized and "raw_douyin_order_coupons" in normalized:
            import threading

            if not first_lock_returned.is_set():
                first_thread_id.setdefault("value", threading.get_ident())
            elif threading.get_ident() != first_thread_id.get("value"):
                second_lock_entered.set()

    def mark_first_lock_returned(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        normalized = statement.lower()
        if "for update" in normalized and "raw_douyin_order_coupons" in normalized:
            import threading

            if threading.get_ident() == first_thread_id.get("value"):
                first_lock_returned.set()

    event.listen(engine, "before_cursor_execute", observe_settlement_lock)
    event.listen(engine, "after_cursor_execute", mark_first_lock_returned)

    def first_fence(_session):
        if first_lock_returned.is_set():
            assert release_first.wait(timeout=10)
        return True

    def first_worker() -> dict[str, object]:
        summary = settle_impacted_coupons(
            sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True),
            source_run_id=run_id,
            page_fence=first_fence,
            impact_batch_size=1,
            coupon_batch_size=1,
        )
        return summary

    def second_worker() -> dict[str, object]:
        summary = settle_impacted_coupons(
            sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True),
            source_run_id=run_id,
            page_fence=lambda _session: True,
            impact_batch_size=1,
            coupon_batch_size=1,
        )
        second_done.set()
        return summary

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(first_worker)
            assert first_lock_returned.wait(timeout=10) is True
            second_future = pool.submit(second_worker)
            assert second_lock_entered.wait(timeout=10) is True
            assert not second_done.is_set()
            release_first.set()
            first_summary = first_future.result(timeout=20)
            second_summary = second_future.result(timeout=20)
        assert first_summary["completed"] is True
        assert second_summary["completed"] is True
        assert second_done.is_set()
    finally:
        event.remove(engine, "before_cursor_execute", observe_settlement_lock)
        event.remove(engine, "after_cursor_execute", mark_first_lock_returned)

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(SettlementFeeResult).where(
                SettlementFeeResult.coupon_id == coupon_id
            )
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(SettlementFeeResultCurrent).where(
                SettlementFeeResultCurrent.coupon_id == coupon_id
            )
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.coupon_id == coupon_id
            )
        ) == 0


def test_postgres_same_run_retry_converges_without_integrity_error(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    engine, factory = postgres_stack
    coupon_id = "pg-same-run"
    with factory.begin() as session:
        _seed_coupon(session, coupon_id)
        _seed_impact(session, run_id="pg-same-run-id", coupon_id=coupon_id)

    summaries = _concurrent_settle(engine, run_id="pg-same-run-id", coupon_id=coupon_id)
    assert all(summary["completed"] is True for summary in summaries)

    with factory() as session:
        rows = list(
            session.scalars(
                select(SettlementFeeResult).where(
                    SettlementFeeResult.coupon_id == coupon_id
                )
            )
        )
        assert len(rows) == 2
        assert len(
            {
                (row.coupon_id, row.fee_direction, row.calculation_run_id)
                for row in rows
            }
        ) == 2
        assert all(row.result_status == 1 for row in rows)
        assert session.scalar(
            select(func.count()).select_from(SettlementFeeResultCurrent).where(
                SettlementFeeResultCurrent.coupon_id == coupon_id
            )
        ) == 2


def test_postgres_refund_event_converges_to_one_adjustment_per_direction(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    engine, factory = postgres_stack
    coupon_id = "pg-refund-race"
    with factory.begin() as session:
        _seed_coupon(session, coupon_id)
        _seed_impact(session, run_id="pg-initial-run", coupon_id=coupon_id)

    _concurrent_settle(engine, run_id="pg-initial-run", coupon_id=coupon_id)
    with factory.begin() as session:
        session.add(
            DouyinRefundEvent(
                refund_event_id="pg-refund-event",
                order_id=f"pg-order-{coupon_id}",
                coupon_id=coupon_id,
                refund_type=1,
                refund_status=2,
                refund_amount_cent=1000,
                occurred_at=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
                source_run_id="pg-refund-source",
                source_observed_at=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
                payload_fingerprint="c" * 64,
                observation_key="pg-refund-observation",
                raw_payload={},
            )
        )
        _seed_impact(session, run_id="pg-refund-run", coupon_id=coupon_id)

    summaries = _concurrent_settle(engine, run_id="pg-refund-run", coupon_id=coupon_id)
    assert all(summary["completed"] is True for summary in summaries)

    with factory() as session:
        rows = list(
            session.scalars(
                select(SettlementFeeAdjustment).where(
                    SettlementFeeAdjustment.refund_event_id == "pg-refund-event"
                )
            )
        )
        assert len(rows) == 2
        assert {(row.fee_direction, row.refund_event_id) for row in rows} == {
            (1, "pg-refund-event"),
            (2, "pg-refund-event"),
        }


def test_postgres_changed_input_different_run_converges_to_one_new_version(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    engine, factory = postgres_stack
    coupon_id = "pg-changed-input"
    with factory.begin() as session:
        _seed_coupon(session, coupon_id)
        _seed_impact(session, run_id="pg-changed-run-a", coupon_id=coupon_id)

    _concurrent_settle(engine, run_id="pg-changed-run-a", coupon_id=coupon_id)
    with factory.begin() as session:
        session.execute(
            update(SkuFeeRule)
            .where(SkuFeeRule.rule_version == "pg-fee-v1")
            .values(
                promotion_service_fee_rate=Decimal("0.120000"),
                management_service_fee_rate=Decimal("0.060000"),
            )
        )
        _seed_impact(session, run_id="pg-changed-run-b", coupon_id=coupon_id)

    summaries = _concurrent_settle(
        engine,
        run_id="pg-changed-run-b",
        coupon_id=coupon_id,
    )
    assert all(summary["completed"] is True for summary in summaries)

    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(SettlementFeeResult).where(
                SettlementFeeResult.coupon_id == coupon_id
            )
        ) == 4
        versions = list(
            session.scalars(
                select(SettlementFeeResult.result_version)
                .where(SettlementFeeResult.coupon_id == coupon_id)
                .order_by(SettlementFeeResult.fee_direction, SettlementFeeResult.result_version)
            )
        )
        assert versions == [1, 2, 1, 2]
