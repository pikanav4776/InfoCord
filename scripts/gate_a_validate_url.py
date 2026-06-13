#!/usr/bin/env python3
"""
Validate DATABASE_URL before pasting into Render (avoids 503 db unavailable).

  $env:DATABASE_URL = "postgresql://..."   # same string that worked for gate_a_migrate
  python scripts/gate_a_validate_url.py

Or save URL to .gate_a_database_url (one line, gitignored).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
URL_FILE = ROOT / ".gate_a_database_url"


def _resolve_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url and URL_FILE.is_file():
        url = URL_FILE.read_text(encoding="utf-8").strip()
    return url.replace("\r", "").replace("\n", "")


def _host_db(url: str) -> str:
    p = urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1))
    db = (p.path or "").lstrip("/").split("?")[0]
    return f"{p.hostname}/{db}" if p.hostname else "?"


def _render_paste_url(raw: str) -> str:
    """URL for Render env: postgresql://, sslmode only, no channel_binding."""
    p = urlparse(raw.replace("postgresql+psycopg2://", "postgresql://", 1))
    q = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() != "channel_binding"
    ]
    return urlunparse(p._replace(scheme="postgresql", query=urlencode(q)))


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass

    url = _resolve_url()
    errors: list[str] = []
    warnings: list[str] = []

    if not url:
        print("ERROR: DATABASE_URL not set. Use the full Neon string, not host-only.")
        print(f"  Save to {URL_FILE.name} or set $env:DATABASE_URL")
        return 1

    if not url.startswith(("postgresql://", "postgres://", "postgresql+psycopg2://")):
        if "neon.tech" in url and "://" not in url:
            errors.append("Looks like HOST ONLY — Render needs the full postgresql://user:pass@host/db?sslmode=require")
        else:
            errors.append("Must start with postgresql:// or postgres:// (copy from Neon Connect)")

    if url.startswith('"') or url.endswith('"'):
        errors.append("Remove surrounding quotes — paste raw URL in Render")

    p = urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1))
    if not p.hostname:
        errors.append("Missing hostname in URL")
    if not p.username:
        errors.append("Missing username (should be neondb_owner)")
    if p.password is None or p.password == "":
        errors.append("Missing password — copy full string from Neon (eye icon)")
    elif "@" in unquote(p.password) and "%40" not in url.split("@")[0]:
        warnings.append("Password may contain @ — if connect fails, URL-encode @ as %40 in password")

    if p.hostname and "pooler" not in p.hostname and "neon.tech" in p.hostname:
        warnings.append("Host has no -pooler — Neon Connect with 'Pooled connection' ON is recommended")

    if "sslmode" not in url and "neon.tech" in url:
        warnings.append("Add ?sslmode=require if Neon string omits it")

    if "channel_binding" in url.lower():
        warnings.append("Neon added channel_binding=require — omit it in Render (use Render paste URL below)")

    host = _host_db(url)
    print(f"URL host/db: {host}")
    print(f"Username:    {p.username or '(missing)'}")
    print(f"Password:    {'set' if p.password else 'MISSING'}")
    print()

    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"FAIL: {e}")

    if errors:
        print("\nRender rejected connection (503) usually means URL format is wrong.")
        return 1

    os.environ.setdefault("FLASK_APP", "run:app")
    os.environ["DATABASE_URL"] = url

    print("Testing connection (SELECT 1)...")
    try:
        from run import app, db
        import sqlalchemy as sa

        with app.app_context():
            db.session.execute(sa.text("SELECT 1"))
            rev = db.session.execute(
                sa.text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar()
            insp = sa.inspect(db.engine)
            tables = set(insp.get_table_names())
            aux = {"note_links", "auth_tokens", "rate_limit_buckets"}
            missing = sorted(aux - tables)
        print(f"OK: connected, alembic={rev!r}")
        if missing:
            print(f"WARN: missing auxiliary tables {missing} — run: python scripts\\gate_a_migrate.py")
        else:
            print("OK: note_links, auth_tokens, rate_limit_buckets present")
        render_url = _render_paste_url(url)
        print()
        print("COPY TO Render -> infocord -> Environment -> DATABASE_URL")
        print("(one line, no quotes — then Save and wait until Live)")
        print("-" * 60)
        print(render_url)
        print("-" * 60)
        return 0 if not missing else 1
    except Exception as exc:
        print(f"FAIL: connection error — {type(exc).__name__}")
        print("  Re-copy from Neon -> Connect -> Pooled connection string")
        print("  If password has special chars, use Neon 'Show password' and copy again")
        return 1


if __name__ == "__main__":
    sys.exit(main())
