class Chat {
  final String id;
  String title;
  final int createdAt;
  int updatedAt;
  String agentId;
  String model;
  int messageCount;
  String? lastMessagePreview;
  bool pinned;

  Chat({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    required this.agentId,
    required this.model,
    this.messageCount = 0,
    this.lastMessagePreview,
    this.pinned = false,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'createdAt': createdAt,
        'updatedAt': updatedAt,
        'agentId': agentId,
        'model': model,
        'messageCount': messageCount,
        'lastMessagePreview': lastMessagePreview,
        'pinned': pinned,
      };

  factory Chat.fromJson(Map<String, dynamic> j) => Chat(
        id: j['id'] as String,
        title: j['title'] as String,
        createdAt: j['createdAt'] as int,
        updatedAt: j['updatedAt'] as int,
        agentId: j['agentId'] as String? ?? 'general',
        model: j['model'] as String? ?? 'llama-3.3-70b-versatile',
        messageCount: j['messageCount'] as int? ?? 0,
        lastMessagePreview: j['lastMessagePreview'] as String?,
        pinned: j['pinned'] as bool? ?? false,
      );
}
