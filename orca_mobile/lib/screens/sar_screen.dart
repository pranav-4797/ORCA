import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';

// Color palette matched to the Stitch design (app.* tailwind tokens).
class _AppColors {
  static const bg = Color(0xFFF6FAFD);
  static const card = Color(0xFFFFFFFF);
  static const input = Color(0xFFF8FAFB);
  static const borderSubtle = Color(0xFFE5E9EC);
  static const borderDefault = Color(0xFFD1D5DB);
  static const primaryText = Color(0xFF171C1F);
  static const secondaryText = Color(0xFF3E494A);
  static const tertiaryText = Color(0xFF6E797A);
  static const brand = Color(0xFF00626A);
  static const btnTeal = Color(0xFF0E7C86);
  static const btnTealHover = Color(0xFF0B666F);
  static const paleCyan = Color(0xFFDDFBFF);
  static const statusGreen = Color(0xFF059669);
  static const statusGreenBg = Color(0xFFECFDF5);
  static const statusGreenBorder = Color(0xFFA7F3D0);
  static const danger = Color(0xFFDC2626);
  static const dangerBg = Color(0xFFFEF2F2);
  static const dangerBorder = Color(0xFFFEE2E2);
  static const amber = Color(0xFFB45309);
  static const amberBg = Color(0xFFFFFBEB);
  static const amberBorder = Color(0xFFFDE68A);
}

class SarScreen extends StatefulWidget {
  const SarScreen({super.key});
  @override
  State<SarScreen> createState() => _SarScreenState();
}

class _SarScreenState extends State<SarScreen> {
  Map<String, dynamic>? status;
  Map<String, dynamic>? detections;
  bool loading = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() => loading = true);
    final s = await context.read<AppState>().api.getSarStatus();
    final d = await context.read<AppState>().api.getSarDetections();
    if (mounted) setState(() { status = s; detections = d; loading = false; });
  }

  Future<void> _runDemo() async {
    setState(() => loading = true);
    final r = await context.read<AppState>().api.runSarDemo();
    if (r != null) {
      setState(() { detections = r; loading = false; });
      context.read<AppState>().showToast('SAR demo scan complete', 'success');
    } else {
      setState(() => loading = false);
      context.read<AppState>().showToast('SAR demo failed', 'error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDemo = status?['active_provider'] == 'demo' || (detections?['source'] as String?)?.toLowerCase().contains('demo') == true;
    return Consumer<AppState>(
      builder: (context, state, _) {
        return Scaffold(
          backgroundColor: _AppColors.bg,
          body: SafeArea(
            child: RefreshIndicator(
              color: _AppColors.btnTeal,
              onRefresh: _refresh,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                children: [
                  // Header
                  Row(
                    children: [
                      Container(
                        width: 44,
                        height: 44,
                        decoration: BoxDecoration(
                          color: _AppColors.dangerBg,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: _AppColors.dangerBorder),
                        ),
                        child: const Icon(Icons.shield, color: _AppColors.danger, size: 22),
                      ),
                      const SizedBox(width: 14),
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'SAR Boundary Monitor',
                              style: TextStyle(color: _AppColors.primaryText, fontSize: 17, fontWeight: FontWeight.w700, height: 1.2),
                            ),
                            SizedBox(height: 2),
                            Text(
                              'Dark-vessel detection near IMBL',
                              style: TextStyle(color: _AppColors.secondaryText, fontSize: 12, fontWeight: FontWeight.w400),
                            ),
                          ],
                        ),
                      ),
                      if (loading)
                        const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2, color: _AppColors.btnTeal),
                        ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  // Provider / status card
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: _AppColors.card,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: _AppColors.borderSubtle),
                      boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.04), blurRadius: 6, offset: const Offset(0, 1))],
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Text(
                              'PROVIDER',
                              style: TextStyle(color: _AppColors.tertiaryText, fontSize: 11, fontWeight: FontWeight.w500, letterSpacing: 0.6),
                            ),
                            const Spacer(),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                              decoration: BoxDecoration(
                                color: isDemo ? _AppColors.amberBg : _AppColors.statusGreenBg,
                                borderRadius: BorderRadius.circular(999),
                                border: Border.all(color: isDemo ? _AppColors.amberBorder : _AppColors.statusGreenBorder),
                              ),
                              child: Text(
                                isDemo ? 'DEMO — SIMULATED' : 'REAL',
                                style: TextStyle(
                                  color: isDemo ? _AppColors.amber : _AppColors.statusGreen,
                                  fontSize: 10,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          status?['active_provider']?.toString() ?? 'demo',
                          style: const TextStyle(color: _AppColors.primaryText, fontSize: 20, fontWeight: FontWeight.w700, letterSpacing: -0.2),
                        ),
                        const SizedBox(height: 6),
                        RichText(
                          text: TextSpan(
                            style: const TextStyle(color: _AppColors.secondaryText, fontSize: 13),
                            children: [
                              const TextSpan(text: 'Boundary: '),
                              TextSpan(
                                text: '${status?['boundary']?['name'] ?? 'IMBL'}',
                                style: const TextStyle(fontWeight: FontWeight.w600, color: _AppColors.secondaryText),
                              ),
                              const TextSpan(text: ' • Radius '),
                              TextSpan(
                                text: '${status?['config']?['boundary_radius_km'] ?? 10} km',
                                style: const TextStyle(fontWeight: FontWeight.w600, color: _AppColors.secondaryText),
                              ),
                            ],
                          ),
                        ),
                        Container(
                          margin: const EdgeInsets.only(top: 12),
                          padding: const EdgeInsets.only(top: 10),
                          decoration: const BoxDecoration(
                            border: Border(top: BorderSide(color: _AppColors.borderSubtle)),
                          ),
                          child: Text(
                            status?['disclaimer']?.toString() ?? 'Unknown != illegal — requires authority verification.',
                            style: const TextStyle(color: _AppColors.tertiaryText, fontSize: 11, fontStyle: FontStyle.italic),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),
                  // Actions
                  Row(
                    children: [
                      Expanded(
                        child: SizedBox(
                          height: 48,
                          child: ElevatedButton(
                            onPressed: _runDemo,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: _AppColors.btnTeal,
                              foregroundColor: Colors.white,
                              elevation: 0,
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                            ).copyWith(
                              overlayColor: WidgetStateProperty.all(_AppColors.btnTealHover.withValues(alpha: 0.15)),
                            ),
                            child: const Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.gps_fixed, size: 16, color: Colors.white),
                                SizedBox(width: 8),
                                Text('Run Demo Scan', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                              ],
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: SizedBox(
                          height: 48,
                          child: OutlinedButton(
                            onPressed: _refresh,
                            style: OutlinedButton.styleFrom(
                              backgroundColor: Colors.white,
                              foregroundColor: _AppColors.primaryText,
                              side: const BorderSide(color: _AppColors.borderDefault),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                            ),
                            child: const Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.refresh, size: 16, color: _AppColors.secondaryText),
                                SizedBox(width: 8),
                                Text('Refresh', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: _AppColors.primaryText)),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 22),
                  // Detections header
                  Text(
                    'Detections (${(detections?['detections'] as List?)?.length ?? detections?['total'] ?? 0})',
                    style: const TextStyle(color: _AppColors.primaryText, fontSize: 15, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 10),
                  if (detections?['detections'] == null || (detections!['detections'] as List).isEmpty)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 24),
                      decoration: BoxDecoration(
                        color: _AppColors.card,
                        borderRadius: BorderRadius.circular(16),
                        border: Border.all(color: _AppColors.borderSubtle),
                        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.04), blurRadius: 6, offset: const Offset(0, 1))],
                      ),
                      child: Column(
                        children: [
                          Container(
                            width: 56,
                            height: 56,
                            decoration: BoxDecoration(
                              color: _AppColors.paleCyan.withValues(alpha: 0.6),
                              borderRadius: BorderRadius.circular(16),
                              border: Border.all(color: const Color(0xFFCCF3F7)),
                            ),
                            child: const Icon(Icons.satellite_alt, color: _AppColors.btnTeal, size: 26),
                          ),
                          const SizedBox(height: 12),
                          const Text(
                            'No detections in last scan',
                            style: TextStyle(color: _AppColors.primaryText, fontSize: 14, fontWeight: FontWeight.w700),
                          ),
                          const SizedBox(height: 6),
                          const Text(
                            'Tap "Run Demo Scan" to generate simulated dark-vessel detections.',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: _AppColors.tertiaryText, fontSize: 12, height: 1.4),
                          ),
                        ],
                      ),
                    )
                  else
                    ... (detections!['detections'] as List).map((d) => Container(
                      margin: const EdgeInsets.only(bottom: 10),
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: _AppColors.card,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: _alertColor(d['alert_level']).withValues(alpha: 0.35)),
                        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.03), blurRadius: 4, offset: const Offset(0, 1))],
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Container(
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: _alertColor(d['alert_level']).withValues(alpha: 0.12),
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: Icon(_iconFor(d['match_status']), color: _alertColor(d['alert_level']), size: 18),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${d['detection_id'] ?? d['id'] ?? 'UNKNOWN'} • ${d['match_status'] ?? 'UNKNOWN'}',
                                  style: TextStyle(color: _alertColor(d['alert_level']), fontSize: 12.5, fontWeight: FontWeight.w700),
                                ),
                                const SizedBox(height: 3),
                                Text(
                                  '${d['latitude']?.toStringAsFixed(4) ?? ''}, ${d['longitude']?.toStringAsFixed(4) ?? ''} • ${(d['distance_to_boundary_km'] ?? 0).toStringAsFixed(1)} km from IMBL',
                                  style: const TextStyle(color: _AppColors.secondaryText, fontSize: 11.5),
                                ),
                                const SizedBox(height: 3),
                                Text(
                                  'Conf ${(d['confidence'] ?? 0).toStringAsFixed(2)} • ${d['source'] ?? ''} ${d['is_near_boundary'] == true ? '• NEAR BOUNDARY' : ''}',
                                  style: const TextStyle(color: _AppColors.tertiaryText, fontSize: 10.5),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: _alertColor(d['alert_level']).withValues(alpha: 0.12),
                              borderRadius: BorderRadius.circular(999),
                            ),
                            child: Text(
                              d['alert_level']?.toString() ?? 'LOW',
                              style: TextStyle(color: _alertColor(d['alert_level']), fontSize: 9.5, fontWeight: FontWeight.w700),
                            ),
                          ),
                        ],
                      ),
                    )),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Color _alertColor(dynamic level) {
    switch (level?.toString().toUpperCase()) {
      case 'HIGH': return _AppColors.danger;
      case 'MEDIUM': return const Color(0xFFD97706);
      default: return _AppColors.statusGreen;
    }
  }
  IconData _iconFor(dynamic status) {
    switch (status?.toString().toUpperCase()) {
      case 'UNKNOWN': return Icons.warning_amber;
      case 'KNOWN': return Icons.verified;
      default: return Icons.help_outline;
    }
  }
}