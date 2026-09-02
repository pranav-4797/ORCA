class OrcaAlert {
  final String id;
  final String message;
  final String severity;
  final DateTime timestamp;
  final bool dismissed;
  final String title;

  OrcaAlert({
    required this.id,
    required this.message,
    required this.severity,
    required this.timestamp,
    this.dismissed = false,
    this.title = '',
  });

  factory OrcaAlert.fromJson(Map<String, dynamic> json) {
    // Backend Alert.as_dict() uses title/message/severity; poll wraps {alerts:[...]}
    final msg = (json['message'] as String?) ??
        (json['title'] as String?) ??
        (json['content'] as String?) ??
        '';
    final sev = (json['severity'] as String?) ??
        (json['level'] as String?) ??
        (json['status'] as String?) ??
        'INFO';
    final id = (json['id'] as String?) ??
        (json['alert_id'] as String?) ??
        DateTime.now().millisecondsSinceEpoch.toString();
    DateTime ts;
    if (json['timestamp'] != null) {
      if (json['timestamp'] is num) {
        ts = DateTime.fromMillisecondsSinceEpoch((json['timestamp'] as num).toInt() * 1000);
      } else {
        ts = DateTime.tryParse(json['timestamp'].toString()) ?? DateTime.now();
      }
    } else if (json['server_time'] != null) {
      final st = json['server_time'];
      if (st is num) {
        ts = DateTime.fromMillisecondsSinceEpoch((st * 1000).toInt());
      } else {
        ts = DateTime.now();
      }
    } else {
      ts = DateTime.now();
    }
    return OrcaAlert(
      id: id,
      message: msg,
      severity: sev,
      timestamp: ts,
      title: json['title'] as String? ?? '',
    );
  }

  OrcaAlert copyWith({bool? dismissed}) {
    return OrcaAlert(
      id: id,
      message: message,
      severity: severity,
      timestamp: timestamp,
      dismissed: dismissed ?? this.dismissed,
      title: title,
    );
  }
}
