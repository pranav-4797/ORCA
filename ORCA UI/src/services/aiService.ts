import { AgentActivityStep } from '../types/agent';
import { Attachment } from '../types/message';

export interface StreamChunk {
  type: 'activity' | 'token' | 'done' | 'error';
  content?: string;
  activityStep?: AgentActivityStep;
  error?: string;
  status?: 'SAFE' | 'CAUTION' | 'UNSAFE' | 'CRITICAL' | 'INFO';
  routing?: { intent: string; agents: string[]; routing_mode: string; complexity: string; reason: string; confidence: number };
  timings?: Record<string, number>;
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
