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

  // Mobile breakpoint: below this width, the Agent Activity Strip is hidden.
  static const double _mobileBreakpoint = 600;

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
    _initSpeech();
  }

  Future<void> _initSpeech() async {
    try {
      _speechAvailable = await _speech.initialize(
        onError: (_) {
          if (mounted) setState(() => _listening = false);
        },
        onStatus: (s) {
          if (s == 'done' || s == 'notListening') {
            if (mounted) setState(() => _listening = false);
          }
        },
      );
    } catch (_) {
      _speechAvailable = false;
    }
  }

  void _scrollBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _send() {
    final text = _ctrl.text.trim();
    if (text.isEmpty) return;
    _ctrl.clear();
    context.read<AppState>().sendQuery(text);
    _scrollBottom();
  }

  Future<void> _voice() async {
    if (!_speechAvailable) return;
    if (_listening) {
      await _speech.stop();
      setState(() => _listening = false);
      return;
    }
    setState(() => _listening = true);
    String? recognized;
    final completer = Completer<void>();
    try {
      await _speech.listen(
        onResult: (r) {
          if (r.recognizedWords.isNotEmpty) recognized = r.recognizedWords;
          if (r.finalResult) {
            _speech.stop();
            setState(() => _listening = false);
            if (recognized != null && recognized!.isNotEmpty) {
              _ctrl.text = recognized!;
              _send();
            }
            if (!completer.isCompleted) completer.complete();
          }
        },
        listenOptions: stt.SpeechListenOptions(listenMode: stt.ListenMode.dictation),
      );
      Future.delayed(const Duration(seconds: 16), () {
        if (!completer.isCompleted) {
          _speech.stop();
          setState(() => _listening = false);
          if (recognized != null && recognized!.isNotEmpty) {
            _ctrl.text = recognized!;
            _send();
          }
          completer.complete();
        }
      });
    } catch (_) {
      setState(() => _listening = false);
    }
  }

  Future<void> _pickFile() async {
    final result = await FilePicker.platform.pickFiles(allowMultiple: false, withData: true);
    if (result != null && result.files.isNotEmpty) {
      final f = result.files.first;
      final size = f.size;
      final name = f.name;
      context.read<AppState>().showToast(
            'Attached $name (${(size / 1024).toStringAsFixed(1)} KB) — sent as context',
            'info',
          );
      _ctrl.text = '${_ctrl.text} [attached: $name]';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(builder: (context, state, _) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollBottom());
      final msgs = state.activeMessages;

      // Determine if we're on a mobile-sized viewport. The Agent Activity
      // Strip is intentionally suppressed on mobile without touching any
      // underlying execution state/logic.
      final isMobile = MediaQuery.of(context).size.width < _mobileBreakpoint;

      return Scaffold(
        backgroundColor: const Color(0xFFF6FAFD),
        body: SafeArea(
          child: Column(
            children: [
              // Header (status band only — title bar & nav are provided by the parent shell)
              const _TopAppHeader(),

              // Agent Activity Strip (hidden on mobile UI)
              if (!isMobile && state.executionState != 'idle' && state.executionSteps.isNotEmpty)
                AgentActivityStrip(
                  steps: state.executionSteps,
                  state: state.executionState,
                  action: state.currentAction,
                ),

              // Chat Message List or Empty State
              Expanded(
                child: msgs.isEmpty
                    ? _EmptyState(onStarter: (q) {
                        _ctrl.text = q;
                        _send();
                      })
                    : ListView.builder(
                        controller: _scroll,
                        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                        itemCount: msgs.length,
                        itemBuilder: (_, i) => ChatBubble(message: msgs[i]),
                      ),
              ),

              // Thinking Indicator
              if (state.isQuerying)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                  color: const Color(0xFFF6FAFD),
                  child: Row(
                    children: [
                      const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Color(0xFF00626A),
                        ),
                      ),
                      const SizedBox(width: 8),
                      const Text(
                        'ORCA is thinking...',
                        style: TextStyle(
                          color: Color(0xFF6E797A),
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),

              // Composer Dock
              _Composer(
                controller: _ctrl,
                listening: _listening,
                onSend: _send,
                onVoice: _voice,
                onPickFile: _pickFile,
                onToggleAgents: () => setState(() => _showAgents = !_showAgents),
                showAgents: _showAgents,
              ),

              // Agent Sheet Selector Overlay
              if (_showAgents) _AgentSheet(onClose: () => setState(() => _showAgents = false)),
            ],
          ),
        ),
      );
    });
  }

  @override
  void dispose() {
    _ctrl.dispose();
    _scroll.dispose();
    _speech.stop();
    super.dispose();
  }
}

class _TopAppHeader extends StatelessWidget {
  const _TopAppHeader();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: Color(0xFFE5E9EC))),
      ),
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: const BoxDecoration(
                  color: Color(0xFFF59E0B),
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 6),
              const Text(
                'Cached Satellite Fix (14m ago)',
                style: TextStyle(
                  color: Color(0xFFD97706),
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          ),
          const Text(
            '18.67°N, 73.88°E',
            style: TextStyle(
              color: Color(0xFF6E797A),
              fontSize: 11,
              fontFamily: 'monospace',
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final ValueChanged<String> onStarter;
  const _EmptyState({required this.onStarter});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Nautical Hero Emblem
            Stack(
              alignment: Alignment.center,
              children: [
                Container(
                  width: 72,
                  height: 72,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: const Color(0xFFDDFBFF).withOpacity(0.8),
                  ),
                ),
                Container(
                  width: 64,
                  height: 64,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: const Color(0xFFDDFBFF),
                    border: Border.all(color: const Color(0xFFBCEBF2)),
                  ),
                  child: const Icon(Icons.sailing, color: Color(0xFF00626A), size: 36),
                ),
              ],
            ),
            const SizedBox(height: 12),
            const Text(
              'Ask ORCA',
              style: TextStyle(
                color: Color(0xFF171C1F),
                fontSize: 20,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 4),
            const Text(
              'How can I assist you today?',
              style: TextStyle(
                color: Color(0xFF3E494A),
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 24),

            // 3 Suggested Cards
            _PromptCard(
              title: 'Is it safe to sail today?',
              onTap: () => onStarter('Is it safe to sail today?'),
            ),
            const SizedBox(height: 10),
            _PromptCard(
              title: 'Are there any nearby hazards?',
              onTap: () => onStarter('Are there any active cyclone or wave warnings near me?'),
            ),
            const SizedBox(height: 10),
            _PromptCard(
              title: 'Where is the nearest fishing zone?',
              onTap: () => onStarter('Where is the nearest official INCOIS Potential Fishing Zone (PFZ) today?'),
            ),

            const SizedBox(height: 20),

            // Quick Topic Filter Pills
            Wrap(
              spacing: 8,
              runSpacing: 8,
              alignment: WrapAlignment.center,
              children: [
                _TopicPill(label: 'PFZ', onTap: () => onStarter('Where is the nearest fishing zone?')),
                _TopicPill(label: 'Waves', onTap: () => onStarter('What is wave height today?')),
                _TopicPill(label: 'Cyclone', onTap: () => onStarter('Any cyclone warning?')),
                _TopicPill(label: 'Safe Route', onTap: () => onStarter('Plot a safe navigational route.')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _PromptCard extends StatelessWidget {
  final String title;
  final VoidCallback onTap;

  const _PromptCard({
    required this.title,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: const Color(0xFFE5E9EC)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.02),
              blurRadius: 4,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Expanded(
              child: Text(
                title,
                style: const TextStyle(
                  color: Color(0xFF171C1F),
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            Container(
              width: 24,
              height: 24,
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFB),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFE5E9EC)),
              ),
              child: const Icon(Icons.chevron_right, color: Color(0xFF6E797A), size: 16),
            ),
          ],
        ),
      ),
    );
  }
}

class _TopicPill extends StatelessWidget {
  final String label;
  final VoidCallback onTap;
  const _TopicPill({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: const Color(0xFFE5E9EC)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.02),
              blurRadius: 2,
            ),
          ],
        ),
        child: Text(
          label,
          style: const TextStyle(
            color: Color(0xFF00626A),
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  final TextEditingController controller;
  final bool listening;
  final VoidCallback onSend;
  final VoidCallback onVoice;
  final VoidCallback onPickFile;
  final VoidCallback onToggleAgents;
  final bool showAgents;

  const _Composer({
    required this.controller,
    required this.listening,
    required this.onSend,
    required this.onVoice,
    required this.onPickFile,
    required this.onToggleAgents,
    required this.showAgents,
  });

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(builder: (context, state, _) {
      final modeLabel = state.getQueryModeLabel();
      return Container(
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
        decoration: const BoxDecoration(
          color: Colors.white,
          border: Border(top: BorderSide(color: Color(0xFFE5E9EC))),
          boxShadow: [
            BoxShadow(
              color: Color(0x05000000),
              blurRadius: 10,
              offset: Offset(0, -2),
            ),
          ],
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Top Control Row
            Row(
              children: [
                IconButton(
                  icon: const Icon(Icons.attach_file, color: Color(0xFF3E494A), size: 20),
                  onPressed: onPickFile,
                  tooltip: 'Attach file',
                ),
                GestureDetector(
                  onTap: onToggleAgents,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: const Color(0xFFDDFBFF),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: const Color(0xFFBCEBF2)),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Text('✨', style: TextStyle(fontSize: 12)),
                        const SizedBox(width: 4),
                        Text(
                          modeLabel.toUpperCase(),
                          style: const TextStyle(
                            color: Color(0xFF00626A),
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const Icon(Icons.keyboard_arrow_down, color: Color(0xFF00626A), size: 16),
                      ],
                    ),
                  ),
                ),
                const Spacer(),
                if (state.isQuerying)
                  IconButton(
                    icon: const Icon(Icons.stop_circle, color: Color(0xFFEF4444)),
                    onPressed: () => state.stopGeneration(),
                    tooltip: 'Stop',
                  ),
              ],
            ),
            const SizedBox(height: 6),
            // Input Row
            Row(
              children: [
                GestureDetector(
                  onTap: onVoice,
                  child: Container(
                    width: 44,
                    height: 44,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: listening
                          ? const Color(0xFFFEE2E2)
                          : const Color(0xFFF8FAFB),
                      border: Border.all(
                        color: listening ? const Color(0xFFEF4444) : const Color(0xFFE5E9EC),
                      ),
                    ),
                    child: Icon(
                      listening ? Icons.mic : Icons.mic_none,
                      color: listening ? const Color(0xFFEF4444) : const Color(0xFF00626A),
                      size: 20,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF8FAFB),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: const Color(0xFFE5E9EC)),
                    ),
                    child: TextField(
                      controller: controller,
                      style: const TextStyle(color: Color(0xFF171C1F), fontSize: 14),
                      maxLines: 4,
                      minLines: 1,
                      textInputAction: state.sendOnEnter
                          ? TextInputAction.send
                          : TextInputAction.newline,
                      onSubmitted: (_) {
                        if (state.sendOnEnter) onSend();
                      },
                      decoration: const InputDecoration(
                        hintText: 'Ask anything, type @ for agents...',
                        hintStyle: TextStyle(color: Color(0xFF6E797A), fontSize: 13),
                        border: InputBorder.none,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                GestureDetector(
                  onTap: onSend,
                  child: Container(
                    width: 44,
                    height: 44,
                    decoration: const BoxDecoration(
                      shape: BoxShape.circle,
                      color: Color(0xFF0E7C86),
                    ),
                    child: const Icon(
                      Icons.arrow_upward,
                      color: Colors.white,
                      size: 20,
                    ),
                  ),
                ),
              ],
            ),
          ],
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
        decoration: const BoxDecoration(
          color: Colors.white,
          border: Border(top: BorderSide(color: Color(0xFFE5E9EC))),
          boxShadow: [
            BoxShadow(
              color: Color(0x10000000),
              blurRadius: 10,
              offset: Offset(0, -4),
            ),
          ],
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Text(
                  'How should ORCA answer?',
                  style: TextStyle(
                    color: Color(0xFF171C1F),
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close, color: Color(0xFF6E797A), size: 16),
                  onPressed: onClose,
                ),
              ],
            ),
            _ModeOption(
              selected: state.queryMode == 'auto',
              icon: '✨',
              title: 'AUTO SELECT — ORCA picks best specialist(s)',
              desc: 'Fast intelligent routing — only needed agents run.',
              onTap: () {
                state.setQueryMode('auto');
                onClose();
              },
            ),
            _ModeOption(
              selected: state.queryMode == 'panel',
              icon: '💬',
              title: 'ORCA Panel — full discussion',
              desc: 'Every relevant specialist runs, debates, then reconciles.',
              onTap: () {
                state.setQueryMode('panel');
                onClose();
              },
            ),
            const Divider(color: Color(0xFFE5E9EC), height: 16),
            const Text(
              'Ask one specialist directly',
              style: TextStyle(
                color: Color(0xFF6E797A),
                fontSize: 10,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 6),
            ...state.backendAgents.map(
              (a) => _ModeOption(
                selected: state.queryMode == 'agent' && state.directAgentKey == a.key,
                icon: '👤',
                title: a.name,
                desc: a.description,
                onTap: () {
                  state.setQueryMode('agent');
                  state.setDirectAgent(a.key);
                  onClose();
                },
              ),
            ),
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

  const _ModeOption({
    required this.selected,
    required this.icon,
    required this.title,
    required this.desc,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: selected
              ? const Color(0xFFDDFBFF)
              : const Color(0xFFF8FAFB),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: selected ? const Color(0xFF00626A) : const Color(0xFFE5E9EC),
          ),
        ),
        child: Row(
          children: [
            Text(icon, style: const TextStyle(fontSize: 16)),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: TextStyle(
                      color: selected ? const Color(0xFF00626A) : const Color(0xFF171C1F),
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    desc,
                    style: const TextStyle(color: Color(0xFF6E797A), fontSize: 10),
                  ),
                ],
              ),
            ),
            if (selected) const Icon(Icons.check_circle, color: Color(0xFF00626A), size: 16),
          ],
        ),
      ),
    );
  }
}