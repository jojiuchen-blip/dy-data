from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import delete, func, select

from apps.api.dy_api.models import (
    AccessPage,
    AccountPermissionAuditLog,
    RolePagePermission,
    User,
    UserPagePermissionOverride,
)


@dataclass(frozen=True)
class PageDefinition:
    page_key: str
    page_name: str
    module_name: str
    route_patterns: tuple[str, ...]


PAGE_DEFINITIONS = (
    PageDefinition("A01", "线索看板", "线索中心", ("/clues",)),
    PageDefinition("A02", "线索明细", "线索中心", ("/clues/:id",)),
    PageDefinition("B01", "全国门店榜单", "订单分佣", ("/ranking",)),
    PageDefinition("B02", "单店结算", "订单分佣", ("/settlement",)),
    PageDefinition("B03", "订单费用明细", "订单分佣", ("/order-details",)),
    PageDefinition("C01", "核销表现", "核销表现", ("/sales-dashboard",)),
    PageDefinition("D01", "后台首页", "管理后台", ("/admin",)),
    PageDefinition("D02", "账号管理", "管理后台", ("/admin/accounts",)),
    PageDefinition("D03", "分佣规则", "管理后台", ("/admin/rules", "/rule-admin")),
    PageDefinition("D04", "商品口径", "管理后台", ("/admin/product-types",)),
    PageDefinition("D05", "线索分配规则", "管理后台", ("/admin/clue-allocation", "/admin/clue-allocation/rules")),
    PageDefinition("D06", "分配试运行", "管理后台", ("/admin/clue-allocation/trial",)),
    PageDefinition("D07", "分配记录", "管理后台", ("/admin/clue-allocation/records",)),
    PageDefinition("D08", "总部线索池", "管理后台", ("/admin/clue-allocation/headquarters",)),
    PageDefinition("D09", "用户建议", "管理后台", ("/admin/feedback",)),
    PageDefinition("D10", "数据同步", "管理后台", ("/admin/sync", "/sync-admin")),
)
ALL_PAGE_KEYS = tuple(page.page_key for page in PAGE_DEFINITIONS)
ALL_PAGE_KEY_SET = frozenset(ALL_PAGE_KEYS)
STORE_DEFAULT_PAGE_KEYS = frozenset({"A01", "A02", "B01", "B02", "B03", "C01"})
VALID_ROLES = frozenset({"highest_admin", "admin", "store"})
VALID_SCOPE_MODES = frozenset({"all", "specified", "none"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_access_control_seed(session: Any) -> None:
    existing = set(session.scalars(select(AccessPage.page_key)).all())
    now = utcnow()
    for sort_order, page in enumerate(PAGE_DEFINITIONS, start=1):
        if page.page_key not in existing:
            session.add(
                AccessPage(
                    page_key=page.page_key,
                    page_name=page.page_name,
                    module_name=page.module_name,
                    route_patterns=list(page.route_patterns),
                    sort_order=sort_order,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
    session.flush()
    existing_defaults = set(
        session.execute(select(RolePagePermission.role, RolePagePermission.page_key)).all()
    )
    for role in ("admin", "store"):
        for page_key in ALL_PAGE_KEYS:
            if (role, page_key) in existing_defaults:
                continue
            session.add(
                RolePagePermission(
                    role=role,
                    page_key=page_key,
                    is_allowed=role == "admin" or page_key in STORE_DEFAULT_PAGE_KEYS,
                    updated_by="system-seed",
                    updated_at=now,
                )
            )
    session.flush()


def page_rows(session: Any) -> list[AccessPage]:
    ensure_access_control_seed(session)
    return list(
        session.scalars(
            select(AccessPage)
            .where(AccessPage.is_active.is_(True))
            .order_by(AccessPage.sort_order, AccessPage.page_key)
        ).all()
    )


def role_default_page_keys(session: Any, role: str) -> tuple[str, ...]:
    if role == "highest_admin":
        return tuple(row.page_key for row in page_rows(session))
    ensure_access_control_seed(session)
    values = set(
        session.scalars(
            select(RolePagePermission.page_key)
            .join(AccessPage, AccessPage.page_key == RolePagePermission.page_key)
            .where(RolePagePermission.role == role)
            .where(RolePagePermission.is_allowed.is_(True))
            .where(AccessPage.is_active.is_(True))
        ).all()
    )
    return tuple(key for key in ALL_PAGE_KEYS if key in values)


def user_override_sets(session: Any, user_id: str) -> tuple[set[str], set[str]]:
    rows = session.execute(
        select(UserPagePermissionOverride.page_key, UserPagePermissionOverride.effect).where(
            UserPagePermissionOverride.user_id == user_id
        )
    ).all()
    return (
        {page_key for page_key, effect in rows if effect == "allow"},
        {page_key for page_key, effect in rows if effect == "deny"},
    )


def effective_page_keys(session: Any, user: User | None, *, role: str | None = None) -> tuple[str, ...]:
    resolved_role = role or (user.role if user is not None else "highest_admin")
    if resolved_role == "highest_admin":
        return tuple(row.page_key for row in page_rows(session))
    defaults = set(role_default_page_keys(session, resolved_role))
    if user is None:
        return tuple(key for key in ALL_PAGE_KEYS if key in defaults)
    allow, deny = user_override_sets(session, user.user_id)
    values = (defaults | allow) - deny
    return tuple(key for key in ALL_PAGE_KEYS if key in values)


def validate_page_keys(values: Iterable[str]) -> set[str]:
    keys = {str(value).strip() for value in values if str(value).strip()}
    unknown = sorted(keys - ALL_PAGE_KEY_SET)
    if unknown:
        raise ValueError(f"Unknown page_key: {', '.join(unknown)}")
    return keys


def replace_user_overrides(
    session: Any,
    user: User,
    *,
    extra_allow: Iterable[str],
    extra_deny: Iterable[str],
    updated_by: str,
) -> None:
    allow = validate_page_keys(extra_allow)
    deny = validate_page_keys(extra_deny)
    if allow & deny:
        raise ValueError("A page cannot be both allowed and denied")
    session.execute(
        delete(UserPagePermissionOverride).where(
            UserPagePermissionOverride.user_id == user.user_id
        )
    )
    now = utcnow()
    for page_key in sorted(allow):
        session.add(
            UserPagePermissionOverride(
                user_id=user.user_id,
                page_key=page_key,
                effect="allow",
                updated_by=updated_by,
                updated_at=now,
            )
        )
    for page_key in sorted(deny):
        session.add(
            UserPagePermissionOverride(
                user_id=user.user_id,
                page_key=page_key,
                effect="deny",
                updated_by=updated_by,
                updated_at=now,
            )
        )
    session.flush()


def update_role_defaults_preserving_customizations(
    session: Any,
    *,
    role: str,
    page_keys: Iterable[str],
    updated_by: str,
) -> dict[str, int]:
    if role not in {"admin", "store"}:
        raise ValueError("Highest administrator defaults are fixed")
    desired = validate_page_keys(page_keys)
    ensure_access_control_seed(session)
    customized_users = list(
        session.scalars(
            select(User)
            .where(User.role == role)
            .where(
                User.user_id.in_(
                    select(UserPagePermissionOverride.user_id).distinct()
                )
            )
        ).all()
    )
    preserved = {
        user.user_id: set(effective_page_keys(session, user)) for user in customized_users
    }
    now = utcnow()
    for row in session.scalars(
        select(RolePagePermission).where(RolePagePermission.role == role)
    ).all():
        row.is_allowed = row.page_key in desired
        row.updated_by = updated_by
        row.updated_at = now
    session.flush()
    for user in customized_users:
        target = preserved[user.user_id]
        replace_user_overrides(
            session,
            user,
            extra_allow=target - desired,
            extra_deny=desired - target,
            updated_by=updated_by,
        )
    total_count = int(
        session.scalar(select(func.count()).select_from(User).where(User.role == role)) or 0
    )
    inherited_count = total_count - len(customized_users)
    return {"inheriting_user_count": inherited_count, "customized_user_count": len(customized_users)}


def add_audit_log(
    session: Any,
    *,
    action: str,
    actor: Any,
    target: User | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    result: str = "success",
) -> AccountPermissionAuditLog:
    row = AccountPermissionAuditLog(
        audit_id=uuid4().hex,
        action=action,
        result=result,
        actor_user_id=getattr(actor, "user_id", None),
        actor_username=str(getattr(actor, "username", "system")),
        actor_role=str(getattr(actor, "role", "highest_admin")),
        target_user_id=target.user_id if target else None,
        target_username=target.username if target else None,
        before_json=before or {},
        after_json=after or {},
        created_at=utcnow(),
    )
    session.add(row)
    return row


def account_permission_snapshot(session: Any, user: User) -> dict[str, Any]:
    allow, deny = user_override_sets(session, user.user_id)
    return {
        "role": user.role,
        "store_scope_mode": user.store_scope_mode,
        "store_ids": [],
        "extra_allow": sorted(allow),
        "extra_deny": sorted(deny),
        "effective_page_keys": list(effective_page_keys(session, user)),
    }


def required_page_key_for_api_path(path: str, method: str = "GET") -> str | None:
    if path.startswith("/api/v1/auth/") or path.startswith("/api/v1/meta/") or path == "/api/v1/feedback":
        return None
    if path.startswith("/api/v1/admin/accounts") or path.startswith("/api/v1/admin/access-control"):
        return "D02"
    if path.startswith("/api/v1/admin/feedback"):
        return "D09"
    if path.startswith("/api/v1/admin/product-type"):
        return "D04"
    if path.startswith("/api/v1/admin/sku-rules") or path.startswith("/api/v1/admin/non-commission"):
        return "D03"
    if path.startswith("/api/v1/admin/clue-allocation/headquarters") or path.startswith("/api/v1/admin/clue-allocation/eligible"):
        return "D08"
    if (
        path.startswith("/api/v1/admin/clue-allocation/records")
        or path.startswith("/api/v1/admin/clue-allocation/decisions")
        or path.startswith("/api/v1/admin/clue-allocation/audit-logs")
        or path.startswith("/api/v1/admin/clue-allocation/master-leads")
    ):
        return "D07"
    if path.startswith("/api/v1/admin/clue-allocation/trial") or path.startswith("/api/v1/admin/clue-allocation/cycles"):
        return "D06"
    if path.startswith("/api/v1/admin/clue-allocation"):
        return "D05"
    if path.startswith("/api/v1/admin/sync") or path.startswith("/api/v1/jobs"):
        return "D10"
    if path.startswith("/api/v1/admin"):
        return "D01"
    if path.startswith("/api/v1/clues/filters") or path.startswith("/api/v1/clues/overview"):
        return "A01"
    if path.startswith("/api/v1/clues/"):
        return "A02"
    if path.startswith("/api/v1/clues"):
        return "A01"
    if path.startswith("/api/v1/commission-rules"):
        return None
    if path.startswith("/api/v1/dashboard/store-ranking"):
        return "B01"
    if path.startswith("/api/v1/stores/") and "monthly-settlement" in path:
        return "B02"
    if path.startswith("/api/v1/order-details"):
        return "B03"
    if path.startswith("/api/v1/dashboard/sales"):
        return "C01"
    return "__UNREGISTERED__" if path.startswith("/api/v1/") else None
