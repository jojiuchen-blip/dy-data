"""Recovery transaction gate using only a disposable loopback database."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.models import Base
from test_clue_geo_recovery import (
    test_preview_is_read_only_and_apply_restores_source_store_once as exercise_restore,
    test_apply_can_be_rolled_back_atomically as exercise_rollback,
    test_changed_source_between_preview_and_apply_is_skipped as exercise_recheck,
    test_authoritative_terminal_evidence_blocks_stale_active_projection as exercise_terminal,
)


def exercise_terminal_sources(session):
    exercise_terminal(session, 'settlement', True)


@pytest.mark.parametrize('exercise', [exercise_restore, exercise_rollback, exercise_recheck, exercise_terminal_sources])
def test_recovery_on_real_postgresql(exercise):
    raw = os.getenv('DY_RELEASE_POSTGRES_URL')
    if not raw:
        pytest.skip('requires disposable release PostgreSQL service')
    url = make_url(raw)
    assert url.drivername.startswith('postgresql')
    assert url.host in {'127.0.0.1', 'localhost'} and url.database == 'dydata_release'
    schema = 'geo_recovery_test_' + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={'options': f'-c search_path={schema}'})
    try:
        Base.metadata.create_all(engine)
        with Session(engine, autoflush=False) as s:
            exercise(s)
    finally:
        engine.dispose()
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
