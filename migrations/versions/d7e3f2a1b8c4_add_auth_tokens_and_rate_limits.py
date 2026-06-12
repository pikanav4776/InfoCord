"""add auth_tokens and rate_limit_buckets tables

Revision ID: d7e3f2a1b8c4
Revises: c4d2e8f1a9b3
Create Date: 2026-06-08 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d7e3f2a1b8c4"
down_revision = "c4d2e8f1a9b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_expires_at", "auth_tokens", ["expires_at"])

    op.create_table(
        "rate_limit_buckets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bucket_key", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket_key", "window_start", name="uq_rate_limit_bucket_window"),
    )
    op.create_index("ix_rate_limit_buckets_bucket_key", "rate_limit_buckets", ["bucket_key"])


def downgrade():
    op.drop_index("ix_rate_limit_buckets_bucket_key", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
    op.drop_index("ix_auth_tokens_expires_at", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_user_id", table_name="auth_tokens")
    op.drop_table("auth_tokens")
