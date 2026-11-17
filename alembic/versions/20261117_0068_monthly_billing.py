"""Persist monthly close evidence, first bill availability and balances."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261117_0068"
down_revision = "20261105_0067"
branch_labels = None
depends_on = None
SOURCE_TABLES = ("settlement_month_close", "settlement_statement_balance", "settlement_statement_visibility")


def upgrade():
    op.add_column("settlement_statement", sa.Column("monthly_close_input_sha256", sa.String(64)))
    op.create_table(
        "settlement_month_close",
        sa.Column("business_month", sa.String(7), primary_key=True),
        sa.Column("source_input_sha256", sa.String(64), nullable=False),
        sa.Column("source_job_id", sa.String(128), nullable=False),
        sa.Column("qualification_version_id", sa.String(128), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("blocked_store_ids", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("unscoped_issue_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("unscoped_issue_count >= 0", name="ck_month_close_unscoped_issues"),
    )
    statement_key = "settlement_statement.statement_id"
    op.create_table(
        "settlement_statement_visibility",
        sa.Column("statement_id", sa.String(128), sa.ForeignKey(statement_key, ondelete="CASCADE"), primary_key=True),
        sa.Column("publication_id", sa.String(64), nullable=False),
        sa.Column("first_visible_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "settlement_statement_balance",
        sa.Column("statement_id", sa.String(128), sa.ForeignKey(statement_key), primary_key=True),
        sa.Column("fee_direction", sa.Integer(), primary_key=True),
        sa.Column("previous_statement_id", sa.String(128), sa.ForeignKey(statement_key)),
        sa.Column("opening_balance_cent", sa.BigInteger(), nullable=False),
        sa.Column("period_net_fee_cent", sa.BigInteger(), nullable=False),
        sa.Column("net_due_cent", sa.BigInteger(), nullable=False),
        sa.Column("closing_balance_cent", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("fee_direction IN (1, 2)", name="ck_statement_balance_direction"),
        sa.CheckConstraint("opening_balance_cent <= 0", name="ck_statement_balance_opening"),
        sa.CheckConstraint("net_due_cent = opening_balance_cent + period_net_fee_cent", name="ck_statement_balance_net"),
        sa.CheckConstraint("closing_balance_cent = CASE WHEN net_due_cent < 0 THEN net_due_cent ELSE 0 END",
                           name="ck_statement_balance_closing"),
    )
    dialect = op.get_bind().dialect.name
    for table in SOURCE_TABLES:
        op.execute(sa.text(
            "INSERT INTO dashboard_publication_source_counters(source_name, generation, changed_at) "
            "VALUES (:name, 0, CURRENT_TIMESTAMP)").bindparams(name=table))
        if dialect == "postgresql":
            op.execute(f"CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON "
                       f"{table} FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()")
        elif dialect == "sqlite":
            for event in ("INSERT", "UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER publication_{table}_{event.lower()} AFTER {event} ON {table} BEGIN "
                           "UPDATE dashboard_publication_source_counters SET generation=generation+1, "
                           f"changed_at=CURRENT_TIMESTAMP WHERE source_name='{table}'; END")


def downgrade():
    bind = op.get_bind()
    for table in ("settlement_statement_balance", "settlement_statement_visibility", "settlement_month_close"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Preserve observed billing history; use a forward migration.")
    for table in ("settlement_statement_balance", "settlement_statement_visibility", "settlement_month_close"):
        op.drop_table(table)
    for table in SOURCE_TABLES:
        op.execute(sa.text("DELETE FROM dashboard_publication_source_counters WHERE source_name=:name")
                   .bindparams(name=table))
    op.drop_column("settlement_statement", "monthly_close_input_sha256")
