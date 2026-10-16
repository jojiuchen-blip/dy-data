"""DYDATA-103: month-close readiness alerts must be visible to an operator.

The worker writes a ``month_close_source_not_ready`` quality issue, but the only
existing admin surface counts issues per product-sync run, so a month-close
alert had no reader.  These tests pin the read-only admin contract and the
frontend contract; they are expected to fail before the implementation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from apps.api.dy_api.models import DataQualityIssue
from apps.worker.month_close import READINESS_ISSUE_TYPE, readiness_issue_id

WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"
# The previous complete business month at this instant is 2026-09.
CLOSE_NOW = datetime(2026, 10, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _issue(db_session, month: str, state: str, *, issue_type=READINESS_ISSUE_TYPE):
    db_session.add(
        DataQualityIssue(
            issue_id=readiness_issue_id(month, state),
            issue_type=issue_type,
            severity="warning",
            message=f"{month} 月结未派发：{state}；来源未就绪前不会生成账单。",
            raw_context_json={
                "business_month": month,
                "state": state,
                # Sensitive source detail that must never leave the endpoint.
                "order_id": "secret-order",
                "coupon_id": "secret-coupon",
                "store_id": "secret-store",
            },
            source_run_id="secret-run",
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()


def test_endpoint_is_registered(monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "1")
    from dy_api.main import create_app

    paths = create_app().openapi()["paths"]
    assert "/api/v1/admin/settlement-month-readiness" in paths


def test_readiness_reader_returns_only_safe_fields(db_session):
    from apps.api.dy_api.settlement_audit_readonly import read_month_close_readiness

    _issue(db_session, "2026-09", "no_current_results")

    payload = read_month_close_readiness(db_session, now=CLOSE_NOW)

    assert len(payload.alerts) == 1
    alert = payload.alerts[0]
    assert (alert.month, alert.state, alert.severity) == (
        "2026-09",
        "no_current_results",
        "warning",
    )
    assert "2026-09" in alert.message
    dumped = payload.model_dump()
    flat = str(dumped)
    for leaked in ("secret-order", "secret-coupon", "secret-store", "secret-run"):
        assert leaked not in flat
    assert set(dumped["alerts"][0]) == {"month", "state", "severity", "message"}


def test_malicious_message_and_context_never_leak(db_session):
    """Stored text can contain order numbers, phones or store names: it must not
    reach the response, which is built from a fixed template only."""

    from apps.api.dy_api.settlement_audit_readonly import read_month_close_readiness

    db_session.add(
        DataQualityIssue(
            issue_id="month-close-readiness:2026-09:no_current_results",
            issue_type=READINESS_ISSUE_TYPE,
            severity="error",
            message=(
                "订单 4991234567890 手机号 13800138000 门店 比亚迪深圳三维都灵店 "
                "SOURCE_LEAK_MARKER"
            ),
            raw_context_json={
                "business_month": "2026-09",
                "state": "no_current_results",
                "order_id": "4991234567890",
                "phone": "13800138000",
                "store_name": "比亚迪深圳三维都灵店",
                "context_leak_marker": "CONTEXT_LEAK_MARKER",
            },
            source_run_id="secret-run",
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    flat = str(read_month_close_readiness(db_session, now=CLOSE_NOW).model_dump())

    for leaked in (
        "4991234567890",
        "13800138000",
        "比亚迪深圳三维都灵店",
        "SOURCE_LEAK_MARKER",
        "CONTEXT_LEAK_MARKER",
        "secret-run",
    ):
        assert leaked not in flat
    # Severity is fixed, not taken from the (malicious) stored row.
    assert '"severity": "warning"' in flat or "'severity': 'warning'" in flat


@pytest.mark.parametrize("month", ["2020-01", "2099-12", "2026-08", "2026-07"])
def test_months_outside_the_recent_window_are_dropped(db_session, month):
    from apps.api.dy_api.settlement_audit_readonly import read_month_close_readiness

    _issue(db_session, month, "no_current_results")

    assert read_month_close_readiness(db_session, now=CLOSE_NOW).alerts == []


@pytest.mark.parametrize("state", ["ready", "unknown_state", "", "ACTIVE_REBUILD"])
def test_unknown_states_are_dropped(db_session, state):
    from apps.api.dy_api.settlement_audit_readonly import read_month_close_readiness

    _issue(db_session, "2026-09", state)

    assert read_month_close_readiness(db_session, now=CLOSE_NOW).alerts == []


@pytest.mark.parametrize(
    "state", ["watermark_incomplete", "no_current_results", "locked"]
)
def test_whitelisted_states_are_reported_with_fixed_severity(db_session, state):
    from apps.api.dy_api.settlement_audit_readonly import read_month_close_readiness

    _issue(db_session, "2026-09", state)

    alerts = read_month_close_readiness(db_session, now=CLOSE_NOW).alerts
    assert [(a.month, a.state, a.severity) for a in alerts] == [
        ("2026-09", state, "warning")
    ]


def test_readiness_reader_ignores_other_issue_types(db_session):
    from apps.api.dy_api.settlement_audit_readonly import read_month_close_readiness

    _issue(db_session, "2026-09", "no_current_results", issue_type="dual_fee_non_commission_owner")

    assert read_month_close_readiness(db_session).alerts == []


def test_readiness_reader_is_empty_when_ready(db_session):
    from apps.api.dy_api.settlement_audit_readonly import read_month_close_readiness

    assert read_month_close_readiness(db_session).alerts == []


def test_frontend_client_exposes_the_readiness_fetch():
    client = (WEB_SRC / "api" / "client.ts").read_text(encoding="utf-8")
    assert "fetchSettlementMonthReadiness" in client
    assert "/admin/settlement-month-readiness" in client


def test_sync_panel_renders_and_hides_the_readiness_warning():
    panel = (WEB_SRC / "components" / "AdminProductSyncPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "fetchSettlementMonthReadiness" in panel
    assert "monthReadinessAlerts" in panel
    assert "月结未派发" in panel
