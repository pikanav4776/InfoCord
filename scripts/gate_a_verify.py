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

EXPECTED_REVISION = "d7e3f2a1b8c4"
REQUIRED_TABLES = {
    "users",
    "categories",
    "notes",
    "note_links",
    "auth_tokens",
    "rate_limit_buckets",
}

_VERIFY_SSL = True


def _request(method: str, url: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    if _HTTPX:
        verify = certifi.where() if (_VERIFY_SSL and certifi) else False
        with httpx.Client(timeout=30.0, verify=verify) as client:
            resp = client.request(method, url, json=body, headers=hdrs)
            try:
                payload = resp.json() if resp.content else {}
            except json.JSONDecodeError:
                payload = {"error": resp.text}
            return resp.status_code, payload
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload


def check_health(api: str) -> bool:
    print("\n=== A1/A5 — Health + schema (migrations + deploy) ===")
    status, body = _request("GET", f"{api}/health")
    print(f"GET /health → {status}")
    print(json.dumps(body, indent=2))

    ok = True
    if status != 200 or body.get("db") != "ok":
        print("FAIL: database not reachable")
        return False

    rev = body.get("migration_revision")
    if rev is None:
        print("FAIL: alembic_version missing — run: python scripts/gate_a_migrate.py")
        ok = False
    elif rev != EXPECTED_REVISION:
        print(f"FAIL: migration at {rev!r}, expected {EXPECTED_REVISION}")
        print("  Fix: python scripts/gate_a_migrate.py  (with Neon DATABASE_URL)")
        ok = False
    else:
        print(f"OK: migration revision {rev}")

    missing = body.get("schema_tables_missing") or []
    if missing:
        print(f"FAIL: missing tables: {missing}")
        ok = False
    else:
        present = body.get("schema_tables_present") or []
        print(f"OK: all required tables present ({len(present)})")

    if body.get("migration_ok") and body.get("schema_ok"):
        print("OK: A1 schema gate passed")
    return ok


def run_full_smoke(api: str) -> bool:
    print("\n=== A2–A4 — Production smoke (signup → note → bearer → delete) ===")
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

    print(f"InfoCord Gate A verify — {api}")
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
