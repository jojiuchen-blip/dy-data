"""add clue allocation cycles and headquarters pool audit

Revision ID: 20260712_0016
Revises: 20260712_0015
Create Date: 2026-07-12 23:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260712_0016"
down_revision = "20260712_0015"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _index_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _column_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _foreign_key_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {foreign_key.get("name") for foreign_key in inspect(op.get_bind()).get_foreign_keys(table_name)}


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _json_object_default():
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def _json_array_default():
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("'[]'::jsonb")
    return sa.text("'[]'")


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], **kwargs) -> None:
    if _has_table(table_name) and index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, **kwargs)


def _drop_index_if_present(index_name: str, table_name: str) -> None:
    if _has_table(table_name) and index_name in _index_names(table_name):
        op.drop_index(index_name, table_name=table_name)


def _backfill_existing_headquarters_pool_entries() -> None:
    if not _has_table("clue_master_leads") or not _has_table("clue_headquarters_pool_entries"):
        return
    snapshot_literal = "'{}'::jsonb" if op.get_bind().dialect.name == "postgresql" else "'{}'"
    op.execute(
        sa.text(
            f"""
            INSERT INTO clue_headquarters_pool_entries (
                headquarters_pool_entry_id,
                lead_key,
                status,
                reason,
                entered_at,
                source_snapshot,
                created_at,
                updated_at
            )
            SELECT
                'headquarters-pool-legacy-' || lead.lead_key,
                lead.lead_key,
                'active',
                COALESCE(NULLIF(lead.anchor_unavailable_reason, ''), 'legacy_headquarters_pool'),
                COALESCE(lead.updated_at, lead.first_seen_at, lead.created_at),
                {snapshot_literal},
                COALESCE(lead.created_at, lead.updated_at, lead.first_seen_at),
                COALESCE(lead.updated_at, lead.created_at, lead.first_seen_at)
            FROM clue_master_leads lead
            WHERE lead.lifecycle_status = 'active'
              AND lead.pool_location = 'headquarters_pool'
              AND NOT EXISTS (
                  SELECT 1
                  FROM clue_headquarters_pool_entries existing
                  WHERE existing.lead_key = lead.lead_key
                    AND existing.status = 'active'
              )
            """
        )
    )


def upgrade() -> None:
    if not _has_table("clue_allocation_cycles"):
        op.create_table(
            "clue_allocation_cycles",
            sa.Column("allocation_cycle_id", sa.Text(), primary_key=True),
            sa.Column("cycle_type", sa.String(length=32), nullable=False),
            sa.Column("execution_mode", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
            sa.Column("parent_cycle_id", sa.Text()),
            sa.Column("selected_lead_keys", _json_type(), nullable=False, server_default=_json_array_default()),
            sa.Column("requested_lead_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active_lead_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("planned_impact_json", _json_type(), nullable=False, server_default=_json_object_default()),
            sa.Column("actual_impact_json", _json_type(), nullable=False, server_default=_json_object_default()),
            sa.Column("actor", sa.Text()),
            sa.Column("privileged_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("preview_token_hash", sa.String(length=64)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("executed_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
        )
    if _has_table("clue_allocation_cycles") and "preview_token_hash" not in _column_names(
        "clue_allocation_cycles"
    ):
        with op.batch_alter_table("clue_allocation_cycles", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("preview_token_hash", sa.String(length=64)))
    for index_name, columns in (
        ("ix_clue_allocation_cycles_cycle_type", ["cycle_type"]),
        ("ix_clue_allocation_cycles_execution_mode", ["execution_mode"]),
        ("ix_clue_allocation_cycles_status", ["status"]),
        ("ix_clue_allocation_cycles_parent_cycle_id", ["parent_cycle_id"]),
        ("ix_clue_allocation_cycles_executed_at", ["executed_at"]),
        ("ix_clue_allocation_cycles_completed_at", ["completed_at"]),
        ("ix_clue_allocation_cycles_mode_status", ["execution_mode", "status"]),
        ("ix_clue_allocation_cycles_parent", ["parent_cycle_id"]),
    ):
        _create_index_if_missing(index_name, "clue_allocation_cycles", list(columns))
    _create_index_if_missing(
        "uq_clue_allocation_cycles_preview_token_hash",
        "clue_allocation_cycles",
        ["preview_token_hash"],
        unique=True,
    )

    round_columns = _column_names("clue_assignment_rounds")
    round_foreign_keys = _foreign_key_names("clue_assignment_rounds")
    if _has_table("clue_assignment_rounds") and "allocation_cycle_id" not in round_columns:
        with op.batch_alter_table("clue_assignment_rounds", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("allocation_cycle_id", sa.Text()))
            batch_op.create_foreign_key(
                "fk_clue_assignment_rounds_allocation_cycle",
                "clue_allocation_cycles",
                ["allocation_cycle_id"],
                ["allocation_cycle_id"],
                ondelete="RESTRICT",
            )
    elif (
        _has_table("clue_assignment_rounds")
        and "fk_clue_assignment_rounds_allocation_cycle" not in round_foreign_keys
    ):
        with op.batch_alter_table("clue_assignment_rounds", recreate="always") as batch_op:
            batch_op.create_foreign_key(
                "fk_clue_assignment_rounds_allocation_cycle",
                "clue_allocation_cycles",
                ["allocation_cycle_id"],
                ["allocation_cycle_id"],
                ondelete="RESTRICT",
            )
    _create_index_if_missing(
        "ix_clue_assignment_rounds_allocation_cycle_id",
        "clue_assignment_rounds",
        ["allocation_cycle_id"],
    )

    if not _has_table("clue_headquarters_pool_entries"):
        op.create_table(
            "clue_headquarters_pool_entries",
            sa.Column("headquarters_pool_entry_id", sa.Text(), primary_key=True),
            sa.Column(
                "lead_key",
                sa.Text(),
                sa.ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("closed_at", sa.DateTime(timezone=True)),
            sa.Column("close_reason", sa.Text()),
            sa.Column("source_assignment_round_id", sa.Text()),
            sa.Column(
                "source_decision_id",
                sa.Text(),
                sa.ForeignKey("clue_allocation_decisions.decision_id", ondelete="RESTRICT"),
            ),
            sa.Column(
                "source_rule_version_id",
                sa.Text(),
                sa.ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="RESTRICT"),
            ),
            sa.Column(
                "allocation_cycle_id",
                sa.Text(),
                sa.ForeignKey("clue_allocation_cycles.allocation_cycle_id", ondelete="RESTRICT"),
            ),
            sa.Column("source_snapshot", _json_type(), nullable=False, server_default=_json_object_default()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    for index_name, columns in (
        ("ix_clue_headquarters_pool_entries_lead_key", ["lead_key"]),
        ("ix_clue_headquarters_pool_entries_status", ["status"]),
        ("ix_clue_headquarters_pool_entries_entered_at", ["entered_at"]),
        ("ix_clue_headquarters_pool_entries_closed_at", ["closed_at"]),
        ("ix_clue_headquarters_pool_entries_source_assignment_round_id", ["source_assignment_round_id"]),
        ("ix_clue_headquarters_pool_entries_source_decision_id", ["source_decision_id"]),
        ("ix_clue_headquarters_pool_entries_source_rule_version_id", ["source_rule_version_id"]),
        ("ix_clue_headquarters_pool_entries_allocation_cycle_id", ["allocation_cycle_id"]),
        ("ix_clue_headquarters_pool_entries_lead_status", ["lead_key", "status"]),
        ("ix_clue_headquarters_pool_entries_entered", ["entered_at"]),
    ):
        _create_index_if_missing(index_name, "clue_headquarters_pool_entries", list(columns))
    _create_index_if_missing(
        "uq_clue_headquarters_pool_entries_active_lead",
        "clue_headquarters_pool_entries",
        ["lead_key"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )
    _backfill_existing_headquarters_pool_entries()

    if not _has_table("clue_allocation_audit_logs"):
        op.create_table(
            "clue_allocation_audit_logs",
            sa.Column("audit_log_id", sa.Text(), primary_key=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column(
                "allocation_cycle_id",
                sa.Text(),
                sa.ForeignKey("clue_allocation_cycles.allocation_cycle_id", ondelete="RESTRICT"),
            ),
            sa.Column("actor", sa.Text()),
            sa.Column("privileged_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("before_snapshot", _json_type(), nullable=False, server_default=_json_object_default()),
            sa.Column("after_snapshot", _json_type(), nullable=False, server_default=_json_object_default()),
            sa.Column("detail_json", _json_type(), nullable=False, server_default=_json_object_default()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    for index_name, columns in (
        ("ix_clue_allocation_audit_logs_event_type", ["event_type"]),
        ("ix_clue_allocation_audit_logs_allocation_cycle_id", ["allocation_cycle_id"]),
        ("ix_clue_allocation_audit_logs_created_at", ["created_at"]),
        ("ix_clue_allocation_audit_logs_cycle_created", ["allocation_cycle_id", "created_at"]),
        ("ix_clue_allocation_audit_logs_event_created", ["event_type", "created_at"]),
    ):
        _create_index_if_missing(index_name, "clue_allocation_audit_logs", list(columns))


def downgrade() -> None:
    if _has_table("clue_allocation_audit_logs"):
        for index_name in (
            "ix_clue_allocation_audit_logs_event_created",
            "ix_clue_allocation_audit_logs_cycle_created",
            "ix_clue_allocation_audit_logs_created_at",
            "ix_clue_allocation_audit_logs_allocation_cycle_id",
            "ix_clue_allocation_audit_logs_event_type",
        ):
            _drop_index_if_present(index_name, "clue_allocation_audit_logs")
        op.drop_table("clue_allocation_audit_logs")

    if _has_table("clue_headquarters_pool_entries"):
        for index_name in (
            "uq_clue_headquarters_pool_entries_active_lead",
            "ix_clue_headquarters_pool_entries_entered",
            "ix_clue_headquarters_pool_entries_lead_status",
            "ix_clue_headquarters_pool_entries_allocation_cycle_id",
            "ix_clue_headquarters_pool_entries_source_rule_version_id",
            "ix_clue_headquarters_pool_entries_source_decision_id",
            "ix_clue_headquarters_pool_entries_source_assignment_round_id",
            "ix_clue_headquarters_pool_entries_closed_at",
            "ix_clue_headquarters_pool_entries_entered_at",
            "ix_clue_headquarters_pool_entries_status",
            "ix_clue_headquarters_pool_entries_lead_key",
        ):
            _drop_index_if_present(index_name, "clue_headquarters_pool_entries")
        op.drop_table("clue_headquarters_pool_entries")

    if _has_table("clue_assignment_rounds"):
        _drop_index_if_present(
            "ix_clue_assignment_rounds_allocation_cycle_id",
            "clue_assignment_rounds",
        )
        round_columns = _column_names("clue_assignment_rounds")
        round_foreign_keys = _foreign_key_names("clue_assignment_rounds")
        if "allocation_cycle_id" in round_columns:
            with op.batch_alter_table("clue_assignment_rounds", recreate="always") as batch_op:
                if "fk_clue_assignment_rounds_allocation_cycle" in round_foreign_keys:
                    batch_op.drop_constraint(
                        "fk_clue_assignment_rounds_allocation_cycle",
                        type_="foreignkey",
                    )
                batch_op.drop_column("allocation_cycle_id")

    if _has_table("clue_allocation_cycles"):
        for index_name in (
            "ix_clue_allocation_cycles_parent",
            "uq_clue_allocation_cycles_preview_token_hash",
            "ix_clue_allocation_cycles_mode_status",
            "ix_clue_allocation_cycles_completed_at",
            "ix_clue_allocation_cycles_executed_at",
            "ix_clue_allocation_cycles_parent_cycle_id",
            "ix_clue_allocation_cycles_status",
            "ix_clue_allocation_cycles_execution_mode",
            "ix_clue_allocation_cycles_cycle_type",
        ):
            _drop_index_if_present(index_name, "clue_allocation_cycles")
        op.drop_table("clue_allocation_cycles")
