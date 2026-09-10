"""A late POI mapping must not replace an already confirmed promotion source."""

from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from apps.api.dy_api.models import (
    DimStorePoiMapping, SettlementFeeResult, SettlementFeeResultCurrent,
    SettlementStatement, SettlementStatementConfirmation, SettlementStatementEntry,
    SkuFeeRule,
)
from apps.worker.collectors.verify_records import collect_shop_pois
from apps.worker.settlement import settle_coupon_local
from tests.test_data_settlement_incremental import _seed_local_coupon
from tests.test_shop_poi_pagination import PageClient


def _snapshot(row):
    return {column.key: getattr(row, column.key) for column in row.__mapper__.column_attrs}


@pytest.mark.parametrize("confirmed", [False, True])
def test_late_mapping_adds_management_without_changing_promotion(db_session, confirmed):
    coupon = _seed_local_coupon(db_session)
    db_session.scalar(select(SkuFeeRule)).management_service_fee_rate = Decimal("0.1")
    db_session.execute(delete(DimStorePoiMapping))
    db_session.flush()
    settle_coupon_local(db_session, coupon, "before-mapping")
    promotion = db_session.scalar(select(SettlementFeeResult))
    assert promotion.fee_direction == 1
    assert promotion.fee_amount_cent == 1000
    bill = SettlementStatement(
        statement_id="protected-promotion", store_id="store-sale", statement_month="2026-08",
        statement_status=2, promotion_original_fee_cent=1000, promotion_net_fee_cent=1000,
    )
    db_session.add(bill)
    entry = SettlementStatementEntry(
        statement_entry_id="promotion-entry", statement_id=bill.statement_id,
        statement_line_id="promotion-line", source_type=1,
        source_record_id=promotion.fee_result_id, original_fee_result_id=promotion.fee_result_id,
        coupon_id=coupon.coupon_id, order_id=coupon.order_id, fee_direction=1,
        original_business_month="2026-08", statement_posting_month="2026-08",
        base_amount_cent=10000, fee_amount_cent=1000, rule_version="fee-v1",
    )
    db_session.add(entry)
    if confirmed:
        db_session.add(SettlementStatementConfirmation(
            confirmation_id="promotion-confirmation", statement_id=bill.statement_id,
            fee_direction=1, confirmation_status=1, confirmed_amount_cent=1000,
            confirmed_by="synthetic-user",
        ))
    db_session.commit()
    promotion_before = _snapshot(promotion)
    bill_before = _snapshot(bill)
    entry_before = _snapshot(entry)
    confirmations_before = [_snapshot(row) for row in db_session.scalars(select(SettlementStatementConfirmation))]

    collect_shop_pois(db_session, PageClient([{"total": 1, "pois": [{
        "poi": {"poi_id": "poi-verify", "poi_name": "Verify"},
        "account": {"poi_account": {"account_id": "store-verify", "account_name": "Verify"}},
    }]}]), source_run_id="late-mapping")
    result = settle_coupon_local(db_session, coupon, "late-mapping")
    db_session.commit()
    assert result["result_count"] == 1
    assert result["adjustment_count"] == 0
    assert result["affected_months"] == ["2026-08"]
    heads = list(db_session.scalars(select(SettlementFeeResult).join(
        SettlementFeeResultCurrent,
        SettlementFeeResultCurrent.fee_result_id == SettlementFeeResult.fee_result_id,
    ).order_by(SettlementFeeResult.fee_direction)))
    assert [(row.fee_direction, row.fee_amount_cent) for row in heads] == [(1, 1000), (2, 1000)]
    assert _snapshot(heads[0]) == promotion_before
    assert _snapshot(bill) == bill_before
    assert _snapshot(entry) == entry_before
    assert entry.source_record_id == promotion.fee_result_id
    confirmations = list(db_session.scalars(select(SettlementStatementConfirmation)))
    assert [_snapshot(row) for row in confirmations] == confirmations_before
    assert len(confirmations) == int(confirmed)
    if confirmed:
        assert confirmations[0].confirmed_amount_cent == 1000
    replay = settle_coupon_local(db_session, coupon, "late-mapping-replay")
    assert replay["result_count"] == replay["adjustment_count"] == 0
