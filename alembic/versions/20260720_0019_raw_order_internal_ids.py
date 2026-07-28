"""add compatible internal ids to raw orders and coupons

Revision ID: 20260720_0019
Revises: 20260715_0018
Create Date: 2026-07-20 15:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260720_0019"
down_revision = "20260715_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _upgrade_sqlite()
        return

    op.add_column(
        "raw_douyin_orders",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_raw_douyin_orders_id", "raw_douyin_orders", ["id"]
    )
    op.add_column(
        "raw_douyin_order_coupons",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
    )
    op.add_column(
        "raw_douyin_order_coupons",
        sa.Column("raw_order_id", sa.BigInteger(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE raw_douyin_order_coupons AS coupon "
            "SET raw_order_id = raw_order.id "
            "FROM raw_douyin_orders AS raw_order "
            "WHERE raw_order.order_id = coupon.order_id"
        )
    )
    op.alter_column(
        "raw_douyin_order_coupons",
        "raw_order_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_raw_douyin_order_coupons_id", "raw_douyin_order_coupons", ["id"]
    )
    op.create_index(
        "ix_raw_douyin_order_coupons_raw_order_id",
        "raw_douyin_order_coupons",
        ["raw_order_id"],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _downgrade_sqlite()
        return

    op.drop_index(
        "ix_raw_douyin_order_coupons_raw_order_id",
        table_name="raw_douyin_order_coupons",
    )
    op.drop_constraint(
        "uq_raw_douyin_order_coupons_id",
        "raw_douyin_order_coupons",
        type_="unique",
    )
    op.drop_column("raw_douyin_order_coupons", "raw_order_id")
    op.drop_column("raw_douyin_order_coupons", "id")
    op.drop_constraint(
        "uq_raw_douyin_orders_id", "raw_douyin_orders", type_="unique"
    )
    op.drop_column("raw_douyin_orders", "id")


def _upgrade_sqlite() -> None:
    op.add_column("raw_douyin_orders", sa.Column("id", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE raw_douyin_orders SET id = rowid WHERE id IS NULL"))
    with op.batch_alter_table("raw_douyin_orders") as batch_op:
        batch_op.alter_column("id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint("uq_raw_douyin_orders_id", ["id"])

    op.add_column(
        "raw_douyin_order_coupons", sa.Column("id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "raw_douyin_order_coupons",
        sa.Column("raw_order_id", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE raw_douyin_order_coupons "
            "SET id = rowid WHERE id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE raw_douyin_order_coupons "
            "SET raw_order_id = ("
            "SELECT raw_douyin_orders.id FROM raw_douyin_orders "
            "WHERE raw_douyin_orders.order_id = raw_douyin_order_coupons.order_id"
            ")"
        )
    )
    with op.batch_alter_table("raw_douyin_order_coupons") as batch_op:
        batch_op.alter_column("id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column(
            "raw_order_id", existing_type=sa.Integer(), nullable=False
        )
        batch_op.create_unique_constraint(
            "uq_raw_douyin_order_coupons_id", ["id"]
        )
        batch_op.create_index(
            "ix_raw_douyin_order_coupons_raw_order_id", ["raw_order_id"]
        )


def _downgrade_sqlite() -> None:
    with op.batch_alter_table("raw_douyin_order_coupons") as batch_op:
        batch_op.drop_index("ix_raw_douyin_order_coupons_raw_order_id")
        batch_op.drop_constraint(
            "uq_raw_douyin_order_coupons_id", type_="unique"
        )
        batch_op.drop_column("raw_order_id")
        batch_op.drop_column("id")
    with op.batch_alter_table("raw_douyin_orders") as batch_op:
        batch_op.drop_constraint("uq_raw_douyin_orders_id", type_="unique")
        batch_op.drop_column("id")
