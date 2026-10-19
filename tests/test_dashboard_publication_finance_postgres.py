"""Real PostgreSQL finance projection gate in a disposable dedicated schema."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from test_dashboard_publication_finance import (
    _run, _seed_finance, publication,
    test_failed_build_rolls_back_owned_projection_rows as _assert_failed_build_rollback,
    test_finance_parity_scope_filters_export_and_frozen_source as _assert_finance_parity,
    test_settlement_parity_huge_integer_cent_scope_and_no_legacy_drift as _assert_settlement_parity,
)
from dy_api.dashboard_publications.schema import metadata, runs
from dy_api.db import normalize_database_url
from dy_api.models import Base, PromotionInvoice, SettlementStatement


POSTGRES_URL = os.getenv("DYDATA_T12_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")
SCHEMA_PATTERN = re.compile(r"pub_finance_[0-9a-f]{12}\Z")


@pytest.fixture()
def postgres_session():
    url = make_url(normalize_database_url(POSTGRES_URL))
    assert url.drivername.startswith("postgresql+")
    assert url.host in {"127.0.0.1", "localhost"} and url.port == 15432
    assert url.database == url.username == "dydata_t12"
    schema = f"pub_finance_{uuid4().hex[:12]}"
    assert SCHEMA_PATTERN.fullmatch(schema)
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options":
        f"-c search_path={schema} -c lock_timeout=5000 -c statement_timeout=120000"})
    try:
        Base.metadata.create_all(engine)
        metadata.create_all(engine)
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            yield session
    finally:
        engine.dispose()
        assert SCHEMA_PATTERN.fullmatch(schema)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_postgres_finance_parity(postgres_session, direction, monkeypatch):
    _assert_finance_parity(postgres_session, direction, monkeypatch)


@pytest.mark.parametrize("legacy_root", [False, True])
def test_postgres_settlement_parity(postgres_session, legacy_root):
    _assert_settlement_parity(postgres_session, legacy_root)


def test_postgres_failed_build_rollback(postgres_session, monkeypatch):
    _assert_failed_build_rollback(postgres_session, monkeypatch)


def test_postgres_delete_cascades_only_analysis(postgres_session):
    _seed_finance(postgres_session)
    _run(postgres_session, "finance-v1", "finance")
    publication.build_finance(postgres_session, "finance-v1", datetime(2026, 10, 19, tzinfo=UTC))
    postgres_session.commit()
    postgres_session.execute(delete(runs).where(runs.c.id == "finance-v1"))
    postgres_session.commit()
    for table in (publication.statements, publication.invoices, publication.pending,
                  publication.pending_members, publication.dimensions):
        assert postgres_session.scalar(select(func.count()).select_from(table)) == 0
    assert postgres_session.scalar(select(func.count()).select_from(SettlementStatement)) == 5
    assert postgres_session.scalar(select(func.count()).select_from(PromotionInvoice)) == 1
