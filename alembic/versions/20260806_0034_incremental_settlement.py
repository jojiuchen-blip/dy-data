"""add local-settlement fingerprints and idempotency constraints

Revision ID: 20260806_0034
Revises: 20260806_0033
Create Date: 2026-08-07 00:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op


revision = "20260806_0034"
down_revision = "20260806_0033"
branch_labels = None
depends_on = None


FEE_RESULT_RUN_UNIQUE = "uk_settlement_fee_result_calculation_run"
ADJUSTMENT_REFUND_UNIQUE = "uk_settlement_fee_adjustment_refund_result_direction"

COMPOSITE_LOOKUP_INDEXES = (
    (
        "job_impacts",
        "ix_job_impacts_source_run_id_id",
        ("source_run_id", "id"),
    ),
    (
        "raw_douyin_orders",
        "ix_raw_douyin_orders_intention_poi_id_order_id",
        ("intention_poi_id", "order_id"),
    ),
    (
        "raw_douyin_order_coupons",
        "ix_raw_douyin_order_coupons_order_id_coupon_id",
        ("order_id", "coupon_id"),
    ),
    (
        "raw_douyin_verify_records",
        "ix_raw_douyin_verify_records_poi_id_coupon_id",
        ("poi_id", "coupon_id"),
    ),
)


def _preflight_unique_groups(bind: sa.Connection) -> None:
    result_duplicate = bind.execute(
        sa.text(
            "SELECT 1 FROM settlement_fee_result "
            "GROUP BY coupon_id, fee_direction, calculation_run_id "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if result_duplicate is not None:
        raise RuntimeError(
            "0034 preflight blocked: settlement fee result calculation-run groups "
            "contain duplicates; no schema/data changes were applied; manual data governance is required."
        )

    adjustment_duplicate = bind.execute(
        sa.text(
            "SELECT 1 FROM settlement_fee_adjustment "
            "WHERE refund_event_id IS NOT NULL "
            "GROUP BY refund_event_id, original_fee_result_id, fee_direction "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if adjustment_duplicate is not None:
        raise RuntimeError(
            "0034 preflight blocked: settlement fee adjustment refund groups "
            "contain duplicates; no schema/data changes were applied; manual data governance is required."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if not context.is_offline_mode():
        _preflight_unique_groups(bind)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("settlement_fee_result", recreate="always") as batch:
            batch.add_column(sa.Column("input_fingerprint", sa.String(length=64), nullable=True))
            batch.create_unique_constraint(
                FEE_RESULT_RUN_UNIQUE,
                ["coupon_id", "fee_direction", "calculation_run_id"],
            )
        with op.batch_alter_table("settlement_fee_adjustment", recreate="always") as batch:
            batch.create_unique_constraint(
                ADJUSTMENT_REFUND_UNIQUE,
                ["refund_event_id", "original_fee_result_id", "fee_direction"],
            )
        for table_name, index_name, columns in COMPOSITE_LOOKUP_INDEXES:
            op.create_index(index_name, table_name, list(columns), unique=False)
        return

    op.add_column(
        "settlement_fee_result",
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        FEE_RESULT_RUN_UNIQUE,
        "settlement_fee_result",
        ["coupon_id", "fee_direction", "calculation_run_id"],
    )
    op.create_unique_constraint(
        ADJUSTMENT_REFUND_UNIQUE,
        "settlement_fee_adjustment",
        ["refund_event_id", "original_fee_result_id", "fee_direction"],
    )
    for table_name, index_name, columns in COMPOSITE_LOOKUP_INDEXES:
        op.create_index(index_name, table_name, list(columns), unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name, index_name, _columns in reversed(COMPOSITE_LOOKUP_INDEXES):
        op.drop_index(index_name, table_name=table_name)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("settlement_fee_adjustment", recreate="always") as batch:
            batch.drop_constraint(ADJUSTMENT_REFUND_UNIQUE, type_="unique")
        with op.batch_alter_table("settlement_fee_result", recreate="always") as batch:
            batch.drop_constraint(FEE_RESULT_RUN_UNIQUE, type_="unique")
            batch.drop_column("input_fingerprint")
        return

    op.drop_constraint(ADJUSTMENT_REFUND_UNIQUE, "settlement_fee_adjustment", type_="unique")
    op.drop_constraint(FEE_RESULT_RUN_UNIQUE, "settlement_fee_result", type_="unique")
    op.drop_column("settlement_fee_result", "input_fingerprint")
