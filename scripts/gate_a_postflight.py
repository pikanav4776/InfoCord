#!/usr/bin/env python3
"""Post-migrate schema check (subprocess helper — avoids import path issues)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def main() -> int:
    os.environ.setdefault("FLASK_APP", "run:app")
    from run import app, db, REQUIRED_SCHEMA_TABLES, EXPECTED_MIGRATION_REVISION, _db_host_hint
    import sqlalchemy as sa

    with app.app_context():
        rev = db.session.execute(
            sa.text("SELECT version_num FROM alembic_version LIMIT 1")
        ).scalar()
        insp = sa.inspect(db.engine)
        present = set(insp.get_table_names())
        missing = [t for t in REQUIRED_SCHEMA_TABLES if t not in present]
        host = _db_host_hint()
        out = {
            "db_host": host,
            "revision": rev,
            "expected": EXPECTED_MIGRATION_REVISION,
            "tables_present": sorted(t for t in REQUIRED_SCHEMA_TABLES if t in present),
            "tables_missing": missing,
        }
        print(json.dumps(out))
        return 0 if not missing and rev == EXPECTED_MIGRATION_REVISION else 1


if __name__ == "__main__":
    sys.exit(main())
