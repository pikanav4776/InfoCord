/// API and crypto constants — must match web client (templates/index.html).
class AppConfig {
  AppConfig._();

  /// Production Render API. Override for local dev.
  static const String apiBaseUrl = String.fromEnvironment(
    'INFOCORD_API_URL',
    defaultValue: 'https://infocord.onrender.com',
  );

  /// Must match web: const SALT = 'infocord-v1'
  static const String masterKeySalt = 'infocord-v1';

  /// Must match web: PBKDF2_ITERATIONS = 310_000
  static const int pbkdf2Iterations = 310000;

  static const int maxNoteLength = 10000;
}
