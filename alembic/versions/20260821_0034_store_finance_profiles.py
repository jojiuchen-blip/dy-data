"""add immutable store finance profile snapshots

Revision ID: 20260821_0034
Revises: 20260821_0033
Create Date: 2026-08-21 13:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260821_0034"
down_revision = "20260821_0033"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    if op.get_bind().dialect.name == "sqlite":
        return sa.Column("id", sa.Integer(), nullable=False, autoincrement=True)
    return sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False, autoincrement=True)


def upgrade() -> None:
    """Create the immutable profile table and current-slot index."""
    op.create_table(
        "store_finance_profile",
        _id_column(),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("profile_type", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("store_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("sap_code", sa.String(length=128)),
        sa.Column("initial_sap_code", sa.String(length=128)),
        sa.Column("service_store_code", sa.String(length=128)),
        sa.Column("factory_confirmed", sa.Boolean()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("import_batch_id", sa.String(length=128), nullable=False),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gmt_modified", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_store_finance_profile"),
        sa.UniqueConstraint("profile_id", name="uk_store_finance_profile_id"),
        sa.UniqueConstraint("store_id", "profile_type", "version_no", name="uk_store_finance_profile_version"),
        sa.CheckConstraint("profile_type IN (1, 2)", name="ck_store_finance_profile_type"),
        sa.CheckConstraint("version_no > 0", name="ck_store_finance_profile_version"),
    )
    op.create_index("idx_store_finance_profile_current", "store_finance_profile", ["store_id", "profile_type"], unique=True, postgresql_where=sa.text("is_current"), sqlite_where=sa.text("is_current"))
    op.create_index("idx_store_finance_profile_batch", "store_finance_profile", ["import_batch_id"])


def downgrade() -> None:
    """Remove the profile table and its indexes."""
    op.drop_index("idx_store_finance_profile_batch", table_name="store_finance_profile")
    op.drop_index("idx_store_finance_profile_current", table_name="store_finance_profile")
    op.drop_table("store_finance_profile")
