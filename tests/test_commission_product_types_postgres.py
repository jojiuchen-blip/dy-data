"""Strict opt-in PostgreSQL checks for commission classification and reporting."""

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import OperationalError

from apps.api.dy_api.models import SkuFeeRule
from scripts import convert_jingcheng_product_types as conversion
from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session
from test_commission_product_classification import (
    CONTEXT, _seed, test_participating_selection_and_official_preservation_are_exact as assert_selection,
    test_participation_evidence_is_inside_the_apply_fence as assert_stale,
)
from test_commission_product_publication import (
    test_analysis_reclassifies_exact_skus_and_reaggregates_distinct_orders as assert_publication,
    test_order_list_pagination_and_full_export_use_the_same_exact_sku_types as assert_details,
    test_frozen_protected_entries_reclassify_only_the_new_analysis as assert_protected,
    test_unresolved_and_uncovered_history_are_counted_and_remain_visible as assert_uncovered,
)

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


def test_participating_conversion_postgres(postgres_session):
    assert_selection(postgres_session)


@pytest.mark.parametrize("mutation", ["rule-rate", "rule-status", "new-rule", "catalog-arrives"])
def test_stale_rule_and_catalog_evidence_postgres(postgres_session, mutation):
    assert_stale(postgres_session, mutation)


def test_classified_publication_postgres(postgres_session, monkeypatch):
    assert_publication(postgres_session, monkeypatch)


def test_classified_order_paging_export_postgres(postgres_session):
    assert_details(postgres_session)


def test_protected_financial_classification_postgres(postgres_session, monkeypatch):
    assert_protected(postgres_session, monkeypatch)


def test_unresolved_and_uncovered_history_postgres(postgres_session, monkeypatch):
    assert_uncovered(postgres_session, monkeypatch)


def test_conversion_fence_blocks_concurrent_participation_change(postgres_session, monkeypatch):
    _seed(postgres_session)
    preview = conversion.convert_product_types(postgres_session, **CONTEXT)
    original = conversion._actor
    checked = []

    def observe_fenced_actor(session, actor, *, lock=False):
        if lock:
            with session.get_bind().connect() as connection:
                with connection.begin():
                    connection.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    with pytest.raises(OperationalError):
                        connection.execute(update(SkuFeeRule).where(
                            SkuFeeRule.sku_id == "other-scope").values(rule_status=2))
                    connection.rollback()
            checked.append(True)
        return original(session, actor, lock=lock)

    monkeypatch.setattr(conversion, "_actor", observe_fenced_actor)
    assert conversion.convert_product_types(postgres_session, **CONTEXT, apply=True,
        preview_hash=preview["preview_hash"])["applied"]
    assert checked == [True]
