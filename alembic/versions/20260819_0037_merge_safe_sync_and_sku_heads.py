"""merge the deployed safe-sync chain with the SKU import head

Revision ID: 20260819_0037
Revises: 20260806_0036, 20260813_0030
Create Date: 2026-08-19 16:00:00
"""

from __future__ import annotations


revision = "20260819_0037"
down_revision = ("20260806_0036", "20260813_0030")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge the two already-applied schema branches without changing data."""


def downgrade() -> None:
    """The merge revision has no standalone schema to reverse."""
