"""switch raw order and coupon primary keys to internal ids

Revision ID: 20260720_0024
Revises: 20260720_0023
Create Date: 2026-07-20 21:15:00
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "20260720_0024"
down_revision = "20260720_0023"
branch_labels = None
depends_on = None


SQLITE_NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}

POSTGRESQL_STAGING_INDEXES = (
    (
        "tmp_raw_douyin_orders_id_pk_0024",
        "raw_douyin_orders",
        "id",
    ),
    (
        "tmp_raw_douyin_orders_order_id_uk_0024",
        "raw_douyin_orders",
        "order_id",
    ),
    (
        "tmp_raw_douyin_order_coupons_id_pk_0024",
        "raw_douyin_order_coupons",
        "id",
    ),
    (
        "tmp_raw_douyin_order_coupons_coupon_id_uk_0024",
        "raw_douyin_order_coupons",
        "coupon_id",
    ),
)


def upgrade() -> None:
    """Promote internal IDs after validating the business-ID shadow links."""

    if op.get_bind().dialect.name == "sqlite":
        if not context.is_offline_mode():
            _assert_internal_links_are_consistent()
        _upgrade_sqlite()
        return
    _upgrade_postgresql()


def downgrade() -> None:
    """Restore the stage-one constraints without deleting internal IDs."""

    if op.get_bind().dialect.name == "sqlite":
        if not context.is_offline_mode():
            _assert_internal_links_are_consistent()
        _downgrade_sqlite()
        return
    _downgrade_postgresql()


def _assert_internal_links_are_consistent() -> None:
    checks = op.get_bind().execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM raw_douyin_orders WHERE id IS NULL) "
            "AS order_null_id_count, "
            "(SELECT count(*) FROM raw_douyin_order_coupons WHERE id IS NULL) "
            "AS coupon_null_id_count, "
            "(SELECT count(*) FROM raw_douyin_orders WHERE order_id IS NULL) "
            "AS order_null_business_id_count, "
            "(SELECT count(*) FROM raw_douyin_order_coupons WHERE coupon_id IS NULL) "
            "AS coupon_null_business_id_count, "
            "(SELECT count(*) FROM ("
            "SELECT id FROM raw_douyin_orders GROUP BY id HAVING count(*) > 1"
            ") AS duplicate_order_ids) AS duplicate_order_id_count, "
            "(SELECT count(*) FROM ("
            "SELECT id FROM raw_douyin_order_coupons GROUP BY id HAVING count(*) > 1"
            ") AS duplicate_coupon_ids) AS duplicate_coupon_id_count, "
            "(SELECT count(*) FROM ("
            "SELECT order_id FROM raw_douyin_orders GROUP BY order_id HAVING count(*) > 1"
            ") AS duplicate_order_business_ids) AS duplicate_order_business_id_count, "
            "(SELECT count(*) FROM ("
            "SELECT coupon_id FROM raw_douyin_order_coupons "
            "GROUP BY coupon_id HAVING count(*) > 1"
            ") AS duplicate_coupon_business_ids) "
            "AS duplicate_coupon_business_id_count, "
            "(SELECT count(*) FROM raw_douyin_order_coupons AS coupon "
            "LEFT JOIN raw_douyin_orders AS raw_order "
            "ON raw_order.id = coupon.raw_order_id "
            "WHERE raw_order.id IS NULL OR raw_order.order_id <> coupon.order_id) "
            "AS internal_reference_mismatch_count"
        )
    ).mappings().one()
    failures = {name: int(value) for name, value in checks.items() if int(value) > 0}
    if failures:
        details = ", ".join(f"{name}={value}" for name, value in failures.items())
        raise RuntimeError(f"raw order internal ID cutover blocked: {details}")


def _upgrade_postgresql() -> None:
    if not context.is_offline_mode():
        _assert_internal_links_are_consistent()
    _prepare_postgresql_constraint_indexes()
    _lock_postgresql_validation_tables()
    if not context.is_offline_mode():
        _assert_internal_links_are_consistent()
    _lock_postgresql_cutover_tables()

    op.drop_constraint(
        "raw_douyin_order_coupons_order_id_fkey",
        "raw_douyin_order_coupons",
        type_="foreignkey",
    )
    op.drop_constraint(
        "raw_douyin_order_coupons_pkey",
        "raw_douyin_order_coupons",
        type_="primary",
    )
    op.drop_constraint(
        "uq_raw_douyin_order_coupons_id",
        "raw_douyin_order_coupons",
        type_="unique",
    )
    op.drop_constraint(
        "raw_douyin_orders_pkey", "raw_douyin_orders", type_="primary"
    )
    op.drop_constraint(
        "uq_raw_douyin_orders_id", "raw_douyin_orders", type_="unique"
    )
    op.execute(
        "ALTER TABLE raw_douyin_orders "
        "ADD CONSTRAINT pk_raw_douyin_orders PRIMARY KEY "
        "USING INDEX tmp_raw_douyin_orders_id_pk_0024"
    )
    op.execute(
        "ALTER TABLE raw_douyin_orders "
        "ADD CONSTRAINT uk_raw_douyin_orders_order_id UNIQUE "
        "USING INDEX tmp_raw_douyin_orders_order_id_uk_0024"
    )
    op.execute(
        "ALTER TABLE raw_douyin_order_coupons "
        "ADD CONSTRAINT pk_raw_douyin_order_coupons PRIMARY KEY "
        "USING INDEX tmp_raw_douyin_order_coupons_id_pk_0024"
    )
    op.execute(
        "ALTER TABLE raw_douyin_order_coupons "
        "ADD CONSTRAINT uk_raw_douyin_order_coupons_coupon_id UNIQUE "
        "USING INDEX tmp_raw_douyin_order_coupons_coupon_id_uk_0024"
    )
    op.execute(
        "ALTER INDEX ix_raw_douyin_order_coupons_raw_order_id "
        "RENAME TO idx_raw_douyin_order_coupons_raw_order"
    )
    _synchronize_postgresql_identity_sequences()


def _downgrade_postgresql() -> None:
    if not context.is_offline_mode():
        _assert_internal_links_are_consistent()
    _prepare_postgresql_constraint_indexes()
    _lock_postgresql_validation_tables()
    if not context.is_offline_mode():
        _assert_internal_links_are_consistent()
    _lock_postgresql_cutover_tables()

    op.drop_constraint(
        "pk_raw_douyin_orders", "raw_douyin_orders", type_="primary"
    )
    op.drop_constraint(
        "uk_raw_douyin_orders_order_id", "raw_douyin_orders", type_="unique"
    )
    op.drop_constraint(
        "pk_raw_douyin_order_coupons",
        "raw_douyin_order_coupons",
        type_="primary",
    )
    op.drop_constraint(
        "uk_raw_douyin_order_coupons_coupon_id",
        "raw_douyin_order_coupons",
        type_="unique",
    )
    op.execute(
        "ALTER TABLE raw_douyin_orders "
        "ADD CONSTRAINT raw_douyin_orders_pkey PRIMARY KEY "
        "USING INDEX tmp_raw_douyin_orders_order_id_uk_0024"
    )
    op.execute(
        "ALTER TABLE raw_douyin_orders "
        "ADD CONSTRAINT uq_raw_douyin_orders_id UNIQUE "
        "USING INDEX tmp_raw_douyin_orders_id_pk_0024"
    )
    op.execute(
        "ALTER TABLE raw_douyin_order_coupons "
        "ADD CONSTRAINT raw_douyin_order_coupons_pkey PRIMARY KEY "
        "USING INDEX tmp_raw_douyin_order_coupons_coupon_id_uk_0024"
    )
    op.execute(
        "ALTER TABLE raw_douyin_order_coupons "
        "ADD CONSTRAINT uq_raw_douyin_order_coupons_id UNIQUE "
        "USING INDEX tmp_raw_douyin_order_coupons_id_pk_0024"
    )
    op.create_foreign_key(
        "raw_douyin_order_coupons_order_id_fkey",
        "raw_douyin_order_coupons",
        "raw_douyin_orders",
        ["order_id"],
        ["order_id"],
        ondelete="CASCADE",
    )
    op.execute(
        "ALTER INDEX idx_raw_douyin_order_coupons_raw_order "
        "RENAME TO ix_raw_douyin_order_coupons_raw_order_id"
    )
    _synchronize_postgresql_identity_sequences()


def _prepare_postgresql_constraint_indexes() -> None:
    """Build replacement indexes without blocking normal table writes."""

    with context.get_context().autocommit_block():
        for index_name, table_name, column_name in POSTGRESQL_STAGING_INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
            op.execute(
                f"CREATE UNIQUE INDEX CONCURRENTLY {index_name} "
                f"ON {table_name} ({column_name})"
            )


def _lock_postgresql_validation_tables() -> None:
    """Block writers while allowing readers during the final shadow-data check."""

    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '5min'")
    op.execute(
        "LOCK TABLE raw_douyin_orders, raw_douyin_order_coupons "
        "IN SHARE ROW EXCLUSIVE MODE"
    )


def _lock_postgresql_cutover_tables() -> None:
    """Upgrade to a bounded metadata lock only for the constraint exchange."""

    op.execute(
        "LOCK TABLE raw_douyin_orders, raw_douyin_order_coupons "
        "IN ACCESS EXCLUSIVE MODE"
    )


def _synchronize_postgresql_identity_sequences() -> None:
    """Move both identity sequences past any explicitly imported internal IDs."""

    for table_name in ("raw_douyin_orders", "raw_douyin_order_coupons"):
        op.execute(
            sa.text(
                "SELECT setval("
                f"pg_get_serial_sequence('{table_name}', 'id')::regclass, "
                f"COALESCE((SELECT max(id) FROM {table_name}), 0) + 1, false)"
            )
        )


def _upgrade_sqlite() -> None:
    with op.batch_alter_table(
        "raw_douyin_order_coupons",
        recreate="always",
        naming_convention=SQLITE_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_raw_douyin_order_coupons_order_id_raw_douyin_orders",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "pk_raw_douyin_order_coupons", type_="primary"
        )
        batch_op.drop_constraint(
            "uq_raw_douyin_order_coupons_id", type_="unique"
        )
        batch_op.create_primary_key("pk_raw_douyin_order_coupons", ["id"])
        batch_op.create_unique_constraint(
            "uk_raw_douyin_order_coupons_coupon_id", ["coupon_id"]
        )

    with op.batch_alter_table(
        "raw_douyin_orders",
        recreate="always",
        naming_convention=SQLITE_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint("pk_raw_douyin_orders", type_="primary")
        batch_op.drop_constraint("uq_raw_douyin_orders_id", type_="unique")
        batch_op.create_primary_key("pk_raw_douyin_orders", ["id"])
        batch_op.create_unique_constraint(
            "uk_raw_douyin_orders_order_id", ["order_id"]
        )
    op.drop_index(
        "ix_raw_douyin_order_coupons_raw_order_id",
        table_name="raw_douyin_order_coupons",
    )
    op.create_index(
        "idx_raw_douyin_order_coupons_raw_order",
        "raw_douyin_order_coupons",
        ["raw_order_id"],
    )


def _downgrade_sqlite() -> None:
    with op.batch_alter_table(
        "raw_douyin_orders",
        recreate="always",
        naming_convention=SQLITE_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint("pk_raw_douyin_orders", type_="primary")
        batch_op.drop_constraint(
            "uk_raw_douyin_orders_order_id", type_="unique"
        )
        batch_op.create_primary_key("pk_raw_douyin_orders", ["order_id"])
        batch_op.create_unique_constraint("uq_raw_douyin_orders_id", ["id"])

    with op.batch_alter_table(
        "raw_douyin_order_coupons",
        recreate="always",
        naming_convention=SQLITE_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "pk_raw_douyin_order_coupons", type_="primary"
        )
        batch_op.drop_constraint(
            "uk_raw_douyin_order_coupons_coupon_id", type_="unique"
        )
        batch_op.create_primary_key(
            "pk_raw_douyin_order_coupons", ["coupon_id"]
        )
        batch_op.create_unique_constraint(
            "uq_raw_douyin_order_coupons_id", ["id"]
        )
        batch_op.create_foreign_key(
            "fk_raw_douyin_order_coupons_order_id_raw_douyin_orders",
            "raw_douyin_orders",
            ["order_id"],
            ["order_id"],
            ondelete="CASCADE",
        )
    op.drop_index(
        "idx_raw_douyin_order_coupons_raw_order",
        table_name="raw_douyin_order_coupons",
    )
    op.create_index(
        "ix_raw_douyin_order_coupons_raw_order_id",
        "raw_douyin_order_coupons",
        ["raw_order_id"],
    )
