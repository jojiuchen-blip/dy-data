"""Persist quota pauses separately from genuine retry attempts.

Revision ID: 20260910_0053
Revises: 20260909_0052
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260910_0053"
down_revision = "20260909_0052"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_job_runs_attempt_bounds"
QUOTA_COLUMN = "quota_pause_count"

ATTEMPT_BOUNDS = (
    "(attempt_count IS NULL OR attempt_count >= 0) AND "
    "(max_attempts IS NULL OR max_attempts BETWEEN 1 AND 3) AND "
    "(quota_pause_count IS NULL OR quota_pause_count >= 0) AND "
    "(attempt_count IS NULL OR max_attempts IS NULL "
    "OR quota_pause_count IS NULL "
    "OR attempt_count <= max_attempts + quota_pause_count) AND "
    "(quota_pause_count IS NULL OR attempt_count IS NULL "
    "OR quota_pause_count <= attempt_count)"
)

SQLITE_INVALID_ATTEMPT_BOUNDS = (
    "(NEW.attempt_count IS NOT NULL AND NEW.attempt_count < 0) OR "
    "(NEW.max_attempts IS NOT NULL AND "
    "(NEW.max_attempts < 1 OR NEW.max_attempts > 3)) OR "
    "(NEW.quota_pause_count IS NOT NULL AND NEW.quota_pause_count < 0) OR "
    "(NEW.attempt_count IS NOT NULL AND NEW.max_attempts IS NOT NULL "
    "AND NEW.quota_pause_count IS NOT NULL "
    "AND NEW.attempt_count > NEW.max_attempts + NEW.quota_pause_count) OR "
    "(NEW.quota_pause_count IS NOT NULL AND NEW.attempt_count IS NOT NULL "
    "AND NEW.quota_pause_count > NEW.attempt_count)"
)

SQLITE_LEGACY_INVALID_ATTEMPT_BOUNDS = (
    "(NEW.attempt_count IS NOT NULL AND NEW.attempt_count < 0) OR "
    "(NEW.max_attempts IS NOT NULL AND "
    "(NEW.max_attempts < 1 OR NEW.max_attempts > 3)) OR "
    "(NEW.attempt_count IS NOT NULL AND NEW.max_attempts IS NOT NULL "
    "AND NEW.attempt_count > NEW.max_attempts)"
)


def _has_column(column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return inspector.has_table("job_runs") and column_name in {
        column["name"] for column in inspector.get_columns("job_runs")
    }


def _has_check_constraint(constraint_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(
        constraint.get("name") == constraint_name
        for constraint in inspector.get_check_constraints("job_runs")
    )


def _sqlite_trigger_name(operation: str) -> str:
    return f"trg_{CONSTRAINT_NAME}_{operation.lower()}"


def _drop_sqlite_attempt_triggers() -> None:
    for operation in ("UPDATE", "INSERT"):
        op.execute(
            f"DROP TRIGGER IF EXISTS {_sqlite_trigger_name(operation)}"
        )


def _create_sqlite_attempt_triggers() -> None:
    for operation in ("INSERT", "UPDATE"):
        trigger_name = _sqlite_trigger_name(operation)
        op.execute(
            f"CREATE TRIGGER {trigger_name} "
            f"BEFORE {operation} ON job_runs "
            f"WHEN {SQLITE_INVALID_ATTEMPT_BOUNDS} "
            "BEGIN "
            f"SELECT RAISE(ABORT, '{CONSTRAINT_NAME}'); "
            "END"
        )


def _create_sqlite_legacy_attempt_triggers() -> None:
    for operation in ("INSERT", "UPDATE"):
        trigger_name = _sqlite_trigger_name(operation)
        op.execute(
            f"CREATE TRIGGER {trigger_name} "
            f"BEFORE {operation} ON job_runs "
            f"WHEN {SQLITE_LEGACY_INVALID_ATTEMPT_BOUNDS} "
            "BEGIN "
            f"SELECT RAISE(ABORT, '{CONSTRAINT_NAME}'); "
            "END"
        )


def upgrade() -> None:
    """Add the durable pause counter and extend the retry bound."""

    if not _has_column(QUOTA_COLUMN):
        op.add_column(
            "job_runs",
            sa.Column(
                QUOTA_COLUMN,
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if op.get_bind().dialect.name == "sqlite":
        _drop_sqlite_attempt_triggers()
        _create_sqlite_attempt_triggers()
        return

    if _has_check_constraint(CONSTRAINT_NAME):
        op.drop_constraint(CONSTRAINT_NAME, "job_runs", type_="check")
    op.create_check_constraint(CONSTRAINT_NAME, "job_runs", ATTEMPT_BOUNDS)


def downgrade() -> None:
    """Refuse to discard pause history or rows beyond the old retry bound."""

    bind = op.get_bind()
    if not _has_column(QUOTA_COLUMN):
        return
    has_pause_history = bind.execute(
        text(
            "SELECT 1 FROM job_runs "
            "WHERE quota_pause_count IS NOT NULL AND quota_pause_count <> 0 "
            "LIMIT 1"
        )
    ).first()
    has_extended_attempts = bind.execute(
        text(
            "SELECT 1 FROM job_runs "
            "WHERE attempt_count IS NOT NULL AND max_attempts IS NOT NULL "
            "AND attempt_count > max_attempts LIMIT 1"
        )
    ).first()
    if has_pause_history is not None or has_extended_attempts is not None:
        raise RuntimeError(
            "cannot downgrade 20260910_0053: quota pause history is populated"
        )

    if bind.dialect.name == "sqlite":
        _drop_sqlite_attempt_triggers()
        op.drop_column("job_runs", QUOTA_COLUMN)
        _create_sqlite_legacy_attempt_triggers()
        return

    if _has_check_constraint(CONSTRAINT_NAME):
        op.drop_constraint(CONSTRAINT_NAME, "job_runs", type_="check")
    op.drop_column("job_runs", QUOTA_COLUMN)
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "job_runs",
        "(attempt_count IS NULL OR attempt_count >= 0) AND "
        "(max_attempts IS NULL OR max_attempts BETWEEN 1 AND 3) AND "
        "(attempt_count IS NULL OR max_attempts IS NULL "
        "OR attempt_count <= max_attempts)",
    )
