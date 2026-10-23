"""Append exact historical attribution decisions without changing bindings.

Revision ID: 20261023_0065
Revises: 20261022_0064
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261023_0065"
down_revision = "20261022_0064"
branch_labels = None
depends_on = None

TABLE = "historical_sale_attribution_decisions"
FK = "fk_fee_result_historical_sale_attribution"


def _sqlite_fee_triggers(bind):
    if bind.dialect.name != "sqlite":
        return []
    return list(bind.execute(sa.text(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
        "AND tbl_name='settlement_fee_result' AND sql IS NOT NULL"
    )).all())


def _restore_sqlite_fee_triggers(bind, triggers):
    # Alembic batch table recreation discards SQLite triggers. Preserve the
    # installed source counters and any earlier fee protections verbatim.
    for name, sql in triggers:
        if bind.execute(sa.text("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=:name"), {"name": name}).first() is None:
            op.execute(sa.text(sql))


def upgrade() -> None:
    """Add empty evidence storage and its narrowly scoped source tracking."""
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        TABLE,
        sa.Column("decision_id", sa.String(128), primary_key=True),
        sa.Column("batch_id", sa.String(128), nullable=False),
        sa.Column("raw_order_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), sa.ForeignKey("raw_douyin_orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("raw_coupon_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), sa.ForeignKey("raw_douyin_order_coupons.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("coupon_id", sa.Text(), nullable=False),
        sa.Column("verify_id", sa.Text(), sa.ForeignKey("raw_douyin_verify_records.verify_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("verify_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("business_month", sa.String(7), nullable=False),
        sa.Column("source_account_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), sa.ForeignKey("dim_stores.store_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_identity_sha256", sa.String(64), nullable=False),
        sa.Column("source_identity_json", json_type, nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("approval_evidence_json", json_type, nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("coupon_id", name="uq_historical_sale_attribution_coupon"),
        sa.CheckConstraint("length(source_identity_sha256) = 64 AND length(evidence_sha256) = 64", name="ck_historical_sale_attribution_digests"),
    )
    op.create_index("ix_historical_sale_attribution_month", TABLE, ["business_month", "decision_id"])
    op.create_index("ix_historical_sale_attribution_batch", TABLE, ["batch_id"])
    bind = op.get_bind()
    fee_triggers = _sqlite_fee_triggers(bind)
    with op.batch_alter_table("settlement_fee_result") as batch:
        batch.add_column(sa.Column("sale_attribution_decision_id", sa.String(128), nullable=True))
        batch.create_foreign_key(FK, TABLE, ["sale_attribution_decision_id"], ["decision_id"], ondelete="RESTRICT")
    op.create_index("ix_fee_result_sale_attribution_decision", "settlement_fee_result", ["sale_attribution_decision_id"])
    _restore_sqlite_fee_triggers(bind, fee_triggers)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(
            "CREATE FUNCTION historical_sale_attribution_immutable() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'historical attribution decisions are immutable'; END $$"
        ))
        op.execute(sa.text(
            f"CREATE TRIGGER historical_sale_attribution_immutable BEFORE UPDATE OR DELETE OR TRUNCATE "
            f"ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION historical_sale_attribution_immutable()"
        ))
        # Existing 0063 function and counter table are the authoritative tracker.
        if sa.inspect(bind).has_table("dashboard_publication_source_counters"):
            op.execute(sa.text(
                f"INSERT INTO dashboard_publication_source_counters(source_name,generation,changed_at) "
                f"VALUES ('{TABLE}',0,clock_timestamp()) ON CONFLICT(source_name) DO NOTHING"
            ))
            op.execute(sa.text(
                f"CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE "
                f"ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()"
            ))
    elif bind.dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(sa.text(
                f"CREATE TRIGGER historical_sale_attribution_no_{operation.lower()} BEFORE {operation} "
                f"ON {TABLE} BEGIN SELECT RAISE(ABORT, 'historical attribution decisions are immutable'); END"
            ))
        if sa.inspect(bind).has_table("dashboard_publication_source_counters"):
            bind.execute(sa.text(
                "INSERT INTO dashboard_publication_source_counters(source_name,generation,changed_at) "
                "VALUES (:source,0,CURRENT_TIMESTAMP) ON CONFLICT(source_name) DO NOTHING"
            ), {"source": TABLE})
            op.execute(sa.text(
                f"CREATE TRIGGER dashboard_publication_{TABLE}_insert AFTER INSERT ON {TABLE} BEGIN "
                "SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM dashboard_publication_source_counters "
                f"WHERE source_name = '{TABLE}') THEN RAISE(ABORT, 'dashboard publication source counter missing') END; "
                "UPDATE dashboard_publication_source_counters SET generation = generation + 1, "
                f"changed_at=CURRENT_TIMESTAMP WHERE source_name = '{TABLE}'; END"
            ))


def downgrade() -> None:
    """Never discard populated attribution or financial provenance."""
    bind = op.get_bind()
    if bind.execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first() is not None:
        raise RuntimeError("Historical attribution evidence is populated; preserve it and use a forward repair.")
    if bind.execute(sa.text("SELECT 1 FROM settlement_fee_result WHERE sale_attribution_decision_id IS NOT NULL LIMIT 1")).first() is not None:
        raise RuntimeError("Historical attribution result provenance is populated.")
    op.drop_index("ix_fee_result_sale_attribution_decision", table_name="settlement_fee_result")
    fee_triggers = _sqlite_fee_triggers(bind)
    with op.batch_alter_table("settlement_fee_result") as batch:
        batch.drop_constraint(FK, type_="foreignkey")
        batch.drop_column("sale_attribution_decision_id")
    _restore_sqlite_fee_triggers(bind, fee_triggers)
    op.drop_table(TABLE)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION historical_sale_attribution_immutable()"))
    if sa.inspect(bind).has_table("dashboard_publication_source_counters"):
        bind.execute(sa.text("DELETE FROM dashboard_publication_source_counters WHERE source_name = :source"), {"source": TABLE})
