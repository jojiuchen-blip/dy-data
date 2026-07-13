"""add immutable clue allocation rule versions

Revision ID: 20260712_0013
Revises: 20260712_0012
Create Date: 2026-07-12 21:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260712_0013"
down_revision = "20260712_0012"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _index_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if _has_table(table_name) and index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _json_server_default():
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def upgrade() -> None:
    if not _has_table("clue_store_groups"):
        op.create_table(
            "clue_store_groups",
            sa.Column("store_group_id", sa.Text(), primary_key=True),
            sa.Column("group_name", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("group_name", name="uq_clue_store_groups_group_name"),
        )

    if not _has_table("clue_allocation_rules"):
        op.create_table(
            "clue_allocation_rules",
            sa.Column("rule_id", sa.Text(), primary_key=True),
            sa.Column("rule_name", sa.Text(), nullable=False),
            sa.Column("scope_type", sa.String(length=32), nullable=False),
            sa.Column("scope_key", sa.Text(), nullable=False),
            sa.Column("scope_city_code", sa.Text()),
            sa.Column("scope_store_group_id", sa.Text()),
            sa.Column("scope_anchor_store_id", sa.Text()),
            sa.Column("created_by", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("scope_key", name="uq_clue_allocation_rules_scope_key"),
        )
    for index_name, columns in (
        ("ix_clue_allocation_rules_scope_type", ["scope_type"]),
        ("ix_clue_allocation_rules_scope_city_code", ["scope_city_code"]),
        ("ix_clue_allocation_rules_scope_store_group_id", ["scope_store_group_id"]),
        ("ix_clue_allocation_rules_scope_anchor_store_id", ["scope_anchor_store_id"]),
        ("ix_clue_allocation_rules_scope", ["scope_type", "scope_key"]),
    ):
        _create_index_if_missing(index_name, "clue_allocation_rules", columns)

    if not _has_table("clue_allocation_rule_versions"):
        op.create_table(
            "clue_allocation_rule_versions",
            sa.Column("rule_version_id", sa.Text(), primary_key=True),
            sa.Column(
                "rule_id",
                sa.Text(),
                sa.ForeignKey("clue_allocation_rules.rule_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("auto_expiry_enabled", sa.Boolean()),
            sa.Column("first_follow_up_sla_hours", sa.Integer()),
            sa.Column("protection_days", sa.Integer()),
            sa.Column("conversion_weight", sa.Numeric(6, 4)),
            sa.Column("follow_24h_weight", sa.Numeric(6, 4)),
            sa.Column("lookback_days", sa.Integer()),
            sa.Column("min_samples", sa.Integer()),
            sa.Column("created_by", sa.Text()),
            sa.Column("updated_by", sa.Text()),
            sa.Column("published_by", sa.Text()),
            sa.Column("retired_by", sa.Text()),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("retired_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("rule_id", "version_no", name="uq_clue_allocation_rule_versions_rule_version"),
        )
    for index_name, columns in (
        ("ix_clue_allocation_rule_versions_rule_id", ["rule_id"]),
        ("ix_clue_allocation_rule_versions_status", ["status"]),
        ("ix_clue_allocation_rule_versions_published_at", ["published_at"]),
        ("ix_clue_allocation_rule_versions_retired_at", ["retired_at"]),
        ("ix_clue_allocation_rule_versions_rule_status", ["rule_id", "status"]),
    ):
        _create_index_if_missing(index_name, "clue_allocation_rule_versions", columns)
    if (
        _has_table("clue_allocation_rule_versions")
        and "uq_clue_allocation_rule_versions_published" not in _index_names("clue_allocation_rule_versions")
    ):
        op.create_index(
            "uq_clue_allocation_rule_versions_published",
            "clue_allocation_rule_versions",
            ["rule_id"],
            unique=True,
            sqlite_where=sa.text("status = 'published'"),
            postgresql_where=sa.text("status = 'published'"),
        )

    if not _has_table("clue_allocation_strategy_configs"):
        op.create_table(
            "clue_allocation_strategy_configs",
            sa.Column("strategy_config_id", sa.Text(), primary_key=True),
            sa.Column(
                "rule_version_id",
                sa.Text(),
                sa.ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("strategy_type", sa.String(length=64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("execution_order", sa.Integer(), nullable=False),
            sa.Column("params_json", _json_type(), nullable=False, server_default=_json_server_default()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    for index_name, columns in (
        ("ix_clue_allocation_strategy_configs_rule_version_id", ["rule_version_id"]),
        ("ix_clue_allocation_strategy_configs_version_order", ["rule_version_id", "execution_order"]),
    ):
        _create_index_if_missing(index_name, "clue_allocation_strategy_configs", columns)

    if not _has_table("clue_store_group_members"):
        op.create_table(
            "clue_store_group_members",
            sa.Column(
                "store_group_id",
                sa.Text(),
                sa.ForeignKey("clue_store_groups.store_group_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "store_id",
                sa.Text(),
                sa.ForeignKey("dim_stores.store_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("store_id", name="uq_clue_store_group_members_store_id"),
        )
    _create_index_if_missing("ix_clue_store_group_members_store_id", "clue_store_group_members", ["store_id"])

    if not _has_table("clue_lead_rule_version_bindings"):
        op.create_table(
            "clue_lead_rule_version_bindings",
            sa.Column("lead_key", sa.Text(), primary_key=True),
            sa.Column(
                "rule_version_id",
                sa.Text(),
                sa.ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("scope_type", sa.String(length=32), nullable=False),
            sa.Column("scope_key", sa.Text(), nullable=False),
            sa.Column(
                "scope_resolution_snapshot",
                _json_type(),
                nullable=False,
                server_default=_json_server_default(),
            ),
            sa.Column(
                "rule_version_snapshot",
                _json_type(),
                nullable=False,
                server_default=_json_server_default(),
            ),
            sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing(
        "ix_clue_lead_rule_version_bindings_rule_version",
        "clue_lead_rule_version_bindings",
        ["rule_version_id"],
    )
    _create_index_if_missing(
        "ix_clue_lead_rule_version_bindings_scope_type",
        "clue_lead_rule_version_bindings",
        ["scope_type"],
    )


def downgrade() -> None:
    for table_name in (
        "clue_lead_rule_version_bindings",
        "clue_store_group_members",
        "clue_allocation_strategy_configs",
        "clue_allocation_rule_versions",
        "clue_allocation_rules",
        "clue_store_groups",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
