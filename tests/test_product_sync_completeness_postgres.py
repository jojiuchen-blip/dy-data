"""Disposable PostgreSQL evidence for empty-product completeness and freshness."""

import pytest

from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session
from test_product_sync_completeness import (
    test_unknown_empty_product_is_reconciled_by_exact_id_without_inventing_sku as _assert_recovered,
    test_unknown_repeated_empty_product_is_not_success_and_preserves_freshness as _assert_incomplete,
    test_empty_record_on_other_status_requires_one_bounded_reconciliation as _assert_other_status,
)

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


def test_postgres_unknown_empty_product_recovers(postgres_session):
    _assert_recovered(postgres_session)


def test_postgres_unknown_empty_product_preserves_success_freshness(postgres_session):
    _assert_incomplete(postgres_session)


@pytest.mark.parametrize("known,detail_has_sku", [(False, True), (False, False), (True, False)])
def test_postgres_repeated_empty_status_is_reconciled(postgres_session, known, detail_has_sku):
    _assert_other_status(postgres_session, known, detail_has_sku)
