"""DYDATA-103: scoped month rebuild, end to end through real publication.

This deliberately does **not** mock ``refresh_active_settlement_lineage`` or
``generate_pending_statements``: a scoped close must reach a real pending
statement for the target month only.  Scaffolding is reused from the existing
publication suite (``_seed_r87_publication_source`` / ``_r87_rebuild_job`` /
``_generation``), which builds a published active generation plus a billable
current commission result.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import (
    DataQualityIssue,
    JobRun,
    RawDouyinOrder,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementStatement,
)
from apps.worker import settlement_rebuild
from apps.worker.settlement_rebuild import (
    SettlementMonthLockedError,
    run_settlement_month_rebuild_job,
)
from test_data_settlement import _load_dual_fee_fixture
from test_settlement_generation_api import (
    _r87_rebuild_job,
    _seed_r87_publication_source,
)

TARGET_MONTH = "2026-09"
OTHER_MONTH = "2026-08"


def _add_target_month_result(db_session, *, month=TARGET_MONTH, store_id="r87-store"):
    """A billable current result for the scoped month (no verify rows needed)."""

    result_id = f"scoped-{month}-result"
    db_session.add(
        SettlementFeeResult(
            fee_result_id=result_id,
            coupon_id=f"scoped-{month}-coupon",
            order_id=f"scoped-{month}-order",
            fee_direction=1,
            result_version=1,
            original_business_month=month,
            rule_match_date=date(2026, 9, 2),
            sale_store_id=store_id,
            sku_id="r87-sku",
            product_scope="all",
            product_type="all",
            sale_channel_normalized="live",
            source_amount_cent=1000,
            refunded_amount_cent=0,
            fee_base_cent=1000,
            fee_rate=Decimal("0.08"),
            fee_amount_cent=80,
            rule_version="r87-rule",
            scope_rule_version="r87-scope",
            result_status=1,
            calculation_run_id="scoped-run",
            calculated_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        SettlementFeeResultCurrent(
            coupon_id=f"scoped-{month}-coupon",
            fee_direction=1,
            fee_result_id=result_id,
        )
    )
    db_session.commit()


def _other_month_fingerprint(db_session):
    results = [
        (row.fee_result_id, row.fee_amount_cent, row.result_status)
        for row in db_session.scalars(
            select(SettlementFeeResult)
            .where(SettlementFeeResult.original_business_month == OTHER_MONTH)
            .order_by(SettlementFeeResult.fee_result_id)
        )
    ]
    statements = [
        (row.statement_id, row.statement_month, row.version_no, row.promotion_net_fee_cent)
        for row in db_session.scalars(
            select(SettlementStatement)
            .where(SettlementStatement.statement_month == OTHER_MONTH)
            .order_by(SettlementStatement.statement_id)
        )
    ]
    return results, statements


def test_scoped_close_generates_pending_statement_for_target_month_only(db_session):
    factory = _seed_r87_publication_source(db_session)
    _add_target_month_result(db_session)
    _r87_rebuild_job(db_session, "scoped-close")
    before = _other_month_fingerprint(db_session)

    assert run_settlement_month_rebuild_job(
        job_id="scoped-close",
        factory=factory,
        business_month=TARGET_MONTH,
        claim_id="scoped-close",
    ) is True

    db_session.expire_all()
    scoped = list(
        db_session.scalars(
            select(SettlementStatement).where(
                SettlementStatement.statement_month == TARGET_MONTH
            )
        )
    )
    assert len(scoped) == 1
    statement = scoped[0]
    assert statement.is_current is True
    assert statement.statement_status == 2  # 待确认
    assert statement.promotion_net_fee_cent == 80
    # Never auto-confirmed, never auto-locked.
    assert statement.confirmed_at is None and statement.locked_at is None
    assert statement.confirmed_by is None and statement.lock_version is None

    job = db_session.get(JobRun, "scoped-close")
    billing = (job.metadata_json or {}).get("billing_generation") or {}
    assert billing.get("created", 0) > 0
    assert (job.metadata_json or {}).get("settlement_projection", {}).get(
        "affected_months"
    ) == [TARGET_MONTH]

    # The other month's fee results and statements are byte-for-byte unchanged.
    assert _other_month_fingerprint(db_session) == before


def test_scoped_close_reports_blocked_fee_directions_in_job_result(db_session):
    """A successful partial close must retain its actual attribution issues."""
    factory = _seed_r87_publication_source(db_session)
    _add_target_month_result(db_session)
    _load_dual_fee_fixture(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    order.owner_account_id = "unmapped-sale-account"
    order.owner_account_name = "Unmapped sale account"
    db_session.commit()
    _r87_rebuild_job(db_session, "scoped-with-attribution-issues")
    before = _other_month_fingerprint(db_session)

    assert run_settlement_month_rebuild_job(
        job_id="scoped-with-attribution-issues",
        factory=factory,
        business_month=TARGET_MONTH,
        claim_id="scoped-with-attribution-issues",
    ) is True

    db_session.expire_all()
    job = db_session.get(JobRun, "scoped-with-attribution-issues")
    issues = list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.source_run_id == "scoped-with-attribution-issues",
        DataQualityIssue.issue_type == "dual_fee_missing_sale_store",
    )))
    assert len(issues) == 2
    assert {issue.raw_context_json["fee_direction"] for issue in issues} == {1, 2}
    assert job.status == "success"
    assert job.metadata_json["result"]["issueCount"] == len(issues)
    statement = db_session.scalar(select(SettlementStatement).where(
        SettlementStatement.statement_month == TARGET_MONTH,
        SettlementStatement.is_current.is_(True),
    ))
    assert statement.statement_status == 2
    assert statement.promotion_net_fee_cent == 80
    assert statement.confirmed_at is None and statement.locked_at is None
    assert _other_month_fingerprint(db_session) == before


def test_scoped_close_refuses_a_locked_target_month(db_session):
    factory = _seed_r87_publication_source(db_session)
    _add_target_month_result(db_session)
    db_session.add(
        SettlementStatement(
            statement_id="scoped-locked",
            store_id="r87-store",
            statement_month=TARGET_MONTH,
            version_no=1,
            is_current=True,
            statement_status=4,
        )
    )
    db_session.commit()
    _r87_rebuild_job(db_session, "scoped-locked-job")
    before = _other_month_fingerprint(db_session)

    with pytest.raises(SettlementMonthLockedError):
        run_settlement_month_rebuild_job(
            job_id="scoped-locked-job",
            factory=factory,
            business_month=TARGET_MONTH,
            claim_id="scoped-locked-job",
        )

    db_session.expire_all()
    statements = list(
        db_session.scalars(
            select(SettlementStatement).where(
                SettlementStatement.statement_month == TARGET_MONTH
            )
        )
    )
    assert len(statements) == 1 and statements[0].statement_status == 4
    assert _other_month_fingerprint(db_session) == before


def test_scoped_close_fails_when_the_month_has_no_billable_result(db_session):
    factory = _seed_r87_publication_source(db_session)
    _r87_rebuild_job(db_session, "scoped-empty")
    before = _other_month_fingerprint(db_session)

    with pytest.raises(settlement_rebuild.SettlementSourceNotReady):
        run_settlement_month_rebuild_job(
            job_id="scoped-empty",
            factory=factory,
            business_month=TARGET_MONTH,
            claim_id="scoped-empty",
        )

    db_session.expire_all()
    assert list(
        db_session.scalars(
            select(SettlementStatement).where(
                SettlementStatement.statement_month == TARGET_MONTH
            )
        )
    ) == []
    assert _other_month_fingerprint(db_session) == before
