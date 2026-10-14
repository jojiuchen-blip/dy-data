"""Correct two confirmed source-name errors without rewriting ranking facts.

The audit table is migration-owned: source_hash retains the original imported
configuration identity, and the before-image explains this explicit correction.
"""

from alembic import op
import sqlalchemy as sa


revision = "20261008_0061"
down_revision = "20260916_0060"
branch_labels = None
depends_on = None

AUDIT_TABLE = "ranking_store_name_correction_0061"
CORRECTIONS = (
    ("7380305331350308915", "BYDEFJ008W", "福建龙长鸿汽车销售服务有限公司", "福建龙迪鑫汽车销售服务有限公司"),
    ("7402151814281398298", "BYDFJ062W", "福建龙迪鑫汽车销售服务有限公司", "福建龙长鸿汽车销售服务有限公司"),
)


def _lock_history() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Same lock as configuration/snapshot publication; block direct writers
        # too so the audited before-image and name update remain atomic.
        op.execute(sa.text("SELECT pg_advisory_xact_lock(7342091101)"))
        op.execute(sa.text("LOCK TABLE ranking_store_org_history IN SHARE ROW EXCLUSIVE MODE"))


def upgrade() -> None:
    _lock_history()
    op.create_table(
        AUDIT_TABLE,
        sa.Column("mapping_version", sa.Text(), primary_key=True),
        sa.Column("store_id", sa.Text(), primary_key=True),
        sa.Column("service_store_code", sa.Text(), nullable=False),
        sa.Column("old_store_name", sa.Text(), nullable=False),
        sa.Column("new_store_name", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.current_timestamp()),
    )
    for store_id, code, old_name, new_name in CORRECTIONS:
        # Match the verified identity AND the known erroneous value. Already
        # corrected rows, unrelated stores and mismatched codes remain untouched.
        op.execute(sa.text(f"""
            INSERT INTO {AUDIT_TABLE}
                (mapping_version, store_id, service_store_code, old_store_name,
                 new_store_name, source_hash, effective_from)
            SELECT mapping_version, store_id, service_store_code, store_name,
                   :new_name, source_hash, effective_from
            FROM ranking_store_org_history
            WHERE store_id = :store_id AND service_store_code = :code
              AND store_name = :old_name
        """).bindparams(store_id=store_id, code=code, old_name=old_name, new_name=new_name))
    op.execute(sa.text(f"""
        UPDATE ranking_store_org_history
        SET store_name = (
            SELECT a.new_store_name FROM {AUDIT_TABLE} a
            WHERE a.mapping_version = ranking_store_org_history.mapping_version
              AND a.store_id = ranking_store_org_history.store_id
        )
        WHERE EXISTS (
            SELECT 1 FROM {AUDIT_TABLE} a
            WHERE a.mapping_version = ranking_store_org_history.mapping_version
              AND a.store_id = ranking_store_org_history.store_id
              AND a.service_store_code = ranking_store_org_history.service_store_code
              AND a.old_store_name = ranking_store_org_history.store_name
              AND a.source_hash = ranking_store_org_history.source_hash
              AND a.effective_from = ranking_store_org_history.effective_from
        )
    """))


def downgrade() -> None:
    _lock_history()
    # Only undo rows this migration changed, while their identity, source and
    # corrected name still match. Never overwrite a later correction/import.
    op.execute(sa.text(f"""
        UPDATE ranking_store_org_history
        SET store_name = (
            SELECT a.old_store_name FROM {AUDIT_TABLE} a
            WHERE a.mapping_version = ranking_store_org_history.mapping_version
              AND a.store_id = ranking_store_org_history.store_id
        )
        WHERE EXISTS (
            SELECT 1 FROM {AUDIT_TABLE} a
            WHERE a.mapping_version = ranking_store_org_history.mapping_version
              AND a.store_id = ranking_store_org_history.store_id
              AND a.service_store_code = ranking_store_org_history.service_store_code
              AND a.new_store_name = ranking_store_org_history.store_name
              AND a.source_hash = ranking_store_org_history.source_hash
              AND a.effective_from = ranking_store_org_history.effective_from
        )
    """))
    op.drop_table(AUDIT_TABLE)
