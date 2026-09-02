import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';

class ChatDrawer extends StatelessWidget {
  const ChatDrawer({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, state, _) {
        final chats = state.filteredChats;
        return Drawer(
          backgroundColor: const Color(0xFF0D1F3C),
          child: Column(
            children: [
              DrawerHeader(
                decoration: const BoxDecoration(color: Color(0xFF0A1628)),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(color: const Color(0xFF00E5FF).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)),
                          child: const Icon(Icons.sailing, color: Color(0xFF00E5FF), size: 20),
                        ),
                        const SizedBox(width: 10),
                        const Text('ORCA', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800)),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text('${chats.length} mission sessions', style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11)),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        onPressed: () {
                          state.createNewChat(title: 'New Conversation');
                          Navigator.pop(context);
                        },
                        icon: const Icon(Icons.add, size: 16),
                        label: const Text('New Chat', style: TextStyle(fontSize: 13)),
                        style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF00E5FF), foregroundColor: const Color(0xFF0A1628), padding: const EdgeInsets.symmetric(vertical: 8)),
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(8),
                child: TextField(
                  style: const TextStyle(color: Colors.white, fontSize: 13),
                  decoration: InputDecoration(
                    hintText: 'Search conversations...',
                    hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.3), fontSize: 12),
                    prefixIcon: const Icon(Icons.search, color: Colors.white24, size: 18),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.05),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  ),
                  onChanged: (v) {
                    // Simple filter - we just call notify, but for now search via state.searchChats
                    // Store query in a local state? For parity, implement simple
                    if (v.isNotEmpty) {
                      // Show filtered
                    }
                  },
                ),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: chats.length,
                  itemBuilder: (ctx, i) {
                    final c = chats[i];
                    final isActive = c.id == state.activeChatId;
                    return ListTile(
                      selected: isActive,
                      selectedTileColor: const Color(0xFF00E5FF).withValues(alpha: 0.08),
                      title: Text(c.title, style: TextStyle(color: isActive ? const Color(0xFF00E5FF) : Colors.white.withValues(alpha: 0.85), fontSize: 13, fontWeight: isActive ? FontWeight.w600 : FontWeight.w400), maxLines: 1, overflow: TextOverflow.ellipsis),
                      subtitle: Text(c.lastMessagePreview ?? '${c.messageCount} msgs', style: TextStyle(color: Colors.white.withValues(alpha: 0.35), fontSize: 11), maxLines: 1),
                      leading: Icon(c.pinned ? Icons.push_pin : Icons.chat_bubble_outline, size: 16, color: c.pinned ? const Color(0xFF00E5FF) : Colors.white24),
                      trailing: PopupMenuButton<String>(
                        icon: const Icon(Icons.more_horiz, size: 16, color: Colors.white24),
                        onSelected: (v) {
                          if (v == 'pin') state.togglePinChat(c.id);
                          if (v == 'rename') {
                            final ctrl = TextEditingController(text: c.title);
                            showDialog(context: context, builder: (d) => AlertDialog(
                              backgroundColor: const Color(0xFF0D1F3C),
                              title: const Text('Rename', style: TextStyle(color: Colors.white)),
                              content: TextField(controller: ctrl, style: const TextStyle(color: Colors.white)),
                              actions: [
                                TextButton(onPressed: ()=> Navigator.pop(d), child: const Text('Cancel')),
                                TextButton(onPressed: (){ state.renameChat(c.id, ctrl.text); Navigator.pop(d); }, child: const Text('Save')),
                              ],
                            ));
                          }
                          if (v == 'delete') state.deleteChat(c.id);
                        },
                        itemBuilder: (_) => [
                          PopupMenuItem(value: 'pin', child: Text(c.pinned ? 'Unpin' : 'Pin')),
                          const PopupMenuItem(value: 'rename', child: Text('Rename')),
                          const PopupMenuItem(value: 'delete', child: Text('Delete')),
                        ],
                      ),
                      onTap: () {
                        state.selectChat(c.id);
                        Navigator.pop(context);
                      },
                    );
                  },
                ),
              ),
              const Divider(color: Colors.white10, height: 1),
              Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(state.currentUser != null ? (state.currentUser!['displayName'] ?? 'Signed in') : 'Guest • ${state.guestCount}/3', style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11)),
                    ),
                    if (state.currentUser == null)
                      TextButton(onPressed: () => state.loginMock('Officer'), child: const Text('Sign in', style: TextStyle(color: Color(0xFF00E5FF), fontSize: 12)))
                    else
                      TextButton(onPressed: () => state.logout(), child: const Text('Sign out', style: TextStyle(color: Colors.white38, fontSize: 11))),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
