"""Actual PostgreSQL shared-heavy-lock and atomic rule-patch checks."""
import pytest
from sqlalchemy import func, select

from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
from scripts.settlement_rule_patch import PatchError, patch_rules
from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session
from test_settlement_rule_patch import (
    context, rows, preview,
    test_preview_is_readonly_then_apply_is_additive_and_replayable as _assert_additive,
    test_failure_rolls_back_catalog_rules_and_audit as _assert_rollback,
)

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


@pytest.fixture()
def db_session(postgres_session):
    yield postgres_session


def test_postgres_additive_apply(db_session, context):
    _assert_additive(db_session, context)


def test_postgres_rollback(db_session, context, monkeypatch):
    _assert_rollback(db_session, context, monkeypatch)


def test_shared_heavy_claim_lock_rejects_concurrent_writer(db_session, context):
    report = preview(db_session, context)
    with db_session.get_bind().connect() as other:
        with other.begin():
            assert other.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY)))
            with pytest.raises(PatchError, match="shared heavy claim lock busy"):
                patch_rules(db_session, rows(), **context, apply=True, fingerprint=report["fingerprint"])


def test_rule_table_fence_blocks_uncoordinated_api_writer(db_session, context):
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from scripts.settlement_rule_patch import _fence
    with db_session.begin():
        _fence(db_session)
        with db_session.get_bind().connect() as other:
            with other.begin():
                other.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(OperationalError):
                    other.execute(text("LOCK TABLE sku_fee_rule IN ROW EXCLUSIVE MODE"))
                other.rollback()


def test_fingerprint_detects_committed_change_in_another_session(db_session, context):
    from sqlalchemy.orm import Session
    from apps.api.dy_api.models import DimSkuProductRule
    report = preview(db_session, context)
    with Session(db_session.get_bind()) as other:
        sku = other.scalar(select(DimSkuProductRule))
        sku.product_scope = "concurrent-scope-change"
        other.commit()
    with pytest.raises(PatchError, match="stale"):
        patch_rules(db_session, rows(), **context, apply=True, fingerprint=report["fingerprint"])
