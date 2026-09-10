"""Atomic POI ownership checks in an isolated disposable PostgreSQL schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import Base, DimStore, DimStorePoiMapping, JobImpact
from apps.worker.repositories import upsert_store_poi_mapping


@pytest.fixture
def poi_pg():
    raw_url = os.getenv("DY_RELEASE_POSTGRES_URL")
    if not raw_url:
        pytest.skip("requires disposable release PostgreSQL service")
    url = make_url(raw_url)
    if not url.drivername.startswith("postgresql") or url.host not in {"127.0.0.1", "localhost"} or url.database != "dydata_release":
        pytest.fail("POI gate requires loopback dydata_release database")
    schema = f"poi_gate_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000 -c statement_timeout=15000"})
    try:
        Base.metadata.create_all(engine, tables=[DimStore.__table__, DimStorePoiMapping.__table__, JobImpact.__table__])
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("contender", ["winner", "other"])
def test_concurrent_poi_insert_preserves_first_owner(poi_pg, contender: str) -> None:
    with poi_pg.begin() as session:
        session.add_all([DimStore(store_id="winner", store_name="Winner"), DimStore(store_id="other", store_name="Other")])
    entered = Event()

    def compete() -> str:
        with poi_pg.begin() as session:
            entered.set()
            try:
                result = upsert_store_poi_mapping(session, contender, "poi", preserve_existing_store=True)
                return result.store_id
            except ValueError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with poi_pg.begin() as session:
            upsert_store_poi_mapping(session, "winner", "poi", preserve_existing_store=True)
            future = pool.submit(compete)
            assert entered.wait(timeout=5)
        assert future.result(timeout=10) == ("winner" if contender == "winner" else "conflict")
    with poi_pg() as session:
        assert session.scalar(select(DimStorePoiMapping.store_id)) == "winner"
