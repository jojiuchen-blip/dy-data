"""Persist organization account scope without changing existing store bindings."""
from alembic import op
import sqlalchemy as sa

revision = '20260915_0059'
down_revision = '20260911_0058'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('org_scope', sa.JSON(), nullable=True))


def downgrade():
    # Downgrading would leave snapshot membership stale and potentially overbroad.
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM users WHERE org_scope IS NOT NULL AND CAST(org_scope AS TEXT) != 'null'")).scalar():
        raise RuntimeError('Convert organization accounts to reviewed store scopes before downgrade')
    op.drop_column('users', 'org_scope')
