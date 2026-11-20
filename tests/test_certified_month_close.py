"""Exercise the writer, immutable publication, and store-scoped readers together."""
from datetime import UTC, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications.finance import (
    build_settlement, monthly_detail_statement_ids, read_monthly_settlement, read_store_ranking,
)
from apps.api.dy_api.dashboard_publications.lifecycle import PublicationError, publish_module
from apps.api.dy_api.dashboard_publications.schema import metadata
from apps.api.dy_api.models import (
    JobRun, RawDouyinOrder, RawDouyinVerifyRecord, SettlementMonthClose, SettlementProjectionActive,
    SettlementStatement, SettlementStatementBalance, SettlementStatementVisibility,
)
from apps.worker import month_close, settlement_rebuild
from apps.worker.billing_auto_confirmation import preview_auto_confirmation
from apps.worker.repositories import upsert_aweme_account, upsert_store, upsert_store_poi_mapping
from account_qualification_fixtures import binding, date_synthetic_store_sources
from test_month_close_auto_bootstrap import MONTH, NOW, _quiet_sqlite_progress, _seed
from test_month_close_auto_bootstrap import bootstrap_session  # noqa: F401
from test_protected_billing_authority_postgres import postgres_engine  # noqa: F401


def _bills(session):
    return {row.store_id: (row.statement_id, row.version_no, row.promotion_net_fee_cent, row.management_net_fee_cent)
        for row in session.scalars(select(SettlementStatement).where(
            SettlementStatement.statement_month == MONTH, SettlementStatement.is_current.is_(True),
        ))}


def _close(factory):
    with factory.begin() as session:
        date_synthetic_store_sources(session, MONTH)
    job_id = month_close.ensure_month_close_job(factory, now=NOW)
    assert job_id
    assert settlement_rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=job_id, business_month=MONTH)
    return job_id


def _partial_then_repaired(session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(session, records=[binding(), binding(
        account="owner-other", poi="poi-other", douyin="dy-other", nickname="Other Sales Account",
    )])
    _quiet_sqlite_progress(monkeypatch, session)
    metadata.create_all(session.get_bind())
    session.rollback()
    with factory.begin() as writer:
        upsert_store(writer, "other", "Other Store")
        upsert_store_poi_mapping(writer, "other", "poi-other", mapping_source="test")
        upsert_aweme_account(writer, "owner-other", store_id="other", binding_status="active")
        order = writer.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
        order.owner_account_id = "owner-other"
        order.owner_account_name = "Other Sales Account"
        order.raw_payload = {"owner_account_name": "Other Sales Account"}
        writer.get(RawDouyinVerifyRecord, "verify-middle").poi_id = "poi-other"

    first_job = _close(factory)
    first_publication = publish_module(factory, "settlement", build_settlement, now=NOW)
    with factory() as reader:
        scope = reader.get(SettlementMonthClose, MONTH)
        assert (scope.is_complete, scope.blocked_store_ids, scope.unscoped_issue_count) == (False, ["other"], 0)
        first_bills = _bills(reader)
        assert set(first_bills) == {"store-sale", "store-verify"}
        assert first_bills["store-sale"][1:] == (1, 3000, 0)
        assert reader.get(SettlementStatementBalance, (first_bills["store-sale"][0], 1)).net_due_cent == 3000
        visibility = reader.get(SettlementStatementVisibility, first_bills["store-sale"][0])
        assert visibility is not None
        first_visible_at = visibility.first_visible_at
        data = read_monthly_settlement(reader, first_publication.id, {"store_id": "store-sale", "month": MONTH})
        assert data["metrics"]["promotion_net_fee_cent"] == 3000
        assert data["period_availability"]["monthly_close"]["status"] == "partial"
        assert monthly_detail_statement_ids(
            reader, first_publication.id, MONTH, store_id="store-sale", scope_store_ids=("store-sale",),
        ) == (first_bills["store-sale"][0],)
        with pytest.raises(PublicationError, match="尚未准备完成"):
            read_monthly_settlement(reader, first_publication.id, {"store_id": "other", "month": MONTH})
        rank = read_store_ranking(reader, first_publication.id, {"period_key": MONTH})
        assert {row["store_id"] for row in rank["list"]} == set(first_bills)

    with factory.begin() as writer:
        # Source drift on a peer's unresolved slot does not invalidate an
        # already frozen store's review/confirmation proof.
        for order in writer.scalars(select(RawDouyinOrder)):
            order.raw_payload = {**order.raw_payload, "receipt_amount": 20001}
    first_visible_utc = first_visible_at if first_visible_at.tzinfo is not None else first_visible_at.replace(tzinfo=UTC)
    preview = preview_auto_confirmation(factory, months=(MONTH,), store_ids=("store-sale",),
                                        now=first_visible_utc + timedelta(days=8))
    assert [(row["direction"], row["state"]) for row in preview["rows"] if row["amount_cent"]] == [(1, "candidate")]
    second_job = _close(factory)
    assert second_job != first_job
    second_publication = publish_module(factory, "settlement", build_settlement, now=NOW + timedelta(days=3))
    with factory() as reader:
        second_bills = _bills(reader)
        assert reader.get(SettlementMonthClose, MONTH).is_complete
        assert {key: second_bills[key] for key in first_bills} == first_bills
        assert second_bills["other"][1:] == (1, 6000, 4000)
        assert reader.get(SettlementStatementVisibility, first_bills["store-sale"][0]).first_visible_at == first_visible_at
        assert reader.get(SettlementStatementVisibility, second_bills["other"][0]).publication_id == second_publication.id
        assert read_monthly_settlement(reader, second_publication.id, {"store_id": "other", "month": MONTH})[
            "metrics"]["promotion_net_fee_cent"] == 6000
    with factory.begin() as writer:
        order = writer.scalar(select(RawDouyinOrder))
        order.raw_payload = {**order.raw_payload, "receipt_amount": 30001}
    assert month_close.ensure_month_close_job(factory, now=NOW) == second_job


def test_certified_month_isolates_missing_receipt_and_returns_only_repaired_shop(bootstrap_session, monkeypatch):
    _partial_then_repaired(bootstrap_session, monkeypatch)


@pytest.mark.parametrize("postgres_engine", ["migration"], indirect=True)
def test_certified_month_isolates_store_and_freezes_actual_postgres_migration(postgres_engine, monkeypatch):
    with Session(postgres_engine, autoflush=False) as session:
        _partial_then_repaired(session, monkeypatch)


def test_unknown_identity_does_not_certify_any_new_store(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    with factory.begin() as session:
        order = session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
        order.owner_account_name = None
        order.owner_account_id = "unknown-opaque"
        order.raw_payload = {"sale_info": {"transfer_uid": "unknown-opaque"}, "receipt_amount": 10001}
    job_id = _close(factory)
    with factory() as session:
        state = session.get(SettlementMonthClose, MONTH)
        assert not state.is_complete and state.unscoped_issue_count
        assert _bills(session) == {}
        assert session.get(SettlementProjectionActive, "settlement").generation_id == "bootstrap-base"
        assert session.get(JobRun, job_id).metadata_json["monthly_close_outcome"]["complete"] is False


def test_complete_inputs_with_no_redemptions_can_certify_zero(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    with factory.begin() as session:
        session.execute(delete(RawDouyinVerifyRecord))
    _close(factory)
    with factory() as session:
        assert session.get(SettlementMonthClose, MONTH).is_complete
        assert _bills(session) == {}


def test_empty_following_period_cannot_certify_zero_before_prior_carry_is_known(bootstrap_session):
    from apps.worker.monthly_close_scope import MonthlyCloseScope

    scope, carry = settlement_rebuild._certify_monthly_balance_inputs(
        bootstrap_session, MonthlyCloseScope("2026-11", "frozen-version", frozenset(), 0),
    )
    assert scope.preceding_scope_unresolved
    assert not scope.complete and not carry
