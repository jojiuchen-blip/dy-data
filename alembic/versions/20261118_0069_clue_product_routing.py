"""Freeze new-ingress product routing and publish independently versioned lists.

Existing leads retain NULL routing mode and their existing rule binding.
No configuration or publication enables routing automatically.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261118_0069"
down_revision = "20261117_0068"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NEW_TABLES = (
    "clue_product_routing_configs", "clue_product_store_list_versions",
    "clue_product_store_list_members", "clue_product_routing_grants",
    "clue_product_routing_operations",
)


def upgrade():
    op.add_column("clue_master_leads", sa.Column("routing_mode", sa.String(16)))
    op.add_column("clue_master_leads", sa.Column("routing_product_id", sa.Text()))
    op.create_index("ix_clue_master_leads_routing_mode", "clue_master_leads", ["routing_mode"])
    op.create_index("ix_clue_master_leads_routing_product_id", "clue_master_leads", ["routing_product_id"])
    op.add_column("clue_assignment_rounds", sa.Column("appointment_at", sa.DateTime(timezone=True)))
    op.add_column("clue_assignment_rounds", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.add_column("clue_follow_up_records", sa.Column("appointment_at", sa.DateTime(timezone=True)))
    op.add_column("clue_allocation_rule_versions", sa.Column("snapshot", JSON_TYPE, nullable=False, server_default="{}"))
    op.create_table(
        "clue_product_routing_configs",
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column("routing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rule_id", sa.Text(), sa.ForeignKey("clue_allocation_rules.rule_id", ondelete="RESTRICT")),
        sa.Column("rule_version_id", sa.Text(), sa.ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="RESTRICT")),
        sa.Column("active_list_version_id", sa.Text()),
        sa.Column("updated_by", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "clue_product_store_list_versions",
        sa.Column("list_version_id", sa.Text(), primary_key=True),
        sa.Column("product_id", sa.Text(), sa.ForeignKey("clue_product_routing_configs.product_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("published_by", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_id", "version_no", name="uq_clue_product_store_list_version"),
    )
    op.create_index("ix_clue_product_store_list_versions_product_id", "clue_product_store_list_versions", ["product_id"])
    op.create_table(
        "clue_product_store_list_members",
        sa.Column("list_version_id", sa.Text(), sa.ForeignKey("clue_product_store_list_versions.list_version_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("store_id", sa.Text(), sa.ForeignKey("dim_stores.store_id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_table(
        "clue_product_routing_grants",
        sa.Column("product_id", sa.Text(), sa.ForeignKey("clue_product_routing_configs.product_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.user_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_clue_product_routing_grants_user_id", "clue_product_routing_grants", ["user_id"])
    op.create_table(
        "clue_product_routing_operations",
        sa.Column("actor_key", sa.Text(), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), primary_key=True),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("result_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    bind = op.get_bind()
    for table in NEW_TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Product routing history exists; preserve bindings and use a forward migration.")
    if bind.execute(sa.text("SELECT 1 FROM clue_master_leads WHERE routing_mode IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("New-ingress routing bindings exist; use a forward migration.")
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    op.drop_column("clue_allocation_rule_versions", "snapshot")
    op.drop_column("clue_follow_up_records", "appointment_at")
    op.drop_column("clue_assignment_rounds", "closed_at")
    op.drop_column("clue_assignment_rounds", "appointment_at")
    op.drop_index("ix_clue_master_leads_routing_product_id", table_name="clue_master_leads")
    op.drop_index("ix_clue_master_leads_routing_mode", table_name="clue_master_leads")
    op.drop_column("clue_master_leads", "routing_product_id")
    op.drop_column("clue_master_leads", "routing_mode")
