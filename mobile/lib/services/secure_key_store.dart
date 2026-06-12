import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Stores secrets in iOS Keychain / Android Keystore (never SharedPreferences).
class SecureKeyStore {
  static const _tokenKey = 'infocord_bearer_token';
  static const _masterKeyKey = 'infocord_master_key_b64';

  final FlutterSecureStorage _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );

  Future<void> saveBearerToken(String token) =>
      _storage.write(key: _tokenKey, value: token);

  Future<String?> readBearerToken() => _storage.read(key: _tokenKey);

  Future<void> saveMasterKeyB64(String b64) =>
      _storage.write(key: _masterKeyKey, value: b64);

  Future<String?> readMasterKeyB64() => _storage.read(key: _masterKeyKey);

  Future<void> clearAll() async {
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _masterKeyKey);
  }
}
