"""Persist the exact frozen sales-name attribution used by monthly fees."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261118_0069"
down_revision = "20261117_0068"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("settlement_fee_result", sa.Column(
        "sale_account_match_json", sa.JSON(none_as_null=True).with_variant(
            postgresql.JSONB(none_as_null=True), "postgresql"
        ),
        nullable=True,
    ))


def downgrade():
    evidence = op.get_bind().execute(sa.text(
        "SELECT 1 FROM settlement_fee_result WHERE sale_account_match_json IS NOT NULL "
        "AND CAST(sale_account_match_json AS TEXT) <> 'null' LIMIT 1"
    )).first()
    if evidence:
        raise RuntimeError("Preserve frozen sales attribution evidence; use a forward migration.")
    op.drop_column("settlement_fee_result", "sale_account_match_json")
