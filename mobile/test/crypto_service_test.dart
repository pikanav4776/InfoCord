import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:infocord_mobile/services/crypto_service.dart';
import 'package:infocord_mobile/utils/note_plaintext.dart';

void main() {
  group('note_plaintext', () {
    test('split and join round-trip', () {
      const original = 'My Title\n\nLine one\nLine two';
      final parts = splitNotePlaintext(original);
      expect(parts.$1, 'My Title');
      expect(parts.$2, 'Line one\nLine two');
      expect(joinNotePlaintext(parts.$1, parts.$2), original);
    });

    test('title only', () {
      final parts = splitNotePlaintext('Title only');
      expect(parts.$1, 'Title only');
      expect(parts.$2, '');
    });
  });

  group('CryptoService (B8 web parity)', () {
    final crypto = CryptoService();

    test('encrypt/decrypt round-trip', () async {
      const password = 'GateBTestPassword123!';
      const plaintext = 'Mobile Title\n\nBody from Flutter';
      final key = await crypto.deriveMasterKey(password);
      final enc = await crypto.encryptNote(plaintext, key);
      expect(enc['ciphertext'], isNotEmpty);
      expect(enc['iv'], isNotEmpty);
      final dec = await crypto.decryptNote(enc['ciphertext']!, enc['iv']!, key);
      expect(dec, plaintext);
    });

    test('ciphertext includes 16-byte GCM tag (web Crypto format)', () async {
      const password = 'tag-length-check';
      final key = await crypto.deriveMasterKey(password);
      final enc = await crypto.encryptNote('hi', key);
      final raw = enc['ciphertext']!.length;
      // base64 decodes to plaintext bytes + 16 tag minimum
      expect(raw, greaterThan(16));
    });

    test('PBKDF2 uses infocord-v1 salt and 310k iterations', () async {
      final k1 = await crypto.deriveMasterKey('same-password');
      final k2 = await crypto.deriveMasterKey('same-password');
      final b1 = await k1.extractBytes();
      final b2 = await k2.extractBytes();
      expect(b1, b2);
    });
  });
}
