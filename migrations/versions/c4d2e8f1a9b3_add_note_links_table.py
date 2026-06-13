"""add note_links table

Revision ID: c4d2e8f1a9b3
Revises: b8a1a6e2c4f1
Create Date: 2026-06-08 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from util import table_exists

revision = "c4d2e8f1a9b3"
down_revision = "b8a1a6e2c4f1"
branch_labels = None
depends_on = None


def upgrade():
    if table_exists("note_links"):
        return
    op.create_table(
        "note_links",
        sa.Column("source_note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["source_note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_note_id", "target_note_id"),
    )


def downgrade():
    if table_exists("note_links"):
        op.drop_table("note_links")
