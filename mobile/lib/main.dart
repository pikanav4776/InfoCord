import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../services/secure_key_store.dart';
import '../services/api_service.dart';
import '../services/crypto_service.dart';
import 'home_screen.dart';
import 'login_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const InfoCordApp());
}

class InfoCordApp extends StatelessWidget {
  const InfoCordApp({super.key});

  @override
  Widget build(BuildContext context) {
    final store = SecureKeyStore();
    final api = ApiService(store: store);
    final syne = GoogleFonts.syneTextTheme(
      ThemeData.dark().textTheme,
    );
    return ChangeNotifierProvider(
      create: (_) => AuthProvider(api: api, store: store, crypto: CryptoService()),
      child: MaterialApp(
        title: 'InfoCord',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.dark,
          scaffoldBackgroundColor: const Color(0xFF0E0F11),
          colorScheme: const ColorScheme.dark(
            primary: Color(0xFFC8F04A),
            surface: Color(0xFF141518),
          ),
          textTheme: syne,
        ),
        home: const _RootGate(),
      ),
    );
  }
}

class _RootGate extends StatefulWidget {
  const _RootGate();

  @override
  State<_RootGate> createState() => _RootGateState();
}

class _RootGateState extends State<_RootGate> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<AuthProvider>().tryRestoreSession();
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    if (auth.isBootstrapping) {
      return const Scaffold(
        backgroundColor: Color(0xFF0E0F11),
        body: Center(
          child: Image(
            image: AssetImage('assets/icons/splash_logo.png'),
            width: 160,
            height: 160,
            fit: BoxFit.contain,
          ),
        ),
      );
    }
    return auth.isLoggedIn ? const HomeScreen() : const LoginScreen();
  }
}
