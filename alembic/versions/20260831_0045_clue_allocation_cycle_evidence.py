"""add allocation cycle evidence and idempotency fields

Revision ID: 20260831_0045
Revises: 20260830_0044
Create Date: 2026-08-31 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260831_0045"
down_revision = "20260830_0044"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _json_object_default():
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def upgrade() -> None:
    with op.batch_alter_table("clue_allocation_cycles") as batch_op:
        batch_op.add_column(sa.Column("actor_user_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("actor_username_snapshot", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("preview_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("idempotency_request_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "request_scope_snapshot",
                _json_type(),
                nullable=False,
                server_default=_json_object_default(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "error_summary",
                _json_type(),
                nullable=False,
                server_default=_json_object_default(),
            )
        )
        batch_op.add_column(sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"))

    op.create_index(
        "uq_clue_allocation_cycles_idempotency_key_hash",
        "clue_allocation_cycles",
        ["idempotency_key_hash"],
        unique=True,
    )
    op.create_index(
        "ix_clue_allocation_cycles_actor_user",
        "clue_allocation_cycles",
        ["actor_user_id", "created_at"],
    )

    with op.batch_alter_table("clue_allocation_audit_logs") as batch_op:
        batch_op.add_column(sa.Column("actor_user_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("actor_username_snapshot", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("actor_role_snapshot", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column(
                "actor_scope_snapshot",
                _json_type(),
                nullable=False,
                server_default=_json_object_default(),
            )
        )
        batch_op.add_column(sa.Column("request_id", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("result_status", sa.String(length=32), nullable=False, server_default="success")
        )
        batch_op.add_column(sa.Column("reason_code", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_clue_allocation_audit_logs_actor_created",
        "clue_allocation_audit_logs",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_clue_allocation_audit_logs_request_id",
        "clue_allocation_audit_logs",
        ["request_id"],
    )

    op.create_table(
        "clue_allocation_cycle_items",
        sa.Column("cycle_item_id", sa.Text(), primary_key=True),
        sa.Column(
            "allocation_cycle_id",
            sa.Text(),
            sa.ForeignKey("clue_allocation_cycles.allocation_cycle_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("lead_key", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("item_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("initial_pool_location", sa.String(length=32), nullable=True),
        sa.Column("rule_binding_id", sa.Text(), nullable=True),
        sa.Column("decision_id", sa.Text(), nullable=True),
        sa.Column("assignment_round_id", sa.Text(), nullable=True),
        sa.Column("headquarters_pool_entry_id", sa.Text(), nullable=True),
        sa.Column("outcome_reason", sa.String(length=128), nullable=True),
        sa.Column(
            "precondition_snapshot",
            _json_type(),
            nullable=False,
            server_default=_json_object_default(),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_detail", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "allocation_cycle_id",
            "lead_key",
            name="uq_clue_allocation_cycle_items_cycle_lead",
        ),
        sa.UniqueConstraint(
            "allocation_cycle_id",
            "sequence_no",
            name="uq_clue_allocation_cycle_items_cycle_sequence",
        ),
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_cycle_status",
        "clue_allocation_cycle_items",
        ["allocation_cycle_id", "item_status"],
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_lead_created",
        "clue_allocation_cycle_items",
        ["lead_key", "created_at"],
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_order_id",
        "clue_allocation_cycle_items",
        ["order_id"],
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_decision_id",
        "clue_allocation_cycle_items",
        ["decision_id"],
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_allocation_cycle_id",
        "clue_allocation_cycle_items",
        ["allocation_cycle_id"],
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_lead_key",
        "clue_allocation_cycle_items",
        ["lead_key"],
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_item_status",
        "clue_allocation_cycle_items",
        ["item_status"],
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_assignment_round_id",
        "clue_allocation_cycle_items",
        ["assignment_round_id"],
    )
    op.create_index(
        "ix_clue_allocation_cycle_items_headquarters_pool_entry_id",
        "clue_allocation_cycle_items",
        ["headquarters_pool_entry_id"],
    )

    op.create_table(
        "clue_allocation_candidates",
        sa.Column("candidate_id", sa.Text(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Text(),
            sa.ForeignKey("clue_allocation_decisions.decision_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lead_key", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("strategy_type", sa.String(length=64), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("store_name_snapshot", sa.Text(), nullable=False),
        sa.Column("city_code", sa.String(length=64), nullable=True),
        sa.Column("eligibility_status", sa.String(length=32), nullable=False),
        sa.Column("exclusion_reason_code", sa.String(length=128), nullable=True),
        sa.Column("exclusion_detail", sa.String(length=500), nullable=True),
        sa.Column("is_sales_store", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_historical_assignment", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_serviceable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("distance_km", sa.Numeric(10, 3), nullable=True),
        sa.Column(
            "store_location_snapshot",
            _json_type(),
            nullable=False,
            server_default=_json_object_default(),
        ),
        sa.Column("score_snapshot_id", sa.Text(), nullable=True),
        sa.Column("conversion_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("follow_24h_rate", sa.Numeric(10, 6), nullable=True),
        sa.Column("store_weight", sa.Numeric(8, 4), nullable=True),
        sa.Column("composite_score", sa.Numeric(12, 6), nullable=True),
        sa.Column("rank_no", sa.Integer(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "sort_key_snapshot",
            _json_type(),
            nullable=False,
            server_default=_json_object_default(),
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "decision_id",
            "store_id",
            name="uq_clue_allocation_candidates_decision_store",
        ),
    )
    op.create_index(
        "ix_clue_allocation_candidates_decision_rank",
        "clue_allocation_candidates",
        ["decision_id", "eligibility_status", "rank_no"],
    )
    op.create_index(
        "ix_clue_allocation_candidates_store_evaluated",
        "clue_allocation_candidates",
        ["store_id", "evaluated_at"],
    )
    op.create_index(
        "ix_clue_allocation_candidates_exclusion",
        "clue_allocation_candidates",
        ["exclusion_reason_code", "evaluated_at"],
    )
    for column_name in (
        "decision_id",
        "lead_key",
        "order_id",
        "strategy_type",
        "store_id",
        "eligibility_status",
        "exclusion_reason_code",
        "score_snapshot_id",
        "composite_score",
    ):
        op.create_index(
            f"ix_clue_allocation_candidates_{column_name}",
            "clue_allocation_candidates",
            [column_name],
        )


def downgrade() -> None:
    op.drop_table("clue_allocation_candidates")
    op.drop_table("clue_allocation_cycle_items")
    op.drop_index(
        "ix_clue_allocation_audit_logs_request_id",
        table_name="clue_allocation_audit_logs",
    )
    op.drop_index(
        "ix_clue_allocation_audit_logs_actor_created",
        table_name="clue_allocation_audit_logs",
    )
    with op.batch_alter_table("clue_allocation_audit_logs") as batch_op:
        batch_op.drop_column("reason_code")
        batch_op.drop_column("result_status")
        batch_op.drop_column("request_id")
        batch_op.drop_column("actor_scope_snapshot")
        batch_op.drop_column("actor_role_snapshot")
        batch_op.drop_column("actor_username_snapshot")
        batch_op.drop_column("actor_user_id")
    op.drop_index(
        "ix_clue_allocation_cycles_actor_user",
        table_name="clue_allocation_cycles",
    )
    op.drop_index(
        "uq_clue_allocation_cycles_idempotency_key_hash",
        table_name="clue_allocation_cycles",
    )
    with op.batch_alter_table("clue_allocation_cycles") as batch_op:
        batch_op.drop_column("state_version")
        batch_op.drop_column("error_summary")
        batch_op.drop_column("request_scope_snapshot")
        batch_op.drop_column("idempotency_request_hash")
        batch_op.drop_column("idempotency_key_hash")
        batch_op.drop_column("preview_expires_at")
        batch_op.drop_column("actor_username_snapshot")
        batch_op.drop_column("actor_user_id")
