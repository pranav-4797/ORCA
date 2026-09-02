import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:file_picker/file_picker.dart';
import '../state/app_state.dart';
import '../widgets/chat_bubble.dart';
import '../widgets/agent_activity.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _ctrl = TextEditingController();
  final ScrollController _scroll = ScrollController();
  late stt.SpeechToText _speech;
  bool _speechAvailable = false;
  bool _listening = false;
  bool _showAgents = false;

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
    _initSpeech();
  }

  Future<void> _initSpeech() async {
    try {
      _speechAvailable = await _speech.initialize(onError: (_) { if (mounted) setState(()=> _listening=false); }, onStatus: (s){ if(s=='done'||s=='notListening'){ if(mounted) setState(()=> _listening=false);} });
    } catch(_){ _speechAvailable=false; }
  }

  void _scrollBottom() { WidgetsBinding.instance.addPostFrameCallback((_) { if(_scroll.hasClients) _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);}); }

  void _send() {
    final text = _ctrl.text.trim();
    if (text.isEmpty) return;
    // sendOnEnter toggle is wired: if false, Enter inserts newline, send only via button
    // Here TextField onSubmitted respects sendOnEnter
    _ctrl.clear();
    context.read<AppState>().sendQuery(text);
    _scrollBottom();
  }

  Future<void> _voice() async {
    if (!_speechAvailable) return;
    if (_listening) { await _speech.stop(); setState(()=> _listening=false); return; }
    setState(()=> _listening=true);
    String? recognized;
    final completer = Completer<void>();
    try {
      await _speech.listen(onResult: (r){
        if (r.recognizedWords.isNotEmpty) recognized=r.recognizedWords;
        if (r.finalResult) {
          _speech.stop(); setState(()=> _listening=false);
          if (recognized!=null && recognized!.isNotEmpty) { _ctrl.text=recognized!; _send(); }
          if(!completer.isCompleted) completer.complete();
        }
      }, listenOptions: stt.SpeechListenOptions(listenMode: stt.ListenMode.dictation));
      Future.delayed(const Duration(seconds: 16), (){ if(!completer.isCompleted){ _speech.stop(); setState(()=> _listening=false); if(recognized!=null&&recognized!.isNotEmpty){_ctrl.text=recognized!; _send();} completer.complete(); }});
    } catch(_){ setState(()=> _listening=false); }
  }

  Future<void> _pickFile() async {
    final result = await FilePicker.platform.pickFiles(allowMultiple: false, withData: true);
    if (result != null && result.files.isNotEmpty) {
      final f = result.files.first;
      final size = f.size;
      final name = f.name;
      context.read<AppState>().showToast('Attached $name (${(size/1024).toStringAsFixed(1)} KB) — sent as context', 'info');
      // For now, we send as text attachment note; backend doesn't yet ingest files except voice
      _ctrl.text = '${_ctrl.text} [attached: $name]';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(builder: (context, state, _) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollBottom());
      final msgs = state.activeMessages;
      return Scaffold(
        backgroundColor: const Color(0xFF0A1628),
        body: Column(
          children: [
            // Agent activity strip
            if (state.executionState != 'idle' && state.executionSteps.isNotEmpty) AgentActivityStrip(steps: state.executionSteps, state: state.executionState, action: state.currentAction),
            // Messages
            Expanded(
              child: msgs.isEmpty
                  ? _EmptyState(onStarter: (q){ _ctrl.text=q; _send(); })
                  : ListView.builder(
                      controller: _scroll,
                      padding: const EdgeInsets.only(top: 12, bottom: 12),
                      itemCount: msgs.length,
                      itemBuilder: (_, i) => ChatBubble(message: msgs[i]),
                    ),
            ),
            if (state.isQuerying)
              Container(padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6), child: Row(children: [SizedBox(width: 14,height:14, child: CircularProgressIndicator(strokeWidth: 2, color: const Color(0xFF00E5FF))), const SizedBox(width: 8), Text('ORCA is thinking...', style: TextStyle(color: Colors.white.withValues(alpha: 0.4), fontSize: 11))])),
            _Composer(
              controller: _ctrl,
              listening: _listening,
              onSend: _send,
              onVoice: _voice,
              onPickFile: _pickFile,
              onToggleAgents: () => setState(()=> _showAgents = !_showAgents),
              showAgents: _showAgents,
            ),
            if (_showAgents) _AgentSheet(onClose: ()=> setState(()=> _showAgents=false)),
          ],
        ),
      );
    });
  }

  @override
  void dispose(){ _ctrl.dispose(); _scroll.dispose(); _speech.stop(); super.dispose(); }
}

class _EmptyState extends StatelessWidget {
  final ValueChanged<String> onStarter;
  const _EmptyState({required this.onStarter});
  @override
  Widget build(BuildContext context) {
    final starters = [
      {'title':'Safe to sail?', 'q':'Is it safe to sail from Panaji Port, Goa tomorrow morning?'},
      {'title':'Nearest PFZ', 'q':'Where is the nearest official INCOIS Potential Fishing Zone (PFZ) today?'},
      {'title':'Cyclone check', 'q':'Are there active cyclone or high wave warnings near Paradip port, Odisha?'},
      {'title':'Safe route', 'q':'Plot a safe navigational route from Mumbai Harbour avoiding restricted zones.'},
    ];
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(padding: const EdgeInsets.all(16), decoration: BoxDecoration(color: const Color(0xFF00E5FF).withValues(alpha: 0.08), shape: BoxShape.circle), child: const Icon(Icons.sailing, color: Color(0xFF00E5FF), size: 36)),
            const SizedBox(height: 12),
            const Text('Ask ORCA', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text('Type or speak your maritime inquiry', style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 12)),
            const SizedBox(height: 20),
            Wrap(
              spacing: 8, runSpacing: 8,
              children: starters.map((s) => GestureDetector(
                onTap: () => onStarter(s['q']!),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.04), borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.white10)),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(s['title']!, style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 2),
                    Text(s['q']!, style: TextStyle(color: Colors.white.withValues(alpha: 0.45), fontSize: 10), maxLines: 2),
                  ]),
                ),
              )).toList(),
            ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 6,
              children: [
                _FishChip(label: 'PFZ', onTap: ()=> onStarter('Where is the nearest fishing zone?')),
                _FishChip(label: 'Waves', onTap: ()=> onStarter('What is wave height today?')),
                _FishChip(label: 'Cyclone', onTap: ()=> onStarter('Any cyclone warning?')),
                _FishChip(label: 'Diving', onTap: ()=> onStarter('Is it safe for diving today?')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _FishChip extends StatelessWidget {
  final String label; final VoidCallback onTap;
  const _FishChip({required this.label, required this.onTap});
  @override
  Widget build(BuildContext context) => GestureDetector(onTap: onTap, child: Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6), decoration: BoxDecoration(color: const Color(0xFF00E5FF).withValues(alpha: 0.08), borderRadius: BorderRadius.circular(16), border: Border.all(color: const Color(0xFF00E5FF).withValues(alpha: 0.18))), child: Text(label, style: const TextStyle(color: Color(0xFF00E5FF), fontSize: 11))));
}

class _Composer extends StatelessWidget {
  final TextEditingController controller;
  final bool listening;
  final VoidCallback onSend;
  final VoidCallback onVoice;
  final VoidCallback onPickFile;
  final VoidCallback onToggleAgents;
  final bool showAgents;
  const _Composer({required this.controller, required this.listening, required this.onSend, required this.onVoice, required this.onPickFile, required this.onToggleAgents, required this.showAgents});
  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(builder: (context, state, _) {
      final modeLabel = state.getQueryModeLabel();
      return Container(
        padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
        decoration: BoxDecoration(color: const Color(0xFF0D1F3C), border: Border(top: BorderSide(color: const Color(0xFF00E5FF).withValues(alpha: 0.08)))),
        child: SafeArea(
          top: false,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Toolbar row: attach + routing pill + agent hint
              Row(
                children: [
                  IconButton(icon: const Icon(Icons.attach_file, color: Colors.white54, size: 18), onPressed: onPickFile, tooltip: 'Attach file'),
                  GestureDetector(
                    onTap: onToggleAgents,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(color: state.queryMode=='auto' ? const Color(0xFF00E5FF).withValues(alpha: 0.12) : state.queryMode=='panel' ? Colors.orange.withValues(alpha: 0.12) : Colors.purple.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(16), border: Border.all(color: state.queryMode=='auto' ? const Color(0xFF00E5FF).withValues(alpha: 0.3) : Colors.white12)),
                      child: Row(mainAxisSize: MainAxisSize.min, children: [
                        Text(state.queryMode=='auto' ? '✨' : state.queryMode=='panel' ? '💬' : '👤', style: const TextStyle(fontSize: 11)),
                        const SizedBox(width: 4),
                        Text(modeLabel, style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w600)),
                        const Icon(Icons.arrow_drop_down, color: Colors.white54, size: 14),
                      ]),
                    ),
                  ),
                  const Spacer(),
                  if (state.isQuerying)
                    IconButton(icon: const Icon(Icons.stop_circle, color: Color(0xFFFF1744)), onPressed: ()=> state.stopGeneration(), tooltip: 'Stop')
                  else
                    const SizedBox.shrink(),
                ],
              ),
              const SizedBox(height: 6),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  GestureDetector(
                    onTap: onVoice,
                    child: Container(width: 42,height:42,decoration: BoxDecoration(shape: BoxShape.circle, color: listening ? const Color(0xFFFF1744).withValues(alpha: 0.2) : const Color(0xFF00E5FF).withValues(alpha: 0.1), border: Border.all(color: listening ? const Color(0xFFFF1744) : const Color(0xFF00E5FF).withValues(alpha: 0.3))), child: Icon(listening ? Icons.mic : Icons.mic_none, color: listening ? const Color(0xFFFF1744) : const Color(0xFF00E5FF), size: 20)),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Container(
                      constraints: const BoxConstraints(minHeight: 42),
                      decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.05), borderRadius: BorderRadius.circular(21), border: Border.all(color: Colors.white.withValues(alpha: 0.1))),
                      child: TextField(
                        controller: controller,
                        style: const TextStyle(color: Colors.white, fontSize: 14),
                        maxLines: 4,
                        minLines: 1,
                        textInputAction: state.sendOnEnter ? TextInputAction.send : TextInputAction.newline,
                        onSubmitted: (_) { if (state.sendOnEnter) onSend(); },
                        onChanged: (v){ if(v.contains('@')){ /* could trigger agent mention */ }},
                        decoration: InputDecoration(
                          hintText: 'Ask anything, type @ for agents, or speak...',
                          hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.3), fontSize: 13),
                          border: InputBorder.none,
                          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  GestureDetector(
                    onTap: onSend,
                    child: Container(width: 42,height:42,decoration: const BoxDecoration(shape: BoxShape.circle, color: Color(0xFF00E5FF)), child: const Icon(Icons.arrow_upward, color: Color(0xFF0A1628), size: 18)),
                  ),
                ],
              ),
            ],
          ),
        ),
      );
    });
  }
}

class _AgentSheet extends StatelessWidget {
  final VoidCallback onClose;
  const _AgentSheet({required this.onClose});
  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(builder: (context, state, _) {
      return Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: const Color(0xFF0D1F3C), border: Border(top: BorderSide(color: Colors.white10))),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [const Text('How should ORCA answer?', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700)), const Spacer(), IconButton(icon: const Icon(Icons.close, color: Colors.white54, size: 16), onPressed: onClose)]),
            _ModeOption(selected: state.queryMode=='auto', icon: '✨', title: 'AUTO SELECT — ORCA picks best specialist(s)', desc: 'Fast intelligent routing — only needed agents run.', onTap: (){ state.setQueryMode('auto'); onClose(); }),
            _ModeOption(selected: state.queryMode=='panel', icon: '💬', title: 'ORCA Panel — full discussion', desc: 'Every relevant specialist runs, debates, then reconciles.', onTap: (){ state.setQueryMode('panel'); onClose(); }),
            const Divider(color: Colors.white10, height: 16),
            const Text('Ask one specialist directly', style: TextStyle(color: Colors.white54, fontSize: 10, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            ...state.backendAgents.map((a) => _ModeOption(selected: state.queryMode=='agent' && state.directAgentKey==a.key, icon: '👤', title: a.name, desc: a.description, onTap: (){ state.setQueryMode('agent'); state.setDirectAgent(a.key); onClose(); })),
          ],
        ),
      );
    });
  }
}

class _ModeOption extends StatelessWidget {
  final bool selected;
  final String icon;
  final String title;
  final String desc;
  final VoidCallback onTap;
  const _ModeOption({required this.selected, required this.icon, required this.title, required this.desc, required this.onTap});
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: selected ? const Color(0xFF00E5FF).withValues(alpha: 0.08) : Colors.white.withValues(alpha: 0.03), borderRadius: BorderRadius.circular(10), border: Border.all(color: selected ? const Color(0xFF00E5FF) : Colors.white10)),
        child: Row(children: [
          Text(icon, style: const TextStyle(fontSize: 16)),
          const SizedBox(width: 8),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: TextStyle(color: selected ? const Color(0xFF00E5FF) : Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text(desc, style: const TextStyle(color: Colors.white38, fontSize: 10)),
          ])),
          if (selected) const Icon(Icons.check_circle, color: Color(0xFF00E5FF), size: 16),
        ]),
      ),
    );
  }
}
