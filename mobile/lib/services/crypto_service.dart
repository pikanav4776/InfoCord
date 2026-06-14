import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import '../config/app_config.dart';

/// Client-side encryption — aligned with web Web Crypto API (AES-GCM tag appended to ciphertext).
class CryptoService {
  final _aes = AesGcm.with256Bits();
  static const int _gcmTagLength = 16;

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

  /// Web Crypto `subtle.encrypt` returns ciphertext || auth_tag (16 bytes).
  Future<Map<String, String>> encryptNote(String plaintext, SecretKey key) async {
    final box = await _aes.encrypt(
      utf8.encode(plaintext),
      secretKey: key,
    );
    final combined = Uint8List.fromList([...box.cipherText, ...box.mac.bytes]);
    return {
      'ciphertext': base64.encode(combined),
      'iv': base64.encode(box.nonce),
    };
  }

  Future<String> decryptNote(
    String ciphertextB64,
    String ivB64,
    SecretKey key,
  ) async {
    final raw = base64.decode(ciphertextB64);
    if (raw.length < _gcmTagLength) {
      throw StateError('Ciphertext too short for AES-GCM');
    }
    final ct = raw.sublist(0, raw.length - _gcmTagLength);
    final tag = raw.sublist(raw.length - _gcmTagLength);
    final box = SecretBox(
      ct,
      nonce: base64.decode(ivB64),
      mac: Mac(tag),
    );
    final bytes = await _aes.decrypt(box, secretKey: key);
    return utf8.decode(bytes);
  }

  String randomSaltB64() {
    final salt = Uint8List.fromList(
      List<int>.generate(16, (_) => Random.secure().nextInt(256)),
    );
    return base64.encode(salt);
  }
}
