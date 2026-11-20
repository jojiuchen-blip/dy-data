"""Actual PostgreSQL aggregation, nullable values and selected-store trial reads."""
from csv import DictReader
from io import StringIO

from fastapi.testclient import TestClient
from sqlalchemy import insert, update
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


def test_postgres_store_summary_csv_keeps_pin_unknown_bucket_and_true_zero(postgres_engine, monkeypatch):
    from dy_api.auth import AuthContext, get_current_user
    from dy_api.main import create_app
    from dy_api.routes._data import get_session_dependency
    from apps.api.dy_api.dashboard_publications.schema import heads

    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    with Session(postgres_engine) as session:
        seed_trial(session)
        session.execute(update(fee_trial.rows).where(fee_trial.rows.c.store_id == "B").values(fee_amount_cent=0))
        session.commit()
        app = create_app()
        identity = [AuthContext(user_id="pg-finance", username="pg-finance", display_name="财务",
            role="highest_admin", store_ids=(), auth_type="test", page_keys=("FIN01", "FIN02"))]
        app.dependency_overrides[get_session_dependency] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: identity[0]
        with TestClient(app) as client:
            params = {"month": "2026-10", "feeDirection": "PROMOTION", "publication_id": "trial-a"}
            page = client.get("/api/v1/admin/finance/trial/stores", params=params)
            assert page.status_code == 200, page.text
            data = page.json()["data"]
            assert data["summary"]["calculatedFeeCent"] == 12300
            stores = {item["storeId"]: item for item in data["list"]}
            assert stores["B"]["calculatedFeeCent"] == 0
            assert stores[None]["calculatedFeeCent"] is None
            seed_trial(session, "trial-b", amount=1)
            session.execute(update(heads).where(heads.c.module == "settlement").values(publication_id="trial-b"))
            session.commit()
            exported = client.get("/api/v1/admin/finance/trial/stores/export", params=params)
            assert exported.status_code == 200, exported.text
            assert exported.content.startswith(b"\xef\xbb\xbf")
            records = list(DictReader(StringIO(exported.content.decode("utf-8-sig"))))
            assert records[-1]["汇总层级"] == "总计"
            assert records[-1]["已算费用（元）"] == "123.00"
            assert {item["试算版本"] for item in records} == {"trial-a"}
            assert next(item for item in records if item["门店ID"] == "B")["已算费用（元）"] == "0.00"
            assert next(item for item in records if item["门店名称"] == "归属待核验")["已算费用（元）"] == ""
