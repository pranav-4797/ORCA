import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';
import '../widgets/safety_hud.dart';
import '../widgets/viz_chart.dart';

class MapScreen extends StatefulWidget {
  // Optional [lat, lon] to center the map on — used when the map is opened
  // contextually (e.g. from an AI response or the dashboard shortcut) so it
  // reflects real, already-known coordinates instead of the generic default.
  final List<double>? focusPoint;
  // When true, renders without its own Scaffold background so it can be
  // embedded inside a contextual panel/bottom sheet.
  final bool embedded;

  const MapScreen({super.key, this.focusPoint, this.embedded = false});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  final MapController _mapCtrl = MapController();

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, state, _) {
        final lat = widget.focusPoint?[0] ?? state.mapPoint?[0] ?? state.lat ?? 16.99;
        final lon = widget.focusPoint?[1] ?? state.mapPoint?[1] ?? state.lon ?? 73.31;
        final geo = state.vizGeojson;
        final hasViz = geo != null && (geo['features'] as List?)?.isNotEmpty == true;

        final content = Column(
            children: [
              // Map
              Expanded(
                flex: 3,
                child: Stack(
                  children: [
                    FlutterMap(
                      mapController: _mapCtrl,
                      options: MapOptions(
                        initialCenter: LatLng(lat, lon),
                        initialZoom: 7,
                        onTap: (tapPos, point) {
                          state.setMapPoint([point.latitude, point.longitude]);
                          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Map point set: ${point.latitude.toStringAsFixed(4)}, ${point.longitude.toStringAsFixed(4)}'), backgroundColor: const Color(0xFF00626A), duration: const Duration(seconds: 2)));
                        },
                      ),
                      children: [
                        TileLayer(
                          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                          userAgentPackageName: 'com.orca.mobile',
                        ),
                        if (state.mapPoint != null)
                          MarkerLayer(markers: [
                            Marker(point: LatLng(state.mapPoint![0], state.mapPoint![1]), width: 36, height: 36, child: const Icon(Icons.location_on, color: Color(0xFFFF6D00), size: 32)),
                          ]),
                        MarkerLayer(markers: [
                          Marker(point: LatLng(lat, lon), width: 40, height: 40, child: Container(decoration: BoxDecoration(color: const Color(0xFF00626A), shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2)), child: const Icon(Icons.my_location, color: Colors.white, size: 18))),
                        ]),
                        if (hasViz)
                          PolylineLayer(
                            polylines: _buildPolylines(geo),
                          ),
                        if (hasViz)
                          MarkerLayer(markers: _buildMarkers(geo)),
                      ],
                    ),
                    Positioned(
                      top: 12,
                      right: 12,
                      child: Column(
                        children: [
                          _MapBtn(icon: Icons.layers, label: 'PFZ', onTap: () => _togglePfz(state)),
                          const SizedBox(height: 8),
                          _MapBtn(icon: Icons.my_location, label: 'Center', onTap: () => _mapCtrl.move(LatLng(lat, lon), 7)),
                        ],
                      ),
                    ),
                    if (!hasViz)
                      Positioned(
                        bottom: 12,
                        left: 12,
                        right: 12,
                        child: Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(color: const Color(0xFFFFFFFF).withValues(alpha: 0.9), borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFFE5E9EC))),
                          child: const Row(children: [
                            Icon(Icons.satellite_alt, color: Color(0xFF6E797A), size: 18),
                            SizedBox(width: 8),
                            Expanded(child: Text('Ask a location question to see operational picture here', style: TextStyle(color: Color(0xFF3E494A), fontSize: 12))),
                          ]),
                        ),
                      ),
                  ],
                ),
              ),
              // HUD + chart below map
              Expanded(
                flex: 2,
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    children: [
                      SafetyHud(oceanState: state.activeMessages.isNotEmpty ? null : null),
                      const SizedBox(height: 12),
                      if (state.vizSeries != null)
                        VizChart(series: state.vizSeries!)
                      else
                        Container(
                          padding: const EdgeInsets.all(16),
                          decoration: BoxDecoration(color: const Color(0xFFF8FAFB), borderRadius: BorderRadius.circular(12)),
                          child: const Text('No forecast series yet — ask ORCA for a marine status', style: TextStyle(color: Color(0xFF6E797A), fontSize: 12)),
                        ),
                    ],
                  ),
                ),
              ),
            ],
          );

        if (widget.embedded) return content;

        return Scaffold(
          backgroundColor: const Color(0xFFF6FAFD),
          body: content,
        );
      },
    );
  }

  List<Polyline> _buildPolylines(Map<String, dynamic> geo) {
    final features = geo['features'] as List<dynamic>;
    final polys = <Polyline>[];
    for (final f in features) {
      final props = f['properties'] as Map<String, dynamic>;
      final geom = f['geometry'] as Map<String, dynamic>;
      if (props['kind'] == 'route' && geom['type'] == 'LineString') {
        final coords = (geom['coordinates'] as List<dynamic>).map((c) => LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble())).toList();
        polys.add(Polyline(points: coords, color: const Color(0xFF00626A), strokeWidth: 3));
      }
      if (props['kind'] == 'imbl_line' && geom['type'] == 'LineString') {
        final coords = (geom['coordinates'] as List<dynamic>).map((c) => LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble())).toList();
        polys.add(Polyline(points: coords, color: const Color(0xFFFF1744), strokeWidth: 1.5));
      }
    }
    return polys;
  }

  List<Marker> _buildMarkers(Map<String, dynamic> geo) {
    final features = geo['features'] as List<dynamic>;
    final markers = <Marker>[];
    for (final f in features) {
      final props = f['properties'] as Map<String, dynamic>;
      final geom = f['geometry'] as Map<String, dynamic>;
      final kind = props['kind'] as String? ?? '';
      if (geom['type'] == 'Point') {
        final lon = (geom['coordinates'][0] as num).toDouble();
        final lat = (geom['coordinates'][1] as num).toDouble();
        Color c = const Color(0xFF171C1F);
        IconData icon = Icons.circle;
        if (kind == 'query_point') { c = const Color(0xFF00626A); icon = Icons.place; }
        if (kind == 'pfz_primary') { c = const Color(0xFF00C853); icon = Icons.phishing; }
        if (kind == 'fleet_recommended') { c = const Color(0xFF00C853); icon = Icons.star; }
        if (kind == 'fleet_candidate') { c = Colors.orange; icon = Icons.circle_outlined; }
        if (kind.startsWith('sar')) { c = kind == 'sar_unknown_high' ? const Color(0xFFFF1744) : Colors.yellow; icon = Icons.warning; }
        markers.add(Marker(point: LatLng(lat, lon), width: 30, height: 30, child: Icon(icon, color: c, size: 20)));
      }
    }
    return markers;
  }

  void _togglePfz(AppState state) {
    // In real app, fetch PFZ live layer toggles WMS tiles — here just refresh
    state.loadPfzLive();
    state.showToast('PFZ live refreshed', 'info');
  }
}

class _MapBtn extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  const _MapBtn({required this.icon, required this.label, required this.onTap});
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(color: const Color(0xFFFFFFFF), borderRadius: BorderRadius.circular(8), border: Border.all(color: const Color(0xFFE5E9EC))),
        child: Column(children: [Icon(icon, color: const Color(0xFF3E494A), size: 16), const SizedBox(height: 2), Text(label, style: const TextStyle(color: Color(0xFF6E797A), fontSize: 9))]),
      ),
    );
  }
}