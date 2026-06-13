import 'package:flutter_test/flutter_test.dart';
import 'package:infocord_mobile/services/api_service.dart';

void main() {
  test('VersionConflictException carries payload', () {
    final ex = VersionConflictException({'error': 'conflict', 'server_version': 2});
    expect(ex.toString(), contains('conflict'));
    expect(ex.payload['server_version'], 2);
  });
}
