"""Immutable, period-qualified store relationships used by monthly settlement.

The account roster certifies eligibility. This separate evidence certifies store
relationships, retaining the exact source and period independently of live maps.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cached_property
from typing import Any, Iterable

from sqlalchemy import and_, exists, false, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    AccountQualificationObservation,
    AccountQualificationSnapshot,
    AccountQualificationVersion,
    DimAwemeAccount,
    DimStore,
    DimStorePoiMapping,
    JobImpact,
    MonthlyStoreEvidenceSnapshot,
)

POLICY = "settlement-monthend-store-evidence-v1"
MAX_FACTS = 20_000
MAX_HISTORY_ROWS = 100_000


class StoreEvidenceError(RuntimeError):
    """Missing, conflicting, or unprovable historical store evidence."""


class MissingStoreEvidenceError(StoreEvidenceError):
    """No evidence version has been materialized for this qualification."""


def _digest(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _time(value: str | datetime) -> datetime:
    return _utc(datetime.fromisoformat(value) if isinstance(value, str) else value)


@dataclass(frozen=True)
class FrozenStoreEvidence:
    version_id: str
    content_sha256: str
    qualification_version_id: str
    records: tuple[dict[str, Any], ...]

    def account_store_ids(self, account_id: str) -> frozenset[str]:
        return self._store_ids("account", account_id)

    def poi_store_ids(self, poi_id: str) -> frozenset[str]:
        return self._store_ids("poi", poi_id)

    def _store_ids(self, kind: str, key: str) -> frozenset[str]:
        return self._store_index.get((kind, key), frozenset())

    @cached_property
    def _store_index(self) -> dict[tuple[str, str], frozenset[str]]:
        index: dict[tuple[str, str], set[str]] = {}
        for row in self.records:
            if row["kind"] == "alias":
                continue
            index.setdefault((row["kind"], row["key"]), set()).add(row["store_id"])
        return {key: frozenset(stores) for key, stores in index.items()}

    def alias_identities(self, name: str) -> frozenset[tuple[str, str]]:
        return self._alias_index.get(name, frozenset())

    @cached_property
    def _alias_index(self) -> dict[str, frozenset[tuple[str, str]]]:
        index: dict[str, set[tuple[str, str]]] = {}
        for row in self.records:
            if row["kind"] == "alias":
                index.setdefault(row["key"], set()).add((row["account_id"], row["douyin_id"]))
        return {key: frozenset(identities) for key, identities in index.items()}

    def as_context(self) -> dict[str, str]:
        return {"policy": POLICY, "version_id": self.version_id,
                "content_sha256": self.content_sha256,
                "qualification_version_id": self.qualification_version_id}


def _payload(version: AccountQualificationVersion, records: list[dict]) -> dict:
    return {"policy": POLICY, "qualification_version_id": version.version_id,
            "qualification_content_sha256": version.content_sha256,
            "business_month": version.business_month, "records": records}


def _read_snapshot(session: Session, row: MonthlyStoreEvidenceSnapshot,
                   version: AccountQualificationVersion) -> FrozenStoreEvidence:
    if row.qualification_version_id != version.version_id:
        raise StoreEvidenceError("store_evidence_qualification_conflict")
    if row.policy_version != POLICY or _digest(_payload(version, row.records_json)) != row.content_sha256:
        raise StoreEvidenceError("store_evidence_digest_mismatch")
    return FrozenStoreEvidence(row.version_id, row.content_sha256,
                               row.qualification_version_id, tuple(row.records_json))


def frozen_store_evidence(session: Session, *, qualification_version: AccountQualificationVersion,
                          version_id: str | None = None) -> FrozenStoreEvidence:
    """Read a previously materialized version without examining current maps."""
    cache = session.info.setdefault("monthly_store_evidence_cache", {})
    cache_key = (qualification_version.version_id, version_id)
    if version_id is not None and cache_key in cache:
        return cache[cache_key]
    query = select(MonthlyStoreEvidenceSnapshot.version_id).where(
        MonthlyStoreEvidenceSnapshot.qualification_version_id == qualification_version.version_id,
    )
    if version_id is not None:
        query = query.where(MonthlyStoreEvidenceSnapshot.version_id == version_id)
    query = query.order_by(MonthlyStoreEvidenceSnapshot.created_at.desc(),
                           MonthlyStoreEvidenceSnapshot.version_id.desc()).limit(1)
    selected_id = session.scalar(query)
    if selected_id is None:
        if version_id is not None:
            raise StoreEvidenceError("store_evidence_pinned_version_missing")
        raise MissingStoreEvidenceError("store_evidence_not_frozen")
    cache_key = (qualification_version.version_id, selected_id)
    if cache_key not in cache:
        row = session.get(MonthlyStoreEvidenceSnapshot, selected_id)
        cache[cache_key] = _read_snapshot(session, row, qualification_version)
    return cache[cache_key]


def store_evidence_condition(qualification_version: AccountQualificationVersion | str,
                             evidence_json_column: Any, *, pinned_version_id: str | None = None) -> Any:
    """Filter fees by the selected mapping version, preserving legacy admission."""
    qualification_id = (qualification_version if isinstance(qualification_version, str)
                        else qualification_version.version_id)
    query = select(MonthlyStoreEvidenceSnapshot).where(
        MonthlyStoreEvidenceSnapshot.qualification_version_id == qualification_id,
    )
    if pinned_version_id is not None:
        query = query.where(MonthlyStoreEvidenceSnapshot.version_id == pinned_version_id)
    latest_id = query.with_only_columns(MonthlyStoreEvidenceSnapshot.version_id).order_by(
        MonthlyStoreEvidenceSnapshot.created_at.desc(), MonthlyStoreEvidenceSnapshot.version_id.desc(),
    ).limit(1).scalar_subquery()
    latest_sha = query.with_only_columns(MonthlyStoreEvidenceSnapshot.content_sha256).order_by(
        MonthlyStoreEvidenceSnapshot.created_at.desc(), MonthlyStoreEvidenceSnapshot.version_id.desc(),
    ).limit(1).scalar_subquery()
    missing_legacy = ~exists(query) if pinned_version_id is None else false()
    return or_(missing_legacy, and_(
        evidence_json_column["policy"].as_string() == POLICY,
        evidence_json_column["qualification_version_id"].as_string() == qualification_id,
        evidence_json_column["version_id"].as_string() == latest_id,
        evidence_json_column["content_sha256"].as_string() == latest_sha,
    ))


def _validated_fact(fact: dict, *, version: AccountQualificationVersion,
                    accounts: set[str], pois: set[str], stores: set[str],
                    identities: set[tuple[str, str]]) -> dict:
    kind, key, store = fact.get("kind"), str(fact.get("key") or "").strip(), str(fact.get("store_id") or "").strip()
    if kind == "alias":
        identity = (str(fact.get("account_id") or ""), str(fact.get("douyin_id") or ""))
        if not key or identity not in identities:
            raise StoreEvidenceError("store_evidence_alias_identity_outside_frozen_roster")
    elif kind not in {"account", "poi"} or key not in (accounts if kind == "account" else pois):
        raise StoreEvidenceError("store_evidence_key_outside_frozen_roster")
    if kind != "alias" and store not in stores:
        raise StoreEvidenceError("store_evidence_store_missing")
    reference, sha = fact.get("source_reference"), fact.get("source_sha256")
    if not isinstance(reference, str) or not reference.strip() or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise StoreEvidenceError("store_evidence_source_proof_missing")
    try:
        observed = _time(fact["observed_at"])
        valid_from = date.fromisoformat(fact["valid_from"])
        valid_to = date.fromisoformat(fact["valid_to"]) if fact.get("valid_to") else None
    except (KeyError, TypeError, ValueError):
        raise StoreEvidenceError("store_evidence_period_proof_missing") from None
    last_day = date.fromisoformat(version.business_month + "-01").replace(day=28)
    last_day = (last_day + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if observed >= _utc(version.cutoff_at) or valid_from > last_day or (valid_to and valid_to < last_day):
        raise StoreEvidenceError("store_evidence_outside_business_period")
    identity_fields = ({"account_id": identity[0], "douyin_id": identity[1]}
                       if kind == "alias" else {"store_id": store})
    return {"kind": kind, "key": key, **identity_fields,
            "source_reference": reference.strip(), "source_sha256": sha,
            "observed_at": observed.isoformat(), "valid_from": valid_from.isoformat(),
            "valid_to": valid_to.isoformat() if valid_to else None}


def _source_fact(kind: str, key: str, store_id: str, *, source: str,
                  observed_at: datetime, values: dict,
                  valid_from: date | None = None, valid_to: date | None = None) -> dict:
    observed = _utc(observed_at)
    return {"kind": kind, "key": key, "store_id": store_id,
            "source_reference": source, "source_sha256": _digest(values),
            "observed_at": observed.isoformat(),
            "valid_from": (valid_from or observed.date()).isoformat(),
            "valid_to": valid_to.isoformat() if valid_to else None}


def preview_store_evidence(session: Session, *, qualification_version: AccountQualificationVersion,
                            facts: Iterable[dict] = ()) -> dict:
    """Build bounded evidence using historical assertions, without writing rows."""
    snapshot = session.get(AccountQualificationSnapshot, qualification_version.content_sha256)
    if snapshot is None:
        raise StoreEvidenceError("qualification_snapshot_missing")
    if _digest({"policy": qualification_version.policy_version, "records": snapshot.records_json}) != qualification_version.content_sha256:
        raise StoreEvidenceError("qualification_source_digest_mismatch")
    records = snapshot.records_json
    accounts = {str(row["account_id"]) for row in records if row.get("account_id")}
    identities = {(str(row["account_id"]), str(row["douyin_id"]))
                  for row in records if row.get("account_id") and row.get("douyin_id")}
    pois = {str(row["poi_id"]) for row in records if row.get("poi_id") not in (None, "", "0", "-1")}
    cutoff = _utc(qualification_version.cutoff_at)
    if session.get(AccountQualificationVersion, qualification_version.version_id) is None:
        raise StoreEvidenceError("qualification_version_missing")
    # Store creation dates bound existence. A matching identifier by itself is
    # never an account-to-store relationship.
    stores = set(session.scalars(select(DimStore.store_id).where(DimStore.created_at < cutoff)))
    provided = list(facts)
    candidates = []
    for row in records:
        if not row.get("store_id"):
            continue
        observation = session.get(AccountQualificationObservation, qualification_version.observation_id)
        if observation is None or observation.ended_at is None:
            raise StoreEvidenceError("qualification_observation_missing")
        for kind, key in (("account", row.get("account_id")), ("poi", row.get("poi_id"))):
            if key and (kind != "poi" or str(key) in pois):
                candidates.append(_source_fact(kind, str(key), str(row["store_id"]),
                    source="account_qualification_snapshot/" + qualification_version.content_sha256,
                    observed_at=observation.ended_at, values=row))
    account_rows = session.scalars(select(DimAwemeAccount).where(
        DimAwemeAccount.account_id.in_(accounts), DimAwemeAccount.updated_at < cutoff,
        DimAwemeAccount.store_id.is_not(None), DimAwemeAccount.valid_from.is_not(None),
    ))
    for row in account_rows:
        candidates.append(_source_fact("account", row.account_id, row.store_id,
            source="dim_aweme_accounts/" + row.account_id, observed_at=row.updated_at,
            valid_from=row.valid_from, valid_to=row.valid_to,
            values={"account_id": row.account_id, "store_id": row.store_id,
                    "valid_from": str(row.valid_from), "valid_to": str(row.valid_to),
                    "updated_at": _utc(row.updated_at).isoformat()}))
    mappings = session.scalars(select(DimStorePoiMapping).where(
        DimStorePoiMapping.poi_id.in_(pois), DimStorePoiMapping.source_observed_at < cutoff,
        DimStorePoiMapping.mapping_source.is_not(None),
    ))
    dated_poi_facts = []
    for row in mappings:
        dated_poi_facts.append(_source_fact("poi", row.poi_id, row.store_id,
            source="dim_store_poi_mappings/" + str(row.source_run_id or row.observation_key or ""),
            observed_at=row.source_observed_at,
            values={"poi_id": row.poi_id, "store_id": row.store_id,
                    "mapping_source": row.mapping_source, "source_run_id": row.source_run_id,
                    "observation_key": row.observation_key}))
    # The audit journal can recover a historical relationship after live maps
    # have moved. Only the last recorded state known before cutoff is selected.
    history = session.scalars(select(JobImpact).where(
        JobImpact.entity_type == "store_poi_mapping", JobImpact.entity_key.in_(pois),
        JobImpact.created_at < cutoff,
    ).order_by(JobImpact.created_at.desc(), JobImpact.id.desc()).limit(MAX_HISTORY_ROWS + 1)).all()
    if len(history) > MAX_HISTORY_ROWS:
        raise StoreEvidenceError("store_evidence_history_limit")
    seen_pois = set()
    for row in history:
        if row.entity_key in seen_pois:
            continue
        seen_pois.add(row.entity_key)
        values = row.new_values_json or {}
        if values.get("store_id"):
            dated_poi_facts.append(_source_fact("poi", row.entity_key, str(values["store_id"]),
                source="job_impacts/" + row.impact_key, observed_at=row.created_at, values=values))
    latest_poi_time: dict[str, datetime] = {}
    for candidate in dated_poi_facts:
        key, observed = candidate["key"], _time(candidate["observed_at"])
        latest_poi_time[key] = max(latest_poi_time.get(key, observed), observed)
    candidates.extend(row for row in dated_poi_facts
                      if _time(row["observed_at"]) == latest_poi_time[row["key"]])
    if len(candidates) + len(provided) > MAX_FACTS:
        raise StoreEvidenceError("store_evidence_fact_limit")
    validated = [_validated_fact(row, version=qualification_version, accounts=accounts,
                                pois=pois, stores=stores, identities=identities) for row in provided]
    for candidate in candidates:
        try:
            validated.append(_validated_fact(candidate, version=qualification_version,
                                            accounts=accounts, pois=pois, stores=stores, identities=identities))
        except StoreEvidenceError as exc:
            if str(exc) not in {"store_evidence_store_missing", "store_evidence_outside_business_period"}:
                raise
    unique = {_digest(row): row for row in validated}
    payload = _payload(qualification_version, [unique[key] for key in sorted(unique)])
    return {**payload, "content_sha256": _digest(payload)}


def freeze_store_evidence(session: Session, *, qualification_version: AccountQualificationVersion,
                           facts: Iterable[dict] = (), expected_content_sha256: str | None = None) -> FrozenStoreEvidence:
    """Append a verified input version. Existing evidence is never updated."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7462180072)"))
    preview = preview_store_evidence(session, qualification_version=qualification_version, facts=facts)
    content = preview["content_sha256"]
    if expected_content_sha256 is not None and content != expected_content_sha256:
        raise StoreEvidenceError("store_evidence_preview_changed")
    version_id = "store-evidence-" + content
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    session.execute(insert(MonthlyStoreEvidenceSnapshot).values(
        version_id=version_id, qualification_version_id=qualification_version.version_id,
        content_sha256=content, policy_version=POLICY, records_json=preview["records"],
        created_at=datetime.now(UTC),
    ).on_conflict_do_nothing(index_elements=["version_id"]))
    session.flush()
    session.info.pop("monthly_store_evidence_cache", None)
    return frozen_store_evidence(session, qualification_version=qualification_version, version_id=version_id)
