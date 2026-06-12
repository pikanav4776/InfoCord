# InfoCord Mobile

Flutter client for InfoCord — matches the web app's E2EE model (PBKDF2 + AES-GCM).

## Prerequisites

- [Flutter SDK](https://docs.flutter.dev/get-started/install) 3.19+
- Xcode (iOS) and/or Android Studio (Android)

## First-time setup

From this directory:

```bash
# Generate android/ and ios/ platform folders if missing
flutter create --project-name infocord_mobile --org com.infocord .

flutter pub get
```

## Configure API URL

Edit `lib/config/app_config.dart`:

- **Production:** `https://infocord.onrender.com`
- **Local:** `http://10.0.2.2:5000` (Android emulator) or `http://127.0.0.1:5000` (iOS simulator)

## Run

```bash
flutter run
```

## Architecture

| Layer | File | Purpose |
|-------|------|---------|
| Crypto | `lib/services/crypto_service.dart` | PBKDF2 (310k) + AES-GCM — matches web |
| Secure storage | `lib/services/secure_key_store.dart` | iOS Keychain / Android Keystore via `flutter_secure_storage` |
| API | `lib/services/api_service.dart` | REST calls to Flask backend |
| Auth state | `lib/providers/auth_provider.dart` | Login, Bearer token, derived key lifecycle |
| UI | `lib/screens/*` | Login, home, note editor, settings |

## Secure key storage

- **Master encryption key** (derived from password): stored in `flutter_secure_storage` after login.
- **Bearer auth token**: stored separately in secure storage for API calls.
- **Password**: never persisted — cleared from memory after key derivation.
- On logout: both token and master key are wiped from secure storage.

## App Store checklist (mobile-specific)

- [ ] Replace placeholder app icon in `assets/icons/`
- [ ] Add privacy policy URL in App Store Connect / Play Console (host at `/legal/privacy`)
- [ ] Implement account deletion UI (calls `DELETE /auth/account`)
- [ ] Integrate Apple Declared Age Range API / Google Play Age Signals API (US state laws)
- [ ] Test on physical devices (secure storage behaves differently on emulator)
