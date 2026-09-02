import 'package:flutter/material.dart';

class PresetQueryButton extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const PresetQueryButton({
    super.key,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: const Color(0xFF00E5FF).withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
            color: const Color(0xFF00E5FF).withValues(alpha: 0.25),
            width: 1,
          ),
        ),
        child: Text(
          label,
          style: const TextStyle(
            color: Color(0xFF00E5FF),
            fontSize: 13,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
    );
  }
}
