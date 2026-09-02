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
      case 2: return 'Operational Picture';
      case 3: return 'Authority • SAR Monitor';
      case 4: return 'System';
      default: return 'ORCA';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, state, _) {
        final chat = state.chats.isNotEmpty ? state.chats.firstWhere((c) => c.id == state.activeChatId, orElse: () => state.chats.first) : null;
        return AppBar(
          backgroundColor: const Color(0xFF0D1F3C),
          elevation: 0,
          leading: Builder(
            builder: (ctx) => IconButton(
              icon: const Icon(Icons.menu, color: Colors.white70),
              onPressed: () => Scaffold.of(ctx).openDrawer(),
            ),
          ),
          title: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(_titleFor(currentIndex, state), style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700), maxLines: 1, overflow: TextOverflow.ellipsis),
              if (currentIndex == 1 && chat != null)
                Text(state.getQueryModeLabel(), style: const TextStyle(color: Color(0xFF00E5FF), fontSize: 10)),
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
              icon: const Icon(Icons.search, color: Colors.white54, size: 20),
              onPressed: () => state.searchModalOpen = !state.searchModalOpen,
            ),
            IconButton(
              icon: Badge(
                isLabelVisible: state.alerts.where((a) => !a.dismissed).isNotEmpty,
                backgroundColor: const Color(0xFFFF1744),
                child: const Icon(Icons.notifications_outlined, color: Colors.white54, size: 20),
              ),
              onPressed: () => onTabChanged(0),
            ),
          ],
        );
      },
    );
  }
}
