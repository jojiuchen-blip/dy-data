"""Immutable input contract for an explicitly reviewed, bounded POI repair.

Parsing a manifest does not authorize writes or prove its database fingerprints.
The coordinator must compare them under database locks before every commit.
No production IDs, credentials or inferred scope are embedded here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"^\S+$")]
Fingerprint = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
PositiveInteger = Annotated[int, Field(strict=True, gt=0)]
NonnegativeCent = Annotated[int, Field(strict=True, ge=0)]


class PoiRepairMapping(BaseModel):
    """One missing POI mapping and its independently verified account store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    poi_id: Identifier
    store_id: Identifier


class PoiRepairCoupon(BaseModel):
    """One valid redeemed coupon whose management result is missing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    coupon_id: Identifier
    sku_id: Identifier
    poi_id: Identifier
    qualifying_verify_id: Identifier
    promotion_fee_result_id: Identifier
    expected_management_cent: NonnegativeCent


class PoiSettlementRepairManifest(BaseModel):
    """Strict, single-month input for a controlled management-fee repair.

    Collection order is immaterial to the fingerprint. Duplicate identities,
    unused mappings, unapproved SKUs and inconsistent totals fail closed.
    The SKU allowlist may include authorized SKUs without affected coupons.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["poi-settlement-repair-v1"]
    base_generation_id: Identifier
    allowed_month: Annotated[str, StringConstraints(strict=True, pattern=r"^\d{4}-\d{2}$")]
    sku_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    source_fingerprint: Fingerprint
    financial_fingerprint: Fingerprint
    expected_coupon_count: PositiveInteger
    expected_management_cent: NonnegativeCent
    mappings: Annotated[tuple[PoiRepairMapping, ...], Field(min_length=1)]
    coupons: Annotated[tuple[PoiRepairCoupon, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Require explicit, consistent identities and exact integer totals."""
        date.fromisoformat(f"{self.allowed_month}-01")
        for values in (
            self.sku_ids,
            tuple(row.poi_id for row in self.mappings),
            tuple(row.coupon_id for row in self.coupons),
            tuple(row.promotion_fee_result_id for row in self.coupons),
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate repair identity")
        if {row.poi_id for row in self.mappings} != {row.poi_id for row in self.coupons}:
            raise ValueError("repair mapping set must match coupon POIs exactly")
        if not {row.sku_id for row in self.coupons}.issubset(self.sku_ids):
            raise ValueError("coupon SKU is outside the explicit allowlist")
        if len(self.coupons) != self.expected_coupon_count:
            raise ValueError("repair coupon count does not match")
        if sum(row.expected_management_cent for row in self.coupons) != self.expected_management_cent:
            raise ValueError("repair management fee total does not match")
        return self

    def fingerprint(self) -> str:
        """Return an order-independent SHA256 over every frozen input field."""
        payload = self.model_dump(mode="json")
        payload["sku_ids"] = sorted(payload["sku_ids"])
        payload["mappings"] = sorted(payload["mappings"], key=lambda row: row["poi_id"])
        payload["coupons"] = sorted(payload["coupons"], key=lambda row: row["coupon_id"])
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
