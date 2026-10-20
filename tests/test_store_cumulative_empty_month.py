"""DYDATA-102: an empty month must not reset the formal cumulative amount.

Confirmed requirement: when the selected period (2026-09) holds no monthly
settlement rows, that period's own fees are zero / an empty state, but the
"累计" figure must keep aggregating the formal window 2026-08 → the selected
month.  A store whose August carries fees therefore still reports August's
cumulative while September is empty.

The fixture is a single store with August amounts and nothing in September, run
against a real SQLite database and the real projection lineage, so the API's
`computedCumulative` is what the settlement page's two cumulative cards render.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from publication_fixture_helpers import publish_fixture
from dy_api.auth import AuthContext, get_current_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    AggStoreRanking,
    DimStore,
    SettlementMonthlyOverlay,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementRankingOverlay,
    SettlementStatement,
)

STORE_ID = "cumulative-single-store"
AUGUST = "2026-08"
SEPTEMBER = "2026-09"
GENERATION = "dydata-102-aug-sep"
AUGUST_PROMOTION_CENT = 2400
AUGUST_MANAGEMENT_CENT = 1200


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=f"{STORE_ID}-user",
        username=f"{STORE_ID}-user",
        display_name="Cumulative Store User",
        role="store",
        store_ids=(STORE_ID,),
        auth_type="user",
        store_scope_mode="assigned",
    )
    return TestClient(app)


@pytest.fixture()
def admin_client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    """Highest administrator, used for the global ranking endpoint."""

    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="system-admin",
        username="system-admin",
        display_name="System Admin",
        role="highest_admin",
        store_ids=(),
        auth_type="env_admin",
    )
    return TestClient(app)


def _settlement(client: TestClient, month: str) -> dict:
    response = client.get(
        f"/api/v1/stores/{STORE_ID}/monthly-settlement",
        params={"month": month, "productScope": "all", "productType": "all"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _ranking(client: TestClient, period_key: str) -> dict:
    response = client.get(
        "/api/v1/dashboard/store-ranking",
        params={
            "periodType": "CUMULATIVE",
            "periodKey": period_key,
            "page": 1,
            "pageSize": 20,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _publish_august_only(db_session: Session) -> None:
    """August materialized; September has no monthly and no cumulative rows."""

    db_session.add(DimStore(store_id=STORE_ID, store_name="Cumulative Store", is_active=True))
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=GENERATION, state="published", input_fingerprint="aug-sep-test"
        )
    )
    db_session.flush()
    for artifact, partition_key in (
        ("monthly", AUGUST),
        ("ranking", f"monthly:{AUGUST}"),
        ("ranking", f"cumulative:{AUGUST}"),
    ):
        db_session.add(
            SettlementProjectionPartitionManifest(
                generation_id=GENERATION,
                artifact=artifact,
                partition_key=partition_key,
                source_kind="overlay",
                data_generation_id=GENERATION,
            )
        )
    db_session.add(
        SettlementMonthlyOverlay(
            generation_id=GENERATION,
            partition_key=AUGUST,
            month=AUGUST,
            store_id=STORE_ID,
            product_scope="all",
            product_type="all",
            promotion_net_fee_cent=AUGUST_PROMOTION_CENT,
            management_net_fee_cent=AUGUST_MANAGEMENT_CENT,
        )
    )
    db_session.add(
        SettlementRankingOverlay(
            generation_id=GENERATION,
            partition_key=f"cumulative:{AUGUST}",
            period_type=2,
            period_key=AUGUST,
            month=AUGUST,
            store_id=STORE_ID,
            store_name="Cumulative Store",
            product_scope="all",
            product_type="all",
            promotion_net_fee_cent=AUGUST_PROMOTION_CENT,
            management_net_fee_cent=AUGUST_MANAGEMENT_CENT,
            net_settlement_reference_cent=AUGUST_PROMOTION_CENT - AUGUST_MANAGEMENT_CENT,
        )
    )
    db_session.add(
        SettlementProjectionActive(projection_name="settlement", generation_id=GENERATION)
    )
    db_session.commit()


def test_empty_september_keeps_the_formal_cumulative_and_does_not_invent_month_rows(
    client: TestClient, db_session: Session
) -> None:
    _publish_august_only(db_session)

    publish_fixture(db_session, "settlement")
    response = client.get(
        f"/api/v1/stores/{STORE_ID}/monthly-settlement",
        params={"month": SEPTEMBER, "productScope": "all", "productType": "all"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]

    # The empty period itself stays an honest empty state.
    assert data["month"] == SEPTEMBER
    assert data["statement"] is None
    assert data["lines"] == []
    assert data["metrics"]["promotionNetFeeCent"] == 0
    assert data["metrics"]["managementNetFeeCent"] == 0
    assert data["metrics"]["salesAmountCent"] == 0

    # The formal cumulative window 2026-08 → 2026-09 is not reset by the empty
    # period: August's amounts are what the two cumulative cards must show.
    assert data["computedCumulative"] == {
        "promotionNetFeeCent": AUGUST_PROMOTION_CENT,
        "managementNetFeeCent": AUGUST_MANAGEMENT_CENT,
    }


def test_empty_september_does_not_write_statements_or_confirmations(
    client: TestClient, db_session: Session
) -> None:
    _publish_august_only(db_session)

    publish_fixture(db_session, "settlement")
    response = client.get(
        f"/api/v1/stores/{STORE_ID}/monthly-settlement",
        params={"month": SEPTEMBER, "productScope": "all", "productType": "all"},
    )

    assert response.status_code == 200, response.text

    from sqlalchemy import func, select  # noqa: PLC0415

    from apps.api.dy_api.models import (  # noqa: PLC0415
        SettlementStatement,
        SettlementStatementConfirmation,
    )

    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 0
    assert (
        db_session.scalar(select(func.count()).select_from(SettlementStatementConfirmation))
        == 0
    )


def test_ranking_cumulative_for_an_empty_september_keeps_the_august_total(
    admin_client: TestClient, db_session: Session
) -> None:
    """The ranking API must apply the same published-window semantics.

    August carries the only published cumulative period; while September has no
    cumulative partition of its own, selecting September still reports the
    formal window 2026-08 → 2026-09, i.e. the August figures — never zero and
    never an unpublished legacy value.
    """

    _publish_august_only(db_session)

    publish_fixture(db_session, "settlement")
    august = _ranking(admin_client, AUGUST)
    september = _ranking(admin_client, SEPTEMBER)

    assert august["totals"]["promotionNetFeeCent"] == AUGUST_PROMOTION_CENT
    assert august["totals"]["managementNetFeeCent"] == AUGUST_MANAGEMENT_CENT

    # The response keeps echoing the month the operator selected.
    assert september["periodType"] == "CUMULATIVE"
    assert september["periodKey"] == SEPTEMBER
    assert september["formalPeriodStartMonth"] == AUGUST
    assert september["totals"] == august["totals"]
    # The table rows agree with the totals, so `/ranking` and `/settlement`
    # cannot disagree about the same store and period.
    assert [row["storeId"] for row in september["list"]] == [STORE_ID]
    assert september["list"][0]["promotionNetFeeCent"] == AUGUST_PROMOTION_CENT
    assert september["list"][0]["managementNetFeeCent"] == AUGUST_MANAGEMENT_CENT
    assert september["total"] == 1


def test_ranking_cumulative_prefers_a_published_september_partition(
    admin_client: TestClient, db_session: Session
) -> None:
    """A published 2026-09 cumulative period wins, even when it is zero."""

    _publish_august_only(db_session)
    db_session.add(
        SettlementProjectionPartitionManifest(
            generation_id=GENERATION,
            artifact="ranking",
            partition_key=f"cumulative:{SEPTEMBER}",
            source_kind="overlay",
            data_generation_id=GENERATION,
        )
    )
    db_session.add(
        SettlementRankingOverlay(
            generation_id=GENERATION,
            partition_key=f"cumulative:{SEPTEMBER}",
            period_type=2,
            period_key=SEPTEMBER,
            month=SEPTEMBER,
            store_id=STORE_ID,
            store_name="Cumulative Store",
            product_scope="all",
            product_type="all",
            promotion_net_fee_cent=0,
            management_net_fee_cent=0,
            net_settlement_reference_cent=0,
        )
    )
    db_session.commit()

    publish_fixture(db_session, "settlement")
    september = _ranking(admin_client, SEPTEMBER)

    assert september["periodKey"] == SEPTEMBER
    assert september["totals"]["promotionNetFeeCent"] == 0
    assert september["totals"]["managementNetFeeCent"] == 0
    assert september["total"] == 1


def test_settled_august_with_an_empty_september_still_reports_august_cumulative(
    client: TestClient, db_session: Session
) -> None:
    """Acceptance scenario: August has a bill, September has no rows at all.

    Selecting 2026-09 must serve the empty state for that period's own fees while
    ``computedCumulative`` still equals the 2026-08 cumulative — the formal window
    2026-08 → 2026-09 — and must never collapse to zero with the empty period.
    """

    _publish_august_only(db_session)
    db_session.add(
        SettlementStatement(
            statement_id="stmt-august",
            store_id=STORE_ID,
            statement_month=AUGUST,
            version_no=1,
            is_current=True,
            statement_status=2,
            promotion_original_fee_cent=AUGUST_PROMOTION_CENT,
            promotion_adjustment_fee_cent=0,
            promotion_net_fee_cent=AUGUST_PROMOTION_CENT,
            management_original_fee_cent=AUGUST_MANAGEMENT_CENT,
            management_adjustment_fee_cent=0,
            management_net_fee_cent=AUGUST_MANAGEMENT_CENT,
            store_name_snapshot="Cumulative Store",
            store_snapshot_status="LIVE_CAPTURED",
            created_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    publish_fixture(db_session, "settlement")
    august = _settlement(client, AUGUST)
    # The August period genuinely has a bill and its own fees.
    assert august["statement"]["statementId"] == "stmt-august"
    assert august["metrics"]["promotionNetFeeCent"] == AUGUST_PROMOTION_CENT
    assert august["metrics"]["managementNetFeeCent"] == AUGUST_MANAGEMENT_CENT

    september = _settlement(client, SEPTEMBER)

    # 2026-09 holds no statement, no lines and no fees of its own.
    assert db_session.scalar(
        select(func.count())
        .select_from(SettlementStatement)
        .where(
            SettlementStatement.store_id == STORE_ID,
            SettlementStatement.statement_month == SEPTEMBER,
        )
    ) == 0
    assert september["statement"] is None
    assert september["lines"] == []
    assert september["metrics"]["promotionNetFeeCent"] == 0
    assert september["metrics"]["managementNetFeeCent"] == 0
    assert september["metrics"]["salesAmountCent"] == 0
    assert september["metrics"]["verifiedAmountCent"] == 0

    # The cumulative is the formal window 2026-08 → 2026-09, i.e. exactly what
    # the settled August period contributes; it does not reset with the empty
    # period.
    assert september["computedCumulative"] == august["computedCumulative"]
    assert september["computedCumulative"] == {
        "promotionNetFeeCent": AUGUST_PROMOTION_CENT,
        "managementNetFeeCent": AUGUST_MANAGEMENT_CENT,
    }


def test_unpublished_legacy_cumulative_rows_are_not_presented(
    client: TestClient, db_session: Session
) -> None:
    """The fallback stays inside the published projection.

    Without an active published generation there is nothing sanctioned to show,
    so legacy aggregate rows must not become a cumulative figure.  This is the
    documented boundary of the empty-month fallback.
    """

    db_session.add(DimStore(store_id=STORE_ID, store_name="Cumulative Store", is_active=True))
    db_session.add(
        AggStoreRanking(
            period_type=2,
            period_key=AUGUST,
            month=AUGUST,
            store_id=STORE_ID,
            store_name="Cumulative Store",
            product_scope="all",
            product_type="all",
            promotion_net_fee_cent=AUGUST_PROMOTION_CENT,
            management_net_fee_cent=AUGUST_MANAGEMENT_CENT,
            net_settlement_reference_cent=AUGUST_PROMOTION_CENT - AUGUST_MANAGEMENT_CENT,
        )
    )
    db_session.commit()

    publish_fixture(db_session, "settlement")
    response = client.get(
        f"/api/v1/stores/{STORE_ID}/monthly-settlement",
        params={"month": SEPTEMBER, "productScope": "all", "productType": "all"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["metrics"]["promotionNetFeeCent"] == 0
    assert data["computedCumulative"] == {
        "promotionNetFeeCent": 0,
        "managementNetFeeCent": 0,
    }


def test_september_with_its_own_cumulative_snapshot_keeps_that_snapshot(
    client: TestClient, db_session: Session
) -> None:
    """A published 2026-09 snapshot wins over the August fallback.

    The fallback must only fill a gap: once the selected month carries its own
    materialized cumulative period, that period is the displayed figure even
    when it is zero (a refund can legitimately bring the window down).
    """

    _publish_august_only(db_session)
    db_session.add(
        SettlementProjectionPartitionManifest(
            generation_id=GENERATION,
            artifact="ranking",
            partition_key=f"cumulative:{SEPTEMBER}",
            source_kind="overlay",
            data_generation_id=GENERATION,
        )
    )
    db_session.add(
        SettlementRankingOverlay(
            generation_id=GENERATION,
            partition_key=f"cumulative:{SEPTEMBER}",
            period_type=2,
            period_key=SEPTEMBER,
            month=SEPTEMBER,
            store_id=STORE_ID,
            store_name="Cumulative Store",
            product_scope="all",
            product_type="all",
            promotion_net_fee_cent=0,
            management_net_fee_cent=0,
            net_settlement_reference_cent=0,
        )
    )
    db_session.commit()

    publish_fixture(db_session, "settlement")
    response = client.get(
        f"/api/v1/stores/{STORE_ID}/monthly-settlement",
        params={"month": SEPTEMBER, "productScope": "all", "productType": "all"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["computedCumulative"] == {
        "promotionNetFeeCent": 0,
        "managementNetFeeCent": 0,
    }
