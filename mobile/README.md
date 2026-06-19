# InfoCord Mobile

Flutter client for InfoCord — matches the web app's E2EE model (PBKDF2 310k + AES-GCM).

**Related:** [Main README](../README.md) · [Deployment / Gate A](../docs/DEPLOYMENT.md) · [CI](../docs/CI.md) · [Production readiness / Gate C (deferred)](../docs/PRODUCTION_READINESS.md#gate-c--store-submission-package-deferred)

> **Prerequisite:** Gate A (backend) must pass before closing Gate B on a real emulator or phone. See [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).

---

## Gate B — Mobile v1 checklist

**Status: Code complete — device verification pending.**

**Strategy:** Flutter app in `mobile/` uses the same E2EE model as web (PBKDF2 310k, salt `infocord-v1`, AES-GCM with auth tag appended to ciphertext for web parity).

| Step | What | Implementation | Verify |
|------|------|----------------|--------|
| **B1** | `flutter create` + build + tests | `mobile/test/` unit tests; run `flutter create` once for `android/`/`ios/` | `flutter test` · `flutter run` |
| **B2** | Sign up, sign in, log out | `signup_screen.dart`, `login_screen.dart`, `AuthProvider.tryRestoreSession()` | Create account → logout → login |
| **B3** | Notes CRUD (E2EE) | Create, read, update, **archive** (web-aligned; `PATCH /notes/{id}/archive`) | + note on device; pull-to-refresh |
| **B4** | Keychain / Keystore | `secure_key_store.dart` — bearer token + master key; password never stored | Kill app → reopen (session restore) |
| **B5** | Account deletion | Settings → password → `AuthProvider.deleteAccount()` (no logout API after delete) | Delete test user on device |
| **B6** | 409 conflict dialog | Keep Mine / Use Server (server path decrypts into editor) | Edit same note on web + mobile |
| **B7** | Privacy + Terms links | `url_launcher` → `/legal/privacy`, `/legal/terms` | Tap links on login + Settings |
| **B8** | Crypto parity with web | `crypto_service.dart` — GCM tag in ciphertext; same plaintext layout (`title\n\nbody`) | Mobile note decrypts on web (same account) |

### B3 — what was partial before mobile v1

| Operation | Before | Now |
|-----------|--------|-----|
| Create / read / update | Dart scaffold only | Full flow wired |
| Delete / archive | Missing | Archive (swipe on home or editor menu) |
| Categories / note links | — | Still **web-only** (post–Gate B) |

---

## B1 — First-time setup (required)

Install the [Flutter SDK](https://docs.flutter.dev/get-started/install/windows/mobile) and add `C:\src\flutter\bin` to your **User** PATH. Restart Cursor after changing PATH.

If `flutter` is not recognized in a terminal, either open a **new** terminal tab or run:

```powershell
..\scripts\flutter.ps1 --version
..\scripts\flutter.ps1 test
```

```powershell
cd c:\InfoCord\mobile
flutter create --project-name infocord_mobile --org com.infocord .
flutter pub get
flutter test
flutter run
```

**API URL:** default production in `lib/config/app_config.dart`. Local dev:

```powershell
flutter run --dart-define=INFOCORD_API_URL=http://10.0.2.2:5000   # Android emulator
flutter run --dart-define=INFOCORD_API_URL=http://127.0.0.1:5000  # iOS simulator
```

**Production (default):** `https://infocord.onrender.com`

---

## B8 — cross-client smoke (manual)

1. Mobile: sign in → create note **"Gate B parity test"**
2. Web: same account at https://infocord.onrender.com/app → note decrypts
3. Web: edit note → mobile pull-to-refresh → see update
4. Optional: trigger 409 (edit in both clients) → test **Keep Mine** / **Use Server** on mobile

---

## Tests (B1)

```bash
flutter test
```

| File | Covers |
|------|--------|
| `test/crypto_service_test.dart` | Encrypt/decrypt round-trip, PBKDF2, GCM tag layout (B8) |
| `test/api_service_test.dart` | `VersionConflictException` (B6) |

**Recommended additions:** widget tests for login/signup; integration test against staging API with `--dart-define`.

CI runs `flutter test` on every push/PR to `main` — see [docs/CI.md](../docs/CI.md).

---

## Configure API URL

Default: `lib/config/app_config.dart` → `INFOCORD_API_URL` compile-time define.

---

## Architecture

| Layer | File | Purpose |
|-------|------|---------|
| Crypto | `lib/services/crypto_service.dart` | PBKDF2 (310k) + AES-GCM — matches web |
| Secure storage | `lib/services/secure_key_store.dart` | iOS Keychain / Android Keystore |
| API | `lib/services/api_service.dart` | REST + Bearer auth |
| Auth | `lib/providers/auth_provider.dart` | Signup, login, restore, delete |
| UI | `lib/screens/*` | Login, signup, home, editor, settings |

Legacy `crypto_auth_service.dart` at repo root is superseded by `mobile/lib/services/crypto_service.dart`.

---

## Secure key storage (B4)

| Secret | Where stored | Never store in |
|--------|--------------|----------------|
| Master encryption key (derived from password) | iOS Keychain / Android Keystore via `flutter_secure_storage` | SharedPreferences, plain files |
| Bearer auth token | Same secure storage | Memory only long-term |
| Password | RAM during login only; cleared after key derivation | Disk, logs, analytics |

- **Cold start:** if token + master key exist → `GET /auth/me` → home without re-login
- **Logout / delete:** `clearAll()` wipes secure storage

Implementation: `secure_key_store.dart` + `auth_provider.dart`.

---

## Development checklist

| Step | Action |
|------|--------|
| 1 | Install Flutter SDK 3.3+ (CI uses 3.29.0) |
| 2 | `flutter create --project-name infocord_mobile --org com.infocord .` |
| 3 | `flutter pub get && flutter test && flutter run` |
| 4 | API URL: `lib/config/app_config.dart` or `--dart-define=INFOCORD_API_URL=...` |
| 5 | B8: create note on mobile → confirm decrypt on web `/app` |
| 6 | B5: account deletion in Settings |
| 7 | Icons: `python ../images/icon_generation.py` then `dart run flutter_launcher_icons` (after `flutter create`) |
| 8 | Build release: `flutter build apk` / `flutter build ios` |

---

## Mobile polish and deferred store readiness

**Store submission is not planned right now.** The items below keep the client store-ready if a native release is approved later.

**Done (good practice / store-ready if needed later):**
- [x] App icon in `assets/icons/` (1024×1024 + adaptive foreground/background)
- [x] Splash screen config (`flutter_native_splash` + in-app bootstrap)
- [x] Privacy + Terms links in app (open browser)
- [x] Account deletion in Settings

**Deferred — not planned for store release:**
- [ ] Device screenshots in `../store/screenshots/` (store submission sizes)
- [ ] Physical device test (secure storage)
- [ ] Apple / Google developer accounts (`../store/accounts.md`)
- [ ] Apple / Google age APIs when shipping to app stores

Deferred store package (Gate C) and production readiness: **[docs/PRODUCTION_READINESS.md](../docs/PRODUCTION_READINESS.md)**  
Store listing reference copy: **[store/listing.md](../store/listing.md)** · Index: **[store/README.md](../store/README.md)**
