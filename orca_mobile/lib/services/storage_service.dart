import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

class StorageService {
  static const _keyBaseUrl = 'orca_base_url';
  static const _keyApiKey = 'orca_api_key';
  static const _keyLanguage = 'orca_language';
  static const _keyVesselClass = 'orca_vessel_class';
  static const _keyUserId = 'orca_user_id';
  static const _keyLastResponse = 'orca_last_response';
  static const _keyLastLat = 'orca_last_lat';
  static const _keyLastLon = 'orca_last_lon';
  static const _keyAlertsRegistered = 'orca_alerts_registered';
  static const _keyQueryMode = 'orca_query_mode';
  static const _keyDirectAgent = 'orca_direct_agent';
  static const _keyFleetDemo = 'orca_fleet_demo_level';
  static const _keyWindDemo = 'orca_wind_demo_scenario';
  static const _keySendOnEnter = 'orca_send_on_enter';
  static const _keyAudioFeedback = 'orca_audio_feedback';
  static const _keyChatHistory = 'orca_chat_history';

  late SharedPreferences _prefs;
  SharedPreferences? get prefs => _prefs;
  SharedPreferences get prefsSync => _prefs;

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
  }

  String get baseUrl => _prefs.getString(_keyBaseUrl) ?? '';
  set baseUrl(String v) => _prefs.setString(_keyBaseUrl, v);

  String get apiKey => _prefs.getString(_keyApiKey) ?? '';
  set apiKey(String v) => _prefs.setString(_keyApiKey, v);

  String get language => _prefs.getString(_keyLanguage) ?? 'en';
  set language(String v) => _prefs.setString(_keyLanguage, v);

  String get vesselClass => _prefs.getString(_keyVesselClass) ?? 'small_fishing_boat';
  set vesselClass(String v) => _prefs.setString(_keyVesselClass, v);

  String? get userId => _prefs.getString(_keyUserId);
  set userId(String? v) {
    if (v != null) {
      _prefs.setString(_keyUserId, v);
    }
  }

  String get lastResponseJson => _prefs.getString(_keyLastResponse) ?? '';
  set lastResponseJson(String v) => _prefs.setString(_keyLastResponse, v);

  double get lastLat => _prefs.getDouble(_keyLastLat) ?? 0.0;
  double get lastLon => _prefs.getDouble(_keyLastLon) ?? 0.0;
  void saveLastPosition(double lat, double lon) {
    _prefs.setDouble(_keyLastLat, lat);
    _prefs.setDouble(_keyLastLon, lon);
  }

  bool get alertsRegistered => _prefs.getBool(_keyAlertsRegistered) ?? false;
  set alertsRegistered(bool v) => _prefs.setBool(_keyAlertsRegistered, v);

  String get queryMode => _prefs.getString(_keyQueryMode) ?? 'auto';
  set queryMode(String v) => _prefs.setString(_keyQueryMode, v);

  String get directAgent => _prefs.getString(_keyDirectAgent) ?? '';
  set directAgent(String v) => _prefs.setString(_keyDirectAgent, v);

  String get fleetDemoLevel => _prefs.getString(_keyFleetDemo) ?? '';
  set fleetDemoLevel(String v) => _prefs.setString(_keyFleetDemo, v);

  String get windDemoScenario => _prefs.getString(_keyWindDemo) ?? '';
  set windDemoScenario(String v) => _prefs.setString(_keyWindDemo, v);

  bool get sendOnEnter => _prefs.getBool(_keySendOnEnter) ?? true;
  set sendOnEnter(bool v) => _prefs.setBool(_keySendOnEnter, v);

  bool get audioFeedback => _prefs.getBool(_keyAudioFeedback) ?? true;
  set audioFeedback(bool v) => _prefs.setBool(_keyAudioFeedback, v);

  String get chatHistoryJson => _prefs.getString(_keyChatHistory) ?? '';
  set chatHistoryJson(String v) => _prefs.setString(_keyChatHistory, v);

  Map<String, dynamic>? getCachedResponse() {
    final raw = lastResponseJson;
    if (raw.isEmpty) return null;
    try {
      return jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  void cacheResponse(Map<String, dynamic> json) {
    lastResponseJson = jsonEncode(json);
  }
}
