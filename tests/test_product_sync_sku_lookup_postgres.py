"""Real PostgreSQL gate for normal known-SKU synchronization."""
import pytest
from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session
from test_product_sync_sku_lookup import (
    test_completed_known_skus_restore_normal_sync_without_losing_manual_fields as _assert_success,
    test_bad_lookup_fails_whole_adapter_and_preserves_current as _assert_failure,
)

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


@pytest.fixture()
def db_session(postgres_session):
    yield postgres_session


def test_postgres_success_preserves_manual_fields(db_session):
    _assert_success(db_session)


@pytest.mark.parametrize("case", ["partial", "owner-conflict"])
def test_postgres_incomplete_or_wrong_owner_preserves_current(db_session, case):
    _assert_failure(db_session, case)
