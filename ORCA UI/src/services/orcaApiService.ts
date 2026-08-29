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
  localStorage.getItem('orca_backend_url') ||
  ((import.meta as any).env?.VITE_BACKEND_URL as string) ||
  'https://orca-backend-1i5u.onrender.com';

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

export interface OrcaPfzLandingCenter {
  name?: string | null;
  state?: string | null;
  sector_id?: string | null;
  sector_name?: string | null;
  direction?: string | null;
  angle_deg?: number | null;
  advisory_distance_km?: number | string | null;
  advisory_depth_m?: number | string | null;
  centre_lat?: number | null;
  centre_lon?: number | null;
  distance_km_to_centre?: number | null;
  pfz_lat?: number | null;
  pfz_lon?: number | null;
  forecast_date?: string | null;
  valid_upto?: string | null;
}

export interface OrcaPfz {
  source?: string;
  landing_center?: OrcaPfzLandingCenter | null;
  alternates?: Array<Record<string, unknown>>;
}

export interface OrcaQueryResponse {
  answer: string;
  status?: 'SAFE' | 'CAUTION' | 'UNSAFE' | 'CRITICAL' | 'INFO';
  language?: string;
  conflicts?: string[];
  reasoning?: string[];
  session_id?: string;
  trace?: OrcaTraceEntry[];
  discussion?: OrcaDiscussionTurn[];
  mode?: 'auto' | 'panel' | 'agent';
  answered_by?: string;
timings?: Record<string, number>;
  routing?: {
    intent: string;
    agents: string[];
    routing_mode: string;
    complexity: string;
    reason: string;
    confidence: number;
  };
  fleet_convergence?: {
    status: string;
    window_hours: number;
    recommendation_changed: boolean;
    change_reason: string;
    candidates: Array<{
      zone_id: string;
      center_lat: number;
      center_lon: number;
      distance_km: number;
      bearing_deg: number;
      base_suitability: number;
      fleet_count: number;
      crowding_ratio: number;
      crowding_penalty: number;
      adjusted_suitability: number;
      crowding_label?: string;
      is_recommended?: boolean;
      source?: string;
    }>;
    raw_best_zone?: any;
    final_zone?: any;
  };
  pfz?: OrcaPfz | null;
  wind_divergence?: {
    status: string;
    forecast_wind_kn: number;
    satellite_wind_kn?: number | null;
    diff_kn?: number | null;
    warning: string;
    satellite_status: string;
    satellite_source?: string;
    reasoning_note?: string;
    is_simulated: boolean;
  };
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

// ---------------------------------------------------------------------------
// Official INCOIS PFZ live layer (/api/pfz/live) -- zone lines + landing
// centres for the operations map. Cached server-side for 10 minutes.
// ---------------------------------------------------------------------------

export interface OrcaPfzLive {
  available?: string[];
  fetched_at?: string;
  forecast_date?: string | null;
  valid_upto?: string | null;
  pfz_lines?: { type: string; features: any[] } | null;
  landing_centres?: { type: string; features: any[] } | null;
  sectors?: Record<string, { name?: string | null }>;
}

export async function fetchPfzLive(): Promise<OrcaPfzLive | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/pfz/live`, {
      signal: AbortSignal.timeout(30000),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null; // backend offline or INCOIS unreachable -- map degrades silently
  }
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

    // ---- Phase 1: dispatch status ------------------------------------
    // AUTO is default — fast intelligent routing; panel only when explicitly chosen.
    const mode: 'auto' | 'panel' | 'agent' = (options.queryMode as any) || 'auto';
    const resolvedMode = mode === 'agent' ? 'agent' : mode === 'panel' ? 'panel' : 'auto';
    const modeLabel = resolvedMode === 'agent'
      ? `Dispatching directly to ${options.targetAgent || 'specialist'} agent`
      : resolvedMode === 'panel'
      ? 'Dispatching to ORCA multi-agent panel (full deliberation)'
      : 'Auto-routing — ORCA picks best specialist(s)';
    onChunk({
      type: 'activity',
      activityStep: this.step(
        'dispatch',
        options.voiceBlob
          ? 'Uploading voice message for transcription'
          : modeLabel,
        options.voiceBlob
          ? `${BACKEND_URL}/query/voice (Whisper STT)`
          : `${BACKEND_URL}/query  (mode=${resolvedMode})`,
        'in_progress'),
    });

    let data: OrcaQueryResponse;
    // Include fleet + wind demo levels if set (via options or global demo controls)
    const fleetDemoLevel = (options as any).fleetDemoLevel || OrcaApiService.getFleetDemoLevel() || null;
    const windDemoScenario = (options as any).windDemoScenario || OrcaApiService.getWindDemoScenario() || null;
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
              mode: resolvedMode,
              agent: resolvedMode === 'agent' ? options.targetAgent : undefined,
              vessel_class: options.vesselClass || 'small_fishing_boat',
              fleet_demo_level: fleetDemoLevel || undefined,
              wind_demo_scenario: windDemoScenario || undefined,
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

    // ---- Phase 2: real agent trace -> activity steps (emit immediately, no artificial delay) ---
    // Activity trace is for explainability — must NOT delay the final answer.
    // Previously this loop had sleep(60) between entries and sleep(8-18ms) per token which artificially inflated latency.
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
      if (abortSignal?.aborted) {
        onChunk({ type: 'error', error: 'Generation stopped by user.' });
        return '';
      }
    }

    // AUTO routing explainability — show which specialists were selected
    if (data.routing) {
      const agentsLabel = (data.routing.agents || []).map((a: string) => a.replace('Agent','').trim()).join(' + ') || 'auto';
      onChunk({
        type: 'activity',
        activityStep: this.step(
          `auto-routing-${Date.now()}`,
          `Auto Router selected: ${agentsLabel}`,
          `Reason: ${data.routing.reason || 'fast intent match'} (${data.routing.routing_mode}, ${data.routing.complexity}, conf ${(data.routing.confidence||0).toFixed(2)})`,
          'completed',
        ),
      });
    }

    // Latency telemetry (if backend provided)
    if (data.timings && typeof (data.timings as any).total_ms === 'number') {
      const total = (data.timings as any).total_ms;
      const breakdown = Object.entries(data.timings).filter(([k])=>k!=='total_ms').map(([k,v])=>`${k}=${v}ms`).join(', ');
      onChunk({
        type: 'activity',
        activityStep: this.step(
          `latency-${Date.now()}`,
          `ORCA completed in ${total} ms`,
          breakdown || undefined,
          'completed',
        ),
      });
    }

    // Fleet Convergence — crowding-adjusted recommendation
    if ((data as any).fleet_convergence) {
      const fc = (data as any).fleet_convergence;
      const status = fc.status || 'OK';
      const changed = fc.recommendation_changed;
      const candidates = fc.candidates || [];
      const simLabel = status.startsWith('SIMULATED') ? ' [DEMO — SIMULATED FLEET ACTIVITY]' : '';
      if (status === 'UNAVAILABLE') {
        onChunk({
          type: 'activity',
          activityStep: this.step(
            `fleet-${Date.now()}`,
            'Fleet convergence unavailable — showing raw suitability',
            fc.reason || 'No fleet data',
            'completed',
          ),
        });
      } else {
        const summary = candidates.map((c: any) => `${c.zone_id}: base ${c.base_suitability} fleet ${c.fleet_count} adj ${c.adjusted_suitability} ${c.crowding_label||''}`).join(' | ').slice(0, 180);
        onChunk({
          type: 'activity',
          activityStep: this.step(
            `fleet-${Date.now()}`,
            changed ? `Fleet convergence: ${fc.raw_best_zone?.zone_id} → ${fc.final_zone?.zone_id}${simLabel}` : `Fleet checked: ${fc.final_zone?.zone_id || 'no change'}${simLabel}`,
            summary || fc.change_reason || `Status ${status}, ${candidates.length} zones`,
            'completed',
          ),
        });
      }
    }

    // Wind Validation (Satellite-Model Wind Divergence Flag) - only surface
    // an activity step when there's something to flag, so a normal MATCH or
    // UNAVAILABLE check doesn't clutter the fisherman's activity feed.
    if ((data as any).wind_divergence) {
      const wdv: any = (data as any).wind_divergence;
      if (wdv.status === 'MODERATE_DIVERGENCE' || wdv.status === 'HIGH_DIVERGENCE') {
        const simLabel = wdv.is_simulated ? ' [DEMO - SIMULATED SATELLITE DATA]' : ' [REAL SATELLITE DATA]';
        const diffTxt = (wdv.diff_kn !== null && wdv.diff_kn !== undefined) ? `${wdv.diff_kn >= 0 ? '+' : ''}${wdv.diff_kn}kn` : 'n/a';
        onChunk({
          type: 'activity',
          activityStep: this.step(
            `wind-${Date.now()}`,
            `Wind validation: ${wdv.status.replace('_', ' ')}${simLabel}`,
            `Forecast ${wdv.forecast_wind_kn}kn vs satellite ${wdv.satellite_wind_kn}kn (${diffTxt}) - ${wdv.warning}`,
            'completed',
          ),
        });
      }
    }

    // ---- Phase 2b: round-table discussion -> activity steps (only when present; no delay) ------------
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
      if (abortSignal?.aborted) {
        onChunk({ type: 'error', error: 'Generation stopped by user.' });
        return '';
      }
    }

    // ---- Phase 3: verdict callout — render immediately (no fake per-token sleep) ---------
    // When the backend returned the official INCOIS PFZ template it already
    // carries its own IMPORTANT/VERDICT header + quick summary, so skip the
    // generic callout and the appended card to avoid duplication.
    const hasOfficialPfzTemplate = data.answer.includes('🛡️ IMPORTANT');
    const verdict = STATUS_CALLOUT[data.status || ''] ||
      `⚪ VERDICT: ${(data.status || 'info').toUpperCase()}`;
    const fullText = hasOfficialPfzTemplate
      ? `${data.answer}`
      : `> [!IMPORTANT]\n> ${verdict}\n\n${data.answer}${this.pfzCardMarkdown(data.pfz)}`;

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

    // Immediate rendering: emit full response as one token (no artificial streaming delay).
    // The backend already spent time on live data + LLM; we must not add fake latency.
    // If you want streaming, implement true SSE backend streaming, not sleep().
    let streamed = fullText;
    onChunk({ type: 'token', content: fullText });
    // Propagate structured status/routing/fleet to the message model so HUD uses authoritative backend status, not text parsing fallback.
    onChunk({
      type: 'done',
      content: fullText,
      // @ts-ignore — extended done chunk carries structured fields for appState to set on the Message
      status: data.status,
      routing: data.routing,
      timings: data.timings,
      fleetConvergence: (data as any).fleet_convergence,
      windDivergence: (data as any).wind_divergence,
      tokens: {
        promptTokens: Math.ceil(prompt.length / 4),
        completionTokens: Math.ceil(fullText.length / 4),
        totalTokens: Math.ceil((prompt.length + fullText.length) / 4),
      },
    } as any);

    if (options.speakReply) {
      OrcaApiService.speak(fullText, data.language);
    }
    return streamed;
  }

  /** Compact "Official INCOIS PFZ" card appended under the answer when the
   * backend resolved the query against the live advisory (landing centre +
   * issued direction/distance/depth). Uses markdown the renderer supports. */
  private pfzCardMarkdown(pfz?: OrcaPfz | null): string {
    const lc = pfz?.landing_center;
    if (!lc?.name) return '';
    const rows: Array<[string, string]> = [
      ['Landing centre', `${lc.name}${lc.state ? `, ${lc.state}` : ''}`],
      ['Sector', `${lc.sector_id ?? ''}${lc.sector_name ? ` — ${lc.sector_name}` : ''}`],
      ['Zone direction', lc.direction ? String(lc.direction) : ''],
      ['Distance offshore', lc.advisory_distance_km != null ? `${lc.advisory_distance_km} km` : ''],
      ['Depth', lc.advisory_depth_m != null ? `${lc.advisory_depth_m} m` : ''],
      ['Valid until', lc.valid_upto ?? ''],
      ['Zone position',
        lc.pfz_lat != null && lc.pfz_lon != null ? `${lc.pfz_lat}, ${lc.pfz_lon}` : ''],
    ].filter(([, v]) => v !== '' && v != null) as Array<[string, string]>;

    const source = (pfz?.source || 'incois_live').replace(/_/g, ' ').toUpperCase();
    return `\n\n> **🎣 OFFICIAL PFZ ADVISORY** · ${source}\n> \n` +
      rows.map(([k, v]) => `> **${k}:** ${v}`).join('\n') + '\n';
  }

  /** Multipart voice query -> STT -> same graph -> same payload shape. */
  private async postVoiceQuery(options: SendMessageOptions): Promise<OrcaQueryResponse> {
    const form = new FormData();
    form.append('audio', options.voiceBlob!, 'speech.webm');
    if (options.chatId) form.append('session_id', options.chatId);
    const mode = (options.queryMode as any) || 'auto';
    if (mode === 'agent' && options.targetAgent) {
      form.append('mode', 'agent');
      form.append('agent', options.targetAgent);
    } else if (mode === 'panel') {
      form.append('mode', 'panel');
    } else {
      form.append('mode', 'auto');
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
    kok: 'kok-IN', tcy: 'tcy-IN',
    kfr: 'sd-IN',  // Kutchi -> Sindhi (closest available)
    byr: 'ml-IN',  // Beary -> Malayalam (closest available)
    mvv: 'mr-IN',  // Malvani -> Marathi (closest available)
    ncr: 'hi-IN',  // Nicobarese -> Hindi (generic fallback)
    adm: 'hi-IN',  // Andamanese -> Hindi (generic fallback)
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

  public static fleetDemoLevel: string | null = null;
  public static windDemoScenario: string | null = null;

  /** Fleet Convergence — set demo level for next query (low/medium/high/severe) */
  public static setFleetDemoLevel(level: string | null): void {
    OrcaApiService.fleetDemoLevel = level;
    if (level) localStorage.setItem('orca_fleet_demo_level', level);
    else localStorage.removeItem('orca_fleet_demo_level');
  }
  public static getFleetDemoLevel(): string | null {
    return OrcaApiService.fleetDemoLevel || localStorage.getItem('orca_fleet_demo_level');
  }
  public static setWindDemoScenario(scenario: string | null): void {
    OrcaApiService.windDemoScenario = scenario;
    if (scenario) localStorage.setItem('orca_wind_demo_scenario', scenario);
    else localStorage.removeItem('orca_wind_demo_scenario');
  }
  public static getWindDemoScenario(): string | null {
    return OrcaApiService.windDemoScenario || localStorage.getItem('orca_wind_demo_scenario');
  }
  public static async simulateFleet(level: string, lat?: number, lon?: number, sessionId?: string): Promise<any> {
    const body: any = { level };
    if (lat != null && lon != null) { body.lat = lat; body.lon = lon; }
    if (sessionId) body.session_id = sessionId;
    return fetch(`${BACKEND_URL}/fleet/simulate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => { if (!r.ok) throw new Error(`fleet simulate ${r.status}`); return r.json(); });
  }
  public static async clearFleet(simulatedOnly: boolean = true): Promise<any> {
    return fetch(`${BACKEND_URL}/fleet/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ simulated_only: simulatedOnly }),
    }).then(r => r.json());
  }
  public static async getFleetStatus(): Promise<any> {
    return fetch(`${BACKEND_URL}/fleet/status`).then(r => r.json());
  }
  public static async getSatelliteWindStatus(): Promise<any> {
    return fetch(`${BACKEND_URL}/satellite-wind/status`).then(r => r.json());
  }
  public static async getSatelliteWindDivergence(lat: number, lon: number, scenario?: string): Promise<any> {
    const qs = new URLSearchParams({ lat: String(lat), lon: String(lon) });
    if (scenario) qs.set('demo_scenario', scenario);
    return fetch(`${BACKEND_URL}/satellite-wind/divergence?${qs}`).then(r => r.json());
  }

  public static cachedGps: [number, number] | null = null;

  /** Acquire live browser GPS coordinates for high-precision local forecasting */
  public static async acquireLiveGps(): Promise<[number, number] | null> {
    if (!('geolocation' in navigator)) return null;
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          OrcaApiService.cachedGps = [pos.coords.latitude, pos.coords.longitude];
          localStorage.setItem('orca_device_gps', JSON.stringify(OrcaApiService.cachedGps));
          resolve(OrcaApiService.cachedGps);
        },
        () => {
          const fallback = OrcaApiService.demoGps();
          resolve(fallback as [number, number] | null);
        },
        { enableHighAccuracy: true, timeout: 6000, maximumAge: 60000 }
      );
    });
  }

  /** Live device GPS or cached position for local sea-state forecasting */
  public static demoGps(): number[] | null {
    if (OrcaApiService.cachedGps) return OrcaApiService.cachedGps;
    const raw = localStorage.getItem('orca_device_gps') || localStorage.getItem('orca_demo_gps');
    return raw ? JSON.parse(raw) : null;
  }

  // -------------------------------------------------------------------------
  // SAR Boundary Surveillance (Innovation #3)
  // -------------------------------------------------------------------------
  public static async getSarStatus(): Promise<any> {
    return fetch(`${BACKEND_URL}/sar/status`, { signal: AbortSignal.timeout(5000) }).then(r => {
      if (!r.ok) throw new Error(`sar/status ${r.status}`);
      return r.json();
    });
  }
  public static async getSarDetections(): Promise<any> {
    return fetch(`${BACKEND_URL}/sar/detections`, { signal: AbortSignal.timeout(8000) }).then(r => {
      if (!r.ok) throw new Error(`sar/detections ${r.status}`);
      return r.json();
    });
  }
  public static async runSarScan(opts: { provider?: string; area?: any; useCache?: boolean } = {}): Promise<any> {
    return fetch(`${BACKEND_URL}/sar/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: opts.provider || 'demo',
        area: opts.area || null,
        use_cache: opts.useCache ?? false,
      }),
      signal: AbortSignal.timeout(10000),
    }).then(r => {
      if (!r.ok) throw new Error(`sar/scan ${r.status}`);
      return r.json();
    });
  }
  public static async runSarDemo(): Promise<any> {
    return fetch(`${BACKEND_URL}/sar/demo`, { method: 'POST', signal: AbortSignal.timeout(10000) }).then(r => {
      if (!r.ok) throw new Error(`sar/demo ${r.status}`);
      return r.json();
    });
  }
  public static async clearSar(): Promise<any> {
    return fetch(`${BACKEND_URL}/sar/clear`, { method: 'POST', signal: AbortSignal.timeout(4000) }).then(r => r.json());
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
