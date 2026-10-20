"""Replay contract tests with synthetic evidence and local-only databases."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    Base, DataQualityIssue, DouyinRefundEvent, JobImpact, JobRun, RawDouyinOrder,
    RawDouyinOrderCoupon, RawDouyinRefundRecord, SettlementFeeAdjustment,
    SettlementFeeResult, SettlementFeeResultCurrent, SettlementStatementEntry,
)
from apps.worker import refund_replay as replay
from apps.worker.collectors import refunds
from apps.worker.repositories import payload_fingerprint
from scripts.replay_refund_evidence import main, parse_args


@pytest.fixture()
def replay_engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'replay.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def evidence(number: int = 1) -> dict:
    return {"refund_event_id": f"refund-{number}", "order_id": f"order-{number}",
            "coupon_id": f"coupon-{number}", "status": 50, "refund_type": "partial",
            "refund_amount_cent": 1000, "completed_at": "2026-08-01T10:00:00+08:00"}


def seed(engine, payload: dict | None = None, *, number: int = 1, source: str = "source-run") -> int:
    payload = payload or evidence(number)
    with Session(engine) as session, session.begin():
        session.add(RawDouyinOrder(order_id=f"order-{number}"))
        session.flush()
        session.add(RawDouyinOrderCoupon(coupon_id=f"coupon-{number}", order_id=f"order-{number}"))
        raw = RawDouyinRefundRecord(
            source_record_key=f"refund-{number}", refund_id=f"refund-{number}", order_id=f"order-{number}",
            raw_refund_status="50", normalized_refund_status=2, refund_amount_cent=payload.get("refund_amount_cent"),
            refund_completed_at=datetime.fromisoformat("2026-08-01T10:00:00+08:00").astimezone(timezone.utc),
            source_run_id=source, source_observed_at=datetime.fromisoformat("2026-08-01T10:00:00+08:00").astimezone(timezone.utc),
            payload_hash=payload_fingerprint(payload), raw_payload=payload,
        )
        session.add(raw)
        session.flush()
        return raw.id


def preview(engine, **kwargs):
    return replay.preview_refunds(engine, replay.ReplayBounds("source-run", 0, 100, 1), **kwargs)


def apply(engine, document, run="repair-run"):
    return replay.apply_refunds(engine, document, expected_digest=document["preview_digest"],
                                repair_run_id=run, reason="Synthetic evidence acceptance")


def seed_financial(session: Session, kind: str, *, order_id="order-1", coupon_id="coupon-1") -> None:
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    if kind == "current":
        session.add(SettlementFeeResultCurrent(coupon_id=coupon_id, fee_direction=1, fee_result_id="old-result"))
    elif kind == "adjustment":
        session.add(SettlementFeeAdjustment(adjustment_id="adjustment", original_fee_result_id="old-result",
            refund_event_id="old-refund", coupon_id=coupon_id, order_id=order_id, fee_direction=1,
            original_business_month="2026-08", adjustment_posting_month="2026-09", adjustment_type=1,
            rule_version="r1", adjustment_reason="existing protected adjustment", occurred_at=now, created_by="test"))
    elif kind == "statement":
        session.add(SettlementStatementEntry(statement_entry_id="entry", statement_id="confirmed-invoiced-statement",
            statement_line_id="line", source_type=1, source_record_id="old-result", original_fee_result_id="old-result",
            coupon_id=coupon_id, order_id=order_id, fee_direction=1, original_business_month="2026-08",
            statement_posting_month="2026-08", rule_version="r1"))
    else:
        session.add(SettlementFeeResult(fee_result_id="old-result", coupon_id=coupon_id, order_id=order_id,
            fee_direction=1, original_business_month="2026-08", rule_match_date=date(2026, 8, 1), sku_id="sku",
            sale_channel_normalized="store", rule_version="r1", scope_rule_version="r1",
            calculation_run_id="calculation", calculated_at=now))


def test_preview_is_select_only_and_does_not_expose_payload_or_order_pii(replay_engine):
    raw_id = seed(replay_engine)
    statements = []
    event.listen(replay_engine, "before_cursor_execute", lambda conn, cursor, statement, params, context, many: statements.append(statement))
    result = preview(replay_engine)
    assert result["scanned"] == result["ready"] == 1
    assert result["blocked"] == result["existing_events"] == 0
    assert result["rows"][0]["raw_id"] == raw_id
    assert all(statement.lstrip().upper().startswith(("SELECT", "PRAGMA")) for statement in statements)
    output = json.dumps(result)
    assert all(value not in output for value in ("order-1", "coupon-1", "refund-1", "raw_payload"))
    with Session(replay_engine) as session:
        assert session.scalar(select(func.count(JobRun.job_id))) == 0
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0


def test_unknown_amount_unit_is_blocked_without_any_write(replay_engine):
    payload = evidence()
    del payload["refund_amount_cent"]
    payload["refund_info_list"] = [{"refund_amount": 1000}]
    payload["total_refund_amount"] = 1000
    seed(replay_engine, payload)
    statements = []
    event.listen(replay_engine, "before_cursor_execute", lambda conn, cursor, statement, params, context, many: statements.append(statement))
    result = preview(replay_engine)
    assert result["ready"] == 0 and result["blocked"] == 1
    assert "refund_amount_unit_ambiguous" in result["rows"][0]["reasons"]
    assert result["financial_guard"] == {"policy": "only_otherwise_ready", "not_checked_is_not_approval": True,
                                         "checked": 0, "not_checked": 1}
    assert not any(table in statement for statement in statements for table in (
        "settlement_fee_result", "settlement_fee_adjustment", "settlement_statement_entry"))
    assert apply(replay_engine, result)["blocked"] == 1
    with Session(replay_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0


def test_explicit_cent_snapshot_can_backfill_legacy_null_without_fabricating_payload(replay_engine):
    raw_id = seed(replay_engine)
    with Session(replay_engine) as session, session.begin():
        session.get(RawDouyinRefundRecord, raw_id).refund_amount_cent = None
    document = preview(replay_engine)
    assert document["ready"] == 1
    result = apply(replay_engine, document)
    assert result["applied"] == 1 and result["blocked"] == 0
    with Session(replay_engine) as session:
        raw = session.get(RawDouyinRefundRecord, raw_id)
        assert raw.refund_amount_cent == 1000 and raw.raw_payload == evidence()
        assert raw.payload_hash == document["rows"][0]["payload_hash"] and raw.source_run_id == "source-run"


def test_nonnull_snapshot_amount_mismatch_is_blocked(replay_engine):
    raw_id = seed(replay_engine)
    with Session(replay_engine) as session, session.begin():
        session.get(RawDouyinRefundRecord, raw_id).refund_amount_cent = 999
    document = preview(replay_engine)
    assert document["ready"] == 0 and "refund_amount_snapshot_mismatch" in document["reasons"]
    assert apply(replay_engine, document)["applied"] == 0


def test_platform_refund_initiator_never_becomes_financial_scope(replay_engine):
    payload = {**evidence(), "refund_info_list": [], "refund_type": 2}
    seed(replay_engine, payload)
    result = preview(replay_engine)
    assert result["ready"] == 0 and "refund_scope_not_explicit" in result["reasons"]


def test_existing_conflicting_event_is_blocked_without_type_or_amount_correction(replay_engine):
    seed(replay_engine)
    with Session(replay_engine) as session, session.begin():
        session.add(DouyinRefundEvent(refund_event_id="refund-1", order_id="order-1", coupon_id="coupon-1",
            refund_type=2, refund_status=2, refund_amount_cent=999, occurred_at=datetime(2026, 8, 1, 2, tzinfo=timezone.utc),
            payload_fingerprint=payload_fingerprint(evidence()), source_run_id="original-event-run"))
    document = preview(replay_engine)
    assert document["ready"] == 0 and document["existing_events"] == 1
    assert document["reasons"] == {"existing_event_requires_reconciliation": 1}
    assert apply(replay_engine, document)["blocked"] == 1
    with Session(replay_engine) as session:
        row = session.scalar(select(DouyinRefundEvent))
        assert row.refund_type == 2 and row.refund_amount_cent == 999 and row.source_run_id == "original-event-run"


def test_repeated_apply_is_idempotent_preserves_evidence_success_time_and_dqi(replay_engine):
    raw_id = seed(replay_engine)
    with Session(replay_engine) as session, session.begin():
        session.add(DataQualityIssue(issue_id="old-issue", issue_type="old_refund_missing_type",
            severity="error", message="Historical evidence", source_run_id="source-run"))
    document = preview(replay_engine)
    result = apply(replay_engine, document)
    assert result["applied"] == result["job_impacts"] == 1
    assert result["needs_downstream_processing"] is True
    assert apply(replay_engine, document) == result
    with Session(replay_engine) as session:
        row = session.get(RawDouyinRefundRecord, raw_id)
        assert row.raw_payload == evidence() and row.payload_hash == payload_fingerprint(evidence())
        assert row.source_run_id == "source-run"
        event_row = session.scalar(select(DouyinRefundEvent))
        first_success_time = event_row.successful_observed_at
        assert event_row.source_run_id == "repair-run" and first_success_time is not None
        assert session.scalar(select(JobImpact)).source_run_id == "repair-run"
        assert session.get(DataQualityIssue, "old-issue").issue_type == "old_refund_missing_type"
        audit = session.get(JobRun, "repair-run")
        assert audit.status == "success" and audit.metadata_json["result"] == result
        assert audit.metadata_json["needs_downstream_processing"] is True
        assert session.get(JobRun, "source-run") is None
    again = apply(replay_engine, preview(replay_engine), run="repair-again")
    assert again["unchanged"] == 1 and again["applied"] == again["job_impacts"] == 0
    with Session(replay_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 1
        assert session.scalar(select(DouyinRefundEvent)).successful_observed_at == first_success_time


@pytest.mark.parametrize("change_hash", [True, False])
def test_changed_snapshot_is_refused_even_if_stored_hash_was_not_updated(replay_engine, change_hash):
    raw_id = seed(replay_engine)
    document = preview(replay_engine)
    with Session(replay_engine) as session, session.begin():
        raw = session.get(RawDouyinRefundRecord, raw_id)
        raw.raw_payload = {**raw.raw_payload, "refund_amount_cent": 2000}
        if change_hash:
            raw.payload_hash = payload_fingerprint(raw.raw_payload)
    result = apply(replay_engine, document)
    assert result["applied"] == 0 and result["blocked"] == 1
    assert result["reasons"] == {"snapshot_changed_since_preview": 1}


@pytest.mark.parametrize("kind", ["result", "current", "adjustment", "statement"])
def test_any_existing_financial_projection_blocks_event_creation(replay_engine, kind):
    seed(replay_engine)
    with Session(replay_engine) as session, session.begin():
        seed_financial(session, kind)
    result = preview(replay_engine)
    assert result["ready"] == 0 and result["blocked"] == 1
    assert "existing_financial_projection_requires_reconciliation" in result["reasons"]
    applied = apply(replay_engine, result)
    assert applied["blocked"] == 1 and applied["applied"] == 0
    with Session(replay_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0


def test_financial_projection_added_after_preview_is_blocked(replay_engine):
    seed(replay_engine)
    document = preview(replay_engine)
    with Session(replay_engine) as session, session.begin():
        seed_financial(session, "result", order_id="different-order")  # Related coupon still blocks.
    result = apply(replay_engine, document)
    assert result["blocked"] == 1 and "existing_financial_projection_requires_reconciliation" in result["reasons"]


def test_cursor_source_filter_and_frozen_upper_are_respected(replay_engine):
    first_id = seed(replay_engine)
    seed(replay_engine, number=2, source="other-source")
    third_id = seed(replay_engine, number=3)
    first = replay.preview_refunds(replay_engine, replay.ReplayBounds("source-run", 0, 1, 1))
    assert first["cursor"] == first_id and first["upper_id"] == third_id and first["has_more"] is True
    seed(replay_engine, number=4)
    second = replay.preview_refunds(replay_engine, replay.ReplayBounds("source-run", first["cursor"], 1, 1), upper_id=first["upper_id"])
    assert second["cursor"] == third_id and second["scanned"] == 1 and second["has_more"] is False
    empty = replay.preview_refunds(replay_engine, replay.ReplayBounds("no-source", 0, 1, 1))
    assert empty["scanned"] == empty["upper_id"] == empty["cursor"] == 0


def test_financial_coupon_scope_is_bounded_before_fact_queries(replay_engine, monkeypatch):
    seed(replay_engine)
    with Session(replay_engine) as session, session.begin():
        session.add_all(RawDouyinOrderCoupon(coupon_id=f"extra-coupon-{number}", order_id="order-1") for number in range(100))

    def forbid_fact_scan(*args):
        pytest.fail("oversized coupon scope must not query financial facts")

    monkeypatch.setattr(replay, "_has_financial_projection", forbid_fact_scan)
    document = preview(replay_engine)
    assert document["ready"] == 0 and document["reasons"] == {"financial_scope_too_large": 1}
    assert document["rows"][0]["financial_check"] == "not_checked_scope_too_large"


@pytest.mark.parametrize("field,value", [("after_id", -1), ("after_id", True), ("batch_size", 101),
    ("batch_size", 0), ("max_batches", 21), ("max_batches", 0), ("source_run_id", ""),
    ("statement_timeout_ms", 0), ("lock_timeout_ms", 1001), ("transaction_timeout_ms", 30001)])
def test_request_bounds_are_mandatory_and_finite(field, value):
    options = dict(source_run_id="source", after_id=0, batch_size=100, max_batches=20)
    options[field] = value
    with pytest.raises(replay.RefundReplayError):
        replay.ReplayBounds(**options)


def test_digest_and_apply_authorization_are_required(replay_engine):
    seed(replay_engine)
    document = preview(replay_engine)
    changed = deepcopy(document)
    changed["rows"][0]["payload_hash"] = "0" * 64
    with pytest.raises(replay.RefundReplayError, match="digest mismatch"):
        apply(replay_engine, changed)
    with pytest.raises(replay.RefundReplayError, match="separate repair_run_id"):
        replay.apply_refunds(replay_engine, document, expected_digest=document["preview_digest"], repair_run_id="source-run", reason="repair")
    with pytest.raises(SystemExit):
        parse_args(["--source-run-id", "s", "--after-id", "0", "--batch-size", "1", "--max-batches", "1", "--apply"])


def test_collector_rejection_or_timeout_rolls_back_entire_batch(replay_engine, monkeypatch):
    seed(replay_engine)
    seed(replay_engine, number=2)
    document = preview(replay_engine)
    process = refunds._process_refund

    def interrupt(session, payload, **kwargs):
        if payload["refund_event_id"] == "refund-2":
            raise TimeoutError("contains-sensitive-payload-that-must-not-be-output")
        return process(session, payload, **kwargs)

    monkeypatch.setattr(refunds, "_process_refund", interrupt)
    result = apply(replay_engine, document)
    assert result["blocked"] == 2 and result["applied"] == result["job_impacts"] == 0
    assert "sensitive" not in json.dumps(result)
    with Session(replay_engine) as session:
        assert session.scalar(select(func.count(DouyinRefundEvent.id))) == 0
        assert session.get(JobRun, "repair-run").status == "failed"


def test_default_cli_is_read_only_and_has_no_amount_override(replay_engine, capsys):
    seed(replay_engine)
    code = main(["--database-url", str(replay_engine.url), "--source-run-id", "source-run",
                 "--after-id", "0", "--batch-size", "1", "--max-batches", "1"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["mode"] == "preview" and result["ready"] == 1
    process = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "scripts/replay_refund_evidence.py"), "--help"],
                             capture_output=True, encoding="utf-8", check=False)
    assert process.returncode == 0 and "--apply" in process.stdout
    assert "override" not in process.stdout
