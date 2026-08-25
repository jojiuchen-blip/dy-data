"""freeze immutable store and SAP snapshots on settlement statements

Revision ID: 20260824_0043
Revises: 20260824_0042
Create Date: 2026-08-24 18:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260824_0043"
down_revision = "20260824_0042"
branch_labels = None
depends_on = None


SNAPSHOT_STATUSES = "'LIVE_CAPTURED', 'BACKFILLED_PROFILE', 'UNRESOLVED'"
EXCEPTION_REASONS = (
    "'NO_PRIOR_BASIC_PROFILE', "
    "'PROFILE_NOT_COMMITTED_BEFORE_STATEMENT', "
    "'AMBIGUOUS_PROFILE_TIME', 'INVALID_PROFILE_VERSION_ORDER'"
)
ENTRY_EXCEPTION_REASONS = "'MISSING_REQUIRED_ENTRY_SNAPSHOT'"


def upgrade() -> None:
    """Add statement snapshots and deterministically backfill historical facts."""
    with op.batch_alter_table("settlement_statement") as batch_op:
        batch_op.add_column(
            sa.Column("store_name_snapshot", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("sap_code_snapshot", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "store_snapshot_status",
                sa.String(length=32),
                nullable=False,
                server_default="UNRESOLVED",
            )
        )
        batch_op.add_column(
            sa.Column(
                "store_snapshot_profile_id", sa.String(length=128), nullable=True
            )
        )
        batch_op.create_check_constraint(
            "ck_settlement_statement_snapshot_status",
            f"store_snapshot_status IN ({SNAPSHOT_STATUSES})",
        )

    with op.batch_alter_table("settlement_statement_entry") as batch_op:
        batch_op.add_column(sa.Column("order_status_snapshot", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("coupon_status_snapshot", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("product_name_snapshot", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("sku_id_snapshot", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("sku_name_snapshot", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("sale_channel_snapshot", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("sale_store_id_snapshot", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("sale_store_snapshot", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("verify_store_id_snapshot", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("verify_store_snapshot", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("sale_time_snapshot", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("verify_time_snapshot", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("received_amount_cent_snapshot", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("fee_rate_snapshot", sa.Numeric(8, 6), nullable=True))
        batch_op.add_column(sa.Column("refund_at_snapshot", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("adjustment_type_snapshot", sa.Integer(), nullable=True))

    op.create_table(
        "settlement_statement_snapshot_migration_exception",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(length=1000), nullable=True),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gmt_modified", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "statement_id",
            name="uk_settlement_statement_snapshot_exception_statement",
        ),
        sa.CheckConstraint(
            f"reason_code IN ({EXCEPTION_REASONS})",
            name="ck_settlement_statement_snapshot_exception_reason",
        ),
    )
    op.create_index(
        "idx_settlement_statement_snapshot_exception_unresolved",
        "settlement_statement_snapshot_migration_exception",
        ["resolved_at", "reason_code"],
    )
    op.create_table(
        "settlement_statement_entry_snapshot_migration_exception",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("statement_entry_id", sa.String(length=128), nullable=False),
        sa.Column("statement_id", sa.String(length=128), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(length=1000), nullable=True),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gmt_modified", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "statement_entry_id",
            name="uk_statement_entry_snapshot_exception_entry",
        ),
        sa.CheckConstraint(
            f"reason_code IN ({ENTRY_EXCEPTION_REASONS})",
            name="ck_statement_entry_snapshot_exception_reason",
        ),
    )
    op.create_index(
        "idx_statement_entry_snapshot_exception_unresolved",
        "settlement_statement_entry_snapshot_migration_exception",
        ["resolved_at", "reason_code"],
    )

    _backfill_historical_snapshots()
    _backfill_historical_entry_snapshots()


def downgrade() -> None:
    """Remove snapshot evidence while preserving pre-existing statement facts."""
    bind = op.get_bind()
    snapshot_fact_count = bind.execute(
        sa.text(
            """
            SELECT
                (SELECT COUNT(*) FROM settlement_statement) +
                (SELECT COUNT(*) FROM settlement_statement_entry) +
                (SELECT COUNT(*) FROM settlement_statement_snapshot_migration_exception) +
                (SELECT COUNT(*) FROM settlement_statement_entry_snapshot_migration_exception)
            """
        )
    ).scalar_one()
    if snapshot_fact_count:
        raise RuntimeError(
            "cannot downgrade 20260824_0043: statement snapshot or exception facts exist"
        )

    op.drop_index(
        "idx_statement_entry_snapshot_exception_unresolved",
        table_name="settlement_statement_entry_snapshot_migration_exception",
    )
    op.drop_table("settlement_statement_entry_snapshot_migration_exception")
    op.drop_index(
        "idx_settlement_statement_snapshot_exception_unresolved",
        table_name="settlement_statement_snapshot_migration_exception",
    )
    op.drop_table("settlement_statement_snapshot_migration_exception")
    with op.batch_alter_table("settlement_statement_entry") as batch_op:
        batch_op.drop_column("adjustment_type_snapshot")
        batch_op.drop_column("refund_at_snapshot")
        batch_op.drop_column("fee_rate_snapshot")
        batch_op.drop_column("received_amount_cent_snapshot")
        batch_op.drop_column("verify_time_snapshot")
        batch_op.drop_column("sale_time_snapshot")
        batch_op.drop_column("verify_store_snapshot")
        batch_op.drop_column("verify_store_id_snapshot")
        batch_op.drop_column("sale_store_snapshot")
        batch_op.drop_column("sale_store_id_snapshot")
        batch_op.drop_column("sale_channel_snapshot")
        batch_op.drop_column("sku_name_snapshot")
        batch_op.drop_column("sku_id_snapshot")
        batch_op.drop_column("product_name_snapshot")
        batch_op.drop_column("coupon_status_snapshot")
        batch_op.drop_column("order_status_snapshot")
    with op.batch_alter_table("settlement_statement") as batch_op:
        batch_op.drop_constraint(
            "ck_settlement_statement_snapshot_status", type_="check"
        )
        batch_op.drop_column("store_snapshot_profile_id")
        batch_op.drop_column("store_snapshot_status")
        batch_op.drop_column("sap_code_snapshot")
        batch_op.drop_column("store_name_snapshot")


def _backfill_historical_snapshots() -> None:
    """Backfill only profiles that provably existed before statement creation."""
    op.execute(
        sa.text(
            """
            WITH invalid_profile_order AS (
                SELECT DISTINCT statement.statement_id
                FROM settlement_statement AS statement
                JOIN store_finance_profile AS earlier
                  ON earlier.store_id = statement.store_id
                 AND earlier.profile_type = 1
                 AND earlier.gmt_create < statement.gmt_create
                JOIN store_finance_profile AS later
                  ON later.store_id = earlier.store_id
                 AND later.profile_type = earlier.profile_type
                 AND later.gmt_create < statement.gmt_create
                 AND later.version_no > earlier.version_no
                 AND later.gmt_create < earlier.gmt_create
                WHERE statement.statement_month >= '2026-08'
            ), ranked_profile AS (
                SELECT
                    statement.statement_id,
                    profile.profile_id,
                    profile.store_name_snapshot,
                    profile.sap_code,
                    ROW_NUMBER() OVER (
                        PARTITION BY statement.statement_id
                        ORDER BY
                            profile.version_no DESC,
                            profile.gmt_create DESC,
                            profile.profile_id DESC
                    ) AS candidate_rank
                FROM settlement_statement AS statement
                JOIN store_finance_profile AS profile
                  ON profile.store_id = statement.store_id
                 AND profile.profile_type = 1
                 AND profile.gmt_create < statement.gmt_create
                WHERE statement.statement_month >= '2026-08'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM invalid_profile_order AS invalid
                      WHERE invalid.statement_id = statement.statement_id
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM finance_import_batch AS batch
                      WHERE batch.batch_id = profile.import_batch_id
                        AND batch.batch_status IN (5, 8, 9)
                        AND COALESCE(batch.committed_at, batch.submitted_at)
                            < statement.gmt_create
                  )
            )
            UPDATE settlement_statement
            SET
                store_name_snapshot = (
                    SELECT ranked.store_name_snapshot
                    FROM ranked_profile AS ranked
                    WHERE ranked.statement_id = settlement_statement.statement_id
                      AND ranked.candidate_rank = 1
                ),
                sap_code_snapshot = (
                    SELECT ranked.sap_code
                    FROM ranked_profile AS ranked
                    WHERE ranked.statement_id = settlement_statement.statement_id
                      AND ranked.candidate_rank = 1
                ),
                store_snapshot_profile_id = (
                    SELECT ranked.profile_id
                    FROM ranked_profile AS ranked
                    WHERE ranked.statement_id = settlement_statement.statement_id
                      AND ranked.candidate_rank = 1
                ),
                store_snapshot_status = 'BACKFILLED_PROFILE'
            WHERE statement_id IN (
                SELECT statement_id
                FROM ranked_profile
                WHERE candidate_rank = 1
            )
            """
        )
    )


def _backfill_historical_entry_snapshots() -> None:
    """Freeze exact-ID historical entry facts so runtime never reads mutable masters."""
    op.execute(
        sa.text(
            """
            UPDATE settlement_statement_entry AS entry
            SET
                order_status_snapshot = (
                    SELECT COALESCE(raw_order.order_status_normalized, raw_order.order_status)
                    FROM raw_douyin_orders AS raw_order
                    WHERE raw_order.order_id = entry.order_id
                    LIMIT 1
                ),
                coupon_status_snapshot = (
                    SELECT COALESCE(coupon.coupon_status_normalized, coupon.coupon_status)
                    FROM raw_douyin_order_coupons AS coupon
                    WHERE coupon.coupon_id = entry.coupon_id
                    LIMIT 1
                ),
                product_name_snapshot = (
                    SELECT raw_order.product_name
                    FROM raw_douyin_orders AS raw_order
                    WHERE raw_order.order_id = entry.order_id
                    LIMIT 1
                ),
                sku_id_snapshot = (
                    SELECT fee.sku_id
                    FROM settlement_fee_result AS fee
                    WHERE fee.fee_result_id = entry.original_fee_result_id
                    LIMIT 1
                ),
                sku_name_snapshot = (
                    SELECT sku.sku_name
                    FROM dim_sku_product_rules AS sku
                    WHERE sku.sku_id = (
                        SELECT fee.sku_id
                        FROM settlement_fee_result AS fee
                        WHERE fee.fee_result_id = entry.original_fee_result_id
                        LIMIT 1
                    )
                    LIMIT 1
                ),
                sale_channel_snapshot = (
                    SELECT fee.sale_channel_normalized
                    FROM settlement_fee_result AS fee
                    WHERE fee.fee_result_id = entry.original_fee_result_id
                    LIMIT 1
                ),
                sale_store_id_snapshot = (
                    SELECT fee.sale_store_id
                    FROM settlement_fee_result AS fee
                    WHERE fee.fee_result_id = entry.original_fee_result_id
                    LIMIT 1
                ),
                sale_store_snapshot = (
                    SELECT store.store_name
                    FROM dim_stores AS store
                    WHERE store.store_id = (
                        SELECT fee.sale_store_id
                        FROM settlement_fee_result AS fee
                        WHERE fee.fee_result_id = entry.original_fee_result_id
                        LIMIT 1
                    )
                    LIMIT 1
                ),
                verify_store_id_snapshot = (
                    SELECT fee.verify_store_id
                    FROM settlement_fee_result AS fee
                    WHERE fee.fee_result_id = entry.original_fee_result_id
                    LIMIT 1
                ),
                verify_store_snapshot = (
                    SELECT store.store_name
                    FROM dim_stores AS store
                    WHERE store.store_id = (
                        SELECT fee.verify_store_id
                        FROM settlement_fee_result AS fee
                        WHERE fee.fee_result_id = entry.original_fee_result_id
                        LIMIT 1
                    )
                    LIMIT 1
                ),
                sale_time_snapshot = (
                    SELECT raw_order.sale_time
                    FROM raw_douyin_orders AS raw_order
                    WHERE raw_order.order_id = entry.order_id
                    LIMIT 1
                ),
                verify_time_snapshot = (
                    SELECT verify.verify_time
                    FROM raw_douyin_verify_records AS verify
                    WHERE verify.coupon_id = entry.coupon_id
                      AND verify.cancel_time IS NULL
                      AND LOWER(COALESCE(verify.verify_status, '')) IN
                          ('1', 'valid', 'verified', 'success', 'fulfilled', 'used')
                    ORDER BY verify.verify_time DESC, verify.verify_id DESC
                    LIMIT 1
                ),
                received_amount_cent_snapshot = (
                    SELECT fee.source_amount_cent
                    FROM settlement_fee_result AS fee
                    WHERE fee.fee_result_id = entry.original_fee_result_id
                    LIMIT 1
                ),
                fee_rate_snapshot = (
                    SELECT fee.fee_rate
                    FROM settlement_fee_result AS fee
                    WHERE fee.fee_result_id = entry.original_fee_result_id
                    LIMIT 1
                ),
                refund_at_snapshot = CASE
                    WHEN entry.source_type = 2 THEN (
                        SELECT adjustment.occurred_at
                        FROM settlement_fee_adjustment AS adjustment
                        WHERE adjustment.adjustment_id = entry.source_record_id
                        LIMIT 1
                    )
                    ELSE (
                        SELECT coupon.coupon_refund_time
                        FROM raw_douyin_order_coupons AS coupon
                        WHERE coupon.coupon_id = entry.coupon_id
                        LIMIT 1
                    )
                END,
                adjustment_type_snapshot = CASE
                    WHEN entry.source_type = 2 THEN (
                        SELECT adjustment.adjustment_type
                        FROM settlement_fee_adjustment AS adjustment
                        WHERE adjustment.adjustment_id = entry.source_record_id
                        LIMIT 1
                    )
                    ELSE NULL
                END
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO settlement_statement_entry_snapshot_migration_exception (
                statement_entry_id,
                statement_id,
                reason_code,
                evidence_json,
                detected_at,
                resolved_at,
                resolution_note,
                gmt_create,
                gmt_modified
            )
            SELECT
                entry.statement_entry_id,
                entry.statement_id,
                'MISSING_REQUIRED_ENTRY_SNAPSHOT',
                '{"migration":"20260824_0043"}',
                CURRENT_TIMESTAMP,
                NULL,
                NULL,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM settlement_statement_entry AS entry
            WHERE entry.order_status_snapshot IS NULL
               OR entry.coupon_status_snapshot IS NULL
               OR entry.product_name_snapshot IS NULL
               OR entry.sku_id_snapshot IS NULL
               OR entry.sku_name_snapshot IS NULL
               OR entry.sale_channel_snapshot IS NULL
               OR entry.sale_store_id_snapshot IS NULL
               OR entry.sale_store_snapshot IS NULL
               OR entry.verify_store_id_snapshot IS NULL
               OR entry.verify_store_snapshot IS NULL
               OR entry.sale_time_snapshot IS NULL
               OR entry.verify_time_snapshot IS NULL
               OR entry.received_amount_cent_snapshot IS NULL
               OR entry.fee_rate_snapshot IS NULL
               OR (
                    entry.source_type = 2
                    AND (
                        entry.refund_at_snapshot IS NULL
                        OR entry.adjustment_type_snapshot IS NULL
                    )
               )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO settlement_statement_snapshot_migration_exception (
                statement_id,
                reason_code,
                evidence_json,
                detected_at,
                resolved_at,
                resolution_note,
                gmt_create,
                gmt_modified
            )
            SELECT
                statement.statement_id,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM store_finance_profile AS earlier
                        JOIN store_finance_profile AS later
                          ON later.store_id = earlier.store_id
                         AND later.profile_type = earlier.profile_type
                         AND later.version_no > earlier.version_no
                        WHERE earlier.store_id = statement.store_id
                          AND earlier.profile_type = 1
                          AND earlier.gmt_create > later.gmt_create
                          AND earlier.gmt_create < statement.gmt_create
                          AND later.gmt_create < statement.gmt_create
                    ) THEN 'INVALID_PROFILE_VERSION_ORDER'
                    WHEN EXISTS (
                        SELECT 1
                        FROM store_finance_profile AS profile
                        WHERE profile.store_id = statement.store_id
                          AND profile.profile_type = 1
                          AND profile.gmt_create = statement.gmt_create
                    ) THEN 'AMBIGUOUS_PROFILE_TIME'
                    WHEN EXISTS (
                        SELECT 1
                        FROM store_finance_profile AS profile
                        WHERE profile.store_id = statement.store_id
                          AND profile.profile_type = 1
                          AND profile.gmt_create < statement.gmt_create
                    ) THEN 'PROFILE_NOT_COMMITTED_BEFORE_STATEMENT'
                    ELSE 'NO_PRIOR_BASIC_PROFILE'
                END,
                '{"migration":"20260824_0043"}',
                CURRENT_TIMESTAMP,
                NULL,
                NULL,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM settlement_statement AS statement
            WHERE statement.statement_month >= '2026-08'
              AND statement.store_snapshot_status = 'UNRESOLVED'
            """
        )
    )
