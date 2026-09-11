from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import Base, ClueAssignmentRound, ClueCenterOrder, ClueMasterLead, RawDouyinClue
from apps.worker import clue_phone_recovery as recovery
from src.dy_data.phones import phone_source_fingerprint
from test_clue_phone_recovery import NOW, _seed


@pytest.fixture()
def factory():
    url = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable local PostgreSQL")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.endswith("_test")
    schema = "clue_phone_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"},
    )
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_postgres_phone_recovery_commits_only_phone_fields(factory):
    with factory() as session:
        order_id, round_id = _seed(session, key="pg-phone", cipher="Enc.pg-phone")
        session.commit()

    def resolver(values):
        assert values == ["Enc.pg-phone"]
        return {"Enc.pg-phone": "13812345678"}

    result = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=resolver,
        order_ids=[order_id],
        max_items=100,
        now=NOW,
    )

    assert result["requested"] == 1
    assert result["repaired"] == 1
    with factory() as reader:
        center = reader.get(ClueCenterOrder, order_id)
        round_row = reader.get(ClueAssignmentRound, round_id)
        lead = reader.get(ClueMasterLead, "pg-phone")
        assert center.phone_plain == "13812345678"
        assert center.phone_source_fingerprint == phone_source_fingerprint(cipher_text="Enc.pg-phone")
        assert round_row.round_status == "active_unfollowed"
        assert round_row.assigned_store_id == "store-1"
        assert lead.current_assignment_round_id == round_id
        assert lead.allocation_state == "assigned"


def test_postgres_source_change_after_network_is_rejected(factory):
    with factory() as session:
        order_id, _ = _seed(session, key="pg-race", cipher="Enc.pg-old")
        session.commit()

    def resolver(values):
        assert values == ["Enc.pg-old"]
        with factory() as writer:
            raw = writer.get(RawDouyinClue, "raw-pg-race")
            raw.telephone = "13999999999"
            raw.enc_telephone = None
            writer.commit()
        return {"Enc.pg-old": "13812345678"}

    result = recovery.run_clue_phone_recovery_batch(
        factory,
        phone_plain_resolver=resolver,
        order_ids=[order_id],
        now=NOW,
    )

    assert result["repaired"] == 0
    assert result["source_changed"] == 1
    with factory() as reader:
        assert reader.get(ClueCenterOrder, order_id).phone_plain is None


def test_postgres_recovery_advisory_lock_has_one_consumer(factory):
    with recovery._phone_recovery_lock(factory) as first:
        assert first is True
        with recovery._phone_recovery_lock(factory) as second:
            assert second is False
