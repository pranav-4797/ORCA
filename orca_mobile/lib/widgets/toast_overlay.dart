import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';

class ToastOverlay extends StatelessWidget {
  const ToastOverlay({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, state, _) {
        if (state.toastMessage == null) return const SizedBox.shrink();
        Color bg;
        switch (state.toastType) {
          case 'error': bg = const Color(0xFFFF1744); break;
          case 'success': bg = const Color(0xFF00C853); break;
          default: bg = const Color(0xFF1A237E);
        }
        return Positioned(
          top: 12,
          left: 16,
          right: 16,
          child: Material(
            color: Colors.transparent,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(12), boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.2), blurRadius: 8)]),
              child: Row(
                children: [
                  Icon(state.toastType == 'error' ? Icons.error_outline : state.toastType == 'success' ? Icons.check_circle_outline : Icons.info_outline, color: Colors.white, size: 18),
                  const SizedBox(width: 8),
                  Expanded(child: Text(state.toastMessage!, style: const TextStyle(color: Colors.white, fontSize: 13))),
                  GestureDetector(onTap: () => state.clearToast(), child: const Icon(Icons.close, color: Colors.white70, size: 16)),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
