#!/usr/bin/env python3
"""
Gate A — Show production vs local DB alignment and next fix step.

  python scripts/gate_a_status.py
  python scripts/gate_a_status.py --api https://infocord.onrender.com
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

API = "https://infocord.onrender.com"
EXPECTED = "e8f4a1b2c3d5"
MIGRATED_HOST_HINT = "ep-old-resonance"  # DB already at head locally


def _host_hint(url: str) -> str | None:
    if not url:
        return None
    try:
        p = urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1))
        host = p.hostname or ""
        db = (p.path or "").lstrip("/").split("?")[0] or ""
        return f"{host}/{db}" if host else None
    except Exception:
        return None


def _fetch_health(api: str) -> dict:
    import httpx
    r = httpx.get(f"{api.rstrip('/')}/health", timeout=120.0, verify=False)
    return r.json() if r.status_code == 200 else {"status": "error", "http": r.status_code}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.getenv("GATE_A_API", API))
    args = parser.parse_args()

    body = _fetch_health(args.api)
    prod_host = body.get("db_host", "?")
    prod_rev = body.get("migration_revision")
    missing = body.get("schema_tables_missing") or []
    local_host = _host_hint(os.getenv("DATABASE_URL", ""))

    print("=" * 60)
    print("Gate A status")
    print("=" * 60)
    print(f"Production API:     {args.api}")
    print(f"Production db_host: {prod_host}")
    print(f"Production revision:{prod_rev!r} (need {EXPECTED!r})")
    print(f"Missing tables:     {missing or 'none'}")
    if local_host:
        print(f"Local DATABASE_URL: {local_host}")
    else:
        print("Local DATABASE_URL: (not set in this shell)")
    print()

    if body.get("migration_revision") == EXPECTED and not missing:
        print("ALIGNED — run: python scripts/gate_a_verify.py --full-smoke --insecure")
        return 0

    if MIGRATED_HOST_HINT in (prod_host or ""):
        print("Production already uses ep-old-resonance but schema behind.")
        print("Run: python scripts/gate_a_migrate.py  (with Render DATABASE_URL in env)")
        return 1

    if local_host and MIGRATED_HOST_HINT in local_host and prod_host != local_host:
        print("MISMATCH — you migrated ep-old-resonance; Render uses a different Neon DB.")
        print()
        print("FASTEST FIX (no migrate):")
        print("  1. Render -> infocord -> Environment -> DATABASE_URL")
        print("  2. Paste your ep-old-resonance pooled connection string (one line)")
        print("  3. Save, wait for Live")
        print("  4. python scripts/gate_a_verify.py --insecure")
        print()
        print("ALTERNATIVE — migrate Render's DB instead:")
        print("  1. Copy DATABASE_URL from Render Environment (eye icon)")
        print('  2. $env:DATABASE_URL = "<paste>"')
        print("  3. python scripts/gate_a_migrate.py")
        return 1

    print("Run gate_a_migrate.py with the same DATABASE_URL Render uses.")
    print(json.dumps(body, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
