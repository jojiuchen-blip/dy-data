"""Freeze provenance and period for monthly sales-store relationships."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261120_0072"
down_revision = "20261119_0071"
branch_labels = None
depends_on = None
TABLE = "monthly_store_evidence_snapshot"


def upgrade():
    op.create_table(TABLE,
        sa.Column("version_id", sa.String(128), primary_key=True),
        sa.Column("qualification_version_id", sa.String(128),
                  sa.ForeignKey("account_qualification_version.version_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("records_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("qualification_version_id", "content_sha256", name="uq_mses_qualification_content"))
    op.create_index("ix_mses_qualification_created", TABLE, ["qualification_version_id", "created_at", "version_id"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("""CREATE FUNCTION monthly_store_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'monthly store relationship evidence is immutable'; END $$"""))
        op.execute(sa.text(f"CREATE TRIGGER monthly_store_evidence_guard BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW EXECUTE FUNCTION monthly_store_evidence_guard()"))
        op.execute(sa.text(f"CREATE TRIGGER monthly_store_evidence_no_truncate BEFORE TRUNCATE ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION monthly_store_evidence_guard()"))
    elif bind.dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(sa.text(f"CREATE TRIGGER mses_{operation.lower()} BEFORE {operation} ON {TABLE} BEGIN SELECT RAISE(ABORT,'monthly store relationship evidence is immutable'); END"))


def downgrade():
    if op.get_bind().execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first():
        raise RuntimeError("Preserve frozen store relationship evidence; use a forward migration.")
    op.drop_table(TABLE)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION monthly_store_evidence_guard()"))
