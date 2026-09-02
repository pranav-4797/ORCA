class AgentTraceEntry {
  final String agentName;
  final String action;
  final String resultSummary;
  final double durationMs;
  final List<String> dataSources;

  AgentTraceEntry({
    required this.agentName,
    required this.action,
    required this.resultSummary,
    required this.durationMs,
    this.dataSources = const [],
  });

  factory AgentTraceEntry.fromJson(Map<String, dynamic> j) => AgentTraceEntry(
        agentName: j['agent_name'] as String? ?? '',
        action: j['action'] as String? ?? '',
        resultSummary: j['result_summary'] as String? ?? '',
        durationMs: (j['duration_ms'] as num?)?.toDouble() ?? 0,
        dataSources: (j['data_sources'] as List<dynamic>?)
                ?.map((e) => e.toString())
                .toList() ??
            [],
      );
}

class DiscussionTurn {
  final String speaker;
  final String? addressing;
  final String? stance;
  final String point;
  final String? consensus;

  DiscussionTurn({
    required this.speaker,
    this.addressing,
    this.stance,
    required this.point,
    this.consensus,
  });

  factory DiscussionTurn.fromJson(Map<String, dynamic> j) {
    if (j.containsKey('consensus')) {
      return DiscussionTurn(
        speaker: 'consensus',
        point: j['consensus'] as String? ?? '',
        consensus: j['consensus'] as String?,
      );
    }
    return DiscussionTurn(
      speaker: j['speaker'] as String? ?? '',
      addressing: j['addressing'] as String?,
      stance: j['stance'] as String?,
      point: j['point'] as String? ?? '',
    );
  }

  bool get isConsensus => consensus != null;
}

class QueryResponse {
  final String answer;
  final String status;
  final List<String> reasoning;
  final String language;
  final double confidenceScore;
  final String mode;
  final String answeredBy;
  final String? transcribedText;
  final String? sessionId;

  // Extended OrchestratorResponse fields
  final List<AgentTraceEntry> trace;
  final List<DiscussionTurn> discussion;
  final List<String> conflicts;
  final Map<String, dynamic>? oceanState;
  final Map<String, dynamic>? risk;
  final Map<String, dynamic>? geofence;
  final Map<String, dynamic>? pfz;
  final Map<String, dynamic>? route;
  final Map<String, dynamic>? trend;
  final Map<String, dynamic>? timings;
  final Map<String, dynamic>? routing;
  final Map<String, dynamic>? fleetConvergence;
  final Map<String, dynamic>? windDivergence;
  final List<Map<String, dynamic>> evidenceTiers;
  final List<String> evidenceSources;
  final List<Map<String, dynamic>> avoidZones;

  QueryResponse({
    required this.answer,
    required this.status,
    this.reasoning = const [],
    this.language = 'en',
    this.confidenceScore = 0.0,
    this.mode = 'auto',
    this.answeredBy = '',
    this.transcribedText,
    this.sessionId,
    this.trace = const [],
    this.discussion = const [],
    this.conflicts = const [],
    this.oceanState,
    this.risk,
    this.geofence,
    this.pfz,
    this.route,
    this.trend,
    this.timings,
    this.routing,
    this.fleetConvergence,
    this.windDivergence,
    this.evidenceTiers = const [],
    this.evidenceSources = const [],
    this.avoidZones = const [],
  });

  factory QueryResponse.fromJson(Map<String, dynamic> json) {
    final traceList = (json['trace'] as List<dynamic>?)
            ?.map((e) => AgentTraceEntry.fromJson(e as Map<String, dynamic>))
            .toList() ??
        [];
    final discussionList =
        (json['discussion'] as List<dynamic>?)?.map((e) {
              if (e is Map<String, dynamic>) return DiscussionTurn.fromJson(e);
              return DiscussionTurn(speaker: e.toString(), point: e.toString());
            }).toList() ??
            [];
    return QueryResponse(
      answer: json['answer'] as String? ?? '',
      status: json['status'] as String? ?? 'UNKNOWN',
      reasoning: (json['reasoning'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          [],
      language: json['language'] as String? ?? 'en',
      confidenceScore: (json['confidence_score'] as num?)?.toDouble() ?? 0.0,
      mode: json['mode'] as String? ?? 'auto',
      answeredBy: json['answered_by'] as String? ?? '',
      transcribedText: json['transcribed_text'] as String?,
      sessionId: json['session_id'] as String?,
      trace: traceList,
      discussion: discussionList,
      conflicts: (json['conflicts'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          [],
      oceanState: json['ocean_state'] as Map<String, dynamic>?,
      risk: json['risk'] as Map<String, dynamic>?,
      geofence: json['geofence'] as Map<String, dynamic>?,
      pfz: json['pfz'] as Map<String, dynamic>?,
      route: json['route'] as Map<String, dynamic>?,
      trend: json['trend'] as Map<String, dynamic>?,
      timings: json['timings'] as Map<String, dynamic>?,
      routing: json['routing'] as Map<String, dynamic>?,
      fleetConvergence: json['fleet_convergence'] as Map<String, dynamic>?,
      windDivergence: json['wind_divergence'] as Map<String, dynamic>?,
      evidenceTiers: (json['evidence_tiers'] as List<dynamic>?)
              ?.map((e) => e as Map<String, dynamic>)
              .toList() ??
          [],
      evidenceSources: (json['evidence_sources'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          [],
      avoidZones: (json['avoid_zones'] as List<dynamic>?)
              ?.map((e) => e as Map<String, dynamic>)
              .toList() ??
          [],
    );
  }

  Map<String, dynamic> toJson() => {
        'answer': answer,
        'status': status,
        'reasoning': reasoning,
        'language': language,
        'confidence_score': confidenceScore,
        'mode': mode,
        'answered_by': answeredBy,
        if (transcribedText != null) 'transcribed_text': transcribedText,
        if (sessionId != null) 'session_id': sessionId,
      };
}
