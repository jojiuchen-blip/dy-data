"""Bounded, exact account/POI resolution and read-only clue query contracts."""
from __future__ import annotations

import re
import unicodedata
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimAwemeAccount, DimStore, DimStorePoiMapping
from apps.api.dy_api.clue_phone_filters import validate_phone_filter
from fastapi import HTTPException

MAX_STORE_SELECTION = 1000
MAX_IDENTIFIER_LENGTH = 128
MAX_RAW_INPUT_LENGTH = 128000
Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=MAX_IDENTIFIER_LENGTH)]


class ClueStoreResolveRequest(BaseModel):
    """Accept pasted text without numeric coercion or silent truncation."""

    model_config = ConfigDict(extra="forbid")
    raw_input: str = Field(strict=True, max_length=MAX_RAW_INPUT_LENGTH)


class ClueQueryFilters(BaseModel):
    """Public filters; authorization scope is never accepted from the caller."""

    model_config = ConfigDict(extra="forbid")
    assigned_store_id: str | None = Field(default=None, strict=True, max_length=MAX_IDENTIFIER_LENGTH)
    assigned_store_ids: list[Identifier] | None = Field(default=None, max_length=MAX_STORE_SELECTION)
    assigned_date_start: str | None = Field(default=None, max_length=32)
    assigned_date_end: str | None = Field(default=None, max_length=32)
    lead_status: str | None = Field(default=None, max_length=64)
    store_display_status: str | None = Field(default=None, max_length=64)
    round_status: str | None = Field(default=None, max_length=64)
    product_type: str | None = Field(default=None, max_length=128)
    org_level: str = Field(default="all", max_length=32)
    org_key: str = Field(default="", max_length=2048)
    province: str | None = Field(default=None, max_length=128)
    city: str | None = Field(default=None, max_length=128)
    verification_status: str | None = Field(default=None, max_length=64)
    q: str | None = Field(default=None, max_length=256)
    phone: str | None = None

    @field_validator("phone", mode="before")
    @classmethod
    def exact_phone(cls, value):
        try:
            return validate_phone_filter(value)
        except ValueError as exc:
            # Pydantic's standard errors include the rejected value; this
            # sensitive input must not be reflected in responses or logs.
            raise HTTPException(status_code=422, detail={"code": "CLUE_PHONE_FILTER_INVALID", "message": str(exc)}) from None

    @field_validator("assigned_store_ids")
    @classmethod
    def unique_store_ids(cls, value: list[str] | None) -> list[str] | None:
        """Keep explicit [] distinct from an absent filter."""
        return list(dict.fromkeys(value)) if value is not None else None


class ClueQueryRequest(BaseModel):
    """Carry large selections in a JSON body rather than the request URL."""

    model_config = ConfigDict(extra="forbid")
    filters: ClueQueryFilters = Field(default_factory=ClueQueryFilters)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ClueExportQueryRequest(BaseModel):
    """Export the same selection without pagination."""

    model_config = ConfigDict(extra="forbid")
    filters: ClueQueryFilters = Field(default_factory=ClueQueryFilters)


def parse_store_identifiers(raw_input: str) -> tuple[list[str], int]:
    """Normalize width, split documented delimiters and retain exact string IDs."""
    if len(raw_input) > MAX_RAW_INPUT_LENGTH:
        raise ValueError("粘贴内容最多 128000 个字符，请分批筛选")
    tokens = [token for token in re.split(r"[\s;/]+", unicodedata.normalize("NFKC", raw_input)) if token]
    if any(len(token) > MAX_IDENTIFIER_LENGTH for token in tokens):
        raise ValueError("单个账户或 POI ID 最多 128 个字符")
    identifiers = list(dict.fromkeys(tokens))
    if len(identifiers) > MAX_STORE_SELECTION:
        raise ValueError("每次最多筛选 1000 个不同 ID，请分批筛选")
    return identifiers, len(tokens)


def resolve_store_identifiers(
    session: Session, raw_input: str, scope_store_ids: tuple[str, ...] | None,
) -> dict:
    """Resolve current account/POI namespaces, returning only authorized matches.

    DimStore IDs are canonical query targets, not an additional input namespace.
    Query in bounded batches; never scan historical bindings or the whole catalog.
    """
    identifiers, input_count = parse_store_identifiers(raw_input)
    candidates: dict[str, dict[str, set[str]]] = {identifier: {} for identifier in identifiers}
    names: dict[str, str] = {}
    authorized = None if scope_store_ids is None else set(scope_store_ids)
    for offset in range(0, len(identifiers), 400):
        batch = identifiers[offset:offset + 400]
        for model, column, namespace in (
            (DimAwemeAccount, DimAwemeAccount.account_id, "account"),
            (DimStorePoiMapping, DimStorePoiMapping.poi_id, "poi"),
        ):
            statement = select(column, DimStore.store_id, DimStore.store_name).join(
                DimStore, model.store_id == DimStore.store_id,
            ).where(column.in_(batch))
            for identifier, store_id, store_name in session.execute(statement):
                if authorized is not None and store_id not in authorized:
                    continue
                candidates[identifier].setdefault(store_id, set()).add(namespace)
                names[store_id] = store_name
    if len(names) > MAX_STORE_SELECTION:
        raise ValueError("匹配门店超过 1000 家，请分批筛选；本次未应用")
    stores = [
        {"store_id": store_id, "store_name": names[store_id], "matches": [
            {"identifier": identifier, "sources": sorted(candidates[identifier][store_id])}
            for identifier in identifiers if store_id in candidates[identifier]
        ]}
        for store_id in sorted(names)
    ]
    unmatched = [identifier for identifier in identifiers if not candidates[identifier]]
    return {
        "stores": stores, "input_count": input_count, "unique_count": len(identifiers),
        "duplicate_count": input_count - len(identifiers),
        "matched_identifier_count": len(identifiers) - len(unmatched),
        "matched_store_count": len(stores), "unmatched_identifiers": unmatched,
    }
