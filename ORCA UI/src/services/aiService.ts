import { AgentActivityStep } from '../types/agent';
import { Attachment } from '../types/message';

export interface StreamChunk {
  type: 'activity' | 'token' | 'done' | 'error';
  content?: string;
  activityStep?: AgentActivityStep;
  error?: string;
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
  /** 'panel' = all agents discuss (default); 'agent' = one specialist directly. */
  queryMode?: 'panel' | 'agent';
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
