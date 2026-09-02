import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';
import '../models/query_response.dart';
import '../models/alert.dart';
import 'storage_service.dart';

class AgentSpec {
  final String key;
  final String name;
  final String description;
  final List<String> requires;
  AgentSpec({required this.key, required this.name, required this.description, required this.requires});
  factory AgentSpec.fromJson(Map<String, dynamic> j) => AgentSpec(
        key: j['key'] as String? ?? '',
        name: j['name'] as String? ?? '',
        description: j['description'] as String? ?? '',
        requires: (j['requires'] as List<dynamic>?)?.map((e) => e.toString()).toList() ?? [],
      );
}

class VizSeries {
  final Map<String, dynamic> series;
  final List<Map<String, dynamic>> exceedanceWindows;
  final List<Map<String, dynamic>> tides;
  VizSeries({required this.series, required this.exceedanceWindows, required this.tides});
  factory VizSeries.fromJson(Map<String, dynamic> j) => VizSeries(
        series: j['series'] as Map<String, dynamic>? ?? {},
        exceedanceWindows: (j['exceedance_windows'] as List<dynamic>?)?.map((e) => e as Map<String, dynamic>).toList() ?? [],
        tides: (j['tides'] as List<dynamic>?)?.map((e) => e as Map<String, dynamic>).toList() ?? [],
      );
}

class ApiService {
  final StorageService _storage;
  String get _baseUrl => _storage.baseUrl.isNotEmpty
      ? _storage.baseUrl
      : ApiConfig.deployedBaseUrl;

  Map<String, String> get _headers {
    final h = <String, String>{'Content-Type': 'application/json'};
    final key = _storage.apiKey;
    if (key.isNotEmpty) h['X-API-Key'] = key;
    return h;
  }

  ApiService(this._storage);

  Future<bool> checkHealth() async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/health'))
          .timeout(ApiConfig.healthTimeout);
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  // --- Core query ---
  Future<QueryResponse> query({
    required String text,
    List<double>? gps,
    List<double>? mapPoint,
    Map<String, dynamic>? destination,
    String? sessionId,
    String? mode,
    String? agent,
    String? queryDepth,
    String? fleetDemoLevel,
    String? windDemoScenario,
  }) async {
    final body = <String, dynamic>{
      'query': text,
      'mode': mode ?? 'auto',
      'vessel_class': _storage.vesselClass,
    };
    if (gps != null && gps.length == 2) body['device_gps'] = gps;
    if (mapPoint != null && mapPoint.length == 2) body['map_point'] = mapPoint;
    if (destination != null) body['destination'] = destination;
    if (sessionId != null) body['session_id'] = sessionId;
    if (agent != null && agent.isNotEmpty) body['agent'] = agent;
    if (queryDepth != null && queryDepth.isNotEmpty) body['query_depth'] = queryDepth;
    if (fleetDemoLevel != null && fleetDemoLevel.isNotEmpty) body['fleet_demo_level'] = fleetDemoLevel;
    if (windDemoScenario != null && windDemoScenario.isNotEmpty) body['wind_demo_scenario'] = windDemoScenario;

    try {
      final headers = Map<String, String>.from(_headers);
      final res = await http
          .post(
            Uri.parse('$_baseUrl/query'),
            headers: headers,
            body: jsonEncode(body),
          )
          .timeout(ApiConfig.queryTimeout);

      if (res.statusCode == 200) {
        final j = jsonDecode(res.body) as Map<String, dynamic>;
        _storage.cacheResponse(j);
        return QueryResponse.fromJson(j);
      } else {
        return QueryResponse(
          answer: 'Server error (${res.statusCode}). Please try again.',
          status: 'CAUTION',
        );
      }
    } on TimeoutException {
      return QueryResponse(
        answer: 'Backend unreachable (timeout). Check your connection and try again.',
        status: 'CAUTION',
      );
    } catch (_) {
      return QueryResponse(
        answer: 'Network error. Please check your connection.',
        status: 'CAUTION',
      );
    }
  }

  Future<QueryResponse> voiceQuery({
    required List<int> audioBytes,
    required String fileName,
    List<double>? gps,
    List<double>? mapPoint,
    String? sessionId,
    String? mode,
    String? agent,
  }) async {
    try {
      final uri = Uri.parse('$_baseUrl/query/voice');
      final request = http.MultipartRequest('POST', uri);
      // Backend expects field name `audio` (main.py: audio: UploadFile = File(...))
      request.files.add(http.MultipartFile.fromBytes(
        'audio',
        audioBytes,
        filename: fileName,
      ));
      request.fields['mode'] = mode ?? 'auto';
      if (agent != null && agent.isNotEmpty) request.fields['agent'] = agent;
      if (gps != null && gps.length == 2) {
        request.fields['device_gps'] = '${gps[0]},${gps[1]}';
      }
      if (mapPoint != null && mapPoint.length == 2) {
        request.fields['map_point'] = '${mapPoint[0]},${mapPoint[1]}';
      }
      if (sessionId != null) request.fields['session_id'] = sessionId;
      if (_storage.apiKey.isNotEmpty) request.headers['X-API-Key'] = _storage.apiKey;

      final streamed = await request.send().timeout(ApiConfig.queryTimeout);
      final res = await http.Response.fromStream(streamed);

      if (res.statusCode == 200) {
        final j = jsonDecode(res.body) as Map<String, dynamic>;
        _storage.cacheResponse(j);
        return QueryResponse.fromJson(j);
      } else {
        return QueryResponse(
          answer: 'Voice processing failed (${res.statusCode}).',
          status: 'CAUTION',
        );
      }
    } on TimeoutException {
      return QueryResponse(
        answer: 'Backend unreachable during voice query.',
        status: 'CAUTION',
      );
    } catch (_) {
      return QueryResponse(
        answer: 'Voice query failed. Please try again.',
        status: 'CAUTION',
      );
    }
  }

  // --- Agents registry ---
  Future<List<AgentSpec>> fetchAgents() async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/agents'), headers: _headers)
          .timeout(const Duration(seconds: 4));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final agents = data['agents'] as List<dynamic>? ?? [];
        return agents.map((e) => AgentSpec.fromJson(e as Map<String, dynamic>)).toList();
      }
      return [];
    } catch (_) {
      return [];
    }
  }

  // --- Viz ---
  Future<Map<String, dynamic>?> fetchVizGeojson(String sessionId) async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/viz/$sessionId'), headers: _headers)
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  Future<VizSeries?> fetchVizSeries(String sessionId) async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/viz/$sessionId/series'), headers: _headers)
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        return VizSeries.fromJson(data);
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  Future<Map<String, dynamic>?> fetchPfzLive() async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/api/pfz/live'), headers: _headers)
          .timeout(const Duration(seconds: 30));
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  // --- Fleet ---
  Future<Map<String, dynamic>?> getFleetStatus() async {
    try {
      final res = await http.get(Uri.parse('$_baseUrl/fleet/status'), headers: _headers).timeout(const Duration(seconds: 5));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return null;
    } catch (_) { return null; }
  }

  Future<Map<String, dynamic>?> simulateFleet({required String level, double? lat, double? lon, String? sessionId}) async {
    try {
      final body = <String, dynamic>{'level': level};
      if (lat != null) body['lat'] = lat;
      if (lon != null) body['lon'] = lon;
      if (sessionId != null) body['session_id'] = sessionId;
      final res = await http.post(Uri.parse('$_baseUrl/fleet/simulate'), headers: _headers, body: jsonEncode(body)).timeout(const Duration(seconds: 5));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return null;
    } catch (_) { return null; }
  }

  Future<void> clearFleet({bool simulatedOnly = true}) async {
    try {
      await http.post(Uri.parse('$_baseUrl/fleet/clear?simulated_only=$simulatedOnly'), headers: _headers).timeout(const Duration(seconds: 5));
    } catch (_) {}
  }

  // --- Satellite wind ---
  Future<Map<String, dynamic>?> getSatelliteWindStatus() async {
    try {
      final res = await http.get(Uri.parse('$_baseUrl/satellite-wind/status'), headers: _headers).timeout(const Duration(seconds: 5));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return null;
    } catch (_) { return null; }
  }

  Future<Map<String, dynamic>?> getSatelliteWindDivergence(double lat, double lon, {String? demoScenario}) async {
    try {
      final qs = 'lat=$lat&lon=$lon${demoScenario != null && demoScenario.isNotEmpty ? '&demo_scenario=$demoScenario' : ''}';
      final res = await http.get(Uri.parse('$_baseUrl/satellite-wind/divergence?$qs'), headers: _headers).timeout(const Duration(seconds: 5));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return null;
    } catch (_) { return null; }
  }

  // --- SAR ---
  Future<Map<String, dynamic>?> getSarStatus() async {
    try {
      final res = await http.get(Uri.parse('$_baseUrl/sar/status'), headers: _headers).timeout(const Duration(seconds: 5));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return null;
    } catch (_) { return null; }
  }

  Future<Map<String, dynamic>?> getSarDetections() async {
    try {
      final res = await http.get(Uri.parse('$_baseUrl/sar/detections'), headers: _headers).timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return null;
    } catch (_) { return null; }
  }

  Future<Map<String, dynamic>?> runSarScan({String provider = 'demo', Map<String, dynamic>? area, bool useCache = false}) async {
    try {
      final body = {'provider': provider, 'area': area, 'use_cache': useCache};
      final res = await http.post(Uri.parse('$_baseUrl/sar/scan'), headers: _headers, body: jsonEncode(body)).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return null;
    } catch (_) { return null; }
  }

  Future<Map<String, dynamic>?> runSarDemo() async {
    try {
      final res = await http.post(Uri.parse('$_baseUrl/sar/demo'), headers: _headers).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return null;
    } catch (_) { return null; }
  }

  Future<void> clearSar() async {
    try { await http.post(Uri.parse('$_baseUrl/sar/clear'), headers: _headers).timeout(const Duration(seconds: 4)); } catch (_) {}
  }

  // --- Users / alerts ---
  Future<void> registerUser({
    required String userId,
    required double lat,
    required double lon,
    String language = 'en',
  }) async {
    try {
      final res = await http
          .post(
            Uri.parse('$_baseUrl/users/register'),
            headers: _headers,
            body: jsonEncode({
              'user_id': userId,
              'lat': lat,
              'lon': lon,
              'name': '',
              'phone': '',
              'location_name': '',
              'language': language,
              'sms_critical_only': true,
            }),
          )
          .timeout(ApiConfig.healthTimeout);
      if (res.statusCode == 200) {
        _storage.alertsRegistered = true;
      }
    } catch (_) {}
  }

  Future<void> updatePosition({
    required String userId,
    required double lat,
    required double lon,
  }) async {
    try {
      await http
          .post(
            Uri.parse('$_baseUrl/users/$userId/position'),
            headers: _headers,
            body: jsonEncode({'lat': lat, 'lon': lon, 'location_name': ''}),
          )
          .timeout(ApiConfig.healthTimeout);
    } catch (_) {}
  }

  Future<List<OrcaAlert>> fetchAlerts(String userId) async {
    try {
      final res = await http
          .get(Uri.parse('$_baseUrl/alerts/$userId'), headers: _headers)
          .timeout(ApiConfig.healthTimeout);
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        if (data is List) {
          return data.map((e) => OrcaAlert.fromJson(e as Map<String, dynamic>)).toList();
        }
        if (data is Map && data.containsKey('alerts')) {
          return (data['alerts'] as List).map((e) => OrcaAlert.fromJson(e as Map<String, dynamic>)).toList();
        }
        return [];
      }
      return [];
    } catch (_) {
      return [];
    }
  }

  // SSE stub — for future live push. Currently polling is used.
  Stream<Map<String, dynamic>> subscribeAlertsSSE(String userId) async* {
    final client = http.Client();
    try {
      final request = http.Request('GET', Uri.parse('$_baseUrl/alerts/stream/$userId'));
      request.headers.addAll(_headers);
      request.headers['Accept'] = 'text/event-stream';
      final response = await client.send(request);
      final stream = response.stream.transform(utf8.decoder).transform(const LineSplitter());
      await for (final line in stream) {
        if (line.startsWith('data: ')) {
          final data = line.substring(6);
          try {
            yield jsonDecode(data) as Map<String, dynamic>;
          } catch (_) {}
        } else if (line.startsWith(':')) {
          // keep-alive
        }
      }
    } finally {
      client.close();
    }
  }
}
