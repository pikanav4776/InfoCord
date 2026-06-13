"""Shared helpers for idempotent Alembic migrations (schema drift safe)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def _inspector():
    return sa.inspect(op.get_bind())


def table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return column_name in {c["name"] for c in _inspector().get_columns(table_name)}


def index_exists(table_name: str, index_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return index_name in {idx["name"] for idx in _inspector().get_indexes(table_name)}


# ── Gate A auxiliary tables (formal DDL — idempotent) ─────────────────────────


def ensure_note_links_table() -> None:
    """Directed links between notes (source -> target), cascade on note delete."""
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


def ensure_auth_tokens_table() -> None:
    """
    Bearer session tokens — security model:
      - Plaintext tokens NEVER stored (client/mobile only).
      - DB holds HMAC-SHA256(token, FLASK_SECRET_KEY) hex digests (64 chars).
      - expires_at enforced on lookup; rows purged on login / account delete.
    """
    if not table_exists("auth_tokens"):
        op.create_table(
            "auth_tokens",
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("token_hash"),
        )
    if table_exists("auth_tokens"):
        if not index_exists("auth_tokens", "ix_auth_tokens_user_id"):
            op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
        if not index_exists("auth_tokens", "ix_auth_tokens_expires_at"):
            op.create_index("ix_auth_tokens_expires_at", "auth_tokens", ["expires_at"])


def ensure_rate_limit_buckets_table() -> None:
    """PostgreSQL-backed fixed-window rate limits (multi-worker safe)."""
    if not table_exists("rate_limit_buckets"):
        op.create_table(
            "rate_limit_buckets",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("bucket_key", sa.String(length=255), nullable=False),
            sa.Column("window_start", sa.DateTime(), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "bucket_key", "window_start", name="uq_rate_limit_bucket_window"
            ),
        )
    if table_exists("rate_limit_buckets"):
        if not index_exists("rate_limit_buckets", "ix_rate_limit_buckets_bucket_key"):
            op.create_index(
                "ix_rate_limit_buckets_bucket_key", "rate_limit_buckets", ["bucket_key"]
            )


def ensure_all_gate_a_auxiliary_tables() -> None:
    """Create note_links, auth_tokens, rate_limit_buckets if missing."""
    ensure_note_links_table()
    ensure_auth_tokens_table()
    ensure_rate_limit_buckets_table()
