import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';

class VizChart extends StatelessWidget {
  final Map<String, dynamic> series;
  const VizChart({super.key, required this.series});

  @override
  Widget build(BuildContext context) {
    final s = series['series'] as Map<String, dynamic>? ?? {};
    final times = (s['times'] as List<dynamic>?) ?? [];
    final waves = (s['wave_height_m'] as List<dynamic>?)?.map((e) => (e as num).toDouble()).toList() ?? [];
    final gusts = (s['wind_gust_kmh'] as List<dynamic>?)?.map((e) => (e as num).toDouble()).toList() ?? [];
    final exceed = (series['exceedance_windows'] as List<dynamic>?) ?? [];
    final tides = (series['tides'] as List<dynamic>?) ?? [];

    if (times.isEmpty) {
      return Container(
        height: 180,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(color: const Color(0xFFF8FAFB), borderRadius: BorderRadius.circular(12)),
        child: const Center(child: Text('No hourly series for this query', style: TextStyle(color: Color(0xFF6E797A), fontSize: 12))),
      );
    }

    final waveSpots = <FlSpot>[];
    final gustSpots = <FlSpot>[];
    for (int i = 0; i < waves.length && i < times.length; i++) {
      waveSpots.add(FlSpot(i.toDouble(), waves[i]));
      if (i < gusts.length) gustSpots.add(FlSpot(i.toDouble(), gusts[i]));
    }

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: const Color(0xFFFFFFFF), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFFE5E9EC))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('48H WAVE / GUST', style: TextStyle(color: Color(0xFF6E797A), fontSize: 9, letterSpacing: 0.8, fontWeight: FontWeight.w700)),
          const SizedBox(height: 12),
          SizedBox(
            height: 140,
            child: LineChart(
              LineChartData(
                gridData: FlGridData(show: true, drawVerticalLine: false, horizontalInterval: 1, getDrawingHorizontalLine: (_) => FlLine(color: const Color(0xFFE5E9EC), strokeWidth: 0.5)),
                titlesData: FlTitlesData(
                  leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 32, getTitlesWidget: (v, m) => Text(v.toStringAsFixed(1), style: const TextStyle(color: Color(0xFF6E797A), fontSize: 8)))),
                  bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                  topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                  rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                ),
                borderData: FlBorderData(show: false),
                lineBarsData: [
                  LineChartBarData(spots: waveSpots, isCurved: true, color: const Color(0xFF0E7C86), barWidth: 2, dotData: const FlDotData(show: false), belowBarData: BarAreaData(show: true, color: const Color(0xFF0E7C86).withValues(alpha: 0.12))),
                  if (gustSpots.isNotEmpty) LineChartBarData(spots: gustSpots, isCurved: true, color: const Color(0xFFFF6D00), barWidth: 1.5, dotData: const FlDotData(show: false)),
                ],
                extraLinesData: ExtraLinesData(
                  horizontalLines: exceed.map<HorizontalLine>((e) {
                    final thr = (e['threshold'] as num?)?.toDouble() ?? 0;
                    return HorizontalLine(y: thr, color: const Color(0xFFFF1744).withValues(alpha: 0.4), strokeWidth: 1, dashArray: [4, 4]);
                  }).toList(),
                ),
              ),
            ),
          ),
          const SizedBox(height: 6),
          Row(children: [
            _Legend(color: const Color(0xFF0E7C86), label: 'Wave m'),
            const SizedBox(width: 12),
            _Legend(color: const Color(0xFFFF6D00), label: 'Gust km/h'),
            const Spacer(),
            if (exceed.isNotEmpty) const Text('— unsafe threshold', style: TextStyle(color: Color(0xFFFF1744), fontSize: 9)),
          ]),
          if (tides.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: (tides as List).map<Widget>((t) => Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(color: const Color(0xFFF0F4F7), borderRadius: BorderRadius.circular(16)),
                child: Text('${t['kind']}: ${t['time_local']?.toString().substring(11,16) ?? ''} • ${t['height_m']} m', style: const TextStyle(color: Color(0xFF3E494A), fontSize: 10)),
              )).toList(),
            ),
          ],
        ],
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  final Color color;
  final String label;
  const _Legend({required this.color, required this.label});
  @override
  Widget build(BuildContext context) {
    return Row(children: [Container(width: 12, height: 3, decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(2))), const SizedBox(width: 4), Text(label, style: const TextStyle(color: Color(0xFF6E797A), fontSize: 10))]);
  }
}