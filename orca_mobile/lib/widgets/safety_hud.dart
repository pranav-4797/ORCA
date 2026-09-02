import 'package:flutter/material.dart';

class SafetyHud extends StatelessWidget {
  final Map<String, dynamic>? oceanState;
  final Map<String, dynamic>? risk;
  const SafetyHud({super.key, this.oceanState, this.risk});

  @override
  Widget build(BuildContext context) {
    // Adapted from SafetyFactorHUD.ts — 6 factors: waves, wind, sea, rain, visibility, temp
    // Mobile: show as row of pills when data available, else placeholder
    final hasData = oceanState != null || risk != null;
    if (!hasData) {
      return Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.03), borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.white10)),
        child: const Row(children: [Icon(Icons.shield_outlined, color: Colors.white24, size: 16), SizedBox(width: 8), Text('Safety Factor HUD — ask ORCA for live breakdown', style: TextStyle(color: Colors.white38, fontSize: 11))]),
      );
    }
    final factors = [
      {'label': 'WAVES', 'icon': Icons.waves, 'value': '${oceanState?['wave_height_m'] ?? '—'} m'},
      {'label': 'WIND', 'icon': Icons.air, 'value': '${oceanState?['wind_speed_kmh'] ?? '—'} km/h'},
      {'label': 'SEA', 'icon': Icons.water, 'value': oceanState?['sst_celsius'] != null ? '${oceanState!['sst_celsius']}°C' : '—'},
      {'label': 'VIS', 'icon': Icons.visibility_outlined, 'value': '—'},
      {'label': 'RAIN', 'icon': Icons.water_drop_outlined, 'value': '—'},
      {'label': 'TEMP', 'icon': Icons.thermostat_outlined, 'value': oceanState?['sst_celsius'] != null ? '${oceanState!['sst_celsius']}°C' : '—'},
    ];
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: const Color(0xFF0D1F3C), borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.white10)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('FACTOR BREAKDOWN', style: TextStyle(color: Colors.white54, fontSize: 9, letterSpacing: 0.8, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          Row(
            children: factors.map((f) => Expanded(child: Column(children: [
              Icon(f['icon'] as IconData, color: const Color(0xFF00E5FF), size: 18),
              const SizedBox(height: 4),
              Text(f['label'] as String, style: const TextStyle(color: Colors.white38, fontSize: 8)),
              const SizedBox(height: 2),
              Text(f['value'] as String, style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w600)),
            ]))).toList(),
          ),
        ],
      ),
    );
  }
}
