"""Frozen settlement account eligibility; independent of ranking and store attribution.

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
)
from apps.worker.collectors.normalizers import get_path, text as source_text

POLICY_VERSION = "settlement-monthend-cn-v2"
FIRST_MONTH = "2026-10"
SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_AGE = timedelta(hours=2)
MAX_AUTOMATIC_MONTH_ATTEMPTS = 8
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
ELIGIBLE_TYPES = {"子机构门店号", "子机构区域号"}
ORDER_IDENTITY_CONTRACT_URL = "https://partner.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/order.query/query"


class AccountQualificationError(RuntimeError):
    """Missing, partial or unprovable month-end evidence."""


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
    identities = set()
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
               "douyin_uid": field("douyin_uid"), "poi_id": record.get("poi_id"),
               "account_type": kind, "binding_status": status, "raw_payload": payload,
               "qualification_status": "ineligible" if reasons else "eligible", "reason_codes": reasons}
        identity = (account, row["douyin_id"], row["poi_id"], kind)
        identifiable = any(identity[:3])
        if identifiable and identity in identities:
            raise AccountQualificationError("duplicate_or_conflicting_binding_identity")
        if identifiable:
            identities.add(identity)
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


def qualified_records(session: Session, *, version: Version, order) -> list[dict]:
    cache = session.info.setdefault("account_qualification_indexes", {})
    if version.content_sha256 not in cache:
        snapshot = session.get(Snapshot, version.content_sha256)
        if snapshot is None or digest({"policy": version.policy_version, "records": snapshot.records_json}) != version.content_sha256:
            raise AccountQualificationError("qualification_source_digest_mismatch")
        accounts, uids, short_ids = {}, {}, {}
        for row in snapshot.records_json:
            accounts.setdefault(row["account_id"], []).append(row)
            if row.get("douyin_uid"):
                uids.setdefault(row["douyin_uid"], []).append(row)
            if row.get("douyin_id"):
                short_ids.setdefault(row["douyin_id"], []).append(row)
        cache[version.content_sha256] = accounts, uids, short_ids
    accounts, uids, short_ids = cache[version.content_sha256]
    account_id, uid = str(order.owner_account_id or "").strip(), str(order.owner_douyin_uid or "").strip()
    payload = getattr(order, "raw_payload", None) or {}

    def selected_origin(*paths):
        # Match first()/text() exactly, including its first nonempty raw value
        # priority rather than searching lower-priority fields for a match.
        for path in paths:
            value = get_path(payload, path) if isinstance(payload, dict) else None
            if value not in (None, ""):
                return path, source_text(value)
        return None, None

    account_origin, source_account = selected_origin(
        "owner_account_id", "sale_info.transfer_uid", "sale_info.account_id", "order_sale_info.transfer_uid")
    uid_origin, source_uid = selected_origin(
        "owner_douyin_uid", "sale_info.transfer_douyin_uid", "order_sale_info.transfer_douyin_uid")
    if ((account_origin is not None and (source_account or "") != account_id)
            or (uid_origin is not None and (source_uid or "") != uid)):
        raise AccountQualificationError("qualification_identity_source_conflict")
    opaque_origin = account_origin in {"sale_info.transfer_uid", "order_sale_info.transfer_uid"}
    account_candidates = [] if opaque_origin else accounts.get(account_id, [])
    # Official order-query schema: transfer_douyin_uid is the order owner's
    # Douyin short handle, while transfer_uid is encrypted and is not a Douyin
    # UID. Only this proven selected origin may match workbook douyin_id.
    # Source: ORDER_IDENTITY_CONTRACT_URL; a generic owner_douyin_uid is not
    # silently reclassified into the short-handle namespace.
    short_origin = uid_origin in {"sale_info.transfer_douyin_uid", "order_sale_info.transfer_douyin_uid"}
    secondary_candidates = short_ids.get(uid, []) if short_origin else uids.get(uid, [])
    if account_candidates and secondary_candidates:
        common = {row["account_id"] for row in account_candidates} & {row["account_id"] for row in secondary_candidates}
        if not common:
            raise AccountQualificationError("qualification_identity_ambiguous")
        candidates = [row for row in secondary_candidates if row["account_id"] in common]
    else:
        candidates = account_candidates + secondary_candidates
    if not candidates:
        raise AccountQualificationError("qualification_identity_unresolved")
    eligible = [row for row in candidates if row["account_type"] in ELIGIBLE_TYPES
                and row["binding_status"] == "认证成功"]
    if not eligible:
        raise AccountQualificationError("account_not_qualified_in_frozen_month")
    if len({row["account_id"] for row in eligible}) != 1:
        raise AccountQualificationError("qualification_identity_ambiguous")
    return eligible
