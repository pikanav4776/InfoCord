"""add version to notes

Revision ID: 3a70526dcb7c
Revises: edc83421847f
Create Date: 2026-05-19 16:42:33.728550

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a70526dcb7c'
down_revision = 'edc83421847f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('notes', sa.Column('version', sa.Integer(), nullable=False, server_default='1'))


def downgrade():
    op.drop_column('notes', 'version')