"""add recovery_key_hash to users

Revision ID: b8a1a6e2c4f1
Revises: 5bf057d790d8
Create Date: 2026-06-02 09:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b8a1a6e2c4f1"
down_revision = "5bf057d790d8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("recovery_key_hash", sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column("users", "recovery_key_hash")
