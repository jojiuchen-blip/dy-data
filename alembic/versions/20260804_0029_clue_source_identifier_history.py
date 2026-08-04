"""add clue source identifier history

Revision ID: 20260804_0029
Revises: 20260727_0028
Create Date: 2026-08-04 12:00:00
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from alembic import op
import sqlalchemy as sa


revision = "20260804_0029"
down_revision = "20260727_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clue_source_identifier_history",
        sa.Column("identifier_history_id", sa.Text(), primary_key=True),
        sa.Column(
            "lead_key",
            sa.Text(),
            sa.ForeignKey("clue_master_leads.lead_key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_clue_row_key", sa.Text(), nullable=False),
        sa.Column("identifier_type", sa.String(length=32), nullable=False),
        sa.Column("identifier_value", sa.Text(), nullable=False),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_clue_row_key",
            "identifier_type",
            "identifier_value",
            name="uq_clue_source_identifier_history_source_type_value",
        ),
    )
    for index_name, columns in (
        ("ix_clue_source_identifier_history_lead_key", ["lead_key"]),
        ("ix_clue_source_identifier_history_source_clue_row_key", ["source_clue_row_key"]),
        ("ix_clue_source_identifier_history_first_seen_at", ["first_seen_at"]),
        ("ix_clue_source_identifier_history_last_seen_at", ["last_seen_at"]),
        ("ix_clue_source_identifier_history_is_current", ["is_current"]),
        (
            "ix_clue_source_identifier_history_lead_type_current",
            ["lead_key", "identifier_type", "is_current"],
        ),
        (
            "ix_clue_source_identifier_history_source_type_current",
            ["source_clue_row_key", "identifier_type", "is_current"],
        ),
    ):
        op.create_index(index_name, "clue_source_identifier_history", columns)
    _backfill_current_identifiers()


def downgrade() -> None:
    op.drop_table("clue_source_identifier_history")


def _backfill_current_identifiers() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT
                lead_key,
                source_clue_row_key,
                source_identity_key,
                canonical_clue_id,
                first_seen_at,
                last_seen_at,
                created_at,
                updated_at
            FROM clue_master_leads
            """
        )
    ).mappings()
    history_table = sa.table(
        "clue_source_identifier_history",
        sa.column("identifier_history_id", sa.Text()),
        sa.column("lead_key", sa.Text()),
        sa.column("source_clue_row_key", sa.Text()),
        sa.column("identifier_type", sa.String(length=32)),
        sa.column("identifier_value", sa.Text()),
        sa.column("source_payload_hash", sa.String(length=64)),
        sa.column("first_seen_at", sa.DateTime(timezone=True)),
        sa.column("last_seen_at", sa.DateTime(timezone=True)),
        sa.column("is_current", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    while rows := result.fetchmany(5_000):
        values: list[dict[str, object]] = []
        for row in rows:
            first_seen_at = _as_datetime(row["first_seen_at"] or row["created_at"])
            last_seen_at = _as_datetime(
                row["last_seen_at"] or row["updated_at"] or first_seen_at
            )
            created_at = _as_datetime(row["created_at"] or first_seen_at)
            updated_at = _as_datetime(row["updated_at"] or last_seen_at)
            for identifier_type, identifier_value in (
                ("source_identity_key", row["source_identity_key"]),
                ("clue_id", row["canonical_clue_id"]),
            ):
                if not identifier_value:
                    continue
                values.append(
                    {
                        "identifier_history_id": _history_id(
                            row["source_clue_row_key"],
                            identifier_type,
                            identifier_value,
                        ),
                        "lead_key": row["lead_key"],
                        "source_clue_row_key": row["source_clue_row_key"],
                        "identifier_type": identifier_type,
                        "identifier_value": identifier_value,
                        "source_payload_hash": None,
                        "first_seen_at": first_seen_at,
                        "last_seen_at": last_seen_at,
                        "is_current": True,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    }
                )
        if values:
            op.bulk_insert(history_table, values)


def _history_id(source_clue_row_key: str, identifier_type: str, identifier_value: str) -> str:
    source = f"{source_clue_row_key}|{identifier_type}|{identifier_value}"
    return f"clue-identifier-{sha256(source.encode('utf-8')).hexdigest()[:32]}"


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("clue identifier history backfill requires timestamp values")
