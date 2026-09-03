import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';
import '../models/query_response.dart';
import '../models/alert.dart';
import '../models/chat.dart';
import '../models/user_category.dart';
import '../services/api_service.dart';
import '../services/storage_service.dart';
import '../services/tts_service.dart';
import '../config/api_config.dart';

class AgentActivityStep {
  final String id;
  final String title;
  final String? description;
  final String status; // pending | in_progress | completed | error
  final int? durationMs;
  final int timestamp;
  AgentActivityStep({
    required this.id,
    required this.title,
    this.description,
    required this.status,
    this.durationMs,
    required this.timestamp,
  });
  Map<String, dynamic> toJson() => {'id':id,'title':title,'description':description,'status':status,'durationMs':durationMs,'timestamp':timestamp};
  factory AgentActivityStep.fromJson(Map<String, dynamic> j) => AgentActivityStep(id: j['id'], title: j['title'], description: j['description'], status: j['status'], durationMs: j['durationMs'], timestamp: j['timestamp']);
}

class ChatMessage {
  final String id;
  final String chatId;
  final String role; // user | assistant | system
  String content;
  final int timestamp;
  String? status;
  String? answeredBy;
  List<AgentActivityStep> activitySteps;
  Map<String, dynamic>? tokens;
  Map<String, dynamic>? autoRouting;
  Map<String, dynamic>? fleetConvergence;
  Map<String, dynamic>? windDivergence;
  List<String> reasoning;
  String? transcribedText;
  bool isStreaming;
  String? agentId;
  String? modelUsed;
  // The viz/session id whose geojson corresponds to this response, so a
  // "View in Map" tap can re-center the contextual map on the right data.
  String? vizSessionId;

  ChatMessage({
    required this.id,
    required this.chatId,
    required this.role,
    required this.content,
    required this.timestamp,
    this.status,
    this.answeredBy,
    this.activitySteps = const [],
    this.tokens,
    this.autoRouting,
    this.fleetConvergence,
    this.windDivergence,
    this.reasoning = const [],
    this.transcribedText,
    this.isStreaming = false,
    this.agentId,
    this.modelUsed,
    this.vizSessionId,
  });

  // Compatibility getters for old code
  String get text => content;
  bool get isUser => role == 'user';
  bool get isVoice => transcribedText != null;

  Map<String, dynamic> toJson() => {
        'id': id,
        'chatId': chatId,
        'role': role,
        'content': content,
        'timestamp': timestamp,
        'status': status,
        'answeredBy': answeredBy,
        'activitySteps': activitySteps.map((e) => e.toJson()).toList(),
        'tokens': tokens,
        'autoRouting': autoRouting,
        'fleetConvergence': fleetConvergence,
        'windDivergence': windDivergence,
        'reasoning': reasoning,
        'transcribedText': transcribedText,
        'isStreaming': isStreaming,
        'agentId': agentId,
        'modelUsed': modelUsed,
        'vizSessionId': vizSessionId,
      };

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
        id: j['id'] as String,
        chatId: j['chatId'] as String,
        role: j['role'] as String,
        content: j['content'] as String,
        timestamp: j['timestamp'] as int,
        status: j['status'] as String?,
        answeredBy: j['answeredBy'] as String?,
        activitySteps: (j['activitySteps'] as List<dynamic>?)?.map((e) => AgentActivityStep.fromJson(e as Map<String, dynamic>)).toList() ?? [],
        tokens: j['tokens'] as Map<String, dynamic>?,
        autoRouting: j['autoRouting'] as Map<String, dynamic>?,
        fleetConvergence: j['fleetConvergence'] as Map<String, dynamic>?,
        windDivergence: j['windDivergence'] as Map<String, dynamic>?,
        reasoning: (j['reasoning'] as List<dynamic>?)?.map((e) => e.toString()).toList() ?? [],
        transcribedText: j['transcribedText'] as String?,
        isStreaming: j['isStreaming'] as bool? ?? false,
        agentId: j['agentId'] as String?,
        modelUsed: j['modelUsed'] as String?,
        vizSessionId: j['vizSessionId'] as String?,
      );
}

class AppState extends ChangeNotifier {
  final ApiService api;
  final StorageService storage;
  final TtsService tts;

  AppState({required this.api, required this.storage, required this.tts});

  // --- Backend ---
  bool _isOnline = false;
  bool get isOnline => _isOnline;
  bool? backendOnline;

  // --- Location ---
  double? _lat;
  double? _lon;
  double? get lat => _lat;
  double? get lon => _lon;
  bool _locationGranted = false;
  bool get locationGranted => _locationGranted;
  List<double>? get gpsCoords => _lat != null && _lon != null ? [_lat!, _lon!] : null;
  List<double>? _mapPoint;
  List<double>? get mapPoint => _mapPoint;
  String _gpsStatus = 'none'; // granted | denied | cached | none
  String get gpsStatus => _gpsStatus;

  // --- Session / chat ---
  String? _sessionId;
  String? get sessionId => _sessionId;
  List<Chat> chats = [];
  Map<String, List<ChatMessage>> messages = {};
  String? activeChatId;
  bool _isQuerying = false;
  bool get isQuerying => _isQuerying;
  bool get isStreaming => _isQuerying;

  // Execution state for AgentPanel
  List<AgentActivityStep> executionSteps = [];
  String executionState = 'idle'; // idle | thinking | executing | completed | error
  String currentAction = 'Ready to assist';

  // --- Viz ---
  Map<String, dynamic>? vizGeojson;
  Map<String, dynamic>? vizSeries;
  String? vizSessionId;
  bool mapPanelOpen = true;
  Map<String, dynamic>? pfzLive;
  int pfzLiveLoadedAt = 0;

  // --- Routing ---
  String queryMode = 'auto'; // auto | panel | agent
  String directAgentKey = '';
  List<AgentSpec> backendAgents = [
    AgentSpec(key: 'ocean_state', name: 'Ocean-State Agent', description: 'Live SST, waves, wind, tides and chlorophyll', requires: []),
    AgentSpec(key: 'hazard', name: 'Hazard Agent', description: 'Safety verdicts + live IMD cyclone/marine alerts', requires: ['ocean_state']),
    AgentSpec(key: 'pfz', name: 'PFZ Agent', description: 'Nearest fishing zones from live thermal fronts', requires: []),
    AgentSpec(key: 'geospatial', name: 'Geospatial Agent', description: 'Boundary geofencing + weather-aware safe routes', requires: []),
    AgentSpec(key: 'trend', name: 'Trend Agent', description: 'Months-long SST/chlorophyll trend analysis', requires: []),
  ];

  // --- Alerts ---
  List<OrcaAlert> _alerts = [];
  List<OrcaAlert> get alerts => List.unmodifiable(_alerts);
  Timer? _alertTimer;
  _PositionTimer? _positionTimer;

  // --- Auth mock ---
  Map<String, dynamic>? currentUser; // {uid, displayName, email}
  bool authInitialized = true;
  bool isSelectingRole = false;
  UserCategoryProfile? userCategory;
  int get guestCount {
    int c = 0;
    for (final list in messages.values) {
      c += list.where((m) => m.role == 'user').length;
    }
    return c;
  }
  bool get isGuestLimitReached => currentUser == null && guestCount >= 3;

  // --- Settings ---
  String get language => storage.language;
  set language(String v) { storage.language = v; notifyListeners(); }
  String get vesselClass => storage.vesselClass;
  set vesselClass(String v) { storage.vesselClass = v; notifyListeners(); }
  String get baseUrl => storage.baseUrl;
  set baseUrl(String v) { storage.baseUrl = v; notifyListeners(); }
  String get userId => storage.userId ?? '';
  bool get alertsRegistered => storage.alertsRegistered;
  String get fleetDemoLevel => storage.fleetDemoLevel;
  String get windDemoScenario => storage.windDemoScenario;

  // UI toggles
  bool get sendOnEnter => storage.sendOnEnter;
  set sendOnEnter(bool v) { storage.sendOnEnter = v; notifyListeners(); }
  bool get audioFeedback => storage.audioFeedback;
  set audioFeedback(bool v) { storage.audioFeedback = v; tts.setEnabled(v); notifyListeners(); }

  String activeLanguage = 'en';
  String activeNavTab = 'chat'; // overview | chat | sar | system
  bool sidebarCollapsed = true;
  bool searchModalOpen = false;
  bool settingsModalOpen = false;

  // Toast
  String? toastMessage;
  String toastType = 'info';

  Future<void> init() async {
    await storage.init();
    await tts.init();
    tts.setEnabled(storage.audioFeedback);
    if (storage.userId == null) storage.userId = const Uuid().v4();
    _sessionId = 'mobile_${storage.userId}';
    queryMode = storage.queryMode;
    directAgentKey = storage.directAgent;
    activeLanguage = storage.language;
    // Load chats
    _loadChats();
    if (chats.isEmpty) {
      final id = const Uuid().v4();
      chats = [Chat(id: id, title: 'Mission Briefing', createdAt: DateTime.now().millisecondsSinceEpoch, updatedAt: DateTime.now().millisecondsSinceEpoch, agentId: 'general', model: 'llama-3.3-70b-versatile')];
      messages[id] = [];
      activeChatId = id;
    }
    if (activeChatId == null && chats.isNotEmpty) activeChatId = chats.first.id;
    // Load cached response if no messages
    if (messages[activeChatId]?.isEmpty ?? true) {
      final cached = storage.getCachedResponse();
      if (cached != null) {
        final resp = QueryResponse.fromJson(cached);
        final mid = const Uuid().v4();
        messages[activeChatId!] = [
          ChatMessage(id: mid, chatId: activeChatId!, role: 'assistant', content: resp.answer, timestamp: DateTime.now().millisecondsSinceEpoch, status: resp.status, reasoning: resp.reasoning, answeredBy: resp.answeredBy),
        ];
      }
    }
    // Load user category
    final catJson = storage.prefs?.getString('orca_user_category');
    if (catJson != null) {
      try { userCategory = UserCategoryProfile.fromJson(jsonDecode(catJson)); } catch(_){}
    }
    _checkHealth();
    Timer.periodic(const Duration(seconds: 30), (_) => _checkHealth());
    // Fetch agents when online
    if (_isOnline) fetchBackendAgents();
    // Preload GPS from storage
    if (storage.lastLat != 0 || storage.lastLon != 0) {
      _lat = storage.lastLat;
      _lon = storage.lastLon;
      if (_lat != 0 && _lon != 0) {
        _gpsStatus = 'cached';
        _locationGranted = true;
      }
    }
    notifyListeners();
  }

  void _loadChats() {
    final raw = storage.chatHistoryJson;
    if (raw.isEmpty) {
      // No saved
      return;
    }
    try {
      final data = jsonDecode(raw) as Map<String, dynamic>;
      final cList = (data['chats'] as List<dynamic>?) ?? [];
      chats = cList.map((e) => Chat.fromJson(e as Map<String, dynamic>)).toList();
      final mMap = data['messages'] as Map<String, dynamic>? ?? {};
      messages = {};
      mMap.forEach((k,v) {
        messages[k] = (v as List<dynamic>).map((e) => ChatMessage.fromJson(e as Map<String, dynamic>)).toList();
      });
      activeChatId = data['activeChatId'] as String?;
    } catch(_) {}
  }

  void _saveChats() {
    final data = {
      'chats': chats.map((c) => c.toJson()).toList(),
      'messages': messages.map((k,v) => MapEntry(k, v.map((m) => m.toJson()).toList())),
      'activeChatId': activeChatId,
    };
    storage.chatHistoryJson = jsonEncode(data);
  }

  void _checkHealth() async {
    final wasOnline = _isOnline;
    _isOnline = await api.checkHealth();
    backendOnline = _isOnline;
    if (_isOnline && wasOnline != _isOnline) {
      fetchBackendAgents();
      loadPfzLive();
    }
    if (wasOnline != _isOnline) notifyListeners();
  }

  Future<void> fetchBackendAgents() async {
    final agents = await api.fetchAgents();
    if (agents.isNotEmpty) {
      backendAgents = agents;
      if (!backendAgents.any((a) => a.key == directAgentKey)) {
        directAgentKey = backendAgents.first.key;
      }
      notifyListeners();
    }
  }

  Future<void> loadPfzLive() async {
    final data = await api.fetchPfzLive();
    if (data != null) {
      pfzLive = data;
      pfzLiveLoadedAt = DateTime.now().millisecondsSinceEpoch;
      notifyListeners();
    }
  }

  Future<void> loadViz(String sid) async {
    try {
      final geo = await api.fetchVizGeojson(sid);
      final series = await api.fetchVizSeries(sid);
      if (geo != null) vizGeojson = geo;
      if (series != null) {
        vizSeries = {'series': series.series, 'exceedance_windows': series.exceedanceWindows, 'tides': series.tides};
      }
      vizSessionId = sid;
      mapPanelOpen = true;
      notifyListeners();
    } catch(_) {}
  }

  // Derives a real [lat, lon] focus point from the currently loaded viz
  // geojson (query point / PFZ / hazard / fleet / SAR markers, in priority
  // order) so the contextual map can center on actual returned data.
  // Returns null when nothing usable is loaded — never fabricates coords.
  List<double>? focusPointFromViz({String? preferredKind}) {
    final geo = vizGeojson;
    final features = geo?['features'] as List<dynamic>?;
    if (features == null || features.isEmpty) return mapPoint;
    const priority = ['query_point', 'pfz_primary', 'fleet_recommended', 'sar_unknown_high', 'sar', 'fleet_candidate'];
    Map<String, dynamic>? pick(bool Function(String kind) matches) {
      for (final f in features) {
        final props = f['properties'] as Map<String, dynamic>?;
        final geom = f['geometry'] as Map<String, dynamic>?;
        final kind = props?['kind'] as String? ?? '';
        if (geom?['type'] == 'Point' && matches(kind)) return geom;
      }
      return null;
    }
    if (preferredKind != null) {
      final geom = pick((k) => k == preferredKind || k.startsWith(preferredKind));
      if (geom != null) {
        final coords = geom['coordinates'] as List<dynamic>;
        return [(coords[1] as num).toDouble(), (coords[0] as num).toDouble()];
      }
    }
    for (final kind in priority) {
      final geom = pick((k) => k == kind || k.startsWith(kind));
      if (geom != null) {
        final coords = geom['coordinates'] as List<dynamic>;
        return [(coords[1] as num).toDouble(), (coords[0] as num).toDouble()];
      }
    }
    // Fall back to the first available point feature.
    final geom = pick((_) => true);
    if (geom != null) {
      final coords = geom['coordinates'] as List<dynamic>;
      return [(coords[1] as num).toDouble(), (coords[0] as num).toDouble()];
    }
    return mapPoint;
  }

  // --- Chat management ---
  String createNewChat({String? agentId, String? title}) {
    final id = const Uuid().v4();
    final chat = Chat(id: id, title: title ?? 'New Conversation', createdAt: DateTime.now().millisecondsSinceEpoch, updatedAt: DateTime.now().millisecondsSinceEpoch, agentId: agentId ?? 'general', model: 'llama-3.3-70b-versatile');
    chats.insert(0, chat);
    messages[id] = [];
    activeChatId = id;
    _saveChats();
    notifyListeners();
    return id;
  }

  void selectChat(String id) {
    if (chats.any((c) => c.id == id)) {
      activeChatId = id;
      notifyListeners();
    }
  }

  void deleteChat(String id) {
    chats.removeWhere((c) => c.id == id);
    messages.remove(id);
    if (activeChatId == id) activeChatId = chats.isNotEmpty ? chats.first.id : null;
    if (chats.isEmpty) createNewChat();
    _saveChats();
    notifyListeners();
  }

  void renameChat(String id, String newTitle) {
    final c = chats.firstWhere((e) => e.id == id, orElse: () => chats.first);
    c.title = newTitle;
    c.updatedAt = DateTime.now().millisecondsSinceEpoch;
    _saveChats();
    notifyListeners();
  }

  void togglePinChat(String id) {
    final c = chats.firstWhere((e) => e.id == id);
    c.pinned = !c.pinned;
    _saveChats();
    notifyListeners();
  }

  List<Chat> get filteredChats {
    // Sorted pinned first, then by updatedAt desc
    final list = List<Chat>.from(chats);
    list.sort((a,b) {
      if (a.pinned && !b.pinned) return -1;
      if (!a.pinned && b.pinned) return 1;
      return b.updatedAt.compareTo(a.updatedAt);
    });
    return list;
  }

  List<ChatMessage> get activeMessages => activeChatId != null ? (messages[activeChatId!] ?? []) : [];

  // Search
  List<Chat> searchChats(String q) {
    if (q.isEmpty) return filteredChats;
    final lower = q.toLowerCase();
    return filteredChats.where((c) => c.title.toLowerCase().contains(lower) || (messages[c.id]?.any((m) => m.content.toLowerCase().contains(lower)) ?? false)).toList();
  }

  // --- Send message ---
  Future<void> sendQuery(String text, {List<int>? audioBytes, String? fileName}) async {
    if (text.trim().isEmpty && audioBytes == null) return;
    if (_isQuerying) return;
    // Guest limit
    if (isGuestLimitReached) {
      showToast('Guest limit reached (3 free queries). Please sign in.', 'error');
      notifyListeners();
      return;
    }
    // Ensure active chat
    String chatId = activeChatId ?? createNewChat();
    if (messages[chatId] == null) messages[chatId] = [];
    final chat = chats.firstWhere((c) => c.id == chatId);
    // User message
    final userMsg = ChatMessage(id: const Uuid().v4(), chatId: chatId, role: 'user', content: text.isNotEmpty ? text : '🎙️ voice message', timestamp: DateTime.now().millisecondsSinceEpoch);
    messages[chatId]!.add(userMsg);
    if (chat.messageCount == 0 || chat.title == 'New Conversation' || chat.title == 'Mission Briefing') {
      chat.title = text.length > 35 ? '${text.substring(0,35)}...' : text;
    }
    chat.messageCount = messages[chatId]!.length;
    chat.updatedAt = DateTime.now().millisecondsSinceEpoch;
    chat.lastMessagePreview = text.substring(0, text.length > 60 ? 60 : text.length);
    // Placeholder assistant
    final assistantId = const Uuid().v4();
    final answeringPath = queryMode == 'agent' ? '${backendAgents.firstWhere((a)=>a.key==directAgentKey, orElse:()=>backendAgents.first).name} (direct)' : queryMode == 'auto' ? 'AUTO SELECT' : 'ORCA Panel';
    final assistantMsg = ChatMessage(id: assistantId, chatId: chatId, role: 'assistant', content: '', timestamp: DateTime.now().millisecondsSinceEpoch, isStreaming: true, agentId: 'orca', modelUsed: answeringPath);
    messages[chatId]!.add(assistantMsg);
    _isQuerying = true;
    executionState = 'thinking';
    currentAction = 'Analyzing request...';
    executionSteps = [];
    _saveChats();
    notifyListeners();

    // Backend call
    QueryResponse resp;
    if (audioBytes != null && fileName != null) {
      resp = await api.voiceQuery(audioBytes: audioBytes, fileName: fileName, gps: gpsCoords, mapPoint: _mapPoint, sessionId: chatId, mode: queryMode, agent: queryMode=='agent'? directAgentKey : null);
    } else {
      resp = await api.query(text: text, gps: gpsCoords, mapPoint: _mapPoint, sessionId: chatId, mode: queryMode, agent: queryMode=='agent'? directAgentKey : null, fleetDemoLevel: fleetDemoLevel.isNotEmpty ? fleetDemoLevel : null, windDemoScenario: windDemoScenario.isNotEmpty ? windDemoScenario : null);
    }

    // If offline / error, show toast
    if (resp.answer.contains('Backend unreachable') || resp.answer.contains('Network error')) {
      showToast('Backend offline — showing cached/demo', 'error');
    }

    // Build activity steps from trace
    executionSteps = resp.trace.map((t) => AgentActivityStep(id: 'trace-${t.agentName}', title: '${t.agentName}: ${t.action}', description: t.resultSummary, status: 'completed', durationMs: t.durationMs.round(), timestamp: DateTime.now().millisecondsSinceEpoch)).toList();
    if (resp.routing != null) {
      final agents = (resp.routing!['agents'] as List<dynamic>?)?.join(' + ') ?? 'auto';
      executionSteps.add(AgentActivityStep(id: 'routing-${DateTime.now().millisecondsSinceEpoch}', title: 'Auto Router selected: $agents', description: resp.routing!['reason']?.toString(), status: 'completed', timestamp: DateTime.now().millisecondsSinceEpoch));
    }
    // Discussion steps
    for (final d in resp.discussion) {
      if (d.isConsensus) {
        executionSteps.add(AgentActivityStep(id: 'consensus-${DateTime.now().millisecondsSinceEpoch}', title: 'Round table consensus reached', description: d.consensus, status: 'completed', timestamp: DateTime.now().millisecondsSinceEpoch));
      } else {
        final icon = d.stance == 'challenge' ? '⚡' : d.stance == 'agree' ? '✅' : d.stance == 'concede' ? '🤝' : '💬';
        executionSteps.add(AgentActivityStep(id: 'disc-${DateTime.now().millisecondsSinceEpoch}-${resp.discussion.indexOf(d)}', title: '$icon ${d.speaker} → ${d.addressing ?? 'ALL'} (${d.stance ?? 'clarify'})', description: d.point, status: 'completed', timestamp: DateTime.now().millisecondsSinceEpoch));
      }
    }
    if (resp.timings != null && resp.timings!['total_ms'] != null) {
      executionSteps.add(AgentActivityStep(id: 'latency-${DateTime.now().millisecondsSinceEpoch}', title: 'ORCA completed in ${resp.timings!['total_ms']} ms', description: resp.timings!.entries.where((e)=>e.key!='total_ms').map((e)=>'${e.key}=${e.value}ms').join(', '), status: 'completed', timestamp: DateTime.now().millisecondsSinceEpoch));
    }
    if (resp.fleetConvergence != null) {
      final fc = resp.fleetConvergence!;
      executionSteps.add(AgentActivityStep(id: 'fleet-${DateTime.now().millisecondsSinceEpoch}', title: 'Fleet convergence: ${fc['status']}', description: (fc['change_reason'] ?? '').toString().substring(0, (fc['change_reason']?.toString().length ?? 0) > 120 ? 120 : fc['change_reason']?.toString().length ?? 0), status: 'completed', timestamp: DateTime.now().millisecondsSinceEpoch));
    }
    if (resp.windDivergence != null && (resp.windDivergence!['status'] == 'MODERATE_DIVERGENCE' || resp.windDivergence!['status'] == 'HIGH_DIVERGENCE')) {
      final w = resp.windDivergence!;
      executionSteps.add(AgentActivityStep(id: 'wind-${DateTime.now().millisecondsSinceEpoch}', title: 'Wind validation: ${w['status']}', description: w['warning']?.toString(), status: 'completed', timestamp: DateTime.now().millisecondsSinceEpoch));
    }

    // Fill assistant message
    final hasOfficialPfz = resp.answer.contains('🛡️ IMPORTANT');
    // We keep answer as is; web adds verdict callout but mobile will render HUD separately
    assistantMsg.content = resp.answer;
    assistantMsg.status = resp.status;
    assistantMsg.answeredBy = resp.answeredBy;
    assistantMsg.reasoning = resp.reasoning;
    assistantMsg.transcribedText = resp.transcribedText;
    assistantMsg.activitySteps = List.from(executionSteps);
    assistantMsg.autoRouting = resp.routing;
    assistantMsg.fleetConvergence = resp.fleetConvergence;
    assistantMsg.windDivergence = resp.windDivergence;
    assistantMsg.isStreaming = false;
    assistantMsg.vizSessionId = resp.sessionId ?? chatId;
    if (resp.timings != null && resp.timings!['total_ms'] != null) {
      assistantMsg.modelUsed = '${assistantMsg.modelUsed} · ${resp.timings!['total_ms']}ms';
    }

    executionState = 'completed';
    currentAction = 'Completed response';
    _isQuerying = false;
    chat.messageCount = messages[chatId]!.length;
    _saveChats();
    notifyListeners();
    // Load viz
    if (resp.sessionId != null) {
      loadViz(resp.sessionId!);
    } else {
      loadViz(chatId);
    }
    // TTS if audio feedback and voice query
    if (audioBytes != null && audioFeedback) {
      tts.speak(resp.answer, resp.language);
    }
  }

  // Wrapper for old callers
  Future<void> sendVoiceQuery(List<int> audioBytes, String fileName) async {
    await sendQuery('', audioBytes: audioBytes, fileName: fileName);
  }

  void stopGeneration() {
    _isQuerying = false;
    executionState = 'completed';
    currentAction = 'Stopped by user';
    notifyListeners();
  }

  void setLocation(double lat, double lon) {
    _lat = lat; _lon = lon; _locationGranted = true; _gpsStatus = 'granted';
    storage.saveLastPosition(lat, lon);
    notifyListeners();
  }

  void setManualLocation(double lat, double lon) {
    _lat = lat; _lon = lon;
    storage.saveLastPosition(lat, lon);
    _gpsStatus = 'cached';
    notifyListeners();
  }

  void setMapPoint(List<double>? point) {
    _mapPoint = point;
    notifyListeners();
  }

  void setQueryMode(String mode) {
    queryMode = mode;
    storage.queryMode = mode;
    notifyListeners();
  }

  void setDirectAgent(String key) {
    directAgentKey = key;
    storage.directAgent = key;
    notifyListeners();
  }

  void setFleetDemoLevel(String? level) {
    storage.fleetDemoLevel = level ?? '';
    notifyListeners();
  }

  void setWindDemoScenario(String? scenario) {
    storage.windDemoScenario = scenario ?? '';
    notifyListeners();
  }

  void setLanguage(String lang) {
    activeLanguage = lang;
    storage.language = lang;
    showToast('Language switched to $lang', 'success');
    notifyListeners();
  }

  // Auth mock
  void loginMock(String name) {
    currentUser = {'uid': const Uuid().v4(), 'displayName': name, 'email': '$name@orca.local'};
    showToast('Welcome aboard, $name!', 'success');
    notifyListeners();
  }

  void logout() {
    currentUser = null;
    userCategory = null;
    showToast('Signed out', 'info');
    notifyListeners();
  }

  void setUserCategory(UserCategoryProfile profile) {
    userCategory = profile;
    storage.vesselClass = profile.vesselClass;
    // Persist
    storage.prefs?.setString('orca_user_category', jsonEncode(profile.toJson()));
    showToast('Role set to ${profile.badgeEmoji} ${profile.roleName}', 'success');
    notifyListeners();
  }

  // Alerts
  void startAlertPolling() {
    if (_alertTimer != null) return;
    _fetchAlerts();
    _alertTimer = Timer.periodic(ApiConfig.alertPollInterval, (_) => _fetchAlerts());
  }
  void stopAlertPolling() { _alertTimer?.cancel(); _alertTimer = null; }
  void _fetchAlerts() async {
    if (storage.userId == null) return;
    final fetched = await api.fetchAlerts(storage.userId!);
    if (fetched.isNotEmpty) {
      _alerts = fetched;
      notifyListeners();
    }
  }
  void startPositionUpdates() {
    _positionTimer?.timer?.cancel();
    _positionTimer = _PositionTimer(onTick: () {
      if (storage.userId != null && _lat != null && _lon != null) {
        api.updatePosition(userId: storage.userId!, lat: _lat!, lon: _lon!);
      }
    });
    _positionTimer!.start();
  }
  void stopPositionUpdates() { _positionTimer?.cancel(); _positionTimer = null; }
  void dismissAlert(String alertId) {
    _alerts = _alerts.map((a) => a.id == alertId ? a.copyWith(dismissed: true) : a).toList();
    notifyListeners();
  }
  void clearChat() {
    if (activeChatId != null) {
      messages[activeChatId!] = [];
      final c = chats.firstWhere((e) => e.id == activeChatId);
      c.messageCount = 0;
      c.lastMessagePreview = '';
      _saveChats();
      notifyListeners();
    }
  }

  // Toast
  void showToast(String msg, String type) {
    toastMessage = msg;
    toastType = type;
    notifyListeners();
    Future.delayed(const Duration(seconds: 3), () {
      toastMessage = null;
      notifyListeners();
    });
  }

  void refresh() => notifyListeners();
  void clearToast() { toastMessage = null; notifyListeners(); }
  void setNavTab(String v) { activeNavTab = v; notifyListeners(); }

  // Visual helpers
  String getQueryModeLabel() {
    if (queryMode == 'agent') {
      final spec = backendAgents.firstWhere((a) => a.key == directAgentKey, orElse: () => backendAgents.first);
      return spec.name;
    }
    if (queryMode == 'auto') return 'AUTO SELECT';
    return 'ORCA Panel';
  }

  @override
  void dispose() {
    stopAlertPolling();
    stopPositionUpdates();
    super.dispose();
  }
}

class _PositionTimer {
  Timer? timer;
  final VoidCallback onTick;
  _PositionTimer({required this.onTick});
  void start() { timer = Timer.periodic(ApiConfig.positionUpdateInterval, (_) => onTick()); }
  void cancel() { timer?.cancel(); timer = null; }
}