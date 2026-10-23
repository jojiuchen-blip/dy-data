"""Promotion registration routes against a disposable local PostgreSQL schema."""

from __future__ import annotations

import pytest

from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session
from test_api_store_billing import (
    client,
    simple_invoice_context,
    test_simple_invoice_derives_facts_and_preserves_leading_zero_replay_audit as _assert_registration,
    test_simple_invoice_failed_commit_rolls_back_every_fact as _assert_rollback,
    test_simple_invoice_preview_and_registration_share_exact_cent_rounding as _assert_rounding,
    test_simple_invoice_replays_pre_simplification_hash_from_archived_facts as _assert_legacy_replay,
)

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


@pytest.fixture()
def db_session(postgres_session):
    """Reuse the guarded local-only disposable-schema PostgreSQL fixture."""
    yield postgres_session


def test_registration_and_idempotency(client, db_session, simple_invoice_context):
    _assert_registration(client, db_session, simple_invoice_context)


def test_registration_rollback(client, db_session, simple_invoice_context, monkeypatch):
    _assert_rollback(client, db_session, simple_invoice_context, monkeypatch)


def test_legacy_registration_replay(client, db_session, simple_invoice_context):
    _assert_legacy_replay(client, db_session, simple_invoice_context)


@pytest.mark.parametrize(("amounts", "expected"), [
    ([1], (1, 1, 0)), ([9, 9], (18, 17, 1)), ([-150, 100, 100], (50, 47, 3)),
])
def test_preview_and_registration_rounding(client, db_session, monkeypatch, amounts, expected):
    _assert_rounding(client, db_session, monkeypatch, amounts, expected)
