"""constrain the task-control state machine allowlists

Revision ID: 20260806_0031
Revises: 20260806_0030
Create Date: 2026-08-06 15:00:00
"""

from __future__ import annotations

from alembic import op


revision = "20260806_0031"
down_revision = "20260806_0030"
branch_labels = None
depends_on = None


CONSTRAINTS = (
    (
        "ck_job_runs_parent_sync_complete_window",
        "job_kind IS NULL OR job_kind != 'parent_sync' OR ("
        "parent_job_id IS NOT NULL AND execution_slot IS NOT NULL "
        "AND execution_slot = 'heavy_sync' "
        "AND business_date IS NULL AND data_source IS NOT NULL "
        "AND config_version IS NOT NULL AND window_start IS NOT NULL "
        "AND window_end IS NOT NULL AND window_end > window_start)",
    ),
    (
        "ck_job_runs_job_kind_allowlist",
        "job_kind IS NULL OR job_kind IN ("
        "'range_sync', 'parent_sync', 'date_sync', 'finalize', 'product_sync')",
    ),
    (
        "ck_job_runs_current_stage_allowlist",
        "current_stage IS NULL OR current_stage IN ("
        "'collect', 'collect_dimensions', 'materialize', 'settle', 'finalize')",
    ),
    (
        "ck_job_runs_status_allowlist",
        "status IN ('pending', 'queued', 'running', 'retry_wait', "
        "'success', 'partial', 'failed', 'cancelled')",
    ),
    (
        "ck_job_runs_attempt_bounds",
        "(attempt_count IS NULL OR attempt_count >= 0) AND "
        "(max_attempts IS NULL OR max_attempts BETWEEN 1 AND 3) AND "
        "(attempt_count IS NULL OR max_attempts IS NULL "
        "OR attempt_count <= max_attempts)",
    ),
)

SQLITE_INVALID_CONDITIONS = (
    (
        "ck_job_runs_parent_sync_complete_window",
        "NEW.job_kind = 'parent_sync' AND ("
        "NEW.parent_job_id IS NULL OR NEW.execution_slot IS NULL "
        "OR NEW.execution_slot != 'heavy_sync' "
        "OR NEW.business_date IS NOT NULL OR NEW.data_source IS NULL "
        "OR NEW.config_version IS NULL OR NEW.window_start IS NULL "
        "OR NEW.window_end IS NULL OR NEW.window_end <= NEW.window_start)",
    ),
    (
        "ck_job_runs_job_kind_allowlist",
        "NEW.job_kind IS NOT NULL AND NEW.job_kind NOT IN ("
        "'range_sync', 'parent_sync', 'date_sync', 'finalize', 'product_sync')",
    ),
    (
        "ck_job_runs_current_stage_allowlist",
        "NEW.current_stage IS NOT NULL AND NEW.current_stage NOT IN ("
        "'collect', 'collect_dimensions', 'materialize', 'settle', 'finalize')",
    ),
    (
        "ck_job_runs_status_allowlist",
        "NEW.status NOT IN ('pending', 'queued', 'running', 'retry_wait', "
        "'success', 'partial', 'failed', 'cancelled')",
    ),
    (
        "ck_job_runs_attempt_bounds",
        "(NEW.attempt_count IS NOT NULL AND NEW.attempt_count < 0) OR "
        "(NEW.max_attempts IS NOT NULL AND "
        "(NEW.max_attempts < 1 OR NEW.max_attempts > 3)) OR "
        "(NEW.attempt_count IS NOT NULL AND NEW.max_attempts IS NOT NULL "
        "AND NEW.attempt_count > NEW.max_attempts)",
    ),
)


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _create_sqlite_validation_triggers()
        return
    for constraint_name, condition in CONSTRAINTS:
        op.create_check_constraint(
            constraint_name,
            "job_runs",
            condition,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _drop_sqlite_validation_triggers()
        return
    for constraint_name, _condition in reversed(CONSTRAINTS):
        op.drop_constraint(constraint_name, "job_runs", type_="check")


def _create_sqlite_validation_triggers() -> None:
    for constraint_name, invalid_condition in SQLITE_INVALID_CONDITIONS:
        for operation in ("INSERT", "UPDATE"):
            trigger_name = _sqlite_trigger_name(constraint_name, operation)
            op.execute(
                f"CREATE TRIGGER {trigger_name} "
                f"BEFORE {operation} ON job_runs "
                f"WHEN {invalid_condition} "
                "BEGIN "
                f"SELECT RAISE(ABORT, '{constraint_name}'); "
                "END"
            )


def _drop_sqlite_validation_triggers() -> None:
    for constraint_name, _invalid_condition in reversed(SQLITE_INVALID_CONDITIONS):
        for operation in ("UPDATE", "INSERT"):
            op.execute(
                f"DROP TRIGGER IF EXISTS "
                f"{_sqlite_trigger_name(constraint_name, operation)}"
            )


def _sqlite_trigger_name(constraint_name: str, operation: str) -> str:
    return f"trg_{constraint_name}_{operation.lower()}"
