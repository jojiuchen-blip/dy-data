"""add immutable settlement results, adjustments, statements, and projections

Revision ID: 20260720_0021
Revises: 20260720_0020
Create Date: 2026-07-20 18:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720_0021"
down_revision = "20260720_0020"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    if op.get_bind().dialect.name == "sqlite":
        return sa.Column("id", sa.Integer(), nullable=False, autoincrement=True)
    return sa.Column(
        "id", sa.BigInteger(), sa.Identity(), nullable=False, autoincrement=True
    )


def _json_type() -> sa.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "gmt_create",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "gmt_modified",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def upgrade() -> None:
    _create_refund_event()
    _create_fee_result()
    _create_fee_result_current()
    _create_fee_adjustment()
    _create_statement()
    _create_statement_line()
    _create_statement_entry()
    _replace_monthly_projection()
    _replace_ranking_projection()


def downgrade() -> None:
    _guard_downgrade_against_new_data()
    _restore_ranking_projection()
    _restore_monthly_projection()
    op.drop_table("settlement_statement_entry")
    op.drop_table("settlement_statement_line")
    op.drop_table("settlement_statement")
    op.drop_table("settlement_fee_adjustment")
    op.drop_table("settlement_fee_result_current")
    op.drop_table("settlement_fee_result")
    op.drop_table("douyin_refund_event")


def _create_refund_event() -> None:
    op.create_table(
        "douyin_refund_event",
        _id_column(),
        sa.Column("refund_event_id", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("coupon_id", sa.String(length=128), nullable=True),
        sa.Column("refund_type", sa.Integer(), nullable=False),
        sa.Column("refund_status", sa.Integer(), nullable=False),
        sa.Column(
            "refund_amount_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_run_id", sa.String(length=128), nullable=True),
        sa.Column("raw_payload", _json_type(), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_douyin_refund_event"),
        sa.UniqueConstraint(
            "refund_event_id", name="uk_douyin_refund_event_id"
        ),
        sa.CheckConstraint(
            "refund_type IN (1, 2)", name="ck_douyin_refund_event_type"
        ),
        sa.CheckConstraint(
            "refund_status IN (1, 2, 3, 4)",
            name="ck_douyin_refund_event_status",
        ),
        sa.CheckConstraint(
            "refund_amount_cent >= 0", name="ck_douyin_refund_event_amount"
        ),
    )
    op.create_index(
        "idx_douyin_refund_event_coupon_time",
        "douyin_refund_event",
        ["coupon_id", "occurred_at"],
    )
    op.create_index(
        "idx_douyin_refund_event_order_time",
        "douyin_refund_event",
        ["order_id", "occurred_at"],
    )
    op.create_index(
        "idx_douyin_refund_event_source_run",
        "douyin_refund_event",
        ["source_run_id"],
    )


def _create_fee_result() -> None:
    op.create_table(
        "settlement_fee_result",
        _id_column(),
        sa.Column("fee_result_id", sa.String(length=128), nullable=False),
        sa.Column("coupon_id", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("original_business_month", sa.String(length=7), nullable=False),
        sa.Column("rule_match_date", sa.Date(), nullable=False),
        sa.Column("sale_store_id", sa.String(length=128), nullable=True),
        sa.Column("verify_store_id", sa.String(length=128), nullable=True),
        sa.Column("sku_id", sa.String(length=128), nullable=False),
        sa.Column(
            "product_scope",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "product_type",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "sale_channel_normalized", sa.String(length=32), nullable=False
        ),
        sa.Column(
            "source_amount_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "refunded_amount_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "fee_base_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "fee_rate",
            sa.Numeric(precision=8, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "fee_amount_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("scope_rule_version", sa.String(length=64), nullable=False),
        sa.Column("result_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("calculation_run_id", sa.String(length=128), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_fee_result"),
        sa.UniqueConstraint(
            "fee_result_id", name="uk_settlement_fee_result_id"
        ),
        sa.UniqueConstraint(
            "coupon_id",
            "fee_direction",
            "result_version",
            name="uk_settlement_fee_result_revision",
        ),
        sa.CheckConstraint(
            "fee_direction IN (1, 2)", name="ck_settlement_fee_result_direction"
        ),
        sa.CheckConstraint(
            "result_version > 0", name="ck_settlement_fee_result_version"
        ),
        sa.CheckConstraint(
            "source_amount_cent >= 0 AND refunded_amount_cent >= 0 "
            "AND fee_base_cent >= 0 AND fee_amount_cent >= 0",
            name="ck_settlement_fee_result_amounts",
        ),
        sa.CheckConstraint(
            "fee_rate >= 0 AND fee_rate <= 1",
            name="ck_settlement_fee_result_rate",
        ),
        sa.CheckConstraint(
            "result_status IN (1, 2, 3)",
            name="ck_settlement_fee_result_status",
        ),
    )
    op.create_index(
        "idx_settlement_fee_result_month_store",
        "settlement_fee_result",
        [
            "original_business_month",
            "fee_direction",
            "sale_store_id",
            "verify_store_id",
        ],
    )
    op.create_index(
        "idx_settlement_fee_result_product",
        "settlement_fee_result",
        ["product_scope", "product_type"],
    )
    op.create_index(
        "idx_settlement_fee_result_rule", "settlement_fee_result", ["rule_version"]
    )
    op.create_index(
        "idx_settlement_fee_result_match_date",
        "settlement_fee_result",
        ["rule_match_date", "fee_direction"],
    )
    op.create_index(
        "idx_settlement_fee_result_calculation_run",
        "settlement_fee_result",
        ["calculation_run_id"],
    )


def _create_fee_result_current() -> None:
    op.create_table(
        "settlement_fee_result_current",
        _id_column(),
        sa.Column("coupon_id", sa.String(length=128), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("fee_result_id", sa.String(length=128), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_fee_result_current"),
        sa.UniqueConstraint(
            "coupon_id",
            "fee_direction",
            name="uk_settlement_fee_result_current_slot",
        ),
        sa.UniqueConstraint(
            "fee_result_id", name="uk_settlement_fee_result_current_result"
        ),
        sa.CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_fee_result_current_direction",
        ),
    )


def _create_fee_adjustment() -> None:
    op.create_table(
        "settlement_fee_adjustment",
        _id_column(),
        sa.Column("adjustment_id", sa.String(length=128), nullable=False),
        sa.Column("original_fee_result_id", sa.String(length=128), nullable=False),
        sa.Column("refund_event_id", sa.String(length=128), nullable=True),
        sa.Column("coupon_id", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("original_business_month", sa.String(length=7), nullable=False),
        sa.Column("adjustment_posting_month", sa.String(length=7), nullable=False),
        sa.Column("adjustment_type", sa.Integer(), nullable=False),
        sa.Column(
            "adjustment_base_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "adjustment_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("adjustment_reason", sa.String(length=1000), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_fee_adjustment"),
        sa.UniqueConstraint(
            "adjustment_id", name="uk_settlement_fee_adjustment_id"
        ),
        sa.CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_fee_adjustment_direction",
        ),
        sa.CheckConstraint(
            "adjustment_type IN (1, 2, 3, 4)",
            name="ck_settlement_fee_adjustment_type",
        ),
    )
    op.create_index(
        "idx_settlement_fee_adjustment_original",
        "settlement_fee_adjustment",
        ["original_fee_result_id"],
    )
    op.create_index(
        "idx_settlement_fee_adjustment_refund",
        "settlement_fee_adjustment",
        ["refund_event_id"],
    )
    op.create_index(
        "idx_settlement_fee_adjustment_posting",
        "settlement_fee_adjustment",
        ["adjustment_posting_month", "fee_direction"],
    )
    op.create_index(
        "idx_settlement_fee_adjustment_coupon",
        "settlement_fee_adjustment",
        ["coupon_id", "occurred_at"],
    )
    op.create_index(
        "idx_settlement_fee_adjustment_rule",
        "settlement_fee_adjustment",
        ["rule_version"],
    )


def _create_statement() -> None:
    op.create_table(
        "settlement_statement",
        _id_column(),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("statement_month", sa.String(length=7), nullable=False),
        sa.Column("statement_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "promotion_original_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "promotion_adjustment_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "promotion_net_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "management_original_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "management_adjustment_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "management_net_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("confirmed_by", sa.String(length=128), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_version", sa.String(length=64), nullable=True),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_statement"),
        sa.UniqueConstraint("statement_id", name="uk_settlement_statement_id"),
        sa.UniqueConstraint(
            "store_id",
            "statement_month",
            name="uk_settlement_statement_store_month",
        ),
        sa.UniqueConstraint(
            "lock_version", name="uk_settlement_statement_lock_version"
        ),
        sa.CheckConstraint(
            "statement_status IN (1, 2, 3, 4)",
            name="ck_settlement_statement_status",
        ),
        sa.CheckConstraint(
            "promotion_net_fee_cent = promotion_original_fee_cent + "
            "promotion_adjustment_fee_cent",
            name="ck_settlement_statement_promotion_net",
        ),
        sa.CheckConstraint(
            "management_net_fee_cent = management_original_fee_cent + "
            "management_adjustment_fee_cent",
            name="ck_settlement_statement_management_net",
        ),
    )
    op.create_index(
        "idx_settlement_statement_status_month",
        "settlement_statement",
        ["statement_status", "statement_month"],
    )
    op.create_index(
        "idx_settlement_statement_locked_at", "settlement_statement", ["locked_at"]
    )


def _create_statement_line() -> None:
    op.create_table(
        "settlement_statement_line",
        _id_column(),
        sa.Column("statement_line_id", sa.String(length=128), nullable=False),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column(
            "product_scope",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "product_type",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "original_entry_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "adjustment_entry_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "original_base_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "adjustment_base_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("net_base_cent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "original_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "adjustment_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("net_fee_cent", sa.BigInteger(), nullable=False, server_default="0"),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_statement_line"),
        sa.UniqueConstraint(
            "statement_line_id", name="uk_settlement_statement_line_id"
        ),
        sa.UniqueConstraint(
            "statement_id",
            "fee_direction",
            "product_scope",
            "product_type",
            name="uk_settlement_statement_line_dimension",
        ),
        sa.CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_statement_line_direction",
        ),
        sa.CheckConstraint(
            "original_entry_count >= 0 AND adjustment_entry_count >= 0",
            name="ck_settlement_statement_line_counts",
        ),
        sa.CheckConstraint(
            "net_base_cent = original_base_cent + adjustment_base_cent",
            name="ck_settlement_statement_line_net_base",
        ),
        sa.CheckConstraint(
            "net_fee_cent = original_fee_cent + adjustment_fee_cent",
            name="ck_settlement_statement_line_net_fee",
        ),
    )
    op.create_index(
        "idx_settlement_statement_line_statement",
        "settlement_statement_line",
        ["statement_id", "fee_direction"],
    )


def _create_statement_entry() -> None:
    op.create_table(
        "settlement_statement_entry",
        _id_column(),
        sa.Column("statement_entry_id", sa.String(length=128), nullable=False),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("statement_line_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.String(length=128), nullable=False),
        sa.Column("original_fee_result_id", sa.String(length=128), nullable=False),
        sa.Column("coupon_id", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("original_business_month", sa.String(length=7), nullable=False),
        sa.Column("statement_posting_month", sa.String(length=7), nullable=False),
        sa.Column(
            "product_scope",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "product_type",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "base_amount_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "fee_amount_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_settlement_statement_entry"),
        sa.UniqueConstraint(
            "statement_entry_id", name="uk_settlement_statement_entry_id"
        ),
        sa.UniqueConstraint(
            "source_type",
            "source_record_id",
            name="uk_settlement_statement_entry_source",
        ),
        sa.CheckConstraint(
            "source_type IN (1, 2)",
            name="ck_settlement_statement_entry_source_type",
        ),
        sa.CheckConstraint(
            "fee_direction IN (1, 2)",
            name="ck_settlement_statement_entry_direction",
        ),
    )
    op.create_index(
        "idx_settlement_statement_entry_line",
        "settlement_statement_entry",
        ["statement_line_id"],
    )
    op.create_index(
        "idx_settlement_statement_entry_statement_order",
        "settlement_statement_entry",
        ["statement_id", "order_id"],
    )
    op.create_index(
        "idx_settlement_statement_entry_coupon",
        "settlement_statement_entry",
        ["coupon_id"],
    )
    op.create_index(
        "idx_settlement_statement_entry_original",
        "settlement_statement_entry",
        ["original_fee_result_id"],
    )


def _replace_monthly_projection() -> None:
    op.create_table(
        "agg_store_monthly_settlement_v2",
        _id_column(),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column(
            "product_scope",
            sa.String(length=128),
            nullable=False,
            server_default="all",
        ),
        sa.Column(
            "product_type",
            sa.String(length=128),
            nullable=False,
            server_default="all",
        ),
        sa.Column("sales_order_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sales_amount_cent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "verified_order_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "verified_amount_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "promotion_base_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "promotion_original_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "promotion_adjustment_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "promotion_net_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "management_base_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "management_original_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "management_adjustment_fee_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "management_net_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("statement_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("projection_run_id", sa.String(length=128), nullable=False),
        sa.Column(
            "estimated_receivable_commission_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "commissionable_total_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "estimated_payable_commission_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_agg_store_monthly_settlement"),
        sa.UniqueConstraint(
            "month",
            "store_id",
            "product_scope",
            "product_type",
            name="uk_agg_store_monthly_settlement_slot",
        ),
        sa.CheckConstraint(
            "statement_status IN (1, 2, 3, 4)",
            name="ck_agg_store_monthly_settlement_status",
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO agg_store_monthly_settlement_v2 ("
            "month, store_id, product_scope, product_type, projection_run_id, "
            "estimated_receivable_commission_cent, commissionable_total_cent, "
            "estimated_payable_commission_cent, gmt_create, gmt_modified"
            ") SELECT month, store_id, 'all', product_type, "
            "'migration-20260720-0021', estimated_receivable_commission_cent, "
            "commissionable_total_cent, estimated_payable_commission_cent, "
            "updated_at, updated_at FROM agg_store_monthly_settlement"
        )
    )
    op.drop_table("agg_store_monthly_settlement")
    op.rename_table(
        "agg_store_monthly_settlement_v2", "agg_store_monthly_settlement"
    )
    op.create_index(
        "idx_agg_store_monthly_settlement_store_month",
        "agg_store_monthly_settlement",
        ["store_id", "month"],
    )
    op.create_index(
        "idx_agg_store_monthly_settlement_status",
        "agg_store_monthly_settlement",
        ["statement_status"],
    )


def _replace_ranking_projection() -> None:
    op.create_table(
        "agg_store_ranking_v2",
        _id_column(),
        sa.Column("period_type", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("period_key", sa.String(length=7), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("store_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "product_scope",
            sa.String(length=128),
            nullable=False,
            server_default="all",
        ),
        sa.Column(
            "product_type",
            sa.String(length=128),
            nullable=False,
            server_default="all",
        ),
        sa.Column("sales_order_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sales_amount_cent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "verified_order_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "verified_amount_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "promotion_net_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "management_net_fee_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "net_settlement_reference_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("projection_run_id", sa.String(length=128), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column(
            "self_sold_self_verified_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "self_sold_other_verified_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "other_sold_self_verified_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "self_verify_income_cent", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "effective_commission_income_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_agg_store_ranking"),
        sa.UniqueConstraint(
            "period_type",
            "period_key",
            "store_id",
            "product_scope",
            "product_type",
            name="uk_agg_store_ranking_slot",
        ),
        sa.CheckConstraint(
            "period_type IN (1, 2)", name="ck_agg_store_ranking_period_type"
        ),
        sa.CheckConstraint(
            "net_settlement_reference_cent = promotion_net_fee_cent - "
            "management_net_fee_cent",
            name="ck_agg_store_ranking_net_reference",
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO agg_store_ranking_v2 ("
            "period_type, period_key, store_id, store_name, product_scope, "
            "product_type, sales_order_count, projection_run_id, month, "
            "self_sold_self_verified_count, self_sold_other_verified_count, "
            "other_sold_self_verified_count, self_verify_income_cent, "
            "effective_commission_income_cent, gmt_create, gmt_modified"
            ") SELECT 1, month, store_id, COALESCE(store_name, ''), 'all', "
            "product_type, sales_order_count, 'migration-20260720-0021', month, "
            "self_sold_self_verified_count, self_sold_other_verified_count, "
            "other_sold_self_verified_count, self_verify_income_cent, "
            "effective_commission_income_cent, updated_at, updated_at "
            "FROM agg_store_ranking"
        )
    )
    op.drop_table("agg_store_ranking")
    op.rename_table("agg_store_ranking_v2", "agg_store_ranking")
    op.create_index(
        "idx_agg_store_ranking_period_fee",
        "agg_store_ranking",
        ["period_type", "period_key", "promotion_net_fee_cent"],
    )
    op.create_index(
        "idx_agg_store_ranking_period_sales",
        "agg_store_ranking",
        ["period_type", "period_key", "sales_amount_cent"],
    )
    op.create_index(
        "idx_agg_store_ranking_month", "agg_store_ranking", ["month"]
    )


def _guard_downgrade_against_new_data() -> None:
    bind = op.get_bind()
    for table_name in (
        "settlement_statement_entry",
        "settlement_statement_line",
        "settlement_statement",
        "settlement_fee_adjustment",
        "settlement_fee_result_current",
        "settlement_fee_result",
        "douyin_refund_event",
    ):
        count = bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table_name}"))
        if count:
            raise RuntimeError(
                "cannot downgrade settlement reporting schema while new tables "
                f"contain data: {table_name}={count}"
            )

    monthly_target_count = bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM agg_store_monthly_settlement WHERE "
            "product_scope <> 'all' OR sales_order_count <> 0 OR "
            "sales_amount_cent <> 0 OR verified_order_count <> 0 OR "
            "verified_amount_cent <> 0 OR promotion_base_cent <> 0 OR "
            "promotion_original_fee_cent <> 0 OR promotion_adjustment_fee_cent <> 0 OR "
            "promotion_net_fee_cent <> 0 OR management_base_cent <> 0 OR "
            "management_original_fee_cent <> 0 OR management_adjustment_fee_cent <> 0 OR "
            "management_net_fee_cent <> 0 OR statement_status <> 1"
        )
    )
    ranking_target_count = bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM agg_store_ranking WHERE period_type <> 1 OR "
            "period_key <> month OR product_scope <> 'all' OR sales_amount_cent <> 0 OR "
            "verified_order_count <> 0 OR verified_amount_cent <> 0 OR "
            "promotion_net_fee_cent <> 0 OR management_net_fee_cent <> 0 OR "
            "net_settlement_reference_cent <> 0"
        )
    )
    if monthly_target_count or ranking_target_count:
        raise RuntimeError(
            "cannot downgrade settlement reporting schema while target projection "
            f"fields contain data: monthly={monthly_target_count}, "
            f"ranking={ranking_target_count}"
        )


def _restore_monthly_projection() -> None:
    op.create_table(
        "agg_store_monthly_settlement_legacy",
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column(
            "estimated_receivable_commission_cent", sa.Integer(), nullable=False
        ),
        sa.Column("commissionable_total_cent", sa.Integer(), nullable=False),
        sa.Column(
            "estimated_payable_commission_cent", sa.Integer(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("month", "store_id", "product_type"),
    )
    op.execute(
        sa.text(
            "INSERT INTO agg_store_monthly_settlement_legacy ("
            "month, store_id, product_type, estimated_receivable_commission_cent, "
            "commissionable_total_cent, estimated_payable_commission_cent, updated_at"
            ") SELECT month, store_id, product_type, "
            "estimated_receivable_commission_cent, commissionable_total_cent, "
            "estimated_payable_commission_cent, gmt_modified "
            "FROM agg_store_monthly_settlement"
        )
    )
    op.drop_table("agg_store_monthly_settlement")
    op.rename_table(
        "agg_store_monthly_settlement_legacy", "agg_store_monthly_settlement"
    )


def _restore_ranking_projection() -> None:
    op.create_table(
        "agg_store_ranking_legacy",
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("store_name", sa.Text(), nullable=True),
        sa.Column("sales_order_count", sa.Integer(), nullable=False),
        sa.Column("self_sold_self_verified_count", sa.Integer(), nullable=False),
        sa.Column("self_sold_other_verified_count", sa.Integer(), nullable=False),
        sa.Column("other_sold_self_verified_count", sa.Integer(), nullable=False),
        sa.Column("self_verify_income_cent", sa.Integer(), nullable=False),
        sa.Column("effective_commission_income_cent", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("month", "product_type", "store_id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO agg_store_ranking_legacy ("
            "month, product_type, store_id, store_name, sales_order_count, "
            "self_sold_self_verified_count, self_sold_other_verified_count, "
            "other_sold_self_verified_count, self_verify_income_cent, "
            "effective_commission_income_cent, updated_at"
            ") SELECT month, product_type, store_id, store_name, sales_order_count, "
            "self_sold_self_verified_count, self_sold_other_verified_count, "
            "other_sold_self_verified_count, self_verify_income_cent, "
            "effective_commission_income_cent, gmt_modified FROM agg_store_ranking"
        )
    )
    op.drop_table("agg_store_ranking")
    op.rename_table("agg_store_ranking_legacy", "agg_store_ranking")
