"""add normalized raw order and coupon settlement fields

Revision ID: 20260720_0022
Revises: 20260720_0021
Create Date: 2026-07-20 23:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_0022"
down_revision = "20260720_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_douyin_orders",
        sa.Column("order_status_raw", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "raw_douyin_orders",
        sa.Column("order_status_normalized", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "raw_douyin_orders",
        sa.Column("sale_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "raw_douyin_orders",
        sa.Column(
            "order_paid_amount_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "raw_douyin_orders",
        sa.Column("sale_channel_raw", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "raw_douyin_orders",
        sa.Column("sale_channel_normalized", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE raw_douyin_orders SET "
            "order_status_raw = order_status, "
            "order_status_normalized = CASE "
            "WHEN lower(trim(coalesce(order_status, ''))) IN "
            "('paid', 'success', 'completed', 'fulfilled') THEN 'paid' "
            "WHEN lower(trim(coalesce(order_status, ''))) IN "
            "('closed', 'cancelled', 'canceled', 'unpaid_closed') THEN 'closed' "
            "WHEN lower(trim(coalesce(order_status, ''))) IN "
            "('refund', 'refunded', 'fully_refunded') THEN 'refunded' "
            "ELSE 'unknown' END, "
            "sale_time = pay_time, "
            "order_paid_amount_cent = coalesce(paid_amount_cent, 0), "
            "sale_channel_raw = sale_channel, "
            "sale_channel_normalized = CASE "
            "WHEN lower(trim(coalesce(sale_channel, ''))) IN "
            "('live', 'live_stream', 'livestream') THEN 'live' "
            "WHEN lower(trim(coalesce(sale_channel, ''))) IN "
            "('short_video', 'shortvideo', 'video') THEN 'short_video' "
            "WHEN trim(coalesce(sale_channel, '')) = '' THEN 'unknown' "
            "ELSE 'other' END"
        )
    )
    op.create_index(
        "idx_raw_douyin_orders_status",
        "raw_douyin_orders",
        ["order_status_normalized"],
    )
    op.create_index(
        "idx_raw_douyin_orders_sale_month", "raw_douyin_orders", ["sale_time"]
    )
    op.create_index(
        "idx_raw_douyin_orders_channel_owner",
        "raw_douyin_orders",
        ["sale_channel_normalized", "owner_account_id"],
    )

    op.add_column(
        "raw_douyin_order_coupons",
        sa.Column("coupon_status_raw", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "raw_douyin_order_coupons",
        sa.Column("coupon_status_normalized", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "raw_douyin_order_coupons",
        sa.Column("coupon_paid_amount_cent", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "raw_douyin_order_coupons",
        sa.Column(
            "coupon_refunded_amount_cent",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "raw_douyin_order_coupons",
        sa.Column("latest_refund_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE raw_douyin_order_coupons SET "
            "coupon_status_raw = coupon_status, "
            "coupon_status_normalized = CASE "
            "WHEN lower(trim(coalesce(coupon_status, ''))) IN "
            "('available', 'unused', 'valid') THEN 'available' "
            "WHEN lower(trim(coalesce(coupon_status, ''))) IN "
            "('verified', 'fulfilled', 'used', 'success') THEN 'verified' "
            "WHEN lower(trim(coalesce(coupon_status, ''))) IN "
            "('cancelled', 'canceled', 'revoked', 'reversed') THEN 'cancelled' "
            "WHEN lower(trim(coalesce(coupon_status, ''))) IN "
            "('refund', 'refunded', 'fully_refunded') THEN 'refunded' "
            "ELSE 'unknown' END, "
            "coupon_refunded_amount_cent = coalesce(coupon_refunded_cent, 0), "
            "latest_refund_at = coupon_refund_time"
        )
    )
    op.execute(
        sa.text(
            "UPDATE raw_douyin_order_coupons SET coupon_paid_amount_cent = ("
            "SELECT raw_douyin_orders.order_paid_amount_cent "
            "FROM raw_douyin_orders "
            "WHERE raw_douyin_orders.order_id = raw_douyin_order_coupons.order_id"
            ") WHERE (SELECT count(*) FROM raw_douyin_order_coupons AS sibling "
            "WHERE sibling.order_id = raw_douyin_order_coupons.order_id) = 1"
        )
    )
    op.create_index(
        "idx_raw_douyin_order_coupons_status",
        "raw_douyin_order_coupons",
        ["coupon_status_normalized"],
    )
    op.create_index(
        "idx_raw_douyin_order_coupons_latest_refund",
        "raw_douyin_order_coupons",
        ["latest_refund_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_raw_douyin_order_coupons_latest_refund",
        table_name="raw_douyin_order_coupons",
    )
    op.drop_index(
        "idx_raw_douyin_order_coupons_status",
        table_name="raw_douyin_order_coupons",
    )
    with op.batch_alter_table("raw_douyin_order_coupons") as batch_op:
        batch_op.drop_column("latest_refund_at")
        batch_op.drop_column("coupon_refunded_amount_cent")
        batch_op.drop_column("coupon_paid_amount_cent")
        batch_op.drop_column("coupon_status_normalized")
        batch_op.drop_column("coupon_status_raw")

    op.drop_index(
        "idx_raw_douyin_orders_channel_owner", table_name="raw_douyin_orders"
    )
    op.drop_index(
        "idx_raw_douyin_orders_sale_month", table_name="raw_douyin_orders"
    )
    op.drop_index("idx_raw_douyin_orders_status", table_name="raw_douyin_orders")
    with op.batch_alter_table("raw_douyin_orders") as batch_op:
        batch_op.drop_column("sale_channel_normalized")
        batch_op.drop_column("sale_channel_raw")
        batch_op.drop_column("order_paid_amount_cent")
        batch_op.drop_column("sale_time")
        batch_op.drop_column("order_status_normalized")
        batch_op.drop_column("order_status_raw")
