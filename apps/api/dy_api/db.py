from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def get_database_url(required: bool = True) -> str | None:
    url = os.getenv("DY_DATABASE_URL") or os.getenv("DATABASE_URL")
    if required and not url:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before opening the database.")
    return url


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


def make_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    url = database_url or get_database_url(required=True)
    assert url is not None
    url = normalize_database_url(url)
    return create_engine(url, echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_engine() -> Engine | None:
    global _ENGINE
    if _ENGINE is None:
        url = get_database_url(required=False)
        if not url:
            return None
        _ENGINE = make_engine(url)
    return _ENGINE


def get_session_factory() -> sessionmaker[Session] | None:
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        engine = get_engine()
        if engine is None:
            return None
        _SESSION_FACTORY = make_session_factory(engine)
    return _SESSION_FACTORY


def get_session() -> Iterator[Session | None]:
    factory = get_session_factory()
    if factory is None:
        yield None
        return

    with session_scope(factory) as session:
        yield session


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Engine) -> None:
    Base.metadata.create_all(engine)
