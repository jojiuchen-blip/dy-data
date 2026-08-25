"""add G2 management correction, SAP suggestion, reversal, and carry-forward facts

Revision ID: 20260824_0041
Revises: 20260821_0040
Create Date: 2026-08-24 10:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260824_0041"
down_revision = "20260821_0040"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    if op.get_bind().dialect.name == "sqlite":
        return sa.Column("id", sa.Integer(), nullable=False, autoincrement=True)
    return sa.Column(
        "id", sa.BigInteger(), sa.Identity(), nullable=False, autoincrement=True
    )


def upgrade() -> None:
    """Append the minimum immutable G2 schema after the closed G1 head."""

    with op.batch_alter_table("store_finance_profile") as batch_op:
        batch_op.add_column(
            sa.Column("is_tombstone", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column(
                "source_type", sa.Integer(), nullable=False, server_default="1"
            )
        )
        batch_op.alter_column(
            "import_batch_id",
            existing_type=sa.String(length=128),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "ck_store_finance_profile_source", "source_type IN (1, 2, 3)"
        )

    for table_name in ("invoice_record", "promotion_invoice"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_tombstone",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    with op.batch_alter_table("finance_import_batch") as batch_op:
        batch_op.drop_constraint(
            "ck_finance_import_batch_status", type_="check"
        )
        batch_op.add_column(
            sa.Column("reverses_batch_id", sa.String(length=128), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_finance_import_batch_status",
            "batch_status IN (1, 2, 3, 4, 5, 6, 7, 8, 9)",
        )
    op.create_index(
        "idx_finance_import_batch_reverses",
        "finance_import_batch",
        ["reverses_batch_id"],
    )

    with op.batch_alter_table("finance_import_row") as batch_op:
        batch_op.add_column(
            sa.Column("reversal_effect_type", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "reverses_target_record_id", sa.String(length=128), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "previous_target_record_id", sa.String(length=128), nullable=True
            )
        )
        batch_op.create_check_constraint(
            "ck_finance_import_row_reversal_effect",
            "reversal_effect_type IS NULL OR reversal_effect_type IN (1, 2)",
        )

    op.create_table(
        "sap_suggestion",
        _id_column(),
        sa.Column("suggestion_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "supersedes_suggestion_id", sa.String(length=128), nullable=True
        ),
        sa.Column("suggested_sap_code", sa.String(length=128), nullable=False),
        sa.Column("suggestion_note", sa.String(length=1000), nullable=False),
        sa.Column("suggestion_status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("submitted_by", sa.String(length=128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handled_by", sa.String(length=128), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handling_reason", sa.String(length=1000), nullable=True),
        sa.Column("confirmed_profile_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True),
        sa.Column("request_payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sap_suggestion"),
        sa.UniqueConstraint("suggestion_id", name="uk_sap_suggestion_id"),
        sa.UniqueConstraint(
            "store_id", "version_no", name="uk_sap_suggestion_store_version"
        ),
        sa.UniqueConstraint(
            "idempotency_key_hash", name="uk_sap_suggestion_idempotency"
        ),
        sa.CheckConstraint("version_no > 0", name="ck_sap_suggestion_version"),
        sa.CheckConstraint(
            "suggestion_status IN (1, 2, 3, 4)",
            name="ck_sap_suggestion_status",
        ),
    )
    op.create_index(
        "idx_sap_suggestion_current",
        "sap_suggestion",
        ["store_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index(
        "idx_sap_suggestion_status", "sap_suggestion", ["suggestion_status"]
    )
    op.create_index(
        "idx_sap_suggestion_submitted", "sap_suggestion", ["submitted_at"]
    )

    op.create_table(
        "management_carryforward_application",
        _id_column(),
        sa.Column("application_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column("source_statement_id", sa.String(length=128), nullable=False),
        sa.Column("source_statement_month", sa.String(length=7), nullable=False),
        sa.Column("target_statement_id", sa.String(length=128), nullable=False),
        sa.Column("target_statement_month", sa.String(length=7), nullable=False),
        sa.Column("invoice_id", sa.String(length=128), nullable=True),
        sa.Column("applied_amount_cent", sa.BigInteger(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "supersedes_application_id", sa.String(length=128), nullable=True
        ),
        sa.Column("projection_sha256", sa.String(length=64), nullable=False),
        sa.Column("gmt_create", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "id", name="pk_management_carryforward_application"
        ),
        sa.UniqueConstraint(
            "application_id", name="uk_management_carryforward_application_id"
        ),
        sa.UniqueConstraint(
            "source_statement_id",
            "target_statement_id",
            "version_no",
            name="uk_management_carryforward_application_version",
        ),
        sa.CheckConstraint(
            "version_no > 0",
            name="ck_management_carryforward_application_version",
        ),
        sa.CheckConstraint(
            "applied_amount_cent > 0",
            name="ck_management_carryforward_application_amount",
        ),
    )
    op.create_index(
        "idx_management_carryforward_current",
        "management_carryforward_application",
        ["source_statement_id", "target_statement_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index(
        "idx_management_carryforward_store_month",
        "management_carryforward_application",
        ["store_id", "target_statement_month"],
    )
    op.create_index(
        "idx_management_carryforward_invoice",
        "management_carryforward_application",
        ["invoice_id"],
    )


def _assert_downgrade_safe() -> None:
    connection = op.get_bind()
    checks = {
        "SAP suggestions": "SELECT COUNT(*) FROM sap_suggestion",
        "management carry-forward applications": (
            "SELECT COUNT(*) FROM management_carryforward_application"
        ),
        "finance import reversals": (
            "SELECT COUNT(*) FROM finance_import_batch "
            "WHERE reverses_batch_id IS NOT NULL OR batch_status = 9"
        ),
        "finance import reversal rows": (
            "SELECT COUNT(*) FROM finance_import_row "
            "WHERE reversal_effect_type IS NOT NULL "
            "OR reverses_target_record_id IS NOT NULL "
            "OR previous_target_record_id IS NOT NULL"
        ),
        "page or reversal profile versions": (
            "SELECT COUNT(*) FROM store_finance_profile "
            "WHERE source_type != 1 OR import_batch_id IS NULL OR is_tombstone"
        ),
        "invoice tombstones": "SELECT COUNT(*) FROM invoice_record WHERE is_tombstone",
        "promotion tombstones": "SELECT COUNT(*) FROM promotion_invoice WHERE is_tombstone",
    }
    populated = [
        label
        for label, query in checks.items()
        if int(connection.execute(sa.text(query)).scalar_one() or 0) > 0
    ]
    if populated:
        raise RuntimeError(
            "cannot downgrade 20260824_0041 while G2 immutable facts exist: "
            + ", ".join(populated)
        )


def downgrade() -> None:
    """Remove an unused G2 schema while refusing to discard immutable facts."""

    _assert_downgrade_safe()

    op.drop_index(
        "idx_management_carryforward_invoice",
        table_name="management_carryforward_application",
    )
    op.drop_index(
        "idx_management_carryforward_store_month",
        table_name="management_carryforward_application",
    )
    op.drop_index(
        "idx_management_carryforward_current",
        table_name="management_carryforward_application",
    )
    op.drop_table("management_carryforward_application")

    op.drop_index("idx_sap_suggestion_submitted", table_name="sap_suggestion")
    op.drop_index("idx_sap_suggestion_status", table_name="sap_suggestion")
    op.drop_index("idx_sap_suggestion_current", table_name="sap_suggestion")
    op.drop_table("sap_suggestion")

    with op.batch_alter_table("finance_import_row") as batch_op:
        batch_op.drop_constraint(
            "ck_finance_import_row_reversal_effect", type_="check"
        )
        batch_op.drop_column("previous_target_record_id")
        batch_op.drop_column("reverses_target_record_id")
        batch_op.drop_column("reversal_effect_type")

    op.drop_index(
        "idx_finance_import_batch_reverses", table_name="finance_import_batch"
    )
    with op.batch_alter_table("finance_import_batch") as batch_op:
        batch_op.drop_constraint(
            "ck_finance_import_batch_status", type_="check"
        )
        batch_op.drop_column("reverses_batch_id")
        batch_op.create_check_constraint(
            "ck_finance_import_batch_status",
            "batch_status IN (1, 2, 3, 4, 5, 6, 7, 8)",
        )

    with op.batch_alter_table("store_finance_profile") as batch_op:
        batch_op.drop_constraint(
            "ck_store_finance_profile_source", type_="check"
        )
        batch_op.alter_column(
            "import_batch_id",
            existing_type=sa.String(length=128),
            nullable=False,
        )
        batch_op.drop_column("source_type")
        batch_op.drop_column("is_tombstone")

    for table_name in ("promotion_invoice", "invoice_record"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("is_tombstone")
