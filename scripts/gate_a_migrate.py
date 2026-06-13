#!/usr/bin/env python3
"""
Gate A — Step A1: Apply Alembic migrations to the target database.

Usage (Neon production):
  set DATABASE_URL=postgresql://...   # Windows CMD
  $env:DATABASE_URL="postgresql://..."  # PowerShell
  python scripts/gate_a_migrate.py

Requires FLASK_APP (defaults to run:app via .flaskenv).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _preflight_schema() -> None:
    """Log alembic revision + notes columns before upgrade (no secrets)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        load_dotenv(ROOT / ".flaskenv")
    except ImportError:
        pass

    os.environ.setdefault("FLASK_APP", "run:app")
    if not os.getenv("DATABASE_URL"):
        return

    try:
        from run import app, db
        import sqlalchemy as sa

        with app.app_context():
            rev = None
            try:
                rev = db.session.execute(
                    sa.text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar()
            except Exception:
                pass

            note_cols: list[str] = []
            try:
                insp = sa.inspect(db.engine)
                note_cols = [c["name"] for c in insp.get_columns("notes")]
            except Exception:
                pass

            print(f"Preflight: alembic_version={rev!r}, notes.version present={'version' in note_cols}")
    except Exception:
        pass


def main() -> int:
    os.chdir(ROOT)

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        load_dotenv(ROOT / ".flaskenv", override=False)
    except ImportError:
        pass

    os.environ.setdefault("FLASK_APP", "run:app")

    db_url = os.getenv("DATABASE_URL")
    url_file = ROOT / ".gate_a_database_url"
    if not db_url and url_file.is_file():
        db_url = url_file.read_text(encoding="utf-8").strip()
        os.environ["DATABASE_URL"] = db_url
        print(f"Using DATABASE_URL from {url_file.name}")
    if not db_url:
        print("ERROR: DATABASE_URL is not set.")
        print("  Copy FROM Render -> infocord -> Environment -> DATABASE_URL")
        print("  CMD:         set DATABASE_URL=postgresql://...")
        print("  PowerShell:  $env:DATABASE_URL = \"postgresql://...\"  (one line, in quotes)")
        print("  Or paste one line into .gate_a_database_url (gitignored) in repo root")
        return 1

    db_url = _normalize_database_url(db_url)
    os.environ["DATABASE_URL"] = db_url

    host_hint = "neon.tech" if "neon" in db_url else db_url.split("@")[-1][:40]
    print(f"Target database: ...@{host_hint}")

    if "localhost" in db_url or "127.0.0.1" in db_url:
        print("")
        print("WARNING: DATABASE_URL points at localhost.")
        print("  Gate A requires Render's Neon URL — copy from Render -> Environment.")
        print("  Continuing anyway (local dev is OK).\n")

    _preflight_schema()

    print("Running: flask db upgrade")
    print("-" * 50)

    try:
        subprocess.check_call([sys.executable, "-m", "flask", "db", "upgrade"], env=os.environ)
        subprocess.check_call([sys.executable, "-m", "flask", "db", "current"], env=os.environ)
    except subprocess.CalledProcessError as exc:
        print(f"Migration failed (exit {exc.returncode})")
        return exc.returncode or 1

    missing = _postflight_schema()
    print("-" * 50)
    if missing:
        print(f"FAIL: after upgrade, still missing tables: {missing}")
        print("  Check migration logs above for errors.")
        return 1

    print("A1 complete — all Gate A tables present. Verify with:")
    print("  python scripts/gate_a_verify.py --insecure")
    print("")
    print("IMPORTANT: Use the SAME DATABASE_URL as Render -> Environment.")
    print("If /health still shows an old migration_revision, Render points at a different DB.")
    return 0


def _normalize_database_url(url: str) -> str:
    """Strip whitespace/newlines — broken URLs are a common copy-paste failure."""
    cleaned = url.strip().replace("\r", "").replace("\n", "")
    if cleaned != url.strip():
        print("WARNING: DATABASE_URL contained newline(s) — stripped automatically.")
    if ".neon" in cleaned and ".neon.tech" not in cleaned:
        print("WARNING: DATABASE_URL looks truncated (missing .neon.tech).")
        print("  Copy the full one-line string from Neon Connect.")
    return cleaned


def _run_postflight() -> tuple[list[str], dict | None]:
    """Run postflight in a subprocess with PYTHONPATH set (Windows-safe)."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env.setdefault("FLASK_APP", "run:app")
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "gate_a_postflight.py")],
            env=env,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("Postflight check timed out")
        return ["<postflight timeout>"], None

    if proc.returncode != 0 and not proc.stdout.strip():
        print(f"Postflight check failed: {proc.stderr.strip() or 'unknown error'}")
        return ["<postflight error>"], None

    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        print(f"Postflight check failed: {proc.stdout or proc.stderr}")
        return ["<postflight error>"], None

    host = data.get("db_host")
    rev = data.get("revision")
    expected = data.get("expected")
    missing = data.get("tables_missing") or []
    present = data.get("tables_present") or []

    print(f"Postflight: db_host={host!r}, revision={rev!r}, expected={expected!r}")
    print(f"Postflight: tables present={present}")
    if missing:
        print(f"Postflight: tables MISSING={missing}")
    elif host:
        print("")
        print(">>> Copy this DATABASE_URL into Render -> Environment (one line, no breaks):")
        print(f"    Host must be: {host}")
        print("    Then Save -> Manual Deploy -> python scripts\\gate_a_verify.py --insecure")

    return missing, data


def _postflight_schema() -> list[str]:
    """Return missing required tables after upgrade (empty list = success)."""
    missing, _ = _run_postflight()
    return missing


if __name__ == "__main__":
    sys.exit(main())
