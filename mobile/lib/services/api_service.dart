import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/note.dart';
import 'secure_key_store.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;
  @override
  String toString() => message;
}

class ApiService {
  ApiService({SecureKeyStore? store}) : _store = store ?? SecureKeyStore();

  final SecureKeyStore _store;
  final String baseUrl = AppConfig.apiBaseUrl;

  Future<Map<String, String>> _headers() async {
    final token = await _store.readBearerToken();
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Future<http.Response> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final headers = await _headers();
    switch (method) {
      case 'GET':
        return http.get(uri, headers: headers);
      case 'POST':
        return http.post(uri, headers: headers, body: jsonEncode(body));
      case 'PUT':
        return http.put(uri, headers: headers, body: jsonEncode(body));
      case 'PATCH':
        return http.patch(uri, headers: headers, body: jsonEncode(body));
      case 'DELETE':
        return http.delete(uri, headers: headers, body: body != null ? jsonEncode(body) : null);
      default:
        throw ArgumentError('Unsupported method: $method');
    }
  }

  Map<String, dynamic> _decodeJson(http.Response res) {
    if (res.body.isEmpty) return {};
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> signup({
    required String email,
    required String password,
    required String name,
  }) async {
    final res = await _request('POST', '/auth/signup', body: {
      'email': email,
      'password': password,
      'name': name,
    });
    final data = _decodeJson(res);
    if (res.statusCode != 201) {
      throw ApiException(data['error'] as String? ?? 'Signup failed', statusCode: res.statusCode);
    }
    return data;
  }

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    final res = await _request('POST', '/auth/login', body: {
      'email': email,
      'password': password,
    });
    final data = _decodeJson(res);
    if (res.statusCode != 200) {
      throw ApiException(data['error'] as String? ?? 'Login failed', statusCode: res.statusCode);
    }
    if (data['token'] != null) {
      await _store.saveBearerToken(data['token'] as String);
    }
    return data;
  }

  Future<Map<String, dynamic>?> fetchMe() async {
    final token = await _store.readBearerToken();
    if (token == null) return null;
    final res = await _request('GET', '/auth/me');
    if (res.statusCode == 200) {
      return _decodeJson(res);
    }
    if (res.statusCode == 401) {
      await _store.clearAll();
    }
    return null;
  }

  Future<void> logout() async {
    try {
      await _request('POST', '/auth/logout');
    } finally {
      await _store.clearAll();
    }
  }

  Future<void> deleteAccount(String password) async {
    final res = await _request('DELETE', '/auth/account', body: {'password': password});
    final data = _decodeJson(res);
    if (res.statusCode != 200) {
      throw ApiException(data['error'] as String? ?? 'Delete failed', statusCode: res.statusCode);
    }
    await _store.clearAll();
  }

  Future<List<Note>> fetchNotes() async {
    final res = await _request('GET', '/notes');
    if (res.statusCode != 200) {
      throw ApiException('Failed to load notes', statusCode: res.statusCode);
    }
    final list = jsonDecode(res.body) as List<dynamic>;
    return list.map((e) => Note.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Note> createNote({
    required String title,
    required String ciphertext,
    required String iv,
    required String salt,
    String? categoryId,
  }) async {
    final res = await _request('POST', '/notes', body: {
      'title': title,
      'ciphertext': ciphertext,
      'iv': iv,
      'salt': salt,
      if (categoryId != null) 'category_id': categoryId,
    });
    final data = _decodeJson(res);
    if (res.statusCode != 201) {
      throw ApiException(data['error'] as String? ?? 'Create failed', statusCode: res.statusCode);
    }
    return Note.fromJson(data);
  }

  Future<void> updateNote({
    required String noteId,
    required int version,
    required String title,
    required String ciphertext,
    required String iv,
    required String salt,
  }) async {
    final res = await _request('PUT', '/notes/$noteId', body: {
      'title': title,
      'ciphertext': ciphertext,
      'iv': iv,
      'salt': salt,
      'version': version,
    });
    if (res.statusCode == 409) {
      throw VersionConflictException(_decodeJson(res));
    }
    if (res.statusCode != 200) {
      throw ApiException(_decodeJson(res)['error'] as String? ?? 'Update failed', statusCode: res.statusCode);
    }
  }

  Future<Note> fetchNote(String noteId) async {
    final res = await _request('GET', '/notes/$noteId');
    final data = _decodeJson(res);
    if (res.statusCode != 200) {
      throw ApiException(data['error'] as String? ?? 'Fetch failed', statusCode: res.statusCode);
    }
    return Note.fromJson(data);
  }

  Future<void> archiveNote(String noteId) async {
    final res = await _request('PATCH', '/notes/$noteId/archive');
    if (res.statusCode != 200) {
      throw ApiException(_decodeJson(res)['error'] as String? ?? 'Archive failed', statusCode: res.statusCode);
    }
  }

  Future<void> persistMasterKey(SecretKey key) async {
    final bytes = await key.extractBytes();
    await _store.saveMasterKeyB64(base64.encode(bytes));
  }

  Future<SecretKey?> loadMasterKey() async {
    final b64 = await _store.readMasterKeyB64();
    if (b64 == null) return null;
    return SecretKey(base64.decode(b64));
  }

  Future<bool> hasStoredSession() async {
    final token = await _store.readBearerToken();
    final key = await _store.readMasterKeyB64();
    return token != null && key != null;
  }
}

class VersionConflictException implements Exception {
  VersionConflictException(this.payload);
  final Map<String, dynamic> payload;
  @override
  String toString() => 'Version conflict: ${payload['error']}';
}
