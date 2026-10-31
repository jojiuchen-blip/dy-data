"""Commission SKU classification preserves eligibility and historical money."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from apps.api.dy_api.commission_classification import participation_rules
from apps.api.dy_api.models import DimSkuProductRule, SkuFeeRule
from scripts.convert_jingcheng_product_types import ConversionError, convert_product_types


PAST = datetime(2000, 8, 1, tzinfo=timezone.utc)
CONTEXT = {"actor": "ops:classification-test", "change_reason": "DYDATA-104 Oct30",
    "idempotency_key": "commission-classification-test", "participating_only": True}


def _rule(session, sku_id, *, suffix="positive", effective=PAST, rate="0.1", status=1,
          product_type="268保养"):
    identity = f"{sku_id}-{suffix}"
    row = SkuFeeRule(rule_version=identity, idempotency_key_hash=identity,
        request_payload_sha256=identity, sku_id=sku_id, product_scope_snapshot="旧范围",
        product_type_snapshot=product_type, promotion_service_fee_rate=Decimal(rate),
        management_service_fee_rate=Decimal("0"), effective_date=effective.date(),
        effective_at=effective, rule_status=status, created_by="synthetic",
        change_reason="synthetic", published_at=PAST)
    session.add(row)
    return row


def _seed(session):
    for sku_id, scope, product_type in (
        ("old-scope", "精诚养车", "268保养"), ("other-scope", "本品", "unknown"),
        ("official", "精诚养车", "售后官方"), ("official-snapshot", "其他", "外观清洁"),
        ("past-disabled", "其他", "漆面"), ("zero", "其他", "不分佣"),
        ("future", "其他", "未来商品"), ("scope-without-rule", "精诚养车", "未核实"),
        ("other-scope-suffix", "本品", "不能用近似ID"),
    ):
        session.add(DimSkuProductRule(sku_id=sku_id, product_id="shared-product",
            sku_name="精诚养车名称不是资格", product_scope=scope, product_type=product_type,
            is_active_product=False, commission_rate=Decimal("0.1234")))
    for sku_id in ("old-scope", "other-scope", "official", "past-disabled", "missing-catalog"):
        _rule(session, sku_id)
    _rule(session, "official-snapshot", product_type="售后官方")
    _rule(session, "past-disabled", suffix="disabled", effective=datetime(2001, 1, 1, tzinfo=timezone.utc), status=2)
    _rule(session, "zero", rate="0")
    _rule(session, "future", effective=datetime(2099, 1, 1, tzinfo=timezone.utc))
    session.commit()


def test_participating_selection_and_official_preservation_are_exact(db_session):
    _seed(db_session)
    rules_before = [(row.rule_version, row.product_type_snapshot, row.promotion_service_fee_rate,
        row.rule_status) for row in db_session.scalars(select(SkuFeeRule).order_by(SkuFeeRule.rule_version))]
    db_session.rollback()
    preview = convert_product_types(db_session, **CONTEXT)
    assert preview["applied"] is False
    assert preview["target_count"] == 5
    assert preview["changed_count"] == 4
    assert preview["missing_catalog_sku_ids"] == ["missing-catalog"]
    assert {row["sku_id"] for row in preview["unproven_skus"]} == {
        "zero", "future", "scope-without-rule", "other-scope-suffix"}
    expected = {"old-scope": "精诚养车", "other-scope": "精诚养车", "official": "售后官方",
        "official-snapshot": "售后官方", "past-disabled": "精诚养车"}
    assert {row["sku_id"]: row["product_type_after"] for row in preview["diff"]} == expected
    assert all(row["rule_version"] and row["effective_date"] for row in preview["participation_rules"])
    applied = convert_product_types(db_session, **CONTEXT, apply=True, preview_hash=preview["preview_hash"])
    assert applied["applied"] and not applied["rebuild_queued"]
    rows = {row.sku_id: row for row in db_session.scalars(select(DimSkuProductRule))}
    for sku_id, value in expected.items():
        assert rows[sku_id].product_type == value
        assert not rows[sku_id].is_active_product
        assert rows[sku_id].commission_rate == Decimal("0.1234")
    assert rows["scope-without-rule"].product_type == "未核实"
    assert rows["other-scope-suffix"].product_type == "不能用近似ID"
    assert rows["official"].product_scope == "精诚养车"
    assert [(row.rule_version, row.product_type_snapshot, row.promotion_service_fee_rate,
        row.rule_status) for row in db_session.scalars(select(SkuFeeRule).order_by(SkuFeeRule.rule_version))] == rules_before
    db_session.rollback()
    assert convert_product_types(db_session, **CONTEXT, apply=True,
        preview_hash=preview["preview_hash"])["replayed"]


@pytest.mark.parametrize("mutation", ["rule-rate", "rule-status", "new-rule", "catalog-arrives"])
def test_participation_evidence_is_inside_the_apply_fence(db_session, mutation):
    _seed(db_session)
    preview = convert_product_types(db_session, **CONTEXT)
    if mutation == "new-rule":
        _rule(db_session, "other-scope-suffix")
    elif mutation == "catalog-arrives":
        db_session.add(DimSkuProductRule(sku_id="missing-catalog", product_type="新档案", product_scope="其他"))
    else:
        rule = db_session.scalar(select(SkuFeeRule).where(SkuFeeRule.sku_id == "other-scope"))
        if mutation == "rule-rate":
            rule.promotion_service_fee_rate = Decimal("0.2")
        else:
            rule.rule_status = 2
    db_session.commit()
    with pytest.raises(ConversionError, match="stale"):
        convert_product_types(db_session, **CONTEXT, apply=True, preview_hash=preview["preview_hash"])
    assert db_session.scalar(select(DimSkuProductRule.product_type).where(
        DimSkuProductRule.sku_id == "old-scope")) == "268保养"


def test_product_sync_keeps_participant_types_across_scopes_and_distinct_skus(db_session):
    from apps.worker.product_sync import execute_product_sync, NormalizedProductSyncAdapter
    from test_worker_product_sync import FixturePages, _item, _queue

    _seed(db_session)
    for number in range(2):
        job_id = f"commission-types-sync-{number}"
        _queue(db_session, job_id=job_id)
        response = execute_product_sync(db_session, job_id=job_id,
            adapter=NormalizedProductSyncAdapter(FixturePages([{"items": [
                _item(sku_id=sku_id, sku_name="平台新名称") for sku_id in
                ("other-scope", "official", "official-snapshot", "past-disabled", "zero", "other-scope-suffix")],
                "hasMore": False, "nextCursor": None}])) )
        assert response.status == "SUCCESS"
    rows = {row.sku_id: row for row in db_session.scalars(select(DimSkuProductRule))}
    assert rows["other-scope"].product_type == rows["past-disabled"].product_type == "精诚养车"
    assert rows["official"].product_type == rows["official-snapshot"].product_type == "售后官方"
    assert rows["zero"].product_type == "不分佣"
    assert rows["other-scope-suffix"].product_type == "不能用近似ID"
    assert set(participation_rules(db_session, ("other-scope", "other-scope-suffix"))) == {"other-scope"}
