import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';

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
          backgroundColor: const Color(0xFF0A1628),
          body: RefreshIndicator(
            onRefresh: _refresh,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // Header
                Row(
                  children: [
                    Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: const Color(0xFFFF1744).withValues(alpha: 0.12), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.shield, color: Color(0xFFFF1744), size: 20)),
                    const SizedBox(width: 10),
                    const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('SAR Boundary Monitor', style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w700)),
                      Text('Dark-vessel detection near IMBL', style: TextStyle(color: Colors.white38, fontSize: 11)),
                    ]),
                    const Spacer(),
                    if (loading) const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Color(0xFF00E5FF))),
                  ],
                ),
                const SizedBox(height: 14),
                // Status card
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(color: const Color(0xFF0D1F3C), borderRadius: BorderRadius.circular(14), border: Border.all(color: Colors.white10)),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        const Text('Provider', style: TextStyle(color: Colors.white54, fontSize: 11)),
                        const Spacer(),
                        Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3), decoration: BoxDecoration(color: isDemo ? Colors.orange.withValues(alpha: 0.15) : const Color(0xFF00C853).withValues(alpha: 0.15), borderRadius: BorderRadius.circular(12)), child: Text(isDemo ? 'DEMO — SIMULATED' : 'REAL', style: TextStyle(color: isDemo ? Colors.orange : const Color(0xFF00C853), fontSize: 10, fontWeight: FontWeight.w700))),
                      ]),
                      const SizedBox(height: 6),
                      Text(status?['active_provider']?.toString() ?? 'demo', style: const TextStyle(color: Colors.white, fontSize: 13)),
                      const SizedBox(height: 8),
                      Text('Boundary: ${status?['boundary']?['name'] ?? 'IMBL'} • Radius ${status?['config']?['boundary_radius_km'] ?? 10} km', style: const TextStyle(color: Colors.white38, fontSize: 11)),
                      const SizedBox(height: 8),
                      Text(status?['disclaimer']?.toString() ?? 'Unknown != illegal — requires authority verification.', style: const TextStyle(color: Colors.white30, fontSize: 10, fontStyle: FontStyle.italic)),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                // Actions
                Row(
                  children: [
                    Expanded(child: ElevatedButton.icon(onPressed: _runDemo, icon: const Icon(Icons.radar, size: 16), label: const Text('Run Demo Scan', style: TextStyle(fontSize: 13)), style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF00E5FF), foregroundColor: const Color(0xFF0A1628)))),
                    const SizedBox(width: 8),
                    Expanded(child: OutlinedButton.icon(onPressed: _refresh, icon: const Icon(Icons.refresh, size: 16), label: const Text('Refresh', style: TextStyle(fontSize: 13)), style: OutlinedButton.styleFrom(foregroundColor: Colors.white70, side: const BorderSide(color: Colors.white12)))),
                  ],
                ),
                const SizedBox(height: 16),
                // Detections
                Text('Detections (${(detections?['detections'] as List?)?.length ?? detections?['total'] ?? 0})', style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w600)),
                const SizedBox(height: 8),
                if (detections?['detections'] == null || (detections!['detections'] as List).isEmpty)
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.03), borderRadius: BorderRadius.circular(12)),
                    child: Column(children: [
                      const Icon(Icons.satellite_alt, color: Colors.white12, size: 36),
                      const SizedBox(height: 8),
                      const Text('No detections in last scan', style: TextStyle(color: Colors.white38, fontSize: 12)),
                      const SizedBox(height: 4),
                      Text('Tap "Run Demo Scan" to generate simulated dark-vessel detections.', style: TextStyle(color: Colors.white.withValues(alpha: 0.25), fontSize: 11)),
                    ]),
                  )
                else
                  ... (detections!['detections'] as List).map((d) => Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: const Color(0xFF0D1F3C), borderRadius: BorderRadius.circular(12), border: Border.all(color: _alertColor(d['alert_level']).withValues(alpha: 0.3))),
                    child: Row(
                      children: [
                        Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: _alertColor(d['alert_level']).withValues(alpha: 0.12), borderRadius: BorderRadius.circular(8)), child: Icon(_iconFor(d['match_status']), color: _alertColor(d['alert_level']), size: 18)),
                        const SizedBox(width: 10),
                        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text('${d['detection_id'] ?? d['id'] ?? 'UNKNOWN'} • ${d['match_status'] ?? 'UNKNOWN'}', style: TextStyle(color: _alertColor(d['alert_level']), fontSize: 12, fontWeight: FontWeight.w700)),
                          const SizedBox(height: 2),
                          Text('${d['latitude']?.toStringAsFixed(4) ?? ''}, ${d['longitude']?.toStringAsFixed(4) ?? ''} • ${(d['distance_to_boundary_km'] ?? 0).toStringAsFixed(1)} km from IMBL', style: const TextStyle(color: Colors.white70, fontSize: 11)),
                          const SizedBox(height: 2),
                          Text('Conf ${(d['confidence'] ?? 0).toStringAsFixed(2)} • ${d['source'] ?? ''} ${d['is_near_boundary'] == true ? '• NEAR BOUNDARY' : ''}', style: const TextStyle(color: Colors.white38, fontSize: 10)),
                        ])),
                        Container(padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2), decoration: BoxDecoration(color: _alertColor(d['alert_level']).withValues(alpha: 0.15), borderRadius: BorderRadius.circular(6)), child: Text(d['alert_level']?.toString() ?? 'LOW', style: TextStyle(color: _alertColor(d['alert_level']), fontSize: 9, fontWeight: FontWeight.w700))),
                      ],
                    ),
                  )),
              ],
            ),
          ),
        );
      },
    );
  }

  Color _alertColor(dynamic level) {
    switch (level?.toString().toUpperCase()) {
      case 'HIGH': return const Color(0xFFFF1744);
      case 'MEDIUM': return const Color(0xFFFF6D00);
      default: return const Color(0xFF00C853);
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
