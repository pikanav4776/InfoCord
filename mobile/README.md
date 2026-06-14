# InfoCord Mobile

Flutter client for InfoCord — matches the web app's E2EE model (PBKDF2 310k + AES-GCM).

## Gate B — Mobile v1 checklist

| Step | Feature | Status |
|------|---------|--------|
| **B1** | `flutter create` + build + tests | Run setup below; tests in `test/` |
| **B2** | Sign up, sign in, log out | `signup_screen.dart`, `login_screen.dart`, session restore |
| **B3** | Notes CRUD (E2EE) | Create, read, update, archive (web-aligned delete) |
| **B4** | Keychain / Keystore | `secure_key_store.dart` + cold-start session restore |
| **B5** | Account deletion | Settings → password confirm → `AuthProvider.deleteAccount` |
| **B6** | 409 conflict dialog | Keep Mine / Use Server (loads decrypted server copy) |
| **B7** | Privacy + Terms links | `url_launcher` → production `/legal/*` |
| **B8** | Crypto parity with web | GCM tag appended to ciphertext; see `test/crypto_service_test.dart` |

### B3 — What was partial before

| Operation | Was | Now |
|-----------|-----|-----|
| Create / read / update | Implemented | Unchanged |
| Delete / archive | Missing | Archive via swipe or editor (matches web `PATCH .../archive`) |
| Categories / links | Not in mobile v1 | Still web-only |

### B1 — First-time setup (required)

Install the [Flutter SDK](https://docs.flutter.dev/get-started/install/windows/mobile) and add `C:\src\flutter\bin` to your **User** PATH. Restart Cursor after changing PATH.

If `flutter` is not recognized in a terminal, either open a **new** terminal tab or run:

```powershell
..\scripts\flutter.ps1 --version
..\scripts\flutter.ps1 test
```

```bash
cd mobile
flutter create --project-name infocord_mobile --org com.infocord .
flutter pub get
flutter test
flutter run
```

**Android emulator API URL:** `flutter run --dart-define=INFOCORD_API_URL=http://10.0.2.2:5000`  
**iOS simulator:** `http://127.0.0.1:5000`  
**Production (default):** `https://infocord.onrender.com`

### B8 — Manual cross-client test

1. Mobile: sign in → create note "Gate B parity test"
2. Web: sign in to same account at `/app` → note decrypts
3. Web: edit note → mobile pull-to-refresh → see update
4. Trigger 409 (edit same note in both) → test Keep Mine / Use Server on mobile

### Tests (B1)

```bash
flutter test
```

| File | Covers |
|------|--------|
| `test/crypto_service_test.dart` | PBKDF2 stability, encrypt/decrypt, GCM tag layout (B8) |
| `test/api_service_test.dart` | 409 exception type (B6) |

**Recommended additions:** widget tests for login/signup; integration test against staging API with `--dart-define`.

---

## Gate C — Store submission package

| Step | Feature | Status |
|------|---------|--------|
| **C1** | Developer accounts | Manual — `../store/accounts.md` |
| **C2** | App icon + adaptive layers | `assets/icons/app_icon*.png` (regenerate: `python ../images/icon_generation.py`) |
| **C3** | Splash screen | `flutter_native_splash` + branded bootstrap in `main.dart` |
| **C4** | Screenshots | `../store/screenshots/README.md` |
| **C5** | Listing copy | `../store/listing.md` |
| **C6** | Privacy URL | `https://infocord.onrender.com/legal/privacy` via `LegalLinks` |

After `flutter create`:

```bash
flutter pub get
dart run flutter_launcher_icons
dart run flutter_native_splash:create
```

Verify package: `python ../scripts/gate_c_status.py --insecure`

---

## Configure API URL

Default: `lib/config/app_config.dart` → `INFOCORD_API_URL` compile-time define.

## Architecture

| Layer | File | Purpose |
|-------|------|---------|
| Crypto | `lib/services/crypto_service.dart` | PBKDF2 (310k) + AES-GCM — matches web |
| Secure storage | `lib/services/secure_key_store.dart` | iOS Keychain / Android Keystore |
| API | `lib/services/api_service.dart` | REST + Bearer auth |
| Auth | `lib/providers/auth_provider.dart` | Signup, login, restore, delete |
| UI | `lib/screens/*` | Login, signup, home, editor, settings |

## Secure key storage (B4)

- **Master key** (PBKDF2 from password): secure storage after login
- **Bearer token**: secure storage for API calls
- **Password**: never persisted
- **Cold start:** if token + master key exist → `GET /auth/me` → home without re-login
- **Logout / delete:** `clearAll()` wipes secure storage

## App Store checklist

- [x] App icon in `assets/icons/` (1024×1024 + adaptive foreground/background)
- [x] Splash screen config (`flutter_native_splash` + in-app bootstrap)
- [x] Privacy + Terms links in app (open browser)
- [x] Account deletion in Settings
- [ ] Device screenshots in `../store/screenshots/`
- [ ] Physical device test (secure storage)
- [ ] Apple / Google developer accounts (`../store/accounts.md`)
- [ ] Apple / Google age APIs when shipping stores
