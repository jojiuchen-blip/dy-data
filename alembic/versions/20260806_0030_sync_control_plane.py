"""add the safe synchronization control-plane schema

Revision ID: 20260806_0030
Revises: 20260804_0029
Create Date: 2026-08-06 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260806_0030"
down_revision = "20260804_0029"
branch_labels = None
depends_on = None


DATE_SYNC_IDENTITY = sa.text(
    "job_kind = 'date_sync' "
    "AND parent_job_id IS NOT NULL "
    "AND business_date IS NOT NULL "
    "AND data_source IS NOT NULL "
    "AND config_version IS NOT NULL"
)
DATE_SYNC_COMPLETE_WINDOW = (
    "job_kind IS NULL OR job_kind != 'date_sync' OR ("
    "parent_job_id IS NOT NULL AND business_date IS NOT NULL "
    "AND data_source IS NOT NULL AND config_version IS NOT NULL "
    "AND window_start IS NOT NULL AND window_end IS NOT NULL "
    "AND window_end > window_start)"
)
RANGE_SYNC_NO_EXECUTION_SLOT = (
    "job_kind IS NULL OR job_kind != 'range_sync' "
    "OR execution_slot IS NULL"
)
HEAVY_SYNC_RUNNING = sa.text(
    "execution_slot = 'heavy_sync' "
    "AND status = 'running'"
)
EVENT_WITH_IDEMPOTENCY_KEY = sa.text("idempotency_key IS NOT NULL")
ACTIVE_OPS_COMMAND = sa.text("status IN ('pending', 'running')")


def json_type() -> sa.types.TypeEngine:
    """Return JSONB on PostgreSQL and portable JSON elsewhere."""

    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    _extend_job_runs()
    _create_job_stage_runs()
    _create_component_heartbeats()
    _create_job_attempts()
    _create_component_heartbeat_attempt_foreign_key()
    _create_job_events()
    _create_component_metric_samples()
    _create_ops_commands()


def downgrade() -> None:
    op.drop_table("ops_commands")
    op.drop_table("component_metric_samples")
    op.drop_table("job_events")
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE component_heartbeats "
                "SET current_attempt_id = NULL "
                "WHERE current_attempt_id IS NOT NULL"
            )
        )
    else:
        op.drop_constraint(
            "fk_component_heartbeats_current_attempt",
            "component_heartbeats",
            type_="foreignkey",
        )
    op.drop_table("job_attempts")
    op.drop_table("component_heartbeats")
    op.drop_table("job_stage_runs")

    for index_name in (
        "ix_job_runs_heartbeat_at",
        "ix_job_runs_lease_expires_at",
        "ix_job_runs_parent_business_date",
        "uq_job_runs_heavy_sync_running_slot",
        "uq_job_runs_date_sync_identity",
    ):
        op.drop_index(index_name, table_name="job_runs")

    job_run_columns = (
        "pause_after_stage_requested_at",
        "cancel_requested_at",
        "error_summary",
        "error_code",
        "rss_peak_bytes",
        "rows_affected",
        "rows_written",
        "rows_read",
        "progress_total",
        "progress_current",
        "next_retry_at",
        "heartbeat_at",
        "lease_expires_at",
        "lease_epoch",
        "lease_owner",
        "max_attempts",
        "attempt_count",
        "current_stage",
        "window_end",
        "window_start",
        "config_version",
        "data_source",
        "business_date",
        "execution_slot",
        "job_kind",
        "parent_job_id",
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE job_runs "
                "SET job_kind = NULL, parent_job_id = NULL "
                "WHERE parent_job_id IS NOT NULL"
            )
        )
        with op.batch_alter_table("job_runs", recreate="always") as batch_op:
            batch_op.drop_constraint(
                "ck_job_runs_range_sync_no_execution_slot",
                type_="check",
            )
            batch_op.drop_constraint(
                "ck_job_runs_date_sync_complete_window",
                type_="check",
            )
            batch_op.drop_constraint(
                "fk_job_runs_parent_job_id",
                type_="foreignkey",
            )
            for column_name in job_run_columns:
                batch_op.drop_column(column_name)
    else:
        op.drop_constraint(
            "ck_job_runs_range_sync_no_execution_slot",
            "job_runs",
            type_="check",
        )
        op.drop_constraint(
            "ck_job_runs_date_sync_complete_window",
            "job_runs",
            type_="check",
        )
        op.drop_constraint(
            "fk_job_runs_parent_job_id",
            "job_runs",
            type_="foreignkey",
        )
        for column_name in job_run_columns:
            op.drop_column("job_runs", column_name)


def _extend_job_runs() -> None:
    op.add_column(
        "job_runs",
        sa.Column("parent_job_id", sa.Text(), nullable=True),
    )
    for column in (
        sa.Column("job_kind", sa.String(length=32), nullable=True),
        sa.Column("execution_slot", sa.String(length=32), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=True),
        sa.Column("data_source", sa.String(length=128), nullable=True),
        sa.Column("config_version", sa.String(length=128), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_stage", sa.String(length=32), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_epoch", sa.Integer(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_current", sa.BigInteger(), nullable=True),
        sa.Column("progress_total", sa.BigInteger(), nullable=True),
        sa.Column("rows_read", sa.BigInteger(), nullable=True),
        sa.Column("rows_written", sa.BigInteger(), nullable=True),
        sa.Column("rows_affected", sa.BigInteger(), nullable=True),
        sa.Column("rss_peak_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "pause_after_stage_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    ):
        op.add_column("job_runs", column)

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("job_runs", recreate="always") as batch_op:
            batch_op.create_foreign_key(
                "fk_job_runs_parent_job_id",
                "job_runs",
                ["parent_job_id"],
                ["job_id"],
                ondelete="RESTRICT",
            )
            batch_op.create_check_constraint(
                "ck_job_runs_date_sync_complete_window",
                DATE_SYNC_COMPLETE_WINDOW,
            )
            batch_op.create_check_constraint(
                "ck_job_runs_range_sync_no_execution_slot",
                RANGE_SYNC_NO_EXECUTION_SLOT,
            )
    else:
        op.create_foreign_key(
            "fk_job_runs_parent_job_id",
            "job_runs",
            "job_runs",
            ["parent_job_id"],
            ["job_id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            "ck_job_runs_date_sync_complete_window",
            "job_runs",
            DATE_SYNC_COMPLETE_WINDOW,
        )
        op.create_check_constraint(
            "ck_job_runs_range_sync_no_execution_slot",
            "job_runs",
            RANGE_SYNC_NO_EXECUTION_SLOT,
        )

    op.create_index(
        "uq_job_runs_date_sync_identity",
        "job_runs",
        ["parent_job_id", "business_date", "data_source", "config_version"],
        unique=True,
        sqlite_where=DATE_SYNC_IDENTITY,
        postgresql_where=DATE_SYNC_IDENTITY,
    )
    op.create_index(
        "uq_job_runs_heavy_sync_running_slot",
        "job_runs",
        ["execution_slot"],
        unique=True,
        sqlite_where=HEAVY_SYNC_RUNNING,
        postgresql_where=HEAVY_SYNC_RUNNING,
    )
    op.create_index(
        "ix_job_runs_parent_business_date",
        "job_runs",
        ["parent_job_id", "business_date"],
    )
    op.create_index(
        "ix_job_runs_lease_expires_at",
        "job_runs",
        ["lease_expires_at"],
    )
    op.create_index(
        "ix_job_runs_heartbeat_at",
        "job_runs",
        ["heartbeat_at"],
    )
def _create_job_stage_runs() -> None:
    op.create_table(
        "job_stage_runs",
        sa.Column("stage_run_id", sa.Text(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Text(),
            sa.ForeignKey("job_runs.job_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage_name", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("checkpoint_json", json_type(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "job_id",
            "stage_name",
            name="uq_job_stage_runs_job_stage",
        ),
        sa.UniqueConstraint(
            "job_id",
            "stage_run_id",
            name="uq_job_stage_runs_job_stage_run",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', "
            "'cancelled', 'skipped')",
            name="ck_job_stage_runs_status",
        ),
        sa.CheckConstraint(
            "status != 'success' OR committed_at IS NOT NULL",
            name="ck_job_stage_runs_success_committed_at",
        ),
        sa.CheckConstraint(
            "lease_epoch IS NULL OR lease_epoch >= 0",
            name="ck_job_stage_runs_lease_epoch",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_job_stage_runs_time_order",
        ),
    )
    op.create_index(
        "ix_job_stage_runs_job_status",
        "job_stage_runs",
        ["job_id", "status"],
    )
    op.create_index(
        "ix_job_stage_runs_committed_at",
        "job_stage_runs",
        ["committed_at"],
    )


def _create_job_attempts() -> None:
    op.create_table(
        "job_attempts",
        sa.Column("attempt_id", sa.Text(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Text(),
            sa.ForeignKey("job_runs.job_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage_run_id", sa.Text(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("component_type", sa.String(length=32), nullable=False),
        sa.Column("component_instance_id", sa.Text(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("container_instance_id", sa.Text(), nullable=True),
        sa.Column("batch_size", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_type", sa.String(length=32), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("rss_peak_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error_id", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "stage_run_id"],
            ["job_stage_runs.job_id", "job_stage_runs.stage_run_id"],
            name="fk_job_attempts_job_stage_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["component_instance_id", "component_type"],
            [
                "component_heartbeats.component_instance_id",
                "component_heartbeats.component_type",
            ],
            name="fk_job_attempts_component_identity",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_job_attempts_job_attempt_number",
        ),
        sa.UniqueConstraint(
            "job_id",
            "lease_epoch",
            name="uq_job_attempts_job_lease_epoch",
        ),
        sa.UniqueConstraint(
            "job_id",
            "attempt_id",
            name="uq_job_attempts_job_attempt",
        ),
        sa.UniqueConstraint(
            "job_id",
            "component_instance_id",
            "attempt_id",
            name="uq_job_attempts_job_component_attempt",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_job_attempts_attempt_number",
        ),
        sa.CheckConstraint(
            "lease_epoch > 0",
            name="ck_job_attempts_lease_epoch",
        ),
        sa.CheckConstraint(
            "batch_size IS NULL OR batch_size > 0",
            name="ck_job_attempts_batch_size",
        ),
        sa.CheckConstraint(
            "exit_type IS NULL OR exit_type IN ("
            "'success', 'retryable_failure', 'fatal_failure', "
            "'cancelled', 'crashed', 'resource_guard')",
            name="ck_job_attempts_exit_type",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_job_attempts_time_order",
        ),
    )
    op.create_index(
        "ix_job_attempts_job_started",
        "job_attempts",
        ["job_id", "started_at"],
    )
    op.create_index(
        "ix_job_attempts_stage_run_id",
        "job_attempts",
        ["stage_run_id"],
    )
    op.create_index(
        "ix_job_attempts_component_started",
        "job_attempts",
        ["component_instance_id", "started_at"],
    )


def _create_job_events() -> None:
    op.create_table(
        "job_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Text(),
            sa.ForeignKey("job_runs.job_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage_run_id", sa.Text(), nullable=True),
        sa.Column("attempt_id", sa.Text(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("error_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("payload_json", json_type(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "stage_run_id"],
            ["job_stage_runs.job_id", "job_stage_runs.stage_run_id"],
            name="fk_job_events_job_stage_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "attempt_id"],
            ["job_attempts.job_id", "job_attempts.attempt_id"],
            name="fk_job_events_job_attempt",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "actor_type IN ('system', 'worker', 'ops_agent', 'user')",
            name="ck_job_events_actor_type",
        ),
    )
    op.create_index(
        "uq_job_events_idempotency_key",
        "job_events",
        ["job_id", "idempotency_key"],
        unique=True,
        sqlite_where=EVENT_WITH_IDEMPOTENCY_KEY,
        postgresql_where=EVENT_WITH_IDEMPOTENCY_KEY,
    )
    op.create_index(
        "ix_job_events_job_occurred",
        "job_events",
        ["job_id", "occurred_at"],
    )
    op.create_index(
        "ix_job_events_attempt_id",
        "job_events",
        ["attempt_id"],
    )
    op.create_index(
        "ix_job_events_type_occurred",
        "job_events",
        ["event_type", "occurred_at"],
    )


def _create_component_heartbeats() -> None:
    current_attempt_constraints: tuple[sa.ForeignKeyConstraint, ...] = ()
    if op.get_bind().dialect.name == "sqlite":
        current_attempt_constraints = (
            sa.ForeignKeyConstraint(
                ["current_job_id", "component_instance_id", "current_attempt_id"],
                [
                    "job_attempts.job_id",
                    "job_attempts.component_instance_id",
                    "job_attempts.attempt_id",
                ],
                name="fk_component_heartbeats_current_attempt",
                ondelete="RESTRICT",
                use_alter=True,
            ),
        )
    op.create_table(
        "component_heartbeats",
        sa.Column("component_instance_id", sa.Text(), primary_key=True),
        sa.Column("component_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "current_job_id",
            sa.Text(),
            sa.ForeignKey("job_runs.job_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("current_attempt_id", sa.Text(), nullable=True),
        sa.Column("rss_bytes", sa.BigInteger(), nullable=True),
        sa.Column("rss_peak_bytes", sa.BigInteger(), nullable=True),
        sa.Column("memory_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("cpu_percent", sa.Float(), nullable=True),
        sa.Column("queue_depth", sa.Integer(), nullable=True),
        sa.Column("activity_json", json_type(), nullable=False),
        sa.Column("queue_summary_json", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *current_attempt_constraints,
        sa.UniqueConstraint(
            "component_instance_id",
            "component_type",
            name="uq_component_heartbeats_instance_type",
        ),
        sa.CheckConstraint(
            "current_attempt_id IS NULL OR current_job_id IS NOT NULL",
            name="ck_component_heartbeats_current_attempt_job",
        ),
        sa.CheckConstraint(
            "component_type IN ("
            "'worker', 'browser', 'api', 'postgres', 'proxy', 'ops_agent')",
            name="ck_component_heartbeats_component_type",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'starting', 'healthy', 'degraded', 'draining', 'unhealthy', 'stopped')",
            name="ck_component_heartbeats_status",
        ),
        sa.CheckConstraint(
            "rss_bytes IS NULL OR rss_bytes >= 0",
            name="ck_component_heartbeats_rss_bytes",
        ),
        sa.CheckConstraint(
            "rss_peak_bytes IS NULL OR rss_peak_bytes >= 0",
            name="ck_component_heartbeats_rss_peak_bytes",
        ),
        sa.CheckConstraint(
            "memory_limit_bytes IS NULL OR memory_limit_bytes > 0",
            name="ck_component_heartbeats_memory_limit_bytes",
        ),
        sa.CheckConstraint(
            "queue_depth IS NULL OR queue_depth >= 0",
            name="ck_component_heartbeats_queue_depth",
        ),
    )
    op.create_index(
        "ix_component_heartbeats_type_last_heartbeat",
        "component_heartbeats",
        ["component_type", "last_heartbeat_at"],
    )
    op.create_index(
        "ix_component_heartbeats_status",
        "component_heartbeats",
        ["status"],
    )
    op.create_index(
        "ix_component_heartbeats_current_job_id",
        "component_heartbeats",
        ["current_job_id"],
    )


def _create_component_heartbeat_attempt_foreign_key() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.create_foreign_key(
        "fk_component_heartbeats_current_attempt",
        "component_heartbeats",
        "job_attempts",
        ["current_job_id", "component_instance_id", "current_attempt_id"],
        ["job_id", "component_instance_id", "attempt_id"],
        ondelete="RESTRICT",
    )


def _create_component_metric_samples() -> None:
    op.create_table(
        "component_metric_samples",
        sa.Column("metric_sample_id", sa.Text(), primary_key=True),
        sa.Column(
            "component_instance_id",
            sa.Text(),
            sa.ForeignKey(
                "component_heartbeats.component_instance_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Text(),
            sa.ForeignKey("job_runs.job_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("attempt_id", sa.Text(), nullable=True),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("metric_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", json_type(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "component_instance_id", "attempt_id"],
            [
                "job_attempts.job_id",
                "job_attempts.component_instance_id",
                "job_attempts.attempt_id",
            ],
            name="fk_component_metric_samples_job_component_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "component_instance_id",
            "metric_name",
            "sampled_at",
            name="uq_component_metric_samples_instance_metric_sampled",
        ),
        sa.CheckConstraint(
            "expires_at > sampled_at",
            name="ck_component_metric_samples_retention",
        ),
        sa.CheckConstraint(
            "attempt_id IS NULL OR job_id IS NOT NULL",
            name="ck_component_metric_samples_attempt_job",
        ),
    )
    op.create_index(
        "ix_component_metric_samples_component_sampled",
        "component_metric_samples",
        ["component_instance_id", "sampled_at"],
    )
    op.create_index(
        "ix_component_metric_samples_expires_at",
        "component_metric_samples",
        ["expires_at"],
    )
    op.create_index(
        "ix_component_metric_samples_job_sampled",
        "component_metric_samples",
        ["job_id", "sampled_at"],
    )


def _create_ops_commands() -> None:
    op.create_table(
        "ops_commands",
        sa.Column("command_id", sa.Text(), primary_key=True),
        sa.Column("command_type", sa.String(length=32), nullable=False),
        sa.Column("target_component", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "related_job_id",
            sa.Text(),
            sa.ForeignKey("job_runs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("lease_epoch", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_code", sa.String(length=64), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "command_type = 'restart'",
            name="ck_ops_commands_command_type",
        ),
        sa.CheckConstraint(
            "target_component IN ('worker', 'browser')",
            name="ck_ops_commands_target_component",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'running', 'success', 'failed', "
            "'rejected', 'expired', 'cancelled')",
            name="ck_ops_commands_status",
        ),
        sa.CheckConstraint(
            "lease_epoch IS NULL OR lease_epoch > 0",
            name="ck_ops_commands_lease_epoch",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_ops_commands_expiry",
        ),
    )
    op.create_index(
        "uq_ops_commands_idempotency_key_hash",
        "ops_commands",
        ["idempotency_key_hash"],
        unique=True,
    )
    op.create_index(
        "uq_ops_commands_active_target",
        "ops_commands",
        ["target_component"],
        unique=True,
        sqlite_where=ACTIVE_OPS_COMMAND,
        postgresql_where=ACTIVE_OPS_COMMAND,
    )
    op.create_index(
        "ix_ops_commands_status_created",
        "ops_commands",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_ops_commands_expires_at",
        "ops_commands",
        ["expires_at"],
    )
    op.create_index(
        "ix_ops_commands_related_job_id",
        "ops_commands",
        ["related_job_id"],
    )
    op.create_index(
        "ix_ops_commands_target_cooldown",
        "ops_commands",
        ["target_component", "cooldown_until"],
    )
