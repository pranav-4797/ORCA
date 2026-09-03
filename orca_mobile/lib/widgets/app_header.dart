import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';

class AppHeader extends StatelessWidget implements PreferredSizeWidget {
  final int currentIndex;
  final ValueChanged<int> onTabChanged;
  const AppHeader({super.key, required this.currentIndex, required this.onTabChanged});

  @override
  Size get preferredSize => const Size.fromHeight(56);

  String _titleFor(int idx, AppState state) {
    switch (idx) {
      case 0: return 'Overview • ${state.userCategory?.roleName ?? 'ORCA'}';
      case 1: {
        if (state.chats.isEmpty) return 'Ask ORCA';
        final c = state.chats.firstWhere((c) => c.id == state.activeChatId, orElse: () => state.chats.first);
        return c.title;
      }
      case 2: return 'Authority • SAR Monitor';
      case 3: return 'System';
      default: return 'ORCA';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, state, _) {
        final chat = state.chats.isNotEmpty ? state.chats.firstWhere((c) => c.id == state.activeChatId, orElse: () => state.chats.first) : null;
        return AppBar(
          backgroundColor: const Color(0xFFFFFFFF), // Sidebar / surface white
          elevation: 0,
          shadowColor: const Color(0xFFE5E9EC), // subtle border, for a hairline shadow if elevation is added later
          leading: Builder(
            builder: (ctx) => IconButton(
              icon: const Icon(Icons.menu, color: Color(0xFF3E494A)), // secondary text
              onPressed: () => Scaffold.of(ctx).openDrawer(),
            ),
          ),
          title: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(_titleFor(currentIndex, state), style: const TextStyle(color: Color(0xFF171C1F), fontSize: 14, fontWeight: FontWeight.w700), maxLines: 1, overflow: TextOverflow.ellipsis), // primary text
              if (currentIndex == 1 && chat != null)
                Text(state.getQueryModeLabel(), style: const TextStyle(color: Color(0xFF00626A), fontSize: 10)), // primary / brand teal
            ],
          ),
          actions: [
            if (state.backendOnline == false)
              Container(
                margin: const EdgeInsets.only(right: 8),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(color: const Color(0xFFFF6D00).withValues(alpha: 0.15), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFFFF6D00).withValues(alpha: 0.3))),
                child: const Text('Offline', style: TextStyle(color: Color(0xFFFF6D00), fontSize: 10, fontWeight: FontWeight.w700)),
              ),
            IconButton(
              icon: const Icon(Icons.search, color: Color(0xFF6E797A), size: 20), // tertiary text
              onPressed: () => state.searchModalOpen = !state.searchModalOpen,
            ),
            IconButton(
              icon: Badge(
                isLabelVisible: state.alerts.where((a) => !a.dismissed).isNotEmpty,
                backgroundColor: const Color(0xFFFF1744),
                child: const Icon(Icons.notifications_outlined, color: Color(0xFF6E797A), size: 20), // tertiary text
              ),
              onPressed: () => onTabChanged(0),
            ),
          ],
        );
      },
    );
  }
}