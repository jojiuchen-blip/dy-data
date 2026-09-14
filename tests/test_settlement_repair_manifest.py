"""Strict, synthetic inputs for the bounded POI repair's immutable manifest."""

from copy import deepcopy
from importlib import import_module

import pytest


def _payload():
    return {
        "protocol": "poi-settlement-repair-v1",
        "base_generation_id": "published-base",
        "allowed_month": "2026-08",
        "sku_ids": ["sku-a", "sku-b"],
        "source_fingerprint": "a" * 64,
        "financial_fingerprint": "b" * 64,
        "expected_coupon_count": 2,
        "expected_management_cent": 300,
        "mappings": [{"poi_id": "poi-a", "store_id": "store-a"}],
        "coupons": [
            {"coupon_id": "coupon-a", "sku_id": "sku-a", "poi_id": "poi-a",
             "qualifying_verify_id": "verify-a", "promotion_fee_result_id": "fee-a",
             "expected_management_cent": 100},
            {"coupon_id": "coupon-b", "sku_id": "sku-b", "poi_id": "poi-a",
             "qualifying_verify_id": "verify-b", "promotion_fee_result_id": "fee-b",
             "expected_management_cent": 200},
        ],
    }


def _manifest_class():
    # An explicit assertion reports a missing implementation as a test failure.
    from importlib.util import find_spec

    path = "apps.worker.settlement_repair_manifest"
    assert find_spec(path) is not None, "bounded repair manifest is not implemented"
    return import_module(path).PoiSettlementRepairManifest


def test_manifest_hash_is_order_independent_and_input_is_not_mutable():
    model = _manifest_class()
    payload = _payload()
    original = model.model_validate(payload)
    permuted = deepcopy(payload)
    permuted["sku_ids"].reverse()
    permuted["coupons"].reverse()
    assert original.fingerprint() == model.model_validate(permuted).fingerprint()
    payload["coupons"][0]["expected_management_cent"] = 999
    assert original.coupons[0].expected_management_cent == 100
    with pytest.raises(ValueError):
        original.coupons[0].expected_management_cent = 999


@pytest.mark.parametrize("change", [
    lambda p: p.update(protocol="unknown"),
    lambda p: p.update(allowed_month="2026-13"),
    lambda p: p.update(allowed_month="2026-8"),
    lambda p: p.update(base_generation_id=" "),
    lambda p: p.update(source_fingerprint="not-a-hash"),
    lambda p: p.update(financial_fingerprint=""),
    lambda p: p.update(expected_coupon_count=3),
    lambda p: p.update(expected_management_cent=301),
    lambda p: p.update(expected_management_cent="300"),
    lambda p: p.update(expected_coupon_count=True),
    lambda p: p.update(sku_ids=[]),
    lambda p: p["sku_ids"].append("sku-a"),
    lambda p: p["coupons"][0].update(sku_id="unapproved-sku"),
    lambda p: p["coupons"][0].update(poi_id="unmapped-poi"),
    lambda p: p["coupons"][0].update(expected_management_cent=-1),
    lambda p: p["coupons"][0].update(expected_management_cent=100.0),
    lambda p: p["coupons"][0].update(expected_management_cent=True),
    lambda p: p["coupons"][0].update(qualifying_verify_id=""),
    lambda p: p["coupons"][0].update(coupon_id="coupon-b"),
    lambda p: p["coupons"][0].update(promotion_fee_result_id="fee-b"),
    lambda p: p["mappings"].append({"poi_id": "unused", "store_id": "store-a"}),
    lambda p: p["mappings"].append({"poi_id": "poi-a", "store_id": "other"}),
    lambda p: p["mappings"][0].update(store_id=""),
    lambda p: p.update(coupons=[]),
    lambda p: p.update(force=True),
    lambda p: p["coupons"][0].update(force=True),
])
def test_manifest_rejects_ambiguous_or_expanded_inputs(change):
    model = _manifest_class()
    payload = _payload()
    change(payload)
    with pytest.raises(ValueError):
        model.model_validate(payload)


@pytest.mark.parametrize("field", ["source_fingerprint", "financial_fingerprint", "base_generation_id"])
def test_manifest_hash_binds_the_frozen_source_and_base(field):
    model = _manifest_class()
    payload = _payload()
    first = model.model_validate(payload).fingerprint()
    payload[field] = "c" * 64
    assert model.model_validate(payload).fingerprint() != first
