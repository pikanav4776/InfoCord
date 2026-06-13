# Store screenshots (Gate C4)

Capture from a **physical device or emulator** after `flutter run` (mobile) or browser at `/app` (web marketing optional). Place finished PNGs in this folder using the names below.

## Required sizes

### Apple App Store (iPhone)

| File name | Size | Device reference |
|-----------|------|------------------|
| `ios_6.7_01_login.png` | 1290 × 2796 | iPhone 15 Pro Max / 6.7" |
| `ios_6.7_02_home.png` | 1290 × 2796 | Notes list |
| `ios_6.7_03_editor.png` | 1290 × 2796 | Note editor |
| `ios_6.5_01_login.png` | 1284 × 2778 | iPhone 11 Pro Max / 6.5" (optional if 6.7 set provided) |

Minimum **3 screenshots** per device class. Suggested flow: Login → Home (notes) → Editor → Settings (privacy link visible).

### Google Play (phone)

| File name | Size | Notes |
|-----------|------|-------|
| `android_phone_01_login.png` | 1080 × 1920 min | 16:9 or 9:16 |
| `android_phone_02_home.png` | 1080 × 1920 | Up to 8 screenshots |
| `android_phone_03_editor.png` | 1080 × 1920 | |

Play accepts **320–3840 px** on the short edge; **1080 × 1920** is a safe default.

## Capture tips

1. Use production API or staging with test account — no real secrets in screenshots.
2. Dark theme matches brand (`#0e0f11`); status bar dark.
3. Show **encrypted** value prop: note titles visible, body can be sample text.
4. Include **Settings** shot with Privacy / Terms links for reviewer trust.

## Flutter emulator screenshot

```bash
cd mobile
flutter run -d <device_id>
# In another terminal:
flutter screenshot store/screenshots/android_phone_01_login.png
```

## Web (optional — for website / PR)

Browser full-page or 390 × 844 viewport for consistency with mobile framing.
