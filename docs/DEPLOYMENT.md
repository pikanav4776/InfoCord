# Deployment

**Audience:** You + ops  
**Related:** [CI/CD](CI.md) · [Production readiness](PRODUCTION_READINESS.md) · [Main README](../README.md)

InfoCord runs on **Render** (Flask/Gunicorn) with **Neon** PostgreSQL. Production API: `https://infocord.onrender.com`.

---

## Environment variables

Copy [`.env.example`](../.env.example) to `.env` locally. **Never commit `.env`.**

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (Neon in prod; local Postgres for dev) |
| `FLASK_SECRET_KEY` | Flask session signing |
| `FLASK_ENV` | `development` or `production` |
| `NOTE_ENCRYPTION_KEY` | Server-side key for non-note crypto helpers (tests/gates) |

**Local example:**

```env
DATABASE_URL=postgresql://postgres:your-db-password@localhost:5433/infocord_mvp
FLASK_SECRET_KEY=your-secret-key
FLASK_ENV=development
NOTE_ENCRYPTION_KEY=your-base64-32-byte-key
```

`run.py` also accepts `DB_USERNAME` / `DB_PASSWORD` (or legacy `DB_username` / `DB_password`) and `DB_PORT` when `DATABASE_URL` is unset.

**Production:** Set the same variables in Render → **infocord** → **Environment**. If credentials were ever committed to git, rotate `FLASK_SECRET_KEY`, `NOTE_ENCRYPTION_KEY`, and your database password, then update Render and local `.env`.

---

## Render deployment

| Item | Detail |
|------|--------|
| **Service** | Gunicorn WSGI via [`render.yaml`](../render.yaml) |
| **Pre-deploy** | `pip install -r requirements.txt`, `flask db upgrade` |
| **Start command** | `gunicorn run:app` (see [`Procfile`](../Procfile)) |
| **Auto-deploy** | Push to `main` triggers deploy |
| **TLS** | Render provides HTTPS; `SESSION_COOKIE_SECURE` enabled in production |

### Verify deploy succeeded

1. After merge to `main`, open Render → **infocord** → wait for **Live**.
2. `GET https://infocord.onrender.com/health` → `"status": "ok"`, `"db": "ok"`.

See [CI.md — Verify deploy](CI.md#verify-deploy-succeeded) for the full CI/CD flow.

---

## Neon PostgreSQL

Neon is the production PostgreSQL host. The Flask app connects via `DATABASE_URL`.

**Manual checks:**

- Render → **infocord** → **Environment** → `DATABASE_URL` (must match `/health` `db_host` after deploy)
- Neon console → **Tables** → confirm all six tables exist: `users`, `categories`, `notes`, `note_links`, `auth_tokens`, `rate_limit_buckets`

**Connection string tips:**

- Copy from Neon **Connect**; use pooled URL for Render
- Use `?sslmode=require` only — omit `channel_binding=require`

**Source of truth for which DB Render uses:** `db_host` in `/health` (not the app URL). If migrate passed locally but verify fails, Render `DATABASE_URL` points at a different Neon project — realign or run `python scripts/gate_a_migrate.py` against Render's URL.

---

## Health endpoint

`GET /health` probes database connectivity and schema state.

**Expected response (essential fields):**

```json
{
  "status": "ok",
  "db": "ok",
  "db_host": "ep-xxxx-pooler.c-3.us-east-2.aws.neon.tech/neondb",
  "migration_revision": "e8f4a1b2c3d5",
  "migration_ok": true,
  "schema_ok": true,
  "schema_tables_missing": []
}
```

Also available: `GET /` (root).

---

## Gate A — Pre-app backend checklist (Phase A)

**Status: Complete** — production API + Neon verified at `https://infocord.onrender.com` before mobile work.

### What was done

1. **Schema (A1)** — Ran Alembic to head revision `e8f4a1b2c3d5` on Neon. All six tables present. Bearer tokens store HMAC digests only (never plaintext).
2. **Render alignment (A5)** — Set Render `DATABASE_URL` to the **same** pooled Neon URL used for migrate.
3. **Deploy** — `git push origin main` → Render auto-deploys; `render.yaml` runs `flask db upgrade` pre-deploy.
4. **Smoke (A2–A4)** — Automated prod test: signup → encrypted note → Bearer auth → account delete.

| Step | What | How verified |
|------|------|--------------|
| **A1** | Migrations at head on Neon | `/health`: `migration_ok: true`, `schema_tables_missing: []` |
| **A2** | Prod signup → note | `--full-smoke` or manual `/app` |
| **A3** | Account deletion | `--full-smoke` or Settings → Delete |
| **A4** | Bearer token auth | `--full-smoke` |
| **A5** | Latest code on Render | `git push` + `/health` returns 200 |

### Verify (re-run anytime)

```powershell
cd c:\InfoCord
.venv\Scripts\activate
python scripts/gate_a_verify.py --insecure
python scripts/gate_a_verify.py --full-smoke --insecure
```

Both must print **`GATE A: PASSED`**. On Windows add `--insecure` if TLS verification fails.

### Gate A tooling

| Script | Purpose |
|--------|---------|
| `scripts/gate_a_migrate.py` | Apply migrations to `$env:DATABASE_URL` |
| `scripts/gate_a_verify.py` | Gate A verify (`--full-smoke --insecure`) |
| `scripts/gate_a_validate_url.py` | Test URL locally; print Render-safe connection string |
| `scripts/gate_a_status.py` | Compare prod `db_host` vs local `DATABASE_URL` |

**New migrations workflow:** set `DATABASE_URL` to Neon → `gate_a_migrate.py` → push to Render → re-run verify.

---

## Production hardening (already in place)

| Concern | Implementation |
|---------|----------------|
| **Bearer tokens** | HMAC digests in PostgreSQL `auth_tokens` (restart- and multi-worker-safe) |
| **Rate limiting** | PostgreSQL `rate_limit_buckets` + `@db_rate_limit` on auth endpoints |
| **Account lockout** | 5 failed attempts → 15-minute lockout |
| **Secure cookies** | HttpOnly, Secure (prod), SameSite=Lax |
| **CORS** | Configured for production frontend origins |

`Flask-Limiter` is listed in `requirements.txt` but unused — in-memory storage would not survive restarts or scale across Gunicorn workers.

---

## See also

- [CI.md](CI.md) — automated tests and deploy verification
- [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) — deferred store assets (Gate C), monitoring gaps, compliance
- [mobile/README.md](../mobile/README.md) — Gate B mobile client (requires Gate A pass first)
