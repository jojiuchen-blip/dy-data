"""add clue allocation decisions and self-owned round namespace

Revision ID: 20260712_0014
Revises: 20260712_0013
Create Date: 2026-07-12 22:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260712_0014"
down_revision = "20260712_0013"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _unique_constraint_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {constraint["name"] for constraint in inspect(op.get_bind()).get_unique_constraints(table_name)}


def _foreign_key_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {foreign_key["name"] for foreign_key in inspect(op.get_bind()).get_foreign_keys(table_name)}


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_present(index_name: str, table_name: str) -> None:
    if _has_table(table_name) and index_name in _index_names(table_name):
        op.drop_index(index_name, table_name=table_name)


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _json_server_default():
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def _round_namespace_needs_downgrade_guard() -> bool:
    if not _has_table("clue_assignment_rounds"):
        return False
    collision = op.get_bind().execute(
        sa.text(
            """
            SELECT 1
            FROM clue_assignment_rounds
            GROUP BY order_id, round_no
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    return collision is not None


def upgrade() -> None:
    if not _has_table("clue_allocation_decisions"):
        op.create_table(
            "clue_allocation_decisions",
            sa.Column("decision_id", sa.Text(), primary_key=True),
            sa.Column("attempt_key", sa.Text(), nullable=False),
            sa.Column(
                "lead_key",
                sa.Text(),
                sa.ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("order_id", sa.Text()),
            sa.Column("rule_id", sa.Text()),
            sa.Column(
                "rule_version_id",
                sa.Text(),
                sa.ForeignKey("clue_allocation_rule_versions.rule_version_id", ondelete="RESTRICT"),
            ),
            sa.Column("scope_type", sa.String(length=32)),
            sa.Column("scope_key", sa.Text()),
            sa.Column("strategy_type", sa.String(length=64), nullable=False),
            sa.Column("execution_order", sa.Integer()),
            sa.Column("allocation_cycle_id", sa.Text()),
            sa.Column("execution_mode", sa.String(length=32), nullable=False, server_default="formal"),
            sa.Column("assignment_round_id", sa.Text()),
            sa.Column("round_no", sa.Integer()),
            sa.Column("selected_store_id", sa.Text()),
            sa.Column("selected_store_name", sa.Text()),
            sa.Column("decision_status", sa.String(length=32), nullable=False),
            sa.Column("reason", sa.Text()),
            sa.Column("decision_snapshot", _json_type(), nullable=False, server_default=_json_server_default()),
            sa.Column("actor", sa.Text()),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("attempt_key", name="uq_clue_allocation_decisions_attempt_key"),
        )
    for index_name, columns in (
        ("ix_clue_allocation_decisions_lead_key", ["lead_key"]),
        ("ix_clue_allocation_decisions_order_id", ["order_id"]),
        ("ix_clue_allocation_decisions_rule_id", ["rule_id"]),
        ("ix_clue_allocation_decisions_rule_version", ["rule_version_id"]),
        ("ix_clue_allocation_decisions_scope_type", ["scope_type"]),
        ("ix_clue_allocation_decisions_strategy_type", ["strategy_type"]),
        ("ix_clue_allocation_decisions_allocation_cycle_id", ["allocation_cycle_id"]),
        ("ix_clue_allocation_decisions_execution_mode", ["execution_mode"]),
        ("ix_clue_allocation_decisions_assignment_round_id", ["assignment_round_id"]),
        ("ix_clue_allocation_decisions_selected_store_id", ["selected_store_id"]),
        ("ix_clue_allocation_decisions_decision_status", ["decision_status"]),
        ("ix_clue_allocation_decisions_executed_at", ["executed_at"]),
        ("ix_clue_allocation_decisions_lead_executed", ["lead_key", "executed_at"]),
        ("ix_clue_allocation_decisions_order_executed", ["order_id", "executed_at"]),
    ):
        _create_index_if_missing(index_name, "clue_allocation_decisions", list(columns))

    round_columns = _column_names("clue_assignment_rounds")
    round_constraints = _unique_constraint_names("clue_assignment_rounds")
    round_foreign_keys = _foreign_key_names("clue_assignment_rounds")
    old_round_constraint = "uq_clue_assignment_rounds_order_round"
    new_round_constraint = "uq_clue_assignment_rounds_order_execution_mode_round"
    needs_round_rebuild = bool(
        {"lead_key", "rule_version_id", "strategy_type", "allocation_decision_id"}.difference(round_columns)
        or old_round_constraint in round_constraints
        or new_round_constraint not in round_constraints
    )
    if needs_round_rebuild and _has_table("clue_assignment_rounds"):
        with op.batch_alter_table("clue_assignment_rounds", recreate="always") as batch_op:
            if "lead_key" not in round_columns:
                batch_op.add_column(sa.Column("lead_key", sa.Text()))
            if "fk_clue_assignment_rounds_lead_key" not in round_foreign_keys:
                batch_op.create_foreign_key(
                    "fk_clue_assignment_rounds_lead_key",
                    "clue_master_leads",
                    ["lead_key"],
                    ["lead_key"],
                    ondelete="RESTRICT",
                )
            if "rule_version_id" not in round_columns:
                batch_op.add_column(sa.Column("rule_version_id", sa.Text()))
            if "fk_clue_assignment_rounds_rule_version" not in round_foreign_keys:
                batch_op.create_foreign_key(
                    "fk_clue_assignment_rounds_rule_version",
                    "clue_allocation_rule_versions",
                    ["rule_version_id"],
                    ["rule_version_id"],
                    ondelete="RESTRICT",
                )
            if "strategy_type" not in round_columns:
                batch_op.add_column(sa.Column("strategy_type", sa.String(length=64)))
            if "allocation_decision_id" not in round_columns:
                batch_op.add_column(sa.Column("allocation_decision_id", sa.Text()))
            if "fk_clue_assignment_rounds_allocation_decision" not in round_foreign_keys:
                batch_op.create_foreign_key(
                    "fk_clue_assignment_rounds_allocation_decision",
                    "clue_allocation_decisions",
                    ["allocation_decision_id"],
                    ["decision_id"],
                    ondelete="RESTRICT",
                )
            if old_round_constraint in round_constraints:
                batch_op.drop_constraint(old_round_constraint, type_="unique")
            if new_round_constraint not in round_constraints:
                batch_op.create_unique_constraint(
                    new_round_constraint,
                    ["order_id", "execution_mode", "round_no"],
                )
    for index_name, columns in (
        ("ix_clue_assignment_rounds_lead_key", ["lead_key"]),
        ("ix_clue_assignment_rounds_rule_version", ["rule_version_id"]),
        ("ix_clue_assignment_rounds_strategy_type", ["strategy_type"]),
        ("ix_clue_assignment_rounds_allocation_decision", ["allocation_decision_id"]),
    ):
        _create_index_if_missing(index_name, "clue_assignment_rounds", list(columns))


def downgrade() -> None:
    # A formal/trial round 1 can coexist with legacy round 1 after this revision.
    # Restoring the former key would otherwise silently discard or rewrite history.
    if _round_namespace_needs_downgrade_guard():
        raise RuntimeError(
            "cannot downgrade clue allocation engine while multiple execution namespaces share an order round"
        )

    if _has_table("clue_assignment_rounds"):
        for index_name in (
            "ix_clue_assignment_rounds_lead_key",
            "ix_clue_assignment_rounds_rule_version",
            "ix_clue_assignment_rounds_strategy_type",
            "ix_clue_assignment_rounds_allocation_decision",
        ):
            _drop_index_if_present(index_name, "clue_assignment_rounds")
        round_constraints = _unique_constraint_names("clue_assignment_rounds")
        round_foreign_keys = _foreign_key_names("clue_assignment_rounds")
        with op.batch_alter_table("clue_assignment_rounds", recreate="always") as batch_op:
            if "uq_clue_assignment_rounds_order_execution_mode_round" in round_constraints:
                batch_op.drop_constraint("uq_clue_assignment_rounds_order_execution_mode_round", type_="unique")
            if "uq_clue_assignment_rounds_order_round" not in round_constraints:
                batch_op.create_unique_constraint("uq_clue_assignment_rounds_order_round", ["order_id", "round_no"])
            for foreign_key_name in (
                "fk_clue_assignment_rounds_allocation_decision",
                "fk_clue_assignment_rounds_rule_version",
                "fk_clue_assignment_rounds_lead_key",
            ):
                if foreign_key_name in round_foreign_keys:
                    batch_op.drop_constraint(foreign_key_name, type_="foreignkey")
            columns = _column_names("clue_assignment_rounds")
            for column_name in ("allocation_decision_id", "strategy_type", "rule_version_id", "lead_key"):
                if column_name in columns:
                    batch_op.drop_column(column_name)

    if _has_table("clue_allocation_decisions"):
        op.drop_table("clue_allocation_decisions")
