"""Freeze shared task denominators and first self-store verification dates."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0070"
down_revision = "20261118_0069"
branch_labels = None
depends_on = None

SOURCE_TABLES = ("raw_douyin_refund_records", "douyin_refund_event")
TASK_COLUMNS = ("follow_24h_numerator", "follow_any_numerator", "follow_denominator",
                "verification_numerator", "verification_denominator")
RANKING_COLUMNS = ("task_follow_24h_numerator", "task_follow_any_numerator", "task_verification_numerator",
                   "follow_denominator", "verification_denominator")
VERIFICATION_TABLE = "dashboard_publication_self_store_verifications"
CONTRACTS = {"clue-overview": "clue-task-v3", "douyin-ranking": "clue-task-v1"}


def frozen_metadata_0070():
    """Keep this revision independent of later application metadata changes."""
    metadata = sa.MetaData()
    sa.Table("dashboard_publication_runs", metadata, sa.Column("id", sa.String(64), primary_key=True))
    sa.Table(
        VERIFICATION_TABLE, metadata,
        sa.Column("publication_id", sa.String(64), sa.ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("order_id", sa.Text(), primary_key=True), sa.Column("store_id", sa.Text(), primary_key=True),
        sa.Column("verify_id", sa.Text(), nullable=False), sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False), sa.Column("product_type", sa.Text()),
        sa.Column("is_jingcheng", sa.Boolean(), nullable=False),
        sa.Column("store_name", sa.Text()), sa.Column("province", sa.Text()), sa.Column("city", sa.Text()),
        sa.Index("ix_pub_self_verify_store_date", "publication_id", "store_id", "business_date"),
        sa.Index("ix_pub_self_verify_date_product", "publication_id", "business_date", "is_jingcheng"),
    )
    return metadata


def upgrade():
    for table, columns in (("dashboard_publication_clue_rounds", TASK_COLUMNS),
                           ("dashboard_ranking_rounds", RANKING_COLUMNS)):
        for name in columns:
            op.add_column(table, sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
    op.add_column("dashboard_ranking_rounds", sa.Column("task_under_observation", sa.Boolean(),
        nullable=False, server_default=sa.false()))
    frozen_metadata_0070().tables[VERIFICATION_TABLE].create(op.get_bind())
    dialect = op.get_bind().dialect.name
    for table in SOURCE_TABLES:
        op.execute(sa.text(
            "INSERT INTO dashboard_publication_source_counters(source_name, generation, changed_at) "
            "VALUES (:name, 0, CURRENT_TIMESTAMP) ON CONFLICT (source_name) DO NOTHING").bindparams(name=table))
        if dialect == "postgresql":
            op.execute(f"CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON "
                       f"{table} FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()")
        elif dialect == "sqlite":
            for event in ("INSERT", "UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER publication_{table}_{event.lower()} AFTER {event} ON {table} BEGIN "
                           "UPDATE dashboard_publication_source_counters SET generation=generation+1, "
                           f"changed_at=CURRENT_TIMESTAMP WHERE source_name='{table}'; END")
    # Existing counters, runs and active heads remain untouched. New code
    # rejects prior contracts until the worker publishes complete new facts.


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text(f"SELECT 1 FROM {VERIFICATION_TABLE} LIMIT 1")).first():
        raise RuntimeError("Preserve published task/verification facts; use a forward migration.")
    publication_runs = sa.table("dashboard_publication_runs", sa.column("module"), sa.column("stats_json", sa.JSON()))
    for row in bind.execute(sa.select(publication_runs).where(publication_runs.c.module.in_(CONTRACTS))).mappings():
        if (row["stats_json"] or {}).get("task_metrics_contract") == CONTRACTS[row["module"]]:
            raise RuntimeError("Preserve published task/verification facts; use a forward migration.")
    op.drop_table(VERIFICATION_TABLE)
    op.drop_column("dashboard_ranking_rounds", "task_under_observation")
    for table, columns in (("dashboard_publication_clue_rounds", TASK_COLUMNS),
                           ("dashboard_ranking_rounds", RANKING_COLUMNS)):
        for name in reversed(columns):
            op.drop_column(table, name)
    for table in SOURCE_TABLES:
        if bind.dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER dashboard_publication_change ON {table}")
        elif bind.dialect.name == "sqlite":
            for event in ("insert", "update", "delete"):
                op.execute(f"DROP TRIGGER publication_{table}_{event}")
        op.execute(sa.text("DELETE FROM dashboard_publication_source_counters WHERE source_name=:name").bindparams(name=table))
