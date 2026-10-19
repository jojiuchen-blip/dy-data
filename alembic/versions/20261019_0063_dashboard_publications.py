"""Freeze unified dashboard sidecars and source tracking at revision 0063.

This historical revision deliberately imports no runtime schema or dependency
configuration. Only analytical sidecars are created; no business facts are copied.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261019_0063"
down_revision = "20261009_0062"
branch_labels = None
depends_on = None

SOURCE_TABLES_0063 = (
    'agg_store_monthly_settlement',
    'agg_store_ranking',
    'clue_assignment_rounds',
    'clue_center_orders',
    'clue_follow_up_records',
    'clue_master_leads',
    'dim_aweme_accounts',
    'dim_sku_product_rules',
    'dim_store_org_assignments',
    'dim_store_poi_mappings',
    'dim_stores',
    'finance_import_batch',
    'finance_operation_audit',
    'invoice_record',
    'invoice_status_event',
    'management_carryforward_application',
    'promotion_invoice',
    'promotion_invoice_allocation',
    'ranking_lead_org_bindings',
    'ranking_store_eligibility',
    'ranking_store_org_history',
    'raw_aweme_bindings',
    'raw_douyin_clues',
    'raw_douyin_order_coupons',
    'raw_douyin_orders',
    'raw_douyin_verify_records',
    'sap_suggestion',
    'settlement_fee_adjustment',
    'settlement_fee_result',
    'settlement_fee_result_current',
    'settlement_monthly_overlay',
    'settlement_order_details',
    'settlement_projection_active',
    'settlement_projection_compaction_closure',
    'settlement_projection_generation',
    'settlement_projection_partition_manifest',
    'settlement_ranking_overlay',
    'settlement_statement',
    'settlement_statement_confirmation',
    'settlement_statement_entry',
    'settlement_statement_line',
    'store_finance_profile',
)


def frozen_metadata_0063() -> sa.MetaData:
    """The exact 0063 table, constraint and index definitions."""
    metadata = sa.MetaData()
    table_dashboard_publication_runs = sa.Table(
        'dashboard_publication_runs', metadata,
        sa.Column('id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('module', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('cutoff', sa.DateTime(timezone=True), nullable=False),
        sa.Column('data_as_of', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_refresh_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('stats_json', sa.JSON(), nullable=False),
        sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pin_reason', sa.Text(), nullable=True),
        sa.Column('pinned_by', sa.String(length=128), nullable=True),
        sa.CheckConstraint("(status = 'success' AND published_at IS NOT NULL) OR (status <> 'success' AND published_at IS NULL)", name='ck_dashboard_publication_published'),
        sa.CheckConstraint("status IN ('building', 'success', 'failed')", name='ck_dashboard_publication_status'),
        sa.UniqueConstraint('module', 'id', name='uq_dashboard_publication_module_id'),
    )
    sa.Index('ix_dashboard_publication_module_created', table_dashboard_publication_runs.c['module'], table_dashboard_publication_runs.c['created_at'], table_dashboard_publication_runs.c['id'], unique=False)
    sa.Index('ix_dashboard_publication_module_published', table_dashboard_publication_runs.c['module'], table_dashboard_publication_runs.c['status'], table_dashboard_publication_runs.c['published_at'], unique=False)
    table_dashboard_publication_source_counters = sa.Table(
        'dashboard_publication_source_counters', metadata,
        sa.Column('source_name', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('generation', sa.BigInteger(), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    )
    table_dashboard_ranking_lead_bindings = sa.Table(
        'dashboard_ranking_lead_bindings', metadata,
        sa.Column('lead_key', sa.Text(), primary_key=True, nullable=False),
        sa.Column('first_assigned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('mapping_version', sa.Text(), nullable=False),
    )
    table_dashboard_publication_clue_organizations = sa.Table(
        'dashboard_publication_clue_organizations', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('store_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('store_name', sa.Text(), nullable=True),
        sa.Column('group_name', sa.Text(), nullable=True),
        sa.Column('service_center_name', sa.Text(), nullable=True),
        sa.Column('district_name', sa.Text(), nullable=True),
        sa.Column('area_name', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_pub_clue_org_path', table_dashboard_publication_clue_organizations.c['publication_id'], table_dashboard_publication_clue_organizations.c['service_center_name'], table_dashboard_publication_clue_organizations.c['district_name'], table_dashboard_publication_clue_organizations.c['area_name'], unique=False)
    table_dashboard_publication_clue_rounds = sa.Table(
        'dashboard_publication_clue_rounds', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('assignment_round_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('order_id', sa.Text(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('assigned_store_id', sa.Text(), nullable=True),
        sa.Column('assigned_store_name', sa.Text(), nullable=True),
        sa.Column('order_assigned_store_name', sa.Text(), nullable=True),
        sa.Column('assigned_province', sa.Text(), nullable=True),
        sa.Column('assigned_city', sa.Text(), nullable=True),
        sa.Column('product_type', sa.Text(), nullable=True),
        sa.Column('is_jingcheng', sa.Boolean(), nullable=False),
        sa.Column('is_headquarters', sa.Boolean(), nullable=False),
        sa.Column('lead_status', sa.Text(), nullable=True),
        sa.Column('round_status', sa.Text(), nullable=True),
        sa.Column('store_display_status', sa.Text(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_self_store_verified', sa.Boolean(), nullable=True),
        sa.Column('active_clue', sa.Integer(), nullable=False),
        sa.Column('followed_clue', sa.Integer(), nullable=False),
        sa.Column('successful_follow_clue', sa.Integer(), nullable=False),
        sa.Column('self_store_verified_clue', sa.Integer(), nullable=False),
        sa.Column('pending_reassign_clue', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_pub_clues_date_product', table_dashboard_publication_clue_rounds.c['publication_id'], table_dashboard_publication_clue_rounds.c['assigned_at'], table_dashboard_publication_clue_rounds.c['product_type'], unique=False)
    sa.Index('ix_pub_clues_order', table_dashboard_publication_clue_rounds.c['publication_id'], table_dashboard_publication_clue_rounds.c['order_id'], unique=False)
    sa.Index('ix_pub_clues_store_date', table_dashboard_publication_clue_rounds.c['publication_id'], table_dashboard_publication_clue_rounds.c['assigned_store_id'], table_dashboard_publication_clue_rounds.c['assigned_at'], table_dashboard_publication_clue_rounds.c['order_id'], unique=False)
    table_dashboard_publication_finance_dimensions = sa.Table(
        'dashboard_publication_finance_dimensions', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('kind', sa.String(length=32), primary_key=True, nullable=False),
        sa.Column('key', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    table_dashboard_publication_finance_invoices = sa.Table(
        'dashboard_publication_finance_invoices', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('position', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('fee_direction', sa.String(length=16), nullable=False),
        sa.Column('store_id', sa.String(length=128), nullable=False),
        sa.Column('month', sa.String(length=7), nullable=False),
        sa.Column('statement_id', sa.String(length=128), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('confirmed', sa.Boolean(), nullable=False),
        sa.Column('is_history', sa.Boolean(), nullable=False),
        sa.Column('is_projection', sa.Boolean(), nullable=False),
        sa.Column('search_text', sa.Text(), nullable=False),
        sa.Column('amount_cent', sa.BigInteger(), nullable=False),
        sa.Column('item', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_pub_finance_invoice_filter', table_dashboard_publication_finance_invoices.c['publication_id'], table_dashboard_publication_finance_invoices.c['fee_direction'], table_dashboard_publication_finance_invoices.c['month'], table_dashboard_publication_finance_invoices.c['store_id'], unique=False)
    table_dashboard_publication_finance_pending = sa.Table(
        'dashboard_publication_finance_pending', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('position', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('fee_direction', sa.String(length=16), nullable=False),
        sa.Column('store_id', sa.String(length=128), nullable=False),
        sa.Column('as_of_month', sa.String(length=7), nullable=False),
        sa.Column('month', sa.String(length=7), nullable=True),
        sa.Column('amount_cent', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_pub_finance_pending_filter', table_dashboard_publication_finance_pending.c['publication_id'], table_dashboard_publication_finance_pending.c['fee_direction'], table_dashboard_publication_finance_pending.c['as_of_month'], table_dashboard_publication_finance_pending.c['month'], unique=False)
    table_dashboard_publication_finance_pending_members = sa.Table(
        'dashboard_publication_finance_pending_members', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('position', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('statement_id', sa.String(length=128), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    table_dashboard_publication_finance_statements = sa.Table(
        'dashboard_publication_finance_statements', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('statement_id', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('fee_direction', sa.String(length=16), primary_key=True, nullable=False),
        sa.Column('store_id', sa.String(length=128), nullable=False),
        sa.Column('month', sa.String(length=7), nullable=False),
        sa.Column('amount_cent', sa.BigInteger(), nullable=False),
        sa.Column('confirmed_cent', sa.BigInteger(), nullable=False),
        sa.Column('issued_cent', sa.BigInteger(), nullable=False),
        sa.Column('settled_cent', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_pub_finance_statement_filter', table_dashboard_publication_finance_statements.c['publication_id'], table_dashboard_publication_finance_statements.c['fee_direction'], table_dashboard_publication_finance_statements.c['month'], table_dashboard_publication_finance_statements.c['store_id'], unique=False)
    table_dashboard_publication_heads = sa.Table(
        'dashboard_publication_heads', metadata,
        sa.Column('module', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('publication_id', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['module', 'publication_id'], ['dashboard_publication_runs.module', 'dashboard_publication_runs.id'], name='fk_dashboard_publication_head', ondelete='RESTRICT'),
    )
    table_dashboard_publication_sales_coupons = sa.Table(
        'dashboard_publication_sales_coupons', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('coupon_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('order_id', sa.Text(), nullable=False),
        sa.Column('product_type', sa.Text(), nullable=False),
        sa.Column('sale_store_id', sa.Text(), nullable=True),
        sa.Column('sale_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sale_month', sa.String(length=7), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False),
        sa.Column('verify_store_id', sa.Text(), nullable=True),
        sa.Column('verify_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verify_month', sa.String(length=7), nullable=True),
        sa.Column('paid_amount_cent', sa.Integer(), nullable=False),
        sa.Column('cycle_days', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_pub_sales_product', table_dashboard_publication_sales_coupons.c['publication_id'], table_dashboard_publication_sales_coupons.c['product_type'], unique=False)
    sa.Index('ix_pub_sales_sale', table_dashboard_publication_sales_coupons.c['publication_id'], table_dashboard_publication_sales_coupons.c['sale_store_id'], table_dashboard_publication_sales_coupons.c['sale_month'], table_dashboard_publication_sales_coupons.c['product_type'], unique=False)
    sa.Index('ix_pub_sales_verify', table_dashboard_publication_sales_coupons.c['publication_id'], table_dashboard_publication_sales_coupons.c['verify_store_id'], table_dashboard_publication_sales_coupons.c['verify_month'], table_dashboard_publication_sales_coupons.c['product_type'], unique=False)
    table_dashboard_publication_sales_product_scopes = sa.Table(
        'dashboard_publication_sales_product_scopes', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('product_scope', sa.Text(), primary_key=True, nullable=False),
        sa.Column('product_type', sa.Text(), primary_key=True, nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    table_dashboard_publication_sales_stores = sa.Table(
        'dashboard_publication_sales_stores', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('store_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('store_name', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    table_dashboard_publication_settlement_monthly = sa.Table(
        'dashboard_publication_settlement_monthly', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('month', sa.String(length=7), primary_key=True, nullable=False),
        sa.Column('store_id', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('product_scope', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('product_type', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('sales_order_count', sa.BigInteger(), nullable=False),
        sa.Column('sales_amount_cent', sa.BigInteger(), nullable=False),
        sa.Column('verified_order_count', sa.BigInteger(), nullable=False),
        sa.Column('verified_amount_cent', sa.BigInteger(), nullable=False),
        sa.Column('promotion_base_cent', sa.BigInteger(), nullable=False),
        sa.Column('promotion_original_fee_cent', sa.BigInteger(), nullable=False),
        sa.Column('promotion_adjustment_fee_cent', sa.BigInteger(), nullable=False),
        sa.Column('promotion_net_fee_cent', sa.BigInteger(), nullable=False),
        sa.Column('management_base_cent', sa.BigInteger(), nullable=False),
        sa.Column('management_original_fee_cent', sa.BigInteger(), nullable=False),
        sa.Column('management_adjustment_fee_cent', sa.BigInteger(), nullable=False),
        sa.Column('management_net_fee_cent', sa.BigInteger(), nullable=False),
        sa.Column('net_settlement_reference_cent', sa.BigInteger(), nullable=False),
        sa.Column('statement', sa.JSON(), nullable=True),
        sa.Column('lines', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    table_dashboard_publication_settlement_ranking = sa.Table(
        'dashboard_publication_settlement_ranking', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('period_type', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('period_key', sa.String(length=7), primary_key=True, nullable=False),
        sa.Column('store_id', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('product_scope', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('product_type', sa.String(length=128), primary_key=True, nullable=False),
        sa.Column('store_name', sa.String(length=255), nullable=False),
        sa.Column('sales_order_count', sa.BigInteger(), nullable=False),
        sa.Column('sales_amount_cent', sa.BigInteger(), nullable=False),
        sa.Column('verified_order_count', sa.BigInteger(), nullable=False),
        sa.Column('verified_amount_cent', sa.BigInteger(), nullable=False),
        sa.Column('promotion_net_fee_cent', sa.BigInteger(), nullable=False),
        sa.Column('management_net_fee_cent', sa.BigInteger(), nullable=False),
        sa.Column('net_settlement_reference_cent', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    table_dashboard_ranking_eligibility = sa.Table(
        'dashboard_ranking_eligibility', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('eligibility_version', sa.Text(), primary_key=True, nullable=False),
        sa.Column('service_store_code', sa.Text(), primary_key=True, nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_dashboard_ranking_eligibility_date', table_dashboard_ranking_eligibility.c['publication_id'], table_dashboard_ranking_eligibility.c['effective_from'], unique=False)
    table_dashboard_ranking_info = sa.Table(
        'dashboard_ranking_info', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('cutoff', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    table_dashboard_ranking_orders = sa.Table(
        'dashboard_ranking_orders', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('order_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('store_id', sa.Text(), nullable=True),
        sa.Column('is_jingcheng', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('historical_unverified', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_dashboard_ranking_orders_date', table_dashboard_ranking_orders.c['publication_id'], table_dashboard_ranking_orders.c['occurred_at'], table_dashboard_ranking_orders.c['store_id'], unique=False)
    table_dashboard_ranking_organizations = sa.Table(
        'dashboard_ranking_organizations', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('mapping_version', sa.Text(), primary_key=True, nullable=False),
        sa.Column('store_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('service_store_code', sa.Text(), nullable=False),
        sa.Column('store_name', sa.Text(), nullable=False),
        sa.Column('group_key', sa.Text(), nullable=True),
        sa.Column('group_name', sa.Text(), nullable=True),
        sa.Column('service_center_key', sa.Text(), nullable=True),
        sa.Column('service_center_name', sa.Text(), nullable=True),
        sa.Column('district_key', sa.Text(), nullable=True),
        sa.Column('district_name', sa.Text(), nullable=True),
        sa.Column('area_key', sa.Text(), nullable=True),
        sa.Column('area_name', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_dashboard_ranking_org_date', table_dashboard_ranking_organizations.c['publication_id'], table_dashboard_ranking_organizations.c['effective_from'], unique=False)
    table_dashboard_ranking_rounds = sa.Table(
        'dashboard_ranking_rounds', metadata,
        sa.Column('publication_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('round_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('order_id', sa.Text(), nullable=False),
        sa.Column('lead_key', sa.Text(), nullable=False),
        sa.Column('store_id', sa.Text(), nullable=True),
        sa.Column('mapping_version', sa.Text(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_jingcheng', sa.Boolean(), nullable=False),
        sa.Column('follow_24h', sa.Integer(), nullable=False),
        sa.Column('follow_any', sa.Integer(), nullable=False),
        sa.Column('self_verified', sa.Integer(), nullable=False),
        sa.Column('under_observation', sa.Boolean(), nullable=False),
        sa.Column('first_assignment_changed', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['dashboard_publication_runs.id'], ondelete='CASCADE'),
    )
    sa.Index('ix_dashboard_ranking_rounds_date', table_dashboard_ranking_rounds.c['publication_id'], table_dashboard_ranking_rounds.c['assigned_at'], table_dashboard_ranking_rounds.c['store_id'], unique=False)
    sa.Index('ix_dashboard_ranking_rounds_responsibility', table_dashboard_ranking_rounds.c['publication_id'], table_dashboard_ranking_rounds.c['order_id'], table_dashboard_ranking_rounds.c['store_id'], table_dashboard_ranking_rounds.c['assigned_at'], unique=False)
    return metadata


def _create_tracking(bind) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(
            "CREATE FUNCTION dashboard_publication_track_change() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN UPDATE dashboard_publication_source_counters "
            "SET generation = generation + 1, changed_at = clock_timestamp() "
            "WHERE source_name = TG_TABLE_NAME; "
            "IF NOT FOUND THEN RAISE EXCEPTION 'dashboard publication source counter missing'; END IF; "
            "RETURN NULL; END $$"
        ))
    for name in SOURCE_TABLES_0063:
        bind.execute(sa.text(
            "INSERT INTO dashboard_publication_source_counters (source_name,generation,changed_at) "
            "VALUES (:name,0,CURRENT_TIMESTAMP)"
        ), {"name": name})
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(
                f'CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE '
                f'ON "{name}" FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()'
            ))
        elif bind.dialect.name == "sqlite":
            for event_name in ("insert", "update", "delete"):
                op.execute(sa.text(
                    f'CREATE TRIGGER dashboard_publication_{name}_{event_name} '
                    f'AFTER {event_name.upper()} ON "{name}" BEGIN '
                    'SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM dashboard_publication_source_counters '
                    f"WHERE source_name = '{name}') THEN RAISE(ABORT, 'dashboard publication source counter missing') END; "
                    'UPDATE dashboard_publication_source_counters SET generation = generation + 1, '
                    f"changed_at = CURRENT_TIMESTAMP WHERE source_name = '{name}'; END"
                ))


def upgrade() -> None:
    bind = op.get_bind()
    # This is a schema contract, not a best-effort list. A misspelled or absent
    # source must stop BEFORE sidecar creation rather than silently omit tracking.
    existing = set(sa.inspect(bind).get_table_names())
    missing = set(SOURCE_TABLES_0063) - existing
    if missing:
        raise RuntimeError("dashboard publication source schema is incomplete: " + ",".join(sorted(missing)))
    frozen_metadata_0063().create_all(bind, checkfirst=False)
    _create_tracking(bind)


def downgrade() -> None:
    bind = op.get_bind()
    metadata = frozen_metadata_0063()
    # Published/pinned snapshots and permanent first-attribution bindings are
    # business evidence. Never erase them as an automatic schema rollback.
    for table in metadata.sorted_tables:
        if table.name == "dashboard_publication_source_counters":
            continue
        if bind.execute(sa.select(sa.literal(1)).select_from(table).limit(1)).first():
            raise RuntimeError("dashboard publication sidecars contain data; archive or use a forward repair")
    for name in SOURCE_TABLES_0063:
        if bind.dialect.name == "postgresql":
            op.execute(sa.text(f'DROP TRIGGER dashboard_publication_change ON "{name}"'))
        elif bind.dialect.name == "sqlite":
            for event_name in ("insert", "update", "delete"):
                op.execute(sa.text(f'DROP TRIGGER dashboard_publication_{name}_{event_name}'))
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION dashboard_publication_track_change()"))
    metadata.drop_all(bind, checkfirst=False)
