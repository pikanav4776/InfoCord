import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../models/note.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import '../services/crypto_service.dart';
import '../utils/note_plaintext.dart';

class NoteEditorScreen extends StatefulWidget {
  const NoteEditorScreen({super.key, this.note});

  final Note? note;

  @override
  State<NoteEditorScreen> createState() => _NoteEditorScreenState();
}

class _NoteEditorScreenState extends State<NoteEditorScreen> {
  late final TextEditingController _title;
  late final TextEditingController _body;
  late int _version;
  late String _noteId;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    if (widget.note != null) {
      final parts = splitNotePlaintext(widget.note!.plaintext ?? widget.note!.title);
      _title = TextEditingController(text: parts.$1.isNotEmpty ? parts.$1 : widget.note!.title);
      _body = TextEditingController(text: parts.$2);
      _version = widget.note!.version;
      _noteId = widget.note!.id;
    } else {
      _title = TextEditingController();
      _body = TextEditingController();
      _version = 1;
      _noteId = '';
    }
  }

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  AuthProvider get _auth => context.read<AuthProvider>();

  Future<void> _save() async {
    final plaintext = joinNotePlaintext(_title.text, _body.text);
    if (_title.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Title is required')),
      );
      return;
    }
    if (plaintext.length > AppConfig.maxNoteLength) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Note too long (max 10,000 chars)')),
      );
      return;
    }

    setState(() => _saving = true);
    try {
      final api = _auth.api;
      final crypto = _auth.crypto;
      final key = await api.loadMasterKey();
      if (key == null) throw Exception('Encryption key missing');

      final enc = await crypto.encryptNote(plaintext, key);
      final salt = crypto.randomSaltB64();
      final title = _title.text.trim();

      if (widget.note == null) {
        await api.createNote(
          title: title,
          ciphertext: enc['ciphertext']!,
          iv: enc['iv']!,
          salt: salt,
        );
      } else {
        await _updateWithConflictHandling(
          api: api,
          crypto: crypto,
          key: key,
          title: title,
          enc: enc,
          salt: salt,
        );
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString())),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _updateWithConflictHandling({
    required ApiService api,
    required CryptoService crypto,
    required SecretKey key,
    required String title,
    required Map<String, String> enc,
    required String salt,
  }) async {
    try {
      await api.updateNote(
        noteId: _noteId,
        version: _version,
        title: title,
        ciphertext: enc['ciphertext']!,
        iv: enc['iv']!,
        salt: salt,
      );
    } on VersionConflictException {
      if (!mounted) return;
      final choice = await showDialog<String>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Version Conflict'),
          content: const Text(
            'This note was changed elsewhere. Keep your version or load the server copy?',
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, 'local'), child: const Text('Keep Mine')),
            TextButton(onPressed: () => Navigator.pop(ctx, 'server'), child: const Text('Use Server')),
          ],
        ),
      );
      if (choice == 'server') {
        await _loadServerCopy(api, crypto, key);
        return;
      }
      if (choice == 'local') {
        final server = await api.fetchNote(_noteId);
        _version = server.version;
        await api.updateNote(
          noteId: _noteId,
          version: _version,
          title: title,
          ciphertext: enc['ciphertext']!,
          iv: enc['iv']!,
          salt: salt,
        );
      }
    }
  }

  Future<void> _loadServerCopy(
    ApiService api,
    CryptoService crypto,
    SecretKey key,
  ) async {
    final server = await api.fetchNote(_noteId);
    final pt = await crypto.decryptNote(server.ciphertext, server.iv, key);
    final parts = splitNotePlaintext(pt);
    setState(() {
      _version = server.version;
      _title.text = parts.$1.isNotEmpty ? parts.$1 : server.title;
      _body.text = parts.$2;
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Loaded server version — review and save again if needed')),
      );
    }
  }

  Future<void> _archive() async {
    if (widget.note == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Archive note?'),
        content: const Text('This removes the note from your list (same as web archive).'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Archive')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _auth.archiveNote(_noteId);
    if (mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.note == null ? 'New Note' : 'Edit Note'),
        actions: [
          if (widget.note != null)
            IconButton(
              icon: const Icon(Icons.archive_outlined),
              tooltip: 'Archive',
              onPressed: _saving ? null : _archive,
            ),
          TextButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Save'),
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _title,
              decoration: const InputDecoration(labelText: 'Title'),
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: TextField(
                controller: _body,
                decoration: const InputDecoration(
                  labelText: 'Content',
                  alignLabelWithHint: true,
                ),
                maxLines: null,
                expands: true,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
