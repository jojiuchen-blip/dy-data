from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, exists, false, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from apps.api.dy_api.models import (
    AccessPage,
    AccountPermissionAuditLog,
    ClueAllocationAuditLog,
    ClueAllocationCandidate,
    ClueAllocationCycle,
    ClueAllocationCycleItem,
    ClueAllocationDecision,
    ClueAllocationRule,
    ClueAllocationRuleVersion,
    ClueAllocationStrategyConfig,
    ClueAssignmentRound,
    ClueMasterLead,
    ClueHeadquartersPoolEntry,
    ClueStoreGroup,
    ClueStoreGroupMember,
    DimAwemeAccount,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    DataQualityIssue,
    JobRun,
    SkuProductSyncHistory,
    StoreScoreSnapshot,
    StoreScoreSnapshotGeneration,
    StoreScoreSnapshotRun,
    User,
    UserFeedbackSubmission,
    UserStoreScope,
    UserPagePermissionOverride,
)
from apps.api.dy_api.access_control import (
    add_audit_log,
    effective_page_keys,
    page_rows,
    replace_user_overrides,
    role_default_page_keys,
    update_role_defaults_preserving_customizations,
    user_override_sets,
    validate_page_keys,
)
from apps.api.dy_api.db import get_session_factory
from apps.api.dy_api.user_auth_state import replace_user_store_scopes
from apps.worker.backfill import iter_backfill_windows, successful_window_keys
from apps.worker.collectors.types import CollectionWindow
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.clue_allocation import refresh_store_score_snapshots
from apps.worker.clue_headquarters_pool import (
    HEADQUARTERS_POOL_REASON_CODES,
    canonical_headquarters_pool_reason,
    headquarters_pool_reason_storage_values,
)
from apps.worker.clue_allocation_cycles import (
    AllocationCycleError,
    preview_rebuild_trial_allocation_cycle,
    preview_trial_allocation_cycle,
    rebuild_trial_allocation_cycle,
    run_trial_allocation_cycle,
    validate_allocation_preview_grant,
)
from apps.worker.manual_sync import run_manual_sync_job
from apps.worker.clue_rule_versions import (
    RuleImmutableError,
    RuleNotFoundError,
    RuleVersionError,
    create_rule as create_clue_allocation_rule,
    create_rule_version,
    create_store_group,
    delete_rule_version,
    publish_rule_version,
    replace_store_group_members,
    retire_rule_version,
    update_rule_version,
)
from apps.worker.product_sync import PRODUCT_SYNC_JOB_NAME, run_product_sync_job
from apps.worker.projection_lineage import (
    MAX_LINEAGE_DEPTH,
    LineageError,
    active_generation_id,
    canonical_score_partition_key,
    resolve_projection_partitions,
)
from apps.worker.repositories import queue_job_run
from dy_api.routes._settlement_jobs import run_settlement_rebuild_job
from apps.worker.sync_config import load_sync_config, save_sync_config
from dy_api.auth import (
    AuthContext,
    get_current_admin,
    get_current_super_admin,
    get_current_user,
    hash_password_pbkdf2,
    normalize_account_value,
)
from dy_api.routes._data import get_data_store, generated_at, request_id, sanitize_error_message
from dy_api.schemas import (
    AccountListData,
    AccountPagePermissionUpdateRequest,
    AccountPermissionAuditListData,
    AccountPermissionAuditRow,
    AccountPasswordUpdateRequest,
    AccountRow,
    AccountStoreScopeRow,
    AccountUpsertRequest,
    AccessControlData,
    AccessPageRow,
    ManualSyncRequest,
    ManualSyncResult,
    ClueAllocationCandidateRow,
    ClueAllocationDecisionData,
    ClueAllocationDecisionDetailData,
    ClueAllocationDecisionRow,
    ClueAllocationAuditLogData,
    ClueAllocationAuditLogRow,
    ClueAllocationCycleData,
    ClueAllocationCycleDetailData,
    ClueAllocationCycleExecutionData,
    ClueAllocationCycleItemRow,
    ClueAllocationCyclePreviewData,
    ClueAllocationCyclePreviewRequest,
    ClueAllocationCycleRequest,
    ClueAllocationCycleRebuildRequest,
    ClueAllocationCycleRow,
    ClueAllocationEligibleLeadData,
    ClueAllocationEligibleLeadRow,
    ClueHeadquartersPoolData,
    ClueHeadquartersPoolEntryRow,
    ClueHeadquartersPoolFilterOptions,
    ClueHeadquartersPoolSummary,
    ClueMasterLeadData,
    ClueMasterLeadRow,
    ClueAllocationRuleCreateRequest,
    ClueAllocationRuleData,
    ClueAllocationRuleDetailData,
    ClueAllocationRuleListData,
    ClueAllocationRuleVersionData,
    ClueAllocationRuleVersionDeleteData,
    ClueAllocationRuleVersionWrite,
    ClueStoreGroupCreateRequest,
    ClueStoreGroupData,
    ClueStoreGroupListData,
    ClueStoreGroupMembersUpdate,
    FeedbackListData,
    FeedbackRow,
    FeedbackStatusUpdateRequest,
    NonCommissionOwnerAccountBulkUpdateRequest,
    NonCommissionOwnerAccountBulkUpdateResult,
    NonCommissionOwnerAccountListData,
    Pagination,
    ProductTypeVisibilityData,
    ProductTypeVisibilityUpdate,
    RolePagePermissionUpdateRequest,
    RolePermissionImpactData,
    ProductSyncRunRequest,
    SkuRuleBulkUpdateRequest,
    SkuRuleBulkUpdateResult,
    SkuRuleListData,
    SkuRuleLookupData,
    SkuRuleLookupRequest,
    StoreScoreRefreshRequest,
    StoreScoreRefreshResult,
    StoreScoreSnapshotData,
    StoreScoreSnapshotRow,
    StoreScoreSnapshotRunData,
    SyncAdminData,
    SyncConfigData,
    SyncConfigUpdate,
    SyncProgressData,
    SyncScheduleData,
    SyncWorkerStatusData,
    SyncWindowData,
    UnactivatedStoreAccountListData,
    UnactivatedStoreAccountRow,
    JobRun as JobRunData,
    dump_model,
)


# Score history is resolved in bounded pages independently from API pagination.
SCORE_RUN_PAGE_SIZE = 100
SCORE_FACT_BATCH_SIZE = 400
SCORE_SIDECAR_BATCH_SIZE = 400


class _ScoreSidecarClaim(str):
    """Rule identity with authoritative generation-sidecar metadata."""

    snapshot_date: date
    partition_key: str
    generation_id: str

    def __new__(
        cls,
        rule_version_id: str,
        *,
        snapshot_date: date,
        partition_key: str,
        generation_id: str,
    ):
        value = str.__new__(cls, rule_version_id)
        value.snapshot_date = snapshot_date
        value.partition_key = partition_key
        value.generation_id = generation_id
        return value


router = APIRouter()
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

HEADQUARTERS_POOL_REASON_LABELS = {
    "missing_follow_poi": "缺少位置锚点",
    "anchor_store_unmapped": "锚点门店无法匹配",
    "anchor_geo_invalid": "锚点城市或经纬度不可用",
    "no_published_rule": "未匹配可用分配规则",
    "all_strategies_disabled": "当前规则未启用分配策略",
    "no_eligible_candidate": "所有启用策略均无可用门店",
    "all_strategies_exhausted": "所有启用策略均已结束",
    "data_inconsistency": "关键事实不一致，待总部治理",
}
WORKER_STATUS_JOB_NAMES = (
    "collect_and_settle",
    "backend_aweme_export",
    "manual_backend_aweme_export",
    "douyin_collection",
)
DEFAULT_WORKER_CHUNK_MAX_ATTEMPTS = 2
DISABLED_WORKER_POLL_SECONDS = 60
FEEDBACK_CATEGORIES = {"experience", "data", "feature", "other"}
FEEDBACK_STATUSES = {"new", "reviewed", "resolved", "ignored"}


def _require_available_store(store):
    if not store.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    return store


def _require_clue_admin_context(
    current_user: AuthContext = Depends(get_current_user),
) -> AuthContext:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_user


def _require_clue_super_admin_context(
    current_user: AuthContext = Depends(get_current_user),
) -> AuthContext:
    if not current_user.is_highest_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Highest administrator access required",
        )
    return current_user


def _stable_actor_user_id(current_user: AuthContext) -> str:
    return current_user.user_id or f"environment:{current_user.username}"


def _record_clue_admin_audit(
    session,
    *,
    request: Request,
    current_user: AuthContext,
    event_type: str,
    before_snapshot: dict | None = None,
    after_snapshot: dict | None = None,
    detail: dict | None = None,
) -> None:
    session.add(
        ClueAllocationAuditLog(
            audit_log_id=f"allocation-audit-{uuid4().hex}",
            event_type=event_type,
            actor=current_user.username,
            actor_user_id=_stable_actor_user_id(current_user),
            actor_username_snapshot=current_user.username,
            actor_role_snapshot=current_user.role,
            actor_scope_snapshot={
                "mode": current_user.store_scope_mode,
                "store_ids": list(current_user.store_ids),
            },
            request_id=request_id(request),
            result_status="success",
            privileged_confirmation=True,
            before_snapshot=jsonable_encoder(_without_phone_fields(before_snapshot or {})),
            after_snapshot=jsonable_encoder(_without_phone_fields(after_snapshot or {})),
            detail_json=jsonable_encoder(_without_phone_fields(detail or {})),
            created_at=datetime.now(timezone.utc),
        )
    )


def _clue_scope_store_ids(current_user: AuthContext) -> tuple[str, ...] | None:
    if current_user.has_global_data_access:
        return None
    return tuple(sorted({store_id for store_id in current_user.store_ids if store_id}))


def _lead_scope_condition(current_user: AuthContext):
    store_ids = _clue_scope_store_ids(current_user)
    if store_ids is None:
        return None
    if not store_ids:
        return false()
    return or_(
        ClueMasterLead.anchor_store_id.in_(store_ids),
        exists(
            select(1).where(
                ClueAssignmentRound.lead_key == ClueMasterLead.lead_key,
                ClueAssignmentRound.assigned_store_id.in_(store_ids),
                ClueAssignmentRound.execution_mode == "formal",
            )
        ),
    )


def _rule_scope_condition(current_user: AuthContext):
    store_ids = _clue_scope_store_ids(current_user)
    if store_ids is None:
        return None
    if not store_ids:
        return false()
    city_codes = select(DimStore.city_code).where(
        DimStore.store_id.in_(store_ids),
        DimStore.city_code.is_not(None),
    )
    store_group_ids = select(ClueStoreGroupMember.store_group_id).where(
        ClueStoreGroupMember.store_id.in_(store_ids)
    )
    return or_(
        ClueAllocationRule.scope_type == "global",
        ClueAllocationRule.scope_anchor_store_id.in_(store_ids),
        ClueAllocationRule.scope_city_code.in_(city_codes),
        ClueAllocationRule.scope_store_group_id.in_(store_group_ids),
    )


def _decision_scope_condition(current_user: AuthContext):
    store_ids = _clue_scope_store_ids(current_user)
    if store_ids is None:
        return None
    if not store_ids:
        return false()
    lead_scope = _lead_scope_condition(current_user)
    return or_(
        ClueAllocationDecision.selected_store_id.in_(store_ids),
        exists(
            select(1).where(
                ClueMasterLead.lead_key == ClueAllocationDecision.lead_key,
                lead_scope,
            )
        ),
    )


def _cycle_scope_condition(current_user: AuthContext):
    if _clue_scope_store_ids(current_user) is None:
        return None
    lead_scope = _lead_scope_condition(current_user)
    return exists(
        select(1)
        .select_from(ClueAllocationCycleItem)
        .join(ClueMasterLead, ClueMasterLead.lead_key == ClueAllocationCycleItem.lead_key)
        .where(
            ClueAllocationCycleItem.allocation_cycle_id
            == ClueAllocationCycle.allocation_cycle_id,
            lead_scope,
        )
    )


def _scoped_cycle_items(
    session,
    cycles: list[ClueAllocationCycle],
    current_user: AuthContext,
) -> dict[str, list[ClueAllocationCycleItem]] | None:
    if _clue_scope_store_ids(current_user) is None:
        return None
    cycle_ids = [cycle.allocation_cycle_id for cycle in cycles]
    if not cycle_ids:
        return {}
    lead_scope = _lead_scope_condition(current_user)
    rows = session.scalars(
        select(ClueAllocationCycleItem)
        .join(ClueMasterLead, ClueMasterLead.lead_key == ClueAllocationCycleItem.lead_key)
        .where(
            ClueAllocationCycleItem.allocation_cycle_id.in_(cycle_ids),
            lead_scope,
        )
        .order_by(
            ClueAllocationCycleItem.allocation_cycle_id,
            ClueAllocationCycleItem.sequence_no,
            ClueAllocationCycleItem.cycle_item_id,
        )
    ).all()
    grouped: dict[str, list[ClueAllocationCycleItem]] = {
        cycle_id: [] for cycle_id in cycle_ids
    }
    for row in rows:
        grouped.setdefault(row.allocation_cycle_id, []).append(row)
    return grouped


def _shanghai_day_start(value: date) -> datetime:
    return datetime.combine(value, datetime.min.time(), tzinfo=SHANGHAI_TZ).astimezone(timezone.utc)


def _rule_version_http_error(error: RuleVersionError) -> HTTPException:
    if isinstance(error, RuleNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, RuleImmutableError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


def _allocation_cycle_http_error(error: AllocationCycleError) -> HTTPException:
    detail = str(error)
    if detail.startswith(
        ("active_round_exists:", "rebuild_blocked_by_follow_up:", "idempotency_key_conflict")
    ):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


@router.get("/accounts")
def list_accounts(
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _require_account_manager(actor)
    statement = select(User).order_by(User.created_at, User.username)
    if not actor.is_highest_admin:
        statement = statement.where(User.role == "store")
    users = store.session.execute(statement).scalars().all()
    data = AccountListData(rows=[_account_row(store.session, user) for user in users])
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/accounts/unactivated-stores")
def list_unactivated_store_accounts(
    q: str | None = None,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _require_account_manager(actor)
    data = UnactivatedStoreAccountListData(
        rows=_unactivated_store_account_rows(store.session, q=q)
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/accounts")
def create_account(
    payload: AccountUpsertRequest,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _require_account_manager(actor)
    _ensure_actor_can_manage_role(actor, payload.role)
    _validate_password_payload(payload.password, payload.password_confirm, required=True)
    technical_username = payload.username or f"acct{uuid4().hex}"
    _ensure_unique_user_fields(
        store.session,
        username=technical_username,
        external_account_id=payload.external_account_id,
        exclude_user_id=None,
    )
    store_ids = _validated_scope_store_ids(
        payload.role, payload.store_scope_mode, payload.store_ids
    )
    _ensure_store_ids_exist(store.session, store_ids)
    now = generated_at()
    user = User(
        user_id=uuid4().hex,
        username=normalize_account_value(technical_username),
        external_account_id=_optional_account_value(payload.external_account_id),
        display_name=normalize_account_value(payload.display_name),
        role=payload.role,
        store_scope_mode=_normalized_scope_mode(payload.role, payload.store_scope_mode),
        status=payload.status,
        is_initialized=True,
        password_hash=hash_password_pbkdf2(payload.password or ""),
        created_at=now,
        updated_at=now,
    )
    store.session.add(user)
    store.session.flush()
    _replace_user_scopes(store.session, user.user_id, store_ids)
    add_audit_log(
        store.session,
        action="account.created",
        actor=actor,
        target=user,
        after=_account_audit_snapshot(store.session, user),
    )
    store.session.commit()
    data = _account_row(store.session, user)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/accounts/{user_id}")
def update_account(
    user_id: str,
    payload: AccountUpsertRequest,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _require_account_manager(actor)
    user = store.session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    _ensure_actor_can_manage_user(actor, user)
    _ensure_actor_can_manage_role(actor, payload.role)
    if user.role == "highest_admin" and payload.role != "highest_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Highest administrator accounts cannot be downgraded",
        )
    if actor.user_id == user.user_id and payload.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot disable your own account",
        )
    before = _account_audit_snapshot(store.session, user)
    _validate_password_payload(payload.password, payload.password_confirm, required=False)
    technical_username = payload.username or user.username
    _ensure_unique_user_fields(
        store.session,
        username=technical_username,
        external_account_id=payload.external_account_id,
        exclude_user_id=user_id,
    )
    store_ids = _validated_scope_store_ids(
        payload.role, payload.store_scope_mode, payload.store_ids
    )
    _ensure_store_ids_exist(store.session, store_ids)
    user.username = normalize_account_value(technical_username)
    user.external_account_id = _optional_account_value(payload.external_account_id)
    user.display_name = normalize_account_value(payload.display_name)
    user.role = payload.role
    user.store_scope_mode = _normalized_scope_mode(payload.role, payload.store_scope_mode)
    user.status = payload.status
    user.is_initialized = True if payload.password else user.is_initialized
    if payload.password:
        user.password_hash = hash_password_pbkdf2(payload.password)
    user.auth_version += 1
    user.updated_at = generated_at()
    _replace_user_scopes(store.session, user.user_id, store_ids)
    add_audit_log(
        store.session,
        action="account.updated",
        actor=actor,
        target=user,
        before=before,
        after=_account_audit_snapshot(store.session, user),
    )
    store.session.commit()
    data = _account_row(store.session, user)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/accounts/{user_id}/reset-password")
def admin_reset_account_password(
    user_id: str,
    payload: AccountPasswordUpdateRequest,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _require_account_manager(actor)
    user = store.session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    _ensure_actor_can_manage_user(actor, user)
    if payload.password != payload.password_confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password confirmation does not match",
        )
    user.password_hash = hash_password_pbkdf2(payload.password)
    user.is_initialized = True
    user.auth_version += 1
    user.updated_at = generated_at()
    add_audit_log(
        store.session,
        action="account.password_reset",
        actor=actor,
        target=user,
        after={"password_reset": True},
    )
    store.session.commit()
    data = _account_row(store.session, user)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/accounts/{user_id}/page-permissions")
def update_account_page_permissions(
    user_id: str,
    payload: AccountPagePermissionUpdateRequest,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _require_account_manager(actor)
    user = store.session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    _ensure_actor_can_manage_user(actor, user)
    if user.role == "highest_admin":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Highest administrator permissions are fixed",
        )
    before = _account_audit_snapshot(store.session, user)
    try:
        replace_user_overrides(
            store.session,
            user,
            extra_allow=payload.extra_allow,
            extra_deny=payload.extra_deny,
            updated_by=actor.username,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    user.auth_version += 1
    user.updated_at = generated_at()
    after = _account_audit_snapshot(store.session, user)
    add_audit_log(
        store.session,
        action="account.page_permissions.updated",
        actor=actor,
        target=user,
        before=before,
        after=after,
    )
    store.session.commit()
    return {
        "data": dump_model(_account_row(store.session, user)),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/accounts/{user_id}/page-permissions/restore")
def restore_account_page_permissions(
    user_id: str,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    return update_account_page_permissions(
        user_id,
        AccountPagePermissionUpdateRequest(extra_allow=[], extra_deny=[]),
        actor,
        store,
    )


@router.get("/access-control")
def get_access_control(
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _require_account_manager(actor)
    pages = page_rows(store.session)
    data = AccessControlData(
        pages=[
            AccessPageRow(
                page_key=row.page_key,
                page_name=row.page_name,
                module_name=row.module_name,
                route_patterns=list(row.route_patterns or []),
            )
            for row in pages
        ],
        role_permissions={
            role: list(role_default_page_keys(store.session, role))
            for role in ("highest_admin", "admin", "store")
        },
    )
    store.session.commit()
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/access-control/roles/{role}/preview")
def preview_role_page_permissions(
    role: str,
    payload: RolePagePermissionUpdateRequest,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _ensure_actor_can_manage_role_defaults(actor, role)
    try:
        page_keys = validate_page_keys(payload.page_keys)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    customized = set(
        store.session.scalars(
            select(UserPagePermissionOverride.user_id)
            .join(User, User.user_id == UserPagePermissionOverride.user_id)
            .where(User.role == role)
            .distinct()
        ).all()
    )
    total = int(store.session.scalar(select(func.count()).select_from(User).where(User.role == role)) or 0)
    data = RolePermissionImpactData(
        role=role,
        page_keys=sorted(page_keys),
        inheriting_user_count=total - len(customized),
        customized_user_count=len(customized),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/access-control/roles/{role}")
def update_role_page_permissions(
    role: str,
    payload: RolePagePermissionUpdateRequest,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _ensure_actor_can_manage_role_defaults(actor, role)
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role permission change must be previewed and confirmed",
        )
    before = {"page_keys": list(role_default_page_keys(store.session, role))}
    try:
        impact = update_role_defaults_preserving_customizations(
            store.session,
            role=role,
            page_keys=payload.page_keys,
            updated_by=actor.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    for user in store.session.scalars(select(User).where(User.role == role)).all():
        user.auth_version += 1
    after = {"page_keys": list(role_default_page_keys(store.session, role))}
    add_audit_log(
        store.session,
        action="role.page_permissions.updated",
        actor=actor,
        before={"role": role, **before},
        after={"role": role, **after, **impact},
    )
    store.session.commit()
    data = RolePermissionImpactData(role=role, page_keys=after["page_keys"], **impact)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/access-control/audit-logs")
def list_account_permission_audit_logs(
    target_user_id: str | None = None,
    action: str | None = None,
    actor_username: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    actor: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    _require_account_manager(actor)
    statement = select(AccountPermissionAuditLog)
    if target_user_id:
        statement = statement.where(AccountPermissionAuditLog.target_user_id == target_user_id)
    if action:
        statement = statement.where(AccountPermissionAuditLog.action == action)
    if actor_username:
        statement = statement.where(
            func.lower(AccountPermissionAuditLog.actor_username).contains(
                actor_username.strip().lower()
            )
        )
    if created_from:
        statement = statement.where(AccountPermissionAuditLog.created_at >= created_from)
    if created_to:
        statement = statement.where(AccountPermissionAuditLog.created_at <= created_to)
    if not actor.is_highest_admin:
        store_user_ids = select(User.user_id).where(User.role == "store")
        statement = statement.where(AccountPermissionAuditLog.target_user_id.in_(store_user_ids))
    rows = store.session.scalars(
        statement.order_by(AccountPermissionAuditLog.created_at.desc()).limit(500)
    ).all()
    data = AccountPermissionAuditListData(
        rows=[
            AccountPermissionAuditRow(
                audit_id=row.audit_id,
                action=row.action,
                result=row.result,
                actor_user_id=row.actor_user_id,
                actor_username=row.actor_username,
                actor_role=row.actor_role,
                target_user_id=row.target_user_id,
                target_username=row.target_username,
                before=row.before_json or {},
                after=row.after_json or {},
                created_at=row.created_at,
            )
            for row in rows
        ]
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/feedback")
def list_feedback(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    category: str | None = None,
    feedback_status: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    base_conditions = _feedback_conditions(category=category, q=q)
    filtered_conditions = [
        *base_conditions,
        *(_feedback_status_condition(feedback_status)),
    ]

    total = store.session.execute(
        select(func.count())
        .select_from(UserFeedbackSubmission)
        .where(*filtered_conditions)
    ).scalar_one()
    rows = store.session.execute(
        select(UserFeedbackSubmission)
        .where(*filtered_conditions)
        .order_by(UserFeedbackSubmission.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    status_rows = store.session.execute(
        select(UserFeedbackSubmission.status, func.count())
        .where(*base_conditions)
        .group_by(UserFeedbackSubmission.status)
    ).all()
    data = FeedbackListData(
        rows=[_feedback_row(row) for row in rows],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=max(1, (total + page_size - 1) // page_size),
        ),
        status_counts={status_name: count for status_name, count in status_rows},
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/feedback/{feedback_id}/status")
def update_feedback_status(
    feedback_id: str,
    payload: FeedbackStatusUpdateRequest,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    row = store.session.get(UserFeedbackSubmission, feedback_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
    row.status = payload.status
    store.session.commit()
    data = _feedback_row(row)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/sku-rules")
def list_sku_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=500, ge=1, le=1000),
    q: str | None = None,
    product_scope: str | None = None,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = SkuRuleListData(
        **store.list_sku_rules(
            page=page,
            page_size=page_size,
            q=q,
            product_scope=product_scope,
        )
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/sku-rules/lookup")
def lookup_sku_rules(
    payload: SkuRuleLookupRequest,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = SkuRuleLookupData(**store.lookup_sku_rules(payload.sku_ids))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/sku-rules")
def update_sku_rules(
    payload: SkuRuleBulkUpdateRequest,
    background_tasks: BackgroundTasks,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    rules = [dump_model(rule) for rule in payload.rules]
    updated_count = store.upsert_sku_rules(rules)
    job_id = f"admin-sku-rules-{uuid4().hex[:12]}"
    queue_job_run(
        store.session,
        job_id,
        "settlement_rebuild",
        metadata_json={
            "source_run_id": job_id,
            "trigger": "admin_sku_rules",
            "updated_rule_count": updated_count,
        },
    )
    # Make the rules visible to the background rebuild before the request
    # dependency closes this session.
    store.session.commit()
    background_tasks.add_task(run_admin_sku_rule_rebuild_job, job_id=job_id)
    data = SkuRuleBulkUpdateResult(
        updated_count=updated_count,
        job_id=job_id,
        rebuild_status="queued",
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/non-commission-owner-accounts")
def list_non_commission_owner_accounts(
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = NonCommissionOwnerAccountListData(
        rows=store.list_non_commission_owner_accounts()
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/non-commission-owner-accounts")
def update_non_commission_owner_accounts(
    payload: NonCommissionOwnerAccountBulkUpdateRequest,
    background_tasks: BackgroundTasks,
    username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    result = store.replace_non_commission_owner_accounts(
        [account.owner_account_name for account in payload.accounts],
        updated_by=username,
    )
    job_id = f"admin-non-commission-accounts-{uuid4().hex[:12]}"
    queue_job_run(
        store.session,
        job_id,
        "settlement_rebuild",
        metadata_json={
            "source_run_id": job_id,
            "trigger": "admin_non_commission_owner_accounts",
            "updated_rule_count": result["updated_count"],
        },
    )
    store.session.commit()
    background_tasks.add_task(run_admin_sku_rule_rebuild_job, job_id=job_id)
    data = NonCommissionOwnerAccountBulkUpdateResult(
        rows=result["rows"],
        updated_count=result["updated_count"],
        job_id=job_id,
        rebuild_status="queued",
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/master-leads")
def list_clue_master_leads(
    lifecycle_status: str | None = None,
    pool_location: str | None = None,
    allocation_state: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueMasterLead)
    lead_scope = _lead_scope_condition(current_user)
    if lead_scope is not None:
        statement = statement.where(lead_scope)
    if lifecycle_status:
        statement = statement.where(ClueMasterLead.lifecycle_status == lifecycle_status)
    if pool_location:
        if pool_location == "pending_allocation":
            statement = statement.where(
                or_(
                    ClueMasterLead.pool_location == pool_location,
                    ClueMasterLead.pool_location.is_(None),
                )
            )
        else:
            statement = statement.where(ClueMasterLead.pool_location == pool_location)
    if allocation_state:
        statement = statement.where(ClueMasterLead.allocation_state == allocation_state)
    total = int(store.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = store.session.scalars(
        statement.order_by(ClueMasterLead.updated_at.desc(), ClueMasterLead.lead_key)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    data = ClueMasterLeadData(
        rows=[ClueMasterLeadRow(**_clue_master_lead_payload(row)) for row in rows],
        pagination=_pagination(page, page_size, total),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/decisions")
def list_clue_allocation_decisions(
    cycle_id: str | None = None,
    lead_key: str | None = None,
    order_id: str | None = None,
    dataset_kind: str | None = None,
    strategy_type: str | None = None,
    decision_status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationDecision)
    decision_scope = _decision_scope_condition(current_user)
    if decision_scope is not None:
        statement = statement.where(decision_scope)
    if cycle_id:
        statement = statement.where(ClueAllocationDecision.allocation_cycle_id == cycle_id)
    if lead_key:
        statement = statement.where(ClueAllocationDecision.lead_key == lead_key)
    if order_id:
        statement = statement.where(ClueAllocationDecision.order_id == order_id)
    if dataset_kind:
        if dataset_kind not in {"formal", "trial"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="dataset_kind must be formal or trial",
            )
        statement = statement.where(ClueAllocationDecision.execution_mode == dataset_kind)
    if strategy_type:
        statement = statement.where(ClueAllocationDecision.strategy_type == strategy_type)
    if decision_status:
        statement = statement.where(ClueAllocationDecision.decision_status == decision_status)
    total = int(store.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = store.session.scalars(
        statement.order_by(ClueAllocationDecision.executed_at.desc(), ClueAllocationDecision.decision_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    scope_store_ids = _clue_scope_store_ids(current_user)
    data = ClueAllocationDecisionData(
        rows=[
            ClueAllocationDecisionRow(
                **_clue_allocation_decision_payload(
                    row,
                    visible_store_ids=scope_store_ids,
                )
            )
            for row in rows
        ],
        pagination=_pagination(page, page_size, total),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/decisions/{decision_id}")
def get_clue_allocation_decision(
    decision_id: str,
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationDecision).where(
        ClueAllocationDecision.decision_id == decision_id
    )
    decision_scope = _decision_scope_condition(current_user)
    if decision_scope is not None:
        statement = statement.where(decision_scope)
    row = store.session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="allocation decision not found")
    candidate_statement = select(ClueAllocationCandidate).where(
        ClueAllocationCandidate.decision_id == row.decision_id
    )
    scope_store_ids = _clue_scope_store_ids(current_user)
    if scope_store_ids is not None:
        candidate_statement = candidate_statement.where(
            ClueAllocationCandidate.store_id.in_(scope_store_ids)
            if scope_store_ids
            else false()
        )
    data = ClueAllocationDecisionDetailData(
        decision=ClueAllocationDecisionRow(
            **_clue_allocation_decision_payload(
                row,
                visible_store_ids=scope_store_ids,
            )
        ),
        candidates=[
            ClueAllocationCandidateRow(**_clue_allocation_candidate_payload(candidate))
            for candidate in store.session.scalars(
                candidate_statement.order_by(
                    ClueAllocationCandidate.rank_no.is_(None),
                    ClueAllocationCandidate.rank_no,
                    ClueAllocationCandidate.candidate_id,
                )
            ).all()
        ],
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/eligible-leads")
def list_clue_allocation_eligible_leads(
    pool_location: str = "pending_allocation",
    anchor_mapping_status: str | None = None,
    city_code: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = (
        select(ClueMasterLead)
        .where(ClueMasterLead.lifecycle_status == "active")
        .where(ClueMasterLead.normalized_order_status == "active")
        .where(ClueMasterLead.current_assignment_round_id.is_(None))
        .where(
            ClueMasterLead.allocation_state.in_(
                ("pending_allocation", "pending_reassign")
            )
        )
    )
    lead_scope = _lead_scope_condition(current_user)
    if lead_scope is not None:
        statement = statement.where(lead_scope)
    if pool_location:
        if pool_location == "pending_allocation":
            statement = statement.where(
                or_(
                    ClueMasterLead.pool_location == pool_location,
                    ClueMasterLead.pool_location.is_(None),
                )
            )
        else:
            statement = statement.where(ClueMasterLead.pool_location == pool_location)
    if anchor_mapping_status:
        if anchor_mapping_status == "mapped":
            statement = statement.where(ClueMasterLead.anchor_store_id.is_not(None))
        elif anchor_mapping_status == "unmapped":
            statement = statement.where(ClueMasterLead.anchor_store_id.is_(None))
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="anchor_mapping_status must be mapped or unmapped",
            )
    if city_code:
        statement = statement.where(ClueMasterLead.anchor_city_code == city_code)
    if q:
        normalized_query = q.strip()
        if normalized_query:
            statement = statement.where(
                or_(
                    ClueMasterLead.lead_key.contains(normalized_query, autoescape=True),
                    ClueMasterLead.order_id.contains(normalized_query, autoescape=True),
                )
            )
    total = int(store.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = store.session.scalars(
        statement.order_by(ClueMasterLead.updated_at.desc(), ClueMasterLead.lead_key)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    data = ClueAllocationEligibleLeadData(
        rows=[ClueAllocationEligibleLeadRow(**_clue_allocation_eligible_lead_payload(row)) for row in rows],
        pagination=_pagination(page, page_size, total),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/headquarters-pool")
def list_clue_headquarters_pool(
    entry_status: str | None = None,
    reason_code: str | None = None,
    normalized_order_status: str | None = None,
    city_code: str | None = None,
    q: str | None = None,
    # Temporary aliases keep existing clients readable while H01 moves to the Foundation contract.
    pool_status: str | None = None,
    reason: str | None = None,
    entered_date_start: date | None = None,
    entered_date_end: date | None = None,
    order_status: str | None = None,
    order_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    if entered_date_start and entered_date_end and entered_date_end < entered_date_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="entered_date_end must be on or after entered_date_start",
        )

    selected_entry_status = (entry_status or pool_status or "").strip()
    selected_reason = (reason_code or reason or "").strip()
    selected_order_status = (normalized_order_status or order_status or "").strip()
    selected_query = (q or order_id or "").strip()
    selected_city_code = (city_code or "").strip()
    if reason_code and reason_code not in HEADQUARTERS_POOL_REASON_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="reason_code is not a supported headquarters pool reason",
        )

    filters = []
    scope_filters = []
    lead_scope = _lead_scope_condition(current_user)
    if lead_scope is not None:
        filters.append(lead_scope)
        scope_filters.append(lead_scope)
    if selected_entry_status:
        filters.append(ClueHeadquartersPoolEntry.status == selected_entry_status)
    if selected_reason:
        canonical_reason = canonical_headquarters_pool_reason(selected_reason)
        filters.append(
            ClueHeadquartersPoolEntry.reason.in_(
                headquarters_pool_reason_storage_values(canonical_reason)
            )
        )
    if entered_date_start:
        filters.append(ClueHeadquartersPoolEntry.entered_at >= _shanghai_day_start(entered_date_start))
    if entered_date_end:
        filters.append(
            ClueHeadquartersPoolEntry.entered_at
            < _shanghai_day_start(entered_date_end + timedelta(days=1))
        )
    if selected_order_status:
        filters.append(ClueMasterLead.normalized_order_status == selected_order_status)
    if selected_city_code:
        filters.append(ClueMasterLead.anchor_city_code == selected_city_code)
    if selected_query:
        filters.append(
            or_(
                ClueMasterLead.order_id.contains(selected_query, autoescape=True),
                ClueMasterLead.lead_key.contains(selected_query, autoescape=True),
            )
        )

    statement = (
        select(ClueHeadquartersPoolEntry, ClueMasterLead)
        .join(ClueMasterLead, ClueMasterLead.lead_key == ClueHeadquartersPoolEntry.lead_key)
        .where(*filters)
    )
    total_statement = (
        select(func.count())
        .select_from(ClueHeadquartersPoolEntry)
        .join(ClueMasterLead, ClueMasterLead.lead_key == ClueHeadquartersPoolEntry.lead_key)
        .where(*filters)
    )
    total = int(store.session.scalar(total_statement) or 0)
    rows = store.session.execute(
        statement.order_by(
            ClueHeadquartersPoolEntry.entered_at.desc(),
            ClueHeadquartersPoolEntry.headquarters_pool_entry_id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    stored_reason_values = list(
        store.session.scalars(
            select(ClueHeadquartersPoolEntry.reason)
            .join(ClueMasterLead, ClueMasterLead.lead_key == ClueHeadquartersPoolEntry.lead_key)
            .where(*scope_filters)
            .distinct()
            .order_by(ClueHeadquartersPoolEntry.reason)
        ).all()
    )
    canonical_reason_values = {
        canonical_headquarters_pool_reason(value) for value in stored_reason_values
    }
    available_reason_codes = [
        code for code in HEADQUARTERS_POOL_REASON_CODES if code in canonical_reason_values
    ]
    entry_statuses = list(
        store.session.scalars(
            select(ClueHeadquartersPoolEntry.status)
            .join(ClueMasterLead, ClueMasterLead.lead_key == ClueHeadquartersPoolEntry.lead_key)
            .where(*scope_filters)
            .distinct()
            .order_by(ClueHeadquartersPoolEntry.status)
        ).all()
    )
    normalized_order_statuses = list(
        store.session.scalars(
            select(ClueMasterLead.normalized_order_status)
            .join(
                ClueHeadquartersPoolEntry,
                ClueHeadquartersPoolEntry.lead_key == ClueMasterLead.lead_key,
            )
            .where(*scope_filters)
            .distinct()
            .order_by(ClueMasterLead.normalized_order_status)
        ).all()
    )
    city_codes = list(
        store.session.scalars(
            select(ClueMasterLead.anchor_city_code)
            .join(
                ClueHeadquartersPoolEntry,
                ClueHeadquartersPoolEntry.lead_key == ClueMasterLead.lead_key,
            )
            .where(ClueMasterLead.anchor_city_code.is_not(None))
            .where(ClueMasterLead.anchor_city_code != "")
            .where(*scope_filters)
            .distinct()
            .order_by(ClueMasterLead.anchor_city_code)
        ).all()
    )
    data = ClueHeadquartersPoolData(
        rows=[
            ClueHeadquartersPoolEntryRow(
                **_clue_headquarters_pool_entry_payload(entry, lead)
            )
            for entry, lead in rows
        ],
        pagination=_pagination(page, page_size, total),
        summary=ClueHeadquartersPoolSummary(
            current_inventory=int(
                store.session.scalar(
                    select(func.count())
                    .select_from(ClueHeadquartersPoolEntry)
                    .join(
                        ClueMasterLead,
                        ClueMasterLead.lead_key == ClueHeadquartersPoolEntry.lead_key,
                    )
                    .where(ClueHeadquartersPoolEntry.status == "active")
                    .where(*scope_filters)
                )
                or 0
            ),
            filtered_total=total,
        ),
        filter_options=ClueHeadquartersPoolFilterOptions(
            entry_statuses=entry_statuses,
            reason_codes=available_reason_codes,
            normalized_order_statuses=normalized_order_statuses,
            city_codes=city_codes,
            pool_statuses=entry_statuses,
            reasons=available_reason_codes,
            order_statuses=normalized_order_statuses,
        ),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/cycles")
def list_clue_allocation_cycles(
    cycle_mode: str | None = None,
    cycle_status: str | None = None,
    requested_date_start: date | None = None,
    requested_date_end: date | None = None,
    actor_user_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationCycle)
    cycle_scope = _cycle_scope_condition(current_user)
    if cycle_scope is not None:
        statement = statement.where(cycle_scope)
    if requested_date_start and requested_date_end and requested_date_end < requested_date_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="requested_date_end must be on or after requested_date_start",
        )
    if cycle_mode:
        statement = statement.where(ClueAllocationCycle.cycle_type == cycle_mode)
    if cycle_status:
        statement = statement.where(ClueAllocationCycle.status == cycle_status)
    if requested_date_start:
        statement = statement.where(ClueAllocationCycle.created_at >= _shanghai_day_start(requested_date_start))
    if requested_date_end:
        statement = statement.where(
            ClueAllocationCycle.created_at < _shanghai_day_start(requested_date_end + timedelta(days=1))
        )
    if actor_user_id:
        statement = statement.where(ClueAllocationCycle.actor_user_id == actor_user_id)
    total = int(store.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = store.session.scalars(
        statement.order_by(
            ClueAllocationCycle.created_at.desc(),
            ClueAllocationCycle.allocation_cycle_id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    scoped_items = _scoped_cycle_items(store.session, rows, current_user)
    data = ClueAllocationCycleData(
        rows=[
            ClueAllocationCycleRow(
                **_clue_allocation_cycle_payload(
                    row,
                    visible_items=(
                        None
                        if scoped_items is None
                        else scoped_items.get(row.allocation_cycle_id, [])
                    ),
                )
            )
            for row in rows
        ],
        pagination=_pagination(page, page_size, total),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/cycles/{cycle_id}")
def get_clue_allocation_cycle(
    cycle_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    cycle_statement = select(ClueAllocationCycle).where(
        ClueAllocationCycle.allocation_cycle_id == cycle_id
    )
    cycle_scope = _cycle_scope_condition(current_user)
    if cycle_scope is not None:
        cycle_statement = cycle_statement.where(cycle_scope)
    cycle = store.session.scalar(cycle_statement)
    if cycle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="allocation cycle not found")
    item_statement = select(ClueAllocationCycleItem).where(
        ClueAllocationCycleItem.allocation_cycle_id == cycle_id
    )
    lead_scope = _lead_scope_condition(current_user)
    if lead_scope is not None:
        item_statement = item_statement.join(
            ClueMasterLead,
            ClueMasterLead.lead_key == ClueAllocationCycleItem.lead_key,
        ).where(lead_scope)
    total = int(store.session.scalar(select(func.count()).select_from(item_statement.subquery())) or 0)
    items = store.session.scalars(
        item_statement.order_by(
            ClueAllocationCycleItem.sequence_no,
            ClueAllocationCycleItem.cycle_item_id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    scoped_items = _scoped_cycle_items(store.session, [cycle], current_user)
    data = ClueAllocationCycleDetailData(
        cycle=ClueAllocationCycleRow(
            **_clue_allocation_cycle_payload(
                cycle,
                visible_items=(
                    None
                    if scoped_items is None
                    else scoped_items.get(cycle.allocation_cycle_id, [])
                ),
            )
        ),
        items=[
            ClueAllocationCycleItemRow(**_clue_allocation_cycle_item_payload(item))
            for item in items
        ],
        pagination=_pagination(page, page_size, total),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/audit-logs")
def list_clue_allocation_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationAuditLog)
    total = int(store.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = store.session.scalars(
        statement.order_by(
            ClueAllocationAuditLog.created_at.desc(),
            ClueAllocationAuditLog.audit_log_id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    data = ClueAllocationAuditLogData(
        rows=[ClueAllocationAuditLogRow(**_clue_allocation_audit_log_payload(row)) for row in rows],
        pagination=_pagination(page, page_size, total),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/cycle-previews")
def preview_clue_allocation_cycle(
    payload: ClueAllocationCyclePreviewRequest,
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    if not current_user.is_highest_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Highest administrator access required",
        )
    store = _require_available_store(store)
    try:
        if payload.operation == "trial_rebuild":
            result = preview_rebuild_trial_allocation_cycle(
                store.session,
                source_cycle_id=payload.source_cycle_id or "",
                actor=current_user.username,
                privileged_confirmation=payload.privileged_confirmation,
                rebind_rule_version=payload.rebind_rule_version,
            )
        else:
            result = preview_trial_allocation_cycle(
                store.session,
                lead_keys=payload.lead_keys,
                actor=current_user.username,
                rebind_rule_version=payload.rebind_rule_version,
            )
    except AllocationCycleError as error:
        raise _allocation_cycle_http_error(error) from error
    data = ClueAllocationCyclePreviewData(**result)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/trial-cycles")
def execute_clue_allocation_trial(
    request: Request,
    payload: ClueAllocationCycleRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    if not current_user.is_highest_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Highest administrator access required",
        )
    if payload.confirmation_text != "确认试运行":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confirmation_text must be 确认试运行",
        )
    store = _require_available_store(store)
    try:
        preview_grant = validate_allocation_preview_grant(
            payload.preview_token,
            operation="trial",
            actor=current_user.username,
            lead_keys=payload.lead_keys,
            privileged_confirmation=payload.privileged_confirmation,
        )
        result = run_trial_allocation_cycle(
            store.session,
            lead_keys=payload.lead_keys,
            actor=current_user.username,
            actor_user_id=_stable_actor_user_id(current_user),
            actor_role_snapshot=current_user.role,
            actor_scope_snapshot={
                "mode": current_user.store_scope_mode,
                "store_ids": list(current_user.store_ids),
            },
            request_id=request_id(request),
            privileged_confirmation=payload.privileged_confirmation,
            preview_token_hash=preview_grant.token_hash,
            preview_expires_at=preview_grant.expires_at,
            idempotency_key=idempotency_key,
            expected_lead_keys=preview_grant.lead_keys,
            expected_state_snapshot=preview_grant.state_snapshot,
            rebind_rule_version=preview_grant.rebind_rule_version,
        )
        store.session.commit()
    except AllocationCycleError as error:
        store.session.rollback()
        raise _allocation_cycle_http_error(error) from error
    except Exception:
        store.session.rollback()
        raise
    data = ClueAllocationCycleExecutionData(**result)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/rebuild-cycles")
def rebuild_clue_allocation_trial(
    request: Request,
    payload: ClueAllocationCycleRebuildRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    current_user: AuthContext = Depends(get_current_user),
    store=Depends(get_data_store),
):
    if not current_user.is_highest_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Highest administrator access required",
        )
    if payload.confirmation_text != "确认重建试运行":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confirmation_text must be 确认重建试运行",
        )
    store = _require_available_store(store)
    try:
        preview_grant = validate_allocation_preview_grant(
            payload.preview_token,
            operation="trial_rebuild",
            actor=current_user.username,
            source_cycle_id=payload.source_cycle_id,
            privileged_confirmation=payload.privileged_confirmation,
        )
        result = rebuild_trial_allocation_cycle(
            store.session,
            source_cycle_id=payload.source_cycle_id,
            actor=current_user.username,
            actor_user_id=_stable_actor_user_id(current_user),
            actor_role_snapshot=current_user.role,
            actor_scope_snapshot={
                "mode": current_user.store_scope_mode,
                "store_ids": list(current_user.store_ids),
            },
            request_id=request_id(request),
            privileged_confirmation=payload.privileged_confirmation,
            preview_token_hash=preview_grant.token_hash,
            preview_expires_at=preview_grant.expires_at,
            idempotency_key=idempotency_key,
            expected_lead_keys=preview_grant.lead_keys,
            expected_state_snapshot=preview_grant.state_snapshot,
            rebind_rule_version=preview_grant.rebind_rule_version,
        )
        store.session.commit()
    except AllocationCycleError as error:
        store.session.rollback()
        raise _allocation_cycle_http_error(error) from error
    except Exception:
        store.session.rollback()
        raise
    data = ClueAllocationCycleExecutionData(**result)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


def _score_rule_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None

def _score_snapshot_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None

def _score_sidecar_rule_map(
    session,
    *,
    snapshot_run_ids: list[str],
    pinned_generation_id: str | None,
    identities: list[tuple[str, str]] | None = None,
) -> dict[tuple[str, str], str]:
    """Return sidecar rule ids visible through the shared score resolver.

    Sidecars are only candidates here.  Their partition identities are resolved
    through the same manifest/lineage reader used by all aggregate artifacts;
    rows from unrelated generations are ignored, while a tombstoned identity
    remains a claim so stale config cannot resurrect its base fact.
    """

    if not snapshot_run_ids:
        return {}
    if len(snapshot_run_ids) > SCORE_RUN_PAGE_SIZE:
        raise LineageError("score sidecar run batch exceeds the candidate page bound")
    normalized_run_ids: list[str] = []
    for value in snapshot_run_ids:
        normalized = _score_rule_value(value)
        if normalized is None:
            raise LineageError("score sidecar contains an empty run id")
        normalized_run_ids.append(normalized)
    normalized_identities: list[tuple[str, str]] = []
    if identities is None:
        raise LineageError("score sidecar query requires bounded identities")
    if not identities:
        return {}
    if len(identities) > SCORE_FACT_BATCH_SIZE:
        raise LineageError("score sidecar identity batch exceeds the fact bound")
    for run_value, store_value in identities:
        run_id = _score_rule_value(run_value)
        store_id = _score_rule_value(store_value)
        if run_id is None or store_id is None:
            raise LineageError("score sidecar contains an empty identity")
        if run_id not in normalized_run_ids:
            raise LineageError("score sidecar identity is outside the run batch")
        normalized_identities.append((run_id, store_id))
    run_params = {
        f"score_run_{index}": value
        for index, value in enumerate(normalized_run_ids)
    }
    run_placeholders = ", ".join(f":{key}" for key in run_params)
    store_clause = ""
    store_params: dict[str, str] = {}
    pair_values: list[str] = []
    for index, (run_id, store_id) in enumerate(normalized_identities):
        run_key = f"score_identity_run_{index}"
        store_key = f"score_identity_store_{index}"
        store_params[run_key] = run_id
        store_params[store_key] = store_id
        pair_values.append(f"(:{run_key}, :{store_key})")
    store_clause = " AND (snapshot_run_id, store_id) IN (" + ", ".join(pair_values) + ")"
    output: dict[tuple[str, str], _ScoreSidecarClaim] = {}
    seen_metadata: dict[tuple[str, str], tuple[date, str, str]] = {}
    last_run_id: str | None = None
    last_store_id: str | None = None
    last_generation_id: str | None = None
    last_snapshot_date = None
    last_rule_id: str | None = None
    last_partition_key: str | None = None
    while True:
        keyset_clause = ""
        keyset_params: dict[str, str] = {}
        if last_run_id is not None:
            keyset_clause = " AND ("
            keyset_clause += (
                "(snapshot_run_id, store_id, generation_id, snapshot_date, "
                "rule_version_id, partition_key) > "
                "(:score_last_run, :score_last_store, :score_last_generation, "
                ":score_last_date, :score_last_rule, :score_last_partition)"
            )
            keyset_clause += ")"
            keyset_params = {
                "score_last_run": last_run_id,
                "score_last_store": last_store_id or "",
                "score_last_generation": last_generation_id or "",
                "score_last_date": last_snapshot_date,
                "score_last_rule": last_rule_id or "",
                "score_last_partition": last_partition_key or "",
            }
        try:
            result = session.execute(
                text(
                    f"""
                    SELECT generation_id, snapshot_run_id, store_id,
                           rule_version_id, snapshot_date, partition_key
                    FROM store_score_snapshot_generation
                    WHERE snapshot_run_id IN ({run_placeholders})
                      {store_clause}
                      {keyset_clause}
                    ORDER BY snapshot_run_id, store_id, generation_id,
                             snapshot_date, rule_version_id, partition_key
                    LIMIT :score_sidecar_limit
                    """
                ),
                {
                    **run_params,
                    **store_params,
                    **keyset_params,
                    "score_sidecar_limit": SCORE_SIDECAR_BATCH_SIZE,
                },
            )
            rows = [dict(row) for row in result.mappings().all()]
        except Exception as exc:
            raise LineageError("failed to read score sidecars") from exc
        if not rows:
            break
        batch = rows
        keys: list[str] = []
        key_by_index: dict[int, str] = {}
        for index, row in enumerate(batch):
            generation_id = _score_rule_value(row.get("generation_id"))
            run_id = _score_rule_value(row.get("snapshot_run_id"))
            store_id = _score_rule_value(row.get("store_id"))
            rule_id = _score_rule_value(row.get("rule_version_id"))
            snapshot_date = _score_snapshot_date(row.get("snapshot_date"))
            stored_partition_key = _score_rule_value(row.get("partition_key"))
            if (
                generation_id is None
                or run_id is None
                or store_id is None
                or rule_id is None
                or snapshot_date is None
                or stored_partition_key is None
            ):
                raise LineageError("score sidecar contains invalid identity or rule id")
            key = canonical_score_partition_key(snapshot_date, rule_id, store_id)
            if stored_partition_key != key:
                raise LineageError("score sidecar partition key is not canonical")
            identity = (run_id, store_id)
            metadata = (snapshot_date, rule_id, stored_partition_key)
            previous_metadata = seen_metadata.get(identity)
            if previous_metadata is not None and previous_metadata != metadata:
                raise LineageError("score sidecar identity metadata conflicts")
            seen_metadata[identity] = metadata
            keys.append(key)
            key_by_index[index] = key
        resolutions = resolve_projection_partitions(
            session,
            artifact="score",
            partition_keys=keys,
            pinned_generation_id=pinned_generation_id,
        )
        for index, row in enumerate(batch):
            generation_id = _score_rule_value(row.get("generation_id"))
            run_id = _score_rule_value(row.get("snapshot_run_id"))
            store_id = _score_rule_value(row.get("store_id"))
            rule_id = _score_rule_value(row.get("rule_version_id"))
            snapshot_date = _score_snapshot_date(row.get("snapshot_date"))
            stored_partition_key = _score_rule_value(row.get("partition_key"))
            if (
                generation_id is None
                or run_id is None
                or store_id is None
                or rule_id is None
                or snapshot_date is None
                or stored_partition_key is None
            ):
                raise LineageError("score sidecar contains invalid identity or rule id")
            identity = (run_id, store_id)
            resolution = resolutions.get(key_by_index[index])
            row_generation_id = generation_id
            if resolution is None:
                continue
            visible_generation_ids = (
                resolution.lineage_generation_ids | resolution.source_generation_ids
            )
            if row_generation_id not in visible_generation_ids:
                continue
            if resolution.source_kind == "overlay":
                if resolution.actual_data_generation_id != row_generation_id:
                    continue
            elif resolution.source_kind == "tombstone":
                if resolution.nearest_manifest_owner_generation == row_generation_id:
                    raise LineageError("tombstone owner generation has score sidecar data")
            else:
                # A sidecar row owned by a generation in the pinned lineage
                # must have an authoritative overlay or tombstone manifest.
                # Treating a missing/legacy-root manifest as absent would let
                # the fact silently fall back to the run's legacy config.
                raise LineageError(
                    "in-lineage score sidecar has no authoritative manifest"
                )
            # An overlay sidecar exposes a visible rule; a tombstone sidecar
            # claims the same authoritative identity so facts cannot fall back
            # to stale run config and resurrect the hidden base row.
            previous = output.get(identity)
            claim = _ScoreSidecarClaim(
                rule_id,
                snapshot_date=snapshot_date,
                partition_key=stored_partition_key,
                generation_id=row_generation_id,
            )
            if previous is not None and (
                previous != claim
                or previous.snapshot_date != claim.snapshot_date
                or previous.partition_key != claim.partition_key
            ):
                raise LineageError("selected score run has conflicting rule versions")
            output[identity] = claim
        last = batch[-1]
        last_run_id = _score_rule_value(last.get("snapshot_run_id"))
        last_store_id = _score_rule_value(last.get("store_id"))
        last_generation_id = _score_rule_value(last.get("generation_id"))
        last_snapshot_date = _score_snapshot_date(last.get("snapshot_date"))
        last_rule_id = _score_rule_value(last.get("rule_version_id"))
        last_partition_key = _score_rule_value(last.get("partition_key"))
        if (
            last_run_id is None
            or last_store_id is None
            or last_generation_id is None
            or last_snapshot_date is None
            or last_rule_id is None
            or last_partition_key is None
        ):
            raise LineageError("score sidecar contains an invalid ordering identity")
        if len(batch) < SCORE_SIDECAR_BATCH_SIZE:
            break
    return output

def _score_run_config_rule_predicate(session, rule_version_id: str):
    """Build a cross-dialect JSON rule predicate for legacy run metadata."""

    dialect = ""
    try:
        dialect = session.get_bind().dialect.name
    except Exception:
        pass
    if dialect == "sqlite":
        return func.json_extract(
            StoreScoreSnapshotRun.config_json, "$.rule_version_id"
        ) == rule_version_id
    return StoreScoreSnapshotRun.config_json["rule_version_id"].as_string() == rule_version_id

def _score_fact_batches(
    session,
    *,
    snapshot_run_ids: list[str],
    scope_store_ids: tuple[str, ...] | None = None,
):
    """Yield bounded, deterministic score-fact batches for a run page."""

    if not snapshot_run_ids:
        return
    if len(snapshot_run_ids) > SCORE_RUN_PAGE_SIZE:
        raise LineageError("score fact run batch exceeds the candidate page bound")
    normalized_ids = [_score_rule_value(value) for value in snapshot_run_ids]
    if any(value is None for value in normalized_ids):
        raise LineageError("score fact query contains an empty run id")
    run_ids = [value for value in normalized_ids if value is not None]
    last_run_id: str | None = None
    last_score = None
    last_store_id: str | None = None
    while True:
        statement = select(StoreScoreSnapshot).where(
            StoreScoreSnapshot.snapshot_run_id.in_(run_ids)
        )
        if scope_store_ids is not None:
            statement = statement.where(
                StoreScoreSnapshot.store_id.in_(scope_store_ids)
                if scope_store_ids
                else false()
            )
        if last_run_id is not None:
            statement = statement.where(
                or_(
                    StoreScoreSnapshot.snapshot_run_id > last_run_id,
                    (
                        (StoreScoreSnapshot.snapshot_run_id == last_run_id)
                        & (StoreScoreSnapshot.composite_score < last_score)
                    ),
                    (
                        (StoreScoreSnapshot.snapshot_run_id == last_run_id)
                        & (StoreScoreSnapshot.composite_score == last_score)
                        & (StoreScoreSnapshot.store_id > last_store_id)
                    ),
                )
            )
        statement = statement.order_by(
            StoreScoreSnapshot.snapshot_run_id,
            StoreScoreSnapshot.composite_score.desc(),
            StoreScoreSnapshot.store_id,
        ).limit(SCORE_FACT_BATCH_SIZE)
        try:
            rows = list(session.scalars(statement).all())
        except LineageError:
            raise
        except Exception as exc:
            raise LineageError("failed to read score facts") from exc
        if not rows:
            return
        yield rows
        last = rows[-1]
        last_run_id = str(last.snapshot_run_id)
        last_score = last.composite_score
        last_store_id = str(last.store_id)
        if len(rows) < SCORE_FACT_BATCH_SIZE:
            return

def _score_resolve_fact_batch(
    session,
    rows: list[StoreScoreSnapshot],
    runs_by_id: dict[str, StoreScoreSnapshotRun],
    *,
    pinned_generation_id: str | None,
) -> tuple[list[tuple[StoreScoreSnapshot, bool, str | None]], dict[tuple[str, str], str]]:
    """Resolve one bounded fact batch and return visibility/effective rules."""

    if not rows:
        return [], {}
    run_ids = sorted({str(row.snapshot_run_id) for row in rows})
    sidecar_rules: dict[tuple[str, str], str] = {}
    if pinned_generation_id is not None:
        sidecar_rules = _score_sidecar_rule_map(
            session,
            snapshot_run_ids=run_ids,
            pinned_generation_id=pinned_generation_id,
            identities=[(str(row.snapshot_run_id), str(row.store_id)) for row in rows],
        )
    keys: list[str] = []
    key_by_index: dict[int, str] = {}
    for index, row in enumerate(rows):
        run = runs_by_id.get(str(row.snapshot_run_id))
        if run is None:
            raise LineageError("score fact references an unknown snapshot run")
        fact_date = _score_snapshot_date(row.snapshot_date)
        run_date = _score_snapshot_date(run.snapshot_date)
        if fact_date is None or run_date is None or fact_date != run_date:
            raise LineageError("score fact snapshot date does not match its run")
        config = run.config_json if isinstance(run.config_json, dict) else {}
        config_rule = _score_rule_value(config.get("rule_version_id"))
        identity = (str(row.snapshot_run_id), str(row.store_id))
        sidecar_claim = sidecar_rules.get(identity)
        if sidecar_claim is not None:
            if (
                sidecar_claim.snapshot_date != fact_date
                or sidecar_claim.snapshot_date != run_date
            ):
                raise LineageError("score sidecar snapshot date does not match its fact/run")
            rule_id = str(sidecar_claim)
        else:
            rule_id = config_rule
        key = canonical_score_partition_key(fact_date, rule_id, str(row.store_id))
        keys.append(key)
        key_by_index[index] = key
    resolutions = resolve_projection_partitions(
        session,
        artifact="score",
        partition_keys=keys,
        pinned_generation_id=pinned_generation_id,
    )
    resolved: list[tuple[StoreScoreSnapshot, bool, str | None]] = []
    for index, row in enumerate(rows):
        identity = (str(row.snapshot_run_id), str(row.store_id))
        run = runs_by_id[str(row.snapshot_run_id)]
        config = run.config_json if isinstance(run.config_json, dict) else {}
        config_rule = _score_rule_value(config.get("rule_version_id"))
        rule_id = sidecar_rules.get(identity, config_rule)
        if isinstance(rule_id, _ScoreSidecarClaim):
            rule_id = str(rule_id)
        resolution = resolutions.get(key_by_index[index])
        if resolution is None:
            raise LineageError("score fact partition resolution is missing")
        visible = resolution.source_kind != "tombstone"
        if visible and resolution.source_kind == "overlay" and identity not in sidecar_rules:
            # An overlay is visible only when this selected run has the exact
            # sidecar identity that points at the overlay generation.
            raise LineageError("selected score run is missing an overlay sidecar row")
        resolved.append((row, visible, rule_id))
    return resolved, sidecar_rules

def _score_candidate_page_states(
    session,
    runs: list[StoreScoreSnapshotRun],
    *,
    pinned_generation_id: str | None,
    scope_store_ids: tuple[str, ...] | None = None,
) -> dict[str, dict[str, object]]:
    """Resolve one candidate page set-wise, retaining only bounded state."""

    runs_by_id = {str(run.snapshot_run_id): run for run in runs}
    states: dict[str, dict[str, object]] = {}
    for run in runs:
        config = run.config_json if isinstance(run.config_json, dict) else {}
        states[str(run.snapshot_run_id)] = {
            "raw_count": 0,
            "visible_count": 0,
            "effective_rules": set(),
            "fallback_rule": _score_rule_value(config.get("rule_version_id")),
        }
    for rows in _score_fact_batches(
        session,
        snapshot_run_ids=list(runs_by_id),
        scope_store_ids=scope_store_ids,
    ):
        resolved_rows, _sidecar_rules = _score_resolve_fact_batch(
            session,
            rows,
            runs_by_id,
            pinned_generation_id=pinned_generation_id,
        )
        for row, visible, rule_id in resolved_rows:
            state = states[str(row.snapshot_run_id)]
            state["raw_count"] = int(state["raw_count"]) + 1
            if visible:
                state["visible_count"] = int(state["visible_count"]) + 1
                state["effective_rules"].add(rule_id)
    return states

def _score_visible_rows(
    session,
    run: StoreScoreSnapshotRun,
    *,
    pinned_generation_id: str | None,
    page: int,
    page_size: int,
    scope_store_ids: tuple[str, ...] | None = None,
) -> tuple[list[StoreScoreSnapshot], int, int, dict[str, str | None], set[str | None]]:
    """Stream one selected run and retain only the response window."""

    run_id = str(run.snapshot_run_id)
    visible: list[StoreScoreSnapshot] = []
    row_rule_ids: dict[str, str | None] = {}
    effective_rules: set[str | None] = set()
    raw_count = 0
    visible_count = 0
    offset = (page - 1) * page_size
    runs_by_id = {run_id: run}
    for rows in _score_fact_batches(
        session,
        snapshot_run_ids=[run_id],
        scope_store_ids=scope_store_ids,
    ):
        resolved_rows, _sidecar_rules = _score_resolve_fact_batch(
            session,
            rows,
            runs_by_id,
            pinned_generation_id=pinned_generation_id,
        )
        raw_count += len(rows)
        for row, is_visible, rule_id in resolved_rows:
            if not is_visible:
                continue
            effective_rules.add(rule_id)
            if offset <= visible_count < offset + page_size:
                visible.append(row)
                row_rule_ids[str(row.snapshot_id)] = rule_id
            visible_count += 1
    return visible, raw_count, visible_count, row_rule_ids, effective_rules

def _score_run_pages(session, statement, *, page_size: int = 100):
    """Yield deterministic keyset pages without loading run history at once."""

    if page_size < 1 or page_size > SCORE_RUN_PAGE_SIZE:
        raise LineageError("score run page size exceeds the candidate bound")
    base_statement = statement.order_by(None)
    last_computed_at = None
    last_snapshot_run_id = None
    while True:
        page_statement = base_statement
        if last_computed_at is not None:
            page_statement = page_statement.where(
                or_(
                    StoreScoreSnapshotRun.computed_at < last_computed_at,
                    (
                        StoreScoreSnapshotRun.computed_at == last_computed_at
                    )
                    & (StoreScoreSnapshotRun.snapshot_run_id < last_snapshot_run_id),
                )
            )
        page_statement = page_statement.order_by(
            StoreScoreSnapshotRun.computed_at.desc(),
            StoreScoreSnapshotRun.snapshot_run_id.desc(),
        ).limit(page_size)
        try:
            page = list(session.scalars(page_statement).all())
        except LineageError:
            raise
        except Exception as exc:
            raise LineageError("failed to read score run candidates") from exc
        if not page:
            return
        yield page
        last = page[-1]
        last_computed_at = last.computed_at
        last_snapshot_run_id = last.snapshot_run_id
        if len(page) < page_size:
            return


@router.get("/clue-allocation/store-scores")
def list_store_score_snapshots(
    snapshot_run_id: str | None = None,
    snapshot_date: date | None = None,
    run_mode: str | None = None,
    rule_version_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthContext = Depends(_require_clue_admin_context),
    _username: str | None = Depends(lambda: None),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    scope_store_ids = (
        _clue_scope_store_ids(current_user)
        if isinstance(current_user, AuthContext)
        else None
    )
    requested_rule_version_id = _score_rule_value(rule_version_id)
    try:
        try:
            pinned_generation_id = store._pinned_aggregate_generation()
        except AttributeError:
            pinned_generation_id = active_generation_id(store.session)
        if pinned_generation_id is not None:
            pinned_generation_id = _score_rule_value(pinned_generation_id)
            if pinned_generation_id is None:
                raise LineageError("pinned score generation id is empty")

        run_statement = select(StoreScoreSnapshotRun)
        if scope_store_ids is not None:
            run_statement = run_statement.where(
                exists(
                    select(1).where(
                        StoreScoreSnapshot.snapshot_run_id
                        == StoreScoreSnapshotRun.snapshot_run_id,
                        (
                            StoreScoreSnapshot.store_id.in_(scope_store_ids)
                            if scope_store_ids
                            else false()
                        ),
                    )
                )
            )
        if snapshot_run_id:
            run_statement = run_statement.where(
                StoreScoreSnapshotRun.snapshot_run_id == snapshot_run_id
            )
        elif snapshot_date:
            run_statement = run_statement.where(
                StoreScoreSnapshotRun.snapshot_date == snapshot_date
            )
        if run_mode:
            run_statement = run_statement.where(
                StoreScoreSnapshotRun.run_mode == run_mode
            )

        if not snapshot_run_id and requested_rule_version_id is not None:
            config_predicate = _score_run_config_rule_predicate(
                store.session, requested_rule_version_id
            )
            if pinned_generation_id is not None:
                sidecar_exists = select(1).where(
                    (
                        StoreScoreSnapshotGeneration.snapshot_run_id
                        == StoreScoreSnapshotRun.snapshot_run_id
                    )
                    & (
                        StoreScoreSnapshotGeneration.rule_version_id
                        == requested_rule_version_id
                    )
                ).exists()
                run_statement = run_statement.where(
                    or_(config_predicate, sidecar_exists)
                )
            else:
                run_statement = run_statement.where(config_predicate)

        candidate_page_size = 1 if snapshot_run_id else SCORE_RUN_PAGE_SIZE
        candidate_pages = _score_run_pages(
            store.session,
            run_statement,
            page_size=candidate_page_size,
        )
        run = None
        run_rule_id: str | None = None
        while run is None:
            try:
                candidate_page = next(candidate_pages)
            except StopIteration:
                break
            candidate_state_kwargs = {
                "pinned_generation_id": pinned_generation_id,
            }
            if scope_store_ids is not None:
                candidate_state_kwargs["scope_store_ids"] = scope_store_ids
            states = _score_candidate_page_states(
                store.session,
                candidate_page,
                **candidate_state_kwargs,
            )
            for candidate in candidate_page:
                state = states[str(candidate.snapshot_run_id)]
                raw_count = int(state["raw_count"])
                visible_count = int(state["visible_count"])
                effective_rules = set(state["effective_rules"])
                if raw_count > 0 and visible_count == 0:
                    continue
                if not effective_rules and raw_count == 0:
                    fallback_rule = state["fallback_rule"]
                    if fallback_rule is not None:
                        effective_rules = {fallback_rule}
                if len(effective_rules) > 1:
                    raise LineageError(
                        "selected score run has conflicting rule versions"
                    )
                if (
                    requested_rule_version_id is not None
                    and effective_rules != {requested_rule_version_id}
                ):
                    continue
                run = candidate
                run_rule_id = next(iter(effective_rules), None)
                break

        visible_snapshots: list[StoreScoreSnapshot] = []
        row_rule_ids: dict[str, str | None] = {}
        total = 0
        if run is not None:
            visible_row_kwargs = {
                "pinned_generation_id": pinned_generation_id,
                "page": page,
                "page_size": page_size,
            }
            if scope_store_ids is not None:
                visible_row_kwargs["scope_store_ids"] = scope_store_ids
            (
                visible_snapshots,
                raw_count,
                visible_total,
                row_rule_ids,
                effective_rules,
            ) = _score_visible_rows(
                store.session,
                run,
                **visible_row_kwargs,
            )
            if raw_count > 0 and visible_total == 0:
                raise LineageError("selected score run has no visible rows")
            if len(effective_rules) > 1:
                raise LineageError(
                    "selected score run has conflicting rule versions"
                )
            if effective_rules:
                run_rule_id = next(iter(effective_rules))
            if not effective_rules and raw_count == 0 and run_rule_id is not None:
                effective_rules = {run_rule_id}
            if (
                requested_rule_version_id is not None
                and effective_rules != {requested_rule_version_id}
            ):
                run = None
            else:
                total = visible_total

        if run is None:
            data = StoreScoreSnapshotData(
                run=None,
                rows=[],
                pagination=_pagination(page, page_size, 0),
            )
        else:
            data = StoreScoreSnapshotData(
                run=StoreScoreSnapshotRunData(
                    **_store_score_run_payload(
                        run,
                        rule_version_id=run_rule_id,
                        visible_snapshot_count=(
                            total if scope_store_ids is not None else None
                        ),
                        hide_triggered_by=scope_store_ids is not None,
                    )
                ),
                rows=[
                    StoreScoreSnapshotRow(
                        **_store_score_snapshot_payload(
                            row,
                            rule_version_id=row_rule_ids.get(
                                str(row.snapshot_id), run_rule_id
                            ),
                        )
                    )
                    for row in visible_snapshots
                ],
                pagination=_pagination(page, page_size, total),
            )
        return {
            "data": dump_model(data),
            "meta": {"generated_at": generated_at(), "source": "postgres"},
        }
    except LineageError:
        raise
    except Exception as exc:
        raise LineageError("failed to read store score snapshots") from exc


@router.post("/clue-allocation/store-scores/refresh")
def refresh_store_scores(
    request: Request,
    payload: StoreScoreRefreshRequest,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    version = store.session.get(ClueAllocationRuleVersion, payload.rule_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="线索分配规则版本不存在")
    if version.status != "published":
        raise HTTPException(status_code=409, detail="仅已发布规则版本可以刷新门店评分")
    result = refresh_store_score_snapshots(
        store.session,
        run_mode="manual",
        rule_version_id=version.rule_version_id,
        triggered_by=current_user.username,
    )
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="store_scores_refreshed",
        after_snapshot={
            "snapshot_run_id": str(result["snapshot_run_id"]),
            "snapshot_count": int(result["snapshots"]),
            "rule_version_id": version.rule_version_id,
        },
    )
    store.session.commit()
    data = StoreScoreRefreshResult(
        snapshot_run_id=str(result["snapshot_run_id"]),
        snapshot_count=int(result["snapshots"]),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/rules")
def list_clue_allocation_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationRule)
    rule_scope = _rule_scope_condition(current_user)
    if rule_scope is not None:
        statement = statement.where(rule_scope)
    total = int(store.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = store.session.scalars(
        statement.order_by(ClueAllocationRule.scope_type, ClueAllocationRule.scope_key)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    data = ClueAllocationRuleListData(
        rows=[ClueAllocationRuleData(**_clue_allocation_rule_payload(row)) for row in rows],
        pagination=_pagination(page, page_size, total),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/rules/{rule_id}")
def get_clue_allocation_rule(
    rule_id: str,
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationRule).where(ClueAllocationRule.rule_id == rule_id)
    rule_scope = _rule_scope_condition(current_user)
    if rule_scope is not None:
        statement = statement.where(rule_scope)
    rule = store.session.scalar(statement)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clue allocation rule was not found")
    versions = store.session.scalars(
        select(ClueAllocationRuleVersion)
        .where(ClueAllocationRuleVersion.rule_id == rule.rule_id)
        .order_by(ClueAllocationRuleVersion.version_no.desc())
    ).all()
    data = ClueAllocationRuleDetailData(
        rule=ClueAllocationRuleData(**_clue_allocation_rule_payload(rule)),
        versions=[
            ClueAllocationRuleVersionData(**_clue_allocation_rule_version_payload(store.session, version))
            for version in versions
        ],
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/rules", status_code=status.HTTP_201_CREATED)
def create_clue_allocation_rule_route(
    request: Request,
    payload: ClueAllocationRuleCreateRequest,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        rule = create_clue_allocation_rule(
            store.session,
            name=payload.name,
            scope_type=payload.scope.scope_type,
            city_code=payload.scope.city_code,
            store_group_id=payload.scope.store_group_id,
            anchor_store_id=payload.scope.anchor_store_id,
            created_by=current_user.username,
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    rule_snapshot = _clue_allocation_rule_payload(rule)
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="rule_created",
        after_snapshot=rule_snapshot,
    )
    store.session.commit()
    data = ClueAllocationRuleData(**rule_snapshot)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/rules/{rule_id}/versions", status_code=status.HTTP_201_CREATED)
def create_clue_allocation_rule_version_route(
    rule_id: str,
    request: Request,
    payload: ClueAllocationRuleVersionWrite,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        version = create_rule_version(
            store.session,
            rule_id,
            created_by=current_user.username,
            **payload.model_dump(),
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    version_snapshot = _clue_allocation_rule_version_payload(store.session, version)
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="rule_version_created",
        after_snapshot=version_snapshot,
        detail={"rule_id": rule_id},
    )
    store.session.commit()
    data = ClueAllocationRuleVersionData(**version_snapshot)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/clue-allocation/rule-versions/{rule_version_id}")
def update_clue_allocation_rule_version_route(
    rule_version_id: str,
    request: Request,
    payload: ClueAllocationRuleVersionWrite,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    existing_version = store.session.get(ClueAllocationRuleVersion, rule_version_id)
    before_snapshot = (
        _clue_allocation_rule_version_payload(store.session, existing_version)
        if existing_version is not None
        else None
    )
    try:
        version = update_rule_version(
            store.session,
            rule_version_id,
            updated_by=current_user.username,
            **payload.model_dump(),
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    after_snapshot = _clue_allocation_rule_version_payload(store.session, version)
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="rule_version_updated",
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )
    store.session.commit()
    data = ClueAllocationRuleVersionData(**after_snapshot)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.delete("/clue-allocation/rule-versions/{rule_version_id}")
def delete_clue_allocation_rule_version_route(
    rule_version_id: str,
    request: Request,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    existing_version = store.session.get(ClueAllocationRuleVersion, rule_version_id)
    before_snapshot = (
        _clue_allocation_rule_version_payload(store.session, existing_version)
        if existing_version is not None
        else None
    )
    try:
        delete_rule_version(store.session, rule_version_id)
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="rule_version_deleted",
        before_snapshot=before_snapshot,
        detail={"rule_version_id": rule_version_id},
    )
    store.session.commit()
    data = ClueAllocationRuleVersionDeleteData(rule_version_id=rule_version_id, deleted=True)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/rule-versions/{rule_version_id}/publish")
def publish_clue_allocation_rule_version_route(
    rule_version_id: str,
    request: Request,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    existing_version = store.session.get(ClueAllocationRuleVersion, rule_version_id)
    before_snapshot = (
        _clue_allocation_rule_version_payload(store.session, existing_version)
        if existing_version is not None
        else None
    )
    try:
        version = publish_rule_version(
            store.session,
            rule_version_id,
            published_by=current_user.username,
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    after_snapshot = _clue_allocation_rule_version_payload(store.session, version)
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="rule_version_published",
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )
    store.session.commit()
    data = ClueAllocationRuleVersionData(**after_snapshot)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/rule-versions/{rule_version_id}/retire")
def retire_clue_allocation_rule_version_route(
    rule_version_id: str,
    request: Request,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    existing_version = store.session.get(ClueAllocationRuleVersion, rule_version_id)
    before_snapshot = (
        _clue_allocation_rule_version_payload(store.session, existing_version)
        if existing_version is not None
        else None
    )
    try:
        version = retire_rule_version(
            store.session,
            rule_version_id,
            retired_by=current_user.username,
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    after_snapshot = _clue_allocation_rule_version_payload(store.session, version)
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="rule_version_retired",
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )
    store.session.commit()
    data = ClueAllocationRuleVersionData(**after_snapshot)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/store-groups")
def list_clue_store_groups(
    current_user: AuthContext = Depends(_require_clue_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueStoreGroup)
    scope_store_ids = _clue_scope_store_ids(current_user)
    if scope_store_ids is not None:
        statement = statement.where(
            exists(
                select(1).where(
                    ClueStoreGroupMember.store_group_id == ClueStoreGroup.store_group_id,
                    ClueStoreGroupMember.store_id.in_(scope_store_ids),
                )
            )
            if scope_store_ids
            else false()
        )
    groups = store.session.scalars(
        statement.order_by(ClueStoreGroup.group_name, ClueStoreGroup.store_group_id)
    ).all()
    data = ClueStoreGroupListData(
        rows=[
            ClueStoreGroupData(
                **_clue_store_group_payload(
                    store.session,
                    group,
                    visible_store_ids=scope_store_ids,
                )
            )
            for group in groups
        ]
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/store-groups", status_code=status.HTTP_201_CREATED)
def create_clue_store_group_route(
    request: Request,
    payload: ClueStoreGroupCreateRequest,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        group = create_store_group(
            store.session,
            name=payload.name,
            member_store_ids=payload.member_store_ids,
            created_by=current_user.username,
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    group_snapshot = _clue_store_group_payload(store.session, group)
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="store_group_created",
        after_snapshot=group_snapshot,
    )
    store.session.commit()
    data = ClueStoreGroupData(**group_snapshot)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/clue-allocation/store-groups/{store_group_id}/members")
def replace_clue_store_group_members_route(
    store_group_id: str,
    request: Request,
    payload: ClueStoreGroupMembersUpdate,
    current_user: AuthContext = Depends(_require_clue_super_admin_context),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    existing_group = store.session.get(ClueStoreGroup, store_group_id)
    before_snapshot = (
        _clue_store_group_payload(store.session, existing_group)
        if existing_group is not None
        else None
    )
    try:
        group = replace_store_group_members(
            store.session,
            store_group_id,
            member_store_ids=payload.member_store_ids,
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    after_snapshot = _clue_store_group_payload(store.session, group)
    _record_clue_admin_audit(
        store.session,
        request=request,
        current_user=current_user,
        event_type="store_group_members_updated",
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )
    store.session.commit()
    data = ClueStoreGroupData(**after_snapshot)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/product-type-visibility")
def get_product_type_visibility(
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = ProductTypeVisibilityData(**store.product_type_visibility())
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/product-type-visibility")
def update_product_type_visibility(
    payload: ProductTypeVisibilityUpdate,
    username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    if payload.enabled and not payload.visible_product_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one product type is required when visibility control is enabled",
        )
    if (
        payload.enabled
        and payload.default_product_type != "all"
        and payload.default_product_type not in set(payload.visible_product_types)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Default product type must be visible when visibility control is enabled",
        )
    data = ProductTypeVisibilityData(
        **store.save_product_type_visibility(
            enabled=payload.enabled,
            visible_product_scopes=payload.visible_product_scopes,
            visible_product_types=payload.visible_product_types,
            default_product_type=payload.default_product_type,
            updated_by=username,
        )
    )
    store.session.commit()
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/product-sync-runs")
def list_product_sync_runs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200, alias="pageSize"),
    run_status: str | None = Query(default=None, alias="status"),
    mode: str | None = None,
    started_from: datetime | None = Query(default=None, alias="startedFrom"),
    started_to: datetime | None = Query(default=None, alias="startedTo"),
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    conditions = [JobRun.job_name == PRODUCT_SYNC_JOB_NAME]
    if run_status:
        normalized_status = run_status.strip().lower()
        if normalized_status not in {"queued", "running", "success", "failed", "partial"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid product sync status",
            )
        conditions.append(JobRun.status == normalized_status)
    if mode:
        normalized_mode = mode.strip().upper()
        if normalized_mode not in {"INCREMENTAL", "FULL"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid product sync mode",
            )
        conditions.append(JobRun.metadata_json["mode"].as_string() == normalized_mode)
    if started_from is not None:
        conditions.append(JobRun.started_at >= started_from)
    if started_to is not None:
        conditions.append(JobRun.started_at <= started_to)

    total = store.session.scalar(
        select(func.count()).select_from(JobRun).where(*conditions)
    ) or 0
    rows = list(
        store.session.scalars(
            select(JobRun)
            .where(*conditions)
            .order_by(JobRun.started_at.desc(), JobRun.job_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return _product_sync_success(
        request,
        {
            "list": [_product_sync_run_item(store.session, row) for row in rows],
            "total": total,
            "page": page,
            "pageSize": page_size,
        },
    )


@router.post("/product-sync-runs")
def create_product_sync_run(
    payload: ProductSyncRunRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key is required",
        )
    key_hash = sha256(normalized_key.encode("utf-8")).hexdigest()
    request_hash = _canonical_payload_sha256(
        {"mode": payload.mode, "reason": payload.reason}
    )
    existing = _find_product_sync_job_by_idempotency_hash(store.session, key_hash)
    if existing is not None:
        metadata = existing.metadata_json or {}
        if metadata.get("request_payload_sha256") != request_hash:
            raise _product_sync_error(
                request,
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency-Key was already used with a different request",
            )
        return _product_sync_success(
            request,
            {
                "syncRunId": existing.job_id,
                "mode": str(metadata.get("mode") or payload.mode).upper(),
                "status": "QUEUED",
            },
        )

    active = store.session.scalar(
        select(JobRun)
        .where(JobRun.job_name == PRODUCT_SYNC_JOB_NAME)
        .where(JobRun.status.in_(("queued", "running")))
        .order_by(JobRun.started_at.desc(), JobRun.job_id.desc())
        .limit(1)
    )
    if active is not None:
        raise _product_sync_error(
            request,
            status.HTTP_409_CONFLICT,
            "PRODUCT_SYNC_ALREADY_ACTIVE",
            "A product sync run is already queued or running",
        )

    job_id = f"product-sync-{uuid4().hex}"
    try:
        queued_job = queue_job_run(
            store.session,
            job_id,
            PRODUCT_SYNC_JOB_NAME,
            metadata_json={
                "mode": payload.mode,
                "reason": payload.reason,
                "idempotency_key_hash": key_hash,
                "request_payload_sha256": request_hash,
                "observed_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "unchanged_count": 0,
                "phase_counts": {},
                "next_cursor_masked": None,
                "error_code": None,
                "retryable": False,
            },
        )
        queued_job.idempotency_key_hash = key_hash
        store.session.commit()
    except IntegrityError as exc:
        store.session.rollback()
        concurrent = _find_product_sync_job_by_idempotency_hash(
            store.session,
            key_hash,
        )
        if concurrent is not None:
            metadata = concurrent.metadata_json or {}
            if metadata.get("request_payload_sha256") != request_hash:
                raise _product_sync_error(
                    request,
                    status.HTTP_409_CONFLICT,
                    "IDEMPOTENCY_KEY_REUSED",
                    "Idempotency-Key was already used with a different request",
                ) from exc
            return _product_sync_success(
                request,
                {
                    "syncRunId": concurrent.job_id,
                    "mode": str(metadata.get("mode") or payload.mode).upper(),
                    "status": "QUEUED",
                },
            )
        raise _product_sync_error(
            request,
            status.HTTP_409_CONFLICT,
            "PRODUCT_SYNC_ALREADY_ACTIVE",
            "A product sync run is already queued or running",
        ) from exc
    background_tasks.add_task(run_product_sync_job, job_id=job_id)
    return _product_sync_success(
        request,
        {"syncRunId": job_id, "mode": payload.mode, "status": "QUEUED"},
    )


@router.get("/product-sync-runs/{sync_run_id}")
def get_product_sync_run(
    sync_run_id: str,
    request: Request,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    job = store.session.get(JobRun, sync_run_id)
    if job is None or job.job_name != PRODUCT_SYNC_JOB_NAME:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product sync run not found")
    affected_skus = list(
        store.session.scalars(
            select(SkuProductSyncHistory.sku_id)
            .where(SkuProductSyncHistory.sync_run_id == sync_run_id)
            .distinct()
            .order_by(SkuProductSyncHistory.sku_id)
            .limit(20)
        )
    )
    issue_count = store.session.scalar(
        select(func.count())
        .select_from(DataQualityIssue)
        .where(DataQualityIssue.source_run_id == sync_run_id)
    ) or 0
    metadata = job.metadata_json or {}
    return _product_sync_success(
        request,
        {
            "run": _product_sync_run_item(store.session, job),
            "phaseCounts": metadata.get("phase_counts") or {},
            "affectedSkuSample": affected_skus,
            "dataQualityIssueCount": issue_count,
            "retryable": bool(metadata.get("retryable", False)),
        },
    )


@router.get("/sku-products/{sku_id}/sync-history")
def list_sku_product_sync_history(
    sku_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200, alias="pageSize"),
    observed_from: datetime | None = Query(default=None, alias="observedFrom"),
    observed_to: datetime | None = Query(default=None, alias="observedTo"),
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    conditions = [SkuProductSyncHistory.sku_id == sku_id]
    if observed_from is not None:
        conditions.append(SkuProductSyncHistory.observed_at >= observed_from)
    if observed_to is not None:
        conditions.append(SkuProductSyncHistory.observed_at <= observed_to)
    total = store.session.scalar(
        select(func.count()).select_from(SkuProductSyncHistory).where(*conditions)
    ) or 0
    rows = list(
        store.session.scalars(
            select(SkuProductSyncHistory)
            .where(*conditions)
            .order_by(
                SkuProductSyncHistory.observed_at.desc(),
                SkuProductSyncHistory.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return _product_sync_success(
        request,
        {
            "list": [_sku_sync_history_item(row) for row in rows],
            "total": total,
            "page": page,
            "pageSize": page_size,
        },
    )


@router.get("/sync")
def get_sync_admin(
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    data = _sync_admin_data(store)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/sync/config")
def update_sync_config(
    payload: SyncConfigUpdate,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    config = save_sync_config(store.session, dump_model(payload))
    config_data = config.as_dict()
    schedule = _sync_schedule(store.session, config_data)
    data = SyncAdminData(
        config=SyncConfigData(**config_data),
        progress=_sync_progress(store.session, config_data),
        schedule=schedule,
        worker_status=_sync_worker_status(store.session, config_data, schedule),
        jobs=store.recent_jobs(20),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/sync/run")
def run_sync_now(
    payload: ManualSyncRequest,
    background_tasks: BackgroundTasks,
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    start, end = _manual_window(payload)
    job_id = f"manual-{payload.target}-{uuid4().hex[:12]}"
    background_tasks.add_task(
        run_manual_sync_job,
        job_id=job_id,
        target=payload.target,
        start=start,
        end=end,
    )
    data = ManualSyncResult(
        job_id=job_id,
        target=payload.target,
        window=SyncWindowData(
            start=start.isoformat(),
            end=end.isoformat(),
            timezone="Asia/Shanghai",
        ),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


def _product_sync_run_item(session, job: JobRun) -> dict[str, object]:
    metadata = job.metadata_json or {}
    latest_successful_synced_at = session.scalar(
        select(func.max(DimSkuProductRule.last_synced_at)).where(
            DimSkuProductRule.sync_run_id == job.job_id
        )
    )
    return {
        "syncRunId": job.job_id,
        "mode": str(metadata.get("mode") or "INCREMENTAL").upper(),
        "status": job.status.upper(),
        "startedAt": job.started_at,
        "finishedAt": job.finished_at,
        "observedCount": _non_negative_int(metadata.get("observed_count")),
        "insertedCount": _non_negative_int(metadata.get("inserted_count")),
        "updatedCount": _non_negative_int(metadata.get("updated_count")),
        "unchangedCount": _non_negative_int(metadata.get("unchanged_count")),
        "skippedCount": _non_negative_int(metadata.get("skipped_count")),
        "failedCount": max(job.failed_count or 0, 0),
        "latestSuccessfulSyncedAt": latest_successful_synced_at,
        "nextCursorMasked": metadata.get("next_cursor_masked"),
        "errorCode": metadata.get("error_code"),
        "errorMessage": sanitize_error_message(job.error_message),
    }


def _sku_sync_history_item(row: SkuProductSyncHistory) -> dict[str, object]:
    return {
        "snapshotId": row.snapshot_id,
        "syncRunId": row.sync_run_id,
        "skuId": row.sku_id,
        "productId": row.product_id,
        "spuId": row.spu_id,
        "skuName": row.sku_name,
        "productName": row.product_name,
        "creatorAccountId": row.creator_account_id,
        "creatorAccountName": row.creator_account_name,
        "ownerAccountId": row.owner_account_id,
        "ownerAccountName": row.owner_account_name,
        "productStatusRaw": row.product_status_raw,
        "productStatus": row.product_status_normalized,
        "productUpdatedAt": row.product_updated_at,
        "syncStatus": row.sync_status,
        "syncError": row.sync_error,
        "payloadSha256": row.payload_sha256,
        "observedAt": row.observed_at,
    }


def _camel_pagination(page: int, page_size: int, total: int) -> dict[str, int]:
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": max(1, (total + page_size - 1) // page_size),
    }


def _find_product_sync_job_by_idempotency_hash(
    session,
    key_hash: str,
) -> JobRun | None:
    current = session.scalar(
        select(JobRun)
        .where(JobRun.job_name == PRODUCT_SYNC_JOB_NAME)
        .where(JobRun.idempotency_key_hash == key_hash)
        .order_by(JobRun.started_at.desc(), JobRun.job_id.desc())
        .limit(1)
    )
    if current is not None:
        return current

    legacy_jobs = session.scalars(
        select(JobRun)
        .where(JobRun.job_name == PRODUCT_SYNC_JOB_NAME)
        .where(JobRun.idempotency_key_hash.is_(None))
        .order_by(JobRun.started_at.desc(), JobRun.job_id.desc())
    )
    return next(
        (
            job
            for job in legacy_jobs
            if (job.metadata_json or {}).get("idempotency_key_hash") == key_hash
        ),
        None,
    )


def _product_sync_request_id(request: Request) -> str:
    existing = getattr(request.state, "product_sync_request_id", None)
    if existing:
        return existing
    provided = (request.headers.get("X-Request-ID") or "").strip()
    if provided and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", provided):
        request_id = provided
    else:
        request_id = f"req_{uuid4().hex}"
    request.state.product_sync_request_id = request_id
    return request_id


def _product_sync_success(request: Request, data):
    return {
        "data": data,
        "meta": {
            "generatedAt": generated_at(),
            "source": "postgres",
            "requestId": _product_sync_request_id(request),
        },
    }


def _product_sync_error(
    request: Request,
    http_status: int,
    code: str,
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={
            "code": code,
            "message": message,
            "errors": [],
            "requestId": _product_sync_request_id(request),
        },
    )


def _canonical_payload_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _sync_admin_data(store) -> SyncAdminData:
    config = load_sync_config(store.session)
    config_data = config.as_dict()
    schedule = _sync_schedule(store.session, config_data)
    return SyncAdminData(
        config=SyncConfigData(**config_data),
        progress=_sync_progress(store.session, config_data),
        schedule=schedule,
        worker_status=_sync_worker_status(store.session, config_data, schedule),
        jobs=store.recent_jobs(20),
    )


def _account_row(session, user: User) -> AccountRow:
    rows = session.execute(
        select(UserStoreScope.store_id, DimStore.store_name)
        .join(DimStore, DimStore.store_id == UserStoreScope.store_id)
        .where(UserStoreScope.user_id == user.user_id)
        .order_by(DimStore.store_name, UserStoreScope.store_id)
    ).all()
    allow, deny = user_override_sets(session, user.user_id)
    return AccountRow(
        user_id=user.user_id,
        username=user.username,
        external_account_id=user.external_account_id,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        store_scope_mode=user.store_scope_mode,
        is_initialized=user.is_initialized,
        stores=[
            AccountStoreScopeRow(store_id=row.store_id, store_name=row.store_name)
            for row in rows
        ],
        default_page_keys=list(role_default_page_keys(session, user.role)),
        extra_allow=sorted(allow),
        extra_deny=sorted(deny),
        effective_page_keys=list(effective_page_keys(session, user)),
        inherits_role_defaults=not allow and not deny,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _unactivated_store_account_rows(
    session,
    *,
    q: str | None = None,
) -> list[UnactivatedStoreAccountRow]:
    stores = (
        session.execute(
            select(DimStore)
            .where(DimStore.is_active.is_(True))
            .order_by(DimStore.store_name, DimStore.store_id)
        )
        .scalars()
        .all()
    )
    store_ids = [store.store_id for store in stores if store.store_id]
    if not store_ids:
        return []

    activated_store_ids = set(
        session.execute(
            select(UserStoreScope.store_id)
            .join(User, User.user_id == UserStoreScope.user_id)
            .where(User.role == "store")
            .where(User.is_initialized.is_(True))
            .where(UserStoreScope.store_id.in_(store_ids))
        )
        .scalars()
        .all()
    )
    activated_store_ids.update(
        session.execute(
            select(User.external_account_id)
            .where(User.role == "store")
            .where(User.is_initialized.is_(True))
            .where(User.external_account_id.in_(store_ids))
        )
        .scalars()
        .all()
    )

    account_ids_by_store: dict[str, set[str]] = {
        store_id: {store_id} for store_id in store_ids
    }
    for account_id, store_id in session.execute(
        select(DimAwemeAccount.account_id, DimAwemeAccount.store_id).where(
            DimAwemeAccount.store_id.in_(store_ids)
        )
    ).all():
        if account_id and store_id:
            account_ids_by_store.setdefault(store_id, {store_id}).add(account_id)

    poi_ids_by_store: dict[str, set[str]] = {store_id: set() for store_id in store_ids}
    poi_names_by_store: dict[str, set[str]] = {store_id: set() for store_id in store_ids}
    for store_id, poi_id, poi_name in session.execute(
        select(
            DimStorePoiMapping.store_id,
            DimStorePoiMapping.poi_id,
            DimStorePoiMapping.poi_name,
        ).where(DimStorePoiMapping.store_id.in_(store_ids))
    ).all():
        if store_id and poi_id:
            poi_ids_by_store.setdefault(store_id, set()).add(poi_id)
        if store_id and poi_name:
            poi_names_by_store.setdefault(store_id, set()).add(poi_name)

    normalized_query = normalize_account_value(q).lower()
    rows: list[UnactivatedStoreAccountRow] = []
    for store in stores:
        if store.store_id in activated_store_ids:
            continue

        account_ids = sorted(account_ids_by_store.get(store.store_id, {store.store_id}))
        poi_ids = sorted(poi_ids_by_store.get(store.store_id, set()))
        poi_names = sorted(poi_names_by_store.get(store.store_id, set()))
        if normalized_query:
            haystack = [store.store_id, *account_ids, *poi_ids]
            if not any(normalized_query in value.lower() for value in haystack if value):
                continue

        rows.append(
            UnactivatedStoreAccountRow(
                store_id=store.store_id,
                store_name=store.store_name or "",
                certified_subject_name=store.certified_subject_name or "",
                account_ids=account_ids,
                poi_ids=poi_ids,
                poi_names=poi_names,
            )
        )
    return rows


def _feedback_conditions(
    *,
    category: str | None,
    q: str | None,
) -> list:
    conditions = []
    if category:
        if category not in FEEDBACK_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid feedback category",
            )
        conditions.append(UserFeedbackSubmission.category == category)
    normalized_query = (q or "").strip()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        conditions.append(
            or_(
                UserFeedbackSubmission.content.ilike(pattern),
                UserFeedbackSubmission.contact.ilike(pattern),
                UserFeedbackSubmission.page_path.ilike(pattern),
                UserFeedbackSubmission.username.ilike(pattern),
            )
        )
    return conditions


def _feedback_status_condition(feedback_status: str | None) -> list:
    if not feedback_status:
        return []
    if feedback_status not in FEEDBACK_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid feedback status",
        )
    return [UserFeedbackSubmission.status == feedback_status]


def _feedback_row(row: UserFeedbackSubmission) -> FeedbackRow:
    return FeedbackRow(
        feedback_id=row.feedback_id,
        category=row.category,
        content=row.content,
        contact=row.contact,
        page_path=row.page_path,
        user_id=row.user_id,
        username=row.username,
        user_role=row.user_role,
        status=row.status,
        created_at=row.created_at,
    )


def _validate_password_payload(
    password: str | None, password_confirm: str | None, *, required: bool
) -> None:
    if not password and not password_confirm and not required:
        return
    if not password or not password_confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password and confirmation are required",
        )
    if password != password_confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password confirmation does not match",
        )


def _ensure_unique_user_fields(
    session,
    *,
    username: str,
    external_account_id: str | None,
    exclude_user_id: str | None,
) -> None:
    username = normalize_account_value(username)
    external_account_id = _optional_account_value(external_account_id)
    clauses = [User.username == username]
    if external_account_id:
        clauses.append(User.external_account_id == external_account_id)
    query = select(User).where(or_(*clauses))
    for user in session.execute(query).scalars().all():
        if user.user_id != exclude_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Account identifier already exists",
            )


def _ensure_store_ids_exist(session, store_ids: list[str]) -> None:
    if not store_ids:
        return
    unique_store_ids = sorted(set(store_ids))
    existing = set(
        session.execute(
            select(DimStore.store_id).where(DimStore.store_id.in_(unique_store_ids))
        ).scalars().all()
    )
    missing = [store_id for store_id in unique_store_ids if store_id not in existing]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown store_id: {', '.join(missing)}",
        )


def _require_account_manager(actor: AuthContext) -> None:
    if actor.role not in {"highest_admin", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account management access required",
        )


def _ensure_actor_can_manage_role(actor: AuthContext, role: str) -> None:
    if actor.is_highest_admin:
        return
    if actor.role == "admin" and role == "store":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Administrators can manage store accounts only",
    )


def _ensure_actor_can_manage_user(actor: AuthContext, user: User) -> None:
    if actor.is_highest_admin:
        return
    if actor.role == "admin" and user.role == "store":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Administrators can manage store accounts only",
    )


def _ensure_actor_can_manage_role_defaults(actor: AuthContext, role: str) -> None:
    if role not in {"admin", "store"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Highest administrator permissions are fixed",
        )
    if actor.is_highest_admin or (actor.role == "admin" and role == "store"):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Role permission management access required",
    )


def _normalized_scope_mode(role: str, scope_mode: str) -> str:
    return "all" if role == "highest_admin" else scope_mode


def _validated_scope_store_ids(
    role: str, scope_mode: str, store_ids: list[str]
) -> list[str]:
    normalized_ids = sorted({normalize_account_value(value) for value in store_ids if normalize_account_value(value)})
    if role == "highest_admin":
        if scope_mode != "all":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Highest administrators must have all-store scope",
            )
        return []
    if scope_mode == "all":
        if role != "admin":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Store accounts cannot have all-store scope",
            )
        return []
    if scope_mode != "specified" or not normalized_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one store is required for specified scope",
        )
    return normalized_ids


def _account_audit_snapshot(session, user: User) -> dict:
    allow, deny = user_override_sets(session, user.user_id)
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "status": user.status,
        "store_scope_mode": user.store_scope_mode,
        "store_ids": list(
            session.scalars(
                select(UserStoreScope.store_id)
                .where(UserStoreScope.user_id == user.user_id)
                .order_by(UserStoreScope.store_id)
            ).all()
        ),
        "extra_allow": sorted(allow),
        "extra_deny": sorted(deny),
        "effective_page_keys": list(effective_page_keys(session, user)),
    }


def _replace_user_scopes(session, user_id: str, store_ids: list[str]) -> None:
    replace_user_store_scopes(session, user_id, store_ids)


def _optional_account_value(value: str | None) -> str | None:
    normalized = normalize_account_value(value)
    return normalized or None


def _sync_schedule(session, config: dict) -> SyncScheduleData:
    latest_success = session.execute(
        select(JobRun.finished_at)
        .where(JobRun.job_name == "collect_and_settle")
        .where(JobRun.status == "success")
        .where(JobRun.finished_at.is_not(None))
        .order_by(JobRun.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    auto_sync_enabled = bool(config.get("auto_sync_enabled", True))
    next_scheduled_at = None
    if auto_sync_enabled:
        interval_seconds = int(config.get("interval_seconds") or 86400)
        latest_success = _aware_utc(latest_success)
        next_scheduled_at = (
            latest_success + timedelta(seconds=interval_seconds)
            if latest_success is not None
            else datetime.now(timezone.utc)
        )
    return SyncScheduleData(
        auto_sync_enabled=auto_sync_enabled,
        latest_successful_sync_at=_aware_utc(latest_success),
        next_scheduled_sync_at=next_scheduled_at,
    )


def _sync_worker_status(
    session,
    config: dict,
    schedule: SyncScheduleData,
) -> SyncWorkerStatusData:
    return SyncWorkerStatusData(
        mode=_worker_mode_from_env(),
        auto_sync_enabled=bool(config.get("auto_sync_enabled", True)),
        interval_seconds=int(config.get("interval_seconds") or 86400),
        rolling_days=int(config.get("rolling_days") or 30),
        history_chunk_days=int(config.get("history_chunk_days") or 1),
        run_on_start=_truthy_env(os.getenv("WORKER_RUN_ON_START", "true")),
        run_once=_truthy_env(os.getenv("WORKER_RUN_ONCE")),
        chunk_max_attempts=_worker_chunk_max_attempts(),
        disabled_poll_seconds=DISABLED_WORKER_POLL_SECONDS,
        active_job=_job_run_data(_latest_worker_job(session, status="running")),
        latest_success=_job_run_data(_latest_worker_job(session, status="success")),
        latest_failure=_job_run_data(_latest_worker_job(session, status="failed")),
        next_scheduled_sync_at=schedule.next_scheduled_sync_at,
    )


def _latest_worker_job(session, *, status: str) -> JobRun | None:
    return session.execute(
        select(JobRun)
        .where(JobRun.job_name.in_(WORKER_STATUS_JOB_NAMES))
        .where(JobRun.status == status)
        .order_by(JobRun.started_at.desc(), JobRun.job_id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _job_run_data(job: JobRun | None) -> JobRunData | None:
    if job is None:
        return None
    metadata = job.metadata_json if isinstance(job.metadata_json, dict) else {}
    return JobRunData(
        job_id=job.job_id,
        job_name=job.job_name,
        status=job.status,
        started_at=_aware_utc(job.started_at),
        finished_at=_aware_utc(job.finished_at),
        success_count=job.success_count or 0,
        failed_count=job.failed_count or 0,
        error_message=sanitize_error_message(job.error_message),
        metadata_json=metadata,
    )


def _worker_mode_from_env() -> str:
    mode = (os.getenv("WORKER_MODE") or "collect_and_settle").strip().lower()
    return mode or "collect_and_settle"


def _worker_chunk_max_attempts() -> int:
    try:
        attempts = int(
            os.getenv(
                "WORKER_CHUNK_MAX_ATTEMPTS",
                str(DEFAULT_WORKER_CHUNK_MAX_ATTEMPTS),
            )
        )
    except ValueError:
        attempts = DEFAULT_WORKER_CHUNK_MAX_ATTEMPTS
    return max(1, min(5, attempts))


def _truthy_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def run_admin_sku_rule_rebuild_job(*, job_id: str) -> None:
    run_settlement_rebuild_job(job_id=job_id, factory=get_session_factory())


def _pagination(page: int, page_size: int, total: int) -> Pagination:
    return Pagination(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


def _clue_master_lead_payload(row: ClueMasterLead) -> dict:
    return {
        "canonical_clue_id": row.canonical_clue_id,
        "order_id": row.order_id,
        "raw_order_status": row.raw_order_status,
        "normalized_order_status": row.normalized_order_status,
        "lifecycle_status": row.lifecycle_status,
        "pool_location": row.pool_location,
        "allocation_state": row.allocation_state,
        "current_assignment_round_id": row.current_assignment_round_id,
        "allocation_cycle_id": row.allocation_cycle_id,
        "ended_without_assignment": row.ended_without_assignment,
        "closed_at": row.closed_at,
        "closed_reason": row.closed_reason,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
        "anchor_poi_id": row.anchor_poi_id,
        "anchor_store_id": row.anchor_store_id,
        "anchor_source": row.anchor_source,
        "anchor_unavailable_reason": row.anchor_unavailable_reason,
        "anchor_province": row.anchor_province,
        "anchor_city": row.anchor_city,
        "anchor_city_code": row.anchor_city_code,
    }


def _clue_allocation_decision_payload(
    row: ClueAllocationDecision,
    *,
    visible_store_ids: tuple[str, ...] | None = None,
) -> dict:
    snapshot = _without_phone_fields(row.decision_snapshot or {})
    selected_store_visible = (
        visible_store_ids is None or row.selected_store_id in set(visible_store_ids)
    )
    if visible_store_ids is not None:
        allowed_store_ids = set(visible_store_ids)
        candidates = snapshot.get("candidates")
        if isinstance(candidates, list):
            snapshot = {
                **snapshot,
                "candidates": [
                    candidate
                    for candidate in candidates
                    if isinstance(candidate, dict)
                    and candidate.get("store_id") in allowed_store_ids
                ],
            }
    selected_store_id = row.selected_store_id if selected_store_visible else None
    metrics = _clue_allocation_decision_metrics(snapshot, selected_store_id)
    return {
        "decision_id": row.decision_id,
        "cycle_id": row.allocation_cycle_id,
        "lead_key": row.lead_key,
        "order_id": row.order_id,
        "rule_id": row.rule_id,
        "rule_version_id": row.rule_version_id,
        "scope_type": row.scope_type,
        "scope_key": row.scope_key,
        "strategy_type": row.strategy_type,
        "execution_order": row.execution_order,
        "allocation_cycle_id": row.allocation_cycle_id,
        "dataset_kind": snapshot.get("dataset_kind") or row.execution_mode,
        "execution_mode": row.execution_mode,
        "assignment_round_id": row.assignment_round_id,
        "round_no": row.round_no,
        "selected_store_id": selected_store_id,
        "selected_store_name": row.selected_store_name if selected_store_visible else None,
        "decision_status": row.decision_status,
        "reason": row.reason,
        "composite_score": metrics["composite_score"],
        "distance_km": metrics["distance_km"],
        "candidate_count": metrics["candidate_count"],
        "payload": snapshot,
        "actor": row.actor,
        "executed_at": row.executed_at,
    }


def _clue_allocation_decision_metrics(
    snapshot: dict,
    selected_store_id: str | None,
) -> dict[str, float | int | None]:
    candidates = snapshot.get("candidates")
    candidate_rows = candidates if isinstance(candidates, list) else []
    selected = next(
        (
            candidate
            for candidate in candidate_rows
            if isinstance(candidate, dict)
            and (
                candidate.get("store_id") == selected_store_id
                or (selected_store_id is None and candidate.get("rank") == 1)
            )
        ),
        None,
    )
    score = selected.get("score") if isinstance(selected, dict) else None
    return {
        "composite_score": _optional_float(score.get("composite_score")) if isinstance(score, dict) else None,
        "distance_km": _optional_float(selected.get("distance_km")) if isinstance(selected, dict) else None,
        "candidate_count": len(candidate_rows),
    }


def _clue_allocation_candidate_payload(row: ClueAllocationCandidate) -> dict:
    return {
        "candidate_id": row.candidate_id,
        "store_id": row.store_id,
        "store_name": row.store_name_snapshot,
        "eligibility_status": row.eligibility_status,
        "exclusion_reason_code": row.exclusion_reason_code,
        "is_sales_store": row.is_sales_store,
        "is_historical_assignment": row.is_historical_assignment,
        "distance_km": _optional_float(row.distance_km),
        "conversion_rate": _optional_float(row.conversion_rate),
        "follow_24h_rate": _optional_float(row.follow_24h_rate),
        "store_weight": _optional_float(row.store_weight),
        "composite_score": _optional_float(row.composite_score),
        "rank_no": row.rank_no,
        "is_selected": row.is_selected,
    }


def _clue_allocation_eligible_lead_payload(row: ClueMasterLead) -> dict:
    return {
        "lead_key": row.lead_key,
        "canonical_clue_id": row.canonical_clue_id,
        "order_id": row.order_id,
        "allocation_state": row.allocation_state,
        "pool_location": row.pool_location,
        "anchor_store_id": row.anchor_store_id,
        "anchor_city": row.anchor_city,
        "anchor_city_code": row.anchor_city_code,
        "updated_at": row.updated_at,
    }


def _clue_headquarters_pool_entry_payload(
    row: ClueHeadquartersPoolEntry,
    lead: ClueMasterLead,
) -> dict:
    reason_code = canonical_headquarters_pool_reason(row.reason)
    return {
        "headquarters_pool_entry_id": row.headquarters_pool_entry_id,
        "lead_key": row.lead_key,
        "canonical_clue_id": lead.canonical_clue_id,
        "order_id": lead.order_id,
        "normalized_order_status": lead.normalized_order_status,
        "order_status": lead.normalized_order_status,
        "raw_order_status": lead.raw_order_status,
        "entry_status": row.status,
        "status": row.status,
        "reason_code": reason_code,
        "reason_label": HEADQUARTERS_POOL_REASON_LABELS[reason_code],
        "reason": reason_code,
        "entered_at": row.entered_at,
        "closed_at": row.closed_at,
        "close_reason": row.close_reason,
        "anchor_store_id": lead.anchor_store_id,
        "anchor_city": lead.anchor_city,
        "anchor_city_code": lead.anchor_city_code,
        "source_assignment_round_id": row.source_assignment_round_id,
        "source_decision_id": row.source_decision_id,
        "source_rule_version_id": row.source_rule_version_id,
        "allocation_cycle_id": row.allocation_cycle_id,
    }


def _clue_allocation_cycle_payload(
    row: ClueAllocationCycle,
    *,
    visible_items: list[ClueAllocationCycleItem] | None = None,
) -> dict:
    if visible_items is None:
        selected_lead_keys = list(row.selected_lead_keys or [])
        requested_lead_count = row.requested_lead_count
        active_lead_count = row.active_lead_count
        planned_impact = _without_phone_fields(row.planned_impact_json or {})
        actual_impact = _without_phone_fields(row.actual_impact_json or {})
        error_summary = _without_phone_fields(row.error_summary or {})
    else:
        selected_lead_keys = [item.lead_key for item in visible_items]
        requested_lead_count = len(visible_items)
        active_lead_count = len(visible_items)
        counts = Counter(item.item_status for item in visible_items)
        actual_impact = {
            "assigned": int(counts["assigned"]),
            "headquarters": int(counts["headquarters"]),
            "skipped": int(counts["skipped"]),
            "failed": int(counts["failed"]),
            "total": len(visible_items),
        }
        planned_impact = {
            "lead_keys": selected_lead_keys,
            "auto_expiry_enabled": bool(
                (row.planned_impact_json or {}).get("auto_expiry_enabled", False)
            ),
        }
        error_summary = (
            {"failed": int(counts["failed"])} if counts["failed"] else {}
        )
    return {
        "cycle_id": row.allocation_cycle_id,
        "allocation_cycle_id": row.allocation_cycle_id,
        "cycle_mode": row.cycle_type,
        "cycle_type": row.cycle_type,
        "execution_mode": row.execution_mode,
        "cycle_status": row.status,
        "status": row.status,
        "trigger_type": "manual" if row.actor else "scheduled",
        "parent_cycle_id": row.parent_cycle_id,
        "source_cycle_id": row.parent_cycle_id,
        "selected_lead_keys": selected_lead_keys,
        "requested_lead_count": requested_lead_count,
        "eligible_lead_count": active_lead_count,
        "active_lead_count": active_lead_count,
        "assigned_lead_count": int(actual_impact.get("assigned", 0)),
        "headquarters_pool_count": int(actual_impact.get("headquarters", 0)),
        "skipped_lead_count": int(actual_impact.get("skipped", 0)),
        "failed_lead_count": int(actual_impact.get("failed", 0)),
        "planned_impact": planned_impact,
        "actual_impact": actual_impact,
        "actor": row.actor,
        "actor_user_id": row.actor_user_id,
        "actor_username": row.actor_username_snapshot or row.actor,
        "privileged_confirmation": row.privileged_confirmation,
        "requested_at": row.created_at,
        "created_at": row.created_at,
        "executed_at": row.executed_at,
        "completed_at": row.completed_at,
        "error_summary": error_summary,
    }


def _clue_allocation_cycle_item_payload(
    row: ClueAllocationCycleItem,
) -> dict:
    return {
        "cycle_item_id": row.cycle_item_id,
        "sequence_no": row.sequence_no,
        "lead_key": row.lead_key,
        "order_id": row.order_id,
        "item_status": row.item_status,
        "initial_pool_location": row.initial_pool_location,
        "outcome_reason": row.outcome_reason,
        "rule_binding_id": row.rule_binding_id,
        "decision_id": row.decision_id,
        "assignment_round_id": row.assignment_round_id,
        "headquarters_pool_entry_id": row.headquarters_pool_entry_id,
        "attempt_count": row.attempt_count,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "error_code": row.error_code,
    }


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clue_allocation_audit_log_payload(row: ClueAllocationAuditLog) -> dict:
    return {
        "audit_log_id": row.audit_log_id,
        "event_type": row.event_type,
        "allocation_cycle_id": row.allocation_cycle_id,
        "actor": row.actor,
        "actor_user_id": row.actor_user_id,
        "actor_username_snapshot": row.actor_username_snapshot or row.actor,
        "actor_role_snapshot": row.actor_role_snapshot,
        "actor_scope_snapshot": _without_phone_fields(row.actor_scope_snapshot or {}),
        "request_id": row.request_id,
        "result_status": row.result_status,
        "reason_code": row.reason_code,
        "privileged_confirmation": row.privileged_confirmation,
        "before_snapshot": _without_phone_fields(row.before_snapshot or {}),
        "after_snapshot": _without_phone_fields(row.after_snapshot or {}),
        "detail": _without_phone_fields(row.detail_json or {}),
        "created_at": row.created_at,
    }


def _without_phone_fields(value):
    if isinstance(value, dict):
        return {
            key: _without_phone_fields(item)
            for key, item in value.items()
            if not _is_phone_field(key)
        }
    if isinstance(value, list):
        return [_without_phone_fields(item) for item in value]
    return value


def _is_phone_field(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    parts = {part for part in normalized.split("_") if part}
    return "phone" in normalized or "telephone" in normalized or "mobile" in normalized or "tel" in parts


def _store_score_run_payload(
    row: StoreScoreSnapshotRun,
    *,
    rule_version_id: str | None = None,
    visible_snapshot_count: int | None = None,
    hide_triggered_by: bool = False,
) -> dict:
    config = row.config_json if isinstance(getattr(row, "config_json", None), dict) else {}
    if rule_version_id is None:
        rule_version_id = config.get("rule_version_id")
        if not isinstance(rule_version_id, str) or not rule_version_id.strip():
            rule_version_id = None
    return {
        "snapshot_run_id": row.snapshot_run_id,
        "snapshot_date": row.snapshot_date,
        "run_mode": row.run_mode,
        "window_start": row.window_start,
        "window_end": row.window_end,
        "candidate_store_count": (
            visible_snapshot_count
            if visible_snapshot_count is not None
            else row.candidate_store_count
        ),
        "snapshot_count": (
            visible_snapshot_count
            if visible_snapshot_count is not None
            else row.snapshot_count
        ),
        "triggered_by": None if hide_triggered_by else row.triggered_by,
        "computed_at": row.computed_at,
        "rule_version_id": rule_version_id,
    }


def _store_score_snapshot_payload(
    row: StoreScoreSnapshot, *, rule_version_id: str | None = None
) -> dict:
    config = row.config_json if isinstance(getattr(row, "config_json", None), dict) else {}
    if rule_version_id is None:
        rule_version_id = config.get("rule_version_id")
        if not isinstance(rule_version_id, str) or not rule_version_id.strip():
            rule_version_id = None
    return {
        "store_id": row.store_id,
        "rule_version_id": rule_version_id,
        "city_code": row.city_code,
        "conversion_numerator": row.conversion_numerator,
        "conversion_denominator": row.conversion_denominator,
        "conversion_rate": float(row.conversion_rate),
        "conversion_value_source": row.conversion_value_source,
        "follow_24h_numerator": row.follow_24h_numerator,
        "follow_24h_denominator": row.follow_24h_denominator,
        "follow_24h_rate": float(row.follow_24h_rate),
        "follow_24h_value_source": row.follow_24h_value_source,
        "store_weight": float(row.store_weight),
        "composite_score": float(row.composite_score),
    }


def _clue_allocation_rule_payload(row: ClueAllocationRule) -> dict:
    return {
        "rule_id": row.rule_id,
        "name": row.rule_name,
        "scope": {
            "scope_type": row.scope_type,
            "city_code": row.scope_city_code,
            "store_group_id": row.scope_store_group_id,
            "anchor_store_id": row.scope_anchor_store_id,
        },
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _clue_allocation_rule_version_payload(session, row: ClueAllocationRuleVersion) -> dict:
    configs = session.scalars(
        select(ClueAllocationStrategyConfig)
        .where(ClueAllocationStrategyConfig.rule_version_id == row.rule_version_id)
        .order_by(ClueAllocationStrategyConfig.execution_order, ClueAllocationStrategyConfig.strategy_config_id)
    ).all()
    return {
        "rule_version_id": row.rule_version_id,
        "rule_id": row.rule_id,
        "version_no": row.version_no,
        "status": row.status,
        "auto_expiry_enabled": row.auto_expiry_enabled,
        "first_follow_up_sla_hours": row.first_follow_up_sla_hours,
        "protection_days": row.protection_days,
        "conversion_weight": float(row.conversion_weight) if row.conversion_weight is not None else None,
        "follow_24h_weight": float(row.follow_24h_weight) if row.follow_24h_weight is not None else None,
        "lookback_days": row.lookback_days,
        "min_samples": row.min_samples,
        "strategy_configs": [
            {
                "strategy_type": config.strategy_type,
                "enabled": config.enabled,
                "execution_order": config.execution_order,
                "params": dict(config.params_json or {}),
            }
            for config in configs
        ],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "published_at": row.published_at,
        "retired_at": row.retired_at,
    }


def _clue_store_group_payload(
    session,
    group: ClueStoreGroup,
    *,
    visible_store_ids: tuple[str, ...] | None = None,
) -> dict:
    member_statement = select(ClueStoreGroupMember.store_id).where(
        ClueStoreGroupMember.store_group_id == group.store_group_id
    )
    if visible_store_ids is not None:
        member_statement = member_statement.where(
            ClueStoreGroupMember.store_id.in_(visible_store_ids)
            if visible_store_ids
            else false()
        )
    member_store_ids = session.scalars(
        member_statement.order_by(ClueStoreGroupMember.store_id)
    ).all()
    return {
        "store_group_id": group.store_group_id,
        "name": group.group_name,
        "member_store_ids": member_store_ids,
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def _sync_progress(session, config: dict) -> SyncProgressData:
    history_end = config.get("history_end") or datetime.now(SHANGHAI_TZ).isoformat()
    source_window = resolve_collection_window(
        start=config.get("history_start"),
        end=history_end,
        timezone_name="Asia/Shanghai",
    )
    chunks = list(
        iter_backfill_windows(
            source_window,
            chunk_days=int(config.get("history_chunk_days") or 1),
        )
    )
    completed_keys = successful_window_keys(session)
    completed_chunks = [chunk for chunk in chunks if _window_key(chunk) in completed_keys]
    latest = max(completed_chunks, key=lambda chunk: chunk.end, default=None)
    recent_jobs = session.execute(
        text(
            """
            SELECT
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_jobs,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs
            FROM job_runs
            """
        )
    ).mappings().first()
    return SyncProgressData(
        total_windows=len(chunks),
        completed_windows=len(completed_chunks),
        running_jobs=int((recent_jobs or {}).get("running_jobs") or 0),
        failed_jobs=int((recent_jobs or {}).get("failed_jobs") or 0),
        latest_completed_window=(
            SyncWindowData(
                start=latest.start.isoformat(),
                end=latest.end.isoformat(),
                timezone=latest.timezone_name,
            )
            if latest
            else None
        ),
    )


def _manual_window(payload: ManualSyncRequest) -> tuple[datetime, datetime]:
    end = _coerce_datetime(payload.end) if payload.end else datetime.now(SHANGHAI_TZ)
    if payload.start:
        start = _coerce_datetime(payload.start)
    else:
        days = payload.days or 30
        start = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sync end must be after start.",
        )
    return start, end


def _coerce_datetime(value: datetime) -> datetime:
    return value.astimezone(SHANGHAI_TZ) if value.tzinfo else value.replace(tzinfo=SHANGHAI_TZ)


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _window_key(window: CollectionWindow) -> tuple[str, str, str]:
    return (window.start.isoformat(), window.end.isoformat(), window.timezone_name)
