import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'state/app_state.dart';
import 'services/api_service.dart';
import 'services/storage_service.dart';
import 'services/tts_service.dart';
import 'screens/home_screen.dart';
import 'screens/chat_screen.dart';
import 'screens/sar_screen.dart';
import 'screens/settings_screen.dart';
import 'widgets/app_header.dart';
import 'widgets/chat_drawer.dart';
import 'widgets/toast_overlay.dart';

// ---- App color palette ----
class AppColors {
  static const appBackground = Color(0xFFF6FAFD); // Very pale blue-white
  static const sidebar = Color(0xFFFFFFFF); // White
  static const surface = Color(0xFFFFFFFF); // Cards / surfaces
  static const inputBackground = Color(0xFFF8FAFB); // Near-white
  static const hoverSurface = Color(0xFFF0F4F7); // Light blue-grey
  static const activeSurface = Color(0xFFEAEEF1); // Slightly darker grey
  static const primaryText = Color(0xFF171C1F); // Very dark charcoal
  static const secondaryText = Color(0xFF3E494A); // Dark grey
  static const tertiaryText = Color(0xFF6E797A); // Muted grey
  static const subtleBorder = Color(0xFFE5E9EC); // Very light grey
  static const defaultBorder = Color(0xFFD1D5DB); // Light grey
  static const strongBorder = Color(0xFF6E797A); // Grey
  static const primary = Color(0xFF00626A); // Deep teal
  static const primaryContainer = Color(0xFF0E7C86); // Ocean teal
  static const primaryHover = Color(0xFF004F56); // Dark teal
  static const primaryLightBackground = Color(0xFFDDFBFF); // Pale cyan
}

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
        theme: ThemeData.light().copyWith(
          scaffoldBackgroundColor: AppColors.appBackground,
          colorScheme: const ColorScheme.light(
            primary: AppColors.primary,
            surface: AppColors.surface,
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
      backgroundColor: AppColors.hoverSurface,
      body: Center(
        child: Container(
          width: 412,
          height: 892,
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: AppColors.appBackground,
            borderRadius: BorderRadius.circular(28),
            border: Border.all(color: AppColors.defaultBorder, width: 2),
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
            backgroundColor: AppColors.sidebar,
            indicatorColor: AppColors.primaryLightBackground,
            height: 64,
            labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
            destinations: [
              const NavigationDestination(
                icon: Icon(Icons.dashboard_outlined, size: 22),
                selectedIcon: Icon(Icons.dashboard, size: 22, color: AppColors.primary),
                label: 'Overview',
              ),
              const NavigationDestination(
                icon: Icon(Icons.chat_bubble_outline, size: 22),
                selectedIcon: Icon(Icons.chat_bubble, size: 22, color: AppColors.primary),
                label: 'Ask ORCA',
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
                  child: const Icon(Icons.shield, size: 22, color: AppColors.primary),
                ),
                label: 'Authority',
              ),
              const NavigationDestination(
                icon: Icon(Icons.settings_outlined, size: 22),
                selectedIcon: Icon(Icons.settings, size: 22, color: AppColors.primary),
                label: 'System',
              ),
            ],
          ),
        );
      },
    );
  }
}