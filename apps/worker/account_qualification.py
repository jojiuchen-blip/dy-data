"""Frozen monthly settlement sales attribution and account eligibility.

The engineering contract uses the last complete collection on the Shanghai
month-end day, completed strictly before cutoff and within its final two hours.
It does not claim that the observation happened exactly at midnight.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    AccountQualificationObservation as Observation,
    AccountQualificationSnapshot as Snapshot,
    AccountQualificationVersion as Version,
    DimStore,
    DimStorePoiMapping,
)
from apps.worker.collectors.normalizers import get_path, text as source_text

POLICY_VERSION = "settlement-monthend-cn-v2"
FIRST_MONTH = "2026-10"
SALE_ACCOUNT_MATCH_POLICY = "settlement-monthend-sale-name-v1"
SALE_NAME_PATHS = (
    "owner_account_name", "sale_info.transfer_nickName", "sale_info.transfer_nickname",
    "order_sale_info.transfer_nickName", "order_sale_info.transfer_nickname",
)
ROSTER_NAME_FIELDS = ("抖音昵称", "抖音号昵称", "nickname", "douyin_nickname")
SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_AGE = timedelta(hours=2)
MAX_AUTOMATIC_MONTH_ATTEMPTS = 8
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
ELIGIBLE_TYPES = {"子机构门店号", "子机构区域号"}


class AccountQualificationError(RuntimeError):
    """Missing, partial or unprovable month-end evidence."""

    def __init__(self, reason: str, *, candidate_store_ids: frozenset[str] | None = None):
        super().__init__(reason)
        self.candidate_store_ids = candidate_store_ids


@dataclass(frozen=True)
class FrozenSaleMatch:
    account_id: str
    douyin_id: str
    store_id: str
    poi_ids: tuple[str, ...]
    account_name: str
    source_field: str
    qualification_version_id: str
    content_sha256: str
    store_evidence: dict | None = None
    name_match_source: str | None = None
    matched_roster_names: tuple[str, ...] = ()

    def as_context(self) -> dict:
        context = {
            "policy": SALE_ACCOUNT_MATCH_POLICY,
            "qualification_version_id": self.qualification_version_id,
            "content_sha256": self.content_sha256,
            "source_field": self.source_field,
            "account_name": self.account_name,
            "account_id": self.account_id,
            "douyin_id": self.douyin_id,
            "poi_ids": list(self.poi_ids),
            "store_id": self.store_id,
        }
        if self.store_evidence is not None:
            context["store_evidence"] = self.store_evidence
        if self.name_match_source is not None:
            context["name_match_source"] = self.name_match_source
            context["matched_roster_names"] = list(self.matched_roster_names)
        return context


@dataclass(frozen=True)
class CaptureAdmission:
    observation_id: str | None = None
    blocked_reason: str | None = None


class BindingRecords(list):
    """List-compatible collector result with batch-level completeness proof."""

    def __init__(self, values=(), *, proof=None, source_type="unknown"):
        super().__init__(values)
        self.proof = proof or {}
        self.source_type = source_type


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def month_bounds(month: str) -> tuple[datetime, datetime]:
    start = date.fromisoformat(month + "-01")
    following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    cutoff = datetime.combine(following, time.min, SHANGHAI).astimezone(UTC)
    return cutoff - timedelta(days=1), cutoff


def _insert_once(session: Session, model, values: dict, key: str) -> None:
    dialect = session.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    session.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=[key]))


def start_observation(session: Session, *, source_run_id: str, started_at: datetime | None = None, proof: dict | None = None) -> str:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7462180066)"))
    identity = "account-observation-" + uuid4().hex
    session.add(Observation(observation_id=identity, source_run_id=source_run_id,
                            source_type="backend_export", started_at=utc(started_at or datetime.now(UTC)),
                            state="running", complete=False, proof_json=dict(proof or {})))
    session.flush()
    return identity


def in_automatic_capture_window(at: datetime) -> bool:
    current = utc(at)
    month = current.astimezone(SHANGHAI).strftime("%Y-%m")
    if month < FIRST_MONTH:
        return False
    _, cutoff = month_bounds(month)
    return cutoff - MAX_AGE <= current < cutoff


def begin_automatic_observation(session: Session, *, source_run_id: str, started_at: datetime) -> CaptureAdmission:
    """Bound automatic permanent evidence to the useful two-hour window.

    Four half-hour slots plus four aggregate retries may capture at most eight
    distinct snapshots/month. One durable budget marker blocks further exports
    and month close; repeated exhausted retries never create more rows.
    """
    if not in_automatic_capture_window(started_at):
        return CaptureAdmission()
    current = utc(started_at)
    month = current.astimezone(SHANGHAI).strftime("%Y-%m")
    _, cutoff = month_bounds(month)
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7462180066)"))
    marker_id = "account-observation-budget-" + month
    exhausted = session.get(Observation, marker_id)
    count = session.scalar(select(func.count()).select_from(Observation).where(
        Observation.started_at >= cutoff - MAX_AGE, Observation.started_at < cutoff,
        Observation.proof_json["capture_mode"].as_string() == "automatic",
    )) or 0
    if exhausted is not None or count >= MAX_AUTOMATIC_MONTH_ATTEMPTS:
        if exhausted is None:
            _insert_once(session, Observation, dict(
                observation_id=marker_id, source_run_id=source_run_id, source_type="backend_export",
                started_at=current, ended_at=current, state="failed", complete=False,
                proof_json={"capture_mode": "automatic_budget", "business_month": month,
                            "maximum_attempts": MAX_AUTOMATIC_MONTH_ATTEMPTS},
                error_code="monthend_capture_budget_exhausted",
            ), "observation_id")
        return CaptureAdmission(blocked_reason="monthend_capture_budget_exhausted")
    identity = start_observation(session, source_run_id=source_run_id, started_at=current,
                                 proof={"capture_mode": "automatic", "business_month": month})
    return CaptureAdmission(observation_id=identity)


def canonical_records(records: list) -> list[dict]:
    result = []
    seen_records = set()
    for record in records:
        payload = record.get("raw_payload") or {}
        def field(*keys):
            values = {str(payload[key]).strip() for key in keys if payload.get(key) not in (None, "")}
            if len(values) > 1:
                raise AccountQualificationError("conflicting_source_fields")
            return next(iter(values), None)
        kind = field("账号类型", "账户类型", "account_type")
        status = field("抖音号绑定状态", "绑定状态", "binding_status")
        # The exported Chinese columns define the text contract, not a closed
        # vocabulary of negative labels. Unknown/rejected labels are negative
        # rows; numeric API codes are an unverified source contract instead.
        chinese_columns = (any(key in payload for key in ("账号类型", "账户类型"))
                           and any(key in payload for key in ("抖音号绑定状态", "绑定状态")))
        if (kind is None or status is None
                or re.fullmatch(r"[+-]?\d+(?:\.\d+)?", kind)
                or re.fullmatch(r"[+-]?\d+(?:\.\d+)?", status)
                or (not chinese_columns and (kind not in ELIGIBLE_TYPES or status != "认证成功"))):
            raise AccountQualificationError("unknown_type_or_certification_contract")
        reasons = []
        if kind not in ELIGIBLE_TYPES:
            reasons.append("account_type_not_eligible")
        if status != "认证成功":
            reasons.append("certification_not_successful")
        account = field("账户所属id", "账户所属ID", "所属账户id", "所属账户ID", "account_id")
        parsed_account = str(record.get("account_id") or "").strip() or None
        if account != parsed_account or (not account and not reasons):
            raise AccountQualificationError("source_account_identity_missing_or_conflicting")
        if account is None:
            reasons.append("nonqualifying_record_without_account_id")
        row = {"account_id": account, "douyin_id": record.get("douyin_id"),
               "douyin_nickname": record.get("douyin_nickname") or field(*ROSTER_NAME_FIELDS),
               "store_id": record.get("store_id"),
               "douyin_uid": field("douyin_uid"), "poi_id": record.get("poi_id"),
               "account_type": kind, "binding_status": status, "raw_payload": payload,
               "qualification_status": "ineligible" if reasons else "eligible", "reason_codes": reasons}
        # Identical exported rows may be repeated. Distinct rows remain in the
        # evidence so a name conflict affects its own scope at calculation time.
        fingerprint = digest(row)
        if fingerprint in seen_records:
            continue
        seen_records.add(fingerprint)
        result.append(row)
    return sorted(result, key=digest)


def complete_observation(session: Session, observation_id: str, records: list, *, ended_at: datetime | None = None) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7462180066)"))
    observation = session.get(Observation, observation_id)
    if observation is None or observation.state != "running":
        raise AccountQualificationError("observation_not_running")
    end = utc(ended_at or datetime.now(UTC))
    proof = {**dict(getattr(records, "proof", {})), **(observation.proof_json or {})}
    observation.source_type = getattr(records, "source_type", "unknown")
    observation.ended_at = end
    observation.proof_json = proof
    try:
        if end < utc(observation.started_at) or not proof.get("complete") or proof.get("record_count") != len(records):
            raise AccountQualificationError("incomplete_collection")
        normalized = canonical_records(records)
    except AccountQualificationError as exc:
        observation.state, observation.complete, observation.error_code = "failed", False, str(exc)
        session.flush()
        return
    encoded = json.dumps({"policy": POLICY_VERSION, "records": normalized}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        observation.state, observation.complete = "failed", False
        observation.error_code = "qualification_snapshot_size_limit"
        observation.proof_json = {**proof, "snapshot_bytes": len(encoded), "maximum_snapshot_bytes": MAX_SNAPSHOT_BYTES}
        session.flush()
        return
    content = hashlib.sha256(encoded).hexdigest()
    # One terminal UPDATE is enforced by the migration guard. Do not let the
    # content INSERT autoflush an intermediate running observation.
    with session.no_autoflush:
        _insert_once(session, Snapshot, dict(content_sha256=content, records_json=normalized,
                                            record_count=len(normalized), policy_version=POLICY_VERSION), "content_sha256")
    observation.content_sha256 = content
    observation.state, observation.complete = "success", True
    session.flush()


def fail_observation(session: Session, observation_id: str, *, error_code: str, ended_at: datetime | None = None) -> None:
    observation = session.get(Observation, observation_id)
    if observation is not None and observation.state == "running":
        observation.state, observation.complete = "failed", False
        observation.ended_at = utc(ended_at or datetime.now(UTC))
        observation.error_code = error_code[:128]
        session.flush()


def freeze_month(session: Session, month: str, *, now: datetime | None = None) -> Version:
    if month < FIRST_MONTH:
        raise AccountQualificationError("legacy_month_has_no_qualification_version")
    day_start, cutoff = month_bounds(month)
    current = utc(now or datetime.now(UTC))
    if current < cutoff:
        raise AccountQualificationError("month_not_finished")
    # Serialize publication with collection starts/results. Short DB transactions
    # only: the browser request is never made while holding this lock.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7462180066)"))
    existing = session.scalar(select(Version).where(Version.business_month == month))
    if existing is not None:
        return existing
    observations = list(session.scalars(select(Observation).where(
        Observation.started_at >= day_start, Observation.started_at < cutoff,
    ).order_by(Observation.started_at.desc(), Observation.observation_id.desc())))
    if not observations:
        raise AccountQualificationError("monthend_observation_missing")
    latest_started = observations[0]
    last = max(observations, key=lambda row: (utc(row.ended_at) if row.ended_at else cutoff, utc(row.started_at), row.observation_id))
    # A late completion / failed / killed final attempt blocks older success.
    if (latest_started.state != "success" or last.state != "success" or not last.complete or last.content_sha256 is None
            or last.ended_at is None or utc(last.ended_at) >= cutoff
            or utc(last.started_at) < cutoff - MAX_AGE
            or utc(last.ended_at) < cutoff - MAX_AGE
            or any(row.state == "running" for row in observations)):
        raise AccountQualificationError("monthend_latest_attempt_not_complete_or_fresh")
    snapshot = session.get(Snapshot, last.content_sha256)
    if snapshot is None:
        raise AccountQualificationError("qualification_snapshot_missing")
    policy = snapshot.policy_version
    version_id = "account-month-" + digest({"month": month, "observation": last.observation_id,
                                            "hash": last.content_sha256, "policy": policy})
    _insert_once(session, Version, dict(version_id=version_id, business_month=month, cutoff_at=cutoff,
                                        observation_id=last.observation_id, content_sha256=last.content_sha256,
                                        policy_version=policy, frozen_at=current), "business_month")
    session.flush()
    return session.scalar(select(Version).where(Version.business_month == month))


def frozen_version(session: Session, month: str) -> Version:
    version = session.scalar(select(Version).where(Version.business_month == month))
    if version is None:
        raise AccountQualificationError("monthend_version_missing")
    return version


def qualified_version(session: Session, *, month: str, order, pinned_version_id: str | None = None) -> Version:
    try:
        version = frozen_version(session, month)
    except AccountQualificationError:
        version = freeze_month(session, month)
    if pinned_version_id is not None and version.version_id != pinned_version_id:
        raise AccountQualificationError("qualification_version_conflict")
    qualified_records(session, version=version, order=order)
    return version


def order_sale_name(order) -> tuple[str, str]:
    """Read the selected sales-name source with the order collector's priority."""
    payload = getattr(order, "raw_payload", None) or {}
    for source_field in SALE_NAME_PATHS:
        raw = get_path(payload, source_field) if isinstance(payload, dict) else None
        if raw in (None, ""):
            continue
        name = raw.strip() if isinstance(raw, str) else None
        if not isinstance(raw, str) or not name:
            raise AccountQualificationError("qualification_sale_name_source_invalid")
        parsed_name = getattr(order, "owner_account_name", None)
        if not isinstance(parsed_name, str) or parsed_name.strip() != name:
            raise AccountQualificationError("qualification_sale_name_source_conflict")
        return source_field, name
    raise AccountQualificationError("qualification_sale_name_source_missing")


def _roster_names(row: dict) -> set[str]:
    payload = row.get("raw_payload") or {}
    values = {str(payload[key]).strip() for key in ROSTER_NAME_FIELDS
              if payload.get(key) not in (None, "")}
    if row.get("douyin_nickname"):
        values.add(str(row["douyin_nickname"]).strip())
    return values


def _frozen_name_candidates(
    session: Session, *, version: Version, order, allow_conflicting_names: bool = False,
) -> list[dict]:
    """Read exact-name candidates without granting eligibility or attribution."""
    _, name = order_sale_name(order)
    cache = session.info.setdefault("account_qualification_name_indexes", {})
    if version.content_sha256 not in cache:
        snapshot = session.get(Snapshot, version.content_sha256)
        if snapshot is None or digest({"policy": version.policy_version, "records": snapshot.records_json}) != version.content_sha256:
            raise AccountQualificationError("qualification_source_digest_mismatch")
        names = {}
        identities = {}
        conflicting_names = set()
        for row in snapshot.records_json:
            identities.setdefault((row.get("account_id"), row.get("douyin_id")), {})[digest(row)] = row
            source_names = _roster_names(row)
            if len(source_names) > 1:
                conflicting_names.update(source_names)
            for roster_name in source_names:
                names.setdefault(roster_name, {})[digest(row)] = row
        cache[version.content_sha256] = (
            {key: list(rows.values()) for key, rows in names.items()}, conflicting_names,
            {key: list(rows.values()) for key, rows in identities.items()},
        )
    names, conflicting_names, identities = cache[version.content_sha256]
    if name in conflicting_names and not allow_conflicting_names:
        raise AccountQualificationError("qualification_roster_name_source_conflict")
    candidate_rows = {digest(row): row for row in names.get(name, [])}
    evidence = _store_evidence(session, version)
    if evidence is not None:
        sale_time = getattr(order, "sale_time", None) or getattr(order, "pay_time", None)
        if not allow_conflicting_names and sale_time is None and evidence.alias_identities(name):
            raise AccountQualificationError("qualification_alias_sale_time_missing")
        alias_identities = evidence.alias_identities(name, at=None if allow_conflicting_names else sale_time)
        for identity in alias_identities:
            rows = identities.get(identity)
            if not rows:
                raise AccountQualificationError("qualification_alias_identity_unmatched")
            candidate_rows.update({digest(row): row for row in rows})
    candidates = list(candidate_rows.values())
    if not candidates:
        raise AccountQualificationError("qualification_sale_name_unmatched")
    if not allow_conflicting_names and any(len(_roster_names(row)) > 1 for row in candidates):
        raise AccountQualificationError("qualification_roster_name_source_conflict")
    return candidates


def qualified_records(session: Session, *, version: Version, order) -> list[dict]:
    """Match one exact original sales name to one frozen account identity."""
    candidates = _frozen_name_candidates(session, version=version, order=order)
    accounts = {(row.get("account_id"), row.get("douyin_id")) for row in candidates}
    if any(not account_id or not douyin_id for account_id, douyin_id in accounts):
        raise AccountQualificationError("qualification_name_account_missing")
    if len(accounts) != 1:
        raise AccountQualificationError("qualification_name_multiple_accounts")
    merchant_states = {}
    for row in candidates:
        if row["account_type"] in ELIGIBLE_TYPES:
            merchant_states.setdefault(row["account_type"], set()).add(row["binding_status"])
    if any(len(statuses) > 1 for statuses in merchant_states.values()):
        raise AccountQualificationError("qualification_name_record_conflict")
    if not any(statuses == {"认证成功"} for statuses in merchant_states.values()):
        raise AccountQualificationError("account_not_qualified_in_frozen_month")
    return [row for row in candidates
            if row["account_type"] in ELIGIBLE_TYPES and row["binding_status"] == "认证成功"]


def _store_evidence(session: Session, version: Version):
    """Read the execution's immutable mapping version without creating evidence."""
    from apps.worker.monthly_store_evidence import StoreEvidenceError, frozen_store_evidence

    pinned_version = session.info.get("monthly_store_evidence_version_id")
    try:
        return frozen_store_evidence(
            session, qualification_version=version, version_id=pinned_version,
        )
    except StoreEvidenceError as exc:
        if str(exc) != "store_evidence_not_frozen" or pinned_version:
            raise AccountQualificationError(str(exc)) from exc
        # Already captured versions remain readable while their supplemental
        # evidence is prepared. New monthly executions explicitly freeze and pin
        # their evidence before entering this resolver.
        return None


def _candidate_store_ids(session: Session, candidates: list[dict], *, evidence=None) -> frozenset[str]:
    stores = set()
    errors = []
    unresolved = False
    for row in candidates:
        direct_stores = set()
        if evidence is not None:
            direct_stores.update(evidence.account_store_ids(row.get("account_id")))
        elif row.get("store_id"):
            direct_stores.add(source_text(row["store_id"]))
        poi_id = source_text(row.get("poi_id"))
        mapped_stores = set()
        if poi_id and evidence is not None:
            mapped_stores = set(evidence.poi_store_ids(poi_id))
        elif poi_id:
            mapped_stores = set(session.scalars(select(DimStorePoiMapping.store_id).where(
                DimStorePoiMapping.poi_id == poi_id,
            )))
        proven_stores = direct_stores | mapped_stores
        stores.update(proven_stores)
        if not proven_stores:
            unresolved = True
            errors.append("qualification_name_store_unmapped" if poi_id else "qualification_name_store_missing")
        elif any(session.get(DimStore, store_id) is None for store_id in proven_stores):
            unresolved = True
            errors.append("qualification_name_store_unmapped")
        elif direct_stores and mapped_stores and direct_stores != mapped_stores:
            errors.append("qualification_name_store_conflict")
        elif len(proven_stores) != 1:
            errors.append("qualification_name_multiple_stores")
    if errors:
        raise AccountQualificationError(errors[0], candidate_store_ids=None if unresolved else frozenset(stores))
    return frozenset(stores)


def frozen_sale_candidate_stores(session: Session, *, version: Version, order) -> frozenset[str] | None:
    """Bound exception impact to all proven candidate stores without granting fees."""
    try:
        candidates = _frozen_name_candidates(session, version=version, order=order, allow_conflicting_names=True)
        return _candidate_store_ids(session, candidates, evidence=_store_evidence(session, version))
    except AccountQualificationError as exc:
        return exc.candidate_store_ids


def qualified_sale_match(
    session: Session, *, version: Version, order, pinned_context: dict | None = None,
) -> FrozenSaleMatch:
    """Resolve the frozen account's explicit store/POI without live nickname lookup."""
    source_field, name = order_sale_name(order)
    candidates = qualified_records(session, version=version, order=order)
    evidence = _store_evidence(session, version)
    evidence_context = evidence.as_context() if evidence is not None else None
    roster_names = tuple(sorted({roster_name for row in candidates for roster_name in _roster_names(row)}))
    name_match_source = "frozen_historical_alias" if name not in roster_names else None
    poi_ids = tuple(sorted({source_text(row.get("poi_id")) for row in candidates if row.get("poi_id")}))
    if (pinned_context
            and evidence is None
            and pinned_context.get("policy") == SALE_ACCOUNT_MATCH_POLICY
            and pinned_context.get("qualification_version_id") == version.version_id
            and pinned_context.get("content_sha256") == version.content_sha256
            and pinned_context.get("account_name") == name
            and pinned_context.get("account_id") == candidates[0]["account_id"]
            and pinned_context.get("douyin_id") == candidates[0]["douyin_id"]
            and pinned_context.get("poi_ids") == list(poi_ids)
            and pinned_context.get("store_evidence") == evidence_context
            and pinned_context.get("store_id")):
        return FrozenSaleMatch(
            account_id=candidates[0]["account_id"], douyin_id=candidates[0]["douyin_id"],
            store_id=pinned_context["store_id"], poi_ids=poi_ids, account_name=name,
            source_field=source_field, qualification_version_id=version.version_id,
            content_sha256=version.content_sha256, store_evidence=evidence_context,
        )
    stores = _candidate_store_ids(session, candidates, evidence=evidence)
    if len(stores) != 1:
        raise AccountQualificationError("qualification_name_multiple_stores")
    return FrozenSaleMatch(
        account_id=candidates[0]["account_id"], douyin_id=candidates[0]["douyin_id"], store_id=next(iter(stores)),
        poi_ids=tuple(sorted(poi_ids)), account_name=name, source_field=source_field,
        qualification_version_id=version.version_id, content_sha256=version.content_sha256,
        store_evidence=evidence_context, name_match_source=name_match_source,
        matched_roster_names=roster_names if name_match_source is not None else (),
    )
