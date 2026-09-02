import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';
import '../l10n/strings.dart';
import '../models/user_category.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  static const _languages = [
    ('en', 'English'),
    ('hi', 'हिन्दी'),
    ('mr', 'मराठी'),
  ];

  static const _consoleTabs = [
    ('overview', 'Overview'),
    ('chat', 'Ask ORCA'),
    ('sar', 'Authority'),
    ('system', 'System'),
  ];

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(builder: (context, state, _){
      final lang = state.language;
      return Scaffold(
        backgroundColor: const Color(0xFF0A1628),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const SizedBox(height: 8),
            // Console view switcher
            _SectionHeader(icon: Icons.dashboard, title: 'Console View'),
            const SizedBox(height: 8),
            Wrap(spacing: 8, children: _consoleTabs.map((t){
              final isSel = state.activeNavTab == t.$1;
              return ChoiceChip(
                label: Text(t.$2, style: TextStyle(color: isSel ? const Color(0xFF0A1628) : Colors.white70, fontSize: 12)),
                selected: isSel,
                selectedColor: const Color(0xFF00E5FF),
                backgroundColor: Colors.white.withValues(alpha: 0.06),
                onSelected: (_) { state.setNavTab(t.$1); },
              );
            }).toList()),
            const SizedBox(height: 20),
            // Role
            _SectionHeader(icon: Icons.badge, title: 'Operational Role'),
            const SizedBox(height: 8),
            if (state.userCategory != null)
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: const Color(0xFF0D1F3C), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFF00E5FF).withValues(alpha: 0.2))),
                child: Row(children: [
                  Text(state.userCategory!.badgeEmoji, style: const TextStyle(fontSize: 24)),
                  const SizedBox(width: 10),
                  Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(state.userCategory!.roleName, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w700)),
                    Text(state.userCategory!.tagline, style: const TextStyle(color: Colors.white54, fontSize: 11)),
                    const SizedBox(height: 4),
                    Text('Vessel: ${state.userCategory!.vesselClass}', style: const TextStyle(color: Color(0xFF00E5FF), fontSize: 10)),
                  ])),
                  TextButton(onPressed: ()=> _showRolePicker(context, state), child: const Text('Switch', style: TextStyle(color: Color(0xFF00E5FF), fontSize: 12))),
                ]),
              )
            else
              ElevatedButton.icon(onPressed: ()=> _showRolePicker(context, state), icon: const Icon(Icons.person_add, size: 16), label: const Text('Select Role'), style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF00E5FF), foregroundColor: const Color(0xFF0A1628))),
            const SizedBox(height: 20),
            // Language (web baseline en/mr/hi)
            _SectionHeader(icon: Icons.language, title: AppStrings.t('language', lang)),
            const SizedBox(height: 8),
            Wrap(spacing: 8, children: _languages.map((l){
              final sel = state.activeLanguage == l.$1;
              return GestureDetector(
                onTap: ()=> state.setLanguage(l.$1),
                child: Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8), decoration: BoxDecoration(color: sel ? const Color(0xFF00E5FF).withValues(alpha: 0.15) : Colors.white.withValues(alpha: 0.05), borderRadius: BorderRadius.circular(20), border: Border.all(color: sel ? const Color(0xFF00E5FF) : Colors.white10)), child: Text(l.$2, style: TextStyle(color: sel ? const Color(0xFF00E5FF) : Colors.white70, fontSize: 13, fontWeight: sel ? FontWeight.w700 : FontWeight.w400))),
              );
            }).toList()),
            const SizedBox(height: 20),
            // Toggles (actually wired now — web bug fixed)
            _SectionHeader(icon: Icons.tune, title: 'Preferences'),
            const SizedBox(height: 8),
            _ToggleTile(title: 'Send on Enter', subtitle: 'Enter sends, Shift+Enter new line', value: state.sendOnEnter, onChanged: (v){ state.sendOnEnter=v; state.showToast(v ? 'Send on Enter enabled' : 'Send on Enter disabled', 'info'); }),
            _ToggleTile(title: 'Audio Feedback', subtitle: 'Speak answers aloud (TTS)', value: state.audioFeedback, onChanged: (v){ state.audioFeedback=v; state.showToast(v ? 'Audio feedback enabled' : 'Audio muted', 'info'); }),
            const SizedBox(height: 20),
            // Fleet & Wind demo controls
            _SectionHeader(icon: Icons.science, title: 'Simulation & Stress Tests'),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: const Color(0xFF0D1F3C), borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.white10)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Fleet Convergence', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                Wrap(spacing: 6, children: [
                  for (final lvl in ['', 'low','medium','high','severe'])
                    ChoiceChip(
                      label: Text(lvl.isEmpty ? 'Normal' : lvl, style: const TextStyle(fontSize: 11)),
                      selected: state.fleetDemoLevel == lvl,
                      onSelected: (_){ state.setFleetDemoLevel(lvl.isEmpty ? null : lvl); state.showToast(lvl.isEmpty ? 'Fleet Normal' : 'Fleet $lvl set — next PFZ query affected', 'info'); },
                    ),
                ]),
                const SizedBox(height: 12),
                const Text('Wind Divergence', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                Wrap(spacing: 6, children: [
                  for (final sc in ['', 'match','moderate','high_divergence'])
                    ChoiceChip(
                      label: Text(sc.isEmpty ? 'Normal' : sc, style: const TextStyle(fontSize: 11)),
                      selected: state.windDemoScenario == sc,
                      onSelected: (_){ state.setWindDemoScenario(sc.isEmpty ? null : sc); state.showToast(sc.isEmpty ? 'Wind Normal' : 'Wind $sc set', 'info'); },
                    ),
                ]),
              ]),
            ),
            const SizedBox(height: 20),
            // Backend URL
            _SectionHeader(icon: Icons.dns, title: AppStrings.t('backendUrl', lang)),
            const SizedBox(height: 8),
            TextField(
              controller: TextEditingController(text: state.baseUrl),
              style: const TextStyle(color: Colors.white, fontSize: 12, fontFamily: 'monospace'),
              decoration: InputDecoration(hintText: 'https://orca-backend-1i5u.onrender.com', hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.2), fontSize: 11), filled: true, fillColor: Colors.white.withValues(alpha: 0.05), border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1))), focusedBorder: const OutlineInputBorder(borderSide: BorderSide(color: Color(0xFF00E5FF)))),
              onSubmitted: (v){ state.baseUrl=v.trim(); state.showToast('Backend URL updated', 'success'); },
            ),
            const SizedBox(height: 16),
            // Auth
            _SectionHeader(icon: Icons.person, title: 'Account'),
            const SizedBox(height: 8),
            if (state.currentUser == null)
              ElevatedButton.icon(onPressed: ()=> state.loginMock('Officer'), icon: const Icon(Icons.login, size: 16), label: const Text('Sign in with Google (mock)'), style: ElevatedButton.styleFrom(backgroundColor: Colors.white, foregroundColor: Colors.black87))
            else
              Row(children: [
                CircleAvatar(backgroundColor: const Color(0xFF00E5FF), child: Text(state.currentUser!['displayName'][0], style: const TextStyle(color: Color(0xFF0A1628)))),
                const SizedBox(width: 10),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(state.currentUser!['displayName'], style: const TextStyle(color: Colors.white, fontSize: 13)), Text(state.currentUser!['email'], style: const TextStyle(color: Colors.white54, fontSize: 11))])),
                TextButton(onPressed: ()=> state.logout(), child: const Text('Sign out', style: TextStyle(color: Colors.white54))),
              ]),
            const SizedBox(height: 16),
            // Data reset
            OutlinedButton.icon(onPressed: (){
              showDialog(context: context, builder: (d)=> AlertDialog(
                backgroundColor: const Color(0xFF0D1F3C),
                title: const Text('Reset all data?', style: TextStyle(color: Colors.white)),
                content: const Text('Clears chats, settings, and cached data.', style: TextStyle(color: Colors.white70)),
                actions: [TextButton(onPressed: ()=> Navigator.pop(d), child: const Text('Cancel')), TextButton(onPressed: (){ state.storage.chatHistoryJson=''; state.storage.baseUrl=''; Navigator.pop(d); state.showToast('Data reset', 'info'); }, child: const Text('Reset', style: TextStyle(color: Color(0xFFFF1744))))],
              ));
            }, icon: const Icon(Icons.delete_forever, color: Colors.white38, size: 16), label: const Text('Reset Data', style: TextStyle(color: Colors.white38, fontSize: 12)), style: OutlinedButton.styleFrom(side: const BorderSide(color: Colors.white12))),
            const SizedBox(height: 12),
            if (state.activeMessages.isNotEmpty)
              TextButton.icon(onPressed: (){ state.clearChat(); state.showToast('Chat cleared', 'info'); }, icon: const Icon(Icons.clear_all, color: Colors.white38, size: 16), label: Text(AppStrings.t('clearChat', lang), style: const TextStyle(color: Colors.white38, fontSize: 12))),
            const SizedBox(height: 30),
          ],
        ),
      );
    });
  }

  Widget _SectionHeader({required IconData icon, required String title}) => Row(children: [Icon(icon, size: 16, color: const Color(0xFF00E5FF)), const SizedBox(width: 6), Text(title, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w700))]);

  void _showRolePicker(BuildContext context, AppState state){
    showModalBottomSheet(context: context, backgroundColor: const Color(0xFF0D1F3C), shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))), builder: (ctx)=> SafeArea(child: ListView(
      shrinkWrap: true,
      padding: const EdgeInsets.all(16),
      children: [
        const Text('Select Operational Role', style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700)),
        const SizedBox(height: 12),
        ...userCategories.map((c)=> ListTile(
          leading: Text(c.icon, style: const TextStyle(fontSize: 22)),
          title: Text(c.name, style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
          subtitle: Text(c.tagline, style: const TextStyle(color: Colors.white54, fontSize: 10)),
          trailing: state.userCategory?.category == c.key ? const Icon(Icons.check_circle, color: Color(0xFF00E5FF), size: 18) : null,
          onTap: (){
            state.setUserCategory(UserCategoryProfile(category: c.key, roleName: c.name, vesselClass: c.vesselClass, badgeEmoji: c.icon, tagline: c.tagline, updatedAt: DateTime.now().millisecondsSinceEpoch));
            Navigator.pop(ctx);
          },
        )),
      ],
    )));
  }
}

class _ToggleTile extends StatelessWidget {
  final String title; final String subtitle; final bool value; final ValueChanged<bool> onChanged;
  const _ToggleTile({required this.title, required this.subtitle, required this.value, required this.onChanged});
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 8),
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
    decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.04), borderRadius: BorderRadius.circular(10), border: Border.all(color: Colors.white10)),
    child: Row(children: [
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)), Text(subtitle, style: const TextStyle(color: Colors.white38, fontSize: 10))])),
      Switch(value: value, onChanged: onChanged, activeColor: const Color(0xFF00E5FF)),
    ]),
  );
}
