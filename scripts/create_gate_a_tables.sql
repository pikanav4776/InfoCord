-- Gate A auxiliary tables for InfoCord (Neon / PostgreSQL)
-- Run in Neon SQL Editor if flask db upgrade cannot be used.
-- Safe to re-run: uses IF NOT EXISTS.

-- note_links: directed edges between notes
CREATE TABLE IF NOT EXISTS note_links (
    source_note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    PRIMARY KEY (source_note_id, target_note_id)
);

-- auth_tokens: HMAC-SHA256 digests only — NEVER store plaintext bearer tokens
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash   VARCHAR(64) PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at   TIMESTAMP NOT NULL,
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_auth_tokens_user_id ON auth_tokens (user_id);
CREATE INDEX IF NOT EXISTS ix_auth_tokens_expires_at ON auth_tokens (expires_at);

-- rate_limit_buckets: fixed-window counters for auth rate limiting
CREATE TABLE IF NOT EXISTS rate_limit_buckets (
    id           SERIAL PRIMARY KEY,
    bucket_key   VARCHAR(255) NOT NULL,
    window_start TIMESTAMP NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_rate_limit_bucket_window UNIQUE (bucket_key, window_start)
);
CREATE INDEX IF NOT EXISTS ix_rate_limit_buckets_bucket_key ON rate_limit_buckets (bucket_key);

-- After manual SQL, stamp Alembic head (adjust if your head revision differs):
-- INSERT INTO alembic_version (version_num) VALUES ('e8f4a1b2c3d5')
--   ON CONFLICT DO NOTHING;
-- Or run: flask db stamp e8f4a1b2c3d5
