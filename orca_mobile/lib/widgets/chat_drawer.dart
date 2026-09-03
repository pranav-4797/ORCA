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
          backgroundColor: const Color(0xFFFFFFFF), // Sidebar - White
          child: Column(
            children: [
              DrawerHeader(
                decoration: const BoxDecoration(color: Color(0xFFDDFBFF)), // Primary light background
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(color: const Color(0xFF00626A).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(8)),
                          child: const Icon(Icons.sailing, color: Color(0xFF00626A), size: 20), // Primary/brand
                        ),
                        const SizedBox(width: 10),
                        const Text('ORCA', style: TextStyle(color: Color(0xFF171C1F), fontSize: 18, fontWeight: FontWeight.w800)), // Primary text
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text('${chats.length} mission sessions', style: const TextStyle(color: Color(0xFF3E494A), fontSize: 11)), // Secondary text
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
                        style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF00626A), foregroundColor: Colors.white, padding: const EdgeInsets.symmetric(vertical: 8)), // Primary/brand
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(8),
                child: TextField(
                  style: const TextStyle(color: Color(0xFF171C1F), fontSize: 13), // Primary text
                  decoration: InputDecoration(
                    hintText: 'Search conversations...',
                    hintStyle: const TextStyle(color: Color(0xFF6E797A), fontSize: 12), // Tertiary text
                    prefixIcon: const Icon(Icons.search, color: Color(0xFF6E797A), size: 18), // Tertiary text
                    filled: true,
                    fillColor: const Color(0xFFF8FAFB), // Input background
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                      borderSide: const BorderSide(color: Color(0xFFD1D5DB)), // Default border
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                      borderSide: const BorderSide(color: Color(0xFFD1D5DB)), // Default border
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                      borderSide: const BorderSide(color: Color(0xFF00626A)), // Primary/brand
                    ),
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
                      selectedTileColor: const Color(0xFFDDFBFF), // Primary light background
                      title: Text(
                        c.title,
                        style: TextStyle(
                          color: isActive ? const Color(0xFF00626A) : const Color(0xFF171C1F), // Primary/brand : Primary text
                          fontSize: 13,
                          fontWeight: isActive ? FontWeight.w600 : FontWeight.w400,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Text(
                        c.lastMessagePreview ?? '${c.messageCount} msgs',
                        style: const TextStyle(color: Color(0xFF6E797A), fontSize: 11), // Tertiary text
                        maxLines: 1,
                      ),
                      leading: Icon(
                        c.pinned ? Icons.push_pin : Icons.chat_bubble_outline,
                        size: 16,
                        color: c.pinned ? const Color(0xFF00626A) : const Color(0xFF6E797A), // Primary/brand : Tertiary text
                      ),
                      trailing: PopupMenuButton<String>(
                        icon: const Icon(Icons.more_horiz, size: 16, color: Color(0xFF6E797A)), // Tertiary text
                        onSelected: (v) {
                          if (v == 'pin') state.togglePinChat(c.id);
                          if (v == 'rename') {
                            final ctrl = TextEditingController(text: c.title);
                            showDialog(context: context, builder: (d) => AlertDialog(
                              backgroundColor: const Color(0xFFFFFFFF), // Cards/surfaces
                              title: const Text('Rename', style: TextStyle(color: Color(0xFF171C1F))), // Primary text
                              content: TextField(controller: ctrl, style: const TextStyle(color: Color(0xFF171C1F))), // Primary text
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
              const Divider(color: Color(0xFFE5E9EC), height: 1), // Subtle border
              Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        state.currentUser != null ? (state.currentUser!['displayName'] ?? 'Signed in') : 'Guest • ${state.guestCount}/3',
                        style: const TextStyle(color: Color(0xFF3E494A), fontSize: 11), // Secondary text
                      ),
                    ),
                    if (state.currentUser == null)
                      TextButton(onPressed: () => state.loginMock('Officer'), child: const Text('Sign in', style: TextStyle(color: Color(0xFF00626A), fontSize: 12))) // Primary/brand
                    else
                      TextButton(onPressed: () => state.logout(), child: const Text('Sign out', style: TextStyle(color: Color(0xFF6E797A), fontSize: 11))), // Tertiary text
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