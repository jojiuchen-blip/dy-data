"""Store independent manual and current pointers for product routing lists."""
from alembic import op
import sqlalchemy as sa

revision = "20261123_0074"
down_revision = "20261120_0073"
branch_labels = None
depends_on = None


def upgrade():
    table = "clue_product_routing_configs"
    op.add_column(table, sa.Column("manual_list_version_id", sa.Text()))
    op.add_column(table, sa.Column("store_list_source", sa.Text(), nullable=False, server_default="manual"))
    op.add_column(table, sa.Column("store_list_sync_generation", sa.Text()))


def downgrade():
    table = "clue_product_routing_configs"
    op.drop_column(table, "store_list_sync_generation")
    op.drop_column(table, "store_list_source")
    op.drop_column(table, "manual_list_version_id")
