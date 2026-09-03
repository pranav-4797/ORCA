import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';
import '../l10n/strings.dart';
import '../models/user_category.dart';

// Marine Theme Colors based on tailwind config
class OrcaTheme {
  static const Color marine50 = Color(0xFFF6FAFD);
  static const Color marine100 = Color(0xFFEAEEF1);
  static const Color marine200 = Color(0xFFE5E9EC);
  static const Color marine300 = Color(0xFFD1D5DB);
  static const Color marine600 = Color(0xFF6E797A);
  static const Color marine700 = Color(0xFF3E494A);
  static const Color marine900 = Color(0xFF171C1F);
  
  static const Color orcaTeal = Color(0xFF00626A);
  static const Color orcaTealContainer = Color(0xFF0E7C86);
  static const Color orcaCyanLight = Color(0xFFDDFBFF);
  static const Color cardBg = Colors.white;
  static const Color inputBg = Color(0xFFF8FAFB);
}

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
    return Consumer<AppState>(builder: (context, state, _) {
      final lang = state.language;
      final user = state.currentUser;
      final userName = user != null ? (user['displayName'] ?? 'Officer') : 'Officer';
      final userEmail = user != null ? (user['email'] ?? 'Officer@orca.local') : 'Officer@orca.local';
      final initialLetter = userName.isNotEmpty ? userName[0].toUpperCase() : 'O';

      return Scaffold(
        backgroundColor: OrcaTheme.marine50,
        body: SafeArea(
          child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 448), // max-w-md equivalent
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
                children: [
                  // SECTION 1: ACCOUNT & OPERATIONAL ROLE
                  _buildAccountAndRoleCard(context, state, userName, userEmail, initialLetter),
                  const SizedBox(height: 16),

                  // SECTION 2: PREFERENCES & CONTROLS
                  _buildPreferencesCard(context, state, lang),
                  const SizedBox(height: 16),

                  // SECTION 3: DIAGNOSTICS & SIMULATION (Collapsible details)
                  _buildDiagnosticsSection(context, state, lang),
                  const SizedBox(height: 32),
                ],
              ),
            ),
          ),
        ),
      );
    });
  }

  // --- ACCOUNT & ROLE CARD ---
  Widget _buildAccountAndRoleCard(
    BuildContext context,
    AppState state,
    String userName,
    String userEmail,
    String initialLetter,
  ) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: OrcaTheme.cardBg,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: OrcaTheme.marine200),
        boxShadow: const [
          BoxShadow(
            color: Color.fromRGBO(0, 0, 0, 0.03),
            blurRadius: 4,
            offset: Offset(0, 1),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // User Info & Sign In / Out Header
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Row(
                  children: [
                    // Avatar Circle
                    Container(
                      width: 44,
                      height: 44,
                      decoration: BoxDecoration(
                        color: OrcaTheme.orcaCyanLight,
                        shape: BoxShape.circle,
                        border: Border.all(color: OrcaTheme.orcaTeal.withValues(alpha: 0.2)),
                      ),
                      alignment: Alignment.center,
                      child: Text(
                        initialLetter,
                        style: const TextStyle(
                          color: OrcaTheme.orcaTeal,
                          fontWeight: FontWeight.w900,
                          fontSize: 18,
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    // User Details & Badge
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Flexible(
                                child: Text(
                                  userName,
                                  style: const TextStyle(
                                    fontSize: 14,
                                    fontWeight: FontWeight.bold,
                                    color: OrcaTheme.marine900,
                                    letterSpacing: 0.2,
                                  ),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              const SizedBox(width: 6),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                decoration: BoxDecoration(
                                  color: OrcaTheme.orcaCyanLight,
                                  borderRadius: BorderRadius.circular(4),
                                  border: Border.all(color: OrcaTheme.orcaTeal.withValues(alpha: 0.3)),
                                ),
                                child: const Text(
                                  'ACTIVE DUTY',
                                  style: TextStyle(
                                    fontSize: 10,
                                    fontWeight: FontWeight.bold,
                                    color: OrcaTheme.orcaTeal,
                                    letterSpacing: 0.5,
                                  ),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 2),
                          Text(
                            userEmail,
                            style: const TextStyle(
                              fontSize: 12,
                              color: OrcaTheme.marine700,
                              fontFamily: 'monospace',
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              // Sign in / Sign out button
              if (state.currentUser == null)
                OutlinedButton(
                  onPressed: () => state.loginMock('Officer'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    side: const BorderSide(color: OrcaTheme.marine300),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                  child: const Text(
                    'Sign in',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: OrcaTheme.marine700),
                  ),
                )
              else
                OutlinedButton(
                  onPressed: () => state.logout(),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    side: const BorderSide(color: OrcaTheme.marine300),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                  child: const Text(
                    'Sign out',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: OrcaTheme.marine700),
                  ),
                ),
            ],
          ),

          const SizedBox(height: 16),

          // Operational Marine Role Selector
          const Text(
            'OPERATIONAL MARINE ROLE',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.bold,
              color: OrcaTheme.marine600,
              letterSpacing: 0.8,
            ),
          ),
          const SizedBox(height: 8),
          InkWell(
            onTap: () => _showRolePicker(context, state),
            borderRadius: BorderRadius.circular(12),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: OrcaTheme.inputBg,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: OrcaTheme.marine200),
              ),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: OrcaTheme.orcaCyanLight,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: state.userCategory != null
                        ? Text(state.userCategory!.badgeEmoji, style: const TextStyle(fontSize: 16))
                        : const Icon(Icons.shield_outlined, size: 16, color: OrcaTheme.orcaTeal),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          state.userCategory?.roleName ?? 'Coastal Maritime Guard',
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.bold,
                            color: OrcaTheme.marine900,
                          ),
                        ),
                        Text(
                          state.userCategory?.tagline ?? 'Patrol & Emergency Authority Enabled',
                          style: const TextStyle(
                            fontSize: 10,
                            color: OrcaTheme.marine700,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const Icon(Icons.keyboard_arrow_down, size: 20, color: OrcaTheme.marine600),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  // --- PREFERENCES & CONTROLS CARD ---
  Widget _buildPreferencesCard(BuildContext context, AppState state, String lang) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: OrcaTheme.cardBg,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: OrcaTheme.marine200),
        boxShadow: const [
          BoxShadow(
            color: Color.fromRGBO(0, 0, 0, 0.03),
            blurRadius: 4,
            offset: Offset(0, 1),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Section Title
          Row(
            children: [
              const Icon(Icons.tune_rounded, size: 16, color: OrcaTheme.orcaTeal),
              const SizedBox(width: 8),
              Text(
                AppStrings.t('preferences', lang).isNotEmpty 
                    ? AppStrings.t('preferences', lang).toUpperCase() 
                    : 'PREFERENCES & CONTROLS',
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                  color: OrcaTheme.marine900,
                  letterSpacing: 0.8,
                ),
              ),
            ],
          ),

          const SizedBox(height: 16),

          // Language Selector
          Text(
            AppStrings.t('language', lang),
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: OrcaTheme.marine700,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: _languages.map((l) {
              final sel = state.activeLanguage == l.$1;
              return Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 3),
                  child: InkWell(
                    onTap: () => state.setLanguage(l.$1),
                    borderRadius: BorderRadius.circular(12),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 150),
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: sel ? OrcaTheme.orcaTeal : OrcaTheme.inputBg,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: sel ? OrcaTheme.orcaTeal : OrcaTheme.marine200,
                        ),
                      ),
                      child: Text(
                        l.$2,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: sel ? FontWeight.bold : FontWeight.w500,
                          color: sel ? Colors.white : OrcaTheme.marine700,
                        ),
                      ),
                    ),
                  ),
                ),
              );
            }).toList(),
          ),

          const SizedBox(height: 16),

          // Toggles Container
          _buildToggleItem(
            title: 'Audio Feedback',
            subtitle: 'Speak safety answers & alerts aloud (TTS)',
            value: state.audioFeedback,
            onChanged: (v) {
              state.audioFeedback = v;
              state.showToast(v ? 'Audio feedback enabled' : 'Audio muted', 'info');
            },
          ),
          const SizedBox(height: 8),
          _buildToggleItem(
            title: 'Send on Enter',
            subtitle: 'Enter sends, Shift+Enter adds new line',
            value: state.sendOnEnter,
            onChanged: (v) {
              state.sendOnEnter = v;
              state.showToast(v ? 'Send on Enter enabled' : 'Send on Enter disabled', 'info');
            },
          ),

          const SizedBox(height: 12),
          const Divider(height: 1, color: OrcaTheme.marine200),

          // Decorative/Operational Settings Rows (matching mockup UX)
          _buildStaticPreferenceRow(
            title: 'Maritime Alert Urgency',
            valueText: 'High Priority (Gale & Severe Swell)',
          ),
          const Divider(height: 1, color: OrcaTheme.marine200),
          _buildStaticPreferenceRow(
            title: 'Navigation Units',
            valueText: 'Nautical Miles (knots, metres, nm)',
          ),
        ],
      ),
    );
  }

  // Helper toggle item matching styled HTML switch
  Widget _buildToggleItem({
    required String title,
    required String subtitle,
    required bool value,
    required ValueChanged<bool> onChanged,
  }) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: OrcaTheme.inputBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: OrcaTheme.marine200),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                    color: OrcaTheme.marine900,
                  ),
                ),
                Text(
                  subtitle,
                  style: const TextStyle(
                    fontSize: 11,
                    color: OrcaTheme.marine600,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Switch(
            value: value,
            onChanged: onChanged,
            activeColor: OrcaTheme.orcaTeal,
            activeTrackColor: OrcaTheme.orcaTeal.withValues(alpha: 0.3),
            inactiveThumbColor: Colors.white,
            inactiveTrackColor: OrcaTheme.marine300,
          ),
        ],
      ),
    );
  }

  Widget _buildStaticPreferenceRow({required String title, required String valueText}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w500, color: OrcaTheme.marine900),
              ),
              Text(
                valueText,
                style: const TextStyle(fontSize: 11, color: OrcaTheme.marine600),
              ),
            ],
          ),
          const Icon(Icons.chevron_right, size: 18, color: OrcaTheme.marine600),
        ],
      ),
    );
  }

  // --- DIAGNOSTICS & SIMULATION SECTION (COLLAPSIBLE) ---
  Widget _buildDiagnosticsSection(BuildContext context, AppState state, String lang) {
    return Container(
      decoration: BoxDecoration(
        color: OrcaTheme.cardBg,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: OrcaTheme.marine200),
        boxShadow: const [
          BoxShadow(
            color: Color.fromRGBO(0, 0, 0, 0.03),
            blurRadius: 4,
            offset: Offset(0, 1),
          ),
        ],
      ),
      child: ExpansionTile(
        initiallyExpanded: true,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        collapsedShape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        title: Row(
          children: [
            const Icon(Icons.science_outlined, size: 16, color: OrcaTheme.orcaTeal),
            const SizedBox(width: 8),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [
                Text(
                  'DIAGNOSTICS & SIMULATION',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: OrcaTheme.marine900,
                    letterSpacing: 0.8,
                  ),
                ),
                Text(
                  'Maritime testing & simulation overrides',
                  style: TextStyle(fontSize: 10, color: OrcaTheme.marine600),
                ),
              ],
            ),
          ],
        ),
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: OrcaTheme.marine200)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 1. Console View Switcher
                const Text(
                  'CONSOLE VIEW SWITCHER',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: OrcaTheme.marine600,
                    letterSpacing: 0.8,
                  ),
                ),
                const SizedBox(height: 6),
                Row(
                  children: _consoleTabs.map((t) {
                    final isSel = state.activeNavTab == t.$1;
                    return Expanded(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 2),
                        child: InkWell(
                          onTap: () => state.setNavTab(t.$1),
                          borderRadius: BorderRadius.circular(8),
                          child: Container(
                            padding: const EdgeInsets.symmetric(vertical: 6),
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              color: isSel ? OrcaTheme.orcaTeal : OrcaTheme.inputBg,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(
                                color: isSel ? OrcaTheme.orcaTeal : OrcaTheme.marine200,
                              ),
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                if (isSel) ...[
                                  const Icon(Icons.check, size: 12, color: Colors.white),
                                  const SizedBox(width: 2),
                                ],
                                Flexible(
                                  child: Text(
                                    t.$2,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      fontSize: 11,
                                      fontWeight: isSel ? FontWeight.bold : FontWeight.w500,
                                      color: isSel ? Colors.white : OrcaTheme.marine700,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    );
                  }).toList(),
                ),

                const SizedBox(height: 16),

                // 2. Fleet Convergence Test
                const Text(
                  'FLEET CONVERGENCE TEST',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: OrcaTheme.marine600,
                    letterSpacing: 0.8,
                  ),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: ['', 'low', 'medium', 'high', 'severe'].map((lvl) {
                    final isSel = state.fleetDemoLevel == lvl;
                    final label = lvl.isEmpty ? 'Normal' : lvl;
                    return InkWell(
                      onTap: () {
                        state.setFleetDemoLevel(lvl.isEmpty ? null : lvl);
                        state.showToast(
                          lvl.isEmpty ? 'Fleet Normal' : 'Fleet $lvl set — next PFZ query affected',
                          'info',
                        );
                      },
                      borderRadius: BorderRadius.circular(8),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                        decoration: BoxDecoration(
                          color: isSel ? OrcaTheme.orcaTeal : OrcaTheme.inputBg,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                            color: isSel ? OrcaTheme.orcaTeal : OrcaTheme.marine200,
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (isSel) ...[
                              const Icon(Icons.check, size: 12, color: Colors.white),
                              const SizedBox(width: 4),
                            ],
                            Text(
                              label,
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: isSel ? FontWeight.bold : FontWeight.w500,
                                color: isSel ? Colors.white : OrcaTheme.marine700,
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  }).toList(),
                ),

                const SizedBox(height: 16),

                // 3. Wind Divergence Test
                const Text(
                  'WIND DIVERGENCE TEST',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: OrcaTheme.marine600,
                    letterSpacing: 0.8,
                  ),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: ['', 'match', 'moderate', 'high_divergence'].map((sc) {
                    final isSel = state.windDemoScenario == sc;
                    final label = sc.isEmpty ? 'Normal' : sc;
                    return InkWell(
                      onTap: () {
                        state.setWindDemoScenario(sc.isEmpty ? null : sc);
                        state.showToast(sc.isEmpty ? 'Wind Normal' : 'Wind $sc set', 'info');
                      },
                      borderRadius: BorderRadius.circular(8),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                        decoration: BoxDecoration(
                          color: isSel ? OrcaTheme.orcaTeal : OrcaTheme.inputBg,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(
                            color: isSel ? OrcaTheme.orcaTeal : OrcaTheme.marine200,
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (isSel) ...[
                              const Icon(Icons.check, size: 12, color: Colors.white),
                              const SizedBox(width: 4),
                            ],
                            Text(
                              label,
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: isSel ? FontWeight.bold : FontWeight.w500,
                                color: isSel ? Colors.white : OrcaTheme.marine700,
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  }).toList(),
                ),

                const SizedBox(height: 16),

                // 4. Backend Service Endpoint
                Text(
                  AppStrings.t('backendUrl', lang).toUpperCase(),
                  style: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: OrcaTheme.marine600,
                    letterSpacing: 0.8,
                  ),
                ),
                const SizedBox(height: 6),
                TextField(
                  controller: TextEditingController(text: state.baseUrl),
                  style: const TextStyle(
                    color: OrcaTheme.marine900,
                    fontSize: 12,
                    fontFamily: 'monospace',
                  ),
                  decoration: InputDecoration(
                    hintText: 'https://orca-backend-1i5u.onrender.com',
                    hintStyle: const TextStyle(color: OrcaTheme.marine600, fontSize: 11),
                    filled: true,
                    fillColor: OrcaTheme.inputBg,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: OrcaTheme.marine300),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: OrcaTheme.marine300),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: OrcaTheme.orcaTeal),
                    ),
                    suffixIcon: const Icon(Icons.lock_outline, size: 14, color: OrcaTheme.marine600),
                  ),
                  onSubmitted: (v) {
                    state.baseUrl = v.trim();
                    state.showToast('Backend URL updated', 'success');
                  },
                ),

                const SizedBox(height: 16),

                // 5. Action Buttons
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: () {
                      state.showToast('Executed Stress Simulation', 'info');
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: OrcaTheme.orcaCyanLight,
                      foregroundColor: OrcaTheme.orcaTeal,
                      elevation: 0,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: BorderSide(color: OrcaTheme.orcaTeal.withValues(alpha: 0.3)),
                      ),
                    ),
                    child: const Text(
                      'Execute Stress Simulation',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
                    ),
                  ),
                ),

                const SizedBox(height: 8),

                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () {
                      showDialog(
                        context: context,
                        builder: (d) => AlertDialog(
                          backgroundColor: Colors.white,
                          title: const Text('Reset local sensor data?', style: TextStyle(color: OrcaTheme.marine900)),
                          content: const Text(
                            'Clears chats, settings, and cached data.',
                            style: TextStyle(color: OrcaTheme.marine700),
                          ),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(d),
                              child: const Text('Cancel'),
                            ),
                            TextButton(
                              onPressed: () {
                                state.storage.chatHistoryJson = '';
                                state.storage.baseUrl = '';
                                Navigator.pop(d);
                                state.showToast('Data reset', 'info');
                              },
                              child: const Text('Reset', style: TextStyle(color: Colors.red)),
                            ),
                          ],
                        ),
                      );
                    },
                    icon: const Icon(Icons.delete_outline, size: 16, color: OrcaTheme.marine600),
                    label: const Text(
                      'Reset Local Sensor Data',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500, color: OrcaTheme.marine600),
                    ),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      side: const BorderSide(color: OrcaTheme.marine300),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),

                if (state.activeMessages.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.center,
                    child: TextButton.icon(
                      onPressed: () {
                        state.clearChat();
                        state.showToast('Chat cleared', 'info');
                      },
                      icon: const Icon(Icons.clear_all, color: OrcaTheme.marine600, size: 16),
                      label: Text(
                        AppStrings.t('clearChat', lang),
                        style: const TextStyle(color: OrcaTheme.marine600, fontSize: 12),
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  // --- ROLE PICKER BOTTOM SHEET ---
  void _showRolePicker(BuildContext context, AppState state) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              'Select Operational Role',
              style: TextStyle(color: OrcaTheme.marine900, fontSize: 14, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            ...userCategories.map(
              (c) => ListTile(
                leading: Text(c.icon, style: const TextStyle(fontSize: 22)),
                title: Text(
                  c.name,
                  style: const TextStyle(color: OrcaTheme.marine900, fontSize: 12, fontWeight: FontWeight.bold),
                ),
                subtitle: Text(
                  c.tagline,
                  style: const TextStyle(color: OrcaTheme.marine600, fontSize: 10),
                ),
                trailing: state.userCategory?.category == c.key
                    ? const Icon(Icons.check_circle, color: OrcaTheme.orcaTeal, size: 18)
                    : null,
                onTap: () {
                  state.setUserCategory(
                    UserCategoryProfile(
                      category: c.key,
                      roleName: c.name,
                      vesselClass: c.vesselClass,
                      badgeEmoji: c.icon,
                      tagline: c.tagline,
                      updatedAt: DateTime.now().millisecondsSinceEpoch,
                    ),
                  );
                  Navigator.pop(ctx);
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}