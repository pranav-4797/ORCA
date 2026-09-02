import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';
import '../l10n/strings.dart';
import '../widgets/preset_query_button.dart';
import '../widgets/verdict_badge.dart';
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
  void initState(){ super.initState(); _initLocation(); }

  Future<void> _initLocation() async {
    final s = context.read<AppState>();
    if (s.lat != null) { setState(()=> _checking=false); return; }
    try{
      if (!await Geolocator.isLocationServiceEnabled()) { setState(()=> _checking=false); return; }
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) { setState(()=> _checking=false); return; }
      final pos = await Geolocator.getCurrentPosition(locationSettings: const LocationSettings(accuracy: LocationAccuracy.low, timeLimit: Duration(seconds: 10)));
      s.setLocation(pos.latitude, pos.longitude);
    } catch(_){}
    if(mounted) setState(()=> _checking=false);
  }

  @override
  Widget build(BuildContext context){
    return Consumer<AppState>(builder: (context, state, _){
      final lang = state.language;
      final last = state.activeMessages.isNotEmpty ? state.activeMessages.lastWhere((m)=> !m.isUser, orElse: ()=> state.activeMessages.last) : null;
      final hasLast = last != null && !last.isUser;
      return Scaffold(
        backgroundColor: const Color(0xFF0A1628),
        body: Column(
          children: [
            OfflineBanner(isOnline: state.isOnline),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  // Header
                  Row(children: [
                    Container(padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: const Color(0xFF00E5FF).withValues(alpha: 0.1), borderRadius: BorderRadius.circular(12)), child: const Icon(Icons.sailing, color: Color(0xFF00E5FF), size: 26)),
                    const SizedBox(width: 12),
                    Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(AppStrings.t('appTitle', lang), style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: 1)),
                      Text(state.userCategory != null ? '${state.userCategory!.badgeEmoji} ${state.userCategory!.roleName}' : AppStrings.t('appSubtitle', lang), style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 11)),
                    ]),
                    const Spacer(),
                    Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4), decoration: BoxDecoration(color: state.isOnline ? const Color(0xFF00C853).withValues(alpha: 0.12) : const Color(0xFFFF6D00).withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)), child: Row(children: [Container(width: 6,height:6,decoration: BoxDecoration(color: state.isOnline ? const Color(0xFF00C853) : const Color(0xFFFF6D00), shape: BoxShape.circle)), const SizedBox(width: 4), Text(state.isOnline ? 'ONLINE' : 'OFFLINE', style: TextStyle(color: state.isOnline ? const Color(0xFF00C853) : const Color(0xFFFF6D00), fontSize: 9, fontWeight: FontWeight.w700))])),
                  ]),
                  const SizedBox(height: 16),
                  // Location card
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(color: const Color(0xFF0D1F3C), borderRadius: BorderRadius.circular(14), border: Border.all(color: const Color(0xFF00E5FF).withValues(alpha: 0.1))),
                    child: Row(children: [
                      Icon(Icons.location_on_outlined, color: state.locationGranted ? const Color(0xFF00E5FF) : Colors.white38, size: 20),
                      const SizedBox(width: 10),
                      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(AppStrings.t('currentLocation', lang), style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 10)),
                        const SizedBox(height: 2),
                        _checking ? const SizedBox(width: 14,height:14, child: CircularProgressIndicator(strokeWidth: 1.5, color: Color(0xFF00E5FF))) : state.lat != null ? Text('${state.lat!.toStringAsFixed(4)}, ${state.lon!.toStringAsFixed(4)}', style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600, fontFamily: 'monospace')) : Text(AppStrings.t('locationUnknown', lang), style: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 12)),
                        if (state.mapPoint != null) Text('Map point: ${state.mapPoint![0].toStringAsFixed(4)}, ${state.mapPoint![1].toStringAsFixed(4)}', style: const TextStyle(color: Color(0xFFFF6D00), fontSize: 10)),
                      ])),
                      if(state.lat==null && !_checking) TextButton(onPressed: _showManual, child: const Text('Set', style: TextStyle(color: Color(0xFF00E5FF), fontSize: 12))),
                    ]),
                  ),
                  const SizedBox(height: 12),
                  // Safety status
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(color: const Color(0xFF0D1F3C), borderRadius: BorderRadius.circular(14), border: Border.all(color: const Color(0xFF00E5FF).withValues(alpha: 0.1))),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(AppStrings.t('safetyStatus', lang), style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 10)),
                      const SizedBox(height: 8),
                      if (hasLast && last!.status != null) ...[
                        VerdictBadge(status: last.status!),
                        const SizedBox(height: 8),
                        Text(last.content, style: TextStyle(color: Colors.white.withValues(alpha: 0.75), fontSize: 12, height: 1.4), maxLines: 4, overflow: TextOverflow.ellipsis),
                      ] else
                        Text('No data yet — ask ORCA for a status check.', style: TextStyle(color: Colors.white.withValues(alpha: 0.35), fontSize: 12)),
                    ]),
                  ),
                  const SizedBox(height: 12),
                  // Safety HUD if viz exists
                  if (state.vizGeojson != null) const SafetyHud(),
                  const SizedBox(height: 12),
                  if (state.vizSeries != null) VizChart(series: state.vizSeries!),
                  const SizedBox(height: 16),
                  // Scenario starters (Overview scenarios like web's 5 cards)
                  Text('Scenarios', style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 12, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  GridView.count(
                    shrinkWrap: true, physics: const NeverScrollableScrollPhysics(), crossAxisCount: 2, crossAxisSpacing: 8, mainAxisSpacing: 8, childAspectRatio: 2.2,
                    children: [
                      _ScenarioCard(title: 'Safe', sub: 'GOA • LOW', q: 'Is it safe to sail from Panaji Port, Goa tomorrow morning?', color: const Color(0xFF00C853), state: state),
                      _ScenarioCard(title: 'Rough', sub: 'MUMBAI • HIGH', q: 'Is it safe to venture into the sea from Mumbai Harbour tomorrow at 6 AM?', color: const Color(0xFFFF6D00), state: state),
                      _ScenarioCard(title: 'Cyclone', sub: 'PARADIP • EXTREME', q: 'Are there active cyclone or high wave warnings near Paradip port, Odisha?', color: const Color(0xFFFF1744), state: state),
                      _ScenarioCard(title: 'PFZ', sub: 'KOCHI • PFZ', q: 'Where is the nearest potential fishing zone (PFZ) near Kochi coast today?', color: const Color(0xFF00E5FF), state: state),
                    ],
                  ),
                  const SizedBox(height: 16),
                  // Quick queries (FishermanDeck)
                  Text('Quick Queries', style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 12, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, runSpacing: 8, children: [
                    PresetQueryButton(label: 'Nearest fishing zone', onTap: ()=> _preset(state, 'Where is the nearest fishing zone?')),
                    PresetQueryButton(label: 'Any cyclone warning?', onTap: ()=> _preset(state, 'Are there any cyclone warnings for my area?')),
                    PresetQueryButton(label: 'Safe to go out today?', onTap: ()=> _preset(state, 'Is it safe to go fishing today?')),
                    PresetQueryButton(label: "Today's weather", onTap: ()=> _preset(state, "What's the weather like today?")),
                  ]),
                  const SizedBox(height: 16),
                  // Alerts preview
                  if (state.alerts.where((a)=> !a.dismissed).isNotEmpty) ...[
                    Text('Active Alerts', style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 12, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 8),
                    ...state.alerts.where((a)=> !a.dismissed).take(2).map((a) => Container(
                      margin: const EdgeInsets.only(bottom: 6),
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(color: const Color(0xFFFF6D00).withValues(alpha: 0.08), borderRadius: BorderRadius.circular(10), border: Border.all(color: const Color(0xFFFF6D00).withValues(alpha: 0.2))),
                      child: Row(children: [const Icon(Icons.warning_amber, color: Color(0xFFFF6D00), size: 16), const SizedBox(width: 8), Expanded(child: Text(a.message, style: const TextStyle(color: Colors.white70, fontSize: 12), maxLines: 2))]),
                    )),
                  ],
                ]),
              ),
            ),
          ],
        ),
      );
    });
  }

  void _preset(AppState s, String q){
    // Create new chat if needed and send
    s.sendQuery(q);
    DefaultTabController.of(context);
    // Switch to chat tab via parent MainShell — we use simple navigation
    // For now just show toast
    s.showToast('Sent: $q', 'info');
  }

  void _showManual(){
    final latCtrl = TextEditingController(); final lonCtrl = TextEditingController();
    showDialog(context: context, builder: (ctx)=> AlertDialog(
      backgroundColor: const Color(0xFF0D1F3C),
      title: const Text('Enter Location', style: TextStyle(color: Colors.white)),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: latCtrl, keyboardType: TextInputType.number, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: 'Latitude', labelStyle: TextStyle(color: Colors.white54), hintText: 'e.g. 17.15', hintStyle: TextStyle(color: Colors.white24), enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: Colors.white24)), focusedBorder: OutlineInputBorder(borderSide: BorderSide(color: Color(0xFF00E5FF))))),
        const SizedBox(height: 12),
        TextField(controller: lonCtrl, keyboardType: TextInputType.number, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: 'Longitude', labelStyle: TextStyle(color: Colors.white54), hintText: 'e.g. 73.10', hintStyle: TextStyle(color: Colors.white24), enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: Colors.white24)), focusedBorder: OutlineInputBorder(borderSide: BorderSide(color: Color(0xFF00E5FF))))),
      ]),
      actions: [
        TextButton(onPressed: ()=> Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: Colors.white54))),
        TextButton(onPressed: (){
          final lat = double.tryParse(latCtrl.text); final lon = double.tryParse(lonCtrl.text);
          if(lat!=null && lon!=null) context.read<AppState>().setManualLocation(lat, lon);
          Navigator.pop(ctx);
        }, child: const Text('Save', style: TextStyle(color: Color(0xFF00E5FF)))),
      ],
    ));
  }
}

class _ScenarioCard extends StatelessWidget {
  final String title; final String sub; final String q; final Color color; final AppState state;
  const _ScenarioCard({required this.title, required this.sub, required this.q, required this.color, required this.state});
  @override
  Widget build(BuildContext context){
    return GestureDetector(
      onTap: ()=> state.sendQuery(q),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: const Color(0xFF0D1F3C), borderRadius: BorderRadius.circular(12), border: Border.all(color: color.withValues(alpha: 0.25))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Container(width: 8,height:8,decoration: BoxDecoration(color: color, shape: BoxShape.circle)), const SizedBox(width: 6), Text(title, style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700))]),
          const SizedBox(height: 4),
          Text(sub, style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 10)),
          const SizedBox(height: 4),
          Text(q, style: TextStyle(color: Colors.white.withValues(alpha: 0.35), fontSize: 9), maxLines: 2, overflow: TextOverflow.ellipsis),
        ]),
      ),
    );
  }
}
