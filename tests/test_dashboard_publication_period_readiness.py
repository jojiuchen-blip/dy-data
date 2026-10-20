"""Financial completeness is frozen; API reads never inspect scheduler state."""
from datetime import UTC, date, datetime
from pathlib import Path
import sys

import pytest
from sqlalchemy import delete, event, func, insert, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from apps.api.dy_api.dashboard_publications import finance, period_readiness, sources
from apps.api.dy_api.dashboard_publications.lifecycle import PublicationError
from apps.api.dy_api.dashboard_publications.schema import metadata, runs, source_counters
from apps.api.dy_api.models import JobRun, SettlementStatement
from apps.worker.month_close import month_business_dates
from apps.worker.priority_scheduler import _day_state, _priority_rows_for_day
from test_month_close import _publish_day

CUTOFF = datetime(2026, 10, 1, tzinfo=UTC)
FILTERS = dict(month="2026-09", fee_direction="PROMOTION", metric_scope="MONTH")


def _freeze(session, identifier, module):
    session.execute(insert(runs).values(id=identifier, module=module, status="building",
        cutoff=CUTOFF, created_at=CUTOFF, stats_json={}))
    builder = finance.build_finance if module == "finance" else finance.build_settlement
    return builder(session, identifier, CUTOFF)


def _assert_blocked(call):
    with pytest.raises(PublicationError) as caught:
        call()
    assert caught.value.http_status == 503
    assert caught.value.code == "PUBLICATION_PERIOD_NOT_READY"
    assert "账期数据尚未准备完成" in str(caught.value)


def test_real_day_recovery_changes_financial_fingerprint_but_not_frozen_reads(db_session, monkeypatch):
    metadata.create_all(db_session.bind)
    for day in month_business_dates("2026-09"):
        _publish_day(db_session, day)
    missing_day = date(2026, 9, 14)
    winning = _day_state(missing_day, _priority_rows_for_day(db_session, missing_day)).parent
    winning.status = "failed"
    db_session.flush()
    db_session.execute(insert(source_counters), [dict(source_name=name, generation=0,
        changed_at=CUTOFF) for name in sources.SOURCE_TABLES])
    first = period_readiness.capture(db_session, CUTOFF)
    assert first["months"]["2026-09"] | {"revision": ""} == {
        "ready": False, "success_days": 29, "total_days": 30, "revision": ""}
    assert first["months"]["2026-10"]["ready"] is False
    before = sources.source_fingerprint(db_session, "finance", now=CUTOFF)
    sales_before = sources.source_fingerprint(db_session, "sales", now=CUTOFF)
    for module in ("finance", "settlement"):
        _freeze(db_session, "incomplete-" + module, module)
    _assert_blocked(lambda: finance.read_finance_summary(db_session, "incomplete-finance", **FILTERS))
    _assert_blocked(lambda: finance.read_finance_invoices(db_session, "incomplete-finance", **FILTERS))
    _assert_blocked(lambda: finance.export_finance_invoices(db_session, "incomplete-finance", **FILTERS))
    _assert_blocked(lambda: finance.read_store_ranking(db_session, "incomplete-settlement",
        {"period_key": "2026-09", "ranking_basis": "PROMOTION_FEE_MONTH"}))
    _assert_blocked(lambda: finance.read_monthly_settlement(db_session, "incomplete-settlement",
        {"month": "2026-09", "store_id": "none"}))
    assert "2026-09" in finance.read_filters(db_session, "incomplete-finance")["statement_months"]
    winning.status = "success"
    db_session.flush()
    assert sources.source_fingerprint(db_session, "finance", now=CUTOFF) != before
    assert sources.source_fingerprint(db_session, "sales", now=CUTOFF) == sales_before
    _assert_blocked(lambda: finance.read_finance_summary(db_session, "incomplete-finance", **FILTERS))
    _freeze(db_session, "complete-finance", "finance")
    # September is complete without any fee result. A genuine zero is allowed.
    result = finance.read_finance_summary(db_session, "complete-finance", **FILTERS)
    assert set(result["metrics"].values()) == {0}
    assert finance.read_finance_invoices(db_session, "complete-finance", **FILTERS)["list"] == []
    assert finance.export_finance_invoices(db_session, "complete-finance", **FILTERS) == []
    # August is still missing, so cumulative values must not imply completeness.
    _assert_blocked(lambda: finance.read_finance_summary(db_session, "complete-finance",
        **(FILTERS | {"metric_scope": "CUMULATIVE"})))
    for day in month_business_dates("2026-08"):
        _publish_day(db_session, day)
    _freeze(db_session, "prefix-finance", "finance")
    _freeze(db_session, "prefix-settlement", "settlement")
    monkeypatch.setattr(period_readiness, "capture", lambda *a: pytest.fail("reader called scheduler capture"))
    sql = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        sql.append(statement)
    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        assert set(finance.read_finance_summary(db_session, "prefix-finance",
            **(FILTERS | {"metric_scope": "CUMULATIVE"}))["metrics"].values()) == {0}
        assert finance.read_store_ranking(db_session, "prefix-settlement", {
            "period_key": "2026-09", "ranking_basis": "PROMOTION_FEE_MONTH"})["total"] == 0
        finance.read_monthly_settlement(db_session, "prefix-settlement", {"month": "2026-09", "store_id": "none"})
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
    assert sql and all(statement.lstrip().upper().startswith("SELECT") for statement in sql)
    assert all("job_runs" not in statement.lower() for statement in sql)
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 0


@pytest.mark.parametrize("snapshot", [None, {}, {"schema_version": 1, "months": {}},
    {"schema_version": 1, "months": {"2026-09": {"ready": "true"}}}])
def test_absent_or_invalid_frozen_evidence_never_means_ready(snapshot):
    _assert_blocked(lambda: period_readiness.require(snapshot, "2026-09", cumulative=False))


def test_reader_missing_metadata_and_future_period_are_unavailable(db_session):
    metadata.create_all(db_session.bind)
    _freeze(db_session, "no-evidence", "finance")
    db_session.execute(delete(finance.dimensions).where(finance.dimensions.c.kind == "period_readiness"))
    _assert_blocked(lambda: finance.read_finance_summary(db_session, "no-evidence", **FILTERS))
    _assert_blocked(lambda: period_readiness.require({"schema_version": 1, "months": {}},
        "9999-12", cumulative=True))
