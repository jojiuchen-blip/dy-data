"""Real PostgreSQL gate for frozen financial collection completeness."""
import os

import pytest

from test_dashboard_publication_finance_postgres import postgres_session
from test_dashboard_publication_period_readiness import (
    test_real_day_recovery_changes_financial_fingerprint_but_not_frozen_reads as _assert_recovery,
)

pytestmark = pytest.mark.skipif(
    not (os.getenv("DYDATA_PUBLICATION_TEST_DATABASE_URL") or os.getenv("DYDATA_T12_TEST_DATABASE_URL")),
    reason="dedicated PostgreSQL test URL not configured",
)


def test_postgres_real_day_recovery_and_frozen_readiness(postgres_session, monkeypatch):
    _assert_recovery(postgres_session, monkeypatch)
