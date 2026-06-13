# Developer accounts (Gate C1)

Register and complete enrollment **before** first store submission.

## Apple Developer Program

1. Go to [developer.apple.com/programs](https://developer.apple.com/programs/)
2. Enroll with Apple ID (Individual or Organization)
3. Fee: **$99 USD / year**
4. After approval: App Store Connect → **My Apps** → **+** → New App
5. Bundle ID: `com.infocord.infocord_mobile` (matches `flutter create --org com.infocord`)

## Google Play Console

1. Go to [play.google.com/console](https://play.google.com/console)
2. Create developer account (one-time **$25 USD** registration)
3. Create app → default language → **Productivity**
4. Package name: `com.infocord.infocord_mobile`
5. Complete **Data safety** form (encryption, account data, deletion — aligns with `/legal/privacy`)

## Checklist

- [ ] Apple Developer Program active
- [ ] Google Play Console developer account active
- [ ] App record created in App Store Connect
- [ ] App record created in Play Console
- [ ] Signing certificates / Play App Signing configured (after `flutter create`)
