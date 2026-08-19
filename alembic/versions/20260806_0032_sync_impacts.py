"""add incremental impact capture and raw refund evidence

Revision ID: 20260806_0032
Revises: 20260806_0031
Create Date: 2026-08-06 18:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260806_0032"
down_revision = "20260806_0031"
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _id_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        sa.Identity(),
        primary_key=True,
        nullable=False,
        autoincrement=True,
    )


def upgrade() -> None:
    _add_observation_columns()
    _add_mapping_observation_columns()
    _add_refund_event_observation_columns()
    _create_raw_refund_records()
    _create_job_impacts()
    _create_materialization_work_items()
    _create_impact_watermarks()


def downgrade() -> None:
    op.drop_table("job_impact_watermarks")
    op.drop_table("clue_materialization_work_items")
    op.drop_table("job_impacts")
    op.drop_table("raw_douyin_refund_records")
    _drop_refund_event_observation_columns()
    _drop_mapping_observation_columns()
    _drop_observation_columns()


def _add_observation_columns() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    for table_name in (
        "raw_douyin_orders",
        "raw_douyin_order_coupons",
        "raw_douyin_verify_records",
        "raw_douyin_clues",
    ):
        columns = [
            sa.Column("payload_fingerprint", sa.String(length=64), nullable=True),
            sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("observation_key", sa.String(length=256), nullable=True),
        ]
        if table_name == "raw_douyin_clues":
            columns.insert(0, sa.Column("source_run_id", sa.Text(), nullable=True))
        if is_sqlite:
            with op.batch_alter_table(table_name, recreate="always") as batch:
                for column in columns:
                    batch.add_column(column)
        else:
            for column in columns:
                op.add_column(table_name, column)
        if table_name == "raw_douyin_clues":
            op.create_index(
                "ix_raw_douyin_clues_source_run_id",
                table_name,
                ["source_run_id"],
            )


def _drop_observation_columns() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    for table_name in (
        "raw_douyin_orders",
        "raw_douyin_order_coupons",
        "raw_douyin_verify_records",
        "raw_douyin_clues",
    ):
        columns = ["payload_fingerprint", "source_observed_at", "observation_key"]
        if table_name == "raw_douyin_clues":
            columns.insert(0, "source_run_id")
            # SQLite batch recreation copies existing indexes before dropping
            # columns. Remove this new single-column index first so the
            # recreated table does not reference source_run_id after it is
            # removed.
            op.drop_index("ix_raw_douyin_clues_source_run_id", table_name=table_name)
        if is_sqlite:
            with op.batch_alter_table(table_name, recreate="always") as batch:
                for column_name in columns:
                    batch.drop_column(column_name)
        else:
            for column_name in reversed(columns):
                op.drop_column(table_name, column_name)


def _add_mapping_observation_columns() -> None:
    columns = [
        sa.Column("source_run_id", sa.Text(), nullable=True),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_key", sa.String(length=256), nullable=True),
    ]
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("dim_store_poi_mappings", recreate="always") as batch:
            for column in columns:
                batch.add_column(column)
    else:
        for column in columns:
            op.add_column("dim_store_poi_mappings", column)


def _drop_mapping_observation_columns() -> None:
    names = ["source_run_id", "payload_fingerprint", "source_observed_at", "observation_key"]
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("dim_store_poi_mappings", recreate="always") as batch:
            for name in names:
                batch.drop_column(name)
    else:
        for name in reversed(names):
            op.drop_column("dim_store_poi_mappings", name)


def _add_refund_event_observation_columns() -> None:
    columns = [
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("observation_key", sa.String(length=256), nullable=True),
    ]
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("douyin_refund_event", recreate="always") as batch:
            for column in columns:
                batch.add_column(column)
    else:
        for column in columns:
            op.add_column("douyin_refund_event", column)


def _drop_refund_event_observation_columns() -> None:
    columns = ["source_observed_at", "payload_fingerprint", "observation_key"]
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("douyin_refund_event", recreate="always") as batch:
            for column in columns:
                batch.drop_column(column)
    else:
        for column in reversed(columns):
            op.drop_column("douyin_refund_event", column)


def _create_raw_refund_records() -> None:
    op.create_table(
        "raw_douyin_refund_records",
        _id_column("id"),
        sa.Column("source_record_key", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("refund_id", sa.String(length=128), nullable=True),
        sa.Column("raw_refund_status", sa.String(length=128), nullable=True),
        sa.Column("normalized_refund_status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refund_amount_cent", sa.BigInteger(), nullable=True),
        sa.Column("refund_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refund_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_run_id", sa.String(length=64), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("gmt_modified", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_raw_douyin_refund_records"),
        sa.UniqueConstraint("source_record_key", name="uk_raw_douyin_refund_record_source_record_key"),
        sa.CheckConstraint(
            "normalized_refund_status BETWEEN 0 AND 4",
            name="ck_raw_douyin_refund_record_normalized_status",
        ),
        sa.CheckConstraint(
            "refund_amount_cent >= 0",
            name="ck_raw_douyin_refund_record_amount",
        ),
    )
    op.create_index("idx_raw_douyin_refund_record_order_observed", "raw_douyin_refund_records", ["order_id", "source_observed_at"])
    op.create_index("idx_raw_douyin_refund_record_refund_id", "raw_douyin_refund_records", ["refund_id"])
    op.create_index("idx_raw_douyin_refund_record_source_run", "raw_douyin_refund_records", ["source_run_id"])


def _create_job_impacts() -> None:
    op.create_table(
        "job_impacts",
        _id_column("id"),
        sa.Column("impact_key", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_key", sa.String(length=256), nullable=False),
        sa.Column("change_kind", sa.String(length=32), nullable=False, server_default="upsert"),
        sa.Column("old_values_json", json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("new_values_json", json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("affected_closure_json", json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_run_id", sa.String(length=128), nullable=True),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_job_impacts"),
        sa.UniqueConstraint("impact_key", name="uk_job_impacts_impact_key"),
    )
    op.create_index("ix_job_impacts_entity_order", "job_impacts", ["entity_type", "entity_key", "id"])
    op.create_index("ix_job_impacts_created", "job_impacts", ["created_at", "id"])
    op.create_index("ix_job_impacts_source_run", "job_impacts", ["source_run_id"])


def _create_materialization_work_items() -> None:
    op.create_table(
        "clue_materialization_work_items",
        _id_column("work_item_id"),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("impact_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_key", sa.String(length=256), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["impact_id"], ["job_impacts.id"], name="fk_clue_materialization_work_impact", ondelete="RESTRICT"),
        sa.UniqueConstraint("scope", "impact_id", name="uk_clue_materialization_work_scope_impact"),
        sa.CheckConstraint("state IN ('pending', 'processing', 'completed')", name="ck_clue_materialization_work_state"),
    )
    op.create_index("ix_clue_materialization_work_scope_state", "clue_materialization_work_items", ["scope", "state", "work_item_id"])
    op.create_index("ix_clue_materialization_work_impact", "clue_materialization_work_items", ["impact_id"])
    op.create_index("ix_clue_materialization_work_lease", "clue_materialization_work_items", ["state", "lease_expires_at"])


def _create_impact_watermarks() -> None:
    op.create_table(
        "job_impact_watermarks",
        sa.Column("scope", sa.String(length=128), primary_key=True),
        sa.Column("cycle_id", sa.String(length=64), nullable=False),
        sa.Column("frozen_upper_bound_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_work_item_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_impact_watermarks_upper_bound", "job_impact_watermarks", ["frozen_upper_bound_id"])
