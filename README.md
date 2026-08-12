# InfoCord

**Name:** InfoCord (tentative)

**Authors:** Pranav Madan

---

## Context

Modern note-taking and planning applications often store and process sensitive user data in ways that allow service providers to access, analyze, or monetize that information. This creates privacy concerns, especially for users handling personal, academic, or strategic content.

InfoCord is designed as a **privacy-preserving alternative**, where user data is never readable by the server. The system emphasizes **end-to-end encryption (E2EE)**, minimal data collection, and user ownership of information.

---

## Overview

InfoCord is a web-based note organization system with a **Flutter mobile client in progress**, where:

- Users create accounts and organize notes into categories (folders)
- All note content is **encrypted on the client** before being sent to the server
- The server stores only encrypted data (ciphertext, IV, and per-note salt metadata)
- Decryption occurs only on the user's device, in memory during an active session

> **The server acts only as a storage and synchronization layer. The client owns and processes all sensitive data.**

---

## Distribution

**Current focus (June 2026):** Publicize the InfoCord GitHub repository and the hosted web app at `https://infocord.onrender.com`. Formal App Store / Google Play submission is **not planned right now**. The Flutter client and `store/` assets remain **store-ready reference material** — if a native store release becomes necessary later, that will be decided and documented at that time.

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| **Backend** | Flask (Python) — single-app layout in `run.py` (~1,300 lines) |
| **Database** | PostgreSQL (Neon for deployment) |
| **Frontend** | HTML / CSS / JavaScript with Web Crypto API (AES-GCM + PBKDF2) |
| **Mobile** | Flutter (Android/iOS) — code complete, device verification pending; store submission not planned |
| **Auth tokens** | HMAC digests in PostgreSQL `auth_tokens` |
| **Rate limiting** | PostgreSQL `rate_limit_buckets` + `@db_rate_limit` |
| **CI** | GitHub Actions — backend + mobile tests on push/PR to `main` |
| **Deployment** | Gunicorn + Render (`https://infocord.onrender.com`) |

---

## Advantages

- **End-to-End Encryption (E2EE):** Server cannot read user note content
- **Zero-Knowledge Design:** No server-side decryption; API accepts and returns ciphertext only
- **User Data Ownership:** Encryption keys are derived from the user's password and kept in browser memory only
- **Simple, Controlled Architecture:** Avoids overengineering (no CRDTs, no server-side search in MVP)
- **Scalable Foundation:** Backend API and crypto model are ready for mobile and offline expansion

---

## Project Structure

```
InfoCord/
├── run.py                 # Flask app, models, API routes (~1,300 lines)
├── templates/index.html   # Web UI + client-side encryption
├── mobile/                # Flutter app — see mobile/README.md
├── scripts/               # Gate A/C verification and migration helpers
├── store/                 # Deferred store listing assets (reference only)
├── docs/                  # Deployment, CI, production readiness
├── test_auth.py           # Backend test suite (tentatively over 150 tests)
├── migrations/            # Alembic database migrations
└── .github/workflows/ci.yml
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL (local or Neon)
- A `.env` file in the project root (copy from [`.env.example`](.env.example))

**Never commit `.env`.** See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full environment variable reference.

### Install and run locally

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
flask db upgrade
python run.py
```

Open the app at **http://127.0.0.1:5000/app**.

### Run tests

```bash
pytest test_auth.py -v         # backend
cd mobile && flutter test      # mobile
```

Full CI commands, Postgres mimic, and GitHub Actions details: **[docs/CI.md](docs/CI.md)**

---

## API Overview

| Area | Endpoints |
|------|-----------|
| **Health** | `GET /`, `GET /health` |
| **Frontend** | `GET /app` |
| **Auth** | `POST /auth/signup`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/recover`, `POST /auth/change-password`, `POST /auth/recovery-key` |
| **Categories** | `POST/GET /categories`, `PUT /categories/<id>`, `PATCH /categories/<id>/archive` |
| **Notes** | `POST/GET /notes`, `GET/PUT /notes/<id>`, `PATCH /notes/<id>/archive`, `PATCH /notes/<id>/unarchive` |

All note write operations expect `{ ciphertext, iv, salt, ... }` — never plaintext `content`.

---

## Current Summary

| Milestone | Status |
|-----------|--------|
| **MVP (Phases 0–6)** | **Complete** — E2EE note storage, auth, CRUD, version sync, stability, tests |
| **Phase 7 (deployment)** | **Complete** — Render-hosted API with production hardening |
| **Post-MVP** | **Partial** — recovery keys and password change done; mobile code complete (device verification pending; store submission not planned); offline, encrypted search, and AI remain future work |

InfoCord today is a **working privacy-first web note app** with a zero-knowledge backend. The server stores encrypted blobs and metadata; the browser owns encryption, decryption, and search over decrypted content during an active session.

### Key implementation facts

- `test_auth.py` — tentatively over 150 backend tests; 6 Flutter unit tests in `mobile/test/`
- Bearer tokens stored as HMAC digests in PostgreSQL `auth_tokens` (multi-worker-safe)
- Rate limits use PostgreSQL `rate_limit_buckets` via `@db_rate_limit` (not Flask-Limiter)
- Mobile client in `mobile/` is **code complete** — device verification pending; store submission not planned

### Post-MVP highlights

| Concern | Status |
|---------|--------|
| Offline support (IndexedDB + sync queue) | Not started |
| Mobile apps (Flutter) | In progress — code complete, device verification pending; store submission not planned |
| Secure key storage (Keychain/Keystore) | In progress — implemented, device verification pending |
| Recovery keys + password change | Done (web) |
| Version conflict handling | Done (web); offline retry queue future work |
| Encrypted search | Not started — client-side over in-memory decrypted notes |
| Note linking | Done |

---

## Important Disclaimer

Because InfoCord uses end-to-end encryption:

- Passwords are used to derive encryption keys
- **If a password is lost and no recovery key was saved, note content cannot be recovered**
- Recovery keys reset **login credentials only** — they do not decrypt notes unless you still know the old password
- The server cannot access, inspect, or restore user note content

---

## Documentation

| Document | Audience | Contents |
|----------|----------|----------|
| **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** | Project Manager | Render, Neon, env vars, `/health`, Gate A scripts |
| **[docs/CI.md](docs/CI.md)** | Developers | GitHub Actions, local test commands, CI/CD verification |
| **[mobile/README.md](mobile/README.md)** | Mobile dev | Gate B checklist — Flutter setup, E2EE parity, device verification |
| **[docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md)** | Project Manager you | Production readiness, compliance, deferred store path |
| **[store/README.md](store/README.md)** | Future / reference | Deferred store submission package index |
| **[store/listing.md](store/listing.md)** | Future / reference | App Store copy, keywords, age rating (deferred) |
| **[store/accounts.md](store/accounts.md)** | Future / reference | Apple / Google developer account setup (deferred) |
| **[store/screenshots/README.md](store/screenshots/README.md)** | Future / reference | Screenshot capture guide (deferred) |

Development plan PDF and API call graph: `documentation/`
