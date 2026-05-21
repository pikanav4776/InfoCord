"""add lockout fields to users

Revision ID: edc83421847f
Revises: 1a4aca8fbfb9
Create Date: 2026-05-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'edc83421847f'
down_revision = '1a4aca8fbfb9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_attempts')