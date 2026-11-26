"""Track verification status evidence used by delayed follow-up credit."""
from alembic import op
import sqlalchemy as sa

revision = "20261126_0076"
down_revision = "20261125_0075"
branch_labels = None
depends_on = None

TABLE = "clue_order_status_events"
INDEX = "ix_clue_order_status_events_order_normalized"


def upgrade():
    op.create_index(INDEX, TABLE, ["order_id", "normalized_status"])
    op.execute(sa.text(
        "INSERT INTO dashboard_publication_source_counters(source_name, generation, changed_at) "
        "VALUES (:name, 0, CURRENT_TIMESTAMP) ON CONFLICT (source_name) DO NOTHING"
    ).bindparams(name=TABLE))
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE "
                   f"ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()")
    elif dialect == "sqlite":
        for event in ("INSERT", "UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER publication_{TABLE}_{event.lower()} AFTER {event} ON {TABLE} BEGIN "
                       "UPDATE dashboard_publication_source_counters SET generation=generation+1, "
                       f"changed_at=CURRENT_TIMESTAMP WHERE source_name='{TABLE}'; END")


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER dashboard_publication_change ON {TABLE}")
    elif dialect == "sqlite":
        for event in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER publication_{TABLE}_{event}")
    op.execute(sa.text("DELETE FROM dashboard_publication_source_counters WHERE source_name=:name")
               .bindparams(name=TABLE))
    op.drop_index(INDEX, table_name=TABLE)
