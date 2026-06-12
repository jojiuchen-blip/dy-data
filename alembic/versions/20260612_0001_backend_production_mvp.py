"""backend production mvp schema

Revision ID: 20260612_0001
Revises:
Create Date: 2026-06-12 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260612_0001"
down_revision = None
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "raw_douyin_orders",
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("order_status", sa.Text()),
        sa.Column("sku_id", sa.Text()),
        sa.Column("product_name", sa.Text()),
        sa.Column("pay_time", sa.DateTime(timezone=True)),
        sa.Column("create_order_time", sa.DateTime(timezone=True)),
        sa.Column("paid_amount_cent", sa.Integer()),
        sa.Column("owner_account_id", sa.Text()),
        sa.Column("owner_douyin_uid", sa.Text()),
        sa.Column("owner_account_name", sa.Text()),
        sa.Column("sale_role", sa.Text()),
        sa.Column("sale_channel", sa.Text()),
        sa.Column("intention_poi_id", sa.Text()),
        sa.Column("raw_payload", json_type(), nullable=False),
        sa.Column("source_run_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_raw_douyin_orders_sku_id", "raw_douyin_orders", ["sku_id"])
    op.create_index("ix_raw_douyin_orders_pay_time", "raw_douyin_orders", ["pay_time"])
    op.create_index("ix_raw_douyin_orders_owner_account_id", "raw_douyin_orders", ["owner_account_id"])
    op.create_index("ix_raw_douyin_orders_owner_account_name", "raw_douyin_orders", ["owner_account_name"])
    op.create_index("ix_raw_douyin_orders_source_run_id", "raw_douyin_orders", ["source_run_id"])

    op.create_table(
        "raw_douyin_order_coupons",
        sa.Column("coupon_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), sa.ForeignKey("raw_douyin_orders.order_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_item_id", sa.Text()),
        sa.Column("coupon_status", sa.Text()),
        sa.Column("coupon_updated_at", sa.DateTime(timezone=True)),
        sa.Column("coupon_refunded_cent", sa.Integer()),
        sa.Column("coupon_refund_time", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", json_type(), nullable=False),
        sa.Column("source_run_id", sa.Text()),
    )
    op.create_index("ix_raw_douyin_order_coupons_order_id", "raw_douyin_order_coupons", ["order_id"])
    op.create_index("ix_raw_douyin_order_coupons_coupon_status", "raw_douyin_order_coupons", ["coupon_status"])
    op.create_index("ix_raw_douyin_order_coupons_source_run_id", "raw_douyin_order_coupons", ["source_run_id"])

    op.create_table(
        "raw_douyin_verify_records",
        sa.Column("verify_id", sa.Text(), primary_key=True),
        sa.Column("coupon_id", sa.Text()),
        sa.Column("verify_status", sa.Text()),
        sa.Column("verify_time", sa.DateTime(timezone=True)),
        sa.Column("poi_id", sa.Text()),
        sa.Column("verify_store_name_raw", sa.Text()),
        sa.Column("sku_id", sa.Text()),
        sa.Column("product_name", sa.Text()),
        sa.Column("paid_amount_cent", sa.Integer()),
        sa.Column("cancel_time", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", json_type(), nullable=False),
        sa.Column("source_run_id", sa.Text()),
    )
    op.create_index("ix_raw_douyin_verify_records_coupon_id", "raw_douyin_verify_records", ["coupon_id"])
    op.create_index("ix_raw_douyin_verify_records_verify_status", "raw_douyin_verify_records", ["verify_status"])
    op.create_index("ix_raw_douyin_verify_records_verify_time", "raw_douyin_verify_records", ["verify_time"])
    op.create_index("ix_raw_douyin_verify_records_poi_id", "raw_douyin_verify_records", ["poi_id"])
    op.create_index("ix_raw_douyin_verify_records_source_run_id", "raw_douyin_verify_records", ["source_run_id"])

    op.create_table(
        "raw_aweme_bindings",
        sa.Column("binding_key", sa.Text(), primary_key=True),
        sa.Column("douyin_id", sa.Text()),
        sa.Column("douyin_nickname", sa.Text()),
        sa.Column("account_id", sa.Text()),
        sa.Column("account_name", sa.Text()),
        sa.Column("poi_id", sa.Text()),
        sa.Column("binding_status", sa.Text()),
        sa.Column("raw_payload", json_type(), nullable=False),
        sa.Column("source_run_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_raw_aweme_bindings_douyin_id", "raw_aweme_bindings", ["douyin_id"])
    op.create_index("ix_raw_aweme_bindings_douyin_nickname", "raw_aweme_bindings", ["douyin_nickname"])
    op.create_index("ix_raw_aweme_bindings_account_id", "raw_aweme_bindings", ["account_id"])
    op.create_index("ix_raw_aweme_bindings_poi_id", "raw_aweme_bindings", ["poi_id"])
    op.create_index("ix_raw_aweme_bindings_source_run_id", "raw_aweme_bindings", ["source_run_id"])

    op.create_table(
        "dim_stores",
        sa.Column("store_id", sa.Text(), primary_key=True),
        sa.Column("store_name", sa.Text(), nullable=False),
        sa.Column("certified_subject_name", sa.Text()),
        sa.Column("region", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "dim_store_poi_mappings",
        sa.Column("store_id", sa.Text(), sa.ForeignKey("dim_stores.store_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("poi_id", sa.Text(), primary_key=True),
        sa.Column("poi_name", sa.Text()),
        sa.Column("mapping_source", sa.Text()),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("poi_id", name="uq_dim_store_poi_mappings_poi_id"),
    )
    op.create_index("ix_dim_store_poi_mappings_store_id", "dim_store_poi_mappings", ["store_id"])

    op.create_table(
        "dim_sku_product_rules",
        sa.Column("sku_id", sa.Text(), primary_key=True),
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column("product_name", sa.Text()),
        sa.Column("commission_rate", sa.Numeric(6, 4), nullable=False),
        sa.Column("is_service_product", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dim_sku_product_rules_product_type", "dim_sku_product_rules", ["product_type"])

    op.create_table(
        "dim_aweme_accounts",
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column("nickname", sa.Text()),
        sa.Column("store_id", sa.Text(), sa.ForeignKey("dim_stores.store_id")),
        sa.Column("binding_status", sa.Text()),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dim_aweme_accounts_nickname", "dim_aweme_accounts", ["nickname"])

    op.create_table(
        "settlement_order_details",
        sa.Column("coupon_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("verify_id", sa.Text()),
        sa.Column("sku_id", sa.Text()),
        sa.Column("owner_account_id", sa.Text()),
        sa.Column("owner_account_name", sa.Text()),
        sa.Column("product_type", sa.Text(), nullable=False),
        sa.Column("sale_store_id", sa.Text()),
        sa.Column("sale_store_name", sa.Text()),
        sa.Column("sale_time", sa.DateTime(timezone=True)),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("verify_store_id", sa.Text()),
        sa.Column("verify_store_name", sa.Text()),
        sa.Column("verify_time", sa.DateTime(timezone=True)),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("is_commissionable", sa.Boolean(), nullable=False),
        sa.Column("is_refund_excluded", sa.Boolean(), nullable=False),
        sa.Column("paid_amount_cent", sa.Integer(), nullable=False),
        sa.Column("commission_rate", sa.Numeric(6, 4), nullable=False),
        sa.Column("receivable_commission_cent", sa.Integer(), nullable=False),
        sa.Column("payable_commission_cent", sa.Integer(), nullable=False),
        sa.Column("source_run_id", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_settlement_order_details_order_id", "settlement_order_details", ["order_id"])
    op.create_index("ix_settlement_order_details_verify_id", "settlement_order_details", ["verify_id"])
    op.create_index("ix_settlement_order_details_sku_id", "settlement_order_details", ["sku_id"])
    op.create_index("ix_settlement_order_details_sale_store_id", "settlement_order_details", ["sale_store_id"])
    op.create_index("ix_settlement_order_details_verify_store_id", "settlement_order_details", ["verify_store_id"])
    op.create_index("ix_settlement_order_details_sale_time", "settlement_order_details", ["sale_time"])
    op.create_index("ix_settlement_order_details_verify_time", "settlement_order_details", ["verify_time"])
    op.create_index("ix_settlement_order_details_product_type", "settlement_order_details", ["product_type"])
    op.create_index("ix_settlement_order_details_relation_type", "settlement_order_details", ["relation_type"])
    op.create_index("ix_settlement_order_details_source_run_id", "settlement_order_details", ["source_run_id"])
    op.create_index(
        "ix_settlement_order_details_sale_store_month",
        "settlement_order_details",
        ["sale_store_id", "sale_time"],
    )
    op.create_index(
        "ix_settlement_order_details_verify_store_month",
        "settlement_order_details",
        ["verify_store_id", "verify_time"],
    )

    op.create_table(
        "agg_store_ranking",
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("product_type", sa.Text(), primary_key=True),
        sa.Column("store_id", sa.Text(), primary_key=True),
        sa.Column("store_name", sa.Text()),
        sa.Column("sales_order_count", sa.Integer(), nullable=False),
        sa.Column("self_sold_self_verified_count", sa.Integer(), nullable=False),
        sa.Column("self_sold_other_verified_count", sa.Integer(), nullable=False),
        sa.Column("other_sold_self_verified_count", sa.Integer(), nullable=False),
        sa.Column("self_verify_income_cent", sa.Integer(), nullable=False),
        sa.Column("effective_commission_income_cent", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agg_store_monthly_settlement",
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("store_id", sa.Text(), primary_key=True),
        sa.Column("product_type", sa.Text(), primary_key=True),
        sa.Column("estimated_receivable_commission_cent", sa.Integer(), nullable=False),
        sa.Column("commissionable_total_cent", sa.Integer(), nullable=False),
        sa.Column("estimated_payable_commission_cent", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "job_runs",
        sa.Column("job_id", sa.Text(), primary_key=True),
        sa.Column("job_name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata_json", json_type(), nullable=False),
    )
    op.create_index("ix_job_runs_job_name", "job_runs", ["job_name"])
    op.create_index("ix_job_runs_status", "job_runs", ["status"])

    op.create_table(
        "data_quality_issues",
        sa.Column("issue_id", sa.Text(), primary_key=True),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text()),
        sa.Column("coupon_id", sa.Text()),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("raw_context_json", json_type(), nullable=False),
        sa.Column("source_run_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_data_quality_issues_issue_type", "data_quality_issues", ["issue_type"])
    op.create_index("ix_data_quality_issues_order_id", "data_quality_issues", ["order_id"])
    op.create_index("ix_data_quality_issues_coupon_id", "data_quality_issues", ["coupon_id"])
    op.create_index("ix_data_quality_issues_source_run_id", "data_quality_issues", ["source_run_id"])
    op.create_index("ix_data_quality_issues_type_source", "data_quality_issues", ["issue_type", "source_run_id"])
    op.create_index("ix_data_quality_issues_order_coupon", "data_quality_issues", ["order_id", "coupon_id"])


def downgrade() -> None:
    op.drop_table("data_quality_issues")
    op.drop_table("job_runs")
    op.drop_table("agg_store_monthly_settlement")
    op.drop_table("agg_store_ranking")
    op.drop_table("settlement_order_details")
    op.drop_table("dim_aweme_accounts")
    op.drop_table("dim_sku_product_rules")
    op.drop_table("dim_store_poi_mappings")
    op.drop_table("dim_stores")
    op.drop_table("raw_aweme_bindings")
    op.drop_table("raw_douyin_verify_records")
    op.drop_table("raw_douyin_order_coupons")
    op.drop_table("raw_douyin_orders")
