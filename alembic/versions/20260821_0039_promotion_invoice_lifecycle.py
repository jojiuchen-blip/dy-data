"""add promotion invoice physical lifecycle and replacement facts

Revision ID: 20260821_0039
Revises: 20260821_0038
Create Date: 2026-08-21 17:30:00
"""

from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260821_0039"
down_revision = "20260821_0038"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        sa.Identity(),
        autoincrement=True,
        nullable=False,
    )


def upgrade() -> None:
    op.add_column(
        "promotion_invoice",
        sa.Column("physical_invoice_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "promotion_invoice",
        sa.Column("version_kind", sa.Integer(), nullable=True),
    )
    op.add_column(
        "promotion_invoice",
        sa.Column("replaces_invoice_id", sa.String(length=128), nullable=True),
    )
    op.create_table(
        "promotion_invoice_number_registry",
        _id_column(),
        sa.Column("invoice_number", sa.String(length=20), nullable=False),
        sa.Column("physical_invoice_id", sa.String(length=128), nullable=False),
        sa.Column("first_invoice_id", sa.String(length=128), nullable=False),
        sa.Column("store_id", sa.String(length=128), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_promotion_invoice_number_registry"),
        sa.UniqueConstraint(
            "invoice_number", name="uk_promotion_invoice_number_registry_number"
        ),
        sa.UniqueConstraint(
            "physical_invoice_id",
            name="uk_promotion_invoice_number_registry_physical",
        ),
    )
    op.create_table(
        "promotion_invoice_lifecycle_migration_exception",
        _id_column(),
        sa.Column("invoice_id", sa.String(length=128), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "id", name="pk_promotion_invoice_lifecycle_migration_exception"
        ),
        sa.UniqueConstraint(
            "invoice_id", name="uk_promotion_invoice_lifecycle_migration_exception"
        ),
    )

    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT invoice_id, store_id, invoice_number, version_no, "
                "registered_at, supersedes_invoice_id, is_current FROM promotion_invoice "
                "ORDER BY invoice_number, store_id, version_no, invoice_id"
            )
        ).mappings()
    )
    stores_by_number: dict[str, set[str]] = {}
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        stores_by_number.setdefault(row["invoice_number"], set()).add(row["store_id"])
        groups.setdefault((row["store_id"], row["invoice_number"]), []).append(row)
    valid_chain_by_group: dict[tuple[str, str], bool] = {}
    for (store_id, invoice_number), group in groups.items():
        rows_by_id = {row["invoice_id"]: row for row in group}
        roots = [
            row for row in group
            if row["supersedes_invoice_id"] is None
        ]
        children: dict[str, list[dict]] = {}
        for row in group:
            parent_id = row["supersedes_invoice_id"]
            if parent_id in rows_by_id:
                children.setdefault(parent_id, []).append(row)
        current_rows = [row for row in group if row["is_current"]]
        valid_chain = (
            len(roots) == 1
            and roots[0]["version_no"] == 1
            and len(current_rows) == 1
            and all(
            len(child_rows) <= 1 for child_rows in children.values()
            )
        )
        ordered_chain: list[dict] = []
        if valid_chain:
            cursor = roots[0]
            seen: set[str] = set()
            while cursor["invoice_id"] not in seen:
                seen.add(cursor["invoice_id"])
                ordered_chain.append(cursor)
                next_rows = children.get(cursor["invoice_id"], [])
                if not next_rows:
                    break
                next_row = next_rows[0]
                if next_row["version_no"] != cursor["version_no"] + 1:
                    valid_chain = False
                    break
                cursor = next_row
            valid_chain = (
                valid_chain
                and len(ordered_chain) == len(group)
                and ordered_chain[-1]["invoice_id"] == current_rows[0]["invoice_id"]
            )
        valid_chain_by_group[(store_id, invoice_number)] = valid_chain
        digest = hashlib.sha256(f"{store_id}|{invoice_number}".encode("utf-8")).hexdigest()
        physical_id = f"physical-invoice-{digest[:40]}"
        rows_to_update = ordered_chain if valid_chain else group
        for index, row in enumerate(rows_to_update):
            row_physical_id = (
                physical_id
                if valid_chain
                else "physical-invoice-"
                + hashlib.sha256(row["invoice_id"].encode("utf-8")).hexdigest()[:40]
            )
            bind.execute(
                sa.text(
                    "UPDATE promotion_invoice SET physical_invoice_id=:physical, "
                    "version_kind=:kind WHERE invoice_id=:invoice"
                ),
                {
                    "physical": row_physical_id,
                    "kind": 1 if (not valid_chain or index == 0) else 2,
                    "invoice": row["invoice_id"],
                },
            )
        if len(stores_by_number[invoice_number]) == 1 and valid_chain:
            first = ordered_chain[0]
            bind.execute(
                sa.text(
                    "INSERT INTO promotion_invoice_number_registry "
                    "(invoice_number, physical_invoice_id, first_invoice_id, store_id, registered_at) "
                    "VALUES (:number, :physical, :invoice, :store, :registered)"
                ),
                {
                    "number": invoice_number,
                    "physical": physical_id,
                    "invoice": first["invoice_id"],
                    "store": store_id,
                    "registered": first["registered_at"],
                },
            )
        if len(stores_by_number[invoice_number]) > 1 or not valid_chain:
            for row in group:
                bind.execute(
                    sa.text(
                        "INSERT INTO promotion_invoice_lifecycle_migration_exception "
                        "(invoice_id, reason_code, evidence_json) "
                        "VALUES (:invoice, :reason, :evidence)"
                    ),
                    {
                        "invoice": row["invoice_id"],
                        "reason": (
                            "INVOICE_NUMBER_USED_BY_MULTIPLE_STORES"
                            if len(stores_by_number[invoice_number]) > 1
                            else "AMBIGUOUS_INVOICE_VERSION_CHAIN"
                        ),
                        "evidence": json.dumps(
                            {
                                "invoiceNumber": invoice_number,
                                "storeIds": sorted(stores_by_number[invoice_number]),
                            },
                            ensure_ascii=False,
                        ),
                    },
                )

    with op.batch_alter_table("promotion_invoice") as batch:
        batch.alter_column("physical_invoice_id", nullable=False)
        batch.alter_column("version_kind", nullable=False)
        batch.create_unique_constraint(
            "uk_promotion_invoice_physical_version",
            ["physical_invoice_id", "version_no"],
        )
        batch.create_check_constraint(
            "ck_promotion_invoice_version_kind", "version_kind IN (1, 2)"
        )
    op.create_index(
        "idx_promotion_invoice_current_physical",
        "promotion_invoice",
        ["physical_invoice_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index(
        "idx_promotion_invoice_unique_replacement_source",
        "promotion_invoice",
        ["replaces_invoice_id"],
        unique=True,
        postgresql_where=sa.text(
            "replaces_invoice_id IS NOT NULL AND version_kind = 1"
        ),
        sqlite_where=sa.text(
            "replaces_invoice_id IS NOT NULL AND version_kind = 1"
        ),
    )
    op.create_table(
        "promotion_invoice_replacement_source",
        _id_column(),
        sa.Column("replacement_invoice_id", sa.String(length=128), nullable=False),
        sa.Column("source_invoice_id", sa.String(length=128), nullable=False),
        sa.Column("source_physical_invoice_id", sa.String(length=128), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_promotion_invoice_replacement_source"),
        sa.UniqueConstraint(
            "replacement_invoice_id",
            "source_invoice_id",
            name="uk_promotion_invoice_replacement_source_pair",
        ),
        sa.UniqueConstraint(
            "source_invoice_id",
            name="uk_promotion_invoice_replacement_source_source",
        ),
    )
    op.create_index(
        "idx_promotion_invoice_replacement_source_replacement",
        "promotion_invoice_replacement_source",
        ["replacement_invoice_id"],
    )
    bind.execute(
        sa.text(
            "INSERT INTO promotion_invoice_replacement_source "
            "(replacement_invoice_id, source_invoice_id, source_physical_invoice_id, linked_at) "
            "SELECT replacement.invoice_id, source.invoice_id, source.physical_invoice_id, "
            "replacement.registered_at FROM promotion_invoice AS replacement "
            "JOIN promotion_invoice AS source "
            "ON source.invoice_id = replacement.replaces_invoice_id "
            "WHERE replacement.replaces_invoice_id IS NOT NULL AND replacement.version_kind = 1"
        )
    )
    op.create_table(
        "promotion_invoice_lifecycle_event",
        _id_column(),
        sa.Column("lifecycle_event_id", sa.String(length=128), nullable=False),
        sa.Column("physical_invoice_id", sa.String(length=128), nullable=False),
        sa.Column("invoice_id", sa.String(length=128), nullable=False),
        sa.Column("invoice_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("read_version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("operator_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "gmt_create",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_promotion_invoice_lifecycle_event"),
        sa.UniqueConstraint(
            "lifecycle_event_id", name="uk_promotion_invoice_lifecycle_event_id"
        ),
        sa.UniqueConstraint(
            "idempotency_key_hash", name="uk_promotion_invoice_lifecycle_idempotency"
        ),
        sa.CheckConstraint(
            "event_type IN (1, 2)", name="ck_promotion_invoice_lifecycle_event_type"
        ),
        sa.CheckConstraint(
            "read_version > 0", name="ck_promotion_invoice_lifecycle_read_version"
        ),
    )
    op.create_index(
        "idx_promotion_invoice_lifecycle_current_physical",
        "promotion_invoice_lifecycle_event",
        ["physical_invoice_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index(
        "idx_promotion_invoice_lifecycle_invoice",
        "promotion_invoice_lifecycle_event",
        ["invoice_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    lifecycle_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM promotion_invoice_lifecycle_event")
    ).scalar_one()
    replacement_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM promotion_invoice_replacement_source")
    ).scalar_one()
    legacy_replacement_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM promotion_invoice "
            "WHERE replaces_invoice_id IS NOT NULL"
        )
    ).scalar_one()
    if lifecycle_count or replacement_count or legacy_replacement_count:
        raise RuntimeError(
            "cannot downgrade 20260821_0039: promotion invoice lifecycle or "
            "replacement facts exist; archive or reverse them through an audited "
            "business correction before downgrading"
        )
    op.drop_table("promotion_invoice_lifecycle_event")
    op.drop_index(
        "idx_promotion_invoice_replacement_source_replacement",
        table_name="promotion_invoice_replacement_source",
    )
    op.drop_table("promotion_invoice_replacement_source")
    op.drop_index(
        "idx_promotion_invoice_unique_replacement_source",
        table_name="promotion_invoice",
    )
    op.drop_index(
        "idx_promotion_invoice_current_physical", table_name="promotion_invoice"
    )
    with op.batch_alter_table("promotion_invoice") as batch:
        batch.drop_constraint(
            "ck_promotion_invoice_version_kind", type_="check"
        )
        batch.drop_constraint(
            "uk_promotion_invoice_physical_version", type_="unique"
        )
        batch.drop_column("replaces_invoice_id")
        batch.drop_column("version_kind")
        batch.drop_column("physical_invoice_id")
    op.drop_table("promotion_invoice_lifecycle_migration_exception")
    op.drop_table("promotion_invoice_number_registry")
