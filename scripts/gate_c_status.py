#!/usr/bin/env python3
"""
Gate C — Store submission package status.

  python scripts/gate_c_status.py
  python scripts/gate_c_status.py --api https://infocord.onrender.com
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DEFAULT = "https://infocord.onrender.com"
PRIVACY_PATH = "/legal/privacy"

REQUIRED_FILES = [
    "images/app_icon_1024.png",
    "mobile/assets/icons/app_icon.png",
    "mobile/assets/icons/app_icon_foreground.png",
    "mobile/assets/icons/app_icon_background.png",
    "mobile/assets/icons/splash_logo.png",
    "static/icons/icon-512.png",
    "static/icons/icon-192.png",
    "static/icons/apple-touch-icon.png",
    "static/icons/favicon.ico",
    "static/manifest.webmanifest",
    "store/listing.md",
    "store/screenshots/README.md",
]

MANUAL_STEPS = [
    "C1 — Apple Developer Program + Google Play Console accounts (see store/accounts.md)",
    "C4 — Capture phone screenshots into store/screenshots/ (see README there)",
    "C5 — Paste listing copy from store/listing.md into each console",
    "After flutter create: dart run flutter_launcher_icons && dart run flutter_native_splash:create",
]


def _fetch(url: str, insecure: bool) -> tuple[int | None, str]:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "InfoCord-GateC/1.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            body = resp.read(8000).decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate C store package status")
    parser.add_argument("--api", default=API_DEFAULT, help="Production base URL")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verify (Windows)")
    args = parser.parse_args()

    print("Gate C — Store submission package\n")
    ok = True

    print("Assets (C2, C3):")
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if path.exists() and path.stat().st_size > 0:
            print(f"  [ok] {rel}")
        else:
            print(f"  [MISSING] {rel}")
            ok = False

    privacy_url = args.api.rstrip("/") + PRIVACY_PATH
    print(f"\nPrivacy URL (C6): {privacy_url}")
    status, body = _fetch(privacy_url, args.insecure)
    if status == 200 and "Privacy Policy" in body:
        print("  [ok] Returns 200 with privacy policy content")
    else:
        print(f"  [FAIL] status={status}")
        ok = False

    screenshots = list((ROOT / "store" / "screenshots").glob("*.png"))
    print(f"\nScreenshots (C4): {len(screenshots)} PNG(s) in store/screenshots/")
    if not screenshots:
        print("  [pending] Capture device screenshots (see store/screenshots/README.md)")

    print("\nManual steps:")
    for step in MANUAL_STEPS:
        print(f"  • {step}")

    print()
    if ok:
        print("GATE C (automated checks): PASSED — complete manual steps above before submit.")
        return 0
    print("GATE C (automated checks): INCOMPLETE — fix missing items above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
