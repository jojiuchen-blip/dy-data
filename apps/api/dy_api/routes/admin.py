from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select, text

from apps.api.dy_api.models import (
    AccessPage,
    AccountPermissionAuditLog,
    ClueAllocationAuditLog,
    ClueAllocationCycle,
    ClueAllocationDecision,
    ClueAllocationRule,
    ClueAllocationRuleVersion,
    ClueAllocationStrategyConfig,
    ClueMasterLead,
    ClueHeadquartersPoolEntry,
    ClueStoreGroup,
    ClueStoreGroupMember,
    DimAwemeAccount,
    DimStore,
    DimStorePoiMapping,
    JobRun,
    StoreScoreSnapshot,
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
from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.backfill import iter_backfill_windows, successful_window_keys
from apps.worker.collectors.types import CollectionWindow
from apps.worker.collectors.windows import resolve_collection_window
from apps.worker.clue_center import rebuild_clue_center
from apps.worker.clue_allocation import materialize_clue_master_leads, refresh_store_score_snapshots
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
from apps.worker.pipeline import build_douyin_client_from_env
from apps.worker.repositories import finish_job_run, queue_job_run
from apps.worker.settlement import run_settlement_job
from apps.worker.sync_config import load_sync_config, save_sync_config
from dy_api.auth import (
    AuthContext,
    get_current_admin,
    get_current_super_admin,
    get_current_user,
    hash_password_pbkdf2,
    normalize_account_value,
)
from dy_api.routes._data import get_data_store, generated_at, sanitize_error_message
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
    ClueRebuildResult,
    ClueAllocationDecisionData,
    ClueAllocationDecisionRow,
    ClueAllocationAuditLogData,
    ClueAllocationAuditLogRow,
    ClueAllocationCycleData,
    ClueAllocationCycleExecutionData,
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


router = APIRouter()
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
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


def _phone_plain_resolver():
    try:
        client = build_douyin_client_from_env()
    except Exception:
        return None
    resolver = getattr(client, "decrypt_cipher_texts", None)
    return resolver if callable(resolver) else None


def _require_available_store(store):
    if not store.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    return store


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
    if detail.startswith(("active_round_exists:", "rebuild_blocked_by_follow_up:")):
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
    _ensure_unique_user_fields(
        store.session,
        username=payload.username,
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
        username=normalize_account_value(payload.username),
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
    _ensure_unique_user_fields(
        store.session,
        username=payload.username,
        external_account_id=payload.external_account_id,
        exclude_user_id=user_id,
    )
    store_ids = _validated_scope_store_ids(
        payload.role, payload.store_scope_mode, payload.store_ids
    )
    _ensure_store_ids_exist(store.session, store_ids)
    user.username = normalize_account_value(payload.username)
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
    _username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueMasterLead)
    if lifecycle_status:
        statement = statement.where(ClueMasterLead.lifecycle_status == lifecycle_status)
    if pool_location:
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
    lead_key: str | None = None,
    order_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationDecision)
    if lead_key:
        statement = statement.where(ClueAllocationDecision.lead_key == lead_key)
    if order_id:
        statement = statement.where(ClueAllocationDecision.order_id == order_id)
    total = int(store.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = store.session.scalars(
        statement.order_by(ClueAllocationDecision.executed_at.desc(), ClueAllocationDecision.decision_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    data = ClueAllocationDecisionData(
        rows=[ClueAllocationDecisionRow(**_clue_allocation_decision_payload(row)) for row in rows],
        pagination=_pagination(page, page_size, total),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/eligible-leads")
def list_clue_allocation_eligible_leads(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(get_current_admin),
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
    pool_status: str | None = None,
    reason: str | None = None,
    entered_date_start: date | None = None,
    entered_date_end: date | None = None,
    order_status: str | None = None,
    order_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    if entered_date_start and entered_date_end and entered_date_end < entered_date_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="entered_date_end must be on or after entered_date_start",
        )

    filters = []
    if pool_status:
        filters.append(ClueHeadquartersPoolEntry.status == pool_status)
    if reason:
        filters.append(ClueHeadquartersPoolEntry.reason == reason)
    if entered_date_start:
        filters.append(ClueHeadquartersPoolEntry.entered_at >= _shanghai_day_start(entered_date_start))
    if entered_date_end:
        filters.append(
            ClueHeadquartersPoolEntry.entered_at
            < _shanghai_day_start(entered_date_end + timedelta(days=1))
        )
    if order_status:
        filters.append(ClueMasterLead.normalized_order_status == order_status)
    normalized_order_id = (order_id or "").strip()
    if normalized_order_id:
        filters.append(ClueMasterLead.order_id.contains(normalized_order_id, autoescape=True))

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
                    .where(ClueHeadquartersPoolEntry.status == "active")
                )
                or 0
            ),
            filtered_total=total,
        ),
        filter_options=ClueHeadquartersPoolFilterOptions(
            pool_statuses=list(
                store.session.scalars(
                    select(ClueHeadquartersPoolEntry.status)
                    .distinct()
                    .order_by(ClueHeadquartersPoolEntry.status)
                ).all()
            ),
            reasons=list(
                store.session.scalars(
                    select(ClueHeadquartersPoolEntry.reason)
                    .distinct()
                    .order_by(ClueHeadquartersPoolEntry.reason)
                ).all()
            ),
            order_statuses=list(
                store.session.scalars(
                    select(ClueMasterLead.normalized_order_status)
                    .join(
                        ClueHeadquartersPoolEntry,
                        ClueHeadquartersPoolEntry.lead_key == ClueMasterLead.lead_key,
                    )
                    .distinct()
                    .order_by(ClueMasterLead.normalized_order_status)
                ).all()
            ),
        ),
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/cycles")
def list_clue_allocation_cycles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationCycle)
    total = int(store.session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = store.session.scalars(
        statement.order_by(
            ClueAllocationCycle.created_at.desc(),
            ClueAllocationCycle.allocation_cycle_id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    data = ClueAllocationCycleData(
        rows=[ClueAllocationCycleRow(**_clue_allocation_cycle_payload(row)) for row in rows],
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
    _username: str = Depends(get_current_admin),
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


@router.post("/clue-allocation/cycles/preview")
def preview_clue_allocation_cycle(
    payload: ClueAllocationCyclePreviewRequest,
    username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        if payload.operation == "rebuild":
            result = preview_rebuild_trial_allocation_cycle(
                store.session,
                source_cycle_id=payload.source_cycle_id or "",
                actor=username,
                privileged_confirmation=payload.privileged_confirmation,
            )
        else:
            result = preview_trial_allocation_cycle(
                store.session,
                lead_keys=payload.lead_keys,
                actor=username,
            )
    except AllocationCycleError as error:
        raise _allocation_cycle_http_error(error) from error
    data = ClueAllocationCyclePreviewData(**result)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/cycles/trial")
def execute_clue_allocation_trial(
    payload: ClueAllocationCycleRequest,
    username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="explicit confirmation is required before running a trial allocation cycle",
        )
    store = _require_available_store(store)
    try:
        preview_grant = validate_allocation_preview_grant(
            payload.preview_token,
            operation="trial",
            actor=username,
            lead_keys=payload.lead_keys,
            privileged_confirmation=payload.privileged_confirmation,
        )
        result = run_trial_allocation_cycle(
            store.session,
            lead_keys=payload.lead_keys,
            actor=username,
            privileged_confirmation=payload.privileged_confirmation,
            preview_token_hash=preview_grant.token_hash,
            expected_lead_keys=preview_grant.lead_keys,
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


@router.post("/clue-allocation/cycles/rebuild")
def rebuild_clue_allocation_trial(
    payload: ClueAllocationCycleRebuildRequest,
    username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="explicit confirmation is required before rebuilding a trial allocation cycle",
        )
    store = _require_available_store(store)
    try:
        preview_grant = validate_allocation_preview_grant(
            payload.preview_token,
            operation="rebuild",
            actor=username,
            source_cycle_id=payload.source_cycle_id,
            privileged_confirmation=payload.privileged_confirmation,
        )
        result = rebuild_trial_allocation_cycle(
            store.session,
            source_cycle_id=payload.source_cycle_id,
            actor=username,
            privileged_confirmation=payload.privileged_confirmation,
            preview_token_hash=preview_grant.token_hash,
            expected_lead_keys=preview_grant.lead_keys,
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


@router.get("/clue-allocation/store-scores")
def list_store_score_snapshots(
    snapshot_run_id: str | None = None,
    snapshot_date: date | None = None,
    run_mode: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    run_statement = select(StoreScoreSnapshotRun)
    if snapshot_run_id:
        run_statement = run_statement.where(StoreScoreSnapshotRun.snapshot_run_id == snapshot_run_id)
    elif snapshot_date:
        run_statement = run_statement.where(StoreScoreSnapshotRun.snapshot_date == snapshot_date)
    if run_mode:
        run_statement = run_statement.where(StoreScoreSnapshotRun.run_mode == run_mode)
    run = store.session.scalar(
        run_statement.order_by(StoreScoreSnapshotRun.computed_at.desc(), StoreScoreSnapshotRun.snapshot_run_id.desc()).limit(1)
    )
    if run is None:
        data = StoreScoreSnapshotData(run=None, rows=[], pagination=_pagination(page, page_size, 0))
    else:
        snapshot_statement = select(StoreScoreSnapshot).where(StoreScoreSnapshot.snapshot_run_id == run.snapshot_run_id)
        total = int(store.session.scalar(select(func.count()).select_from(snapshot_statement.subquery())) or 0)
        snapshots = store.session.scalars(
            snapshot_statement.order_by(StoreScoreSnapshot.composite_score.desc(), StoreScoreSnapshot.store_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        data = StoreScoreSnapshotData(
            run=StoreScoreSnapshotRunData(**_store_score_run_payload(run)),
            rows=[StoreScoreSnapshotRow(**_store_score_snapshot_payload(row)) for row in snapshots],
            pagination=_pagination(page, page_size, total),
        )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/store-scores/refresh")
def refresh_store_scores(
    payload: StoreScoreRefreshRequest,
    _username: str = Depends(get_current_super_admin),
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
        triggered_by=_username,
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
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    statement = select(ClueAllocationRule)
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
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    rule = store.session.get(ClueAllocationRule, rule_id)
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
    payload: ClueAllocationRuleCreateRequest,
    username: str = Depends(get_current_super_admin),
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
            created_by=username,
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    store.session.commit()
    data = ClueAllocationRuleData(**_clue_allocation_rule_payload(rule))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/rules/{rule_id}/versions", status_code=status.HTTP_201_CREATED)
def create_clue_allocation_rule_version_route(
    rule_id: str,
    payload: ClueAllocationRuleVersionWrite,
    username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        version = create_rule_version(
            store.session,
            rule_id,
            created_by=username,
            **payload.model_dump(),
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    store.session.commit()
    data = ClueAllocationRuleVersionData(**_clue_allocation_rule_version_payload(store.session, version))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/clue-allocation/rule-versions/{rule_version_id}")
def update_clue_allocation_rule_version_route(
    rule_version_id: str,
    payload: ClueAllocationRuleVersionWrite,
    username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        version = update_rule_version(
            store.session,
            rule_version_id,
            updated_by=username,
            **payload.model_dump(),
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    store.session.commit()
    data = ClueAllocationRuleVersionData(**_clue_allocation_rule_version_payload(store.session, version))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.delete("/clue-allocation/rule-versions/{rule_version_id}")
def delete_clue_allocation_rule_version_route(
    rule_version_id: str,
    _username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        delete_rule_version(store.session, rule_version_id)
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    store.session.commit()
    data = ClueAllocationRuleVersionDeleteData(rule_version_id=rule_version_id, deleted=True)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/rule-versions/{rule_version_id}/publish")
def publish_clue_allocation_rule_version_route(
    rule_version_id: str,
    username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        version = publish_rule_version(store.session, rule_version_id, published_by=username)
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    store.session.commit()
    data = ClueAllocationRuleVersionData(**_clue_allocation_rule_version_payload(store.session, version))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/rule-versions/{rule_version_id}/retire")
def retire_clue_allocation_rule_version_route(
    rule_version_id: str,
    username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        version = retire_rule_version(store.session, rule_version_id, retired_by=username)
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    store.session.commit()
    data = ClueAllocationRuleVersionData(**_clue_allocation_rule_version_payload(store.session, version))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.get("/clue-allocation/store-groups")
def list_clue_store_groups(
    _username: str = Depends(get_current_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    groups = store.session.scalars(
        select(ClueStoreGroup).order_by(ClueStoreGroup.group_name, ClueStoreGroup.store_group_id)
    ).all()
    data = ClueStoreGroupListData(
        rows=[ClueStoreGroupData(**_clue_store_group_payload(store.session, group)) for group in groups]
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.post("/clue-allocation/store-groups", status_code=status.HTTP_201_CREATED)
def create_clue_store_group_route(
    payload: ClueStoreGroupCreateRequest,
    username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        group = create_store_group(
            store.session,
            name=payload.name,
            member_store_ids=payload.member_store_ids,
            created_by=username,
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    store.session.commit()
    data = ClueStoreGroupData(**_clue_store_group_payload(store.session, group))
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "postgres"},
    }


@router.put("/clue-allocation/store-groups/{store_group_id}/members")
def replace_clue_store_group_members_route(
    store_group_id: str,
    payload: ClueStoreGroupMembersUpdate,
    _username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    try:
        group = replace_store_group_members(
            store.session,
            store_group_id,
            member_store_ids=payload.member_store_ids,
        )
    except RuleVersionError as exc:
        raise _rule_version_http_error(exc) from exc
    store.session.commit()
    data = ClueStoreGroupData(**_clue_store_group_payload(store.session, group))
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


@router.post("/sync/clue-center/rebuild")
def rebuild_clue_center_materialization(
    _username: str = Depends(get_current_super_admin),
    store=Depends(get_data_store),
):
    store = _require_available_store(store)
    master_result = materialize_clue_master_leads(store.session)
    if master_result.get("skipped") == "locked":
        store.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="线索主数据维护正在执行，请稍后重试",
        )
    stats = rebuild_clue_center(
        store.session,
        phone_plain_resolver=_phone_plain_resolver(),
    )
    store.session.commit()
    data = ClueRebuildResult(
        rebuilt_order_count=stats.get("eligible_orders", 0),
        rebuilt_round_count=stats.get("assignment_rounds", 0),
    )
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
    session.execute(delete(UserStoreScope).where(UserStoreScope.user_id == user_id))
    for store_id in sorted(set(store_ids)):
        session.add(UserStoreScope(user_id=user_id, store_id=store_id))
    session.flush()


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
    factory = get_session_factory()
    if factory is None:
        return
    with session_scope(factory) as session:
        try:
            run_settlement_job(session, job_id=job_id, source_run_id=job_id)
        except Exception as exc:
            try:
                finish_job_run(
                    session,
                    job_id,
                    status="failed",
                    failed_count=1,
                    error_message=str(exc),
                )
            except ValueError:
                pass
            raise


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


def _clue_allocation_decision_payload(row: ClueAllocationDecision) -> dict:
    return {
        "decision_id": row.decision_id,
        "lead_key": row.lead_key,
        "order_id": row.order_id,
        "rule_id": row.rule_id,
        "rule_version_id": row.rule_version_id,
        "scope_type": row.scope_type,
        "scope_key": row.scope_key,
        "strategy_type": row.strategy_type,
        "execution_order": row.execution_order,
        "allocation_cycle_id": row.allocation_cycle_id,
        "execution_mode": row.execution_mode,
        "assignment_round_id": row.assignment_round_id,
        "round_no": row.round_no,
        "selected_store_id": row.selected_store_id,
        "selected_store_name": row.selected_store_name,
        "decision_status": row.decision_status,
        "reason": row.reason,
        "payload": _without_phone_fields(row.decision_snapshot or {}),
        "actor": row.actor,
        "executed_at": row.executed_at,
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
    return {
        "headquarters_pool_entry_id": row.headquarters_pool_entry_id,
        "lead_key": row.lead_key,
        "canonical_clue_id": lead.canonical_clue_id,
        "order_id": lead.order_id,
        "order_status": lead.normalized_order_status,
        "raw_order_status": lead.raw_order_status,
        "status": row.status,
        "reason": row.reason,
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


def _clue_allocation_cycle_payload(row: ClueAllocationCycle) -> dict:
    return {
        "allocation_cycle_id": row.allocation_cycle_id,
        "cycle_type": row.cycle_type,
        "execution_mode": row.execution_mode,
        "status": row.status,
        "parent_cycle_id": row.parent_cycle_id,
        "selected_lead_keys": list(row.selected_lead_keys or []),
        "requested_lead_count": row.requested_lead_count,
        "active_lead_count": row.active_lead_count,
        "planned_impact": _without_phone_fields(row.planned_impact_json or {}),
        "actual_impact": _without_phone_fields(row.actual_impact_json or {}),
        "actor": row.actor,
        "privileged_confirmation": row.privileged_confirmation,
        "created_at": row.created_at,
        "executed_at": row.executed_at,
        "completed_at": row.completed_at,
    }


def _clue_allocation_audit_log_payload(row: ClueAllocationAuditLog) -> dict:
    return {
        "audit_log_id": row.audit_log_id,
        "event_type": row.event_type,
        "allocation_cycle_id": row.allocation_cycle_id,
        "actor": row.actor,
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


def _store_score_run_payload(row: StoreScoreSnapshotRun) -> dict:
    return {
        "snapshot_run_id": row.snapshot_run_id,
        "snapshot_date": row.snapshot_date,
        "run_mode": row.run_mode,
        "window_start": row.window_start,
        "window_end": row.window_end,
        "candidate_store_count": row.candidate_store_count,
        "snapshot_count": row.snapshot_count,
        "triggered_by": row.triggered_by,
        "computed_at": row.computed_at,
    }


def _store_score_snapshot_payload(row: StoreScoreSnapshot) -> dict:
    return {
        "store_id": row.store_id,
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


def _clue_store_group_payload(session, group: ClueStoreGroup) -> dict:
    member_store_ids = session.scalars(
        select(ClueStoreGroupMember.store_id)
        .where(ClueStoreGroupMember.store_group_id == group.store_group_id)
        .order_by(ClueStoreGroupMember.store_id)
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
