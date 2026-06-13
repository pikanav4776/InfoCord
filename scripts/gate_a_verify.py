#!/usr/bin/env python3
"""
Gate A — Verify production backend readiness (A1–A4 via HTTP).

Usage:
  python scripts/gate_a_verify.py
  python scripts/gate_a_verify.py --api https://infocord.onrender.com
  python scripts/gate_a_verify.py --full-smoke   # A2–A4: signup → note → bearer → delete

Windows curl SSL fix not needed — uses Python urllib.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import httpx
    import certifi
    _HTTPX = True
except ImportError:
    _HTTPX = False
    certifi = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPECTED_REVISION = "e8f4a1b2c3d5"
REQUIRED_TABLES = {
    "users",
    "categories",
    "notes",
    "note_links",
    "auth_tokens",
    "rate_limit_buckets",
}

_VERIFY_SSL = True
_HTTP_TIMEOUT = 120.0  # Render free tier cold starts can exceed 30s


def _local_db_host_hint() -> str | None:
    """Non-secret host/db from local DATABASE_URL (for mismatch diagnostics)."""
    raw = os.getenv("DATABASE_URL", "")
    if not raw:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(raw.replace("postgresql+psycopg2://", "postgresql://", 1))
        host = parsed.hostname or ""
        dbname = (parsed.path or "").lstrip("/").split("?")[0] or ""
        return f"{host}/{dbname}" if host else None
    except Exception:
        return None


def _request(method: str, url: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    if _HTTPX:
        verify = certifi.where() if (_VERIFY_SSL and certifi) else False
        with httpx.Client(timeout=_HTTP_TIMEOUT, verify=verify) as client:
            resp = client.request(method, url, json=body, headers=hdrs)
            try:
                payload = resp.json() if resp.content else {}
            except json.JSONDecodeError:
                payload = {"error": resp.text}
            return resp.status_code, payload
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload


def _request_health_with_retry(api: str) -> tuple[int, dict]:
    """GET /health with retry (Render cold start or transient DB probe failure)."""
    url = f"{api}/health"
    last: tuple[int, dict] = (0, {})
    for attempt in range(2):
        try:
            status, body = _request("GET", url)
        except Exception as first_exc:
            if attempt == 0 and _HTTPX and "Timeout" in type(first_exc).__name__:
                _safe_print("  Render cold start — retrying /health in 5s...")
                time.sleep(5)
                continue
            raise
        last = (status, body)
        if attempt == 0 and status == 503 and body.get("db") == "unavailable":
            _safe_print("  Transient DB unavailable — retrying /health in 5s...")
            time.sleep(5)
            continue
        return status, body
    return last


def _safe_print(text: str) -> None:
    """Avoid UnicodeEncodeError on Windows cp1252 consoles."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def check_health(api: str) -> bool:
    _safe_print("\n=== A1/A5 - Health + schema (migrations + deploy) ===")
    try:
        status, body = _request_health_with_retry(api)
    except Exception as exc:
        _safe_print(f"FAIL: /health request error: {exc}")
        _safe_print("  Render may be cold-starting — wait 30s and retry, or wake service in Render dashboard.")
        return False
    _safe_print(f"GET /health -> {status}")
    print(json.dumps(body, indent=2))

    ok = True
    if status != 200 or body.get("db") != "ok":
        _safe_print("FAIL: Render cannot reach Postgres (db unavailable).")
        hint = body.get("db_error_hint")
        err_type = body.get("db_error_type")
        configured = body.get("db_host_configured")
        if configured:
            _safe_print(f"  Render DATABASE_URL host: {configured}")
        if err_type or hint:
            _safe_print(f"  Server error: {err_type or 'unknown'} — {hint or '(no detail)'}")
        _safe_print("  Usually DATABASE_URL on Render is wrong (503 after Save).")
        _safe_print("  Checklist:")
        _safe_print("    - Use Render paste URL from: python scripts\\gate_a_validate_url.py")
        _safe_print("    - Must end with ?sslmode=require (NO channel_binding=require)")
        _safe_print("    - Full URL, not host-only; no quotes; one line")
        _safe_print("    - Push latest run.py (strips channel_binding) then Manual Deploy")
        _safe_print("  Then: Render -> Environment -> DATABASE_URL -> Save -> wait Live")
        local_host = _local_db_host_hint()
        if local_host:
            _safe_print(f"  Your migrated db_host: {local_host}")
        return False

    prod_expected = body.get("migration_expected")
    if prod_expected and prod_expected != EXPECTED_REVISION:
        _safe_print(
            f"NOTE: Render runs old code (server expects {prod_expected!r}, "
            f"verify script expects {EXPECTED_REVISION!r})."
        )
        _safe_print("  Push + Manual Deploy latest commit on Render after fixing DATABASE_URL.")

    rev = body.get("migration_revision")
    missing = body.get("schema_tables_missing") or []

    if rev is None:
        print("FAIL: alembic_version missing — run: python scripts/gate_a_migrate.py")
        ok = False
    elif rev != EXPECTED_REVISION:
        _safe_print(f"FAIL: production DB revision {rev!r}, expected {EXPECTED_REVISION}")
        render_host = body.get("db_host")
        local_host = _local_db_host_hint()
        if render_host and local_host and render_host != local_host:
            _safe_print(f"  Render db_host:  {render_host}")
            _safe_print(f"  Migrated db_host: {local_host}")
            _safe_print("")
            _safe_print("  FIX (pick one):")
            _safe_print("  A) Render -> Environment -> DATABASE_URL = your ep-old-resonance URL -> Save")
            _safe_print("     (already migrated — fastest)")
            _safe_print("  B) Copy DATABASE_URL from Render, run gate_a_migrate.py on that DB instead")
        elif render_host:
            _safe_print(f"  Render db_host: {render_host}")
            _safe_print("  Run: $env:DATABASE_URL = <Render Environment value>; python scripts\\gate_a_migrate.py")
        elif local_host:
            _safe_print(f"  Your migrated db_host: {local_host}")
            _safe_print("  Set Render DATABASE_URL to that exact Neon URL -> Save -> Manual Deploy.")
        ok = False
    else:
        print(f"OK: migration revision {rev}")

    if missing:
        print(f"FAIL: missing tables: {missing}")
        ok = False
    else:
        present = body.get("schema_tables_present") or []
        print(f"OK: all required tables present ({len(present)})")

    schema_ok = not missing and rev == EXPECTED_REVISION
    if schema_ok:
        print("OK: A1 schema gate passed")
        return True

    return ok


def run_full_smoke(api: str) -> bool:
    _safe_print("\n=== A2-A4 - Production smoke (signup -> note -> bearer -> delete) ===")
    tag = uuid.uuid4().hex[:8]
    email = f"gate-a-{tag}@example.com"
    password = "GateATest123!"
    name = "Gate A Smoke"

    ok = True

    status, body = _request("POST", f"{api}/auth/signup", {
        "email": email, "password": password, "name": name,
    })
    print(f"POST /auth/signup → {status}")
    if status != 201:
        print(f"FAIL: {body}")
        return False
    print(f"OK: user created {email}")

    status, body = _request("POST", f"{api}/auth/login", {
        "email": email, "password": password,
    })
    print(f"POST /auth/login → {status}")
    if status != 200 or "token" not in body:
        print(f"FAIL: {body}")
        return False
    token = body["token"]
    print("OK: login + bearer token received")

    status, me = _request("GET", f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"})
    print(f"GET /auth/me (Bearer) → {status}")
    if status != 200 or me.get("email") != email:
        print(f"FAIL: bearer auth — {me}")
        ok = False
    else:
        print("OK: A4 bearer token authenticates")

    from crypto_utils import encrypt_note
    ct, iv = encrypt_note("Gate A smoke test note")
    salt = base64.b64encode(secrets.token_bytes(16)).decode()

    status, note = _request("POST", f"{api}/notes", {
        "title": "Gate A Test",
        "ciphertext": ct,
        "iv": iv,
        "salt": salt,
    }, headers={"Authorization": f"Bearer {token}"})
    print(f"POST /notes → {status}")
    if status != 201:
        print(f"FAIL: {body}")
        return False
    print("OK: encrypted note created (check Neon notes table)")

    status, body = _request("DELETE", f"{api}/auth/account", {
        "password": password,
    }, headers={"Authorization": f"Bearer {token}"})
    print(f"DELETE /auth/account → {status}")
    if status != 200:
        print(f"FAIL: {body}")
        ok = False
    else:
        print("OK: A3 account deleted")

    status, _ = _request("GET", f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"})
    print(f"GET /auth/me after delete → {status}")
    if status != 401:
        print("FAIL: token should be invalid after account deletion")
        ok = False
    else:
        print("OK: session/token revoked after delete")

    if ok:
        print("\nOK: A2–A4 smoke test passed")
    return ok


def main() -> int:
    global _VERIFY_SSL
    parser = argparse.ArgumentParser(description="Gate A production verification")
    parser.add_argument("--api", default="https://infocord.onrender.com", help="API base URL")
    parser.add_argument("--full-smoke", action="store_true", help="Run A2–A4 signup/note/delete smoke")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS certificate verification (Windows SSL workaround)",
    )
    args = parser.parse_args()
    if args.insecure:
        _VERIFY_SSL = False
    api = args.api.rstrip("/")

    _safe_print(f"InfoCord Gate A verify - {api}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

    health_ok = check_health(api)
    smoke_ok = True
    if args.full_smoke:
        smoke_ok = run_full_smoke(api)

    print("\n" + "=" * 50)
    if health_ok and smoke_ok:
        print("GATE A: PASSED")
        return 0
    print("GATE A: FAILED — see messages above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
