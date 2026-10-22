"""Unify administrator identities without widening their persisted data scopes.

Revision ID: 20261022_0064
Revises: 20261019_0063
"""

from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "20261022_0064"
down_revision = "20261019_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, autoload_with=connection)
    overrides = sa.Table("user_page_permission_overrides", metadata, autoload_with=connection)
    audits = sa.Table("account_permission_audit_logs", metadata, autoload_with=connection)
    now = datetime.now(timezone.utc)
    for user in connection.execute(sa.select(users).where(
        users.c.role.in_(("highest_admin", "admin", "viewer")),
    )).mappings():
        if connection.scalar(sa.select(audits.c.audit_id).where(
            audits.c.action == "account.administrator_unified",
            audits.c.target_user_id == user["user_id"],
        ).limit(1)):
            continue
        old_overrides = list(connection.execute(sa.select(overrides).where(
            overrides.c.user_id == user["user_id"],
        )).mappings())
        before = {
            "role": user["role"], "store_scope_mode": user["store_scope_mode"],
            "org_scope": user["org_scope"], "status": user["status"],
            "auth_version": user["auth_version"], "auth_generation": user["auth_generation"],
            "page_overrides": [{
                "page_key": row["page_key"], "effect": row["effect"],
                "updated_by": row["updated_by"], "updated_at": str(row["updated_at"]),
            } for row in old_overrides],
        }
        connection.execute(audits.insert().values(
            audit_id=uuid4().hex, action="account.administrator_unified", result="success",
            actor_user_id=None, actor_username="migration-20261022-0064", actor_role="system",
            target_user_id=user["user_id"], target_username=user["username"],
            before_json=before,
            after_json={"role": "admin", "permissions_fixed": True,
                        "auth_version": user["auth_version"] + 1,
                        "auth_generation": user["auth_generation"] + 1},
            created_at=now,
        ))
        connection.execute(users.update().where(users.c.user_id == user["user_id"]).values(
            role="admin", auth_version=user["auth_version"] + 1,
            auth_generation=user["auth_generation"] + 1,
        ))
        connection.execute(overrides.delete().where(overrides.c.user_id == user["user_id"]))


def downgrade() -> None:
    connection = op.get_bind()
    # Roles and overrides cannot be inferred after subsequent account changes.
    # Retain the durable before-images and require a reviewed backup recovery.
    populated = connection.scalar(sa.text(
        "SELECT COUNT(*) FROM account_permission_audit_logs "
        "WHERE action = 'account.administrator_unified'"
    ))
    if populated:
        raise RuntimeError("Administrator migration contains account history; use reviewed backup recovery")
