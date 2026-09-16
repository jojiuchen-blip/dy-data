"""Add an isolated KPI window start for historical clue corrections."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_0060"
down_revision = "20260915_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clue_assignment_rounds",
        sa.Column("metric_follow_24h_start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_clue_assignment_rounds_metric_follow_24h_start_at",
        "clue_assignment_rounds",
        ["metric_follow_24h_start_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_clue_assignment_rounds_metric_follow_24h_start_at",
        table_name="clue_assignment_rounds",
    )
    op.drop_column("clue_assignment_rounds", "metric_follow_24h_start_at")
