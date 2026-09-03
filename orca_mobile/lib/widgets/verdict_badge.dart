import 'package:flutter/material.dart';

class VerdictBadge extends StatelessWidget {
  final String status;

  const VerdictBadge({super.key, required this.status});

  Color get _color {
    switch (status.toUpperCase()) {
      case 'SAFE':
        return const Color(0xFF00C853);
      case 'CAUTION':
        return const Color(0xFFFFD600);
      case 'UNSAFE':
        return const Color(0xFFFF6D00);
      case 'EXTREME':
      case 'CRITICAL':
        return const Color(0xFFFF1744);
      default:
        return const Color(0xFF6E797A); // Tertiary/muted grey
    }
  }

  IconData get _icon {
    switch (status.toUpperCase()) {
      case 'SAFE':
        return Icons.check_circle;
      case 'CAUTION':
        return Icons.warning;
      case 'UNSAFE':
        return Icons.dangerous;
      case 'EXTREME':
      case 'CRITICAL':
        return Icons.error;
      default:
        return Icons.help_outline;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: _color.withValues(alpha: 0.2),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _color, width: 1.5),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(_icon, color: _color, size: 16),
          const SizedBox(width: 4),
          Text(
            status.toUpperCase(),
            style: TextStyle(
              color: _color,
              fontSize: 12,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}