import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'state/app_state.dart';
import 'services/api_service.dart';
import 'services/storage_service.dart';
import 'services/tts_service.dart';
import 'screens/home_screen.dart';
import 'screens/chat_screen.dart';
import 'screens/map_screen.dart';
import 'screens/sar_screen.dart';
import 'screens/settings_screen.dart';
import 'widgets/app_header.dart';
import 'widgets/chat_drawer.dart';
import 'widgets/toast_overlay.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final storage = StorageService();
  await storage.init();
  final api = ApiService(storage);
  final tts = TtsService();
  final appState = AppState(api: api, storage: storage, tts: tts);
  await appState.init();

  runApp(ORCAApp(appState: appState));
}

class ORCAApp extends StatelessWidget {
  final AppState appState;

  const ORCAApp({super.key, required this.appState});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider.value(
      value: appState,
      child: MaterialApp(
        title: 'ORCA',
        debugShowCheckedModeBanner: false,
        theme: ThemeData.dark().copyWith(
          scaffoldBackgroundColor: const Color(0xFF0A1628),
          colorScheme: const ColorScheme.dark(
            primary: Color(0xFF00E5FF),
            surface: Color(0xFF0D1F3C),
          ),
        ),
        home: kIsWeb ? const _WebPhoneFrame(child: MainShell()) : const MainShell(),
        routes: {
          '/chat': (ctx) => const ChatScreen(),
        },
      ),
    );
  }
}

class _WebPhoneFrame extends StatelessWidget {
  final Widget child;
  const _WebPhoneFrame({required this.child});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF060E1E),
      body: Center(
        child: Container(
          width: 412,
          height: 892,
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: const Color(0xFF0A1628),
            borderRadius: BorderRadius.circular(28),
            border: Border.all(color: const Color(0xFF1A2E4A), width: 2),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.5),
                blurRadius: 32,
                offset: const Offset(0, 12),
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(26),
            child: child,
          ),
        ),
      ),
    );
  }
}

class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _currentIndex = 1; // default to Ask ORCA (chat) as core value

  final _screens = const [
    HomeScreen(), // Overview
    ChatScreen(), // Ask ORCA
    MapScreen(), // Operational picture
    SarScreen(), // Authority / SAR
    SettingsScreen(), // System
  ];

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, appState, _) {
        return Scaffold(
          appBar: AppHeader(
            currentIndex: _currentIndex,
            onTabChanged: (i) => setState(() => _currentIndex = i),
          ),
          drawer: const ChatDrawer(),
          body: Stack(
            children: [
              IndexedStack(
                index: _currentIndex,
                children: _screens,
              ),
              const ToastOverlay(),
            ],
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _currentIndex,
            onDestinationSelected: (i) => setState(() => _currentIndex = i),
            backgroundColor: const Color(0xFF0D1F3C),
            indicatorColor: const Color(0xFF00E5FF).withValues(alpha: 0.15),
            height: 64,
            labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
            destinations: [
              const NavigationDestination(
                icon: Icon(Icons.dashboard_outlined, size: 22),
                selectedIcon: Icon(Icons.dashboard, size: 22, color: Color(0xFF00E5FF)),
                label: 'Overview',
              ),
              const NavigationDestination(
                icon: Icon(Icons.chat_bubble_outline, size: 22),
                selectedIcon: Icon(Icons.chat_bubble, size: 22, color: Color(0xFF00E5FF)),
                label: 'Ask ORCA',
              ),
              const NavigationDestination(
                icon: Icon(Icons.map_outlined, size: 22),
                selectedIcon: Icon(Icons.map, size: 22, color: Color(0xFF00E5FF)),
                label: 'Map',
              ),
              NavigationDestination(
                icon: Badge(
                  isLabelVisible: appState.alerts.where((a) => !a.dismissed).isNotEmpty,
                  backgroundColor: const Color(0xFFFF1744),
                  child: const Icon(Icons.shield_outlined, size: 22),
                ),
                selectedIcon: Badge(
                  isLabelVisible: appState.alerts.where((a) => !a.dismissed).isNotEmpty,
                  backgroundColor: const Color(0xFFFF1744),
                  child: const Icon(Icons.shield, size: 22, color: Color(0xFF00E5FF)),
                ),
                label: 'Authority',
              ),
              const NavigationDestination(
                icon: Icon(Icons.settings_outlined, size: 22),
                selectedIcon: Icon(Icons.settings, size: 22, color: Color(0xFF00E5FF)),
                label: 'System',
              ),
            ],
          ),
        );
      },
    );
  }
}
