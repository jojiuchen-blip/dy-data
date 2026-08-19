"""add compact projection provenance closure metadata

Revision ID: 20260806_0036
Revises: 20260806_0035
Create Date: 2026-08-08 13:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260806_0036"
down_revision = "20260806_0035"
branch_labels = None
depends_on = None


_KIND_BASE_DEPTH_CHECK = (
    "(generation_kind = 'lineage' AND compaction_base_generation_id IS NULL) OR "
    "(generation_kind = 'legacy_root' AND base_generation_id IS NULL "
    "AND lineage_depth = 0 AND compaction_base_generation_id IS NULL) OR "
    "(generation_kind = 'compact' AND base_generation_id IS NULL "
    "AND lineage_depth = 0 AND compaction_base_generation_id IS NOT NULL)"
)

_DIGEST_CHECK = (
    "length(source_digest) = 64 AND source_digest = lower(source_digest) AND "
    "replace(replace(replace(replace(replace(replace(replace(replace("
    "replace(replace(replace(replace(replace(replace(replace(replace("
    "source_digest, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), "
    "'5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), "
    "'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '') = ''"
)

_REFERENCE_CHECK = (
    "reference_head_generation_id IS NULL OR "
    "(reference_head_generation_id = generation_id AND owner_state='owned' "
    "AND source_kind='overlay' AND data_generation_id IS NOT NULL)"
)


def _is_sqlite() -> bool:
    return op.get_context().dialect.name == "sqlite"


def _upgrade_generation() -> None:
    if _is_sqlite():
        with op.batch_alter_table(
            "settlement_projection_generation", recreate="always"
        ) as batch:
            batch.add_column(
                sa.Column(
                    "generation_kind",
                    sa.String(length=32),
                    nullable=False,
                    server_default=sa.text("'lineage'"),
                )
            )
            batch.add_column(
                sa.Column("compaction_base_generation_id", sa.Text(), nullable=True)
            )
            batch.create_foreign_key(
                "fk_settlement_projection_generation_compaction_base",
                "settlement_projection_generation",
                ["compaction_base_generation_id"],
                ["generation_id"],
                ondelete="RESTRICT",
            )
            batch.create_check_constraint(
                "ck_settlement_projection_generation_kind",
                "generation_kind IN ('lineage', 'legacy_root', 'compact')",
            )
            batch.create_check_constraint(
                "ck_settlement_projection_generation_kind_base_depth",
                _KIND_BASE_DEPTH_CHECK,
            )
            batch.create_check_constraint(
                "ck_settlement_projection_generation_compaction_self_reference",
                "compaction_base_generation_id IS NULL "
                "OR compaction_base_generation_id <> generation_id",
            )
    else:
        op.add_column(
            "settlement_projection_generation",
            sa.Column(
                "generation_kind",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'lineage'"),
            ),
        )
        op.add_column(
            "settlement_projection_generation",
            sa.Column("compaction_base_generation_id", sa.Text(), nullable=True),
        )
        op.create_foreign_key(
            "fk_settlement_projection_generation_compaction_base",
            "settlement_projection_generation",
            "settlement_projection_generation",
            ["compaction_base_generation_id"],
            ["generation_id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            "ck_settlement_projection_generation_kind",
            "settlement_projection_generation",
            "generation_kind IN ('lineage', 'legacy_root', 'compact')",
        )
        op.create_check_constraint(
            "ck_settlement_projection_generation_kind_base_depth",
            "settlement_projection_generation",
            _KIND_BASE_DEPTH_CHECK,
        )
        op.create_check_constraint(
            "ck_settlement_projection_generation_compaction_self_reference",
            "settlement_projection_generation",
            "compaction_base_generation_id IS NULL "
            "OR compaction_base_generation_id <> generation_id",
        )
    op.create_index(
        "ix_settlement_projection_generation_compaction_base",
        "settlement_projection_generation",
        ["compaction_base_generation_id"],
    )


def _create_closure() -> None:
    op.create_table(
        "settlement_projection_compaction_closure",
        sa.Column("compact_generation_id", sa.Text(), nullable=False),
        sa.Column("source_generation_id", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint(
            "compact_generation_id",
            "source_generation_id",
            name="pk_settlement_projection_compaction_closure",
        ),
        sa.ForeignKeyConstraint(
            ["compact_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_compaction_closure_compact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_generation_id"],
            ["settlement_projection_generation.generation_id"],
            name="fk_settlement_projection_compaction_closure_source",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "compact_generation_id <> source_generation_id",
            name="ck_settlement_projection_compaction_closure_distinct",
        ),
        sa.CheckConstraint(
            _DIGEST_CHECK,
            name="ck_settlement_projection_compaction_closure_digest",
        ),
    )
    op.create_index(
        "ix_settlement_projection_compaction_closure_source",
        "settlement_projection_compaction_closure",
        ["source_generation_id"],
    )


def _upgrade_manifest() -> None:
    if _is_sqlite():
        with op.batch_alter_table(
            "settlement_projection_partition_manifest", recreate="always"
        ) as batch:
            batch.add_column(
                sa.Column("reference_head_generation_id", sa.Text(), nullable=True)
            )
            batch.create_foreign_key(
                "fk_settlement_projection_manifest_compaction_source",
                "settlement_projection_compaction_closure",
                ["reference_head_generation_id", "data_generation_id"],
                ["compact_generation_id", "source_generation_id"],
                ondelete="RESTRICT",
            )
            batch.create_check_constraint(
                "ck_settlement_projection_manifest_reference_head",
                _REFERENCE_CHECK,
            )
    else:
        op.add_column(
            "settlement_projection_partition_manifest",
            sa.Column("reference_head_generation_id", sa.Text(), nullable=True),
        )
        op.create_foreign_key(
            "fk_settlement_projection_manifest_compaction_source",
            "settlement_projection_partition_manifest",
            "settlement_projection_compaction_closure",
            ["reference_head_generation_id", "data_generation_id"],
            ["compact_generation_id", "source_generation_id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            "ck_settlement_projection_manifest_reference_head",
            "settlement_projection_partition_manifest",
            _REFERENCE_CHECK,
        )
    op.create_index(
        "ix_settlement_projection_manifest_reference_source",
        "settlement_projection_partition_manifest",
        ["reference_head_generation_id", "data_generation_id"],
    )


def upgrade() -> None:
    _upgrade_generation()
    _create_closure()
    _upgrade_manifest()


def _downgrade_preflight() -> None:
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("0036 downgrade requires an online compact-provenance preflight")
    row = op.get_bind().execute(
        sa.text(
            "SELECT "
            "(SELECT COUNT(*) FROM settlement_projection_generation "
            " WHERE generation_kind = 'compact') AS compact_count, "
            "(SELECT COUNT(*) FROM settlement_projection_compaction_closure) "
            " AS closure_count, "
            "(SELECT COUNT(*) FROM settlement_projection_partition_manifest "
            " WHERE reference_head_generation_id IS NOT NULL) AS reference_count"
        )
    ).mappings().one()
    if any(int(row[name] or 0) for name in ("compact_count", "closure_count", "reference_count")):
        raise RuntimeError("0036 downgrade refused: compact provenance is still live")


def _downgrade_manifest() -> None:
    op.drop_index(
        "ix_settlement_projection_manifest_reference_source",
        table_name="settlement_projection_partition_manifest",
    )
    if _is_sqlite():
        with op.batch_alter_table(
            "settlement_projection_partition_manifest", recreate="always"
        ) as batch:
            batch.drop_constraint(
                "fk_settlement_projection_manifest_compaction_source",
                type_="foreignkey",
            )
            batch.drop_constraint(
                "ck_settlement_projection_manifest_reference_head",
                type_="check",
            )
            batch.drop_column("reference_head_generation_id")
    else:
        op.drop_constraint(
            "fk_settlement_projection_manifest_compaction_source",
            "settlement_projection_partition_manifest",
            type_="foreignkey",
        )
        op.drop_constraint(
            "ck_settlement_projection_manifest_reference_head",
            "settlement_projection_partition_manifest",
            type_="check",
        )
        op.drop_column(
            "settlement_projection_partition_manifest",
            "reference_head_generation_id",
        )


def _downgrade_generation() -> None:
    op.drop_index(
        "ix_settlement_projection_generation_compaction_base",
        table_name="settlement_projection_generation",
    )
    if _is_sqlite():
        with op.batch_alter_table(
            "settlement_projection_generation", recreate="always"
        ) as batch:
            batch.drop_constraint(
                "fk_settlement_projection_generation_compaction_base",
                type_="foreignkey",
            )
            batch.drop_constraint(
                "ck_settlement_projection_generation_compaction_self_reference",
                type_="check",
            )
            batch.drop_constraint(
                "ck_settlement_projection_generation_kind_base_depth",
                type_="check",
            )
            batch.drop_constraint(
                "ck_settlement_projection_generation_kind",
                type_="check",
            )
            batch.drop_column("compaction_base_generation_id")
            batch.drop_column("generation_kind")
    else:
        op.drop_constraint(
            "fk_settlement_projection_generation_compaction_base",
            "settlement_projection_generation",
            type_="foreignkey",
        )
        for name in (
            "ck_settlement_projection_generation_compaction_self_reference",
            "ck_settlement_projection_generation_kind_base_depth",
            "ck_settlement_projection_generation_kind",
        ):
            op.drop_constraint(
                name,
                "settlement_projection_generation",
                type_="check",
            )
        op.drop_column(
            "settlement_projection_generation", "compaction_base_generation_id"
        )
        op.drop_column("settlement_projection_generation", "generation_kind")


def downgrade() -> None:
    _downgrade_preflight()
    _downgrade_manifest()
    op.drop_index(
        "ix_settlement_projection_compaction_closure_source",
        table_name="settlement_projection_compaction_closure",
    )
    op.drop_table("settlement_projection_compaction_closure")
    _downgrade_generation()
