"""Opt-in PostgreSQL checks in a per-test disposable schema."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications import sales
from apps.api.dy_api.dashboard_publications.schema import runs
from apps.api.dy_api.models import Base, SettlementOrderDetail
from test_dashboard_publication_sales import CUTOFF, prepare_sales, assert_sales_parity


@pytest.fixture()
def publication_postgres_session():
    """Own one schema without touching other collaborators' test data."""
    url = os.getenv("DYDATA_PUBLICATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_PUBLICATION_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.endswith("_test")
    namespace = "publication_projection_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={namespace}"})
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
        admin.dispose()


def test_sales_projection_on_postgresql(publication_postgres_session):
    prepare_sales(publication_postgres_session)
    assert_sales_parity(publication_postgres_session)


def test_shanghai_month_and_projection_cascade(publication_postgres_session):
    session = publication_postgres_session
    prepare_sales(session)
    session.add(SettlementOrderDetail(coupon_id="tz", order_id="tz", product_type="timezone", sale_store_id="A",
        sale_time=datetime(2026, 1, 31, 20, tzinfo=timezone.utc), is_verified=False))
    session.flush()
    sales.build(session, "s2", CUTOFF)
    assert sales.read(session, "s2", month="2026-02", product_type="timezone")["metrics"]["total_sales_order_count"] == 1
    assert sales.read(session, "s2", month="2026-01", product_type="timezone")["metrics"]["total_sales_order_count"] == 0
    session.execute(delete(runs).where(runs.c.id == "s2"))
    assert session.scalar(select(func.count()).select_from(sales.coupons).where(sales.coupons.c.publication_id == "s2")) == 0
    assert session.scalar(select(func.count()).select_from(SettlementOrderDetail)) == 9
