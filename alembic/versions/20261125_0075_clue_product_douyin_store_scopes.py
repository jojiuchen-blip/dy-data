"""Persist the latest verified Douyin store scope for every product."""
from alembic import op
import sqlalchemy as sa

revision = "20261125_0075"
down_revision = "20261123_0074"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clue_product_douyin_store_scopes",
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column("product_name", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("store_ids", sa.JSON()),
        sa.Column("store_count", sa.Integer()),
    )


def downgrade():
    op.drop_table("clue_product_douyin_store_scopes")
