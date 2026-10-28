"""PostgreSQL gate for catalog predicate fencing in a dedicated test schema."""
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimSkuProductRule
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
from scripts.convert_jingcheng_product_types import ConversionError, _fence, convert_product_types
from test_catalog_type_conversion import (
    assert_conversion_preserves_money, assert_failed_conversion_rolls_back, conversion_context,
)
from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


@pytest.fixture()
def db_session(postgres_session):
    yield postgres_session


def test_postgres_conversion_preserves_money(db_session, conversion_context):
    assert_conversion_preserves_money(db_session, conversion_context)


def test_postgres_conversion_rollback(db_session, conversion_context, monkeypatch):
    assert_failed_conversion_rolls_back(db_session, conversion_context, monkeypatch)


def test_postgres_conversion_refuses_busy_claim_lock(db_session, conversion_context):
    preview = convert_product_types(db_session, **conversion_context)
    with db_session.get_bind().connect() as other:
        with other.begin():
            assert other.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY)))
            with pytest.raises(ConversionError, match="claim lock busy"):
                convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])


@pytest.mark.parametrize("mutation", ["insert", "enter-scope"])
def test_postgres_catalog_fence_blocks_new_predicate_members(db_session, conversion_context, mutation):
    with db_session.begin():
        _fence(db_session)
        with db_session.get_bind().connect() as other:
            with other.begin():
                other.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(OperationalError):
                    if mutation == "insert":
                        other.execute(text("INSERT INTO dim_sku_product_rules (sku_id, product_scope, product_type) "
                                           "VALUES ('concurrent-target', '精诚养车', 'new')"))
                    else:
                        other.execute(text("UPDATE dim_sku_product_rules SET product_scope='精诚养车' WHERE sku_id='name-only'"))
                other.rollback()


def test_postgres_preview_detects_committed_new_target(db_session, conversion_context):
    preview = convert_product_types(db_session, **conversion_context)
    with Session(db_session.get_bind()) as other:
        other.add(DimSkuProductRule(sku_id="concurrent-target", product_scope="精诚养车", product_type="new"))
        other.commit()
    with pytest.raises(ConversionError, match="stale"):
        convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])
