import 'package:flutter_tts/flutter_tts.dart';

class TtsService {
  final FlutterTts _tts = FlutterTts();
  bool _enabled = true;

  static const Map<String, String> langTags = {
    'en': 'en-IN',
    'hi': 'hi-IN',
    'mr': 'mr-IN',
    'ta': 'ta-IN',
    'te': 'te-IN',
    'bn': 'bn-IN',
    'ml': 'ml-IN',
    'kn': 'kn-IN',
    'gu': 'gu-IN',
    'or': 'or-IN',
  };

  Future<void> init() async {
    await _tts.setSpeechRate(0.45);
    await _tts.setPitch(1.0);
  }

  void setEnabled(bool v) => _enabled = v;

  Future<void> speak(String markdown, String language) async {
    if (!_enabled) return;
    final clean = markdown
        .split('\n')
        .where((l) => !l.trim().startsWith('>'))
        .join(' ')
        .replaceAll(RegExp(r'[*_#`]|^\s*-\s', multiLine: true), '')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    if (clean.isEmpty) return;
    await _tts.setLanguage(langTags[language] ?? 'en-IN');
    await _tts.stop();
    await _tts.speak(clean.substring(0, clean.length > 600 ? 600 : clean.length));
  }

  Future<void> stop() async => _tts.stop();
}
