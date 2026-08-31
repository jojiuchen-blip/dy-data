"""merge DYDATA-81 finance and clue platform migration heads

Revision ID: 20260831_0047
Revises: 20260831_0044, 20260831_0046
Create Date: 2026-08-31 15:55:00
"""

from __future__ import annotations


revision = "20260831_0047"
down_revision = ("20260831_0044", "20260831_0046")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the independent finance and clue migration chains."""


def downgrade() -> None:
    """Re-expose the two parent heads when rolling back the merge revision."""
