"""Account management boundaries and serialized administrator lifecycle changes."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import JSON, and_, exists, func, or_, select, text

from apps.api.dy_api.models import User, UserStoreScope

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from apps.api.dy_api.auth import AuthContext


ACCOUNT_MUTATION_LOCK = 105_20261022


def account_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "errors": []})


def manageable_user_condition(actor: AuthContext):
    """Require the whole target account to belong to the actor, not just one store."""
    if actor.can_manage_global_settings:
        return True
    return and_(
        User.role == "store",
        User.store_scope_mode == "specified",
        or_(User.org_scope.is_(None), User.org_scope == JSON.NULL),
        exists(select(1).where(UserStoreScope.user_id == User.user_id)),
        ~exists(select(1).where(
            UserStoreScope.user_id == User.user_id,
            UserStoreScope.store_id.not_in(actor.store_ids),
        )),
    )


def can_manage_user(session: Session, actor: AuthContext, user: User) -> bool:
    return bool(session.scalar(select(User.user_id).where(
        User.user_id == user.user_id, manageable_user_condition(actor),
    )))


def begin_account_mutation(session: Session, actor: AuthContext) -> AuthContext:
    """Serialize account writes, then reject identities revoked while waiting."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCOUNT_MUTATION_LOCK})
    if actor.auth_type == "env_admin":
        return actor
    from apps.api.dy_api.auth import user_store_ids
    from apps.api.dy_api.access_control import effective_page_keys

    user = session.get(User, actor.user_id, populate_existing=True, with_for_update=True)
    if (user is None or user.status != "active" or not user.is_initialized
            or user.auth_version != actor.auth_version):
        raise account_error(401, "AUTH_REQUIRED", "账号状态或权限已变更，请重新登录")
    role = "admin" if user.role in {"highest_admin", "viewer"} else user.role
    current = replace(actor, role=role, store_scope_mode=user.store_scope_mode,
                      store_ids=user_store_ids(session, user.user_id),
                      page_keys=effective_page_keys(session, user, role=role))
    if not current.can_manage_accounts:
        raise account_error(403, "ACCOUNT_SCOPE_FORBIDDEN", "当前账号不能管理账号")
    return current


def protect_last_global_admin(session: Session, user: User, *, role: str,
                              status: str, scope_mode: str) -> None:
    """Called under ACCOUNT_MUTATION_LOCK before changing the target user."""
    was_available = (user.role in {"admin", "highest_admin"} and user.status == "active"
                     and user.store_scope_mode == "all" and user.is_initialized
                     and bool(user.password_hash))
    stays_available = role == "admin" and status == "active" and scope_mode == "all"
    if not was_available or stays_available:
        return
    remaining = session.scalar(select(func.count()).select_from(User).where(
        User.user_id != user.user_id, User.role.in_(("admin", "highest_admin")),
        User.status == "active", User.store_scope_mode == "all",
        User.is_initialized.is_(True), User.password_hash.is_not(None), User.password_hash != "",
    ))
    if not remaining:
        raise account_error(409, "LAST_GLOBAL_ADMIN_REQUIRED", "至少保留一名有效的全部门店范围管理员")
