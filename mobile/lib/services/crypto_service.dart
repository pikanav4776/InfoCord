import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import '../config/app_config.dart';

/// Client-side encryption — aligned with web Web Crypto API.
class CryptoService {
  final _aes = AesGcm.with256Bits();

  Future<SecretKey> deriveMasterKey(String password) async {
    final pbkdf2 = Pbkdf2(
      macAlgorithm: Hmac.sha256(),
      bits: 256,
      iterations: AppConfig.pbkdf2Iterations,
    );
    return pbkdf2.deriveKeyFromPassword(
      password: password,
      nonce: utf8.encode(AppConfig.masterKeySalt),
    );
  }

  Future<Map<String, String>> encryptNote(String plaintext, SecretKey key) async {
    final box = await _aes.encrypt(
      utf8.encode(plaintext),
      secretKey: key,
    );
    return {
      'ciphertext': base64.encode(box.cipherText),
      'iv': base64.encode(box.nonce),
    };
  }

  Future<String> decryptNote(
    String ciphertextB64,
    String ivB64,
    SecretKey key,
  ) async {
    final box = SecretBox(
      base64.decode(ciphertextB64),
      nonce: base64.decode(ivB64),
      mac: Mac.empty,
    );
    final bytes = await _aes.decrypt(box, secretKey: key);
    return utf8.decode(bytes);
  }

  String randomSaltB64() {
    final salt = Uint8List.fromList(
      List<int>.generate(16, (_) => DateTime.now().microsecondsSinceEpoch % 256),
    );
    // Use secure random in production — cryptography package helper:
    return base64.encode(salt);
  }
}
