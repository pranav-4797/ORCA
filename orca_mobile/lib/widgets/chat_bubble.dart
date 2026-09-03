import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';
import 'verdict_badge.dart';
import 'contextual_map_sheet.dart';

class ChatBubble extends StatefulWidget {
  final ChatMessage message;
  const ChatBubble({super.key, required this.message});
  @override
  State<ChatBubble> createState() => _ChatBubbleState();
}

class _ChatBubbleState extends State<ChatBubble> {
  bool _expanded = false;
  bool _playing = false;

  // Exact-match verdict parsing — never substring SAFE inside UNSAFE
  Map<String, String>? _parseVerdict(String content, String? structuredStatus) {
    if (structuredStatus != null) {
      final u = structuredStatus.trim().toUpperCase();
      if (u == 'UNSAFE' || u == 'CRITICAL' || u == 'EXTREME') return {'status':'critical','title':'🔴 CRITICAL HAZARD · DO NOT VENTURE'};
      if (u == 'CAUTION') return {'status':'caution','title':'🟠 CAUTION · MARGINAL CONDITIONS'};
      if (u == 'SAFE' || u == 'SAFE TO SAIL' || u == 'SAFE TO SAIL (ALL CLEAR)') return {'status':'safe','title':'🟢 ALL CLEAR · SAFE TO SAIL'};
      if (u == 'INFO') return {'status':'info','title':'ℹ️ MISSION ADVISORY'};
    }
    final upper = content.toUpperCase();
    // Check UNSAFE first to avoid SAFE substring
    if (RegExp(r'\bUNSAFE\b').hasMatch(upper) || RegExp(r'\bCRITICAL\b').hasMatch(upper)) return {'status':'critical','title':'🔴 CRITICAL HAZARD · DO NOT VENTURE'};
    if (RegExp(r'\bCAUTION\b').hasMatch(upper)) return {'status':'caution','title':'🟠 CAUTION · MARGINAL CONDITIONS'};
    if (RegExp(r'SAFE\s*TO\s*SAIL').hasMatch(upper) || RegExp(r'\bSAFE\b').hasMatch(upper)) {
      // Ensure not UNSAFE already handled
      if (!RegExp(r'\bUNSAFE\b').hasMatch(upper)) return {'status':'safe','title':'🟢 ALL CLEAR · SAFE TO SAIL'};
    }
    return null;
  }

  // Regex of terms that indicate the response carries geographic/operational
  // data worth viewing on the map (PFZ, hazards, locations, vessels, ocean
  // conditions, coordinates, etc.).
  static final RegExp _geoKeywords = RegExp(
    r'\b(PFZ|fishing zone|hazard|cyclone|storm|coast|coastal|offshore|nautical|vessel|fleet|route|waypoint|latitude|longitude|coordinates?|zone|boundary|geofence|SAR|search and rescue|wave|swell|wind|current|ocean|sea state|marine|port|harbou?r|°\s*[NSEW]|\d{1,3}\.\d+\s*,\s*\d{1,3}\.\d+)\b',
    caseSensitive: false,
  );

  bool _isGeoRelevant(ChatMessage msg, AppState state) {
    if (msg.content.isEmpty) return false;
    if (_geoKeywords.hasMatch(msg.content)) return true;
    if (msg.fleetConvergence != null) return true;
    // Also relevant if the backend already attached geo data for this
    // response's session.
    return msg.vizSessionId != null && msg.vizSessionId == state.vizSessionId && state.vizGeojson != null;
  }

  Future<void> _openContextualMap(BuildContext context, ChatMessage msg) async {
    final state = context.read<AppState>();
    if (msg.vizSessionId != null && msg.vizSessionId != state.vizSessionId) {
      await state.loadViz(msg.vizSessionId!);
    }
    final focus = state.focusPointFromViz();
    if (!context.mounted) return;
    showContextualMap(context, focusPoint: focus, contextLabel: 'From: “${msg.content.length > 40 ? '${msg.content.substring(0, 40)}…' : msg.content}”');
  }

  @override
  Widget build(BuildContext context) {
    final msg = widget.message;
    final isUser = msg.isUser;
    final verdict = !isUser ? _parseVerdict(msg.content, msg.status) : null;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 12),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.88),
        child: Column(
          crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: isUser ? const Color(0xFF00626A) : const Color(0xFFFFFFFF),
                borderRadius: BorderRadius.only(topLeft: const Radius.circular(16), topRight: const Radius.circular(16), bottomLeft: Radius.circular(isUser ? 16 : 4), bottomRight: Radius.circular(isUser ? 4 : 16)),
                border: Border.all(color: isUser ? const Color(0xFF0E7C86).withValues(alpha: 0.4) : const Color(0xFFD1D5DB)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (msg.transcribedText != null) ...[
                    Container(
                      padding: const EdgeInsets.all(6),
                      decoration: BoxDecoration(color: const Color(0xFFF0F4F7), borderRadius: BorderRadius.circular(6)),
                      child: Row(children: [const Icon(Icons.mic, size: 14, color: Color(0xFF6E797A)), const SizedBox(width: 4), Expanded(child: Text('Heard you say: "${msg.transcribedText}"', style: const TextStyle(color: Color(0xFF6E797A), fontSize: 11, fontStyle: FontStyle.italic)))]),
                    ),
                    const SizedBox(height: 8),
                  ],
                  if (!isUser && msg.modelUsed != null) ...[
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(color: const Color(0xFFF0F4F7), borderRadius: BorderRadius.circular(12)),
                      child: Text(msg.modelUsed!, style: const TextStyle(color: Color(0xFF00626A), fontSize: 10, fontWeight: FontWeight.w600)),
                    ),
                    const SizedBox(height: 8),
                  ],
                  if (!isUser && verdict != null) ...[
                    _VerdictHud(status: verdict['status']!, title: verdict['title']!),
                    const SizedBox(height: 8),
                  ] else if (!isUser && msg.status != null) ...[
                    VerdictBadge(status: msg.status!),
                    const SizedBox(height: 8),
                  ],
                  if (isUser)
                    Text(msg.content, style: TextStyle(color: Colors.white.withValues(alpha: 0.95), fontSize: 15, height: 1.4))
                  else
                    MarkdownBody(
                      data: msg.content,
                      styleSheet: MarkdownStyleSheet(
                        // Adds breathing room between paragraphs/lines instead of them
                        // being crammed edge-to-edge (this was the main cause of the
                        // "disorganised" look in the verdict/coords/advisory lines).
                        blockSpacing: 10,
                        p: const TextStyle(
                          color: Color(0xFF171C1F),
                          fontSize: 14,
                          height: 1.55,
                          letterSpacing: 0.1,
                        ),
                        strong: const TextStyle(
                          color: Color(0xFF171C1F),
                          fontWeight: FontWeight.w700,
                          height: 1.55,
                        ),
                        em: const TextStyle(color: Color(0xFF3E494A), fontStyle: FontStyle.italic),
                        code: const TextStyle(
                          color: Color(0xFF00626A),
                          backgroundColor: Color(0xFFF0F4F7),
                          fontFamily: 'monospace',
                          fontSize: 12,
                        ),
                        blockquote: const TextStyle(color: Color(0xFF3E494A), fontStyle: FontStyle.italic, height: 1.5),
                        blockquotePadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                        blockquoteDecoration: const BoxDecoration(
                          color: Color(0xFFDDFBFF),
                          border: Border(left: BorderSide(color: Color(0xFF00626A), width: 3)),
                        ),
                        h1: const TextStyle(color: Color(0xFF171C1F), fontSize: 18, fontWeight: FontWeight.w700, height: 1.4),
                        h2: const TextStyle(color: Color(0xFF171C1F), fontSize: 16, fontWeight: FontWeight.w600, height: 1.4),
                        h3: const TextStyle(color: Color(0xFF171C1F), fontSize: 14, fontWeight: FontWeight.w600, height: 1.4),
                        h1Padding: const EdgeInsets.only(bottom: 4),
                        h2Padding: const EdgeInsets.only(bottom: 4),
                        h3Padding: const EdgeInsets.only(bottom: 4),
                        listBullet: const TextStyle(color: Color(0xFF3E494A), height: 1.55),
                        listIndent: 18,
                        a: const TextStyle(color: Color(0xFF00626A), decoration: TextDecoration.underline),
                        textAlign: WrapAlignment.start,
                      ),
                      onTapLink: (text, href, title) {},
                      selectable: true,
                    ),
                  if (!isUser && msg.fleetConvergence != null && (msg.fleetConvergence!['candidates'] as List?)?.isNotEmpty == true) ...[
                    const SizedBox(height: 8),
                    _FleetCard(data: msg.fleetConvergence!),
                  ],
                  if (!isUser && msg.windDivergence != null && (msg.windDivergence!['status'] == 'MODERATE_DIVERGENCE' || msg.windDivergence!['status'] == 'HIGH_DIVERGENCE')) ...[
                    const SizedBox(height: 8),
                    _WindCard(data: msg.windDivergence!),
                  ],
                  if (!isUser && msg.reasoning.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    GestureDetector(
                      onTap: () => setState(() => _expanded = !_expanded),
                      child: Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(color: const Color(0xFFF8FAFB), borderRadius: BorderRadius.circular(8)),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [Icon(_expanded ? Icons.expand_less : Icons.expand_more, size: 14, color: const Color(0xFF6E797A)), const SizedBox(width: 4), const Text('Reasoning', style: TextStyle(color: Color(0xFF6E797A), fontSize: 11, fontWeight: FontWeight.w600))]),
                          if (_expanded) ...[
                            const SizedBox(height: 4),
                            ...msg.reasoning.map((r) => Padding(padding: const EdgeInsets.only(bottom: 2), child: Text('• $r', style: const TextStyle(color: Color(0xFF3E494A), fontSize: 11)))),
                          ],
                        ]),
                      ),
                    ),
                  ],
                  if (!isUser && msg.content.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Wrap(spacing: 6, children: [
                      if (_isGeoRelevant(msg, context.watch<AppState>()))
                        _ActionChip(
                          icon: Icons.map_outlined,
                          label: 'View in Map',
                          onTap: () => _openContextualMap(context, msg),
                        ),
                      _ActionChip(icon: _playing ? Icons.stop : Icons.volume_up, label: _playing ? 'Stop' : 'Listen', onTap: () async {
                        final tts = context.read<AppState>().tts;
                        if (_playing) { await tts.stop(); setState(()=> _playing=false);} else { setState(()=> _playing=true); await tts.speak(msg.content, msg.status ?? 'en'); setState(()=> _playing=false); }
                      }),
                      _ActionChip(icon: Icons.copy, label: 'Copy', onTap: () {
                        // Copy via clipboard - we use ScaffoldMessenger for feedback
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Copied', style: TextStyle(color: Colors.white)), backgroundColor: Color(0xFF00626A)));
                      }),
                      _ActionChip(icon: Icons.refresh, label: 'Regen', onTap: () {
                        // Regenerate: resend last user prompt
                        final state = context.read<AppState>();
                        final msgs = state.messages[state.activeChatId!]!;
                        final idx = msgs.indexOf(msg);
                        if (idx > 0) {
                          final userMsg = msgs[idx-1];
                          if (userMsg.role == 'user') {
                            state.sendQuery(userMsg.content);
                          }
                        }
                      }),
                    ]),
                  ],
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(top: 3, left: 6, right: 6),
              child: Text(
                '${DateTime.fromMillisecondsSinceEpoch(msg.timestamp).hour.toString().padLeft(2,'0')}:${DateTime.fromMillisecondsSinceEpoch(msg.timestamp).minute.toString().padLeft(2,'0')} ${msg.answeredBy != null && msg.answeredBy!.isNotEmpty ? '• ${msg.answeredBy}' : ''}',
                style: const TextStyle(color: Color(0xFF6E797A), fontSize: 10),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _VerdictHud extends StatelessWidget {
  final String status;
  final String title;
  const _VerdictHud({required this.status, required this.title});
  @override
  Widget build(BuildContext context) {
    Color c;
    switch (status) {
      case 'safe': c = const Color(0xFF00C853); break;
      case 'caution': c = const Color(0xFFFFAB00); break;
      case 'critical': c = const Color(0xFFD50000); break;
      default: c = const Color(0xFF6E797A);
    }
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.08), borderRadius: BorderRadius.circular(10), border: Border.all(color: c.withValues(alpha: 0.3))),
      child: Row(children: [
        Container(width: 6, height: 6, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
        const SizedBox(width: 8),
        Expanded(child: Text(title, style: TextStyle(color: c, fontSize: 11, fontWeight: FontWeight.w800))),
      ]),
    );
  }
}

class _FleetCard extends StatelessWidget {
  final Map<String, dynamic> data;
  const _FleetCard({required this.data});
  @override
  Widget build(BuildContext context) {
    final cands = (data['candidates'] as List<dynamic>?) ?? [];
    final changed = data['recommendation_changed'] == true;
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: const Color(0xFFF8FAFB), borderRadius: BorderRadius.circular(10), border: Border.all(color: const Color(0xFFE5E9EC))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [const Text('🎣 Fleet Convergence', style: TextStyle(color: Color(0xFF00626A), fontSize: 11, fontWeight: FontWeight.w700)), if (data['status']?.toString().startsWith('SIMULATED') == true) Container(margin: const EdgeInsets.only(left: 6), padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2), decoration: BoxDecoration(color: Colors.orange.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(4)), child: const Text('DEMO', style: TextStyle(color: Colors.orange, fontSize: 8, fontWeight: FontWeight.w700)))]),
        const SizedBox(height: 6),
        if (changed) Text('Recommendation changed: ${data['raw_best_zone']?['zone_id']} → ${data['final_zone']?['zone_id']} (${data['change_reason'] ?? ''})', style: const TextStyle(color: Color(0xFF3E494A), fontSize: 11)),
        const SizedBox(height: 6),
        ...cands.map((c) => Container(
          margin: const EdgeInsets.only(bottom: 4),
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(color: (c['is_recommended'] == true ? const Color(0xFF00C853).withValues(alpha: 0.08) : const Color(0xFFF8FAFB)), borderRadius: BorderRadius.circular(8), border: Border.all(color: c['is_recommended'] == true ? const Color(0xFF00C853).withValues(alpha: 0.3) : const Color(0xFFE5E9EC))),
          child: Row(children: [
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${c['zone_id']} ${c['is_recommended'] == true ? '✓' : ''}', style: const TextStyle(color: Color(0xFF171C1F), fontSize: 11, fontWeight: FontWeight.w700)),
              Text('${c['distance_km']}km • base ${c['base_suitability']} • fleet ${c['fleet_count']} • adj ${c['adjusted_suitability']}', style: const TextStyle(color: Color(0xFF6E797A), fontSize: 10)),
            ])),
            Text(c['crowding_label'] ?? '', style: const TextStyle(color: Color(0xFF6E797A), fontSize: 10)),
          ]),
        )),
      ]),
    );
  }
}

class _WindCard extends StatelessWidget {
  final Map<String, dynamic> data;
  const _WindCard({required this.data});
  @override
  Widget build(BuildContext context) {
    final isHigh = data['status'] == 'HIGH_DIVERGENCE';
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: (isHigh ? const Color(0xFFD50000) : const Color(0xFFE65100)).withValues(alpha: 0.06), borderRadius: BorderRadius.circular(10), border: Border.all(color: (isHigh ? const Color(0xFFD50000) : const Color(0xFFE65100)).withValues(alpha: 0.3))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [const Text('🌬️ WIND VALIDATION', style: TextStyle(color: Color(0xFF00626A), fontSize: 11, fontWeight: FontWeight.w700)), if (data['is_simulated'] == true) Container(margin: const EdgeInsets.only(left: 6), padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2), decoration: BoxDecoration(color: Colors.orange.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(4)), child: const Text('DEMO', style: TextStyle(color: Colors.orange, fontSize: 8)))]),
        const SizedBox(height: 6),
        Row(children: [
          _WindStat(label: 'Forecast', value: '${data['forecast_wind_kn'] ?? data['forecast_wind_kmh'] ?? '—'} kn'),
          const SizedBox(width: 12),
          _WindStat(label: 'Satellite', value: '${data['satellite_wind_kn'] ?? '—'} kn'),
          const SizedBox(width: 12),
          _WindStat(label: 'Diff', value: '${data['diff_kn'] ?? '—'} kn'),
        ]),
        const SizedBox(height: 4),
        Text(data['warning']?.toString() ?? '', style: const TextStyle(color: Color(0xFF3E494A), fontSize: 11)),
      ]),
    );
  }
}

class _WindStat extends StatelessWidget {
  final String label;
  final String value;
  const _WindStat({required this.label, required this.value});
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: const TextStyle(color: Color(0xFF6E797A), fontSize: 9)), Text(value, style: const TextStyle(color: Color(0xFF171C1F), fontSize: 12, fontWeight: FontWeight.w700))]);
}

class _ActionChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  const _ActionChip({required this.icon, required this.label, required this.onTap});
  @override
  Widget build(BuildContext context) => GestureDetector(
    onTap: onTap,
    child: Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4), decoration: BoxDecoration(color: const Color(0xFFF0F4F7), borderRadius: BorderRadius.circular(16), border: Border.all(color: const Color(0xFFE5E9EC))), child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(icon, size: 12, color: const Color(0xFF3E494A)), const SizedBox(width: 4), Text(label, style: const TextStyle(color: Color(0xFF3E494A), fontSize: 10))])),
  );
}