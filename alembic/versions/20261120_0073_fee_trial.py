"""Add immutable, permission-scoped monthly internal trial projections."""
from alembic import op
import sqlalchemy as sa

revision = "20261120_0073"
down_revision = "20261120_0072"
branch_labels = None
depends_on = None
SOURCE_TABLES = ("data_quality_issues", "monthly_store_evidence_snapshot")


def upgrade():
    op.create_table(
        "dashboard_publication_fee_trial",
        sa.Column("publication_id", sa.String(64), sa.ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("row_id", sa.String(64), primary_key=True),
        sa.Column("month", sa.String(7), nullable=False), sa.Column("fee_direction", sa.Integer(), nullable=False),
        sa.Column("coupon_id", sa.String(128), nullable=False), sa.Column("order_id", sa.String(128)),
        sa.Column("store_id", sa.String(128)), sa.Column("store_name", sa.String(255)),
        sa.Column("product_type", sa.String(128), nullable=False), sa.Column("sku_id", sa.String(128)),
        sa.Column("fee_amount_cent", sa.BigInteger()), sa.Column("base_amount_cent", sa.BigInteger()),
        sa.Column("fee_rate", sa.String(32)), sa.Column("rule_version", sa.String(128)),
        sa.Column("record_status", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(128)), sa.Column("reason", sa.Text()),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.CheckConstraint("fee_direction IN (1, 2)", name="ck_pub_fee_trial_direction"),
        sa.CheckConstraint("record_status IN ('CALCULATED', 'PENDING', 'EXCLUDED')", name="ck_pub_fee_trial_status"),
        sa.CheckConstraint("(record_status = 'CALCULATED' AND fee_amount_cent IS NOT NULL AND base_amount_cent IS NOT NULL) OR "
                           "(record_status <> 'CALCULATED' AND fee_amount_cent IS NULL AND base_amount_cent IS NULL)",
                           name="ck_pub_fee_trial_known_amount"),
    )
    op.create_index("ix_pub_fee_trial_filter", "dashboard_publication_fee_trial",
                    ["publication_id", "month", "fee_direction", "store_id"])
    # These existing inputs now affect settlement trial coverage. Every other
    # source is already tracked by the settlement publication contract.
    for table in SOURCE_TABLES:
        op.execute(sa.text("INSERT INTO dashboard_publication_source_counters(source_name, generation, changed_at) "
            "VALUES (:name, 0, CURRENT_TIMESTAMP) ON CONFLICT (source_name) DO NOTHING").bindparams(name=table))
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} "
                       "FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()")
        elif op.get_bind().dialect.name == "sqlite":
            for event in ("INSERT", "UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER publication_{table}_{event.lower()} AFTER {event} ON {table} BEGIN "
                    f"UPDATE dashboard_publication_source_counters SET generation=generation+1, changed_at=CURRENT_TIMESTAMP WHERE source_name='{table}'; END")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM dashboard_publication_fee_trial LIMIT 1")).first():
        raise RuntimeError("Retain published internal trial evidence; use a forward migration.")
    op.drop_table("dashboard_publication_fee_trial")
    for table in reversed(SOURCE_TABLES):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER dashboard_publication_change ON {table}")
        elif op.get_bind().dialect.name == "sqlite":
            for event in ("insert", "update", "delete"):
                op.execute(f"DROP TRIGGER publication_{table}_{event}")
        op.execute(sa.text("DELETE FROM dashboard_publication_source_counters WHERE source_name=:name").bindparams(name=table))
