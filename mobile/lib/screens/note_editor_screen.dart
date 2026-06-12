import 'dart:convert';
import 'dart:math';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';

import '../config/app_config.dart';
import '../models/note.dart';
import '../services/api_service.dart';
import '../services/crypto_service.dart';

class NoteEditorScreen extends StatefulWidget {
  const NoteEditorScreen({super.key, this.note});

  final Note? note;

  @override
  State<NoteEditorScreen> createState() => _NoteEditorScreenState();
}

class _NoteEditorScreenState extends State<NoteEditorScreen> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  final _api = ApiService();
  final _crypto = CryptoService();
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    if (widget.note != null) {
      _title.text = widget.note!.title;
      _body.text = widget.note!.plaintext ?? '';
    }
  }

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  String _plaintext() {
    final t = _title.text.trim();
    final b = _body.text;
    return t + (b.isNotEmpty ? '\n\n$b' : '');
  }

  Future<void> _save() async {
    final plaintext = _plaintext();
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
      final key = await _api.loadMasterKey();
      if (key == null) throw Exception('Encryption key missing');

      final enc = await _crypto.encryptNote(plaintext, key);
      final salt = base64.encode(List<int>.generate(16, (_) => Random.secure().nextInt(256)));

      if (widget.note == null) {
        await _api.createNote(
          title: _title.text.trim(),
          ciphertext: enc['ciphertext']!,
          iv: enc['iv']!,
          salt: salt,
        );
      } else {
        try {
          await _api.updateNote(
            noteId: widget.note!.id,
            version: widget.note!.version,
            title: _title.text.trim(),
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
                'This note was changed elsewhere. Keep your version or use the server copy?',
              ),
              actions: [
                TextButton(onPressed: () => Navigator.pop(ctx, 'local'), child: const Text('Keep Mine')),
                TextButton(onPressed: () => Navigator.pop(ctx, 'server'), child: const Text('Use Server')),
              ],
            ),
          );
          if (choice == 'server') {
            if (mounted) Navigator.pop(context);
            return;
          }
          if (choice == 'local') {
            final server = await _api.fetchNote(widget.note!.id);
            await _api.updateNote(
              noteId: widget.note!.id,
              version: server.version,
              title: _title.text.trim(),
              ciphertext: enc['ciphertext']!,
              iv: enc['iv']!,
              salt: salt,
            );
          }
        }
      }
      if (mounted) Navigator.pop(context);
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.note == null ? 'New Note' : 'Edit Note'),
        actions: [
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
