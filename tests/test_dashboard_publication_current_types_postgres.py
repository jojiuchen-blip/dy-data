"""Current SKU classification and immutable publication parity on PostgreSQL."""
import pytest

from test_dashboard_publication_sales_postgres import publication_postgres_session
from test_dashboard_publication_sales import (
    test_sales_freezes_current_sku_types_across_scopes_without_rewriting_facts as assert_sales_types,
)
from test_dashboard_publication_clues import (
    test_clue_freeze_prefers_raw_sku_and_preserves_ambiguous_source_type as assert_clue_types,
    test_clue_shared_product_id_requires_all_candidates_to_have_one_type as assert_ambiguous_types,
)


def test_current_sales_types_are_frozen_without_scope_filter(publication_postgres_session):
    assert_sales_types(publication_postgres_session)


def test_current_clue_types_keep_raw_sku_priority_and_immutable_reads(publication_postgres_session):
    assert_clue_types(publication_postgres_session)


@pytest.mark.parametrize("other_type", ["", "unknown", "all", "keep", "Another type"])
def test_ambiguous_product_candidates_preserve_source_type(publication_postgres_session, other_type):
    assert_ambiguous_types(publication_postgres_session, other_type)
