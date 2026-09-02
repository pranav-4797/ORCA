class ApiConfig {
  static const String defaultBaseUrl = 'http://localhost:8000';
  static const String deployedBaseUrl =
      'https://orca-backend-1i5u.onrender.com';

  static const Duration queryTimeout = Duration(seconds: 15);
  static const Duration healthTimeout = Duration(seconds: 5);
  static const Duration alertPollInterval = Duration(seconds: 90);
  static const Duration positionUpdateInterval = Duration(minutes: 3);

  static const int maxRetries = 2;
}
