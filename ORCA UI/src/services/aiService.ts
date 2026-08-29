import { AgentActivityStep } from '../types/agent';
import { Attachment } from '../types/message';

export interface FleetCandidate {
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
}

export interface FleetConvergence {
  status: string;
  window_hours: number;
  recommendation_changed: boolean;
  change_reason: string;
  candidates: FleetCandidate[];
  raw_best_zone?: FleetCandidate | null;
  final_zone?: FleetCandidate | null;
}

export interface StreamChunk {
  type: 'activity' | 'token' | 'done' | 'error';
  content?: string;
  activityStep?: AgentActivityStep;
  error?: string;
  status?: 'SAFE' | 'CAUTION' | 'UNSAFE' | 'CRITICAL' | 'INFO';
  routing?: { intent: string; agents: string[]; routing_mode: string; complexity: string; reason: string; confidence: number };
  timings?: Record<string, number>;
  fleetConvergence?: FleetConvergence;
  tokens?: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
}

export interface SendMessageOptions {
  chatId: string;
  prompt: string;
  agentId: string;
  model: string;
  temperature?: number;
  attachments?: Attachment[];
  /** 'auto' = ORCA picks best specialist(s) (default), 'panel' = full deliberation demo, 'agent' = one specialist directly. */
  queryMode?: 'auto' | 'panel' | 'agent';
  /** Specialist key for queryMode='agent' (see backend GET /agents). */
  targetAgent?: string;
  /** Fleet demo level for convergence forecast: low/medium/high/severe */
  fleetDemoLevel?: string | null;
  /** Wind divergence demo scenario: match/moderate/high_divergence (SIMULATED) */
  windDemoScenario?: string | null;
  /** When set, the prompt is carried as mic audio -> /query/voice (STT). */
  voiceBlob?: Blob;
  /** Speak the finished answer via browser TTS (voice-originated replies). */
  speakReply?: boolean;
  onChunk: (chunk: StreamChunk) => void;
  abortSignal?: AbortSignal;
}

export interface IAIService {
  sendMessage(options: SendMessageOptions): Promise<string>;
  generateTitle(firstMessage: string): Promise<string>;
}
