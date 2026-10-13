"""DYDATA-102: the settlement billing-month selector must offer last month.

Production reproduced the bug: ``/settlement`` 单店分账 showed only 2026-08 and
defaulted to it, because ``statement_months`` listed only months that already
hold settlement data.  The operator default must be the previous Shanghai
business month (2026-09 during 2026-10) even while that month is still empty.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.routes.meta import statement_months_with_previous_business_month  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
OCT_2026 = datetime(2026, 10, 9, 10, 0, tzinfo=SHANGHAI)


def test_previous_business_month_is_added_when_data_is_stale():
    months = statement_months_with_previous_business_month(["2026-08"], now=OCT_2026)

    assert months == ["2026-09", "2026-08"]


def test_newest_month_is_first_so_the_selector_defaults_to_it():
    months = statement_months_with_previous_business_month(
        ["2026-06", "2026-08"], now=OCT_2026
    )

    # StoreSettlementPage uses statementMonths[0] as the default month.
    assert months[0] == "2026-09"
    assert months == ["2026-09", "2026-08", "2026-06"]


def test_existing_months_are_never_dropped_or_duplicated():
    months = statement_months_with_previous_business_month(
        ["2026-09", "2026-08"], now=OCT_2026
    )

    assert months == ["2026-09", "2026-08"]


def test_empty_history_still_offers_the_previous_month():
    assert statement_months_with_previous_business_month([], now=OCT_2026) == ["2026-09"]


def test_future_month_does_not_displace_the_previous_business_month():
    months = statement_months_with_previous_business_month(
        ["2026-10", "2026-08"], now=OCT_2026
    )

    assert "2026-09" in months
    assert months == ["2026-10", "2026-09", "2026-08"]


def test_blank_or_non_string_entries_are_ignored():
    months = statement_months_with_previous_business_month(
        ["2026-08", "", None], now=OCT_2026  # type: ignore[list-item]
    )

    assert months == ["2026-09", "2026-08"]


@pytest.mark.parametrize(
    "moment,expected_head",
    [
        (datetime(2026, 10, 1, 0, 0, tzinfo=SHANGHAI), "2026-09"),
        (datetime(2026, 10, 1, 0, 0, tzinfo=ZoneInfo("UTC")), "2026-09"),
        (datetime(2026, 11, 1, 0, 0, tzinfo=SHANGHAI), "2026-10"),
    ],
)
def test_previous_month_follows_the_shanghai_calendar(moment, expected_head):
    assert statement_months_with_previous_business_month([], now=moment)[0] == expected_head
