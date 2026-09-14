"""Fail closed before a limited repair expands into an unauthorized month."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from apps.api.dy_api.models import (
    SettlementFeeResult, SettlementProjectionActive, SettlementFeeAdjustment,
    SettlementStatement,
)
from apps.worker import settlement_rebuild
from tests.test_settlement_generation_api import (
    _generation, _manifest, _seed_r87_publication_source, _r87_rebuild_job,
)


def _validate(session, *, allowed_months=("2026-08",), base="r87-base"):
    validator = getattr(settlement_rebuild, "validate_bounded_settlement_scope", None)
    assert callable(validator), "limited repair must have an explicit scope guard"
    return validator(
        session, base_generation_id=base, affected_months=("2026-08",),
        allowed_months=allowed_months,
    )


def test_scope_guard_allows_only_the_authorized_month_without_writing(db_session):
    _seed_r87_publication_source(db_session)
    assert _validate(db_session) == ("2026-08",)
    assert not db_session.new and not db_session.dirty and not db_session.deleted


@pytest.mark.parametrize("allowed", [(), ("2026-09",), ("2026-13",), "2026-08"])
def test_scope_guard_rejects_empty_invalid_or_excluding_allowlist(db_session, allowed):
    _seed_r87_publication_source(db_session)
    with pytest.raises(ValueError):
        _validate(db_session, allowed_months=allowed)


def test_scope_guard_rejects_later_current_fee_even_for_august_request(db_session):
    _seed_r87_publication_source(db_session)
    db_session.scalar(select(SettlementFeeResult)).original_business_month = "2026-09"
    db_session.commit()
    with pytest.raises(ValueError, match="authorized months"):
        _validate(db_session)


def test_scope_guard_rejects_later_cumulative_partition_in_base(db_session):
    _seed_r87_publication_source(db_session)
    _manifest(
        db_session, "r87-base", "ranking", "cumulative:2026-09",
        data_generation_id="r87-base",
    )
    db_session.commit()
    with pytest.raises(ValueError, match="authorized months"):
        _validate(db_session)


@pytest.mark.parametrize("base", ["missing-base", "r87-base"])
def test_scope_guard_rejects_stale_or_missing_active_pointer(db_session, base):
    _seed_r87_publication_source(db_session)
    if base == "r87-base":
        db_session.execute(delete(SettlementProjectionActive))
        db_session.commit()
    with pytest.raises(ValueError, match="active"):
        _validate(db_session, base=base)


@pytest.mark.parametrize("other_month", ["2026-07", "2026-09"])
def test_scope_guard_rejects_cross_month_adjustment_closure(db_session, other_month):
    _seed_r87_publication_source(db_session)
    db_session.add(SettlementFeeAdjustment(
        adjustment_id="scope-adjustment", original_fee_result_id="r87-result",
        coupon_id="r87-coupon", order_id="r87-order", fee_direction=1,
        original_business_month="2026-08", adjustment_posting_month=other_month,
        adjustment_type=1, adjustment_base_cent=-100, adjustment_fee_cent=-8,
        rule_version="r87-rule", adjustment_reason="synthetic scope test",
        occurred_at=datetime.now(timezone.utc), created_by="synthetic-user",
    ))
    db_session.commit()
    with pytest.raises(ValueError, match="authorized months"):
        _validate(db_session)


def test_bounded_publication_rejects_later_month_before_writing(db_session):
    factory = _seed_r87_publication_source(db_session)
    db_session.scalar(select(SettlementFeeResult)).original_business_month = "2026-09"
    db_session.commit()
    _r87_rebuild_job(db_session, "scope-publish")
    with pytest.raises(ValueError, match="authorized months"):
        settlement_rebuild.refresh_active_settlement_lineage(
            factory, job_id="scope-publish", claim_id="scope-publish",
            allowed_months=("2026-08",),
        )
    db_session.expire_all()
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == "r87-base"
    assert db_session.scalar(select(SettlementStatement)) is None


def test_bounded_publication_final_validation_rolls_back_real_billing(db_session):
    factory = _seed_r87_publication_source(db_session)
    _r87_rebuild_job(db_session, "scope-final-validation")
    observed_writes = []

    def reject_billing(session):
        if session.scalar(select(SettlementStatement)) is not None:
            observed_writes.append(True)
            raise ValueError("synthetic financial snapshot changed")

    with pytest.raises(ValueError, match="synthetic financial snapshot changed"):
        settlement_rebuild.refresh_active_settlement_lineage(
            factory, job_id="scope-final-validation", claim_id="scope-final-validation",
            allowed_months=("2026-08",), validation_callback=reject_billing,
        )
    db_session.expire_all()
    assert observed_writes == [True]
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == "r87-base"
    assert db_session.scalar(select(SettlementStatement)) is None
    assert settlement_rebuild.refresh_active_settlement_lineage(
        factory, job_id="scope-final-validation", claim_id="scope-final-validation",
        allowed_months=("2026-08",),
    )
    assert settlement_rebuild.refresh_active_settlement_lineage(
        factory, job_id="scope-final-validation", claim_id="scope-final-validation",
        allowed_months=("2026-08",),
    ) is None


def test_bounded_noop_rechecks_active_in_recording_transaction(db_session, monkeypatch):
    factory = _seed_r87_publication_source(db_session)
    _r87_rebuild_job(db_session, "scope-noop-race")
    assert settlement_rebuild.refresh_active_settlement_lineage(
        factory, job_id="scope-noop-race", claim_id="scope-noop-race",
        allowed_months=("2026-08",),
    )
    record = settlement_rebuild._record_settlement_projection_noop

    def move_pointer_before_record(*args, **kwargs):
        with factory() as session:
            session.execute(delete(SettlementProjectionActive))
            session.commit()
        return record(*args, **kwargs)

    monkeypatch.setattr(settlement_rebuild, "_record_settlement_projection_noop", move_pointer_before_record)
    with pytest.raises(ValueError, match="active"):
        settlement_rebuild.refresh_active_settlement_lineage(
            factory, job_id="scope-noop-race", claim_id="scope-noop-race",
            allowed_months=("2026-08",),
        )


def test_scope_guard_checks_actual_staging_partitions_not_only_current_sources(db_session):
    _seed_r87_publication_source(db_session)
    _generation(db_session, "scope-staging", base_generation_id="r87-base", state="staging", depth=1)
    _manifest(
        db_session, "scope-staging", "ranking", "cumulative:2026-09",
        data_generation_id="scope-staging", base_generation_id="r87-base",
    )
    db_session.commit()
    with pytest.raises(ValueError, match="authorized months"):
        settlement_rebuild.validate_bounded_settlement_scope(
            db_session, base_generation_id="r87-base", generation_id="scope-staging",
            affected_months=("2026-08",), allowed_months=("2026-08",),
        )


def test_bounded_noop_rejects_earlier_unauthorized_actual_partition(db_session):
    factory = _seed_r87_publication_source(db_session)
    _r87_rebuild_job(db_session, "scope-noop-partitions")
    assert settlement_rebuild.refresh_active_settlement_lineage(
        factory, job_id="scope-noop-partitions", claim_id="scope-noop-partitions",
        allowed_months=("2026-08",),
    )
    db_session.expire_all()
    current = db_session.get(SettlementProjectionActive, "settlement").generation_id
    _manifest(
        db_session, current, "monthly", "2026-07",
        data_generation_id=current, base_generation_id="r87-base",
    )
    db_session.commit()
    with pytest.raises(ValueError, match="authorized months"):
        settlement_rebuild.refresh_active_settlement_lineage(
            factory, job_id="scope-noop-partitions", claim_id="scope-noop-partitions",
            allowed_months=("2026-08",),
        )
