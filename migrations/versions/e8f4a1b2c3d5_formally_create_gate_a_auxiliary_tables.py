"""formally create gate A auxiliary tables (note_links, auth_tokens, rate_limit_buckets)

Revision ID: e8f4a1b2c3d5
Revises: d7e3f2a1b8c4
Create Date: 2026-06-13 14:30:00.000000

Idempotent repair migration: ensures the three Gate A auxiliary tables exist
even if earlier revisions were partially applied or skipped on a target database.
"""
from alembic import op

from util import ensure_all_gate_a_auxiliary_tables

revision = "e8f4a1b2c3d5"
down_revision = "d7e3f2a1b8c4"
branch_labels = None
depends_on = None


def upgrade():
    ensure_all_gate_a_auxiliary_tables()


def downgrade():
    # Intentionally no-op: prior migrations own teardown of these tables.
    pass
