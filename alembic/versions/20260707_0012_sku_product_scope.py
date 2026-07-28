"""add product scope to sku product rules

Revision ID: 20260707_0012
Revises: 20260706_0011
Create Date: 2026-07-07 10:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260707_0012"
down_revision = "20260706_0011"
branch_labels = None
depends_on = None


JINGCHENG_PRODUCT_SCOPE = "精诚养车"
JINGCHENG_SKU_PRODUCT_TYPES = {
    "1834808062911500": "268保养",
    "1839843694054411": "268保养",
    "1836174558502924": "268保养",
    "1834807415534650": "168保养",
    "1836174232747016": "168保养",
    "1842945450213424": "漆面",
    "1859247916957723": "漆面",
    "1859251879725066": "漆面",
    "1838947657772048": "漆面",
    "1865042571753472": "蒸发箱清洗",
    "1865042831665155": "外循环清洗",
}


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if not _has_table("dim_sku_product_rules"):
        return

    if "product_scope" not in _column_names("dim_sku_product_rules"):
        op.add_column(
            "dim_sku_product_rules",
            sa.Column("product_scope", sa.Text(), nullable=False, server_default=""),
        )

    if "ix_dim_sku_product_rules_product_scope" not in _index_names(
        "dim_sku_product_rules"
    ):
        op.create_index(
            "ix_dim_sku_product_rules_product_scope",
            "dim_sku_product_rules",
            ["product_scope"],
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE dim_sku_product_rules
            SET product_scope = CASE
                    WHEN product_scope IS NULL OR product_scope = ''
                    THEN :product_scope
                    ELSE product_scope
                END,
                product_type = CASE
                    WHEN product_type IS NULL
                         OR product_type = ''
                         OR product_type = :product_scope
                    THEN :product_type
                    ELSE product_type
                END
            WHERE sku_id = :sku_id
            """
        ),
        [
            {
                "sku_id": sku_id,
                "product_scope": JINGCHENG_PRODUCT_SCOPE,
                "product_type": product_type,
            }
            for sku_id, product_type in JINGCHENG_SKU_PRODUCT_TYPES.items()
        ],
    )


def downgrade() -> None:
    if not _has_table("dim_sku_product_rules"):
        return

    if "ix_dim_sku_product_rules_product_scope" in _index_names(
        "dim_sku_product_rules"
    ):
        op.drop_index(
            "ix_dim_sku_product_rules_product_scope",
            table_name="dim_sku_product_rules",
        )

    if "product_scope" in _column_names("dim_sku_product_rules"):
        op.drop_column("dim_sku_product_rules", "product_scope")
