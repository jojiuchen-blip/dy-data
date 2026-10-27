"""Preserve month-end account qualification evidence; no historical backfill.

Revision ID: 20261027_0066
Revises: 20261023_0065
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261027_0066"
down_revision = "20261023_0065"
branch_labels = None
depends_on = None

SNAPSHOT = "account_qualification_snapshot"
OBSERVATION = "account_qualification_observation"
VERSION = "account_qualification_version"
FK = "fk_fee_account_qualification_version"


def upgrade():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(SNAPSHOT,
        sa.Column("content_sha256", sa.String(64), primary_key=True),
        sa.Column("records_json", json_type, nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False))
    op.create_table(OBSERVATION,
        sa.Column("observation_id", sa.String(128), primary_key=True),
        sa.Column("source_run_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("content_sha256", sa.String(64), sa.ForeignKey(SNAPSHOT + ".content_sha256", ondelete="RESTRICT")),
        sa.Column("proof_json", json_type, nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.CheckConstraint("state IN ('running', 'success', 'failed')", name="ck_aqo_state"))
    op.create_index("ix_aqo_started", OBSERVATION, ["started_at", "observation_id"])
    op.create_index("ix_account_qualification_observation_source_run_id", OBSERVATION, ["source_run_id"])
    op.create_table(VERSION,
        sa.Column("version_id", sa.String(128), primary_key=True),
        sa.Column("business_month", sa.String(7), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_id", sa.String(128), sa.ForeignKey(OBSERVATION + ".observation_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_sha256", sa.String(64), sa.ForeignKey(SNAPSHOT + ".content_sha256", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_month", name="uq_aqv_month"))
    bind = op.get_bind()
    triggers = []
    if bind.dialect.name == "sqlite":
        triggers = bind.execute(sa.text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='settlement_fee_result' AND sql IS NOT NULL")).all()
    with op.batch_alter_table("settlement_fee_result") as batch:
        batch.add_column(sa.Column("account_qualification_version_id", sa.String(128), nullable=True))
        batch.create_foreign_key(FK, VERSION, ["account_qualification_version_id"], ["version_id"], ondelete="RESTRICT")
    if bind.dialect.name == "sqlite":
        for name, sql in triggers:
            if not bind.execute(sa.text("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=:name"), {"name": name}).first():
                op.execute(sa.text(sql))
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("""
            CREATE FUNCTION account_qualification_guard() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_TABLE_NAME = 'account_qualification_observation' AND TG_OP = 'UPDATE' THEN
                IF OLD.state = 'running' AND NEW.state IN ('success','failed')
                  AND NEW.observation_id = OLD.observation_id
                  AND NEW.source_run_id = OLD.source_run_id AND NEW.started_at = OLD.started_at
                  AND NEW.ended_at >= OLD.started_at
                  AND ((NEW.state = 'success' AND NEW.complete AND NEW.content_sha256 IS NOT NULL)
                    OR (NEW.state = 'failed' AND NOT NEW.complete AND NEW.content_sha256 IS NULL)) THEN
                  RETURN NEW;
                END IF;
              END IF;
              RAISE EXCEPTION 'account qualification evidence is immutable';
            END $$
        """))
        for table in (SNAPSHOT, OBSERVATION, VERSION):
            op.execute(sa.text(f"CREATE TRIGGER account_qualification_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION account_qualification_guard()"))
            op.execute(sa.text(f"CREATE TRIGGER account_qualification_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION account_qualification_guard()"))
    elif bind.dialect.name == "sqlite":
        for table in (SNAPSHOT, OBSERVATION, VERSION):
            for operation in ("UPDATE", "DELETE"):
                condition = ""
                if table == OBSERVATION and operation == "UPDATE":
                    condition = ("WHEN NOT (OLD.state='running' AND NEW.state IN ('success','failed') "
                                 "AND NEW.observation_id=OLD.observation_id AND NEW.source_run_id=OLD.source_run_id "
                                 "AND NEW.started_at=OLD.started_at AND NEW.ended_at>=OLD.started_at "
                                 "AND ((NEW.state='success' AND NEW.complete=1 AND NEW.content_sha256 IS NOT NULL) "
                                 "OR (NEW.state='failed' AND NEW.complete=0 AND NEW.content_sha256 IS NULL)))")
                op.execute(sa.text(f"CREATE TRIGGER aq_{table}_{operation.lower()} BEFORE {operation} ON {table} {condition} BEGIN SELECT RAISE(ABORT,'account qualification evidence is immutable'); END"))
    if sa.inspect(bind).has_table("dashboard_publication_source_counters"):
        bind.execute(sa.text(
            "INSERT INTO dashboard_publication_source_counters(source_name,generation,changed_at) "
            "VALUES (:source,0,CURRENT_TIMESTAMP) ON CONFLICT(source_name) DO NOTHING"
        ), {"source": VERSION})
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(f"CREATE TRIGGER dashboard_publication_change AFTER INSERT ON {VERSION} FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()"))
        elif bind.dialect.name == "sqlite":
            op.execute(sa.text(
                f"CREATE TRIGGER dashboard_publication_{VERSION}_insert AFTER INSERT ON {VERSION} BEGIN "
                "SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM dashboard_publication_source_counters "
                f"WHERE source_name='{VERSION}') THEN RAISE(ABORT,'dashboard publication source counter missing') END; "
                "UPDATE dashboard_publication_source_counters SET generation=generation+1,changed_at=CURRENT_TIMESTAMP "
                f"WHERE source_name='{VERSION}'; END"
            ))


def downgrade():
    bind = op.get_bind()
    if any(bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() for table in (VERSION, OBSERVATION, SNAPSHOT)):
        raise RuntimeError("Populated account qualification evidence must be preserved; use a forward repair.")
    if bind.execute(sa.text("SELECT 1 FROM settlement_fee_result WHERE account_qualification_version_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Populated account qualification provenance must be preserved.")
    triggers = []
    if bind.dialect.name == "sqlite":
        triggers = bind.execute(sa.text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='settlement_fee_result' AND sql IS NOT NULL")).all()
    with op.batch_alter_table("settlement_fee_result") as batch:
        batch.drop_constraint(FK, type_="foreignkey")
        batch.drop_column("account_qualification_version_id")
    if bind.dialect.name == "sqlite":
        for name, sql in triggers:
            if not bind.execute(sa.text("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=:name"), {"name": name}).first():
                op.execute(sa.text(sql))
    for table in (VERSION, OBSERVATION, SNAPSHOT):
        op.drop_table(table)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION account_qualification_guard()"))
    if sa.inspect(bind).has_table("dashboard_publication_source_counters"):
        bind.execute(sa.text("DELETE FROM dashboard_publication_source_counters WHERE source_name=:source"), {"source": VERSION})
