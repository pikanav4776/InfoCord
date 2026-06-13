#!/usr/bin/env python3
"""
Cross-platform local server for InfoCord.

Gunicorn (Render production) requires Unix-only fcntl and cannot run on Windows.
On Windows this script uses Flask's built-in server; on Linux/macOS it delegates
to gunicorn like render.yaml.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        load_dotenv(ROOT / ".flaskenv")
    except ImportError:
        pass

    os.environ.setdefault("FLASK_APP", "run:app")
    port = int(os.getenv("PORT") or "5000")

    if sys.platform == "win32":
        print("Gunicorn cannot run on Windows (fcntl is Unix-only).")
        print("Render uses gunicorn on Linux — that is correct for production.")
        print(f"Starting Flask dev server on http://0.0.0.0:{port} ...")
        print("Press Ctrl+C to stop.")
        from run import app

        debug = os.getenv("FLASK_ENV", "development") != "production"
        app.run(host="0.0.0.0", port=port, debug=debug)
        return 0

    print(f"Starting gunicorn on 0.0.0.0:{port} ...")
    try:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "gunicorn",
                "run:app",
                f"--bind=0.0.0.0:{port}",
            ],
            env=os.environ,
        )
        return 0
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
