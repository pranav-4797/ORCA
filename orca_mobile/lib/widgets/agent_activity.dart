import 'package:flutter/material.dart';
import '../state/app_state.dart';

class AgentActivityStrip extends StatelessWidget {
  final List<AgentActivityStep> steps;
  final String state;
  final String action;
  const AgentActivityStrip({super.key, required this.steps, required this.state, required this.action});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFFFF), // Cards / surfaces
        border: Border(bottom: BorderSide(color: const Color(0xFFE5E9EC))), // Subtle border
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(
                strokeWidth: 1.5,
                color: state == 'completed' ? const Color(0xFF00C853) : const Color(0xFF00626A), // Primary / brand
              ),
            ),
            const SizedBox(width: 8),
            Text(action, style: const TextStyle(color: Color(0xFF3E494A), fontSize: 11, fontWeight: FontWeight.w600)), // Secondary text
            const Spacer(),
            Text('${steps.length} steps', style: const TextStyle(color: Color(0xFF6E797A), fontSize: 10)), // Tertiary text
          ]),
          const SizedBox(height: 8),
          ...steps.take(4).map((s) => Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(children: [
              Container(
                width: 6,
                height: 6,
                decoration: BoxDecoration(
                  color: s.status == 'completed' ? const Color(0xFF00C853) : const Color(0xFF00626A), // Primary / brand
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(child: Text(s.title, style: const TextStyle(color: Color(0xFF3E494A), fontSize: 10), maxLines: 1, overflow: TextOverflow.ellipsis)), // Secondary text
              if (s.durationMs != null) Text('${s.durationMs}ms', style: const TextStyle(color: Color(0xFF6E797A), fontSize: 9)), // Tertiary text
            ]),
          )),
          if (steps.any((s) => s.description != null))
            ...steps.where((s) => s.description != null).take(2).map((s) => Padding(
              padding: const EdgeInsets.only(top: 2, left: 14),
              child: Text(s.description!, style: const TextStyle(color: Color(0xFF6E797A), fontSize: 10), maxLines: 2), // Tertiary text
            )),
        ],
      ),
    );
  }
}