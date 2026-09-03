import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';
import '../l10n/strings.dart';
import '../widgets/offline_banner.dart';
import '../widgets/safety_hud.dart';
import '../widgets/viz_chart.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  bool _checking = true;

  @override
  void initState() {
    super.initState();
    _initLocation();
  }

  Future<void> _initLocation() async {
    final s = context.read<AppState>();

    if (s.lat != null) {
      setState(() => _checking = false);
      return;
    }

    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        setState(() => _checking = false);
        return;
      }

      var perm = await Geolocator.checkPermission();

      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }

      if (perm == LocationPermission.denied ||
          perm == LocationPermission.deniedForever) {
        setState(() => _checking = false);
        return;
      }

      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.low,
          timeLimit: Duration(seconds: 10),
        ),
      );

      s.setLocation(pos.latitude, pos.longitude);
    } catch (_) {}

    if (mounted) {
      setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, state, _) {
        final lang = state.language;

        final last = state.activeMessages.isNotEmpty
            ? state.activeMessages.lastWhere(
                (m) => !m.isUser,
                orElse: () => state.activeMessages.last,
              )
            : null;

        final hasLast = last != null && !last.isUser;

        final activeAlerts =
            state.alerts.where((a) => !a.dismissed).toList();

        return Scaffold(
          backgroundColor: const Color(0xFFF6FAFD),
          body: SafeArea(
            child: Column(
              children: [
                OfflineBanner(isOnline: state.isOnline),

                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 12,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // Header
                        _buildHeader(state, lang),

                        const SizedBox(height: 16),

                        // Primary Safety Status Card
                        _buildPrimarySafetyCard(
                          state,
                          last,
                          hasLast,
                        ),

                        const SizedBox(height: 16),

                        // Dynamic Visualizations
                        if (state.vizGeojson != null) ...[
                          const SafetyHud(),
                          const SizedBox(height: 12),
                        ],

                        if (state.vizSeries != null) ...[
                          VizChart(series: state.vizSeries!),
                          const SizedBox(height: 16),
                        ],

                        // Important Warnings
                        _buildImportantWarnings(
                          state,
                          activeAlerts.length,
                        ),

                        const SizedBox(height: 16),

                        // Good Fishing Areas
                        _buildPfzCard(state),

                        const SizedBox(height: 16),

                        // Ask ORCA
                        _buildAskOrcaCard(state),

                        const SizedBox(height: 16),

                        // Active Alerts
                        if (activeAlerts.isNotEmpty) ...[
                          _buildActiveAlerts(
                            state,
                            activeAlerts,
                          ),
                          const SizedBox(height: 16),
                        ],

                        // Sync Footer
                        _buildSyncFooter(state),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  // ------------------------------------------------------------
  // HEADER
  // ------------------------------------------------------------

  Widget _buildHeader(AppState state, String lang) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              AppStrings.t('appTitle', lang),
              style: const TextStyle(
                color: Color(0xFF00626A),
                fontSize: 20,
                fontWeight: FontWeight.w900,
                letterSpacing: -0.5,
              ),
            ),

            const SizedBox(height: 2),

            Text(
              state.userCategory != null
                  ? '${state.userCategory!.badgeEmoji} ${state.userCategory!.roleName}'
                  : AppStrings.t('appSubtitle', lang),
              style: const TextStyle(
                color: Color(0xFF6E797A),
                fontSize: 11,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),

        GestureDetector(
          onTap: (state.lat == null && !_checking)
              ? _showManual
              : null,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                    'Arabian Sea',
                    style: TextStyle(
                      color: Color(0xFF3E494A),
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.0,
                    ),
                  ),

                  if (state.lat == null && !_checking) ...[
                    const SizedBox(width: 4),
                    const Icon(
                      Icons.edit_location,
                      size: 12,
                      color: Color(0xFF00626A),
                    ),
                  ],
                ],
              ),

              const SizedBox(height: 2),

              _checking
                  ? const SizedBox(
                      width: 12,
                      height: 12,
                      child: CircularProgressIndicator(
                        strokeWidth: 1.5,
                        color: Color(0xFF00626A),
                      ),
                    )
                  : state.lat != null
                      ? Text(
                          '${state.lat!.toStringAsFixed(4)}° N, '
                          '${state.lon!.toStringAsFixed(4)}° E',
                          style: const TextStyle(
                            color: Color(0xFF00626A),
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            fontFamily: 'monospace',
                          ),
                        )
                      : Text(
                          AppStrings.t('locationUnknown', lang),
                          style: const TextStyle(
                            color: Color(0xFF6E797A),
                            fontSize: 11,
                          ),
                        ),

              if (state.mapPoint != null)
                Text(
                  'Map: ${state.mapPoint![0].toStringAsFixed(4)}, '
                  '${state.mapPoint![1].toStringAsFixed(4)}',
                  style: const TextStyle(
                    color: Color(0xFFD97706),
                    fontSize: 10,
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  // ------------------------------------------------------------
  // PRIMARY SAFETY CARD
  // ------------------------------------------------------------

  Widget _buildPrimarySafetyCard(
      AppState state, dynamic last, bool hasLast) {
    final bool hasData = hasLast && last!.status != null;

    final String status =
        hasData ? last.status!.toString().toLowerCase() : 'unknown';

    // The LEFT LINE is now the only safety colour indicator.
    final Color statusColor =
        status.contains('safe') ||
                status.contains('good') ||
                status.contains('normal')
            ? const Color(0xFF22A06B)
            : status.contains('danger') ||
                    status.contains('avoid') ||
                    status.contains('unsafe') ||
                    status.contains('critical')
                ? const Color(0xFFE5484D)
                : status.contains('caution') ||
                        status.contains('rough') ||
                        status.contains('warning')
                    ? const Color(0xFFF59E0B)
                    : const Color(0xFF9CA3AF);

    final String headline = hasData
        ? last.status!.toString()
        : (state.isOnline
            ? 'Ask ORCA for a safety check.'
            : 'No cached forecast available.');

    final String description = hasData
        ? last.content
        : (state.isOnline
            ? "You're online — ask ORCA about current conditions before heading out."
            : "You're offline and no forecast has been cached yet. Reconnect to get a safety check.");

    return Container(
      decoration: BoxDecoration(
        // No more orange/amber background.
        color: Colors.white,

        borderRadius: BorderRadius.circular(16),

        border: Border.all(
          color: const Color(0xFFE5E9EC),
        ),

        boxShadow: const [
          BoxShadow(
            color: Color.fromRGBO(23, 28, 31, 0.05),
            blurRadius: 3,
            offset: Offset(0, 1),
          ),
        ],
      ),

      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ------------------------------------------------
            // SAFETY STATUS LINE
            // ------------------------------------------------
            Container(
              width: 4,
              decoration: BoxDecoration(
                color: statusColor,
                borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(16),
                  bottomLeft: Radius.circular(16),
                ),
              ),
            ),

            // ------------------------------------------------
            // CARD CONTENT
            // ------------------------------------------------
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment:
                      CrossAxisAlignment.start,
                  children: [
                    Text(
                      headline,
                      style: const TextStyle(
                        color: Color(0xFF171C1F),
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                        letterSpacing: -0.3,
                        height: 1.25,
                      ),
                    ),

                    const SizedBox(height: 4),

                    Text(
                      description,
                      style: const TextStyle(
                        color: Color(0xFF451A03),
                        fontSize: 14,
                        fontWeight: FontWeight.w500,
                        height: 1.5,
                      ),
                      maxLines: 4,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ------------------------------------------------------------
  // IMPORTANT WARNINGS
  // ------------------------------------------------------------

  Widget _buildImportantWarnings(
      AppState state, int activeAlertCount) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment:
              MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'Important Warnings',
              style: TextStyle(
                color: Color(0xFF171C1F),
                fontSize: 14,
                fontWeight: FontWeight.bold,
                letterSpacing: -0.2,
              ),
            ),

            Text(
              '${activeAlertCount > 0 ? activeAlertCount : 2} Active',
              style: const TextStyle(
                color: Color(0xFF6E797A),
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),

        const SizedBox(height: 10),

        _buildWarningCard(
          title: 'Cyclone — Paradip Coast',
          detail: 'Severe storm surge',
          statusText: 'Status: Avoid going out',
          dotColor: const Color(0xFFEF4444),
          statusBg: const Color(0xFFFEF2F2),
          statusBorder: const Color(0xFFFECACA),
          statusColor: const Color(0xFFB91C1C),
          query:
              'Are there active cyclone or high wave warnings near Paradip port, Odisha?',
          state: state,
        ),

        const SizedBox(height: 10),

        _buildWarningCard(
          title: 'Rough Sea — Mumbai Offshore',
          detail: 'Turbulent sea',
          statusText: 'Status: Use caution',
          dotColor: const Color(0xFFF59E0B),
          statusBg: const Color(0xFFFFFBEB),
          statusBorder: const Color(0xFFFDE68A),
          statusColor: const Color(0xFF92400E),
          query:
              'Is it safe to venture into the sea from Mumbai Harbour tomorrow at 6 AM?',
          state: state,
        ),
      ],
    );
  }

  // ------------------------------------------------------------
  // WARNING CARD
  // ------------------------------------------------------------

  Widget _buildWarningCard({
    required String title,
    required String detail,
    required String statusText,
    required Color dotColor,
    required Color statusBg,
    required Color statusBorder,
    required Color statusColor,
    required String query,
    required AppState state,
  }) {
    return GestureDetector(
      onTap: () => state.sendQuery(query),

      child: Container(
        padding: const EdgeInsets.all(14),

        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: const Color(0xFFE5E9EC),
          ),
          boxShadow: const [
            BoxShadow(
              color: Color.fromRGBO(23, 28, 31, 0.05),
              blurRadius: 3,
              offset: Offset(0, 1),
            ),
          ],
        ),

        child: Row(
          crossAxisAlignment:
              CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment:
                    CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(
                          color: dotColor,
                          shape: BoxShape.circle,
                        ),
                      ),

                      const SizedBox(width: 6),

                      Expanded(
                        child: Text(
                          title,
                          style: const TextStyle(
                            color: Color(0xFF171C1F),
                            fontSize: 13,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ),

                  const SizedBox(height: 4),

                  Text(
                    detail,
                    style: const TextStyle(
                      color: Color(0xFF3E494A),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),

            const SizedBox(width: 8),

            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 10,
                vertical: 4,
              ),

              decoration: BoxDecoration(
                color: statusBg,
                borderRadius: BorderRadius.circular(20),
                border: Border.all(
                  color: statusBorder,
                ),
              ),

              child: Text(
                statusText,
                style: TextStyle(
                  color: statusColor,
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ------------------------------------------------------------
  // GOOD FISHING AREAS
  // ------------------------------------------------------------

  Widget _buildPfzCard(AppState state) {
    const query =
        'Where is the nearest potential fishing zone (PFZ) near Kochi coast today?';

    return Column(
      crossAxisAlignment:
          CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment:
              MainAxisAlignment.spaceBetween,
          children: const [
            Text(
              'Good Fishing Areas',
              style: TextStyle(
                color: Color(0xFF171C1F),
                fontSize: 14,
                fontWeight: FontWeight.bold,
                letterSpacing: -0.2,
              ),
            ),

            Text(
              'High Yield',
              style: TextStyle(
                color: Color(0xFF00626A),
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),

        const SizedBox(height: 10),

        GestureDetector(
          onTap: () => state.sendQuery(query),

          child: Container(
            padding: const EdgeInsets.all(14),

            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: const Color(0xFFE5E9EC),
              ),
              boxShadow: const [
                BoxShadow(
                  color: Color.fromRGBO(23, 28, 31, 0.05),
                  blurRadius: 3,
                  offset: Offset(0, 1),
                ),
              ],
            ),

            child: Row(
              mainAxisAlignment:
                  MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment:
                        CrossAxisAlignment.start,
                    children: const [
                      Text(
                        'Kochi Marine PFZ',
                        style: TextStyle(
                          color: Color(0xFF171C1F),
                          fontSize: 13,
                          fontWeight: FontWeight.bold,
                        ),
                      ),

                      SizedBox(height: 2),

                      Text(
                        'Good fishing activity expected',
                        style: TextStyle(
                          color: Color(0xFF3E494A),
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(width: 8),

                Container(
                  padding:
                      const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 6,
                  ),

                  decoration: BoxDecoration(
                    color: const Color(0xFFDDFBFF),
                    borderRadius:
                        BorderRadius.circular(20),
                    border: Border.all(
                      color: const Color(0xFF0E7C86)
                          .withValues(alpha: 0.3),
                    ),
                  ),

                  child: const Text(
                    '14.8 km offshore',
                    style: TextStyle(
                      color: Color(0xFF00626A),
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  // ------------------------------------------------------------
  // ASK ORCA
  // ------------------------------------------------------------

  Widget _buildAskOrcaCard(AppState state) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 16,
        vertical: 14,
      ),

      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: const Color(0xFFE5E9EC),
        ),
        boxShadow: const [
          BoxShadow(
            color: Color.fromRGBO(23, 28, 31, 0.05),
            blurRadius: 3,
            offset: Offset(0, 1),
          ),
        ],
      ),

      child: Column(
        crossAxisAlignment:
            CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment:
                MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'Ask ORCA',
                style: TextStyle(
                  color: Color(0xFF171C1F),
                  fontSize: 15,
                  fontWeight: FontWeight.bold,
                ),
              ),

              ElevatedButton.icon(
                onPressed: () => _preset(
                  state,
                  'Is it safe to go out today?',
                ),

                style: ElevatedButton.styleFrom(
                  backgroundColor:
                      const Color(0xFF00626A),
                  foregroundColor: Colors.white,
                  elevation: 0,
                  padding:
                      const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 10,
                  ),
                  shape:
                      RoundedRectangleBorder(
                    borderRadius:
                        BorderRadius.circular(16),
                  ),
                  textStyle: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                  minimumSize: Size.zero,
                  tapTargetSize:
                      MaterialTapTargetSize
                          .shrinkWrap,
                ),

                icon: const Icon(
                  Icons.chat_bubble_outline,
                  size: 14,
                ),

                label: const Text('Ask'),
              ),
            ],
          ),

          const SizedBox(height: 10),

          SizedBox(
            height: 34,

            child: ListView(
              scrollDirection:
                  Axis.horizontal,

              children: [
                _buildQueryPill(
                  label: 'Nearest PFZ',
                  onTap: () => _preset(
                    state,
                    'Where is the nearest fishing zone?',
                  ),
                  isHighlight: true,
                ),

                const SizedBox(width: 8),

                _buildQueryPill(
                  label: 'Safe to go?',
                  onTap: () => _preset(
                    state,
                    'Is it safe to go fishing today?',
                  ),
                  isHighlight: false,
                ),

                const SizedBox(width: 8),

                _buildQueryPill(
                  label: 'Cyclone warning?',
                  onTap: () => _preset(
                    state,
                    'Are there any cyclone warnings for my area?',
                  ),
                  isHighlight: false,
                ),

                const SizedBox(width: 8),

                _buildQueryPill(
                  label: 'Sea forecast',
                  onTap: () => _preset(
                    state,
                    "What's the weather like today?",
                  ),
                  isHighlight: false,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ------------------------------------------------------------
  // QUERY PILL
  // ------------------------------------------------------------

  Widget _buildQueryPill({
    required String label,
    required VoidCallback onTap,
    required bool isHighlight,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius:
          BorderRadius.circular(999),

      child: Container(
        alignment: Alignment.center,

        padding:
            const EdgeInsets.symmetric(
          horizontal: 14,
          vertical: 8,
        ),

        decoration: BoxDecoration(
          color: isHighlight
              ? const Color(0xFFDDFBFF)
              : const Color(0xFFF8FAFB),

          borderRadius:
              BorderRadius.circular(999),

          border: Border.all(
            color: isHighlight
                ? const Color(0xFF0E7C86)
                    .withValues(alpha: 0.3)
                : const Color(0xFFE5E9EC),
          ),
        ),

        child: Text(
          label,
          style: TextStyle(
            color: isHighlight
                ? const Color(0xFF00626A)
                : const Color(0xFF171C1F),
            fontSize: 12.5,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }

  // ------------------------------------------------------------
  // ACTIVE ALERTS
  // ------------------------------------------------------------

  Widget _buildActiveAlerts(
      AppState state, List<dynamic> activeAlerts) {
    return Column(
      crossAxisAlignment:
          CrossAxisAlignment.start,
      children: [
        const Text(
          'ACTIVE ALERTS',
          style: TextStyle(
            color: Color(0xFF3E494A),
            fontSize: 11,
            fontWeight: FontWeight.bold,
            letterSpacing: 0.5,
          ),
        ),

        const SizedBox(height: 8),

        ...activeAlerts.take(2).map(
              (a) => Container(
                margin:
                    const EdgeInsets.only(
                  bottom: 6,
                ),

                padding:
                    const EdgeInsets.all(10),

                decoration: BoxDecoration(
                  color: const Color(0xFFFFFBEB),
                  borderRadius:
                      BorderRadius.circular(10),
                  border: Border.all(
                    color: const Color(0xFFFDE68A),
                  ),
                ),

                child: Row(
                  children: [
                    const Icon(
                      Icons.warning_amber_rounded,
                      color: Color(0xFFB45309),
                      size: 18,
                    ),

                    const SizedBox(width: 8),

                    Expanded(
                      child: Text(
                        a.message,
                        style: const TextStyle(
                          color: Color(0xFF78350F),
                          fontSize: 12,
                          fontWeight: FontWeight.w500,
                        ),
                        maxLines: 2,
                        overflow:
                            TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
            ),
      ],
    );
  }

  // ------------------------------------------------------------
  // SYNC FOOTER
  // ------------------------------------------------------------

  Widget _buildSyncFooter(AppState state) {
    return Padding(
      padding:
          const EdgeInsets.symmetric(
        vertical: 20,
      ),

      child: Center(
        child: Column(
          children: [
            Icon(
              state.isOnline
                  ? Icons.cloud_done_outlined
                  : Icons.cloud_off_outlined,
              size: 18,
              color: const Color(0xFF9CA3AF),
            ),

            const SizedBox(height: 6),

            Text(
              state.isOnline
                  ? 'Up to date'
                  : 'Showing cached data · You\'re all set for today',

              style: const TextStyle(
                color: Color(0xFF9CA3AF),
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ------------------------------------------------------------
  // PRESET QUERY
  // ------------------------------------------------------------

  void _preset(AppState s, String q) {
    s.sendQuery(q);
    DefaultTabController.of(context);
    s.showToast('Sent: $q', 'info');
  }

  // ------------------------------------------------------------
  // MANUAL LOCATION
  // ------------------------------------------------------------

  void _showManual() {
    final latCtrl = TextEditingController();
    final lonCtrl = TextEditingController();

    showDialog(
      context: context,

      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.white,

        title: const Text(
          'Enter Location',
          style: TextStyle(
            color: Color(0xFF171C1F),
          ),
        ),

        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: latCtrl,
              keyboardType:
                  TextInputType.number,

              style: const TextStyle(
                color: Color(0xFF171C1F),
              ),

              decoration:
                  const InputDecoration(
                labelText: 'Latitude',

                labelStyle: TextStyle(
                  color: Color(0xFF6E797A),
                ),

                hintText: 'e.g. 18.6705',

                hintStyle: TextStyle(
                  color: Color(0xFFD1D5DB),
                ),

                enabledBorder:
                    OutlineInputBorder(
                  borderSide: BorderSide(
                    color: Color(0xFFD1D5DB),
                  ),
                ),

                focusedBorder:
                    OutlineInputBorder(
                  borderSide: BorderSide(
                    color: Color(0xFF00626A),
                  ),
                ),
              ),
            ),

            const SizedBox(height: 12),

            TextField(
              controller: lonCtrl,
              keyboardType:
                  TextInputType.number,

              style: const TextStyle(
                color: Color(0xFF171C1F),
              ),

              decoration:
                  const InputDecoration(
                labelText: 'Longitude',

                labelStyle: TextStyle(
                  color: Color(0xFF6E797A),
                ),

                hintText: 'e.g. 73.8897',

                hintStyle: TextStyle(
                  color: Color(0xFFD1D5DB),
                ),

                enabledBorder:
                    OutlineInputBorder(
                  borderSide: BorderSide(
                    color: Color(0xFFD1D5DB),
                  ),
                ),

                focusedBorder:
                    OutlineInputBorder(
                  borderSide: BorderSide(
                    color: Color(0xFF00626A),
                  ),
                ),
              ),
            ),
          ],
        ),

        actions: [
          TextButton(
            onPressed: () =>
                Navigator.pop(ctx),

            child: const Text(
              'Cancel',
              style: TextStyle(
                color: Color(0xFF6E797A),
              ),
            ),
          ),

          TextButton(
            onPressed: () {
              final lat =
                  double.tryParse(
                latCtrl.text,
              );

              final lon =
                  double.tryParse(
                lonCtrl.text,
              );

              if (lat != null &&
                  lon != null) {
                context
                    .read<AppState>()
                    .setManualLocation(
                      lat,
                      lon,
                    );
              }

              Navigator.pop(ctx);
            },

            child: const Text(
              'Save',
              style: TextStyle(
                color: Color(0xFF00626A),
              ),
            ),
          ),
        ],
      ),
    );
  }
}