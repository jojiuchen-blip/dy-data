"""Keep signed-off retrospective area corrections separate from imported rosters."""
from alembic import op
import sqlalchemy as sa

revision = "20261105_0067"
down_revision = "20261027_0066"
branch_labels = None
depends_on = None
TABLE = "ranking_area_corrections"


def upgrade():
    op.create_table(TABLE,
        sa.Column("mapping_version", sa.Text(), primary_key=True),
        sa.Column("store_id", sa.Text(), primary_key=True),
        *(sa.Column(name, sa.Text(), nullable=False) for name in
          ("service_store_code", "source_hash", "old_key", "old_area", "new_key", "new_area", "reason")),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["mapping_version", "store_id"],
                                ["ranking_store_org_history.mapping_version", "ranking_store_org_history.store_id"]),
        sa.CheckConstraint("old_key <> new_key AND old_area <> new_area AND length(reason)>0"))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE FUNCTION ranking_area_no_rewrite() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'area corrections are append only'; END $$")
        op.execute(f"CREATE TRIGGER no_rewrite BEFORE UPDATE OR DELETE OR TRUNCATE ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION ranking_area_no_rewrite()")
    else:
        for operation in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER no_area_{operation.lower()} BEFORE {operation} ON {TABLE} BEGIN SELECT RAISE(ABORT,'area corrections are append only'); END")
    op.execute(f"INSERT INTO dashboard_publication_source_counters(source_name,generation,changed_at) VALUES ('{TABLE}',0,CURRENT_TIMESTAMP)")
    op.execute(f"INSERT INTO ranking_source_change_counters(source_name,generation,changed_at) VALUES ('{TABLE}',0,CURRENT_TIMESTAMP)")
    if bind.dialect.name == "postgresql":
        op.execute(f"CREATE TRIGGER trg_ranking_source_change_{TABLE}_statement AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION ranking_bump_source_change('{TABLE}')")
        op.execute(f"CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()")
    else:
        op.execute(f"CREATE TRIGGER trg_ranking_source_change_{TABLE}_insert AFTER INSERT ON {TABLE} BEGIN UPDATE ranking_source_change_counters SET generation=generation+1,changed_at=CURRENT_TIMESTAMP WHERE source_name='{TABLE}'; END")
        op.execute(f"CREATE TRIGGER track_area_insert AFTER INSERT ON {TABLE} BEGIN UPDATE dashboard_publication_source_counters SET generation=generation+1,changed_at=CURRENT_TIMESTAMP WHERE source_name='{TABLE}'; END")


def downgrade():
    if op.get_bind().execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first():
        raise RuntimeError("Preserve recorded area corrections; use a forward migration.")
    op.drop_table(TABLE)
    op.execute(f"DELETE FROM ranking_source_change_counters WHERE source_name='{TABLE}'")
    op.execute(f"DELETE FROM dashboard_publication_source_counters WHERE source_name='{TABLE}'")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION ranking_area_no_rewrite()")
