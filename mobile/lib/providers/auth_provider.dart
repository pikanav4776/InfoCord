import 'package:flutter/foundation.dart';

import '../models/note.dart';
import '../services/api_service.dart';
import '../services/crypto_service.dart';
import '../services/secure_key_store.dart';

class AuthProvider extends ChangeNotifier {
  AuthProvider({
    ApiService? api,
    CryptoService? crypto,
    SecureKeyStore? store,
  })  : _api = api ?? ApiService(store: store),
        _crypto = crypto ?? CryptoService();

  final ApiService _api;
  final CryptoService _crypto;

  ApiService get api => _api;
  CryptoService get crypto => _crypto;

  String? userName;
  String? userEmail;
  bool isLoading = false;
  bool isBootstrapping = true;
  String? error;

  bool get isLoggedIn => userName != null;

  /// Restore bearer token + master key session (B4 cold start).
  Future<void> tryRestoreSession() async {
    isBootstrapping = true;
    notifyListeners();
    try {
      if (!await _api.hasStoredSession()) return;
      final me = await _api.fetchMe();
      if (me == null) return;
      userName = me['name'] as String?;
      userEmail = me['email'] as String?;
    } finally {
      isBootstrapping = false;
      notifyListeners();
    }
  }

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
    } on ApiException catch (e) {
      error = e.message;
      return false;
    } catch (e) {
      error = e.toString();
      return false;
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  /// Signup then login + key derive (signup API does not return a token).
  Future<Map<String, dynamic>?> signup({
    required String email,
    required String password,
    required String name,
  }) async {
    isLoading = true;
    error = null;
    notifyListeners();
    try {
      final data = await _api.signup(email: email, password: password, name: name);
      final loggedIn = await login(email, password);
      if (!loggedIn) return null;
      return data;
    } on ApiException catch (e) {
      error = e.message;
      return null;
    } catch (e) {
      error = e.toString();
      return null;
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

  /// B5 — delete account without calling logout API (token revoked server-side).
  Future<void> deleteAccount(String password) async {
    await _api.deleteAccount(password);
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

  Future<void> archiveNote(String noteId) async {
    await _api.archiveNote(noteId);
  }
}
