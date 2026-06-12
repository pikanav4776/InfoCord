import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/note.dart';
import 'secure_key_store.dart';

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
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> login({
    required String email,
    required String password,
  }) async {
    final res = await _request('POST', '/auth/login', body: {
      'email': email,
      'password': password,
    });
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode == 200 && data['token'] != null) {
      await _store.saveBearerToken(data['token'] as String);
    }
    return data;
  }

  Future<void> logout() async {
    await _request('POST', '/auth/logout');
    await _store.clearAll();
  }

  Future<void> deleteAccount(String password) async {
    final res = await _request('DELETE', '/auth/account', body: {'password': password});
    if (res.statusCode != 200) {
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      throw Exception(data['error'] ?? 'Delete failed');
    }
    await _store.clearAll();
  }

  Future<List<Note>> fetchNotes() async {
    final res = await _request('GET', '/notes');
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
    return Note.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
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
      throw VersionConflictException(jsonDecode(res.body) as Map<String, dynamic>);
    }
    if (res.statusCode != 200) {
      throw Exception(jsonDecode(res.body)['error'] ?? 'Update failed');
    }
  }

  Future<Note> fetchNote(String noteId) async {
    final res = await _request('GET', '/notes/$noteId');
    return Note.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
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
}

class VersionConflictException implements Exception {
  VersionConflictException(this.payload);
  final Map<String, dynamic> payload;
  @override
  String toString() => 'Version conflict: ${payload['error']}';
}
