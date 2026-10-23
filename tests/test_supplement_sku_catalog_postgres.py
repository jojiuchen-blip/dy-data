"""Disposable PostgreSQL gate for bounded catalog supplementation."""
import pytest

from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session
from test_supplement_sku_catalog import (
    evidence,
    test_preview_create_history_audit_replay_and_no_job as _assert_flow,
    test_audit_failure_rolls_back_history_and_all_created_catalog as _assert_rollback,
    test_concurrent_catalog_insert_changes_fingerprint as _assert_stale,
    test_current_identity_conflict_blocks_entire_supplement as _assert_conflict,
)

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


@pytest.fixture()
def db_session(postgres_session):
    yield postgres_session


def test_postgres_catalog_flow(db_session, evidence):
    _assert_flow(db_session, evidence)


def test_postgres_atomic_audit_rollback(db_session, evidence, monkeypatch):
    _assert_rollback(db_session, evidence, monkeypatch)


def test_postgres_stale_fingerprint(db_session, evidence):
    _assert_stale(db_session, evidence)


def test_postgres_existing_identity_conflict(db_session, evidence):
    _assert_conflict(db_session, evidence)
