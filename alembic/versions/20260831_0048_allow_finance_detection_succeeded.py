"""allow finance dispute detection jobs to use their terminal status

Revision ID: 20260831_0048
Revises: 20260831_0047
Create Date: 2026-08-31 16:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260831_0048"
down_revision = "20260831_0047"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_job_runs_status_allowlist"
SQLITE_TRIGGER_PREFIX = f"trg_{CONSTRAINT_NAME}_"
OLD_STATUS_CONDITION = (
    "status IN ('pending', 'queued', 'running', 'retry_wait', "
    "'success', 'partial', 'failed', 'cancelled')"
)
NEW_STATUS_CONDITION = (
    "status IN ('pending', 'queued', 'running', 'retry_wait', "
    "'success', 'succeeded', 'partial', 'failed', 'cancelled')"
)
OLD_SQLITE_INVALID_CONDITION = (
    "NEW.status NOT IN ('pending', 'queued', 'running', 'retry_wait', "
    "'success', 'partial', 'failed', 'cancelled')"
)
NEW_SQLITE_INVALID_CONDITION = (
    "NEW.status NOT IN ('pending', 'queued', 'running', 'retry_wait', "
    "'success', 'succeeded', 'partial', 'failed', 'cancelled')"
)


def _has_succeeded_jobs() -> bool:
    return (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM job_runs "
                "WHERE status = 'succeeded' LIMIT 1"
            )
        )
        .first()
        is not None
    )


def _drop_sqlite_status_triggers() -> None:
    for operation in ("UPDATE", "INSERT"):
        op.execute(
            f"DROP TRIGGER IF EXISTS "
            f"{SQLITE_TRIGGER_PREFIX}{operation.lower()}"
        )


def _create_sqlite_status_triggers(invalid_condition: str) -> None:
    for operation in ("INSERT", "UPDATE"):
        trigger_name = f"{SQLITE_TRIGGER_PREFIX}{operation.lower()}"
        op.execute(
            f"CREATE TRIGGER {trigger_name} "
            f"BEFORE {operation} ON job_runs "
            f"WHEN {invalid_condition} "
            "BEGIN "
            f"SELECT RAISE(ABORT, '{CONSTRAINT_NAME}'); "
            "END"
        )


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _drop_sqlite_status_triggers()
        _create_sqlite_status_triggers(NEW_SQLITE_INVALID_CONDITION)
        return

    op.drop_constraint(CONSTRAINT_NAME, "job_runs", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "job_runs",
        NEW_STATUS_CONDITION,
    )


def downgrade() -> None:
    if _has_succeeded_jobs():
        raise RuntimeError(
            "cannot restore the legacy job-run status allowlist while "
            "succeeded finance detection jobs exist"
        )

    if op.get_bind().dialect.name == "sqlite":
        _drop_sqlite_status_triggers()
        _create_sqlite_status_triggers(OLD_SQLITE_INVALID_CONDITION)
        return

    op.drop_constraint(CONSTRAINT_NAME, "job_runs", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "job_runs",
        OLD_STATUS_CONDITION,
    )
