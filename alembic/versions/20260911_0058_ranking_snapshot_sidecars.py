"""Add isolated ranking policy history, evidence and snapshots.

Revision ID: 20260911_0058
Revises: 20260911_0057

Only exercised on disposable local databases at this stage.
"""
from alembic import op
from apps.api.dy_api.ranking_schema_v1 import metadata

revision = "20260911_0058"
down_revision = "20260911_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in metadata.sorted_tables:
        table.create(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    for table in reversed(metadata.sorted_tables):
        table.drop(op.get_bind(), checkfirst=False)
