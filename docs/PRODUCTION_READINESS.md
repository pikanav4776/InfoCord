# Production Readiness

**Audience:** PM / future you  
**Related:** [Deployment](DEPLOYMENT.md) · [CI/CD](CI.md) · [Mobile (Gate B)](../mobile/README.md) · [Store listing](../store/listing.md)

This document tracks what is needed to move InfoCord from a working **web MVP** to a **maintained commercial product** and eventually a **mobile app on Apple App Store / Google Play**. Status reflects the repository as of June 2026.

---

## Current status summary

| Milestone | Overall status |
|-----------|----------------|
| **MVP (Phases 0–6)** | **Complete** — E2EE note storage, auth, CRUD, version sync, stability, tests |
| **MVP Phase 7 (deployment)** | **Complete** — Render-hosted API with production hardening |
| **Post-MVP** | **Partial** — recovery keys and password change done; mobile client code complete (device/store verification pending); offline, encrypted search, and AI remain future work |

---

## README objectives audit

### MVP phases (Phases 0–7)

| Phase | Objective | Met? | Notes |
|-------|-----------|------|-------|
| **0 — Environment** | Python 3.10+, PostgreSQL, Git, venv, dependencies | **Yes** | All items present |
| **1 — Backend foundation** | Flask structure, DB connection, User/Category/Note models, migrations | **Yes** | Alembic migrations through note links |
| **2 — Authentication** | Signup, login, password hashing, email uniqueness, sessions, rate limiting, lockout | **Yes** | Also includes logout, `/auth/me`, Bearer tokens (`auth_tokens` table), recovery endpoints |
| **3 — Core CRUD** | Categories and notes CRUD + archive; validation; local web UI | **Yes** | Notes stored as encrypted payloads from day one |
| **4 — Client-side encryption** | PBKDF2 + AES-GCM in browser; server stores ciphertext/IV/salt only | **Yes** | Implemented in `templates/index.html`; server routes never decrypt |
| **5 — Version sync** | `version` field; server validates on update; client conflict handling | **Done (web)** | 409 conflicts show side-by-side picker. Offline retry queue still future work |
| **6 — Stability** | Error responses, logging, edge cases, health check, tests | **Yes** | `test_auth.py` — tentatively over 150 backend tests; 6 Flutter unit tests. Missing browser E2E, load tests, on-device mobile QA |
| **7 — Deployment** | Render + Neon + HTTPS + secure cookies + env vars | **Yes** | Live API at `https://infocord.onrender.com` |

**MVP verdict:** **Complete for web MVP.** Offline sync queue and "keep both" duplicate flow remain post-MVP.

### Post-MVP objectives

| Objective | Met? | Notes |
|-----------|------|-------|
| Offline support (IndexedDB + sync queue) | **No** | All CRUD requires network |
| Mobile apps (Flutter, Android/iOS) | **Partial** | Code complete in `mobile/`; device testing and store submission pending |
| Secure key storage (Keychain/Keystore) | **Partial** | Implemented in `mobile/lib/services/secure_key_store.dart`; device verification pending |
| Recovery mechanisms | **Yes (web)** | Signup recovery key, `/auth/recover`, `/auth/recovery-key`, settings UI |
| Password change without data loss | **Yes** | `/auth/change-password` + client-side re-encryption batch |
| Improved sync (retry, better conflicts) | **Partial** | Version check only |
| Encrypted search | **No** | Search is client-side over in-memory decrypted notes |
| AI features | **No** | `openai` in `requirements.txt` but unused |
| UX enhancements (sync indicators) | **Partial** | Loading spinners and toasts; no persistent sync status |
| Note linking | **Yes** | `NoteLink` model + UI (beyond original post-MVP list) |

---

## Version sync — what "Partial" means

Each note has a `version` integer. When you save, the client sends the version it last saw. If someone else saved first, the server returns **409 Conflict**.

| Term | Meaning |
|------|---------|
| **409 conflict** | Server version ≠ client version — two edits collided |
| **Merge UI** | Show both versions side-by-side and let the user pick (implemented in web conflict modal) |
| **Retry queue** | Offline edits queued locally; auto-sync when Wi‑Fi returns *(not built yet)* |
| **"Keep both"** | Duplicate the note into two separate notes *(not built)* |

**Recommended roadmap:**

1. **Pre–App Store (online-only):** On 409, show conflict modal — **Keep My Version** or **Use Server Version**. Implemented in `templates/index.html`.
2. **Post–App Store + offline:** When Wi‑Fi returns, detect conflicts, show all conflicting versions, user picks one. Requires IndexedDB sync queue (post-MVP).

---

## App Store & production readiness checklist

### 1. Business readiness

| Item | Verified status | Notes |
|------|-----------------|-------|
| Clear, stable use case | **Agree** | Privacy-preserving encrypted notes for personal/confidential information |
| Defined user base | **Agree (informal)** | Primary persona is privacy-conscious individuals; no formal personas doc |
| Business value validated | **Partial** | Product vision is clear; no revenue model or user-validation metrics |
| Stakeholder sign-off | **Agree (informal)** | Single-developer project |
| Roadmap alignment | **Agree** | README and post-MVP plan reference future RAG and AI work |

**Remaining steps:**
- [ ] Write a one-page product brief (see [outline below](#product-brief--outline))
- [ ] Define monetization (free tier, subscription, one-time purchase)
- [ ] Document long-term maintainer commitment and decision authority

### 2. Technical readiness

| Item | Verified status | Notes |
|------|-----------------|-------|
| Architecture stability | **Partial** | Backend is a single ~1,300-line `run.py` — workable for MVP |
| Scalability | **Mostly agree** | Bearer tokens in PostgreSQL `auth_tokens`; rate limits in `rate_limit_buckets` via `@db_rate_limit` |
| Maintainability | **Partial** | README and inline comments exist; no OpenAPI spec or ADRs |
| Dependencies managed | **Agree** | `DATABASE_URL`, Render deployment, CORS documented; `requirements.txt` pinned |
| Security baseline | **Mostly agree — with caveats** | `@require_login` + per-user row checks; 5 failed logins → 15-min lockout. Note content is E2EE; **email and display name are plaintext PII** on server |
| Testing coverage | **Partially done** | Tentatively over 150 backend tests; 6 Flutter unit tests. **Missing:** browser E2E, load tests, on-device mobile QA |
| CI/CD pipeline | **Partial — CI done** | GitHub Actions on push/PR to `main`. Render auto-deploys. No post-deploy smoke in CI yet |

**Remaining steps:**
- [x] Move Bearer tokens and rate-limit state to PostgreSQL
- [ ] Split `run.py` into modules when team or complexity grows
- [x] Add GitHub Actions: `pytest` + `flutter test`
- [ ] Add branch protection requiring CI checks
- [ ] Add post-deploy `/health` smoke or external uptime monitoring
- [ ] Add E2E tests for login → create note → encrypt → sync flow
- [ ] Load-test auth and note endpoints
- [ ] Remove unused dependencies (`openai`) or document why kept

### 3. Operational readiness

| Item | Verified status | Notes |
|------|-----------------|-------|
| Monitoring & logging | **Partial** | Structured request logging + `X-Request-ID`. **No** uptime monitoring, APM, or Sentry |
| Incident handling plan | **Not started** | No on-call rotation, runbook, or support contact |
| SLA / SLO | **Not started** | No uptime target documented |
| Support model | **Informal only** | No support email, ticket system, or FAQ |
| Backup & disaster recovery | **Partial** | Neon provides managed backups; **no documented restore procedure** |

**Remaining steps:**
- [ ] Set up uptime checks on `GET /health`
- [ ] Add error tracking (Sentry or similar)
- [ ] Write an incident runbook
- [ ] Document Neon backup/restore steps and test a restore once
- [ ] Add a public support contact linked from the app

### 4. Productization

| Item | Verified status | Notes |
|------|-----------------|-------|
| Configuration over hardcoding | **Agree** | `FLASK_SECRET_KEY`, `DATABASE_URL`, `FLASK_ENV`, etc. |
| UI / API consistency | **Agree** | Web at `GET /app`; Flutter UI in `mobile/` — not yet published on stores |

**Remaining steps (web → app store):**
- [x] Flutter mobile app scaffold in `mobile/`
- [x] Align mobile PBKDF2 iterations with web (310,000)
- [x] App icons, splash screens, store screenshots guide, listing copy (`store/`)
- [ ] Apple Developer Program + Google Play Console accounts (`store/accounts.md`)
- [x] Privacy policy URL at `/legal/privacy`
- [x] Terms of service at `/legal/terms`
- [x] Account deletion (`DELETE /auth/account` + Settings UI on web and mobile)

### Summary: what is left before App Store launch

| Priority | Category | Key blockers |
|----------|----------|--------------|
| **P0 — Must have** | Mobile product | Flutter scaffold in `mobile/` — still needs `flutter create`, device testing, store assets |
| **P0 — Must have** | Store requirements | Privacy + terms live; account deletion done; **icons + listing copy done** — screenshots + dev accounts still needed |
| **P0 — Must have** | Production stability | **Done** — Bearer tokens + rate limits in PostgreSQL |
| **P1 — Should have** | Compliance | Privacy policy content, DPDPA (India) + CCPA (US) basics, age APIs for US mobile |
| **P1 — Should have** | Operations | Monitoring, error tracking, incident runbook, backup restore test |
| **P1 — Should have** | CI/CD | Automated tests on every push **done** — branch protection and post-deploy smoke remain |
| **P2 — Nice to have** | MVP polish | Offline sync queue; encrypted search |
| **P2 — Nice to have** | Business | Monetization model, formal product brief |

---

## Gate C — Store submission package

**Status:** Automated assets complete — manual console setup and device screenshots remain.

| Step | What | Status |
|------|------|--------|
| **C1** | Apple Developer + Google Play accounts | Manual — [`store/accounts.md`](../store/accounts.md) |
| **C2** | App icon 1024×1024 + Android adaptive icon | `python images/icon_generation.py` → `mobile/assets/icons/` + `static/icons/` |
| **C3** | Splash screen | `flutter_native_splash` in `mobile/pubspec.yaml`; in-app splash in `main.dart` |
| **C4** | Store screenshots (phone sizes) | Capture guide — [`store/screenshots/README.md`](../store/screenshots/README.md) |
| **C5** | Short + long description, keywords, age rating | [`store/listing.md`](../store/listing.md) |
| **C6** | Privacy policy URL | https://infocord.onrender.com/legal/privacy |

### Icon design

Syne Bold **IC** in white on `#0e0f11`; minimalist eye (ring + pupil) atop the **I**. Web uses Syne via Google Fonts; mobile uses `google_fonts` package.

### Verify Gate C assets

```powershell
cd c:\InfoCord
.venv\Scripts\activate
python scripts/gate_c_status.py --insecure
```

After `flutter create` in `mobile/`:

```bash
cd mobile
flutter pub get
dart run flutter_launcher_icons
dart run flutter_native_splash:create
```

---

## Compliance

| Item | Verified status | Notes |
|------|-----------------|-------|
| Compliance (GDPR, SOC2, HIPAA) | **Partial — needs expansion** | **US:** CCPA/CPRA, COPPA, and **2026 App Store Accountability laws** (TX, UT, LA, etc.) require age signals and parental consent APIs. **India:** DPDPA (2023) applies to Indian users' data. **SOC2/HIPAA:** out of scope unless targeting healthcare/enterprise |
| Data sensitivity (PII, encryption, access control) | **Partial** | Note **content** is E2EE. Server still holds **email, name, session metadata** |
| Licensing / IP | **Not started** | No LICENSE file, third-party attribution, or trademark check on "InfoCord" |
| Vendor lock-in | **Partial** | No proprietary APIs, but **Render + Neon** are operational dependencies |

**Remaining steps:**
- [x] Publish privacy policy at `/legal/privacy`
- [x] Implement account + data deletion (`DELETE /auth/account`)
- [ ] Add age-rating and parental-consent handling when shipping mobile (Apple Declared Age Range API; Google Play Age Signals API)
- [ ] Add `LICENSE` and `THIRD_PARTY_NOTICES` for dependencies
- [ ] Document data-processing agreements with Neon and Render

---

## Product brief — outline

A one-page product brief is best written by you. Use this outline:

1. **One-liner** — What is InfoCord in one sentence?
2. **Problem** — Why do users need encrypted private notes?
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

## Risk & governance

- Full development plan (original format): `documentation/MVP InfoCord Development Plan_README.pdf`
- API call graph: `documentation/run_py_call_graph.svg`

---

## See also

- [DEPLOYMENT.md](DEPLOYMENT.md) — Gate A, Neon, `/health`
- [CI.md](CI.md) — GitHub Actions, local tests
- [mobile/README.md](../mobile/README.md) — Gate B mobile checklist
- [store/listing.md](../store/listing.md) — App Store copy and metadata
