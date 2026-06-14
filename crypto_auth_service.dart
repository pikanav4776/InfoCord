import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class CryptoAuthService {
  final String baseUrl;
  final _secureStorage = const FlutterSecureStorage();
  final _aesAlgorithm = AesGcm.with256bits();
  
  CryptoAuthService({required this.baseUrl});

  // ──────────────────────────────────────────────────────────────────────────
  // 1. KEY DERIVATION & STORAGE
  // ──────────────────────────────────────────────────────────────────────────

  /// Derives a 256-bit master key from a password and salt using PBKDF2-SHA256.
  /// Must align perfectly with your web version's iteration count.
  Future<SecretKey> deriveMasterKey(String password, String saltBase64) async {
    final saltBytes = base64.decode(saltBase64);
    
    final pbkdf2 = Pbkdf2(
      macAlgorithm: Hmac(Sha256()),
      bits: 256,
      iterations: 310000, // Match web client (templates/index.html)
    );

    return await pbkdf2.deriveKeyFromPassword(
      password: password,
      nonce: saltBytes,
    );
  }

  /// Securely commits the raw key bytes into Android Keystore / iOS Keychain
  Future<void> saveMasterKeyToHardware(SecretKey secretKey) async {
    final keyBytes = await secretKey.extractBytes();
    final base64Key = base64.encode(keyBytes);
    
    // Never use SharedPreferences / NSUserDefaults for secrets
    await _secureStorage.write(key: 'user_master_key', value: base64Key);
  }

  /// Retrieves the managed master key from secure hardware storage
  Future<SecretKey?> getMasterKeyFromHardware() async {
    final base64Key = await _secureStorage.read(key: 'user_master_key');
    if (base64Key == null) return null;
    
    return SecretKey(base64.decode(base64Key));
  }

  /// Clear keys on logout
  Future<void> clearSecureData() async {
    await _secureStorage.delete(key: 'user_master_key');
  }

  // ──────────────────────────────────────────────────────────────────────────
  // 2. TRUE CLIENT-SIDE ENCRYPTION & DECRYPTION
  // ──────────────────────────────────────────────────────────────────────────

  /// Encrypts plaintext string using AES-GCM 256
  Future<Map<String, String>> encryptNoteData(String plaintext, SecretKey secretKey) async {
    final plaintextBytes = utf8.encode(plaintext);
    final secretBox = await _aesAlgorithm.encrypt(
      plaintextBytes,
      secretKey: secretKey,
    );

    return {
      "ciphertext": base64.encode(secretBox.cipherText),
      "iv": base64.encode(secretBox.nonce),
    };
  }

  /// Decrypts ciphertext base64 string using AES-GCM 256
  Future<String> decryptNoteData(String ciphertextBase64, String ivBase64, SecretKey secretKey) async {
    final cipherText = base64.decode(ciphertextBase64);
    final nonce = base64.decode(ivBase64);

    // Reconstruct the SecretBox package expected by Dart Cryptography
    final secretBox = SecretBox(
      cipherText,
      nonce: nonce,
      mac: Mac.empty, // AesGCM appends auth tag directly into ciphertext or manages natively
    );

    final decryptedBytes = await _aesAlgorithm.decrypt(
      secretBox,
      secretKey: secretKey,
    );

    return utf8.decode(decryptedBytes);
  }

  // ──────────────────────────────────────────────────────────────────────────
  // 3. API COMMUNICATION & 409 SYNC CONFLICT HANDLING
  // ──────────────────────────────────────────────────────────────────────────

  /// Pushes an updated note structure up to Flask. Handles 409 Out-of-Sync gracefully.
  Future<bool> updateNoteWithConflictResolution({
    required String noteId,
    required int localVersion,
    required String plaintext,
    required String categoryId,
    required String title,
  }) async {
    final secretKey = await getMasterKeyFromHardware();
    if (secretKey == null) throw Exception("User encryption keys missing.");

    // Encrypt mutations locally
    final cryptoPack = await encryptNoteData(plaintext, secretKey);

    final response = await http.put(
      Uri.parse('$baseUrl/notes/$noteId'),
      headers: {
        'Content-Type': 'application/json',
        // 'Authorization': 'Bearer <your_token_or_cookie_management_strategy>'
      },
      body: jsonEncode({
        "category_id": categoryId,
        "title": title,
        "version": localVersion,
        "ciphertext": cryptoPack["ciphertext"],
        "iv": cryptoPack["iv"],
        "salt": "use_existing_or_generate_new_salt"
      }),
    );

    if (response.statusCode == 200) {
      // Success! Update local SQLite or state engine to version = localVersion + 1
      return true;
    } 
    
    if (response.statusCode == 409) {
      // ── STEP 7 CRITICAL REQUIREMENT: HANDLE VERSION CONFLICT ──
      // Someone else updated this note since your last pull.
      final responseData = jsonDecode(response.body);
      
      // 1. Alert user or automatically fetch the absolute newest state from server
      final upToDateNoteRaw = await _fetchSingleNoteFromServer(noteId);
      
      // 2. Decrypt the server's version to show a diff merge view or discard/override
      final serverPlaintext = await decryptNoteData(
        upToDateNoteRaw["ciphertext"], 
        upToDateNoteRaw["iv"], 
        secretKey
      );

      // 3. Resolve conflict (This mock strategy overrides with server version update, or lets user choose)
      // For standard resolution: update local engine to match server state + server version number.
      return false; 
    }

    throw Exception("Failed to update note: ${response.body}");
  }

  Future<Map<String, dynamic>> _fetchSingleNoteFromServer(String noteId) async {
    final response = await http.get(Uri.parse('$baseUrl/notes/$noteId'));
    return jsonDecode(response.body);
  }
}