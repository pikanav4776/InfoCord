# CI/CD

**Audience:** Developers  
**Related:** [Deployment](DEPLOYMENT.md) · [Main README](../README.md)

---

## Pipeline overview

CI validates backend and mobile code quality for the public GitHub repository — it is not a store-submission gate.

| Layer | Tool | Trigger | What runs |
|-------|------|---------|-----------|
| **CI** | GitHub Actions | Push or PR to `main` | `pytest test_auth.py` on Postgres 16; `flutter test` in `mobile/` |
| **CD** | Render | Push to `main` (auto-deploy) | `pip install`, `flask db upgrade`, `gunicorn run:app` per [`render.yaml`](../render.yaml) |

Workflow file: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

---

## Local test commands

### Backend (local — SQLite by default)

```bash
pytest test_auth.py -v
```

`test_auth.py` — tentatively over 150 tests covering auth, E2EE payloads, version sync, recovery, and validation.

### Backend (optional — Postgres, mimics CI)

```bash
# set TEST_DATABASE_URI to your local Postgres URL first
pytest test_auth.py -v
```

### Mobile

```bash
cd mobile
flutter pub get
flutter test
```

Six Flutter unit tests in `mobile/test/` (`crypto_service_test.dart`, `api_service_test.dart`).

---

## Verify CI passed

1. Push or open a PR to `main`.
2. GitHub → **Actions** → **CI** → confirm **backend** and **mobile** jobs are green.

---

## Verify deploy succeeded

1. After merge to `main`, open Render → **infocord** → wait for **Live**.
2. `GET https://infocord.onrender.com/health` → `"status": "ok"`, `"db": "ok"`.

For deeper production checks, run Gate A verify — see [DEPLOYMENT.md — Gate A](DEPLOYMENT.md#gate-a--pre-app-backend-checklist-phase-a).

---

## Secrets

`DATABASE_URL`, `FLASK_SECRET_KEY`, and `NOTE_ENCRYPTION_KEY` belong in Render Environment and local `.env` only — copy from [`.env.example`](../.env.example).

---

## Remaining CI/CD gaps

Tracked in [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md):

- [ ] Branch protection requiring CI checks before merge
- [ ] Post-deploy `/health` smoke in CI
- [ ] Browser E2E tests (Playwright/Cypress)
- [ ] Load tests for auth and note endpoints

---

## See also

- [DEPLOYMENT.md](DEPLOYMENT.md) — Render, Neon, Gate A scripts
- [mobile/README.md](../mobile/README.md) — Flutter setup and Gate B verification
