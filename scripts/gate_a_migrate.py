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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEBUG_LOG = ROOT / "debug-c450b5.log"


def _debug_log(hypothesis_id: str, message: str, data: dict) -> None:
    # region agent log
    try:
        payload = {
            "sessionId": "c450b5",
            "runId": os.getenv("GATE_A_RUN_ID", "pre-migrate"),
            "hypothesisId": hypothesis_id,
            "location": "scripts/gate_a_migrate.py",
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass
    # endregion


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
        _debug_log("A", "preflight_skipped", {"reason": "no DATABASE_URL"})
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
            except Exception as exc:
                _debug_log("A", "alembic_version_read_failed", {"error": type(exc).__name__})

            note_cols: list[str] = []
            try:
                insp = sa.inspect(db.engine)
                note_cols = [c["name"] for c in insp.get_columns("notes")]
            except Exception as exc:
                _debug_log("B", "notes_columns_read_failed", {"error": type(exc).__name__})

            _debug_log("A", "preflight_state", {
                "alembic_revision": rev,
                "notes_columns": note_cols,
                "version_column_present": "version" in note_cols,
            })
            print(f"Preflight: alembic_version={rev!r}, notes.version present={'version' in note_cols}")
    except Exception as exc:
        _debug_log("C", "preflight_failed", {"error": type(exc).__name__, "detail": str(exc)[:200]})


def main() -> int:
    os.chdir(ROOT)

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        load_dotenv(ROOT / ".flaskenv")
    except ImportError:
        pass

    os.environ.setdefault("FLASK_APP", "run:app")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set.")
        print("  Copy the connection string from Neon → Dashboard → Connect.")
        print("  PowerShell:  $env:DATABASE_URL = \"postgresql://...\"")
        return 1

    host_hint = "neon.tech" if "neon" in db_url else db_url.split("@")[-1][:40]
    print(f"Target database: ...@{host_hint}")

    _preflight_schema()

    print("Running: flask db upgrade")
    print("-" * 50)

    try:
        subprocess.check_call([sys.executable, "-m", "flask", "db", "upgrade"], env=os.environ)
        subprocess.check_call([sys.executable, "-m", "flask", "db", "current"], env=os.environ)
        _debug_log("D", "migrate_success", {"status": "ok"})
    except subprocess.CalledProcessError as exc:
        _debug_log("D", "migrate_failed", {"exit_code": exc.returncode})
        print(f"Migration failed (exit {exc.returncode})")
        return exc.returncode or 1

    print("-" * 50)
    print("A1 complete. Verify with:")
    print("  python scripts/gate_a_verify.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
