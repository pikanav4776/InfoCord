import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../providers/auth_provider.dart';
import '../utils/legal_links.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _deletePassword = TextEditingController();
  bool _deleting = false;

  @override
  void dispose() {
    _deletePassword.dispose();
    super.dispose();
  }

  Future<void> _openLegal(Future<void> Function() open) async {
    try {
      await open();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.toString())));
      }
    }
  }

  Future<void> _deleteAccount() async {
    if (_deletePassword.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Enter your password to confirm deletion')),
      );
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete Account'),
        content: const Text(
          'Permanently delete your account and all encrypted notes? This cannot be undone.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    setState(() => _deleting = true);
    try {
      await context.read<AuthProvider>().deleteAccount(_deletePassword.text);
      if (mounted) {
        Navigator.popUntil(context, (r) => r.isFirst);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString())),
        );
      }
    } finally {
      if (mounted) setState(() => _deleting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            title: const Text('Signed in as'),
            subtitle: Text(auth.userEmail ?? ''),
          ),
          const Divider(),
          const Text('Danger Zone', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          const Text(
            'Delete your account and all data. Required for App Store compliance.',
            style: TextStyle(color: Color(0xFF9A9BA8)),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _deletePassword,
            obscureText: true,
            decoration: const InputDecoration(labelText: 'Confirm password'),
          ),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: _deleting ? null : _deleteAccount,
            style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
            child: _deleting
                ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Delete Account'),
          ),
          const SizedBox(height: 24),
          const Text('Legal', style: TextStyle(fontWeight: FontWeight.bold)),
          ListTile(
            title: const Text('Privacy Policy'),
            subtitle: Text('${AppConfig.apiBaseUrl}/legal/privacy'),
            trailing: const Icon(Icons.open_in_new),
            onTap: () => _openLegal(LegalLinks.openPrivacy),
          ),
          ListTile(
            title: const Text('Terms of Service'),
            subtitle: Text('${AppConfig.apiBaseUrl}/legal/terms'),
            trailing: const Icon(Icons.open_in_new),
            onTap: () => _openLegal(LegalLinks.openTerms),
          ),
        ],
      ),
    );
  }
}
