import { IAIService, SendMessageOptions, StreamChunk } from './aiService';
import { AgentActivityStep } from '../types/agent';

/**
 * Real ORCA backend service -- replaces the mock AI with calls to the
 * FastAPI multi-agent backend (default http://localhost:8000).
 *
 * The backend answers in one payload (not token-streamed), so we simulate
 * streaming client-side while the real agent trace feeds the activity panel.
 */

export const BACKEND_URL: string =
  localStorage.getItem('orca_backend_url') || 'http://localhost:8000';

export interface OrcaTraceEntry {
  agent_name: string;
  action: string;
  result_summary: string;
  duration_ms: number;
}

export interface OrcaDiscussionTurn {
  speaker: string;
  addressing?: string | null;
  stance?: 'challenge' | 'clarify' | 'agree' | 'concede';
  point: string;
  consensus?: string;
}

export interface OrcaSpecialist {
  key: string;
  name: string;
  description: string;
  requires: string[];
}

export interface OrcaQueryResponse {
  answer: string;
  status?: 'SAFE' | 'CAUTION' | 'UNSAFE' | 'INFO';
  language?: string;
  conflicts?: string[];
  reasoning?: string[];
  session_id?: string;
  trace?: OrcaTraceEntry[];
  discussion?: OrcaDiscussionTurn[];
  mode?: 'panel' | 'agent';
  answered_by?: string;
}

/** Addressable specialists for direct-agent queries (backend registry). */
export async function fetchOrcaAgents(): Promise<OrcaSpecialist[]> {
  const res = await fetch(`${BACKEND_URL}/agents`, {
    signal: AbortSignal.timeout(4000),
  });
  if (!res.ok) throw new Error(`ORCA backend /agents -> HTTP ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

// ---------------------------------------------------------------------------
// Visualisation payloads (/viz/{session}, /viz/{session}/series)
// ---------------------------------------------------------------------------

export interface OrcaTideExtreme {
  kind: string;
  time_local: string;
  height_m: number;
}

export interface OrcaExceedanceWindow {
  metric: string;
  threshold: number;
  unit: string;
  start: string;
  end: string;
  peak: number;
}

export interface OrcaVizSeries {
  series: {
    times: string[];
    wave_height_m: number[];
    wind_gust_kmh: number[];
  };
  exceedance_windows: OrcaExceedanceWindow[];
  tides: OrcaTideExtreme[];
}

export function fetchVizGeojson(sessionId: string): Promise<any> {
  return fetch(`${BACKEND_URL}/viz/${sessionId}`, {
    signal: AbortSignal.timeout(8000),
  }).then((res) => {
    if (!res.ok) throw new Error(`/viz -> HTTP ${res.status}`);
    return res.json();
  });
}

export function fetchVizSeries(sessionId: string): Promise<OrcaVizSeries> {
  return fetch(`${BACKEND_URL}/viz/${sessionId}/series`, {
    signal: AbortSignal.timeout(8000),
  }).then((res) => {
    if (!res.ok) throw new Error(`/viz/series -> HTTP ${res.status}`);
    return res.json();
  });
}

const STATUS_CALLOUT: Record<string, string> = {
  SAFE: '🟢 **VERDICT: SAFE** — conditions within safe thresholds',
  CAUTION: '🟠 **VERDICT: CAUTION** — borderline conditions, proceed carefully',
  UNSAFE: '🔴 **VERDICT: UNSAFE** — hazardous conditions, do not venture out',
};

export class OrcaApiService implements IAIService {
  private static instance: OrcaApiService;

  public static getInstance(): OrcaApiService {
    if (!OrcaApiService.instance) {
      OrcaApiService.instance = new OrcaApiService();
    }
    return OrcaApiService.instance;
  }

  public async generateTitle(firstMessage: string): Promise<string> {
    const cleaned = firstMessage.trim().replace(/^[^a-zA-Z0-9\u0900-\u097F]+/, '');
    if (cleaned.length < 30) {
      return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
    }
    const words = cleaned.split(/\s+/).slice(0, 5).join(' ');
    return words.charAt(0).toUpperCase() + words.slice(1) + '...';
  }

  private async fetchJson(path: string, init?: RequestInit): Promise<any> {
    const res = await fetch(`${BACKEND_URL}${path}`, init);
    if (!res.ok) {
      throw new Error(`ORCA backend ${path} -> HTTP ${res.status}`);
    }
    return res.json();
  }

  public async sendMessage(options: SendMessageOptions): Promise<string> {
    const { chatId, prompt, onChunk, abortSignal } = options;

    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

    // ---- Phase 1: dispatch status ------------------------------------
    const mode = options.queryMode === 'agent' ? 'agent' : 'panel';
    onChunk({
      type: 'activity',
      activityStep: this.step(
        'dispatch',
        options.voiceBlob
          ? 'Uploading voice message for transcription'
          : mode === 'agent'
            ? `Dispatching directly to ${options.targetAgent || 'specialist'} agent`
            : 'Dispatching to ORCA multi-agent panel',
        options.voiceBlob
          ? `${BACKEND_URL}/query/voice (Whisper STT)`
          : `${BACKEND_URL}/query  (mode=${mode})`,
        'in_progress'),
    });

    let data: OrcaQueryResponse;
    try {
      data = options.voiceBlob
        ? await this.postVoiceQuery(options)
        : await this.fetchJson('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              query: prompt,
              session_id: chatId,
              device_gps: OrcaApiService.demoGps(),
              mode,
              agent: mode === 'agent' ? options.targetAgent : undefined,
            }),
          });
    } catch (err: any) {
      onChunk({
        type: 'error',
        error: `Backend unreachable at ${BACKEND_URL}. Start it with: uvicorn main:app --port 8000`,
      });
      return '';
    }

    if (abortSignal?.aborted) {
      onChunk({ type: 'error', error: 'Generation stopped by user.' });
      return '';
    }

    // ---- Phase 2: real agent trace -> activity steps ------------------
    const steps = data.trace || [];
    for (let i = 0; i < steps.length; i++) {
      const t = steps[i];
      const step: AgentActivityStep = {
        id: `trace-${i}`,
        title: `${t.agent_name}: ${t.action}`.slice(0, 90),
        description: t.result_summary?.slice(0, 140),
        status: 'completed',
        durationMs: Math.round(t.duration_ms || 0),
        timestamp: Date.now(),
      };
      onChunk({ type: 'activity', activityStep: step });
      await sleep(60); // let the UI breathe between entries
      if (abortSignal?.aborted) {
        onChunk({ type: 'error', error: 'Generation stopped by user.' });
        return '';
      }
    }

    // ---- Phase 2b: round-table discussion -> activity steps ------------
    const STANCE_ICON: Record<string, string> = {
      challenge: '\u26a1', clarify: '\u2139\ufe0f', agree: '\u2705', concede: '\ud83e\udd1d',
    };
    for (const t of data.discussion || []) {
      if ((t as any).consensus) {
        onChunk({
          type: 'activity',
          activityStep: this.step(
            `debate-consensus-${Date.now()}`,
            'Round table consensus reached',
            (t as any).consensus,
            'completed',
          ),
        });
      } else {
        onChunk({
          type: 'activity',
          activityStep: this.step(
            `debate-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            `${STANCE_ICON[t.stance || ''] || '\ud83d\udcac'} ${t.speaker} \u2192 ${t.addressing || 'ALL'} (${t.stance || 'clarify'})`,
            t.point,
            'completed',
          ),
        });
      }
      await sleep(60);
      if (abortSignal?.aborted) {
        onChunk({ type: 'error', error: 'Generation stopped by user.' });
        return '';
      }
    }

    // ---- Phase 3: verdict callout + simulated token streaming ---------
    const verdict = STATUS_CALLOUT[data.status || ''] ||
      `⚪ VERDICT: ${(data.status || 'info').toUpperCase()}`;
    const fullText = `> [!IMPORTANT]\n> ${verdict}\n\n${data.answer}`;

    if (options.voiceBlob && (data as any).transcribed_text) {
      onChunk({
        type: 'activity',
        activityStep: this.step(
          'stt-transcript',
          'Heard you say',
          `"${(data as any).transcribed_text}"`,
          'completed',
        ),
      });
    }

    const chunks = fullText.match(/(\s+|[^\s\w]+|\w+)/g) || [fullText];
    let streamed = '';
    for (const chunk of chunks) {
      if (abortSignal?.aborted) break;
      streamed += chunk;
      onChunk({ type: 'token', content: chunk });
      await sleep(8 + Math.random() * 10);
    }

    onChunk({
      type: 'done',
      tokens: {
        promptTokens: Math.ceil(prompt.length / 4),
        completionTokens: Math.ceil(fullText.length / 4),
        totalTokens:
          Math.ceil((prompt.length + fullText.length) / 4),
      },
    });
    if (options.speakReply) {
      OrcaApiService.speak(fullText, data.language);
    }
    return streamed;
  }

  /** Multipart voice query -> STT -> same graph -> same payload shape. */
  private async postVoiceQuery(options: SendMessageOptions): Promise<OrcaQueryResponse> {
    const form = new FormData();
    form.append('audio', options.voiceBlob!, 'speech.webm');
    if (options.chatId) form.append('session_id', options.chatId);
    if (options.queryMode === 'agent' && options.targetAgent) {
      form.append('mode', 'agent');
      form.append('agent', options.targetAgent);
    }
    const res = await fetch(`${BACKEND_URL}/query/voice`, {
      method: 'POST',
      body: form,
      signal: options.abortSignal,
    });
    if (!res.ok) {
      throw new Error(`ORCA backend /query/voice -> HTTP ${res.status}`);
    }
    return res.json();
  }

  private static LANG_TAGS: Record<string, string> = {
    en: 'en-IN', hi: 'hi-IN', mr: 'mr-IN', ta: 'ta-IN', te: 'te-IN',
    bn: 'bn-IN', ml: 'ml-IN', kn: 'kn-IN', gu: 'gu-IN', or: 'or-IN',
    pa: 'pa-IN',
  };

  /** Browser speech synthesis of the final answer (PS Sec 17 TTS leg). */
  public static speak(markdownText: string, language?: string): void {
    if (!('speechSynthesis' in window)) return;
    const clean = markdownText
      .split('\n')
      .filter((l) => !l.trim().startsWith('>'))   // drop the verdict callout
      .join(' ')
      .replace(/[*_#`]|^\s*-\s/gm, '')
      .replace(/\s+/g, ' ')
      .trim();
    if (!clean) return;
    const u = new SpeechSynthesisUtterance(clean.slice(0, 600));
    u.lang = OrcaApiService.LANG_TAGS[language || 'en'] || 'en-IN';
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }

  public static stopSpeaking(): void {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }

  private step(id: string, title: string, desc?: string,
               status: AgentActivityStep['status'] = 'completed'): AgentActivityStep {
    return { id, title, description: desc, status, timestamp: Date.now() };
  }

  /** Optional demo GPS so route/geofence intents work from the browser. */
  public static demoGps(): number[] | null {
    const raw = localStorage.getItem('orca_demo_gps');
    return raw ? JSON.parse(raw) : null;
  }

  /** Proactive alerts: register the browser as a monitorable user and
   * stream server-pushed safety alerts over SSE. */
  public static startAlertStream(
    userId: string,
    lat: number,
    lon: number,
    onAlert: (alert: any) => void,
  ): void {
    fetch(`${BACKEND_URL}/users/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId, lat, lon,
        name: 'Web Officer', language: 'en',
        location_name: 'Monitored position',
      }),
    }).catch(() => console.warn('[ORCA] alert registration failed'));

    const es = new EventSource(`${BACKEND_URL}/alerts/stream/${userId}`);
    es.onmessage = (ev) => {
      try {
        onAlert(JSON.parse(ev.data));
      } catch {
        /* keep-alive comments */
      }
    };
    es.onerror = () => console.warn('[ORCA] alert stream disconnected');
  }
}
