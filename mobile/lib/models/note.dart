class Note {
  Note({
    required this.id,
    required this.title,
    required this.ciphertext,
    required this.iv,
    required this.salt,
    required this.version,
    this.categoryId,
    this.archived = false,
    this.plaintext,
  });

  final String id;
  final String title;
  final String ciphertext;
  final String iv;
  final String salt;
  final int version;
  final String? categoryId;
  final bool archived;
  String? plaintext;

  factory Note.fromJson(Map<String, dynamic> json) => Note(
        id: json['id'] as String,
        title: (json['title'] as String?) ?? '',
        ciphertext: json['ciphertext'] as String,
        iv: json['iv'] as String,
        salt: json['salt'] as String? ?? '',
        version: json['version'] as int? ?? 1,
        categoryId: json['category_id'] as String?,
        archived: json['archived'] as bool? ?? false,
      );
}
