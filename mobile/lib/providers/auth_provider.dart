import 'package:flutter/foundation.dart';

import '../services/api_service.dart';
import '../services/crypto_service.dart';
import '../services/secure_key_store.dart';
import '../models/note.dart';

class AuthProvider extends ChangeNotifier {
  AuthProvider({
    ApiService? api,
    CryptoService? crypto,
    SecureKeyStore? store,
  })  : _api = api ?? ApiService(),
        _crypto = crypto ?? CryptoService(),
        _store = store ?? SecureKeyStore();

  final ApiService _api;
  final CryptoService _crypto;
  final SecureKeyStore _store;

  String? userName;
  String? userEmail;
  bool isLoading = false;
  String? error;

  bool get isLoggedIn => userName != null;

  Future<bool> login(String email, String password) async {
    isLoading = true;
    error = null;
    notifyListeners();
    try {
      final data = await _api.login(email: email, password: password);
      if (data['user'] == null) {
        error = data['error'] as String? ?? 'Login failed';
        return false;
      }
      final key = await _crypto.deriveMasterKey(password);
      await _api.persistMasterKey(key);
      userName = data['user']['name'] as String;
      userEmail = data['user']['email'] as String;
      return true;
    } catch (e) {
      error = e.toString();
      return false;
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    await _api.logout();
    userName = null;
    userEmail = null;
    notifyListeners();
  }

  Future<List<Note>> loadNotesDecrypted() async {
    final key = await _api.loadMasterKey();
    if (key == null) throw Exception('Encryption key missing — sign in again');
    final notes = await _api.fetchNotes();
    for (final note in notes) {
      try {
        note.plaintext = await _crypto.decryptNote(note.ciphertext, note.iv, key);
      } catch (_) {
        note.plaintext = '[decryption failed]';
      }
    }
    return notes;
  }
}
