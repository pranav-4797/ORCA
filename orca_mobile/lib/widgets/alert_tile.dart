import 'package:flutter/material.dart';
import '../models/alert.dart';

class AlertTile extends StatelessWidget {
  final OrcaAlert alert;
  final VoidCallback? onDismiss;

  const AlertTile({super.key, required this.alert, this.onDismiss});

  Color get _color {
    switch (alert.severity.toUpperCase()) {
      case 'SAFE':
        return const Color(0xFF00C853);
      case 'CAUTION':
      case 'WARNING':
        return const Color(0xFFFFD600);
      case 'UNSAFE':
        return const Color(0xFFFF6D00);
      case 'EXTREME':
      case 'CRITICAL':
        return const Color(0xFFFF1744);
      default:
        return const Color(0xFF90A4AE);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (alert.dismissed) return const SizedBox.shrink();

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _color.withValues(alpha: 0.4), width: 1),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: _color.withValues(alpha: 0.2),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(
              _severityIcon,
              color: _color,
              size: 20,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  alert.severity.toUpperCase(),
                  style: TextStyle(
                    color: _color,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.5,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  alert.message,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.85),
                    fontSize: 14,
                    height: 1.3,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  _formatTime(alert.timestamp),
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.35),
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          if (onDismiss != null)
            GestureDetector(
              onTap: onDismiss,
              child: Icon(
                Icons.close,
                size: 18,
                color: Colors.white.withValues(alpha: 0.4),
              ),
            ),
        ],
      ),
    );
  }

  IconData get _severityIcon {
    switch (alert.severity.toUpperCase()) {
      case 'SAFE':
        return Icons.check_circle_outline;
      case 'CAUTION':
      case 'WARNING':
        return Icons.warning_amber;
      case 'UNSAFE':
        return Icons.dangerous_outlined;
      case 'EXTREME':
      case 'CRITICAL':
        return Icons.error_outline;
      default:
        return Icons.info_outline;
    }
  }

  String _formatTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inHours < 1) return '${diff.inMinutes}m ago';
    if (diff.inDays < 1) return '${diff.inHours}h ago';
    return '${dt.day}/${dt.month} ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
  }
}
