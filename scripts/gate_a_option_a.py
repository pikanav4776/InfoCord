#!/usr/bin/env python3
"""
Option A — Ensure Gate A auxiliary tables on ep-old-resonance, then point Render at it.

Creates note_links, auth_tokens, rate_limit_buckets via Alembic (idempotent).

Usage:
  1. Save your ep-old-resonance pooled URL (one line) to .gate_a_database_url
     OR set $env:DATABASE_URL in PowerShell / set DATABASE_URL in CMD
  2. python scripts/gate_a_option_a.py
  3. Paste the SAME URL into Render -> Environment -> DATABASE_URL -> Save
  4. python scripts/gate_a_verify.py --insecure
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
URL_FILE = ROOT / ".gate_a_database_url"
EXPECTED = "e8f4a1b2c3d5"
TARGET_HINT = "old-resonance"
AUX_TABLES = ("note_links", "auth_tokens", "rate_limit_buckets")


def _host_hint(url: str) -> str:
    p = urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1))
    db = (p.path or "").lstrip("/").split("?")[0]
    return f"{p.hostname}/{db}" if p.hostname else "?"


def _resolve_database_url() -> str | None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url and URL_FILE.is_file():
        url = URL_FILE.read_text(encoding="utf-8").strip()
        os.environ["DATABASE_URL"] = url
        print(f"Using DATABASE_URL from {URL_FILE.name}")
    return url or None


def main() -> int:
    os.chdir(ROOT)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        load_dotenv(ROOT / ".flaskenv", override=False)
    except ImportError:
        pass

    db_url = _resolve_database_url()
    if not db_url:
        print("ERROR: Set ep-old-resonance DATABASE_URL first.")
        print(f"  Paste one line into: {URL_FILE}")
        print('  PowerShell: $env:DATABASE_URL = "postgresql://..."')
        return 1

    host = _host_hint(db_url)

    if TARGET_HINT not in host:
        print(f"WARNING: host {host!r} is not ep-old-resonance.")
        print("  Option A expects the DB you already migrated (ep-old-resonance-pooler).")
        print("  Continuing anyway — migrate is idempotent.\n")

    if "localhost" in host or "127.0.0.1" in host:
        print("ERROR: DATABASE_URL points at localhost — use Neon ep-old-resonance URL.")
        return 1

    print("=" * 60)
    print("Option A — create auxiliary tables + align Render")
    print("=" * 60)
    print(f"Target DB: {host}")
    print(f"Will create if missing: {list(AUX_TABLES)}")
    print()

    os.environ.setdefault("FLASK_APP", "run:app")
    os.environ["DATABASE_URL"] = db_url.strip().replace("\r", "").replace("\n", "")

    print("Step 1/2 — flask db upgrade (creates auxiliary tables)")
    print("-" * 60)
    rc = subprocess.call([sys.executable, str(ROOT / "scripts" / "gate_a_migrate.py")], env=os.environ)
    if rc != 0:
        return rc

    print()
    print("Step 2/2 — postflight check")
    print("-" * 60)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gate_a_postflight.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    try:
        post = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        print(proc.stdout or proc.stderr or "postflight failed")
        return 1

    missing = post.get("tables_missing") or []
    rev = post.get("revision")

    if missing:
        print(f"FAIL: still missing tables: {missing}")
        print("  Run SQL manually: scripts/create_gate_a_tables.sql in Neon SQL Editor")
        return 1

    if rev != EXPECTED:
        print(f"FAIL: revision {rev!r}, expected {EXPECTED}")
        return 1

    print(f"OK: all tables present, revision {rev!r}")
    print()
    print("=" * 60)
    print("NEXT — Render dashboard (required for Gate A to pass)")
    print("=" * 60)
    print("  1. Render -> infocord -> Environment -> DATABASE_URL")
    print("  2. Paste the SAME ep-old-resonance URL (one line, no line breaks)")
    print(f"     Host must be: {post.get('db_host')}")
    print("  3. Save -> wait until deploy shows Live")
    print("  4. python scripts\\gate_a_verify.py --insecure")
    print("  5. python scripts\\gate_a_verify.py --full-smoke --insecure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
