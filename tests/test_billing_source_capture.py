"""Publication billing sources must survive restart without reading live facts."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import importlib
import importlib.util
from types import SimpleNamespace

import pytest
from sqlalchemy import select, literal

from apps.api.dy_api.models import JobRun
from apps.worker.settlement import StatementSource


def _api():
    assert importlib.util.find_spec("apps.worker.billing_source_capture") is not None, "durable billing source capture is missing"
    return importlib.import_module("apps.worker.billing_source_capture")


def _source():
    return StatementSource(
        source_type=1, source_record_id="fee-a", original_fee_result_id="fee-a",
        coupon_id="coupon-a", order_id="order-a", fee_direction=1,
        original_business_month="2026-08", posting_month="2026-08", store_id="store-a",
        product_scope="service", product_type="type", base_amount_cent=10000,
        fee_amount_cent=1000, source_amount_cent=10000, rule_version="rule-a",
        verify_time=datetime(2026, 8, 8, tzinfo=timezone.utc), fee_rate=Decimal("0.10"),
    )


def test_frozen_source_bundle_round_trips_and_replays(db_session):
    api = _api()
    db_session.add(JobRun(job_id="capture-job", job_name="settlement_rebuild", status="running"))
    db_session.flush()
    source = _source()
    api.freeze_billing_sources(db_session, generation_id="capture-g", job_id="capture-job", sources=[source])
    db_session.commit()
    api.freeze_billing_sources(db_session, generation_id="capture-g", job_id="capture-job", sources=[source])
    assert api.load_billing_sources(db_session, generation_id="capture-g", job_id="capture-job") == [source]
    with pytest.raises(ValueError, match="changed"):
        api.freeze_billing_sources(db_session, generation_id="capture-g", job_id="capture-job", sources=[replace(source, fee_amount_cent=900)])
    assert api.load_billing_sources(db_session, generation_id="capture-g", job_id="capture-job")[0].fee_amount_cent == 1000


def test_missing_capture_is_not_interpreted_as_empty(db_session):
    with pytest.raises(ValueError, match="missing"):
        _api().load_billing_sources(db_session, generation_id="missing", job_id="missing")


def test_capture_accepts_database_slot_rows(db_session):
    api = _api()
    db_session.add(JobRun(job_id="row-job", job_name="settlement_rebuild", status="running"))
    db_session.flush()
    slots = db_session.execute(select(literal("store-a"), literal("2026-08"))).all()
    api.freeze_billing_sources(db_session, generation_id="row-g", job_id="row-job", sources=[], slots=slots)
    assert api.load_billing_slots(db_session, generation_id="row-g", job_id="row-job") == [("store-a", "2026-08")]
    assert api.load_billing_sources(db_session, generation_id="row-g", job_id="row-job") == []


@pytest.mark.parametrize("new_store", ["store-a", "store-b"])
def test_capture_rechecks_authority_after_waiting_for_slot(monkeypatch, new_store):
    api = _api()
    references = iter([
        [SimpleNamespace(source_kind="result", source_id="old", store_id="store-a", month="2026-08")],
        [SimpleNamespace(source_kind="result", source_id="new", store_id=new_store, month="2026-08")],
    ])
    locks = []
    session = SimpleNamespace(
        execute=lambda query: SimpleNamespace(all=lambda: next(references)),
        scalar=lambda query: SimpleNamespace(fee_result_id=query.compile().params["fee_result_id_1"]),
    )
    monkeypatch.setattr(api, "_lock_settlement_slot", lambda session, store, month: locks.append((store, month)))
    monkeypatch.setattr(api, "_result_statement_source", lambda session, result: result.fee_result_id)
    if new_store == "store-b":
        with pytest.raises(ValueError, match="slots changed"):
            api.collect_billing_sources(session, months=["2026-08"], slots=[("empty-store", "2026-08")])
    else:
        assert api.collect_billing_sources(session, months=["2026-08"], slots=[("empty-store", "2026-08")]) == ["new"]
    assert locks == [("empty-store", "2026-08"), ("store-a", "2026-08")]


def test_empty_capture_has_durable_completion_marker(db_session):
    api = _api()
    db_session.add(JobRun(job_id="empty-job", job_name="settlement_rebuild", status="running"))
    db_session.flush()
    api.freeze_billing_sources(db_session, generation_id="empty-g", job_id="empty-job", sources=[], slots=[("store-a", "2026-08")])
    db_session.commit()
    assert api.load_billing_sources(db_session, generation_id="empty-g", job_id="empty-job") == []
    assert api.load_billing_slots(db_session, generation_id="empty-g", job_id="empty-job") == [("store-a", "2026-08")]
