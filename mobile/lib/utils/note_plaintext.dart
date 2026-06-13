/// Plaintext layout — must match web `templates/index.html` (title + "\\n\\n" + body).

(String title, String body) splitNotePlaintext(String plaintext) {
  final idx = plaintext.indexOf('\n\n');
  if (idx < 0) {
    return (plaintext.trim(), '');
  }
  return (plaintext.substring(0, idx).trim(), plaintext.substring(idx + 2));
}

String joinNotePlaintext(String title, String body) {
  final t = title.trim();
  final b = body;
  if (b.isEmpty) return t;
  return '$t\n\n$b';
}
