"""Preserve the redemption that qualified each immutable fee result.

Revision ID: 20260909_0051
Revises: 20260903_0050
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260909_0051"
down_revision = "20260903_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable provenance; never guess or rewrite historical attribution."""
    op.add_column("settlement_fee_result", sa.Column("qualifying_verify_id", sa.Text(), nullable=True))
    op.add_column("settlement_fee_result", sa.Column("qualifying_verify_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("settlement_fee_result", sa.Column("qualifying_verify_store_id", sa.String(128), nullable=True))
    op.add_column("settlement_fee_result", sa.Column("qualifying_verify_store_name", sa.Text(), nullable=True))
    op.add_column("settlement_fee_result", sa.Column("reverification_anchor_id", sa.String(128), nullable=True))
    op.create_index("idx_settlement_fee_result_reverification_anchor", "settlement_fee_result", ["reverification_anchor_id", "result_version"])
    op.create_table(
        "settlement_billing_source_bundle",
        sa.Column("generation_id", sa.String(128), primary_key=True),
        sa.Column("store_id", sa.String(128), primary_key=True),
        sa.Column("statement_month", sa.String(7), primary_key=True),
        sa.Column("source_job_id", sa.Text(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("sources_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Allow unused rollback, never discard populated financial provenance."""
    populated = op.get_bind().execute(sa.text(
        "SELECT 1 FROM settlement_fee_result "
        "WHERE qualifying_verify_id IS NOT NULL OR qualifying_verify_time IS NOT NULL "
        "OR qualifying_verify_store_id IS NOT NULL OR qualifying_verify_store_name IS NOT NULL "
        "OR reverification_anchor_id IS NOT NULL LIMIT 1"
    )).first()
    captured = op.get_bind().execute(sa.text("SELECT 1 FROM settlement_billing_source_bundle LIMIT 1")).first()
    if populated is not None or captured is not None:
        raise RuntimeError("Fee verification provenance is populated; roll back application images without dropping audit columns.")
    op.drop_column("settlement_fee_result", "qualifying_verify_id")
    op.drop_column("settlement_fee_result", "qualifying_verify_time")
    op.drop_index("idx_settlement_fee_result_reverification_anchor", table_name="settlement_fee_result")
    op.drop_column("settlement_fee_result", "reverification_anchor_id")
    op.drop_column("settlement_fee_result", "qualifying_verify_store_name")
    op.drop_column("settlement_fee_result", "qualifying_verify_store_id")
    op.drop_table("settlement_billing_source_bundle")
