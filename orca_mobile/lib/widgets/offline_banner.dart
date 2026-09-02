import 'package:flutter/material.dart';

class OfflineBanner extends StatelessWidget {
  final bool isOnline;

  const OfflineBanner({super.key, required this.isOnline});

  @override
  Widget build(BuildContext context) {
    if (isOnline) return const SizedBox.shrink();

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      color: const Color(0xFFFF6D00).withValues(alpha: 0.85),
      child: const Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.wifi_off, size: 14, color: Colors.white),
          SizedBox(width: 6),
          Text(
            'Offline — showing cached data',
            style: TextStyle(
              color: Colors.white,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
