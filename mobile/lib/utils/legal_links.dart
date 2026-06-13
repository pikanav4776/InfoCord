import 'package:url_launcher/url_launcher.dart';

import '../config/app_config.dart';

class LegalLinks {
  LegalLinks._();

  static Uri get privacyUri => Uri.parse('${AppConfig.apiBaseUrl}/legal/privacy');
  static Uri get termsUri => Uri.parse('${AppConfig.apiBaseUrl}/legal/terms');

  static Future<void> openPrivacy() => _open(privacyUri);
  static Future<void> openTerms() => _open(termsUri);

  static Future<void> _open(Uri uri) async {
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      throw Exception('Could not open $uri');
    }
  }
}
