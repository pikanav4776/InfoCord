# InfoCord

**Name:** InfoCord (tentative)

**Authors:** Pranav Madan

---

## Context

Modern note-taking and planning applications often store and process sensitive user data in ways that allow service providers to access, analyze, or monetize that information. This creates privacy concerns, especially for users handling personal, academic, or strategic content.

InfoCord is designed as a **privacy-preserving alternative**, where user data is never readable by the server. The system emphasizes **end-to-end encryption (E2EE)**, minimal data collection, and user ownership of information.

---

## Overview of Solution

InfoCord is a web-based (and later mobile) note organization system where:

- Users create accounts and organize notes into categories (folders)
- All note content is **encrypted on the client** before being sent to the server
- The server stores only encrypted data (ciphertext, IV, and per-note salt metadata)
- Decryption occurs only on the user's device, in memory during an active session

The system follows a strict architectural principle:

> **The server acts only as a storage and synchronization layer. The client owns and processes all sensitive data.**

---

## Tech Stack (with justification)

| Layer | Choice | Why |
|-------|--------|-----|
| **Backend** | Flask (Python) | Lightweight and flexible; full control over authentication and API logic; avoids unnecessary abstraction for MVP |
| **Database** | PostgreSQL (Neon for deployment) | Reliable relational DB; strong support for structured data (users, notes, categories); Neon allows scalable, serverless PostgreSQL |
| **Frontend** | HTML / CSS / JavaScript | Minimal overhead for MVP; direct integration with Web Crypto API |
| **Encryption** | Web Crypto API | Built into browsers; supports AES-GCM and PBKDF2; secure and performant without external dependencies |
| **Password hashing** | Werkzeug (`pbkdf2:sha256`) | Secure password storage; industry-standard approach |
| **Local storage (web)** | IndexedDB *(Post-MVP)* | Enables offline functionality; stores encrypted data and sync queue |
| **Migrations** | Flask-Migrate / Alembic | Versioned schema changes |
| **Rate limiting** | Flask-Limiter | Brute-force protection on auth endpoints |
| **Deployment** | Gunicorn + Render | Production WSGI server; hosted API at `https://infocord.onrender.com` |

---

## Advantages

- **End-to-End Encryption (E2EE):** Server cannot read user note content
- **Zero-Knowledge Design:** No server-side decryption; API accepts and returns ciphertext only
- **User Data Ownership:** Encryption keys are derived from the user's password and kept in browser memory only
- **Simple, Controlled Architecture:** Avoids overengineering (no CRDTs, no server-side search in MVP)
- **Scalable Foundation:** Backend API and crypto model are ready for mobile and offline expansion

---

## MVP Development Plan — Status as of June 2026

Each phase below matches the original development plan. **Status** reflects what is implemented in this repository today.

### Phase 0 — Environment Setup

| Item | Status | How it was addressed |
|------|--------|----------------------|
| Python 3.10+ | **Done** | Project runs on modern Python; dependencies pinned in `requirements.txt` |
| PostgreSQL | **Done** | Primary DB via `DATABASE_URL`; local fallback to `infocord_mvp` |
| Git repository | **Done** | Repo initialized with version control |
| Virtual environment | **Done** | Standard `venv` workflow documented below |
| Dependencies (Flask, SQLAlchemy, psycopg2, Werkzeug, Flask-Migrate, etc.) | **Done** | Listed in `requirements.txt` |

---

### Phase 1 — Backend Foundation (Local Development)

| Item | Status | How it was addressed |
|------|--------|----------------------|
| Flask project structure | **Done** | Single-app layout in `run.py` with models, routes, and middleware |
| PostgreSQL connection | **Done** | SQLAlchemy + env-based `DATABASE_URL` normalization |
| Models: User, Category, Note | **Done** | Defined in `run.py`; Alembic migrations under `migrations/versions/` |
| Migrations | **Done** | Initial schema plus follow-ups: `version`, `title`/`salt`, lockout fields, recovery key, note links |

---

### Phase 2 — Authentication (Core MVP Requirement)

| Item | Status | How it was addressed |
|------|--------|----------------------|
| Signup endpoint | **Done** | `POST /auth/signup` — email, password, name validation |
| Login endpoint | **Done** | `POST /auth/login` — session + Bearer token issued |
| Password hashing | **Done** | Werkzeug `generate_password_hash` / `check_password_hash` |
| Email uniqueness | **Done** | Unique constraint on `users.email`; 409 on duplicate |
| HTTP-only cookie sessions | **Done** | Flask session with `SESSION_COOKIE_HTTPONLY`, `SameSite=Lax`, secure flag in production |
| Rate limiting | **Done** | Flask-Limiter on signup, login, recovery (account-based keys, not IP) |
| Temporary account lockout | **Done** | 5 failed attempts → 15-minute lockout (`failed_login_attempts`, `locked_until`) |

**Beyond original MVP scope (also implemented):**

| Item | Status | How it was addressed |
|------|--------|----------------------|
| Bearer token auth | **Done** | Cross-origin / `file://` clients use `Authorization: Bearer` header |
| Logout / session introspection | **Done** | `POST /auth/logout`, `GET /auth/me` |

---

### Phase 3 — Core CRUD Functionality

| Item | Status | How it was addressed |
|------|--------|----------------------|
| Categories: create, read, update, archive | **Done** | `/categories` REST routes |
| Notes: create, read, update, archive | **Done** | `/notes` REST routes; unarchive via `PATCH /notes/<id>/unarchive` |
| Validation (max 10,000 chars, required fields) | **Done** | `MAX_NOTE_LENGTH`, ciphertext/IV/salt required on write |
| End-to-end local functionality | **Done** | Full web UI at `GET /app` (`templates/index.html`) |

**Note:** The plan originally called for plaintext notes first, then encryption in Phase 4. The current codebase stores **encrypted payloads from day one** on the note endpoints (Phase 3 and 4 were merged in practice).

---

### Phase 4 — Client-Side Encryption Integration

| Item | Status | How it was addressed |
|------|--------|----------------------|
| PBKDF2 key derivation (Web Crypto API) | **Done** | 310,000 iterations, SHA-256, in `templates/index.html` |
| Derive encryption key from user password | **Done** | Key derived at login; held in memory as `encKey` only |
| Encrypt note content before sending | **Done** | AES-GCM in browser before `POST`/`PUT` |
| Decrypt notes after retrieval | **Done** | Client decrypts after `GET /notes`; server never decrypts |
| Store ciphertext + IV (+ salt) | **Done** | `notes.content`, `notes.iv`, `notes.salt` columns |

**Supporting files:**

- `templates/index.html` — production web client with inline crypto
- `crypto.js` — standalone client crypto module (same design; can be imported separately)
- `crypto_utils.py` — **legacy server-side encryption helper; not used by current API routes** (server is zero-knowledge for note content)

**User-facing limitation (by design):**

- Password derives the encryption key. **If you forget your password and have no recovery key, note content cannot be recovered.**

---

### Phase 5 — Version-Based Sync System

| Item | Status | How it was addressed |
|------|--------|----------------------|
| `version` field on notes | **Done** | Migration `3a70526dcb7c_add_version_to_notes.py`; default `1`, incremented on update |
| Server validates version on update | **Done** | `PUT /notes/<id>` returns **409** when client version ≠ server version |
| Client handles conflict resolution | **Done (web)** | Conflict modal: side-by-side previews, Keep My Version / Use Server Version. Offline retry queue still future work |

---

### Phase 6 — Stability & Error Handling

| Item | Status | How it was addressed |
|------|--------|----------------------|
| Improved API error responses | **Done** | Consistent JSON errors; global handlers for 400, 404, 405, 429, 500 |
| Server-side logging | **Done** | Structured logging with request IDs (`X-Request-ID` header) |
| Edge cases (failed requests, invalid states) | **Done** | UUID validation, archived-state guards, hex color validation, DB rollback on failure |
| Health check | **Done** | `GET /health` probes database connectivity |
| Test coverage | **Done** | `test_auth.py` — 100+ tests covering auth, E2EE payloads, version sync, recovery, validation |

---

### Phase 7 — Deployment (Optional for MVP Validation)

| Item | Status | How it was addressed |
|------|--------|----------------------|
| Backend → Render | **Done** | Live at `https://infocord.onrender.com`; CORS and frontend API config point to Render |
| Database → Neon | **Assumed deployed** | `DATABASE_URL` env var used in production (Neon-compatible Postgres URL) |
| HTTPS enabled | **Done** | Render provides TLS; `SESSION_COOKIE_SECURE` in production |
| Secure cookies | **Done** | HttpOnly, Secure (prod), SameSite=Lax |
| Environment variables | **Done** | `FLASK_SECRET_KEY`, `DATABASE_URL`, etc. via `.env` / Render config |

---

## Post-MVP Plan — Status as of June 2026

| Concern | Planned scope | Status | How it was addressed / what remains |
|---------|---------------|--------|-------------------------------------|
| **Offline support** | IndexedDB caching; sync queue | **Not started** | App requires network for all CRUD; no IndexedDB or queued operations |
| **Mobile apps (Flutter)** | Android first, iOS second | **Scaffold only** | `crypto_auth_service.dart` defines PBKDF2, AES-GCM, secure storage, and HTTP auth patterns; no full Flutter app in repo |
| **Secure key storage** | iOS Keychain / Android Keystore | **Scaffold only** | Implemented in Dart via `flutter_secure_storage`; not wired to a shipping mobile client |
| **Recovery mechanisms** | Recovery keys (password = encryption key) | **Done (web)** | Signup returns one-time 24-char recovery key; `POST /auth/recover` resets password; `POST /auth/recovery-key` regenerates key; settings UI in frontend |
| **Password change without data loss** | Re-encrypt all notes with new key | **Done** | `POST /auth/change-password` accepts batch of re-encrypted notes; client decrypts with old key and re-encrypts atomically |
| **Improved sync** | Retry logic; better conflict handling | **Partial** | Version conflicts detected and surfaced; no persistent sync queue, idempotency keys, or automatic retry |
| **Encrypted search** | Privacy-preserving full-text search | **Not started** | Current search is **client-side only** over decrypted plaintext in memory (`handleSearch` in frontend) — works online after login, not encrypted-at-rest search |
| **AI features** | Optional, privacy-preserving | **Not started** | `openai` appears in `requirements.txt` but is not integrated into the app |
| **UX enhancements** | Loading states; sync indicators | **Partial** | Loading overlay, button spinners, toast notifications; no persistent sync status indicator |
| **Note linking** | *(not in original post-MVP list)* | **Done** | `NoteLink` model; up to 10 links per note; UI chips and link picker |

---

## Important Disclaimer

Because InfoCord uses end-to-end encryption:

- Passwords are used to derive encryption keys
- **If a password is lost and no recovery key was saved, note content cannot be recovered**
- Recovery keys reset **login credentials only** — they do not decrypt notes unless you still know the old password or have re-encrypted after a password change
- The server cannot access, inspect, or restore user note content

---

## Project Structure

```
InfoCord/
├── run.py                 # Flask app, models, API routes
├── templates/
│   ├── index.html         # Web UI + client-side encryption
│   └── legal/             # Privacy policy & terms (App Store)
├── mobile/                # Flutter app (Android/iOS)
├── crypto.js              # Standalone browser crypto helpers
├── crypto_utils.py        # Legacy server-side crypto (not used by API)
├── crypto_auth_service.dart  # Legacy Dart reference (superseded by mobile/)
├── test_auth.py           # Full test suite
├── migrations/            # Alembic database migrations
├── Procfile               # Render deployment
├── requirements.txt
└── documentation/         # Development plan PDF and diagrams
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL (local or Neon)
- A `.env` file in the project root:

```env
FLASK_SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://user:password@localhost:port_number/infocord_mvp
DB_PORT=port_number
DB_username=your_user
DB_password=your_password
FLASK_ENV=development
```

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
pytest test_auth.py -v
```

Tests use an in-memory SQLite database and do not require PostgreSQL.

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

| Milestone | Overall status |
|-----------|----------------|
| **MVP (Phases 0–6)** | **Complete** — E2EE note storage, auth, CRUD, version sync, stability, tests |
| **MVP Phase 7 (deployment)** | **Complete** — Render-hosted API with production hardening |
| **Post-MVP** | **Partial** — recovery keys and password change done; offline, mobile app, encrypted search, and AI remain future work |

InfoCord today is a **working privacy-first web note app** with a zero-knowledge backend. The server stores encrypted blobs and metadata; the browser owns encryption, decryption, and search over decrypted content during an active session.

---

## README Objectives Audit (June 2026)

This section checks every objective listed in this README against the current codebase.

### MVP phases (Phases 0–7)

| Phase | Objective | Met? | Notes |
|-------|-----------|------|-------|
| **0 — Environment** | Python 3.10+, PostgreSQL, Git, venv, dependencies | **Yes** | All items present |
| **1 — Backend foundation** | Flask structure, DB connection, User/Category/Note models, migrations | **Yes** | Alembic migrations through note links |
| **2 — Authentication** | Signup, login, password hashing, email uniqueness, sessions, rate limiting, lockout | **Yes** | Also includes logout, `/auth/me`, Bearer tokens, recovery endpoints |
| **3 — Core CRUD** | Categories and notes CRUD + archive; validation; local web UI | **Yes** | Notes stored as encrypted payloads from day one |
| **4 — Client-side encryption** | PBKDF2 + AES-GCM in browser; server stores ciphertext/IV/salt only | **Yes** | Implemented in `templates/index.html`; server routes never decrypt |
| **5 — Version sync** | `version` field; server validates on update; client conflict handling | **Done (web)** | 409 conflicts show side-by-side picker: Keep My Version / Use Server Version. Offline retry queue still future work |
| **6 — Stability** | Error responses, logging, edge cases, health check, tests | **Yes** | `test_auth.py` has **100** pytest tests (auth, E2EE payloads, sync, recovery) |
| **7 — Deployment** | Render + Neon + HTTPS + secure cookies + env vars | **Yes** | Live API at `https://infocord.onrender.com`; Neon assumed via `DATABASE_URL` |

**MVP verdict:** **Complete for web MVP.** Offline sync queue and “keep both” duplicate flow remain post-MVP.

### Post-MVP objectives

| Objective | Met? | Notes |
|-----------|------|-------|
| Offline support (IndexedDB + sync queue) | **No** | All CRUD requires network |
| Mobile apps (Flutter, Android/iOS) | **No** | `crypto_auth_service.dart` is a scaffold only; no shipping Flutter project |
| Secure key storage (Keychain/Keystore) | **No** | Defined in Dart scaffold; not wired to a mobile app |
| Recovery mechanisms | **Yes (web)** | Signup recovery key, `/auth/recover`, `/auth/recovery-key`, settings UI |
| Password change without data loss | **Yes** | `/auth/change-password` + client-side re-encryption batch |
| Improved sync (retry, better conflicts) | **Partial** | Version check only |
| Encrypted search | **No** | Search is client-side over in-memory decrypted notes |
| AI features | **No** | `openai` in `requirements.txt` but unused |
| UX enhancements (sync indicators) | **Partial** | Loading spinners and toasts; no persistent sync status |
| Note linking | **Yes** | `NoteLink` model + UI (beyond original post-MVP list) |

**Post-MVP verdict:** Recovery, password change, and note linking are done. **Mobile, offline, encrypted search, and AI remain future work.**

---

## App Store & Production Readiness Checklist

This checklist tracks what is needed to move InfoCord from a working **web MVP** to a **maintained commercial product** and eventually a **mobile app on Apple App Store / Google Play**. Each item includes a verified status against this repository (June 2026).

### 1. Business readiness

| Item | Your assessment | Verified status | Notes |
|------|-----------------|-----------------|-------|
| Clear, stable use case | Yes | **Agree** | Privacy-preserving encrypted notes for personal/confidential information is a real, recurring need |
| Defined user base | Individuals (B2C); possible B2B later | **Agree (informal)** | Primary persona is privacy-conscious individuals; no formal user personas or market sizing doc in repo |
| Business value validated | Intended as commercial product | **Partial** | Product vision is clear; no revenue model, pricing, or user-validation metrics documented |
| Stakeholder sign-off | Developer committed long-term | **Agree (informal)** | Single-developer project; no formal sponsor sign-off document |
| Roadmap alignment | Fits RAG / broader strategy | **Agree** | README and post-MVP plan reference future RAG and AI work |

**Remaining steps**
- [ ] Write a one-page product brief (target user, problem, differentiation vs. Apple Notes / Standard Notes / Obsidian)
- [ ] Define monetization (free tier, subscription, one-time purchase)
- [ ] Document long-term maintainer commitment and decision authority

---

### 2. Technical readiness

| Item | Your assessment | Verified status | Notes |
|------|-----------------|-----------------|-------|
| Architecture stability | Yes — folders per file class | **Partial** | Frontend, migrations, tests, and docs are separated; **backend is a single ~1,000-line `run.py`** — workable for MVP, not yet modularized for a large team |
| Scalability | Under consideration | **Partial — gaps exist** | Bearer tokens stored in **in-memory** `_active_tokens` dict (lost on restart; breaks with multiple Gunicorn workers). Flask-Limiter uses `memory://` storage — same limitation |
| Maintainability | Yes — named modules, documented | **Partial** | README and inline comments exist; no API spec (OpenAPI), no architecture decision records |
| Dependencies managed | Yes — Neon, Render documented | **Agree** | `DATABASE_URL`, Render deployment, CORS origins documented; `requirements.txt` pinned |
| Security baseline | Auth, authz, lockout verified | **Mostly agree — with caveats** | `@require_login` + per-user row checks; 5 failed logins → 15-min lockout (`MAX_FAILED_ATTEMPTS`, `LOCKOUT_DURATION_MINUTES`); rate limiting **enabled only in production** (`FLASK_ENV=production`). Password hashing uses Werkzeug (**PBKDF2-SHA256** by default, not bcrypt). Note content is E2EE; **email and display name are plaintext PII** on server |
| Testing coverage | “Still have to add that” | **Incorrect — partially done** | **`test_auth.py` has 100 API/unit tests** covering auth, E2EE payloads, version sync, recovery, validation. **Missing:** browser E2E tests (Playwright/Cypress), load tests, and mobile client tests |
| CI/CD pipeline | To be considered | **Not started** | No `.github/workflows/` or other automated build/test/deploy pipeline in repo |

**Remaining steps**
- [ ] Move Bearer tokens and rate-limit state to Redis or DB (required before multi-worker production)
- [ ] Split `run.py` into modules (`models.py`, `routes/`, `auth.py`) when team or complexity grows
- [ ] Add GitHub Actions (or similar): lint → `pytest` → deploy on merge
- [ ] Add E2E tests for login → create note → encrypt → sync flow in browser
- [ ] Load-test auth and note endpoints; document expected capacity on Render free/starter tiers
- [ ] Remove unused dependencies (`openai`) or document why they are kept

---

### 3. Operational readiness

| Item | Your assessment | Verified status | Notes |
|------|-----------------|-----------------|-------|
| Monitoring & logging | Logging done; metrics/alerts TBD | **Partial** | Structured request logging + `X-Request-ID` in `run.py`. **No** uptime monitoring, APM, error tracking (Sentry), or alert routing |
| Incident handling plan | Pranav; contact method unclear | **Not started** | No on-call rotation, runbook, or in-app support contact. Email-on-break is not a production incident process |
| SLA / SLO | Not considered | **Not started** | No uptime target (e.g. 99.5%) or latency SLO documented |
| Support model | Pranav | **Informal only** | No support email, ticket system, or FAQ in app or README |
| Backup & disaster recovery | Not formally created | **Partial** | Neon provides managed Postgres backups, but **no documented restore procedure, RTO/RPO, or failover plan** in this repo |

**Remaining steps**
- [ ] Set up uptime checks on `GET /health` (e.g. UptimeRobot, Better Stack, Render health checks)
- [ ] Add error tracking (Sentry or similar) for 500s and unhandled exceptions
- [ ] Write an incident runbook: who is paged, escalation steps, how to roll back Render deploy
- [ ] Document Neon backup/restore steps and test a restore once
- [ ] Add a public support contact (email or form) linked from the app

---

### 4. Productization

| Item | Your assessment | Verified status | Notes |
|------|-----------------|-----------------|-------|
| Configuration over hardcoding | Yes — env vars | **Agree** | `FLASK_SECRET_KEY`, `DATABASE_URL`, `FLASK_ENV`, etc. |
| UI / API consistency | Yes | **Agree (web only)** | Single web entry point at `GET /app`; REST API documented in this README. **No mobile app UI yet** |

**Remaining steps (web → app store)**
- [x] Flutter mobile app scaffold in `mobile/` (run `flutter create` + `flutter pub get` — see `mobile/README.md`)
- [x] Align mobile PBKDF2 iterations with web (310,000)
- [ ] App icons, splash screens, store screenshots, and listing copy
- [ ] Apple Developer Program + Google Play Console accounts
- [x] Privacy policy URL at `/legal/privacy`
- [x] Terms of service at `/legal/terms`
- [x] Account deletion (`DELETE /auth/account` + Settings UI on web and mobile)

---

### Summary: what is left before App Store launch

| Priority | Category | Key blockers |
|----------|----------|--------------|
| **P0 — Must have** | Mobile product | Flutter scaffold in `mobile/` — still needs `flutter create`, device testing, store assets |
| **P0 — Must have** | Store requirements | Privacy + terms live; account deletion done; **icons/screenshots still needed** |
| **P0 — Must have** | Production stability | **Done** — Bearer tokens + rate limits moved to PostgreSQL (`auth_tokens`, `rate_limit_buckets`) |
| **P1 — Should have** | Compliance | Privacy policy content, DPDPA (India) + CCPA (US) basics, age APIs for US mobile |
| **P1 — Should have** | Operations | Monitoring, error tracking, incident runbook, backup restore test |
| **P1 — Should have** | CI/CD | Automated tests on every push |
| **P2 — Nice to have** | MVP polish | Offline sync queue; encrypted search |
| **P2 — Nice to have** | Business | Monetization model, formal product brief |

---

## Version sync — what “Partial” means

Each note has a `version` integer. When you save, the client sends the version it last saw. If someone else (another tab, device, or session) saved first, the server returns **409 Conflict**.

| Term | Meaning |
|------|---------|
| **409 conflict** | Server version ≠ client version — two edits collided |
| **Merge UI** | Show both versions side-by-side and let the user pick (implemented in web conflict modal) |
| **Retry queue** | Offline edits queued locally; auto-sync when Wi‑Fi returns *(not built yet)* |
| **“Keep both”** | Duplicate the note into two separate notes *(not built)* |

**Recommended roadmap (matches your plan):**

1. **Pre–App Store (online-only):** On 409, show conflict modal — **Keep My Version** (override) or **Use Server Version**. Implemented in `templates/index.html`.
2. **Post–App Store + offline:** When Wi‑Fi returns, detect conflicts, show **all conflicting versions**, user picks one. Requires IndexedDB sync queue (post-MVP).

---

## How to verify Neon deployment

Neon is your PostgreSQL host. The Flask app connects via `DATABASE_URL`.

**1. Check Render environment**
- Render dashboard → your InfoCord service → **Environment**
- Confirm `DATABASE_URL` is set and starts with `postgres://` or `postgresql://` pointing at a Neon host (e.g. `*.neon.tech`)

**2. Health check (API)**
```bash
curl https://infocord.onrender.com/health
```
Expect `"database": "ok"`. If `"unavailable"`, the API cannot reach Neon.

**3. Local `.env`**
```env
DATABASE_URL=postgresql://user:pass@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
```

**4. Neon console**
- [console.neon.tech](https://console.neon.tech) → your project → **Tables**
- After signup, you should see `users`, `notes`, `categories`, `auth_tokens`, etc.

**5. Run migrations on production**
```bash
# With DATABASE_URL pointing at Neon
flask db upgrade
```

---

## Flutter mobile app — development checklist

Full scaffold lives in `mobile/`. See `mobile/README.md`.

| Step | Action |
|------|--------|
| 1 | Install Flutter SDK 3.19+ |
| 2 | `cd mobile && flutter create --project-name infocord_mobile --org com.infocord .` |
| 3 | `flutter pub get` |
| 4 | Set API URL in `lib/config/app_config.dart` or `--dart-define=INFOCORD_API_URL=...` |
| 5 | Run on emulator: `flutter run` |
| 6 | Test login → create note → encrypt → sync with web account |
| 7 | Test account deletion in Settings |
| 8 | Replace placeholder icon in `assets/icons/` |
| 9 | Build release: `flutter build apk` / `flutter build ios` |

### Secure key storage (mobile)

| Secret | Where stored | Never store in |
|--------|--------------|----------------|
| Master encryption key (derived from password) | iOS Keychain / Android Keystore via `flutter_secure_storage` | SharedPreferences, plain files |
| Bearer auth token | Same secure storage | Memory only long-term |
| Password | RAM during login only; cleared after key derivation | Disk, logs, analytics |

Implementation: `mobile/lib/services/secure_key_store.dart` + `auth_provider.dart` (derive on login, wipe on logout/delete).

---

## Product brief — what to include

A one-page product brief is **best written by you** — only you know your positioning and goals. Use this outline:

1. **One-liner** — What is InfoCord in one sentence?
2. **Problem** — Why do users need encrypted private notes? (personal planning, research, surprises, etc.)
3. **Target user** — Privacy-conscious individuals; optionally small teams later
4. **Solution** — E2EE notes, zero-knowledge server, categories, recovery keys
5. **Differentiation**

   | Competitor | InfoCord difference |
   |------------|---------------------|
   | Apple Notes | Server can read notes; InfoCord cannot |
   | Standard Notes | Similar E2EE; InfoCord targets simpler MVP + future RAG |
   | Obsidian | Local-first markdown; InfoCord is sync-first encrypted cloud |

6. **Business model** — TBD (free tier / subscription / one-time)
7. **Roadmap** — Mobile → offline sync → RAG/AI (privacy-preserving)
8. **Maintainer** — Who owns long-term decisions (TBD)

---

## Documentation

| Item | Your assessment | Verified status | Notes |
|------|-----------------|-----------------|-------|
| Compliance (GDPR, SOC2, HIPAA) | GDPR N/A for US/India; SOC2/HIPAA out of scope | **Partial — needs expansion** | **US:** CCPA/CPRA (California), COPPA (if minors), and **2026 App Store Accountability laws** (TX, UT, LA, etc.) require age signals and parental consent APIs for many apps — **not just GDPR**. **India:** Digital Personal Data Protection Act (DPDPA, 2023) applies to processing Indian users’ data. **SOC2/HIPAA:** correctly out of scope for a consumer notes app unless you target healthcare/enterprise |
| Data sensitivity (PII, encryption, access control) | Encryption exists | **Partial** | Note **content** is E2EE. Server still holds **email, name, session metadata** — privacy policy and data-retention rules needed |
| Licensing / IP | Not considered | **Not started** | No LICENSE file, third-party attribution, or trademark check on “InfoCord” |
| Vendor lock-in | Low — no custom APIs | **Partial** | No proprietary APIs, but **Render + Neon** are operational dependencies; document migration path |

**Remaining steps**
- [x] Publish privacy policy at `/legal/privacy`
- [x] Implement account + data deletion (`DELETE /auth/account`)
- [ ] Add age-rating and parental-consent handling when shipping mobile (Apple Declared Age Range API; Google Play Age Signals API) for US state compliance
- [ ] Add `LICENSE` and `THIRD_PARTY_NOTICES` for dependencies
- [ ] Document data-processing agreements with Neon and Render

---

### 5. Risk & governance

- Full development plan (original format): `documentation/MVP InfoCord Development Plan_README.pdf`
- API call graph: `documentation/run_py_call_graph.svg`
