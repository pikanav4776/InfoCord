import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/note.dart';
import '../providers/auth_provider.dart';
import '../utils/note_plaintext.dart';
import 'note_editor_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<Note> _notes = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    try {
      final notes = await context.read<AuthProvider>().loadNotesDecrypted();
      if (mounted) {
        setState(() => _notes = notes.where((n) => !n.archived).toList());
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString())),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _preview(Note n) {
    final pt = n.plaintext ?? '';
    final parts = splitNotePlaintext(pt);
    final body = parts.$2.trim();
    if (body.isNotEmpty) return body.split('\n').first;
    return parts.$1;
  }

  Future<void> _archiveNote(Note n) async {
    await context.read<AuthProvider>().archiveNote(n.id);
    await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    return Scaffold(
      appBar: AppBar(
        title: Text(auth.userName ?? 'InfoCord'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () => auth.logout(),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () async {
          final saved = await Navigator.push<bool>(
            context,
            MaterialPageRoute(builder: (_) => const NoteEditorScreen()),
          );
          if (saved == true) _refresh();
        },
        child: const Icon(Icons.add),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _notes.isEmpty
              ? const Center(child: Text('No notes yet. Tap + to create one.'))
              : RefreshIndicator(
                  onRefresh: _refresh,
                  child: ListView.builder(
                    itemCount: _notes.length,
                    itemBuilder: (_, i) {
                      final n = _notes[i];
                      return Dismissible(
                        key: ValueKey(n.id),
                        direction: DismissDirection.endToStart,
                        background: Container(
                          color: Colors.red.shade900,
                          alignment: Alignment.centerRight,
                          padding: const EdgeInsets.only(right: 20),
                          child: const Icon(Icons.archive_outlined),
                        ),
                        confirmDismiss: (_) async {
                          return await showDialog<bool>(
                                context: context,
                                builder: (ctx) => AlertDialog(
                                  title: const Text('Archive note?'),
                                  actions: [
                                    TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
                                    TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Archive')),
                                  ],
                                ),
                              ) ??
                              false;
                        },
                        onDismissed: (_) => _archiveNote(n),
                        child: ListTile(
                          title: Text(n.title.isEmpty ? 'Untitled' : n.title),
                          subtitle: Text(
                            _preview(n),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          onTap: () async {
                            final saved = await Navigator.push<bool>(
                              context,
                              MaterialPageRoute(
                                builder: (_) => NoteEditorScreen(note: n),
                              ),
                            );
                            if (saved == true) _refresh();
                          },
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}
