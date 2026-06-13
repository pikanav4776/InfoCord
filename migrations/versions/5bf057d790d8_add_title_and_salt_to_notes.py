"""add title and salt to notes

Revision ID: 5bf057d790d8
Revises: 3a70526dcb7c
Create Date: 2026-05-26 09:47:42.489072

"""
from alembic import op
import sqlalchemy as sa

from util import column_exists

revision = '5bf057d790d8'
down_revision = '3a70526dcb7c'
branch_labels = None
depends_on = None


def upgrade():
    # Only add columns — do NOT recreate tables (version already added by 3a70526dcb7c).
    if not column_exists('notes', 'title'):
        op.add_column('notes', sa.Column('title', sa.String(length=255), nullable=True))
    if not column_exists('notes', 'salt'):
        op.add_column('notes', sa.Column('salt', sa.String(length=64), nullable=True))


def downgrade():
    if column_exists('notes', 'salt'):
        op.drop_column('notes', 'salt')
    if column_exists('notes', 'title'):
        op.drop_column('notes', 'title')
