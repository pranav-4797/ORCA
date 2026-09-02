import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../state/app_state.dart';
import '../l10n/strings.dart';
import '../widgets/alert_tile.dart';
import '../widgets/offline_banner.dart';

class AlertsScreen extends StatefulWidget {
  const AlertsScreen({super.key});

  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

class _AlertsScreenState extends State<AlertsScreen> {
  @override
  void initState() {
    super.initState();
    final appState = context.read<AppState>();
    if (appState.alertsRegistered) {
      appState.startAlertPolling();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, appState, _) {
        final lang = appState.language;
        final activeAlerts =
            appState.alerts.where((a) => !a.dismissed).toList();

        return Scaffold(
          backgroundColor: const Color(0xFF0A1628),
          body: Column(
            children: [
              OfflineBanner(isOnline: appState.isOnline),
              Expanded(
                child: activeAlerts.isEmpty
                    ? _buildEmptyState(appState, lang)
                    : ListView.builder(
                        padding: const EdgeInsets.only(top: 12),
                        itemCount: activeAlerts.length,
                        itemBuilder: (ctx, i) {
                          return AlertTile(
                            alert: activeAlerts[i],
                            onDismiss: () =>
                                appState.dismissAlert(activeAlerts[i].id),
                          );
                        },
                      ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildEmptyState(AppState appState, String lang) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.notifications_none,
              size: 64,
              color: Colors.white.withValues(alpha: 0.08),
            ),
            const SizedBox(height: 16),
            Text(
              AppStrings.t('noAlerts', lang),
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.3),
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 12),
            if (!appState.alertsRegistered)
              TextButton.icon(
                onPressed: () {
                  if (appState.lat != null &&
                      appState.lon != null &&
                      appState.userId.isNotEmpty) {
                    appState.api.registerUser(
                      userId: appState.userId,
                      lat: appState.lat!,
                      lon: appState.lon!,
                      language: appState.language,
                    );
                    appState.startAlertPolling();
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(AppStrings.t('alertsEnabled', lang)),
                        backgroundColor: const Color(0xFF00C853),
                      ),
                    );
                  }
                },
                icon: const Icon(Icons.notifications_active,
                    color: Color(0xFF00E5FF)),
                label: Text(
                  AppStrings.t('registerForAlerts', lang),
                  style: const TextStyle(color: Color(0xFF00E5FF)),
                ),
              )
            else
              Text(
                'Monitoring for new alerts...',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.25),
                  fontSize: 13,
                ),
              ),
          ],
        ),
      ),
    );
  }
}
