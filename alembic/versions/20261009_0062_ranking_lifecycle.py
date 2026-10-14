"""Add ranking source change tracking and snapshot lifecycle metadata.

The existing ranking facts remain immutable. This migration adds only
sidecars and source-change triggers used to decide when a new fact batch is
needed and which old batches can be removed.

The dependency list is intentionally frozen in this historical migration.
The runtime module may add a dependency in a future revision, but changing
that module must not silently change what an already-applied migration means.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261009_0062"
down_revision = "20261008_0061"
branch_labels = None
depends_on = None


# Keep this list in sync with the source contract at the time migration 0062
# is released. It must not import the mutable runtime tuple.
SOURCE_TABLES_0062 = (
    "raw_douyin_orders",
    "raw_douyin_order_coupons",
    "raw_douyin_verify_records",
    "raw_douyin_refund_records",
    "douyin_refund_event",
    "raw_douyin_clues",
    "raw_aweme_bindings",
    "dim_aweme_accounts",
    "dim_store_poi_mappings",
    "dim_sku_product_rules",
    "dim_stores",
    "dim_store_org_assignments",
    "settlement_order_details",
    "clue_center_orders",
    "clue_assignment_rounds",
    "clue_follow_up_records",
    "ranking_store_org_history",
    "ranking_store_eligibility",
)


def _sqlite_trigger_name(table_name: str, event: str) -> str:
    return f"trg_ranking_source_change_{table_name}_{event}"


def _postgres_trigger_name(table_name: str) -> str:
    return f"trg_ranking_source_change_{table_name}_statement"


def _existing_source_tables() -> list[str]:
    inspector = sa.inspect(op.get_bind())
    return [name for name in SOURCE_TABLES_0062 if inspector.has_table(name)]


def _create_postgres_tracking(table_names: list[str]) -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION ranking_bump_source_change()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                UPDATE ranking_source_change_counters
                SET generation = generation + 1,
                    changed_at = CURRENT_TIMESTAMP
                WHERE source_name = TG_ARGV[0];
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'ranking source change counter is missing for %', TG_ARGV[0];
                END IF;
                RETURN NULL;
            END;
            $$
            """
        )
    )
    for table_name in table_names:
        quoted = '"' + table_name.replace('"', '""') + '"'
        source_literal = "'" + table_name.replace("'", "''") + "'"
        trigger = _postgres_trigger_name(table_name)
        op.execute(
            sa.text(
                f"CREATE TRIGGER {trigger} "
                f"AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {quoted} "
                "FOR EACH STATEMENT "
                f"EXECUTE FUNCTION ranking_bump_source_change({source_literal})"
            )
        )


def _create_sqlite_tracking(table_names: list[str]) -> None:
    for table_name in table_names:
        quoted = '"' + table_name.replace('"', '""') + '"'
        source_literal = "'" + table_name.replace("'", "''") + "'"
        for event in ("insert", "update", "delete"):
            trigger = _sqlite_trigger_name(table_name, event)
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {trigger} AFTER {event.upper()} ON {quoted} BEGIN "
                    "UPDATE ranking_source_change_counters "
                    "SET generation = generation + 1, changed_at = CURRENT_TIMESTAMP "
                    f"WHERE source_name = {source_literal}; END"
                )
            )


def upgrade() -> None:
    op.create_table(
        "ranking_snapshot_lifecycle",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric_version", sa.Text(), nullable=False),
        sa.Column("data_mode", sa.Text(), nullable=False),
        sa.Column("source_fingerprint", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pin_reason", sa.Text(), nullable=True),
        sa.Column("pinned_by", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.CheckConstraint("period_end > period_start", name="ck_ranking_lifecycle_period"),
        sa.CheckConstraint(
            "data_mode IN ('business', 'synthetic')",
            name="ck_ranking_lifecycle_data_mode",
        ),
    )
    op.create_index(
        "ix_ranking_lifecycle_key_created",
        "ranking_snapshot_lifecycle",
        ["period_start", "period_end", "metric_version", "data_mode", "created_at"],
    )
    op.create_index(
        "ix_ranking_lifecycle_accessed",
        "ranking_snapshot_lifecycle",
        ["last_accessed_at", "pinned_at"],
    )
    # The first rollout must not classify historical business checkpoints as
    # disposable cache. Protect existing successful runs for explicit review;
    # newly calculated runs use the ordinary retention policy.
    if sa.inspect(op.get_bind()).has_table("ranking_snapshot_runs"):
        op.execute(sa.text("""
            INSERT INTO ranking_snapshot_lifecycle
                (run_id, period_start, period_end, metric_version, data_mode,
                 created_at, last_accessed_at, pinned_at, pin_reason, pinned_by)
            SELECT run_id, period_start, period_end, metric_version, data_mode,
                   created_at, created_at, CURRENT_TIMESTAMP,
                   'Historical snapshot before lifecycle rollout; review before unarchiving',
                   'migration:20261009_0062'
            FROM ranking_snapshot_runs
            WHERE status = 'success' AND data_mode IN ('business', 'synthetic')
        """))
    op.create_table(
        "ranking_source_change_counters",
        sa.Column("source_name", sa.Text(), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    table_names = _existing_source_tables()
    for table_name in table_names:
        op.execute(
            sa.text(
                "INSERT INTO ranking_source_change_counters(source_name, generation) "
                "VALUES (:source_name, 0)"
            ).bindparams(source_name=table_name)
        )
    if op.get_bind().dialect.name == "postgresql":
        _create_postgres_tracking(table_names)
    elif op.get_bind().dialect.name == "sqlite":
        _create_sqlite_tracking(table_names)


def downgrade() -> None:
    bind = op.get_bind()
    table_names = _existing_source_tables()
    for table_name in table_names:
        if bind.dialect.name == "postgresql":
            quoted = '"' + table_name.replace('"', '""') + '"'
            op.execute(
                sa.text(
                    f"DROP TRIGGER IF EXISTS {_postgres_trigger_name(table_name)} "
                    f"ON {quoted}"
                )
            )
        else:
            for event in ("insert", "update", "delete"):
                op.execute(sa.text(f"DROP TRIGGER IF EXISTS {_sqlite_trigger_name(table_name, event)}"))
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION IF EXISTS ranking_bump_source_change()"))
    op.drop_index("ix_ranking_lifecycle_accessed", table_name="ranking_snapshot_lifecycle")
    op.drop_index("ix_ranking_lifecycle_key_created", table_name="ranking_snapshot_lifecycle")
    op.drop_table("ranking_source_change_counters")
    op.drop_table("ranking_snapshot_lifecycle")
