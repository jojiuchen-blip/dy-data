"""Real PostgreSQL immutability and concurrent materialization of evidence."""
from concurrent.futures import ThreadPoolExecutor

from alembic import command
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import AccountQualificationVersion
from apps.worker.monthly_store_evidence import freeze_store_evidence, frozen_store_evidence
from test_dashboard_publication_migration import full_pg_stack  # noqa: F401
from test_monthly_store_evidence import fact, make_version


def test_real_postgres_evidence_is_idempotent_immutable_and_read_back(full_pg_stack):
    config, engine = full_pg_stack
    command.upgrade(config, "head")
    with Session(engine) as session, session.begin():
        version = make_version(session)
        qualification_id = version.version_id
    def materialize(_):
        with Session(engine) as session, session.begin():
            version = session.get(AccountQualificationVersion, qualification_id)
            return freeze_store_evidence(session, qualification_version=version, facts=[fact()]).version_id
    with ThreadPoolExecutor(max_workers=3) as executor:
        identities = list(executor.map(materialize, range(3)))
    assert len(set(identities)) == 1
    with Session(engine) as session:
        version = session.get(AccountQualificationVersion, qualification_id)
        actual = frozen_store_evidence(session, qualification_version=version, version_id=identities[0])
        assert actual.account_store_ids("account-1") == {"store-a"}
        assert session.scalar(text("SELECT count(*) FROM monthly_store_evidence_snapshot")) == 1
    for statement in (
        "UPDATE monthly_store_evidence_snapshot SET policy_version='tampered'",
        "DELETE FROM monthly_store_evidence_snapshot",
        "TRUNCATE monthly_store_evidence_snapshot",
    ):
        with engine.connect() as connection, connection.begin(), pytest.raises(DBAPIError, match="immutable"):
            connection.execute(text(statement))
    with pytest.raises(RuntimeError, match="Preserve frozen store relationship evidence"):
        command.downgrade(config, "20261119_0071")
