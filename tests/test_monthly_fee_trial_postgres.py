"""Actual PostgreSQL aggregation, nullable values and selected-store trial reads."""
from sqlalchemy import insert
from sqlalchemy.orm import Session
import pytest

from apps.api.dy_api.dashboard_publications import fee_trial
from test_monthly_fee_trial import seed_trial
from test_protected_billing_authority_postgres import postgres_engine  # noqa: F401


def test_postgres_internal_trial_nullable_amount_scope_and_negative_adjustment(postgres_engine):
    with Session(postgres_engine) as session:
        seed_trial(session)
        data = fee_trial.read(session, "trial-a", month="2026-10", fee_direction="PROMOTION", scope_store_ids=("A",))
        assert data["summary"]["calculated_fee_cent"] == 12300
        assert data["summary"]["pending_coupon_count"] == 1
        assert len(data["list"]) == 3
        assert all(row["store_id"] == "A" for row in data["list"])
        assert [row["fee_amount_cent"] for row in data["list"] if row["record_status"] == "PENDING"] == [None]
        empty = fee_trial.read(session, "trial-a", month="2026-10", fee_direction="PROMOTION", scope_store_ids=())
        assert empty["list"] == []
        assert empty["summary"]["calculated_fee_cent"] is None


def test_postgres_trial_database_rejects_fabricated_pending_zero(postgres_engine):
    from sqlalchemy.exc import IntegrityError
    with Session(postgres_engine) as session:
        seed_trial(session)
        with pytest.raises(IntegrityError):
            session.execute(insert(fee_trial.rows).values(publication_id="trial-a", row_id="bad-amount",
                month="2026-10", fee_direction=1, coupon_id="pending-zero", product_type="all",
                fee_amount_cent=0, base_amount_cent=0, record_status="PENDING", search_text=""))
            session.flush()
        session.rollback()


@pytest.mark.parametrize("postgres_engine", ["migration"], indirect=True)
def test_migrated_postgres_trial_scope_contract_and_new_source_tracking(postgres_engine):
    from sqlalchemy import text
    with Session(postgres_engine) as session:
        seed_trial(session)
        data = fee_trial.read(session, "trial-a", month="2026-10", fee_direction="PROMOTION", scope_store_ids=("A",))
        assert data["summary"]["calculated_fee_cent"] == 12300
        assert data["summary"]["pending_coupon_count"] == 1
        assert set(session.scalars(text("SELECT source_name FROM dashboard_publication_source_counters "
            "WHERE source_name IN ('monthly_store_evidence_snapshot','data_quality_issues')"))) == {
                "monthly_store_evidence_snapshot", "data_quality_issues"}
