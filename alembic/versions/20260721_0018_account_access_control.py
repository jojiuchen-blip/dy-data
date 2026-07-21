"""add account page permissions, store scopes and audit logs

Revision ID: 20260721_0018
Revises: 20260713_0017
Create Date: 2026-07-21 12:00:00
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260721_0018"
down_revision = "20260713_0017"
branch_labels = None
depends_on = None


PAGES = (
    ("A01", "线索看板", "线索中心", ("/clues",)),
    ("A02", "线索明细", "线索中心", ("/clues/:id",)),
    ("B01", "全国门店榜单", "订单分佣", ("/ranking",)),
    ("B02", "单店结算", "订单分佣", ("/settlement",)),
    ("B03", "订单费用明细", "订单分佣", ("/order-details",)),
    ("C01", "核销表现", "核销表现", ("/sales-dashboard",)),
    ("D01", "后台首页", "管理后台", ("/admin",)),
    ("D02", "账号管理", "管理后台", ("/admin/accounts",)),
    ("D03", "分佣规则", "管理后台", ("/admin/rules", "/rule-admin")),
    ("D04", "商品口径", "管理后台", ("/admin/product-types",)),
    ("D05", "线索分配规则", "管理后台", ("/admin/clue-allocation", "/admin/clue-allocation/rules")),
    ("D06", "分配试运行", "管理后台", ("/admin/clue-allocation/trial",)),
    ("D07", "分配记录", "管理后台", ("/admin/clue-allocation/records",)),
    ("D08", "总部线索池", "管理后台", ("/admin/clue-allocation/headquarters",)),
    ("D09", "用户建议", "管理后台", ("/admin/feedback",)),
    ("D10", "数据同步", "管理后台", ("/admin/sync", "/sync-admin")),
)
STORE_DEFAULTS = {"A01", "A02", "B01", "B02", "B03", "C01"}


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("users", "store_scope_mode"):
        op.add_column(
            "users",
            sa.Column("store_scope_mode", sa.String(16), nullable=False, server_default="specified"),
        )
        op.create_index("ix_users_store_scope_mode", "users", ["store_scope_mode"])
    if not _has_column("users", "auth_version"):
        op.add_column(
            "users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1")
        )

    if not _has_table("access_pages"):
        op.create_table(
            "access_pages",
            sa.Column("page_key", sa.String(8), primary_key=True),
            sa.Column("page_name", sa.Text(), nullable=False),
            sa.Column("module_name", sa.Text(), nullable=False),
            sa.Column("route_patterns", sa.JSON(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_access_pages_is_active", "access_pages", ["is_active"])

    if not _has_table("role_page_permissions"):
        op.create_table(
            "role_page_permissions",
            sa.Column("role", sa.String(32), primary_key=True),
            sa.Column(
                "page_key",
                sa.String(8),
                sa.ForeignKey("access_pages.page_key", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("is_allowed", sa.Boolean(), nullable=False),
            sa.Column("updated_by", sa.Text()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not _has_table("user_page_permission_overrides"):
        op.create_table(
            "user_page_permission_overrides",
            sa.Column(
                "user_id", sa.Text(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
            ),
            sa.Column(
                "page_key",
                sa.String(8),
                sa.ForeignKey("access_pages.page_key", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("effect", sa.String(8), nullable=False),
            sa.Column("updated_by", sa.Text()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_user_page_permission_overrides_page_key",
            "user_page_permission_overrides",
            ["page_key"],
        )

    if not _has_table("account_permission_audit_logs"):
        op.create_table(
            "account_permission_audit_logs",
            sa.Column("audit_id", sa.Text(), primary_key=True),
            sa.Column("action", sa.String(96), nullable=False),
            sa.Column("result", sa.String(16), nullable=False, server_default="success"),
            sa.Column("actor_user_id", sa.Text()),
            sa.Column("actor_username", sa.Text(), nullable=False),
            sa.Column("actor_role", sa.String(32), nullable=False),
            sa.Column("target_user_id", sa.Text()),
            sa.Column("target_username", sa.Text()),
            sa.Column("before_json", sa.JSON(), nullable=False),
            sa.Column("after_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_account_permission_audit_logs_action", "account_permission_audit_logs", ["action"])
        op.create_index("ix_account_permission_audit_logs_created_at", "account_permission_audit_logs", ["created_at"])
        op.create_index("ix_account_permission_audit_logs_target_user_id", "account_permission_audit_logs", ["target_user_id"])
        op.create_index("ix_account_permission_audit_logs_actor_user_id", "account_permission_audit_logs", ["actor_user_id"])

    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    connection.execute(text("UPDATE users SET role = 'highest_admin' WHERE role = 'admin'"))
    connection.execute(text("UPDATE users SET role = 'admin' WHERE role = 'viewer'"))
    connection.execute(
        text("UPDATE users SET store_scope_mode = 'all' WHERE role IN ('highest_admin', 'admin')")
    )
    connection.execute(
        text(
            "UPDATE users SET store_scope_mode = CASE "
            "WHEN EXISTS (SELECT 1 FROM user_store_scopes s WHERE s.user_id = users.user_id) "
            "THEN 'specified' ELSE 'none' END WHERE role = 'store'"
        )
    )
    access_pages = sa.table(
        "access_pages",
        sa.column("page_key", sa.String()),
        sa.column("page_name", sa.Text()),
        sa.column("module_name", sa.Text()),
        sa.column("route_patterns", sa.JSON()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    role_permissions = sa.table(
        "role_page_permissions",
        sa.column("role", sa.String()),
        sa.column("page_key", sa.String()),
        sa.column("is_allowed", sa.Boolean()),
        sa.column("updated_by", sa.Text()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    connection.execute(
        access_pages.insert(),
        [
            {
                "page_key": key,
                "page_name": name,
                "module_name": module,
                "route_patterns": list(routes),
                "sort_order": index,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for index, (key, name, module, routes) in enumerate(PAGES, start=1)
        ],
    )
    connection.execute(
        role_permissions.insert(),
        [
            {
                "role": role,
                "page_key": key,
                "is_allowed": allowed,
                "updated_by": "migration",
                "updated_at": now,
            }
            for key, _name, _module, _routes in PAGES
            for role, allowed in (("admin", True), ("store", key in STORE_DEFAULTS))
        ],
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("UPDATE users SET role = 'viewer' WHERE role = 'admin'"))
    connection.execute(text("UPDATE users SET role = 'admin' WHERE role = 'highest_admin'"))
    if _has_table("account_permission_audit_logs"):
        op.drop_table("account_permission_audit_logs")
    if _has_table("user_page_permission_overrides"):
        op.drop_table("user_page_permission_overrides")
    if _has_table("role_page_permissions"):
        op.drop_table("role_page_permissions")
    if _has_table("access_pages"):
        op.drop_table("access_pages")
    if _has_column("users", "auth_version"):
        op.drop_column("users", "auth_version")
    if _has_column("users", "store_scope_mode"):
        op.drop_index("ix_users_store_scope_mode", table_name="users")
        op.drop_column("users", "store_scope_mode")
