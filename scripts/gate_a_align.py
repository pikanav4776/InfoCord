#!/usr/bin/env python3
"""
Gate A — Migrate DATABASE_URL target, then check if Render /health matches.

Usage:
  $env:DATABASE_URL = "<Neon connection string>"
  $env:FLASK_APP = "run:app"
  python scripts/gate_a_align.py

Two ways to pass Gate A:
  A) Migrate ep-old-resonance (already at head), then set Render DATABASE_URL to that same URL.
  B) Copy DATABASE_URL from Render Environment, run this script to migrate Render's DB, then verify.
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

API = os.getenv("GATE_A_API", "https://infocord.onrender.com").rstrip("/")
EXPECTED = "e8f4a1b2c3d5"


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


def _fetch_health() -> dict:
    try:
        import httpx
        r = httpx.get(f"{API}/health", timeout=60.0, verify=False)
        return r.json() if r.status_code == 200 else {"status": "error", "http": r.status_code}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def main() -> int:
    os.environ.setdefault("FLASK_APP", "run:app")
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set.")
        print("")
        print("Pick one:")
        print("  1) Render -> infocord -> Environment -> copy DATABASE_URL -> paste in PowerShell")
        print("     Then re-run: python scripts/gate_a_align.py")
        print("  2) Or use your ep-old-resonance Neon URL, migrate, then update Render to match.")
        return 1

    local_host = _host_hint(db_url)
    print(f"Gate A align — local target: {local_host}")
    print("Step 1: migrate...")
    print("-" * 50)

    rc = subprocess.call([sys.executable, str(ROOT / "scripts" / "gate_a_migrate.py")], env=os.environ)
    if rc != 0:
        return rc

    print("-" * 50)
    print(f"Step 2: compare to {API}/health ...")
    body = _fetch_health()
    print(json.dumps(body, indent=2))

    if body.get("db") != "ok":
        print("")
        print("Render cannot reach Postgres. Fix DATABASE_URL on Render, Save, Manual Deploy.")
        return 1

    prod_rev = body.get("migration_revision")
    prod_host = body.get("db_host")
    if body.get("migration_ok") and body.get("schema_ok"):
        print("")
        print("ALIGNED — production matches migrated database.")
        print("Next: python scripts/gate_a_verify.py --full-smoke --insecure")
        return 0

    print("")
    print("NOT ALIGNED — Render is still on a different database or old schema.")
    if prod_host and local_host and prod_host != local_host:
        print(f"  Render db_host:  {prod_host}")
        print(f"  Local db_host:   {local_host}")
        print("")
        print("Fix (recommended): Render -> Environment -> DATABASE_URL")
        print(f"  Set to the SAME Neon URL you just migrated ({local_host})")
        print("  Save -> Manual Deploy -> re-run: python scripts/gate_a_verify.py --insecure")
    elif prod_rev and prod_rev != EXPECTED:
        print(f"  Production revision: {prod_rev!r} (expected {EXPECTED})")
        if local_host:
            print(f"  You migrated: {local_host}")
            print("  Copy that full DATABASE_URL into Render Environment, Save, redeploy.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
