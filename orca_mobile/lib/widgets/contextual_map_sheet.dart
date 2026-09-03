import 'package:flutter/material.dart';
import '../screens/map_screen.dart';

/// Opens the existing map implementation as a collapsible/expandable
/// contextual panel (draggable bottom sheet) instead of a separate
/// primary navigation section.
///
/// [focusPoint] is an optional real [lat, lon] pair — e.g. derived from
/// an AI response's geographic data — used to center the map. When null,
/// MapScreen falls back to its own existing default behavior.
Future<void> showContextualMap(
  BuildContext context, {
  List<double>? focusPoint,
  String? contextLabel,
}) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (ctx) {
      return DraggableScrollableSheet(
        initialChildSize: 0.75,
        minChildSize: 0.4,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) {
          return Container(
            decoration: const BoxDecoration(
              color: Color(0xFFF6FAFD),
              borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
            ),
            clipBehavior: Clip.antiAlias,
            child: Column(
              children: [
                const SizedBox(height: 8),
                Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: const Color(0xFFD1D5DB),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 10, 8, 6),
                  child: Row(
                    children: [
                      const Icon(Icons.map, color: Color(0xFF00626A), size: 18),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          contextLabel ?? 'Operational Picture',
                          style: const TextStyle(
                            color: Color(0xFF171C1F),
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close, color: Color(0xFF6E797A), size: 20),
                        onPressed: () => Navigator.of(ctx).pop(),
                      ),
                    ],
                  ),
                ),
                const Divider(height: 1, color: Color(0xFFE5E9EC)),
                Expanded(
                  child: MapScreen(focusPoint: focusPoint, embedded: true),
                ),
              ],
            ),
          );
        },
      );
    },
  );
}
