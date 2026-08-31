"""retire legacy clue rounds and default new rounds to formal

Revision ID: 20260831_0046
Revises: 20260831_0045
Create Date: 2026-08-31 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260831_0046"
down_revision = "20260831_0045"
branch_labels = None
depends_on = None


_ROUND_COLUMNS = (
    "assignment_round_id",
    "order_id",
    "lead_key",
    "rule_version_id",
    "strategy_type",
    "allocation_decision_id",
    "allocation_cycle_id",
    "round_no",
    "assigned_at",
    "assigned_at_source",
    "assigned_store_id",
    "assigned_store_name",
    "followed_at",
    "follow_result",
    "is_followed",
    "is_follow_success",
    "round_status",
    "execution_mode",
    "matured_at",
    "terminal_reason",
    "expires_at",
    "first_sla_expires_at",
    "protection_started_at",
    "protection_expires_at",
    "auto_expiry_enabled",
    "first_follow_up_sla_hours",
    "protection_days",
    "reassign_reason",
    "reassigned_at",
    "verified_store_id",
    "verified_store_name",
    "verified_at",
    "is_self_store_verified",
    "created_at",
    "updated_at",
)


def _sample_conflicts(statement: str) -> list[str]:
    return [str(row[0]) for row in op.get_bind().execute(sa.text(statement)).fetchmany(20)]


def _guard_legacy_conversion() -> None:
    unknown_modes = _sample_conflicts(
        """
        SELECT assignment_round_id
        FROM clue_assignment_rounds
        WHERE execution_mode NOT IN ('legacy', 'formal', 'trial')
        ORDER BY assignment_round_id
        """
    )
    if unknown_modes:
        raise RuntimeError(
            "clue round retirement found unknown execution modes: "
            + ", ".join(unknown_modes)
        )

    unsafe_namespace_conflicts = _sample_conflicts(
        """
        SELECT legacy.assignment_round_id
        FROM clue_assignment_rounds legacy
        JOIN clue_assignment_rounds formal
          ON formal.lead_key = legacy.lead_key
         AND formal.round_no = legacy.round_no
         AND formal.execution_mode = 'formal'
        WHERE legacy.execution_mode = 'legacy'
          AND legacy.lead_key IS NOT NULL
          AND (
              formal.order_id <> legacy.order_id
              OR EXISTS (
                  SELECT 1 FROM clue_follow_up_records record
                  WHERE record.assignment_round_id = legacy.assignment_round_id
              )
              OR EXISTS (
                  SELECT 1 FROM clue_allocation_decisions decision
                  WHERE decision.assignment_round_id = legacy.assignment_round_id
              )
              OR EXISTS (
                  SELECT 1 FROM clue_allocation_cycle_items item
                  WHERE item.assignment_round_id = legacy.assignment_round_id
              )
              OR EXISTS (
                  SELECT 1 FROM clue_headquarters_pool_entries pool_entry
                  WHERE pool_entry.source_assignment_round_id = legacy.assignment_round_id
              )
              OR EXISTS (
                  SELECT 1 FROM clue_master_leads lead
                  WHERE lead.current_assignment_round_id = legacy.assignment_round_id
              )
              OR EXISTS (
                  SELECT 1 FROM clue_center_orders center
                  WHERE center.current_assignment_round_id = legacy.assignment_round_id
              )
          )
        ORDER BY legacy.assignment_round_id
        """
    )
    if unsafe_namespace_conflicts:
        raise RuntimeError(
            "legacy clue round conversion found referenced formal namespace collisions: "
            + ", ".join(unsafe_namespace_conflicts)
        )

    invalid_active_rounds = _sample_conflicts(
        """
        SELECT legacy.assignment_round_id
        FROM clue_assignment_rounds legacy
        LEFT JOIN clue_center_orders center
          ON center.current_assignment_round_id = legacy.assignment_round_id
        LEFT JOIN clue_master_leads lead
          ON lead.lead_key = legacy.lead_key
        WHERE legacy.execution_mode = 'legacy'
          AND legacy.round_status IN ('active_unfollowed', 'active_followed')
          AND NOT EXISTS (
              SELECT 1
              FROM clue_assignment_rounds formal
              WHERE formal.lead_key = legacy.lead_key
                AND formal.round_no = legacy.round_no
                AND formal.execution_mode = 'formal'
          )
          AND (
              legacy.lead_key IS NULL
              OR lead.lead_key IS NULL
              OR legacy.assigned_store_id IS NULL
              OR TRIM(legacy.assigned_store_id) = ''
              OR center.order_id IS NULL
              OR center.order_id <> legacy.order_id
              OR lead.order_id IS NULL
              OR lead.order_id <> legacy.order_id
              OR lead.current_assignment_round_id IS NULL
              OR lead.current_assignment_round_id <> legacy.assignment_round_id
              OR lead.lifecycle_status <> 'active'
              OR lead.normalized_order_status <> 'active'
              OR lead.pool_location <> 'store_follow_up_pool'
              OR lead.allocation_state <> 'assigned'
          )
        ORDER BY legacy.assignment_round_id
        """
    )
    if invalid_active_rounds:
        raise RuntimeError(
            "legacy clue round conversion found active rows with invalid ownership/pointers: "
            + ", ".join(invalid_active_rounds)
        )

    duplicate_active_rounds = _sample_conflicts(
        """
        SELECT MIN(assignment_round_id)
        FROM clue_assignment_rounds
        WHERE execution_mode = 'legacy'
          AND round_status IN ('active_unfollowed', 'active_followed')
          AND lead_key IS NOT NULL
        GROUP BY lead_key
        HAVING COUNT(*) > 1
        ORDER BY MIN(assignment_round_id)
        """
    )
    if duplicate_active_rounds:
        raise RuntimeError(
            "legacy clue round conversion found multiple active rounds for one lead: "
            + ", ".join(duplicate_active_rounds)
        )

    inconsistent_follow_records = _sample_conflicts(
        """
        SELECT record.follow_up_record_id
        FROM clue_follow_up_records record
        LEFT JOIN clue_assignment_rounds round_row
          ON round_row.assignment_round_id = record.assignment_round_id
        WHERE round_row.assignment_round_id IS NULL
           OR record.order_id <> round_row.order_id
           OR record.round_no <> round_row.round_no
           OR COALESCE(record.assigned_store_id, '')
              <> COALESCE(round_row.assigned_store_id, '')
        ORDER BY record.follow_up_record_id
        """
    )
    if inconsistent_follow_records:
        raise RuntimeError(
            "clue round retirement found inconsistent follow-up record ownership: "
            + ", ".join(inconsistent_follow_records)
        )


def upgrade() -> None:
    _guard_legacy_conversion()

    round_columns = ",\n                ".join(
        f"legacy.{column_name}" for column_name in _ROUND_COLUMNS
    )
    op.execute(
        sa.text(
            f"""
            CREATE TABLE clue_legacy_round_retirement_log AS
            SELECT
                {round_columns},
                CAST(NULL AS VARCHAR(128)) AS retained_assignment_round_id
            FROM clue_assignment_rounds legacy
            WHERE 1 = 0
            """
        )
    )

    insert_columns = ", ".join((*_ROUND_COLUMNS, "retained_assignment_round_id"))
    op.execute(
        sa.text(
            f"""
            INSERT INTO clue_legacy_round_retirement_log (
                {insert_columns}
            )
            SELECT
                {round_columns},
                (
                    SELECT formal.assignment_round_id
                    FROM clue_assignment_rounds formal
                    WHERE formal.lead_key = legacy.lead_key
                      AND formal.round_no = legacy.round_no
                      AND formal.execution_mode = 'formal'
                    ORDER BY formal.assignment_round_id
                    LIMIT 1
                )
            FROM clue_assignment_rounds legacy
            WHERE legacy.execution_mode = 'legacy'
            """
        )
    )

    op.execute(
        sa.text(
            """
            DELETE FROM clue_assignment_rounds
            WHERE assignment_round_id IN (
                SELECT assignment_round_id
                FROM clue_legacy_round_retirement_log
                WHERE retained_assignment_round_id IS NOT NULL
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE clue_assignment_rounds
            SET execution_mode = 'formal',
                auto_expiry_enabled = CASE
                    WHEN round_status IN ('active_unfollowed', 'active_followed') THEN FALSE
                    ELSE auto_expiry_enabled
                END
            WHERE execution_mode = 'legacy'
            """
        )
    )

    with op.batch_alter_table("clue_assignment_rounds") as batch_op:
        batch_op.alter_column(
            "execution_mode",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default="formal",
        )
        batch_op.create_check_constraint(
            "ck_clue_assignment_rounds_execution_mode",
            "execution_mode IN ('formal', 'trial')",
        )


def downgrade() -> None:
    namespace_conflicts = _sample_conflicts(
        """
        SELECT retired.assignment_round_id
        FROM clue_legacy_round_retirement_log retired
        JOIN clue_assignment_rounds later_formal
          ON later_formal.lead_key = retired.lead_key
         AND later_formal.round_no = retired.round_no
         AND later_formal.execution_mode = 'formal'
         AND later_formal.assignment_round_id <> retired.assignment_round_id
         AND (
             retired.retained_assignment_round_id IS NULL
             OR later_formal.assignment_round_id <> retired.retained_assignment_round_id
         )
        WHERE retired.lead_key IS NOT NULL
        ORDER BY retired.assignment_round_id
        """
    )
    if namespace_conflicts:
        raise RuntimeError(
            "cannot restore retired legacy rounds because newer formal rounds conflict: "
            + ", ".join(namespace_conflicts)
        )

    with op.batch_alter_table("clue_assignment_rounds") as batch_op:
        batch_op.drop_constraint(
            "ck_clue_assignment_rounds_execution_mode",
            type_="check",
        )
        batch_op.alter_column(
            "execution_mode",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default="legacy",
        )

    op.execute(
        sa.text(
            """
            UPDATE clue_assignment_rounds
            SET execution_mode = 'legacy',
                auto_expiry_enabled = (
                    SELECT retired.auto_expiry_enabled
                    FROM clue_legacy_round_retirement_log retired
                    WHERE retired.assignment_round_id = clue_assignment_rounds.assignment_round_id
                )
            WHERE assignment_round_id IN (
                SELECT assignment_round_id
                FROM clue_legacy_round_retirement_log
                WHERE retained_assignment_round_id IS NULL
            )
            """
        )
    )

    restore_columns = ", ".join(_ROUND_COLUMNS)
    op.execute(
        sa.text(
            f"""
            INSERT INTO clue_assignment_rounds ({restore_columns})
            SELECT {restore_columns}
            FROM clue_legacy_round_retirement_log retired
            WHERE retired.retained_assignment_round_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM clue_assignment_rounds current_round
                  WHERE current_round.assignment_round_id = retired.assignment_round_id
              )
            """
        )
    )
    op.drop_table("clue_legacy_round_retirement_log")
